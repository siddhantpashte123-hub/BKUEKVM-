"""OS template catalogue and verified image downloads."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from ..database import get_db
from ..deps import require_permission
from ..models import OSNodeTemplate, TemplateStatus
from ..schemas import Message, TemplateOut
from ..services.template_service import download_template, seed_templates

router = APIRouter(prefix="/api/templates", tags=["templates"])


@router.get("", response_model=list[TemplateOut])
def list_templates(db=Depends(get_db), user=Depends(require_permission("template:read"))):
    return db.query(OSNodeTemplate).order_by(OSNodeTemplate.os_family, OSNodeTemplate.version).all()


@router.post("/seed", response_model=Message)
def seed_catalogue(db=Depends(get_db), user=Depends(require_permission("template:manage"))):
    created = seed_templates(db)
    return Message(message=f"Seeded {created} new template(s)")


@router.post("/{template_id}/download", response_model=TemplateOut)
def download(
    template_id: int,
    background: BackgroundTasks,
    db=Depends(get_db),
    user=Depends(require_permission("template:manage")),
):
    template = db.get(OSNodeTemplate, template_id)
    if not template:
        raise HTTPException(404, "Template not found")
    if template.status == TemplateStatus.DOWNLOADING:
        raise HTTPException(409, "Download already in progress")
    # Run synchronously inside a background task; UI polls the status field.
    background.add_task(_download_wrapper, template_id)
    return template


def _download_wrapper(template_id: int) -> None:
    # Background tasks get their own session
    from ..database import SessionLocal

    db = SessionLocal()
    try:
        template = db.get(OSNodeTemplate, template_id)
        if template:
            download_template(db, template)
    finally:
        db.close()
