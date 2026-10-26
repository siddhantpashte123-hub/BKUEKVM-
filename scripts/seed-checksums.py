#!/usr/bin/env python3
"""Pin SHA-256 checksums for curated OS templates.

Usage (after a verified download):
    python scripts/seed-checksums.py <template_id> <sha256-hex>

Production deployments should pin every checksum so the template service
rejects tampered cloud images before they can boot a guest.
"""
from __future__ import annotations

import sys

sys.path.insert(0, "backend")

from app.database import SessionLocal  # noqa: E402
from app.models import OSNodeTemplate  # noqa: E402


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    template_id, checksum = int(sys.argv[1]), sys.argv[2].strip().lower()
    if len(checksum) != 64:
        print("A SHA-256 checksum must be 64 hex characters")
        return 2
    db = SessionLocal()
    try:
        template = db.get(OSNodeTemplate, template_id)
        if not template:
            print(f"Template {template_id} not found")
            return 1
        template.checksum_sha256 = checksum
        db.commit()
        print(f"Pinned checksum for template {template.name}: {checksum}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
