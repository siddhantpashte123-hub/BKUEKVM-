"""Storage pool inventory."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..database import get_db
from ..deps import require_permission
from ..models import StoragePool, VPS
from ..schemas import StoragePoolOut

router = APIRouter(prefix="/api/storage", tags=["storage"])


@router.get("/pools", response_model=list[StoragePoolOut])
def list_pools(db=Depends(get_db), user=Depends(require_permission("storage:read"))):
    return db.query(StoragePool).order_by(StoragePool.name).all()


@router.get("/allocations")
def disk_allocations(db=Depends(get_db), user=Depends(require_permission("storage:read"))):
    rows = (
        db.query(VPS)
        .filter(VPS.status != "deleted")
        .order_by(VPS.disk_gb.desc())
        .all()
    )
    return [
        {
            "vps_id": v.public_id,
            "vps_name": v.name,
            "disk_gb": v.disk_gb,
            "node_id": v.node_id,
        }
        for v in rows
    ]
