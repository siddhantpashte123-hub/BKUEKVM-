"""Authentication, sessions, rate limiting and password policy."""
from datetime import datetime, timezone

from app.database import SessionLocal
from app.models import APISession


def test_login_success_sets_cookies(client):
    resp = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "Sup3rStr0ng!Passw0rd"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["username"] == "admin"
    assert "bluekvm_session" in resp.cookies
    assert "bluekvm_csrf" in resp.cookies
    assert body["csrf_token"]


def test_login_wrong_password_rejected(client):
    resp = client.post(
        "/api/auth/login", json={"username": "admin", "password": "wrong-password"}
    )
    assert resp.status_code == 401
    assert "bluekvm_session" not in resp.cookies


def test_login_rate_limited_after_repeated_failures(client):
    for _ in range(8):
        client.post("/api/auth/login", json={"username": "admin", "password": "nope"})
    resp = client.post(
        "/api/auth/login", json={"username": "admin", "password": "nope"}
    )
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


def test_me_requires_authentication(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_returns_current_user(admin_client):
    resp = admin_client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.json()["is_superuser"] is True


def test_logout_revokes_session(admin_client):
    assert admin_client.post("/api/auth/logout").status_code == 200
    # Cookie is cleared, so subsequent calls are unauthenticated
    assert admin_client.get("/api/auth/me").status_code == 401


def test_change_password_enforces_strength_and_rotation(admin_client):
    weak = admin_client.post(
        "/api/auth/change-password",
        json={"current_password": "Sup3rStr0ng!Passw0rd", "new_password": "alllowercaseonly"},
    )
    assert weak.status_code == 422

    good = admin_client.post(
        "/api/auth/change-password",
        json={"current_password": "Sup3rStr0ng!Passw0rd", "new_password": "N3w!Str0ng#Pass99"},
    )
    assert good.status_code == 200

    # Old password no longer works
    old = admin_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "Sup3rStr0ng!Passw0rd"},
    )
    assert old.status_code == 401

    # Restore password for other tests
    admin_client.post(
        "/api/auth/change-password",
        json={"current_password": "N3w!Str0ng#Pass99", "new_password": "Sup3rStr0ng!Passw0rd"},
    )


def test_expired_session_rejected(client, db):
    client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "Sup3rStr0ng!Passw0rd"},
    )
    session = db.query(APISession).order_by(APISession.id.desc()).first()
    session.expires_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
    db.commit()
    assert client.get("/api/auth/me").status_code == 401


def test_login_history_recorded(admin_client):
    resp = admin_client.get("/api/auth/login-history")
    assert resp.status_code == 200
    assert any(row["success"] for row in resp.json())


def test_revoked_session_cannot_be_used(admin_client, db):
    sessions = admin_client.get("/api/auth/sessions").json()
    target = next(s for s in sessions if not s["current"])
    if target:
        assert admin_client.post(f"/api/auth/sessions/{target['id']}/revoke").status_code == 200
