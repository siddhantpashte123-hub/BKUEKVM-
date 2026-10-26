"""Audit trail writer. Administrative actions are never silently performed."""
from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from ..models import AuditLog

log = logging.getLogger("bluekvm.audit")

# Fields that must never land in the audit store
_FORBIDDEN_KEYS = {"password", "secret", "token", "credential", "private_key"}


def _sanitize(details: dict | None) -> str:
    if not details:
        return "{}"
    clean = {k: ("***REDACTED***" if k.lower() in _FORBIDDEN_KEYS else v) for k, v in details.items()}
    return json.dumps(clean, default=str)[:8192]


def record_audit(
    db: Session,
    *,
    action: str,
    user_id: int | None = None,
    resource_type: str = "",
    resource_id: str = "",
    ip_address: str = "",
    details: dict | None = None,
) -> AuditLog:
    entry = AuditLog(
        action=action,
        user_id=user_id,
        resource_type=resource_type,
        resource_id=str(resource_id),
        ip_address=ip_address,
        details=_sanitize(details),
    )
    db.add(entry)
    db.commit()
    log.info("audit %s %s/%s by user=%s", action, resource_type, resource_id, user_id)
    return entry
