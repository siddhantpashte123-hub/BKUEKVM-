#!/usr/bin/env bash
# BLUEKVM PANNEL — safe staged update with automatic backup and health gate.
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/bluekvm}"
BACKUP_ROOT="/var/backups/bluekvm"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$BACKUP_ROOT/$STAMP"

if [ "$(id -u)" -ne 0 ]; then
  echo "[FAIL] Run with sudo/root." >&2
  exit 1
fi
if [ ! -d "$INSTALL_DIR" ]; then
  echo "[FAIL] $INSTALL_DIR not found — run the installer first." >&2
  exit 1
fi

# shellcheck disable=SC1091
set -a; . "$INSTALL_DIR/.env"; set +a
mkdir -p "$BACKUP_DIR"

echo "[INFO] Backing up configuration and database metadata"
cp -a "$INSTALL_DIR/.env" "$BACKUP_DIR/env"
case "$DATABASE_URL" in
  postgresql*)
    DB_PASS="$(echo "$DATABASE_URL" | sed -E 's#.*://bluekvm:([^@]+)@.*#\1#')"
    PGPASSWORD="$DB_PASS" pg_dump -h 127.0.0.1 -U bluekvm bluekvm > "$BACKUP_DIR/bluekvm.sql" \
      || echo "[WARN] pg_dump failed — continuing but fix database access before retrying"
    ;;
  sqlite:*)
    cp -f "${DATABASE_URL#sqlite:///}" "$BACKUP_DIR/bluekvm.db" 2>/dev/null || true
    ;;
esac

echo "[INFO] Updating application files"
if [ -d "$INSTALL_DIR/.git" ]; then
  git -C "$INSTALL_DIR" fetch --tags
  git -C "$INSTALL_DIR" pull --ff-only
else
  echo "[FAIL] Not a git checkout — deploy a verified release tarball manually." >&2
  exit 1
fi

echo "[INFO] Refreshing dependencies"
"$INSTALL_DIR/backend/.venv/bin/pip" install -q -r "$INSTALL_DIR/backend/requirements.txt"
(cd "$INSTALL_DIR/frontend" && npm install --no-audit --no-fund && npm run build)

echo "[INFO] Applying database migrations"
(cd "$INSTALL_DIR/backend" && . .venv/bin/activate && alembic upgrade head)

echo "[INFO] Restarting services"
systemctl restart bluekvm-worker bluekvm-api

echo "[INFO] Waiting for health check"
for _ in $(seq 1 15); do
  if curl -fsS "http://127.0.0.1:${BLUEKVM_PORT:-8989}/health/ready" 2>/dev/null | grep -qE '"status"[[:space:]]*:[[:space:]]*"ready"'; then
    echo "[ OK ] Update complete and healthy. Backup at $BACKUP_DIR"
    exit 0
  fi
  sleep 2
done
echo "[FAIL] Health check failed. Roll back with docs/updates-and-recovery.md" >&2
exit 1
