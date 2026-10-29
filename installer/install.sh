#!/usr/bin/env bash
# =====================================================================
# BLUEKVM PANNEL — one-command installer with interactive menu
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/siddhantpashte123-hub/BKUEKVM-/main/installer/install.sh)
#
# Production recommendation: download a versioned release, verify its
# checksum, and execute the verified local copy instead of piping remote
# code straight into bash.
# =====================================================================
set -u

GITHUB_REPO="siddhantpashte123-hub/BKUEKVM-"
GITHUB_RAW="https://raw.githubusercontent.com/${GITHUB_REPO}/main"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo .)"

# Resolve shared library whether run from a checkout or piped over curl
if [ -f "$SCRIPT_DIR/lib.sh" ]; then
  # shellcheck source=lib.sh
  . "$SCRIPT_DIR/lib.sh"
else
  TMP_LIB="$(mktemp -t bluekvm-lib.XXXXXX.sh)"
  if ! curl -fsSL "$GITHUB_RAW/installer/lib.sh" -o "$TMP_LIB"; then
    printf '\033[31m[FAIL]\033[0m Cannot download installer library from %s\n' "$GITHUB_RAW" >&2
    exit 1
  fi
  # shellcheck disable=SC1090
  . "$TMP_LIB"
fi

print_banner() {
  clear 2>/dev/null || true
  printf "%b" "${C_BLUE_BOLD}"
  cat <<'BANNER'
╔══════════════════════════════════════════════╗
║                                              ║
║              BLUEKVM PANNEL                  ║
║                 INSTALLER                    ║
║                                              ║
╠══════════════════════════════════════════════╣
║                                              ║
║  1. INSTALL PANNEL                           ║
║  2. CANCEL                                   ║
║  3. UNINSTALL PANNEL                         ║
║  4. PANNEL STATUS                            ║
║                                              ║
╚══════════════════════════════════════════════╝
BANNER
  printf "%b" "${C_RESET}"
}

# ---------------------------------------------------------------- install --
do_install() {
  require_root
  echo
  info "Starting pre-installation checks"
  detect_distro
  info "Distribution: $DISTRO_NAME"
  check_arch
  check_resources
  check_kvm
  UPGRADE=0
  if installed; then
    UPGRADE=1
    warn "An existing BLUEKVM PANNEL installation was found at $INSTALL_DIR"
    printf "Continue and upgrade in place? Existing VMs and data are preserved [y/N]: "
    read -r CONFIRM
    [ "$CONFIRM" = "y" ] || [ "$CONFIRM" = "Y" ] || die "Installation cancelled."
  else
    [ ! -e "$ENV_FILE" ] || die "Existing configuration found; refusing to overwrite it."
    check_port "$PANEL_PORT" || die "Free port $PANEL_PORT and re-run the installer."
  fi

  echo
  info "Installing system dependencies"
  repair_package_state
  if [ "$DISTRO_FAMILY" = "debian" ]; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get install -y --no-install-recommends \
      python3 python3-venv python3-pip python3-libvirt \
      qemu-kvm qemu-utils libvirt-daemon-system libvirt-clients dnsmasq-base \
      genisoimage cloud-image-utils openssh-client \
      postgresql postgresql-contrib \
      nginx curl ca-certificates git rsync openssl \
      nodejs npm || die "Package installation failed."
  elif [ "$DISTRO_FAMILY" = "rhel" ]; then
    dnf install -y python3 python3-pip qemu-kvm libvirt libvirt-client libvirt-python3 \
      qemu-img genisoimage dnsmasq openssh-clients postgresql-server nginx curl git rsync openssl nodejs npm \
      || die "Package installation failed."
  else
    warn "Unrecognized distribution ($DISTRO). Installing runtime dependencies anyway."
    command -v python3 >/dev/null || die "python3 is required"
    command -v npm >/dev/null || die "Node.js/npm is required to build the frontend"
  fi
  start_libvirt
  configure_container_hypervisor
  # Reload daemons when the container profile changed qemu.conf
  if is_container && [ -f /etc/libvirt/qemu.conf ]; then
    _spawn_libvirt_daemons 2>/dev/null || true
  fi
  ensure_default_network
  ok "System dependencies installed"

  # ------------------------------------------------------------- users/dirs --
  id bluekvm >/dev/null 2>&1 || useradd --system --home "$DATA_DIR" --shell /usr/sbin/nologin bluekvm
  ensure_service_groups
  install -d -o bluekvm -g bluekvm "$INSTALL_DIR" "$DATA_DIR/vms" "$DATA_DIR/templates" "$DATA_DIR/backups" "$LOG_DIR"
  prepare_storage_permissions
  ok "Directories and service account ready"

  # ------------------------------------------------------------- application --
  info "Deploying application files to $INSTALL_DIR"
  # Repositories can inherit an owner different from the installing user
  # (containers, mounted volumes); whitelist the path before any git call.
  git config --global --add safe.directory "$INSTALL_DIR" 2>/dev/null || true
  if [ -d "$SCRIPT_DIR/../backend" ] && [ -d "$SCRIPT_DIR/../frontend" ]; then
    rsync -a --exclude '.venv' --exclude 'node_modules' --exclude 'dist' \
      --exclude '.git' --exclude '.env' --exclude '__pycache__' "$SCRIPT_DIR/../" "$INSTALL_DIR/"
  else
    if [ -d "$INSTALL_DIR/.git" ]; then
      git config --global --add safe.directory "$INSTALL_DIR" 2>/dev/null || true
      git -C "$INSTALL_DIR" pull --ff-only || die "git pull failed"
    else
      # Installations deployed from a source checkout may not contain .git.
      # Clone into a temporary directory rather than cloning over an existing
      # directory (which contains .env and other local state).
      SOURCE_TMP="$(mktemp -d)" || die "Could not create source staging directory."
      git clone "https://github.com/${GITHUB_REPO}.git" "$SOURCE_TMP/source" || {
        rm -rf "$SOURCE_TMP"
        die "Source download failed."
      }
      rsync -a --exclude '.git' --exclude '.env' --exclude '.venv' \
        --exclude 'node_modules' --exclude 'dist' --exclude '__pycache__' \
        "$SOURCE_TMP/source/" "$INSTALL_DIR/" || {
        rm -rf "$SOURCE_TMP"
        die "Source deployment failed."
      }
      rm -rf "$SOURCE_TMP"
    fi
  fi
  install -d -m 755 "$INSTALL_DIR/installer"
  cp -f "$SCRIPT_DIR"/*.sh "$INSTALL_DIR/installer/" 2>/dev/null || true

  install_sshx_client || die "SSHX client installation failed. Check outbound access to https://sshx.io and re-run."

  ensure_python
  ok "Using Python interpreter: $PYTHON_BIN ($("$PYTHON_BIN" --version 2>&1))"
  info "Creating Python virtual environment"
  # --system-site-packages is required so the distro python3-libvirt binding
  # (installed via apt, no PyPI wheel) is importable inside the venv.
  "$PYTHON_BIN" -m venv --system-site-packages "$INSTALL_DIR/backend/.venv"
  "$INSTALL_DIR/backend/.venv/bin/pip" install --upgrade pip >/dev/null
  "$INSTALL_DIR/backend/.venv/bin/pip" install -r "$INSTALL_DIR/backend/requirements.txt" \
    || die "Python dependency installation failed."
  verify_libvirt_binding "$INSTALL_DIR/backend/.venv/bin/python"
  ok "Backend dependencies installed"

  info "Building frontend"
  (cd "$INSTALL_DIR/frontend" && npm install --no-audit --no-fund && npm run build) \
    || die "Frontend build failed."
  ok "Frontend built"

  # ------------------------------------------------------------- secrets/env --
  if [ "$UPGRADE" -eq 1 ]; then
    # The Fernet key and database URL are essential for existing VM credentials
    # and data. Never regenerate or rewrite them during an upgrade.
    [ -f "$ENV_FILE" ] || die "Existing configuration is missing; upgrade aborted."
    set -a; . "$ENV_FILE"; set +a
    [ -n "${DATABASE_URL:-}" ] || die "Existing DATABASE_URL missing; upgrade aborted."
    ADMIN_USERNAME="${BLUEKVM_ADMIN_USERNAME:-admin}"
    GENERATED_ADMIN_PASSWORD=""
    case "$DATABASE_URL" in sqlite:*) DB_KIND="sqlite" ;; *) DB_KIND="existing database" ;; esac
    PANEL_PORT="${BLUEKVM_PORT:-$PANEL_PORT}"
    ok "Existing configuration and credentials preserved"
  else
    SECRET_KEY="$(openssl rand -hex 32)"
    CREDENTIAL_KEY="$("$INSTALL_DIR/backend/.venv/bin/python" -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
    ADMIN_USERNAME="${BLUEKVM_ADMIN_USERNAME:-admin}"
    # Interactive email/password prompt (no-ops for non-TTY/CI installs)
    prompt_admin_credentials

    DB_KIND="sqlite"
    DATABASE_URL="sqlite:///$DATA_DIR/bluekvm.db"
    if command -v psql >/dev/null 2>&1 && has_systemd; then
      info "Configuring PostgreSQL"
      PG_PASSWORD="$(openssl rand -hex 16)"
      if ! systemctl is-active --quiet postgresql; then
        if [ "$DISTRO_FAMILY" = "rhel" ]; then
          postgresql-setup --initdb 2>/dev/null || true
        fi
        systemctl enable --now postgresql
      fi
      su - postgres -c "psql -tc \"SELECT 1 FROM pg_roles WHERE rolname='bluekvm'\"" | grep -q 1 \
        || su - postgres -c "psql -c \"CREATE ROLE bluekvm LOGIN PASSWORD '$PG_PASSWORD';\""
      su - postgres -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname='bluekvm'\"" | grep -q 1 \
        || su - postgres -c "createdb -O bluekvm bluekvm"
      DATABASE_URL="postgresql+psycopg://bluekvm:${PG_PASSWORD}@127.0.0.1:5432/bluekvm"
      DB_KIND="postgresql"
      ok "PostgreSQL database 'bluekvm' ready"
    else
      warn "PostgreSQL not available — using SQLite at $DATA_DIR/bluekvm.db (development fallback)"
    fi

    umask 077
    cat > "$ENV_FILE" <<EOF
BLUEKVM_ENV=production
BLUEKVM_HOST=0.0.0.0
BLUEKVM_PORT=$PANEL_PORT
BLUEKVM_PUBLIC_URL=http://$(hostname -I 2>/dev/null | awk '{print $1}'):$PANEL_PORT
BLUEKVM_SECRET_KEY=$SECRET_KEY
BLUEKVM_CREDENTIAL_KEY=$CREDENTIAL_KEY
DATABASE_URL=$DATABASE_URL
BLUEKVM_ADMIN_USERNAME=$ADMIN_USERNAME
BLUEKVM_ADMIN_EMAIL=$ADMIN_EMAIL
BLUEKVM_ADMIN_PASSWORD=$ADMIN_PASSWORD
BLUEKVM_SESSION_TTL_MINUTES=720
BLUEKVM_COOKIE_SECURE=0
BLUEKVM_CSRF_ENABLED=1
BLUEKVM_LOGIN_RATE_PER_MINUTE=8
BLUEKVM_LIBVIRT_URI=qemu:///system
BLUEKVM_VM_STORAGE_DIR=$DATA_DIR/vms
BLUEKVM_TEMPLATE_DIR=$DATA_DIR/templates
BLUEKVM_BACKUP_DIR=$DATA_DIR/backups
BLUEKVM_LOG_LEVEL=INFO
BLUEKVM_LOG_DIR=$LOG_DIR
EOF
    chmod 600 "$ENV_FILE"
    ok "Environment file written with generated secrets"
  fi

  # ------------------------------------------------------------- migrations --
  info "Running database migrations"
  (cd "$INSTALL_DIR/backend" && . .venv/bin/activate && alembic upgrade head) \
    || die "Database migration failed."
  ok "Migrations applied"

  # ------------------------------------------------------------- services ----
  # A standalone start script works everywhere (containers, WSL, bare metal).
  cat > "$INSTALL_DIR/start-panel.sh" <<EOF
#!/usr/bin/env bash
# BLUEKVM PANNEL launcher (embedded worker; no systemd required)
set -euo pipefail
cd "$INSTALL_DIR/backend"
set -a; . "$ENV_FILE"; set +a
exec "$INSTALL_DIR/backend/.venv/bin/uvicorn" app.main:app \\
  --host 0.0.0.0 --port "\${BLUEKVM_PORT:-$PANEL_PORT}"
EOF
  chmod 755 "$INSTALL_DIR/start-panel.sh"

  if has_systemd; then
    install -m 644 "$INSTALL_DIR/deployment/bluekvm-api.service" /etc/systemd/system/
    install -m 644 "$INSTALL_DIR/deployment/bluekvm-worker.service" /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable bluekvm-worker bluekvm-api || die "Could not enable services."
    systemctl restart bluekvm-worker bluekvm-api || die "Services failed to start."
    ok "systemd services enabled and started"
  else
    warn "systemd is not available (container/WSL). Installing start script instead."
    if is_container; then info "Container environment detected"; fi
    # Best-effort immediate start; restarts are the orchestrator's responsibility.
    pkill -f "uvicorn app.main:app" 2>/dev/null || true
    nohup "$INSTALL_DIR/start-panel.sh" >>"$LOG_DIR/panel.out.log" 2>&1 &
    sleep 2
    ok "Panel launched in background (log: $LOG_DIR/panel.out.log)"
    info "Start manually any time with: $INSTALL_DIR/start-panel.sh"
  fi

  # ------------------------------------------------------------- health ------
  info "Running health checks"
  HEALTHY=0
  for _ in $(seq 1 15); do
    if curl -fsS "http://127.0.0.1:$PANEL_PORT/health/ready" 2>/dev/null | grep -q '"status": "ready"'; then
      HEALTHY=1; break
    fi
    sleep 2
  done

  # Probe the local hypervisor once so the local node flips from
  # "unconfigured" to online/offline with the real KVM reason recorded.
  info "Probing local virtualization node"
  (
    cd "$INSTALL_DIR/backend"
    . .venv/bin/activate
    set -a; . "$ENV_FILE"; set +a
    python - <<'PY'
from app.database import Base, SessionLocal, engine
from app.bootstrap import run_bootstrap
from app.models import Node
from app.virtualization.manager import manager

Base.metadata.create_all(bind=engine)
db = SessionLocal()
run_bootstrap(db, health_check=False)
node = db.query(Node).filter(Node.is_local.is_(True)).first()
if node:
    manager.health_check(db, node)
    print(f"node={node.name} status={node.status.value} kvm_ready={node.kvm_ready}")
    if node.last_error:
        print(f"reason={node.last_error}")
PY
  ) || warn "Node probe failed — open Virtualization Nodes and click Verify connection"

  # The recursive application ownership pass is intentionally followed by a
  # final QEMU DAC pass: otherwise a repeat installer run changes VM disks
  # back to bluekvm:bluekvm and QEMU cannot boot an existing guest.
  chown -R bluekvm:bluekvm "$DATA_DIR" "$LOG_DIR" "$INSTALL_DIR" 2>/dev/null || true
  prepare_storage_permissions

  echo
  printf "%b" "${C_BLUE_BOLD}========================================${C_RESET}\n"
  printf "%b" "${C_BLUE_BOLD}       BLUEKVM PANNEL INSTALLED${C_RESET}\n"
  printf "%b" "${C_BLUE_BOLD}========================================${C_RESET}\n"
  if [ "$HEALTHY" -eq 1 ]; then ok "Health check passed"; else err "Health check did not pass — inspect: journalctl -u bluekvm-api"; fi
  echo "  Dashboard : http://$(hostname -I 2>/dev/null | awk '{print $1}'):$PANEL_PORT"
  echo "  Username  : $ADMIN_USERNAME"
  if [ -n "$GENERATED_ADMIN_PASSWORD" ]; then
    printf "  Password  : %b%s%b  (shown once — store it now)\n" "$C_YELLOW" "$GENERATED_ADMIN_PASSWORD" "$C_RESET"
  else
    echo "  Password  : (the one you entered, or supplied via BLUEKVM_ADMIN_PASSWORD)"
  fi
  echo "  Database  : $DB_KIND"
  if [ "${KVM_READY:-0}" -eq 0 ]; then
    warn "KVM is not usable on this host. Register a KVM-capable node under Virtualization Nodes."
  fi
  echo "  Logs      : journalctl -u bluekvm-api -f"
}

# --------------------------------------------------------------- menu loop --
main() {
  while true; do
    print_banner
    echo
    printf "%bEnter your choice [1-4]:%b " "$C_WHITE" "$C_RESET"
    read -r CHOICE
    case "$CHOICE" in
      1)
        do_install
        echo; printf "Press Enter to return to the menu…"; read -r _
        ;;
      2)
        info "Cancelled — no changes were made."
        exit 0
        ;;
      3)
        if [ -f "$SCRIPT_DIR/uninstall.sh" ]; then
          bash "$SCRIPT_DIR/uninstall.sh"
        else
          TMP_UN="$(mktemp -t bluekvm-uninstall.XXXXXX.sh)"
          curl -fsSL "$GITHUB_RAW/installer/uninstall.sh" -o "$TMP_UN" && bash "$TMP_UN"
        fi
        echo; printf "Press Enter to return to the menu…"; read -r _
        ;;
      4)
        if [ -f "$SCRIPT_DIR/status.sh" ]; then
          bash "$SCRIPT_DIR/status.sh"
        else
          TMP_ST="$(mktemp -t bluekvm-status.XXXXXX.sh)"
          curl -fsSL "$GITHUB_RAW/installer/status.sh" -o "$TMP_ST" && bash "$TMP_ST"
        fi
        echo
        printf "1. BACK TO MENU\n2. EXIT\nChoose [1-2]: "
        read -r SUB
        [ "$SUB" = "2" ] && exit 0
        ;;
      *)
        err "Invalid selection — please enter 1, 2, 3 or 4."
        sleep 1
        ;;
    esac
  done
}

main "$@"
