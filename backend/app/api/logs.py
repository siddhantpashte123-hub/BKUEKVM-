"""Audit log and task inspection endpoints."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_permission
from ..models import AuditLog, Task
from ..schemas import AuditOut, TaskOut

router = APIRouter(tags=["logs"])


@router.get("/api/audit-logs", response_model=list[AuditOut])
def audit_logs(
    db: Session = Depends(get_db),
    user=Depends(require_permission("audit:read")),
    limit: int = 100,
    action: str | None = None,
):
    limit = min(max(limit, 1), 500)
    query = db.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action.ilike(f"%{action}%"))
    return query.order_by(AuditLog.created_at.desc()).limit(limit).all()


@router.get("/api/tasks", response_model=list[TaskOut])
def list_tasks(
    db: Session = Depends(get_db),
    user=Depends(require_permission("vps:read")),
    vps_id: int | None = None,
    limit: int = 100,
):
    limit = min(max(limit, 1), 500)
    query = db.query(Task)
    if vps_id is not None:
        query = query.filter(Task.vps_id == vps_id)
    tasks = query.order_by(Task.created_at.desc()).limit(limit).all()
    result = []
    for task in tasks:
        out = TaskOut.model_validate(task)
        out.steps = json.loads(task.steps or "[]")
        result.append(out)
    return result


@router.get("/api/tasks/{task_id}", response_model=TaskOut)
def get_task(
    task_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_permission("vps:read")),
):
    task = db.get(Task, task_id)
    if not task:
        from fastapi import HTTPException

        raise HTTPException(404, "Task not found")
    out = TaskOut.model_validate(task)
    out.steps = json.loads(task.steps or "[]")
    return out
