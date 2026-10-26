"""Unauthenticated health endpoints for load balancers and the installer."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import __version__
from ..database import get_db
from ..virtualization.capabilities import detect_capabilities

router = APIRouter(tags=["health"])


@router.get("/health/live")
def liveness():
    return {"status": "alive", "version": __version__}


@router.get("/health/ready")
def readiness(db: Session = Depends(get_db)):
    checks = {"api": "ok", "version": __version__}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "connected"
    except Exception as exc:  # noqa: BLE001
        checks["database"] = f"error: {type(exc).__name__}"
    caps = detect_capabilities()
    checks["kvm"] = "ready" if caps.kvm_available else "unavailable"
    checks["kvm_reason"] = caps.kvm_reason
    overall = "ready" if checks["database"] == "connected" else "degraded"
    return {"status": overall, "checks": checks}
