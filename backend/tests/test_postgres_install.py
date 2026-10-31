"""Regression coverage for the PostgreSQL installer and migration setup."""
import os
from pathlib import Path
import subprocess

import pytest
from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = (ROOT / "installer/install.sh").read_text()


def test_postgres_psycopg_dialect_is_installable_without_opening_connection():
    # Constructing the engine imports the configured DBAPI. No database server
    # is required and we do not claim that authentication succeeds here.
    engine = create_engine("postgresql+psycopg://user:password@127.0.0.1:5432/example")
    try:
        assert engine.dialect.name == "postgresql"
        assert engine.dialect.driver == "psycopg"
    finally:
        engine.dispose()


@pytest.mark.parametrize("database_url", [
    "sqlite:////tmp/example.db",
    "postgresql+psycopg://bluekvm:secret@127.0.0.1:5432/bluekvm",
])
def test_installer_migrations_use_installed_env_file(tmp_path, database_url):
    backend = tmp_path / "install/backend"
    (backend / ".venv/bin").mkdir(parents=True)
    (backend / ".venv/bin/activate").write_text(":\n")
    env_file = tmp_path / "install/.env"
    env_file.write_text(f"DATABASE_URL={database_url}\n")
    result_file = tmp_path / "alembic-env"
    start = INSTALLER.index('  (\n    cd "$INSTALL_DIR/backend" || exit 1', INSTALLER.index('# ------------------------------------------------------------- migrations'))
    end = INSTALLER.index('\n  ok "Migrations applied"', start)
    block = INSTALLER[start:end]
    command = (
        'set -eu\n'
        'alembic() { printf "%s" "$DATABASE_URL" > "$RESULT_FILE"; }\n'
        'die() { echo "$*" >&2; exit 1; }\n'
        + block + '\n'
    )
    subprocess.run(
        ["bash", "-c", command], check=True, capture_output=True, text=True,
        env={**os.environ, "INSTALL_DIR": str(tmp_path / "install"),
             "ENV_FILE": str(env_file), "RESULT_FILE": str(result_file),
             # An inherited stale URL must not override the installed config.
             "DATABASE_URL": "sqlite:////tmp/wrong.db"},
    )
    assert result_file.read_text() == database_url


@pytest.mark.parametrize("existing_role,existing_db", [("1", ""), ("", "1"), ("1", "1")])
def test_fresh_installer_refuses_existing_postgres_objects(tmp_path, existing_role, existing_db):
    start = INSTALLER.index('      ROLE_EXISTS="$(su - postgres')
    end = INSTALLER.index('      DATABASE_URL="postgresql+psycopg', start)
    block = INSTALLER[start:end]
    log = tmp_path / "su.log"
    command = '''
set -eu
PG_PASSWORD=not-a-real-secret
die() { echo "$*" >&2; exit 1; }
su() {
  printf '%s\\n' "$*" >> "$CALL_LOG"
  case "$*" in
    *pg_roles*) printf '%s' "$EXISTING_ROLE" ;;
    *pg_database*) printf '%s' "$EXISTING_DB" ;;
    *createdb*|*ON_ERROR_STOP*) echo "unexpected modification" >&2; return 99 ;;
  esac
}
''' + block
    result = subprocess.run(
        ["bash", "-c", command], capture_output=True, text=True,
        env={**os.environ, "EXISTING_ROLE": existing_role, "EXISTING_DB": existing_db,
             "CALL_LOG": str(log)},
    )
    assert result.returncode != 0
    assert "Refusing to overwrite or reuse unknown credentials" in result.stderr
    assert "createdb" not in log.read_text()
    assert "ON_ERROR_STOP" not in log.read_text()
