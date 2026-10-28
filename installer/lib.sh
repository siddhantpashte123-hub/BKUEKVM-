#!/usr/bin/env bash
# BLUEKVM PANNEL — shared installer library
# Sourced by install.sh, uninstall.sh and status.sh.

# ------------------------------------------------------------------ palette --
if [ -t 1 ]; then
  C_RESET='\033[0m'
  C_BLUE='\033[38;5;75m'      # electric blue
  C_BLUE_BOLD='\033[1;38;5;75m'
  C_WHITE='\033[97m'
  C_GREEN='\033[32m'
  C_RED='\033[31m'
  C_YELLOW='\033[33m'
  C_GRAY='\033[90m'
else
  C_RESET=''; C_BLUE=''; C_BLUE_BOLD=''; C_WHITE=''; C_GREEN=''; C_RED=''; C_YELLOW=''; C_GRAY=''
fi

# ------------------------------------------------------------- installation --
INSTALL_DIR="/opt/bluekvm"
DATA_DIR="/var/lib/bluekvm"
LOG_DIR="/var/log/bluekvm"
ENV_FILE="$INSTALL_DIR/.env"
SERVICES=("bluekvm-api" "bluekvm-worker")
PANEL_PORT=8080

log()  { printf "%b\n" "${C_GRAY}[$(date +%H:%M:%S)]${C_RESET} ${C_WHITE}$*${C_RESET}"; }
info() { printf "%b\n" "${C_BLUE}[INFO]${C_RESET}  $*"; }
ok()   { printf "%b\n" "${C_GREEN}[ OK ]${C_RESET}  $*"; }
warn() { printf "%b\n" "${C_YELLOW}[WARN]${C_RESET} $*"; }
err()  { printf "%b\n" "${C_RED}[FAIL]${C_RESET} $*" >&2; }
die()  { err "$*"; exit 1; }

require_root() {
  if [ "$(id -u)" -ne 0 ]; then
    err "Root or sudo privileges are required."
    die  "Re-run with: sudo $0"
  fi
}

# ------------------------------------------------------------- system probes --
detect_distro() {
  if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    DISTRO="${ID:-unknown}"
    DISTRO_VERSION="${VERSION_ID:-unknown}"
    DISTRO_NAME="${PRETTY_NAME:-$DISTRO $DISTRO_VERSION}"
  else
    DISTRO="unknown"; DISTRO_VERSION="unknown"; DISTRO_NAME="unknown"
  fi
  case "$DISTRO" in
    ubuntu|debian) DISTRO_FAMILY="debian" ;;
    rhel|centos|rocky|almalinux|fedora|ol) DISTRO_FAMILY="rhel" ;;
    *) DISTRO_FAMILY="unknown" ;;
  esac
}

check_arch() {
  ARCH="$(uname -m)"
  case "$ARCH" in
    x86_64|aarch64) ok "CPU architecture: $ARCH (supported)" ;;
    *) warn "Architecture $ARCH is untested; x86_64/aarch64 are recommended" ;;
  esac
}

check_kvm() {
  if [ -e /dev/kvm ]; then
    if [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
      KVM_READY=1
      ok "KVM: /dev/kvm present and accessible"
    else
      KVM_READY=0
      warn "KVM: /dev/kvm exists but is not read/writable (check libvirt group membership)"
    fi
  else
    KVM_READY=0
    if grep -Eq 'vmx|svm' /proc/cpuinfo 2>/dev/null; then
      warn "KVM: CPU supports virtualization but /dev/kvm is missing (modules not loaded or nested virt disabled)"
    else
      warn "KVM: no VMX/SVM extensions exposed — nested virtualization is likely disabled by the hosting provider"
    fi
    warn "The panel will install, but VM creation requires a KVM-capable external node."
  fi
  if [ -d /sys/module/kvm_intel ] || [ -d /sys/module/kvm_amd ]; then
    local mod nested
    mod="kvm_intel"; [ -d /sys/module/kvm_amd ] && mod="kvm_amd"
    nested="$(cat /sys/module/$mod/parameters/nested 2>/dev/null || echo unknown)"
    info "Nested virtualization ($mod): $nested"
  fi
}

check_resources() {
  local mem_mb disk_gb cpus
  mem_mb="$(awk '/MemTotal/ {printf "%d", $2/1024}' /proc/meminfo)"
  disk_gb="$(df -BG --output=avail / | tail -1 | tr -dc '0-9')"
  cpus="$(nproc 2>/dev/null || echo 1)"
  info "Resources: $cpus vCPU · ${mem_mb} MB RAM · ${disk_gb} GB free disk"
  [ "$mem_mb" -ge 1800 ] || warn "Less than 2 GB RAM detected — the panel plus guests will be constrained"
  [ "$disk_gb" -ge 20 ] || warn "Less than 20 GB free disk — VM images and backups need substantial space"
}

check_port() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    if ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$port$"; then
      err "Port $port is already in use"
      return 1
    fi
  elif command -v netstat >/dev/null 2>&1; then
    if netstat -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$port$"; then
      err "Port $port is already in use"
      return 1
    fi
  fi
  ok "Port $port is available"
}

installed() { [ -d "$INSTALL_DIR" ] && [ -f "$ENV_FILE" ]; }

# --------------------------------------------------------- package repair --
# A previously interrupted apt/dpkg run blocks every later package operation
# ("dpkg was interrupted"). Repair it automatically before installing anything.
repair_package_state() {
  if [ "$DISTRO_FAMILY" = "debian" ]; then
    if command -v dpkg >/dev/null 2>&1; then
      info "Checking package manager state"
      dpkg --configure -a >/dev/null 2>&1 || warn "dpkg --configure -a reported issues"
      apt-get -f install -y >/dev/null 2>&1 || true
    fi
  elif [ "$DISTRO_FAMILY" = "rhel" ]; then
    command -v dnf >/dev/null 2>&1 && dnf -q clean all >/dev/null 2>&1 || true
  fi
}

# ------------------------------------------------------------ python pick --
# New interpreters (3.14+) lack prebuilt wheels for native deps such as
# pydantic-core, which forces a Rust source build and fails. Restrict the
# panel virtualenv to interpreters with full wheel coverage (3.10 - 3.13).
python_supported() {
  local bin="$1"
  command -v "$bin" >/dev/null 2>&1 || return 1
  "$bin" -c 'import sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] <= (3, 13) else 1)' 2>/dev/null
}

pick_python() {
  local candidate
  # Prefer mature, widely-wheeled interpreters first.
  for candidate in python3.12 python3.11 python3.13 python3.10; do
    if python_supported "$candidate"; then
      command -v "$candidate"
      return 0
    fi
  done
  if python_supported python3; then
    command -v python3
    return 0
  fi
  return 1
}

ensure_python() {
  local picked
  picked="$(pick_python 2>/dev/null || true)"
  if [ -n "$picked" ]; then
    PYTHON_BIN="$picked"
    return 0
  fi
  warn "No supported Python (3.10-3.13) found; attempting to install python3.12"
  if [ "$DISTRO_FAMILY" = "debian" ]; then
    apt-get install -y python3.12 python3.12-venv || true
  elif [ "$DISTRO_FAMILY" = "rhel" ]; then
    dnf install -y python3.12 || true
  fi
  picked="$(pick_python 2>/dev/null || true)"
  if [ -z "$picked" ]; then
    err "A supported Python interpreter (3.10 through 3.13) is required."
    err "Detected interpreter: $(python3 --version 2>&1 || echo 'python3 missing')."
    die "Install python3.12 (e.g. 'apt install python3.12 python3.12-venv') and re-run."
  fi
  PYTHON_BIN="$picked"
}

# ------------------------------------------------------- runtime detection --
has_systemd() {
  [ -d /run/systemd/system ] && command -v systemctl >/dev/null 2>&1
}

is_container() {
  [ -f /.dockerenv ] || grep -qE '(docker|containerd|kubepods|lxc)' /proc/1/cgroup 2>/dev/null
}

# -------------------------------------------------- credential interaction --
password_strength_ok() {
  local p="$1" classes=0
  [ "${#p}" -ge 12 ] || return 1
  printf '%s' "$p" | grep -q '[a-z]' && classes=$((classes + 1))
  printf '%s' "$p" | grep -q '[A-Z]' && classes=$((classes + 1))
  printf '%s' "$p" | grep -q '[0-9]' && classes=$((classes + 1))
  printf '%s' "$p" | grep -q '[^a-zA-Z0-9]' && classes=$((classes + 1))
  [ "$classes" -ge 3 ]
}

# Interactive admin setup. Non-interactive (piped/CI/container build) runs
# keep using BLUEKVM_ADMIN_* environment variables or a random password.
# Outputs: ADMIN_EMAIL, ADMIN_PASSWORD, GENERATED_ADMIN_PASSWORD.
prompt_admin_credentials() {
  ADMIN_EMAIL="${BLUEKVM_ADMIN_EMAIL:-admin@localhost}"
  ADMIN_PASSWORD="${BLUEKVM_ADMIN_PASSWORD:-}"
  GENERATED_ADMIN_PASSWORD=""

  # Explicit env-provided credentials always win (CI, automation, Docker)
  if [ -n "$ADMIN_PASSWORD" ]; then
    info "Using administrator password from BLUEKVM_ADMIN_PASSWORD"
    return 0
  fi

  if [ -t 0 ]; then
    printf "\n%bAdministrator account setup%b\n" "$C_BLUE_BOLD" "$C_RESET"
    if [ -z "${BLUEKVM_ADMIN_EMAIL:-}" ]; then
      printf "Administrator email [%s]: " "$ADMIN_EMAIL"
      read -r INPUT_EMAIL
      ADMIN_EMAIL="${INPUT_EMAIL:-$ADMIN_EMAIL}"
    fi

    while true; do
      printf "Administrator password (min 12 chars, blank = generate one): "
      read -rs P1; echo
      if [ -z "$P1" ]; then
        break
      fi
      if ! password_strength_ok "$P1"; then
        warn "Password needs at least 12 characters and 3 of: lowercase, uppercase, digit, symbol"
        continue
      fi
      printf "Confirm password: "
      read -rs P2; echo
      if [ "$P1" != "$P2" ]; then
        warn "Passwords do not match — try again"
        continue
      fi
      ADMIN_PASSWORD="$P1"
      return 0
    done
  fi

  # Interactive blank entry, piped curl installs, CI or container builds:
  # always end with a strong random password, never an empty secret.
  GENERATED_ADMIN_PASSWORD="$(openssl rand -base64 18 | tr -dc 'A-Za-z0-9!@#%^+_-' | head -c 20)"
  ADMIN_PASSWORD="$GENERATED_ADMIN_PASSWORD"
  [ -t 0 ] && ok "A random password will be generated and shown once after installation"
}

service_state() {
  local svc="$1"
  if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files "$svc.service" >/dev/null 2>&1 | grep -q "$svc"; then
    systemctl is-active "$svc" 2>/dev/null || true
  else
    echo "not_installed"
  fi
}
