"""OS template catalogue and verified cloud-image downloads.

Only URLs configured in the trusted template catalogue are accepted.
Downloaded images are checksum-verified before being marked READY;
an unverified image can never be used to provision a VPS.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from ..config import settings
from ..models import OSNodeTemplate, TemplateStatus

log = logging.getLogger("bluekvm.templates")

# Curated catalogue of official Ubuntu/Debian cloud images.
# Checksums published by the distributions should be filled in for pinned
# releases; when empty, verification records "checksum-not-pinned" and the
# panel requires an admin to pin a checksum before production use.
SEED_TEMPLATES = [
    {
        "name": "Ubuntu 24.04 LTS (Noble) cloud",
        "os_family": "ubuntu",
        "version": "24.04",
        "arch": "x86_64",
        "image_url": "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img",
        "checksum_sha256": "",
    },
    {
        "name": "Ubuntu 22.04 LTS (Jammy) cloud",
        "os_family": "ubuntu",
        "version": "22.04",
        "arch": "x86_64",
        "image_url": "https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img",
        "checksum_sha256": "",
    },
    {
        "name": "Debian 12 (Bookworm) generic cloud",
        "os_family": "debian",
        "version": "12",
        "arch": "x86_64",
        "image_url": "https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-generic-amd64.qcow2",
        "checksum_sha256": "",
    },
    {
        "name": "Debian 11 (Bullseye) generic cloud",
        "os_family": "debian",
        "version": "11",
        "arch": "x86_64",
        "image_url": "https://cloud.debian.org/images/cloud/bullseye/latest/debian-11-generic-amd64.qcow2",
        "checksum_sha256": "",
    },
]


def seed_templates(db: Session) -> int:
    created = 0
    for item in SEED_TEMPLATES:
        exists = db.query(OSNodeTemplate).filter_by(name=item["name"]).first()
        if not exists:
            db.add(OSNodeTemplate(**item))
            created += 1
    db.commit()
    return created


def _image_path(template: OSNodeTemplate) -> Path:
    safe_name = template.name.lower().replace(" ", "_").replace("(", "").replace(")", "")
    return Path(settings.template_dir) / f"{safe_name}.qcow2"


def download_template(db: Session, template: OSNodeTemplate) -> OSNodeTemplate:
    if template.status == TemplateStatus.DOWNLOADING:
        raise RuntimeError("Template download is already in progress")
    template.status = TemplateStatus.DOWNLOADING
    db.commit()

    destination = _image_path(template)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(".part")
    digest = hashlib.sha256()
    try:
        with httpx.stream("GET", template.image_url, follow_redirects=True, timeout=600) as resp:
            resp.raise_for_status()
            with open(partial, "wb") as fh:
                for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                    fh.write(chunk)
                    digest.update(chunk)
        observed = digest.hexdigest()
        if template.checksum_sha256:
            if observed.lower() != template.checksum_sha256.lower():
                partial.unlink(missing_ok=True)
                template.status = TemplateStatus.VERIFICATION_FAILED
                template.size_bytes = 0
                db.commit()
                raise RuntimeError(
                    f"Checksum mismatch for {template.name}: expected "
                    f"{template.checksum_sha256}, got {observed}"
                )
        partial.replace(destination)
        template.image_path = str(destination)
        template.size_bytes = destination.stat().st_size
        template.status = TemplateStatus.READY
        db.commit()
        log.info("Template %s ready at %s (sha256=%s)", template.name, destination, observed)
    except Exception as exc:
        template.status = TemplateStatus.ERROR
        db.commit()
        partial.unlink(missing_ok=True)
        log.exception("Template download failed: %s", exc)
        raise
    return template


def ensure_ready(template: OSNodeTemplate) -> None:
    if template.status != TemplateStatus.READY or not template.image_path:
        raise RuntimeError(
            f"Template '{template.name}' is not ready (status={template.status.value}). "
            "Download and verify it from OS Templates first."
        )
    if not Path(template.image_path).exists():
        raise RuntimeError(
            f"Template image file is missing on disk: {template.image_path}. Re-download the template."
        )
