"""FastAPI dependencies: authentication, CSRF and role-based authorization."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import APISession, User, VPS, VPSStatus
from .security import constant_time_equals, hash_token

SESSION_COOKIE = "bluekvm_session"
CSRF_COOKIE = "bluekvm_csrf"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# Permission catalogue used by the seeded roles
PERMISSIONS = {
    "vps:read", "vps:manage",
    "node:read", "node:manage",
    "template:read", "template:manage",
    "network:read", "network:manage",
    "storage:read",
    "backup:read", "backup:manage",
    "user:read", "user:manage",
    "audit:read",
    "monitoring:read",
    "settings:read", "settings:manage",
}


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return request.client.host if request.client else "unknown"


def _load_role_permissions(user: User) -> list[str]:
    try:
        perms = json.loads(user.role.permissions or "[]")
    except json.JSONDecodeError:
        perms = []
    return ["*"] if user.is_superuser else perms


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    session = db.query(APISession).filter(APISession.token_hash == hash_token(token)).first()
    if not session or session.revoked_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session is invalid or revoked")
    now = datetime.now(timezone.utc)
    expires = session.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < now:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    user = db.get(User, session.user_id)
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account is disabled")
    session.last_seen_at = now
    db.commit()
    request.state.session = session
    request.state.permissions = _load_role_permissions(user)
    return user


def enforce_csrf(request: Request) -> None:
    if request.method in SAFE_METHODS or not settings.csrf_enabled or settings.is_dev:
        return
    session = getattr(request.state, "session", None)
    token = request.headers.get(CSRF_HEADER, "")
    if not session or not token or not constant_time_equals(token, session.csrf_token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF token missing or invalid")


def require_permission(permission: str):
    def dependency(
        request: Request,
        user: User = Depends(get_current_user),
        _csrf: None = Depends(enforce_csrf),
    ) -> User:
        perms = getattr(request.state, "permissions", []) or []
        if "*" not in perms and permission not in perms:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {permission}")
        return user

    return dependency


def can_access_vps(request: Request, user: User, vps: VPS) -> bool:
    perms = getattr(request.state, "permissions", []) or []
    if "*" in perms or "vps:manage" in perms:
        return True
    # Scoped users may only touch resources explicitly assigned to them
    return vps.owner_id == user.id


def scoped_vps_query(request: Request, db: Session, user: User):
    query = db.query(VPS).filter(VPS.status != VPSStatus.DELETED)
    perms = getattr(request.state, "permissions", []) or []
    if "*" not in perms and "vps:manage" not in perms:
        query = query.filter(VPS.owner_id == user.id)
    return query
