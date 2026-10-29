"""VPS instance management API — every action is backed by real workflows."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import (
    can_access_vps,
    client_ip,
    require_permission,
    scoped_vps_query,
)
from ..models import (
    ConsoleSession,
    Node,
    OSNodeTemplate,
    Task,
    TaskStatus,
    TemplateStatus,
    VPS,
    VPSStatus,
)
from ..schemas import (
    ConsoleSessionOut,
    GuestIpOut,
    SshxSessionOut,
    LifecycleRequest,
    Message,
    TaskOut,
    VPSCreate,
    VPSDetailOut,
    VPSOut,
)
from ..security import (
    console_expiry,
    decrypt_secret,
    encrypt_secret,
    generate_password,
    generate_token,
    hash_token,
)
from ..services.audit import record_audit
from ..services.sshx_sessions import SshxSessionError, sshx_sessions
from ..virtualization.manager import manager

router = APIRouter(prefix="/api/vps", tags=["vps"])


# --------------------------------------------------------------- helpers --
def _serialize(vps: VPS, stats: dict | None = None, generated_password: str | None = None) -> VPSDetailOut:
    data = {c.name: getattr(vps, c.name) for c in vps.__table__.columns}
    data["status"] = vps.status.value if hasattr(vps.status, "value") else vps.status
    data["node_name"] = vps.node.name if vps.node else ""
    data["template_name"] = vps.template.name if vps.template else ""
    data["stats"] = stats
    data["has_password"] = bool(vps.init_password_encrypted)
    # Never serialize the ciphertext; the transient generated value is only
    # ever present on the single create response that mints it.
    data.pop("init_password_encrypted", None)
    data["generated_password"] = generated_password
    return VPSDetailOut(**data)


def _get_visible(request: Request, db: Session, user, public_id: str) -> VPS:
    vps = db.query(VPS).filter(VPS.public_id == public_id).first()
    if not vps or vps.status == VPSStatus.DELETED:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "VPS not found")
    if not can_access_vps(request, user, vps):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This VPS is not assigned to you")
    return vps


def _queue_task(db: Session, task_type: str, vps_id: int, idempotency_key: str | None = None) -> Task:
    if idempotency_key:
        existing = db.query(Task).filter(Task.idempotency_key == idempotency_key).first()
        if existing:
            return existing
    task = Task(task_type=task_type, vps_id=vps_id, idempotency_key=idempotency_key)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


# ----------------------------------------------------------------- routes --
@router.get("", response_model=dict)
def list_vps(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("vps:read")),
    search: str = "",
    status_filter: str | None = Query(None, alias="status"),
    os_filter: str | None = Query(None, alias="os"),
    sort: str = "-created_at",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    query = scoped_vps_query(request, db, user)
    if search:
        like = f"%{search}%"
        query = query.filter(or_(VPS.name.ilike(like), VPS.hostname.ilike(like), VPS.ip_address.ilike(like)))
    if status_filter:
        try:
            query = query.filter(VPS.status == VPSStatus(status_filter))
        except ValueError:
            raise HTTPException(400, f"Unknown status filter: {status_filter}")
    if os_filter:
        query = query.join(OSNodeTemplate).filter(OSNodeTemplate.os_family == os_filter)

    sort_column = {
        "created_at": VPS.created_at, "-created_at": VPS.created_at.desc(),
        "name": VPS.name, "-name": VPS.name.desc(),
        "status": VPS.status, "-status": VPS.status.desc(),
    }.get(sort, VPS.created_at.desc())
    query = query.order_by(sort_column)
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": [_serialize(v).model_dump() for v in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


@router.post("", response_model=VPSDetailOut, status_code=201)
def create_vps(
    payload: VPSCreate,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("vps:manage")),
):
    # Duplicate-submission protection
    if payload.idempotency_key:
        existing = db.query(VPS).filter(VPS.idempotency_key == payload.idempotency_key).first()
        if existing:
            return _serialize(existing)
    if db.query(VPS).filter(VPS.name == payload.name).first():
        raise HTTPException(status.HTTP_409_CONFLICT, f"VPS name '{payload.name}' is already in use")

    template = db.get(OSNodeTemplate, payload.template_id)
    if not template:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "OS template not found")
    if template.status != TemplateStatus.READY:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Template '{template.name}' is not ready (status={template.status.value}). "
            "Download it from OS Templates first.",
        )

    node = None
    if payload.node_id is not None:
        node = db.get(Node, payload.node_id)
        if not node:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found")
        if not node.kvm_ready or node.status.value != "online":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Node '{node.name}' cannot run VMs: {node.last_error or 'KVM not ready'}",
            )
        manager.find_placement(db, payload.vcpus, payload.ram_mb, payload.disk_gb, node.id)
    else:
        # Fail fast with an honest message when no node can host the VM
        node = manager.find_placement(db, payload.vcpus, payload.ram_mb, payload.disk_gb)

    # Credentials: an explicit wizard password wins; otherwise generate a
    # strong random one and hand it back exactly once in this response.
    generated_password = ""
    plain_password = payload.cloud_init_password.strip()
    if not plain_password:
        plain_password = generate_password()
        generated_password = plain_password

    vps = VPS(
        name=payload.name,
        hostname=payload.hostname,
        description=payload.description,
        owner_id=payload.owner_id or user.id,
        node_id=node.id,
        template_id=template.id,
        vcpus=payload.vcpus,
        ram_mb=payload.ram_mb,
        disk_gb=payload.disk_gb,
        network_id=payload.network_id,
        ip_address=payload.ip_address,
        mac_address=payload.mac_address,
        ssh_public_key=payload.ssh_public_key.strip(),
        cloud_init_user="ubuntu",
        init_password_encrypted=encrypt_secret(plain_password),
        expires_at=payload.expires_at,
        idempotency_key=payload.idempotency_key,
        status=VPSStatus.PENDING,
    )
    db.add(vps)
    db.commit()
    db.refresh(vps)
    _queue_task(db, "create_vps", vps.id, idempotency_key=payload.idempotency_key)
    record_audit(
        db, action="vps.create", user_id=user.id, resource_type="vps",
        resource_id=vps.public_id, ip_address=client_ip(request),
        details={"name": vps.name, "vcpus": vps.vcpus, "ram_mb": vps.ram_mb, "disk_gb": vps.disk_gb},
    )
    return _serialize(vps, generated_password=generated_password or None)


@router.get("/{public_id}", response_model=VPSDetailOut)
def get_vps(
    public_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("vps:read")),
):
    return _serialize(_get_visible(request, db, user, public_id))


@router.get("/{public_id}/stats")
def vps_stats(
    public_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("vps:read")),
):
    vps = _get_visible(request, db, user, public_id)
    if vps.status in (VPSStatus.PENDING, VPSStatus.PROVISIONING, VPSStatus.DELETED):
        return {"available": False, "reason": f"VM is {vps.status.value}"}
    try:
        driver = manager.get_driver(vps.node)
        stats = driver.get_stats(vps.name)
        return {**stats.__dict__, "available": stats.available}
    except Exception as exc:  # noqa: BLE001 - metrics must not break the page
        return {"available": False, "reason": str(exc)}


@router.post("/{public_id}/actions/{action}", response_model=Message)
def lifecycle(
    public_id: str,
    action: str,
    payload: LifecycleRequest,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("vps:manage")),
):
    action_map = {
        "start": "start_vps", "stop": "stop_vps",
        "shutdown": "shutdown_vps", "restart": "restart_vps",
    }
    if action not in action_map:
        raise HTTPException(400, f"Unsupported action: {action}")
    vps = _get_visible(request, db, user, public_id)
    if vps.status in (VPSStatus.PROVISIONING, VPSStatus.DELETING, VPSStatus.PENDING):
        raise HTTPException(409, f"Cannot {action} a VPS that is {vps.status.value}")
    task = _queue_task(db, action_map[action], vps.id)
    record_audit(db, action=f"vps.{action}", user_id=user.id, resource_type="vps",
                 resource_id=vps.public_id, ip_address=client_ip(request),
                 details={"reason": payload.reason, "task_id": task.id})
    return Message(message=f"{action.capitalize()} queued (task {task.id})")


@router.post("/{public_id}/reinstall", response_model=Message)
def reinstall(
    public_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("vps:manage")),
):
    vps = _get_visible(request, db, user, public_id)
    task = _queue_task(db, "reinstall_vps", vps.id)
    record_audit(db, action="vps.reinstall", user_id=user.id, resource_type="vps",
                 resource_id=vps.public_id, ip_address=client_ip(request),
                 details={"task_id": task.id})
    return Message(message=f"Reinstall queued (task {task.id}). The existing disk will be replaced.")


@router.delete("/{public_id}", response_model=Message)
def delete_vps(
    public_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("vps:manage")),
    confirm: str = Query(..., description="Must equal the VPS name"),
):
    vps = _get_visible(request, db, user, public_id)
    if confirm != vps.name:
        raise HTTPException(400, "Confirmation must equal the VPS name")
    task = _queue_task(db, "delete_vps", vps.id)
    record_audit(db, action="vps.delete", user_id=user.id, resource_type="vps",
                 resource_id=vps.public_id, ip_address=client_ip(request),
                 details={"task_id": task.id})
    return Message(message=f"Deletion queued (task {task.id})")


@router.get("/{public_id}/tasks", response_model=list[TaskOut])
def vps_tasks(
    public_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("vps:read")),
):
    vps = _get_visible(request, db, user, public_id)
    import json

    tasks = db.query(Task).filter(Task.vps_id == vps.id).order_by(Task.created_at.desc()).all()
    result = []
    for t in tasks:
        out = TaskOut.model_validate(t)
        out.steps = json.loads(t.steps or "[]")
        result.append(out)
    return result


@router.post("/{public_id}/console-session", response_model=ConsoleSessionOut)
def create_console_session(
    public_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("vps:read")),
):
    vps = _get_visible(request, db, user, public_id)
    if not can_access_vps(request, user, vps):
        raise HTTPException(403, "Not authorized for this VPS console")
    token = generate_token()
    expires = console_expiry(60)
    session = ConsoleSession(
        token_hash=hash_token(token), vps_id=vps.id, user_id=user.id,
        expires_at=expires, kind="vnc",
    )
    db.add(session)
    db.commit()
    record_audit(db, action="console.open", user_id=user.id, resource_type="vps",
                 resource_id=vps.public_id, ip_address=client_ip(request))
    return ConsoleSessionOut(
        console_token=token, vps_id=vps.id, expires_at=expires,
        ws_path=f"/ws/console?token={token}", kind="vnc",
    )


@router.post("/{public_id}/sshx-session", response_model=SshxSessionOut)
def create_sshx_session(
    public_id: str,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user=Depends(require_permission("vps:read")),
):
    """Open one owner-authorized, short-lived hosted sshx.io guest terminal.

    sshx.io URLs are bearer links. BLUEKVM creates the URL only after the
    normal per-VPS access check, returns it once to this request, and never
    writes it to the database, audit data, logs, or a frontend store.
    """
    vps = _get_visible(request, db, user, public_id)
    if not can_access_vps(request, user, vps):
        raise HTTPException(403, "Not authorized for this VPS terminal")
    if vps.status != VPSStatus.RUNNING:
        raise HTTPException(409, "VPS is not running — start it before opening SSHX")
    if not vps.init_password_encrypted:
        raise HTTPException(
            409,
            "This VPS has no stored password; SSHX requires the credential set during provisioning.",
        )

    driver = manager.get_driver(vps.node)
    host = vps.ip_address or ""
    try:
        fresh_ip = driver.get_guest_ip(vps.name, vps.mac_address)
    except Exception:
        fresh_ip = ""
    if fresh_ip:
        host = fresh_ip
        if host != vps.ip_address:
            vps.ip_address = host
            db.commit()
    if not host:
        raise HTTPException(
            409,
            "Guest IP address is not available yet. Wait for DHCP lease / qemu-guest-agent, then retry.",
        )

    try:
        password = decrypt_secret(vps.init_password_encrypted)
    except ValueError as exc:
        raise HTTPException(409, "Stored VPS credential cannot be decrypted") from exc

    expires = console_expiry(settings.sshx_session_ttl_seconds)
    # No usable token is returned to the browser: the DB row is lifecycle/audit
    # state only. Its random hash remains non-replayable if the DB is exposed.
    session = ConsoleSession(
        token_hash=hash_token(generate_token()),
        vps_id=vps.id,
        user_id=user.id,
        expires_at=expires,
        used_at=datetime.now(timezone.utc),
        kind="sshx",
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    try:
        sshx_url = sshx_sessions.start(
            session_id=session.id,
            vps_name=vps.name,
            host=host,
            username=vps.cloud_init_user or "ubuntu",
            password=password,
            expires_at=expires,
        )
    except SshxSessionError as exc:
        session.revoked_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    record_audit(
        db,
        action="sshx.open",
        user_id=user.id,
        resource_type="vps",
        resource_id=vps.public_id,
        ip_address=client_ip(request),
        details={"session_id": session.id, "ttl_seconds": settings.sshx_session_ttl_seconds},
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return SshxSessionOut(sshx_url=sshx_url, vps_id=vps.id, expires_at=expires)


@router.get("/{public_id}/guest-ip", response_model=GuestIpOut)
def guest_ip(
    public_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("vps:read")),
):
    """Return the guest IPv4 address, discovering it via agent/DHCP leases."""
    vps = _get_visible(request, db, user, public_id)
    driver = manager.get_driver(vps.node)
    ip = vps.ip_address or ""
    source = "cached" if ip else ""
    try:
        fresh = driver.get_guest_ip(vps.name, vps.mac_address)
    except Exception as exc:  # driver errors must not 500 the UI
        fresh = ""
        discovery_error = str(exc)
    else:
        discovery_error = ""
    if fresh:
        ip, source = fresh, "discovered"
        if fresh != vps.ip_address:
            vps.ip_address = fresh
            db.commit()
    if not ip:
        detail = (
            "Guest IP address is not available yet. Wait for DHCP lease / "
            "qemu-guest-agent, then retry."
        )
        if discovery_error:
            detail = f"{detail} ({discovery_error})"
        raise HTTPException(409, detail)
    return GuestIpOut(
        ip_address=ip, source=source, ssh_port=22,
        username=vps.cloud_init_user or "ubuntu",
    )
