"""Initial BLUEKVM PANNEL schema

Creates the full authoritative metadata schema from the SQLAlchemy models.
Using metadata.create_all keeps PostgreSQL and SQLite identical for the
baseline; future schema changes will be expressed as explicit migrations.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-26
"""
from alembic import op

from app.database import Base
from app import models  # noqa: F401  (register every model on Base.metadata)

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
