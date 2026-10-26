"""Backup and snapshot workflows.

A libvirt *snapshot* is a qcow2 delta tied to the running domain; an
independent *backup* is a full, verified disk copy under the backup
directory. A backup is only marked successful after the output file is
verified on disk.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Backup, Task, VPS
from ..virtualization.manager import manager


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _qemu_img() -> str:
    binary = shutil.which("qemu-img")
    if not binary:
        raise RuntimeError("qemu-img is not installed on this host")
    return binary


def _verify_image(path: Path) -> int:
    result = subprocess.run(
        [_qemu_img(), "info", str(path)], capture_output=True, text=True, timeout=120, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(f"Backup verification failed: {result.stderr.strip()}")
    size = path.stat().st_size
    if size <= 0:
        raise RuntimeError("Backup verification failed: output file is empty")
    return size


def run_backup_task(db: Session, task: Task, driver_manager) -> None:
    vps = db.get(VPS, task.vps_id) if task.vps_id else None
    if not vps:
        raise RuntimeError("Backup task has no associated VPS")
    driver = driver_manager.get_driver(vps.node)

    if task.task_type == "create_snapshot":
        name = f"snap-{vps.name}-{int(time.time())}"
        snapshot = driver.create_snapshot(vps.name, name)
        record = Backup(
            vps_id=vps.id, backup_type="snapshot", status="ready",
            snapshot_name=snapshot, note=task.steps[:0] or "",
        )
        db.add(record)
        db.commit()
        task.steps = __import__("json").dumps(
            [{"name": "snapshot", "status": "succeeded", "detail": snapshot}]
        )
        return

    if task.task_type == "create_backup":
        backup_root = Path(settings.backup_dir) / vps.name
        backup_root.mkdir(parents=True, exist_ok=True)
        output = backup_root / f"{vps.name}-{int(time.time())}.qcow2"
        record = Backup(vps_id=vps.id, backup_type="backup", status="running", path=str(output))
        db.add(record)
        db.commit()

        disk_path = Path(settings.vm_storage_dir) / vps.name / "disk.qcow2"
        if not disk_path.exists():
            record.status = "failed"
            record.error = f"source disk missing: {disk_path}"
            record.finished_at = _utcnow()
            db.commit()
            raise RuntimeError(record.error)

        result = subprocess.run(
            [_qemu_img(), "convert", "-O", "qcow2", "-c", str(disk_path), str(output)],
            capture_output=True, text=True, timeout=3600, check=False,
        )
        if result.returncode != 0:
            record.status = "failed"
            record.error = result.stderr.strip()
            record.finished_at = _utcnow()
            db.commit()
            raise RuntimeError(f"qemu-img convert failed: {record.error}")

        # Success is only recorded after real verification
        record.size_bytes = _verify_image(output)
        record.status = "ready"
        record.finished_at = _utcnow()
        db.commit()
        _apply_retention(db, vps.id)
        task.steps = __import__("json").dumps(
            [{"name": "backup", "status": "succeeded", "detail": str(output)}]
        )
        return

    if task.task_type == "restore_backup":
        backup = db.get(Backup, int(task.idempotency_key)) if task.idempotency_key else None
        if not backup or backup.status != "ready" or not Path(backup.path).exists():
            raise RuntimeError("Backup record is missing or not verified")
        driver.power_off(vps.name)
        disk_path = Path(settings.vm_storage_dir) / vps.name / "disk.qcow2"
        disk_path.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [_qemu_img(), "convert", "-O", "qcow2", backup.path, str(disk_path)],
            capture_output=True, text=True, timeout=3600, check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Restore failed: {result.stderr.strip()}")
        driver.start(vps.name)
        return

    if task.task_type == "delete_backup":
        backup = db.get(Backup, int(task.idempotency_key)) if task.idempotency_key else None
        if not backup:
            return
        if backup.backup_type == "backup" and backup.path:
            Path(backup.path).unlink(missing_ok=True)
        else:
            try:
                driver.delete_snapshot(vps.name, backup.snapshot_name)
            except Exception:
                pass
        db.delete(backup)
        db.commit()


def _apply_retention(db: Session, vps_id: int, keep: int = 7) -> None:
    backups = (
        db.query(Backup)
        .filter(Backup.vps_id == vps_id, Backup.backup_type == "backup", Backup.status == "ready")
        .order_by(Backup.created_at.desc())
        .all()
    )
    for stale in backups[keep:]:
        if stale.path:
            Path(stale.path).unlink(missing_ok=True)
        db.delete(stale)
    db.commit()
