"""Application settings and panel branding.

Secrets are never readable through this API; only non-sensitive panel
preferences are persisted.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import __version__
from ..config import settings
from ..database import get_db
from ..deps import require_permission
from ..models import AppSetting
from ..schemas import SettingUpdate

router = APIRouter(prefix="/api/settings", tags=["settings"])

PUBLIC_DEFAULTS = {
    "app_name": "BLUEKVM PANNEL",
    "branding_tagline": "Premium KVM VPS management",
    "default_port": 8989,
    "release_channel": "stable",
    "audit_retention_days": 90,
    "session_ttl_minutes": 720,
    "notifications": {"email": False, "webhook": False},
}

# Only these keys may be modified through the web interface
ALLOWED_KEYS = set(PUBLIC_DEFAULTS) | {"panel_notes", "maintenance_mode"}


@router.get("")
def get_settings(db: Session = Depends(get_db), user=Depends(require_permission("settings:read"))):
    values = dict(PUBLIC_DEFAULTS)
    for row in db.query(AppSetting).all():
        try:
            values[row.key] = json.loads(row.value)
        except json.JSONDecodeError:
            values[row.key] = row.value
    return {
        "settings": values,
        "environment": {
            "version": __version__,
            "env": settings.env,
            "port": settings.port,
            "database": "postgresql" if not settings.is_sqlite else "sqlite",
            "cookie_secure": settings.cookie_secure,
            "csrf_enabled": settings.csrf_enabled,
        },
    }


@router.put("/{key}")
def update_setting(
    key: str,
    payload: SettingUpdate,
    db: Session = Depends(get_db),
    user=Depends(require_permission("settings:manage")),
):
    if key not in ALLOWED_KEYS:
        raise HTTPException(403, "Setting is not editable or does not exist")
    if key == "default_port":
        port = payload.value
        if not isinstance(port, int) or not (1024 <= port <= 65535):
            raise HTTPException(400, "Port must be an integer between 1024 and 65535")
    row = db.get(AppSetting, key)
    encoded = json.dumps(payload.value)
    if row:
        row.value = encoded
    else:
        db.add(AppSetting(key=key, value=encoded))
    db.commit()
    return {"key": key, "value": payload.value}
