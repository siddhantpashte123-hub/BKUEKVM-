#!/usr/bin/env bash
# BLUEKVM PANNEL — real installation/service status. Works even when uninstalled.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo .)"
if [ -f "$SCRIPT_DIR/lib.sh" ]; then
  # shellcheck source=lib.sh
  . "$SCRIPT_DIR/lib.sh"
else
  TMP_LIB="$(mktemp -t bluekvm-lib.XXXXXX.sh)"
  curl -fsSL "https://raw.githubusercontent.com/siddhantpashte123-hub/BKUEKVM-/main/installer/lib.sh" -o "$TMP_LIB" && . "$TMP_LIB"
fi

value() { # key file -> env value
  grep -E "^$1=" "$2" 2>/dev/null | head -1 | cut -d= -f2-
}

printf "%b" "${C_BLUE_BOLD}========================================${C_RESET}\n"
printf "%b" "${C_BLUE_BOLD}       BLUEKVM PANNEL STATUS${C_RESET}\n"
printf "%b" "${C_BLUE_BOLD}========================================${C_RESET}\n"

# ------------------------------------------------------------- installation --
if installed; then
  ok "Installation  : INSTALLED ($INSTALL_DIR)"
else
  warn "Installation  : NOT INSTALLED"
fi

# Honor the configured port without executing the environment file.
if installed; then
  CONFIGURED_PORT="$(value BLUEKVM_PORT "$ENV_FILE")"
  if [[ "$CONFIGURED_PORT" =~ ^[0-9]+$ ]] && [ "$CONFIGURED_PORT" -ge 1 ] && [ "$CONFIGURED_PORT" -le 65535 ]; then
    PANEL_PORT="$CONFIGURED_PORT"
  fi
fi

# ------------------------------------------------------------------ services --
# systemctl may exist inside a container even though systemd is not PID 1.
# In that case the installer uses a standalone uvicorn process with an embedded
# worker, not systemd units. A port listener alone is not proof it is BLUEKVM.
if has_systemd; then
  API_STATE="$(service_state bluekvm-api)"
  WORKER_STATE="$(service_state bluekvm-worker)"
  if [ "$API_STATE" = "active" ] && [ "$WORKER_STATE" = "active" ]; then
    ok "Service       : RUNNING (api=$API_STATE worker=$WORKER_STATE)"
  elif installed; then
    err "Service       : NOT FULLY RUNNING (api=$API_STATE worker=$WORKER_STATE)"
  else
    warn "Service       : NOT CONFIGURED"
  fi
elif installed; then
  PANEL_PID="$(standalone_panel_pid || true)"
  if [ -n "$PANEL_PID" ]; then
    if curl -fsS -m 4 "http://127.0.0.1:$PANEL_PORT/health/live" >/dev/null 2>&1; then
      ok "Service       : RUNNING (standalone API pid=$PANEL_PID; worker status not checked)"
    else
      warn "Service       : STARTED (standalone API pid=$PANEL_PID; health unavailable)"
    fi
  else
    warn "Service       : UNKNOWN (standalone process not detected; check Web Access below)"
  fi
else
  warn "Service       : NOT CONFIGURED"
fi

# ---------------------------------------------------------------------- port --
if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$PANEL_PORT$"; then
  ok "Port          : $PANEL_PORT (listening)"
else
  if installed; then err "Port          : $PANEL_PORT NOT LISTENING"; else warn "Port          : $PANEL_PORT free"; fi
fi

# --------------------------------------------------------------- web access --
if curl -fsS -m 4 "http://127.0.0.1:$PANEL_PORT/health/live" >/dev/null 2>&1; then
  ok "Web Access    : AVAILABLE (http://127.0.0.1:$PANEL_PORT)"
else
  if installed; then err "Web Access    : ERROR"; else warn "Web Access    : NOT CONFIGURED"; fi
fi

# ------------------------------------------------------------------ database --
if installed && [ -f "$ENV_FILE" ]; then
  DB_URL="$(value DATABASE_URL "$ENV_FILE")"
  case "$DB_URL" in
    sqlite:*)
      DB_FILE="${DB_URL#sqlite:///}"
      if [ -f "$DB_FILE" ]; then ok "Database      : CONNECTED (sqlite: $DB_FILE)"; else err "Database      : ERROR (missing $DB_FILE)"; fi
      ;;
    postgresql*)
      if command -v pg_isready >/dev/null 2>&1 && pg_isready -h 127.0.0.1 -q; then
        ok "Database      : CONNECTED (postgresql)"
      else
        err "Database      : ERROR (postgresql not ready)"
      fi
      ;;
    *) warn "Database      : UNKNOWN SCHEME" ;;
  esac
else
  warn "Database      : NOT CONFIGURED"
fi

# ----------------------------------------------------------------------- KVM --
if [ -e /dev/kvm ] && [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
  ok "KVM           : READY (/dev/kvm accessible)"
else
  warn "KVM           : NOT READY ($(detect_distro 2>/dev/null; uname -m); nested virt or modules may be missing)"
fi

# ------------------------------------------------------------------- python --
if [ -x "$INSTALL_DIR/backend/.venv/bin/python" ]; then
  ok "Python venv   : $("$INSTALL_DIR/backend/.venv/bin/python" --version 2>&1) ($INSTALL_DIR/backend/.venv)"
elif installed; then
  err "Python venv   : MISSING (re-run the installer or create it with python3.12 -m venv)"
else
  warn "Python venv   : NOT CONFIGURED"
fi

# ------------------------------------------------------------ live resources --
CPU_PERCENT="$(ps -A -o %cpu 2>/dev/null | awk -v cores="$(nproc)" '{s+=$1} END {printf "%.1f%%", s/cores}')"
MEM_LINE="$(free -m | awk '/Mem:/ {printf "%d MB / %d MB (%.1f%%)", $3, $2, $3/$2*100}')"
DISK_LINE="$(df -h / | awk 'NR==2 {printf "%s / %s (%s)", $3, $2, $5}')"
echo
printf "CPU Usage     : %s\n" "${CPU_PERCENT:-unavailable}"
printf "RAM Usage     : %s\n" "${MEM_LINE:-unavailable}"
printf "Disk Usage    : %s\n" "${DISK_LINE:-unavailable}"
printf "%b" "${C_BLUE_BOLD}========================================${C_RESET}\n"
