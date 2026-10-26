"""User and role administration."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import client_ip, require_permission
from ..models import APISession, Role, User
from ..schemas import Message, RoleOut, UserCreate, UserOut, UserUpdate
from ..security import hash_password
from ..services.audit import record_audit

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/roles", response_model=list[RoleOut])
def roles(db: Session = Depends(get_db), user=Depends(require_permission("user:read"))):
    result = []
    for role in db.query(Role).order_by(Role.id).all():
        out = RoleOut.model_validate(role)
        out.permissions = __import__("json").loads(role.permissions or "[]")
        result.append(out)
    return result


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), user=Depends(require_permission("user:read"))):
    return db.query(User).order_by(User.id).all()


@router.post("", response_model=UserOut, status_code=201)
def create_user(
    payload: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("user:manage")),
):
    if db.query(User).filter((User.username == payload.username) | (User.email == payload.email)).first():
        raise HTTPException(409, "Username or email already exists")
    role = db.get(Role, payload.role_id)
    if not role:
        raise HTTPException(404, "Role not found")
    new_user = User(
        username=payload.username,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role_id=payload.role_id,
        is_active=payload.is_active,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    record_audit(db, action="user.create", user_id=user.id, resource_type="user",
                 resource_id=new_user.username, ip_address=client_ip(request),
                 details={"role": role.name})
    return new_user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("user:manage")),
):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found")
    if payload.email:
        target.email = payload.email
    if payload.role_id is not None:
        if not db.get(Role, payload.role_id):
            raise HTTPException(404, "Role not found")
        target.role_id = payload.role_id
    if payload.is_active is not None:
        target.is_active = payload.is_active
    db.commit()
    db.refresh(target)
    record_audit(db, action="user.update", user_id=user.id, resource_type="user",
                 resource_id=target.username, ip_address=client_ip(request),
                 details=payload.model_dump(exclude_none=True))
    return target


@router.post("/{user_id}/revoke-sessions", response_model=Message)
def revoke_user_sessions(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("user:manage")),
):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found")
    from datetime import datetime, timezone

    count = (
        db.query(APISession)
        .filter(APISession.user_id == user_id, APISession.revoked_at.is_(None))
        .update({APISession.revoked_at: datetime.now(timezone.utc)})
    )
    db.commit()
    record_audit(db, action="user.revoke_sessions", user_id=user.id, resource_type="user",
                 resource_id=target.username, ip_address=client_ip(request),
                 details={"revoked": count})
    return Message(message=f"Revoked {count} session(s)")


@router.delete("/{user_id}", response_model=Message)
def delete_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("user:manage")),
):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found")
    if target.is_superuser:
        raise HTTPException(400, "The super administrator account cannot be deleted")
    username = target.username
    db.delete(target)
    db.commit()
    record_audit(db, action="user.delete", user_id=user.id, resource_type="user",
                 resource_id=username, ip_address=client_ip(request))
    return Message(message="User deleted")
