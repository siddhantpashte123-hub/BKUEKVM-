#!/usr/bin/env bash
# Rebuild a damaged BLUEKVM Python venv on a systemd host, preserving the old
# environment. This does not modify the panel .env, database, or VM disks.
set -euo pipefail

if [ "${1:-}" != "--apply" ] || [ "$#" -ne 1 ]; then
  echo "Usage: sudo bash repair-venv.sh --apply" >&2
  echo "Stops panel services, backs up the existing venv, reinstalls dependencies, and restarts the services." >&2
  exit 2
fi
if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root or with sudo." >&2
  exit 1
fi

INSTALL_DIR="${BLUEKVM_INSTALL_DIR:-/opt/bluekvm}"
BACKEND="$INSTALL_DIR/backend"
VENV="$BACKEND/.venv"
ENV_FILE="$INSTALL_DIR/.env"
REQUIREMENTS="$BACKEND/requirements.txt"
BACKUP_DIR=""

report_failure() {
  local status=$?
  if [ "$status" -ne 0 ] && [ -n "$BACKUP_DIR" ]; then
    echo "[FAIL] Repair did not complete. Previous venv is preserved at: $BACKUP_DIR/original-venv" >&2
    echo "The script did not reset or delete the database or VM disks. Inspect service logs before retrying." >&2
  fi
}
trap report_failure EXIT

[ -f "$ENV_FILE" ] || { echo "Panel configuration not found; no changes made." >&2; exit 1; }
[ -f "$REQUIREMENTS" ] || { echo "Backend requirements not found; no changes made." >&2; exit 1; }
[ -d "$VENV" ] && [ ! -L "$VENV" ] || { echo "Existing venv directory missing or is a symlink; no changes made." >&2; exit 1; }
command -v systemctl >/dev/null && command -v runuser >/dev/null && command -v curl >/dev/null \
  || { echo "systemctl, runuser and curl are required; no changes made." >&2; exit 1; }
id bluekvm >/dev/null 2>&1 || { echo "Panel account 'bluekvm' not found; no changes made." >&2; exit 1; }
for unit in bluekvm-api.service bluekvm-worker.service; do
  [ "$(systemctl show "$unit" -p LoadState --value 2>/dev/null || true)" = "loaded" ] \
    || { echo "$unit is not loaded; no changes made." >&2; exit 1; }
done

# Prefer the old venv's system Python version; this keeps distro libvirt
# bindings available on Ubuntu (for example Python 3.10 on 22.04).
OLD_VERSION="$("$VENV/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)"
PYTHON_BIN=""
for candidate in "python${OLD_VERSION}" python3.12 python3.11 python3.10 python3.13 python3; do
  [ "$candidate" != "python" ] || continue
  command -v "$candidate" >/dev/null 2>&1 || continue
  if "$candidate" -c 'import sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] <= (3, 13) else 1)' >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v "$candidate")"
    break
  fi
done
[ -n "$PYTHON_BIN" ] || { echo "Python 3.10–3.13 not found; no changes made." >&2; exit 1; }

PORT_LINE="$(grep -E '^BLUEKVM_PORT=' "$ENV_FILE" 2>/dev/null | tail -1 || true)"
if [ -n "$PORT_LINE" ]; then
  PORT="${PORT_LINE#BLUEKVM_PORT=}"
  PORT="${PORT#\"}"; PORT="${PORT%\"}"
  PORT="${PORT#\'}"; PORT="${PORT%\'}"
else
  PORT=8989
fi
if ! [[ "$PORT" =~ ^[0-9]+$ ]] || [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
  echo "Invalid panel port in configuration; no changes made." >&2
  exit 1
fi

echo "Stopping panel API and worker (VMs are not stopped)..."
systemctl stop bluekvm-api.service bluekvm-worker.service
BACKUP_DIR="$(mktemp -d "$BACKEND/.venv-backup.XXXXXX")"
mv -- "$VENV" "$BACKUP_DIR/original-venv"
echo "Existing venv backed up at: $BACKUP_DIR/original-venv"
echo "Creating a fresh Python environment using $PYTHON_BIN..."
"$PYTHON_BIN" -m venv --system-site-packages "$VENV"

# Old installed panel releases may not list psycopg even when PostgreSQL is in
# use. Supply the compatible driver only if the installed requirements omit it.
EXTRA=()
if ! grep -Eq '^[[:space:]]*psycopg([[:space:]]|\[|[<=>!~])' "$REQUIREMENTS"; then
  EXTRA+=("psycopg[binary]==3.2.10")
fi
"$VENV/bin/python" -m pip install --no-cache-dir -r "$REQUIREMENTS" "${EXTRA[@]}"
"$VENV/bin/python" -c 'from sqlalchemy import create_engine; import fastapi, uvicorn, psycopg, libvirt'
"$VENV/bin/uvicorn" --version >/dev/null
if ! "$VENV/bin/python" -m pip check; then
  echo "[WARN] pip check reported dependency issues; inspect them before relying on the panel." >&2
fi

# Verify under the same OS account used by systemd, not just as root.
chown -R bluekvm "$VENV"
runuser -u bluekvm -- "$VENV/bin/python" -c 'from sqlalchemy import create_engine; import fastapi, uvicorn, psycopg, libvirt'
runuser -u bluekvm -- "$VENV/bin/uvicorn" --version >/dev/null

echo "Restarting panel services..."
systemctl reset-failed bluekvm-api.service bluekvm-worker.service
systemctl start bluekvm-api.service bluekvm-worker.service
for _ in $(seq 1 15); do
  if systemctl is-active --quiet bluekvm-api.service && systemctl is-active --quiet bluekvm-worker.service && \
    curl -fsS --max-time 3 "http://127.0.0.1:$PORT/health/ready" | grep -qE '"status"[[:space:]]*:[[:space:]]*"ready"'; then
    echo "[ OK ] Panel and worker are running; readiness check passed on port $PORT."
    echo "Previous venv backup: $BACKUP_DIR/original-venv"
    exit 0
  fi
  sleep 2
done
echo "[FAIL] Venv was rebuilt, but services or readiness did not become healthy." >&2
echo "Run: journalctl -u bluekvm-api -u bluekvm-worker -n 80 --no-pager" >&2
exit 1
