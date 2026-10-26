"""Authentication: login, logout, sessions, password changes, login history."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import SESSION_COOKIE, CSRF_COOKIE, client_ip, get_current_user
from ..models import APISession, LoginHistory, User
from ..ratelimit import login_limiter
from ..schemas import (
    ChangePasswordRequest,
    LoginHistoryOut,
    LoginRequest,
    LoginResponse,
    Message,
    UserOut,
)
from ..security import (
    constant_time_equals,
    generate_csrf_token,
    generate_token,
    hash_password,
    hash_token,
    session_expiry,
    verify_password,
)
from ..services.audit import record_audit

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_cookies(response: Response, token: str, csrf: str, expires: datetime) -> None:
    max_age = settings.session_ttl_minutes * 60
    response.set_cookie(
        SESSION_COOKIE, token, max_age=max_age, httponly=True,
        secure=settings.cookie_secure, samesite="lax", path="/",
    )
    response.set_cookie(
        CSRF_COOKIE, csrf, max_age=max_age, httponly=False,
        secure=settings.cookie_secure, samesite="lax", path="/",
    )


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = client_ip(request)
    allowed, retry_after = login_limiter.check(
        f"login:{ip}", settings.login_rate_per_minute, window_seconds=60
    )
    if not allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many attempts. Retry in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    user = db.query(User).filter(
        (User.username == payload.username) | (User.email == payload.username)
    ).first()

    if not user or not verify_password(payload.password, user.password_hash):
        db.add(
            LoginHistory(
                username=payload.username, user_id=user.id if user else None,
                ip_address=ip, user_agent=request.headers.get("user-agent", "")[:512],
                success=False, reason="invalid credentials",
            )
        )
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    if not user.is_active:
        db.add(
            LoginHistory(
                username=payload.username, user_id=user.id, ip_address=ip,
                user_agent=request.headers.get("user-agent", "")[:512],
                success=False, reason="account disabled",
            )
        )
        db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is disabled")

    token = generate_token()
    csrf = generate_csrf_token()
    expires = session_expiry()
    db.add(
        APISession(
            token_hash=hash_token(token), csrf_token=csrf, user_id=user.id,
            user_agent=request.headers.get("user-agent", "")[:512],
            ip_address=ip, expires_at=expires,
        )
    )
    user.last_login_at = datetime.now(timezone.utc)
    db.add(
        LoginHistory(
            username=user.username, user_id=user.id, ip_address=ip,
            user_agent=request.headers.get("user-agent", "")[:512],
            success=True, reason="login",
        )
    )
    db.commit()
    _set_cookies(response, token, csrf, expires)
    record_audit(db, action="auth.login", user_id=user.id, resource_type="session",
                 ip_address=ip, details={"username": user.username})
    return LoginResponse(user=UserOut.model_validate(user), csrf_token=csrf, expires_at=expires)


@router.post("/logout", response_model=Message)
def logout(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    session = getattr(request.state, "session", None)
    if session:
        session.revoked_at = datetime.now(timezone.utc)
        db.commit()
    response = Response(
        content=json.dumps({"message": "Logged out"}), media_type="application/json"
    )
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    record_audit(db, action="auth.logout", user_id=user.id, resource_type="session",
                 ip_address=client_ip(request))
    return response


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.get("/permissions")
def permissions(request: Request, user: User = Depends(get_current_user)):
    return {"permissions": getattr(request.state, "permissions", [])}


@router.post("/change-password", response_model=Message)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    if constant_time_equals(payload.current_password, payload.new_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "New password must differ from the old one")
    user.password_hash = hash_password(payload.new_password)
    # Revoke all other sessions after a password change
    for sess in db.query(APISession).filter(
        APISession.user_id == user.id, APISession.revoked_at.is_(None)
    ):
        if sess is not getattr(request.state, "session", None):
            sess.revoked_at = datetime.now(timezone.utc)
    db.commit()
    record_audit(db, action="auth.change_password", user_id=user.id,
                 resource_type="user", resource_id=user.id, ip_address=client_ip(request))
    return Message(message="Password updated")


@router.get("/sessions")
def list_sessions(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    current = getattr(request.state, "session", None)
    rows = (
        db.query(APISession)
        .filter(APISession.user_id == user.id)
        .order_by(APISession.created_at.desc())
        .all()
    )
    return [
        {
            "id": s.id,
            "ip_address": s.ip_address,
            "user_agent": s.user_agent,
            "created_at": s.created_at,
            "last_seen_at": s.last_seen_at,
            "expires_at": s.expires_at,
            "revoked": s.revoked_at is not None,
            "current": current is not None and s.id == current.id,
        }
        for s in rows
    ]


@router.post("/sessions/{session_id}/revoke", response_model=Message)
def revoke_session(
    session_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    sess = db.get(APISession, session_id)
    if not sess or sess.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    sess.revoked_at = datetime.now(timezone.utc)
    db.commit()
    record_audit(db, action="auth.revoke_session", user_id=user.id,
                 resource_type="session", resource_id=sess.id, ip_address=client_ip(request))
    return Message(message="Session revoked")


@router.get("/login-history", response_model=list[LoginHistoryOut])
def login_history(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    limit: int = 50,
):
    limit = min(max(limit, 1), 200)
    return (
        db.query(LoginHistory)
        .filter(LoginHistory.user_id == user.id)
        .order_by(LoginHistory.created_at.desc())
        .limit(limit)
        .all()
    )
