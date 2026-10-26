"""Dashboard aggregation: real counts, live host metrics and recent activity."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, scoped_vps_query
from ..models import AuditLog, Node, Task, VPS, VPSStatus
from ..services.metrics import cpu_timeseries, host_metrics

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary")
def summary(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    base = scoped_vps_query(request, db, user)
    rows = (
        base.with_entities(VPS.status, func.count(VPS.id))
        .group_by(VPS.status)
        .all()
    )
    by_status = {status.value: count for status, count in rows}
    return {
        "vps_total": sum(by_status.values()),
        "vps_running": by_status.get(VPSStatus.RUNNING.value, 0),
        "vps_stopped": by_status.get(VPSStatus.STOPPED.value, 0),
        "vps_provisioning": by_status.get(VPSStatus.PROVISIONING.value, 0)
        + by_status.get(VPSStatus.PENDING.value, 0),
        "vps_error": by_status.get(VPSStatus.ERROR.value, 0),
        "nodes_total": db.query(Node).count(),
        "nodes_online": db.query(Node).filter(Node.status == "online").count(),
        "tasks_running": db.query(Task).filter(Task.status == "running").count(),
        "tasks_queued": db.query(Task).filter(Task.status == "queued").count(),
    }


@router.get("/metrics")
def metrics(db: Session = Depends(get_db), user=Depends(get_current_user)):
    host = host_metrics()
    host["timeseries"] = cpu_timeseries(60)
    return host


@router.get("/activity")
def activity(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    limit: int = 10,
):
    limit = min(max(limit, 1), 50)
    logs = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).all()
    tasks = (
        db.query(Task).order_by(Task.created_at.desc()).limit(limit).all()
    )
    return {
        "audit": [
            {
                "id": a.id,
                "action": a.action,
                "resource_type": a.resource_type,
                "resource_id": a.resource_id,
                "user_id": a.user_id,
                "created_at": a.created_at,
            }
            for a in logs
        ],
        "tasks": [
            {
                "id": t.id,
                "task_type": t.task_type,
                "status": t.status.value if hasattr(t.status, "value") else t.status,
                "progress": t.progress,
                "vps_id": t.vps_id,
                "created_at": t.created_at,
            }
            for t in tasks
        ],
    }
