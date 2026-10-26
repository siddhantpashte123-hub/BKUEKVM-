"""Virtualization node registration and health management."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import client_ip, require_permission
from ..models import Node, NodeStatus, VPS, VPSStatus
from ..schemas import Message, NodeCreate, NodeOut, NodeUpdate
from ..security import encrypt_secret
from ..services.audit import record_audit
from ..virtualization.capabilities import detect_capabilities
from ..virtualization.manager import manager

router = APIRouter(prefix="/api/nodes", tags=["nodes"])


def _serialize(node: Node) -> dict:
    data = NodeOut.model_validate(node).model_dump()
    data["vm_count"] = len([v for v in node.vps_instances if v.status != VPSStatus.DELETED])
    try:
        data["capabilities"] = json.loads(node.capabilities or "{}")
    except json.JSONDecodeError:
        data["capabilities"] = {}
    return data


@router.get("")
def list_nodes(db: Session = Depends(get_db), user=Depends(require_permission("node:read"))):
    return [_serialize(n) for n in db.query(Node).order_by(Node.id).all()]


@router.post("", status_code=201)
def register_node(
    payload: NodeCreate,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("node:manage")),
):
    if db.query(Node).filter(Node.name == payload.name).first():
        raise HTTPException(409, f"Node name '{payload.name}' already exists")
    node = Node(
        name=payload.name,
        address=payload.address,
        libvirt_uri=payload.libvirt_uri,
        credential_encrypted=encrypt_secret(payload.credential) if payload.credential else None,
        is_local=payload.is_local,
        status=NodeStatus.UNCONFIGURED,
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    record_audit(db, action="node.register", user_id=user.id, resource_type="node",
                 resource_id=node.name, ip_address=client_ip(request))
    manager.health_check(db, node)
    return _serialize(node)


@router.get("/capabilities")
def host_capabilities(user=Depends(require_permission("node:read"))):
    return detect_capabilities().to_dict()


@router.post("/{node_id}/health-check")
def health_check(
    node_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("node:manage")),
):
    node = db.get(Node, node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    manager.invalidate(node.id)
    manager.health_check(db, node)
    record_audit(db, action="node.health_check", user_id=user.id, resource_type="node",
                 resource_id=node.name, ip_address=client_ip(request))
    return _serialize(node)


@router.patch("/{node_id}")
def update_node(
    node_id: int,
    payload: NodeUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("node:manage")),
):
    node = db.get(Node, node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    if payload.name:
        node.name = payload.name
    if payload.address:
        node.address = payload.address
    if payload.status:
        try:
            node.status = NodeStatus(payload.status)
        except ValueError:
            raise HTTPException(400, f"Invalid status: {payload.status}")
    db.commit()
    record_audit(db, action="node.update", user_id=user.id, resource_type="node",
                 resource_id=node.name, ip_address=client_ip(request),
                 details={"status": node.status.value})
    return _serialize(node)


@router.delete("/{node_id}", response_model=Message)
def remove_node(
    node_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("node:manage")),
):
    node = db.get(Node, node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    active = db.query(VPS).filter(VPS.node_id == node_id, VPS.status != VPSStatus.DELETED).count()
    if active:
        raise HTTPException(409, f"Node still hosts {active} VPS instance(s); migrate them first")
    manager.invalidate(node.id)
    name = node.name
    db.delete(node)
    db.commit()
    record_audit(db, action="node.remove", user_id=user.id, resource_type="node",
                 resource_id=name, ip_address=client_ip(request))
    return Message(message="Node removed")
