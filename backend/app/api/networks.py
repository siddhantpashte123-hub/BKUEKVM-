"""Network management (read-mostly; host networking is never auto-modified)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..database import get_db
from ..deps import require_permission
from ..models import IPAllocation, Network, VPS
from ..schemas import NetworkOut

router = APIRouter(prefix="/api/networks", tags=["networks"])


@router.get("", response_model=list[NetworkOut])
def list_networks(db=Depends(get_db), user=Depends(require_permission("network:read"))):
    return db.query(Network).order_by(Network.name).all()


@router.get("/{network_id}/allocations")
def allocations(
    network_id: int,
    db=Depends(get_db),
    user=Depends(require_permission("network:read")),
):
    network = db.get(Network, network_id)
    if not network:
        raise HTTPException(404, "Network not found")
    rows = db.query(IPAllocation).filter(IPAllocation.network_id == network_id).all()
    return [
        {
            "id": a.id,
            "address": a.address,
            "mac_address": a.mac_address,
            "allocation_type": a.allocation_type,
            "vps_id": a.vps_id,
            "vps_name": db.get(VPS, a.vps_id).name if a.vps_id else None,
        }
        for a in rows
    ]
