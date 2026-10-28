"""Security primitives: password hashing, opaque tokens, secret encryption."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from cryptography.fernet import Fernet, InvalidToken

from .config import settings

# bcrypt operates on at most 72 bytes. Longer inputs are pre-hashed with
# SHA-256 (a well-established pattern) so arbitrary-length passwords still
# verify deterministically instead of raising inside the crypto library.
_BCRYPT_MAX_BYTES = 72


def _prepare(password: str) -> bytes:
    raw = password.encode("utf-8")
    if len(raw) > _BCRYPT_MAX_BYTES:
        raw = hashlib.sha256(raw).hexdigest().encode("ascii")
    return raw


# ------------------------------------------------------------- passwords --
def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prepare(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_prepare(password), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------- tokens --
def generate_token() -> str:
    """Opaque, high-entropy session/console token."""
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    """Tokens are stored hashed so a DB dump cannot replay sessions."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def session_expiry(ttl_minutes: int | None = None) -> datetime:
    return datetime.now(timezone.utc) + timedelta(
        minutes=ttl_minutes or settings.session_ttl_minutes
    )


def console_expiry(ttl_seconds: int = 60) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)


# ---------------------------------------------- node credential encryption --
def _fernet() -> Fernet:
    key = settings.credential_key
    if not key or key.startswith("CHANGE_ME"):
        # Deterministic fallback derived from the app secret keeps dev working;
        # the installer always provisions an explicit Fernet key.
        derived = base_key = hashlib.sha256(
            ("bluekvm::" + settings.secret_key).encode()
        ).digest()
        from base64 import urlsafe_b64encode

        key = urlsafe_b64encode(derived).decode()
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Unable to decrypt stored credential") from exc
