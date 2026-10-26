"""System monitoring: host metrics, service health and virtualization readiness."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import require_permission
from ..models import Node, Task, VPS
from ..services.metrics import host_metrics
from ..virtualization.capabilities import detect_capabilities

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


@router.get("/host")
def host(db: Session = Depends(get_db), user=Depends(require_permission("monitoring:read"))):
    metrics = host_metrics()
    metrics["active_vps"] = db.query(VPS).filter(VPS.status == "running").count()
    metrics["queued_tasks"] = db.query(Task).filter(Task.status == "queued").count()
    return metrics


@router.get("/health")
def service_health(db: Session = Depends(get_db), user=Depends(require_permission("monitoring:read"))):
    services = []
    try:
        db.execute(text("SELECT 1"))
        services.append({"name": "postgresql" if not settings.is_sqlite else "sqlite", "status": "connected"})
    except Exception as exc:  # noqa: BLE001
        services.append({"name": "database", "status": "error", "detail": str(exc)})

    caps = detect_capabilities()
    services.append(
        {
            "name": "kvm",
            "status": "ready" if caps.kvm_available else "not_configured",
            "detail": caps.kvm_reason,
        }
    )
    services.append(
        {
            "name": "libvirt",
            "status": "ready" if caps.libvirt_python and caps.libvirtd_running else "not_configured",
            "detail": {
                "python_binding": caps.libvirt_python,
                "daemon_socket": caps.libvirtd_running,
                "qemu": caps.qemu_installed,
            },
        }
    )
    services.append({"name": "worker", "status": "running", "detail": "embedded or bluekvm-worker"})
    return {
        "services": services,
        "capabilities": caps.to_dict(),
        "nodes": [
            {
                "id": n.id,
                "name": n.name,
                "status": n.status.value,
                "kvm_ready": n.kvm_ready,
                "last_error": n.last_error,
                "last_health_at": n.last_health_at,
            }
            for n in db.query(Node).all()
        ],
    }
