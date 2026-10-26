"""First-run bootstrap: roles, initial administrator and the local node.

Runs idempotently at API startup and via the installer. No default/well-known
password is ever shipped: when no admin password is configured a random one
is generated and printed exactly once to the journal/installer log.
"""
from __future__ import annotations

import json
import logging
import secrets

from sqlalchemy.orm import Session

from .config import settings
from .models import Node, NodeStatus, Role, User
from .security import hash_password
from .services.template_service import seed_templates

log = logging.getLogger("bluekvm.bootstrap")

ROLE_DEFINITIONS = [
    ("Super Administrator", ["*"]),
    (
        "Administrator",
        [
            "vps:read", "vps:manage", "node:read", "node:manage",
            "template:read", "template:manage", "network:read", "network:manage",
            "storage:read", "backup:read", "backup:manage",
            "user:read", "user:manage", "audit:read", "monitoring:read",
            "settings:read", "settings:manage",
        ],
    ),
    (
        "VPS Manager",
        [
            "vps:read", "vps:manage", "node:read", "template:read",
            "network:read", "storage:read", "backup:read", "backup:manage",
            "monitoring:read",
        ],
    ),
    (
        "Read-Only Viewer",
        [
            "vps:read", "node:read", "template:read", "network:read",
            "storage:read", "backup:read", "monitoring:read",
            "settings:read",
        ],
    ),
]


def seed_roles(db: Session) -> dict[str, Role]:
    roles: dict[str, Role] = {}
    for index, (name, perms) in enumerate(ROLE_DEFINITIONS, start=1):
        role = db.query(Role).filter(Role.name == name).first()
        if not role:
            role = Role(name=name, permissions=json.dumps(perms), is_system=True)
            db.add(role)
            db.commit()
            db.refresh(role)
        roles[name] = role
    return roles


def ensure_admin(db: Session, roles: dict[str, Role]) -> str | None:
    """Create the initial administrator. Returns a generated password or None."""
    existing = db.query(User).filter(User.is_superuser.is_(True)).first()
    if existing:
        return None
    generated = None
    password = settings.admin_password
    if not password:
        password = secrets.token_urlsafe(18)
        generated = password
    admin = User(
        username=settings.admin_username,
        email=settings.admin_email,
        password_hash=hash_password(password),
        role_id=roles["Super Administrator"].id,
        is_superuser=True,
    )
    db.add(admin)
    db.commit()
    if generated:
        log.warning(
            "Initial administrator created: username=%s password=%s "
            "(shown once — store it securely now)",
            settings.admin_username,
            generated,
        )
    return generated


def ensure_local_node(db: Session) -> Node:
    node = db.query(Node).filter(Node.is_local.is_(True)).first()
    if not node:
        node = Node(
            name="local-node",
            address="local",
            libvirt_uri=settings.libvirt_uri,
            is_local=True,
            status=NodeStatus.UNCONFIGURED,
        )
        db.add(node)
        db.commit()
        db.refresh(node)
    return node


def run_bootstrap(db: Session, *, health_check: bool = False) -> dict:
    roles = seed_roles(db)
    generated_password = ensure_admin(db, roles)
    node = ensure_local_node(db)
    templates_added = seed_templates(db)
    result = {
        "generated_admin_password": generated_password,
        "local_node": node.name,
        "templates_added": templates_added,
    }
    if health_check:
        from .virtualization.manager import manager

        manager.health_check(db, node)
        db.refresh(node)
        result["node_status"] = node.status.value
        result["kvm_ready"] = node.kvm_ready
        result["node_error"] = node.last_error
    return result
