"""VPS provisioning and lifecycle workflows.

Every long-running operation is represented by a durable Task row with
timestamped steps and logs. The worker claims queued tasks atomically so
duplicate submissions and worker restarts never double-provision a VM.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    Backup,
    IPAllocation,
    Task,
    TaskStatus,
    TemplateStatus,
    VPS,
    VPSStatus,
)
from ..security import decrypt_secret
from ..virtualization.base import HypervisorError, KVMUnavailableError, VMSpec
from ..virtualization.manager import manager
from .template_service import ensure_ready

log = logging.getLogger("bluekvm.provision")
WORKER_ID = f"worker-{os.getpid()}-{threading.get_ident()}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- task IO --
def _load_steps(task: Task) -> list[dict]:
    try:
        return json.loads(task.steps or "[]")
    except json.JSONDecodeError:
        return []


def add_step(task: Task, name: str, status: str = "running", detail: str = "") -> None:
    steps = _load_steps(task)
    for step in reversed(steps):
        if step["name"] == name and step["status"] == "running":
            step["status"] = status
            step["finished_at"] = utcnow().isoformat()
            if detail:
                step["detail"] = detail
            break
    else:
        steps.append(
            {
                "name": name,
                "status": status,
                "detail": detail,
                "started_at": utcnow().isoformat(),
                "finished_at": utcnow().isoformat() if status != "running" else None,
            }
        )
    task.steps = json.dumps(steps)


def append_log(task: Task, message: str) -> None:
    line = f"[{utcnow().isoformat()}] {message}\n"
    task.logs = (task.logs or "") + line
    log.info("task %s: %s", task.id, message)


def set_progress(task: Task, percent: int) -> None:
    task.progress = max(0, min(100, percent))


def claim_next_task(db: Session) -> Task | None:
    """Atomically claim the oldest queued task (works with Postgres and SQLite)."""
    task = db.query(Task).filter(Task.status == TaskStatus.QUEUED).order_by(Task.id).first()
    if not task:
        return None
    claimed = (
        db.query(Task)
        .filter(Task.id == task.id, Task.status == TaskStatus.QUEUED)
        .update({Task.status: TaskStatus.RUNNING, Task.claimed_by: WORKER_ID, Task.started_at: utcnow()})
    )
    db.commit()
    if not claimed:
        return None
    db.refresh(task)
    return task


# ------------------------------------------------------------- dispatchers --
def run_task(db: Session, task: Task) -> None:
    append_log(task, f"Starting task {task.task_type} (id={task.id})")
    try:
        if task.task_type == "create_vps":
            _provision_vps(db, task)
        elif task.task_type == "delete_vps":
            _delete_vps(db, task)
        elif task.task_type in ("start_vps", "stop_vps", "shutdown_vps", "restart_vps"):
            _lifecycle(db, task)
        elif task.task_type == "reinstall_vps":
            _reinstall(db, task)
        elif task.task_type in ("create_backup", "create_snapshot", "restore_backup", "delete_backup"):
            from .backups import run_backup_task

            run_backup_task(db, task, manager)
        else:
            raise HypervisorError(f"Unknown task type: {task.task_type}")
        if task.status != TaskStatus.FAILED:
            task.status = TaskStatus.SUCCEEDED
            set_progress(task, 100)
            task.finished_at = utcnow()
            add_step(task, "completed", "succeeded")
            append_log(task, "Task completed successfully")
    except (KVMUnavailableError, HypervisorError, RuntimeError, ValueError) as exc:
        _fail_task(db, task, exc)
    except Exception as exc:  # noqa: BLE001 - worker must never die silently
        log.exception("Unhandled error in task %s", task.id)
        _fail_task(db, task, exc)
    finally:
        db.commit()


def _fail_task(db: Session, task: Task, exc: Exception) -> None:
    task.status = TaskStatus.FAILED
    task.error = f"{type(exc).__name__}: {exc}"
    task.finished_at = utcnow()
    add_step(task, "failed", "failed", detail=str(exc))
    append_log(task, f"ERROR: {task.error}")
    if task.vps_id:
        vps = db.get(VPS, task.vps_id)
        if vps and vps.status == VPSStatus.PROVISIONING:
            vps.status = VPSStatus.ERROR
            vps.last_error = task.error
            db.commit()


# ------------------------------------------------------------- provisioning --
def _provision_vps(db: Session, task: Task) -> None:
    vps = db.get(VPS, task.vps_id)
    if not vps:
        raise HypervisorError("VPS record no longer exists")
    vps.status = VPSStatus.PROVISIONING
    vps.last_error = ""
    db.commit()

    add_step(task, "reserve_resources", "running")
    node = manager.find_placement(db, vps.vcpus, vps.ram_mb, vps.disk_gb, node_id=vps.node_id)
    vps.node_id = node.id
    db.commit()
    driver = manager.get_driver(node)
    add_step(task, "reserve_resources", "succeeded", f"node={node.name}")
    set_progress(task, 10)
    append_log(task, f"Resources reserved on node '{node.name}'")

    add_step(task, "validate_template", "running")
    template = vps.template
    ensure_ready(template)
    add_step(task, "validate_template", "succeeded", template.name)
    set_progress(task, 20)

    add_step(task, "create_disk", "running")
    # Decrypt the VM credential only here, inside the worker, for the
    # cloud-init seed — it never crosses the API boundary.
    cloud_password = ""
    if vps.init_password_encrypted:
        try:
            cloud_password = decrypt_secret(vps.init_password_encrypted)
        except ValueError:
            cloud_password = ""
    spec = VMSpec(
        name=vps.name,
        hostname=vps.hostname,
        vcpus=vps.vcpus,
        ram_mb=vps.ram_mb,
        disk_gb=vps.disk_gb,
        base_image_path=template.image_path,
        libvirt_network=settings.default_network,
        bridge=settings.default_bridge,
        ssh_public_key=vps.ssh_public_key,
        cloud_init_user=vps.cloud_init_user or "ubuntu",
        cloud_init_password=cloud_password,
        storage_dir=settings.vm_storage_dir if node.is_local else f"{settings.vm_storage_dir}/node-{node.id}",
        mac_address=vps.mac_address,
    )
    info = driver.define_vm(spec)
    vps.libvirt_uuid = info.uuid
    vps.mac_address = info.metadata.get("mac_address", vps.mac_address)
    db.commit()
    add_step(task, "create_disk", "succeeded", info.metadata.get("disk_path", ""))
    set_progress(task, 55)
    append_log(task, f"Domain defined with libvirt UUID {info.uuid}")

    add_step(task, "configure_cloud_init", "succeeded", "NoCloud seed ISO attached")
    add_step(task, "configure_networking", "succeeded", f"mac={vps.mac_address}")
    set_progress(task, 70)

    add_step(task, "start_vm", "running")
    driver.start(vps.name)
    add_step(task, "start_vm", "succeeded")
    set_progress(task, 80)

    add_step(task, "verify_state", "running")
    verified = manager.sync_vps_state(vps, driver)
    db.commit()
    if verified.status != VPSStatus.RUNNING:
        raise HypervisorError(
            f"VM was created but did not reach running state (power={vps.power_state}). "
            "Check the guest console and task logs."
        )
    add_step(task, "verify_state", "succeeded", f"power_state={vps.power_state}")
    append_log(task, f"VPS '{vps.name}' is running")
    set_progress(task, 95)

    if vps.network_id and not vps.ip_address:
        allocation = (
            db.query(IPAllocation)
            .filter(IPAllocation.network_id == vps.network_id, IPAllocation.vps_id.is_(None))
            .first()
        )
        if allocation:
            allocation.vps_id = vps.id
            vps.ip_address = allocation.address
            db.commit()


def _delete_vps(db: Session, task: Task) -> None:
    vps = db.get(VPS, task.vps_id)
    if not vps:
        add_step(task, "delete", "succeeded", "record already removed")
        return
    vps.status = VPSStatus.DELETING
    db.commit()
    add_step(task, "stop_and_undefine", "running")
    try:
        driver = manager.get_driver(vps.node)
        driver.delete(vps.name, purge_disks=True)
        add_step(task, "stop_and_undefine", "succeeded")
    except HypervisorError as exc:
        append_log(task, f"Hypervisor delete warning: {exc}")
        add_step(task, "stop_and_undefine", "succeeded", "domain absent; continuing")

    if vps.network_id:
        alloc = db.query(IPAllocation).filter_by(vps_id=vps.id).first()
        if alloc:
            alloc.vps_id = None
    vps.status = VPSStatus.DELETED
    vps.power_state = "undefined"
    db.commit()
    append_log(task, f"VPS '{vps.name}' deleted; metadata retained for audit")


def _lifecycle(db: Session, task: Task) -> None:
    vps = db.get(VPS, task.vps_id)
    if not vps or vps.status == VPSStatus.DELETED:
        raise HypervisorError("VPS does not exist or has been deleted")
    driver = manager.get_driver(vps.node)
    action = task.task_type.replace("_vps", "")
    add_step(task, action, "running")
    if action == "start":
        driver.start(vps.name)
    elif action == "stop":
        driver.power_off(vps.name)
    elif action == "shutdown":
        driver.shutdown(vps.name)
    elif action == "restart":
        driver.restart(vps.name)
    manager.sync_vps_state(vps, driver)
    db.commit()
    add_step(task, action, "succeeded", f"power_state={vps.power_state}")
    append_log(task, f"{action} completed; state={vps.status.value}")


def _reinstall(db: Session, task: Task) -> None:
    vps = db.get(VPS, task.vps_id)
    if not vps:
        raise HypervisorError("VPS does not exist")
    add_step(task, "reinstall", "running", "recreating domain from verified template")
    driver = manager.get_driver(vps.node)
    driver.delete(vps.name, purge_disks=True)
    append_log(task, "Existing domain and disks removed")
    _provision_vps(db, task)
