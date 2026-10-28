#!/usr/bin/env python3
"""Probe the local virtualization node and persist its real state.

Run this after starting libvirtd or whenever the panel reports
"No KVM-capable online node is registered". It is idempotent: the local
node and bootstrap data are created if missing, then a libvirt health
check updates status, KVM readiness, hypervisor version, pools and networks.

Usage:
    cd /opt/bluekvm/backend && . .venv/bin/activate
    set -a; . /opt/bluekvm/.env; set +a
    python /opt/bluekvm/scripts/node-healthcheck.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running both from a checkout and an installed deployment
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.bootstrap import run_bootstrap  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import Node  # noqa: E402
from app.virtualization.manager import manager  # noqa: E402


def main() -> int:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        run_bootstrap(db, health_check=False)
        node = db.query(Node).filter(Node.is_local.is_(True)).first()
        if not node:
            print("No local node found after bootstrap", file=sys.stderr)
            return 1
        manager.health_check(db, node)
        print(f"node={node.name}")
        print(f"status={node.status.value}")
        print(f"kvm_ready={node.kvm_ready}")
        print(f"hypervisor={node.hypervisor_version or 'unknown'}")
        if node.last_error:
            print(f"reason={node.last_error}")
            return 2
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
