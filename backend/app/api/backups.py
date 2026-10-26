"""Backup and snapshot management API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..database import get_db
from ..deps import can_access_vps, client_ip, require_permission
from ..models import Backup, Task, VPS
from ..schemas import BackupOut, Message
from ..services.audit import record_audit

router = APIRouter(prefix="/api/backups", tags=["backups"])


def _queue(db: Session, task_type: str, vps_id: int, key: str) -> Task:
    existing = db.query(Task).filter(Task.idempotency_key == key).first()
    if existing:
        return existing
    task = Task(task_type=task_type, vps_id=vps_id, idempotency_key=key)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.get("", response_model=list[BackupOut])
def list_backups(
    vps_id: int | None = None,
    db=Depends(get_db),
    user=Depends(require_permission("backup:read")),
):
    query = db.query(Backup)
    if vps_id is not None:
        query = query.filter(Backup.vps_id == vps_id)
    return query.order_by(Backup.created_at.desc()).limit(200).all()


@router.post("/vps/{public_id}", status_code=201)
def create_backup(
    public_id: str,
    request: Request,
    backup_type: str = Query("backup", pattern="^(backup|snapshot)$"),
    note: str = Query("", max_length=255),
    db=Depends(get_db),
    user=Depends(require_permission("backup:manage")),
):
    vps = db.query(VPS).filter(VPS.public_id == public_id).first()
    if not vps:
        raise HTTPException(404, "VPS not found")
    if not can_access_vps(request, user, vps):
        raise HTTPException(403, "Not authorized for this VPS")
    task_type = "create_backup" if backup_type == "backup" else "create_snapshot"
    task = _queue(db, task_type, vps.id, key=f"{task_type}-{vps.id}-{note or 'manual'}")
    record_audit(db, action=f"backup.{backup_type}", user_id=user.id, resource_type="vps",
                 resource_id=vps.public_id, ip_address=client_ip(request),
                 details={"task_id": task.id, "note": note})
    return {"message": f"{backup_type.capitalize()} job queued", "task_id": task.id}


@router.post("/{backup_id}/restore", response_model=Message)
def restore_backup(
    backup_id: int,
    request: Request,
    db=Depends(get_db),
    user=Depends(require_permission("backup:manage")),
):
    backup = db.get(Backup, backup_id)
    if not backup or backup.backup_type != "backup":
        raise HTTPException(404, "Restorable backup not found")
    vps = db.get(VPS, backup.vps_id)
    if not vps or not can_access_vps(request, user, vps):
        raise HTTPException(403, "Not authorized")
    task = _queue(db, "restore_backup", vps.id, key=f"restore-{backup.id}")
    record_audit(db, action="backup.restore", user_id=user.id, resource_type="backup",
                 resource_id=str(backup.id), ip_address=client_ip(request),
                 details={"vps": vps.public_id, "task_id": task.id})
    return Message(message=f"Restore queued (task {task.id})")


@router.delete("/{backup_id}", response_model=Message)
def delete_backup(
    backup_id: int,
    request: Request,
    db=Depends(get_db),
    user=Depends(require_permission("backup:manage")),
):
    backup = db.get(Backup, backup_id)
    if not backup:
        raise HTTPException(404, "Backup not found")
    vps = db.get(VPS, backup.vps_id)
    if vps and not can_access_vps(request, user, vps):
        raise HTTPException(403, "Not authorized")
    task = _queue(db, "delete_backup", backup.vps_id, key=f"delete-backup-{backup.id}")
    record_audit(db, action="backup.delete", user_id=user.id, resource_type="backup",
                 resource_id=str(backup.id), ip_address=client_ip(request))
    return Message(message=f"Backup deletion queued (task {task.id})")
