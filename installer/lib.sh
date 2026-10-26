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

service_state() {
  local svc="$1"
  if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files "$svc.service" >/dev/null 2>&1 | grep -q "$svc"; then
    systemctl is-active "$svc" 2>/dev/null || true
  else
    echo "not_installed"
  fi
}
