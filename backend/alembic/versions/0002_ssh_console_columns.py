"""SSH-in-browser support: VM credentials and console session kind

Adds:
  * vps.cloud_init_user           — default cloud-init login user
  * vps.init_password_encrypted   — Fernet-encrypted VM password (optional,
                                    used by the browser SSH terminal)
  * console_sessions.kind         — 'vnc' (legacy recovery console) or
                                    'ssh' (browser terminal token)

The baseline (0001) creates tables from the current model metadata, so on a
fresh database these columns may already exist. Every ADD COLUMN is therefore
guarded by an inspector check to keep `alembic upgrade head` idempotent on
both SQLite and PostgreSQL.

Revision ID: 0002_ssh
Revises: 0001_initial
Create Date: 2026-10-28
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_ssh"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _existing_columns(table: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    vps_cols = _existing_columns("vps")
    with op.batch_alter_table("vps") as batch:
        if "cloud_init_user" not in vps_cols:
            batch.add_column(
                sa.Column("cloud_init_user", sa.String(length=64), nullable=False, server_default="ubuntu")
            )
        if "init_password_encrypted" not in vps_cols:
            batch.add_column(sa.Column("init_password_encrypted", sa.Text(), nullable=True))

    session_cols = _existing_columns("console_sessions")
    with op.batch_alter_table("console_sessions") as batch:
        if "kind" not in session_cols:
            batch.add_column(
                sa.Column("kind", sa.String(length=8), nullable=False, server_default="vnc")
            )


def downgrade() -> None:
    with op.batch_alter_table("console_sessions") as batch:
        batch.drop_column("kind")
    with op.batch_alter_table("vps") as batch:
        batch.drop_column("init_password_encrypted")
        batch.drop_column("cloud_init_user")
