#!/usr/bin/env bash
# Local development launcher: backend on :8080, Vite dev server on :5173.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export BLUEKVM_ENV=development
export BLUEKVM_COOKIE_SECURE=0
export BLUEKVM_CSRF_ENABLED=0
export BLUEKVM_STARTUP_HEALTHCHECK=0
export DATABASE_URL="${DATABASE_URL:-sqlite:///$ROOT/backend/data/bluekvm.db}"
export BLUEKVM_VM_STORAGE_DIR="$ROOT/backend/data/vms"
export BLUEKVM_TEMPLATE_DIR="$ROOT/backend/data/templates"
export BLUEKVM_BACKUP_DIR="$ROOT/backend/data/backups"
export BLUEKVM_LOG_DIR="$ROOT/backend/data/logs"

echo "Starting BLUEKVM PANNEL backend on http://localhost:8080"
(
  cd "$ROOT/backend"
  [ -d .venv ] || python3 -m venv .venv
  . .venv/bin/activate
  pip install -q -r requirements-dev.txt
  uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
) &
API_PID=$!

echo "Starting Vite dev server on http://localhost:5173"
(
  cd "$ROOT/frontend"
  [ -d node_modules ] || npm install
  npm run dev
) &
WEB_PID=$!

trap 'kill $API_PID $WEB_PID 2>/dev/null || true' EXIT
wait
