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

# Start the libvirt daemon on systemd hosts, SysV-shim hosts, and bare
# containers that ship neither (e.g. GitHub Codespaces: Ubuntu 24.04 images
# only contain systemd units, so 'service' reports "unrecognized service").
start_libvirt() {
  mkdir -p /run/libvirt /var/run/libvirt 2>/dev/null || true
  if has_systemd; then
    systemctl enable --now libvirtd 2>/dev/null \
      || systemctl enable --now virtqemud 2>/dev/null || true
  elif command -v service >/dev/null 2>&1; then
    service libvirtd start 2>/dev/null || service virtqemud start 2>/dev/null || true
  fi

  if ! _libvirt_socket_present; then
    _spawn_libvirt_daemons
  fi

  # Give the socket a moment to appear
  local i
  for i in $(seq 1 12); do
    _libvirt_socket_present && return 0
    sleep 1
  done
  warn "libvirt socket did not appear — VM provisioning will stay blocked until libvirtd runs"
  return 0
}

_libvirt_socket_present() {
  [ -S /var/run/libvirt/libvirt-sock ] || [ -S /run/libvirt/libvirt-sock ]
}

# Last-resort manual daemon startup used in init-less containers. Tries the
# monolithic libvirtd first, then the modular virt* daemons (noble default).
_spawn_libvirt_daemons() {
  if command -v libvirtd >/dev/null 2>&1; then
    libvirtd -d 2>/dev/null || nohup libvirtd >/var/log/libvirtd-manual.log 2>&1 &
    sleep 1
  fi
  local d
  for d in virtlogd virtlockd virtnodedevd virtnetworkd virtstoraged virtqemud virtproxyd; do
    if command -v "$d" >/dev/null 2>&1 && ! pgrep -x "$d" >/dev/null 2>&1; then
      "$d" --daemon 2>/dev/null || nohup "$d" >"/var/log/${d}-manual.log" 2>&1 &
    fi
  done
}

# In containers without systemd/polkit the unprivileged libvirt-qemu account
# often cannot open /dev/ptmx or storage files. Running QEMU as root matches
# the single-tenant trust model of such test containers. On real systemd
# hosts this is intentionally NOT applied (dynamic DAC handles permissions).
configure_container_hypervisor() {
  is_container || return 0
  local conf="${BLUEKVM_QEMU_CONF:-/etc/libvirt/qemu.conf}"
  [ -f "$conf" ] || return 0
  if grep -q "BLUEKVM container override" "$conf" 2>/dev/null; then
    return 0
  fi
  cat >> "$conf" <<'EOF'

# BLUEKVM container override: restrictive devpts/DAC in init-less containers
# blocks the unprivileged libvirt-qemu account (PTY creation, storage access).
# Do not use on multi-tenant or systemd-managed production hosts.
user = "root"
group = "root"
EOF
  # Relax devpts so QEMU can allocate serial PTYs (best effort; some
  # containers forbid remount and that is fine with type=user networking).
  mount -o remount,ptmxmode=0666 /dev/pts 2>/dev/null || true
  ok "Container hypervisor profile applied (QEMU runs as root inside container)"
}

# Define + start the standard 'default' NAT network so freshly provisioned
# VMs receive DHCP leases. Best effort: unprivileged containers may lack
# CAP_NET_ADMIN, in which case the driver's type=user fallback still works.
ensure_default_network() {
  command -v virsh >/dev/null 2>&1 || return 0
  _libvirt_socket_present || return 0
  if ! virsh -c qemu:///system net-info default >/dev/null 2>&1; then
    cat >/tmp/bluekvm-default-net.xml <<'XML'
<network>
  <name>default</name>
  <forward mode='nat'/>
  <bridge name='virbr0' stp='on' delay='0'/>
  <ip address='192.168.122.1' netmask='255.255.255.0'>
    <dhcp><range start='192.168.122.2' end='192.168.122.254'/></dhcp>
  </ip>
</network>
XML
    virsh -c qemu:///system net-define /tmp/bluekvm-default-net.xml >/dev/null 2>&1 || true
    rm -f /tmp/bluekvm-default-net.xml
  fi
  virsh -c qemu:///system net-autostart default >/dev/null 2>&1 || warn "Could not enable default network autostart."
  if ! LC_ALL=C virsh -c qemu:///system net-info default 2>/dev/null | grep -Eq 'Active:[[:space:]]+yes'; then
    if ! virsh -c qemu:///system net-start default; then
      warn "Default NAT network could not start; check dnsmasq and host CAP_NET_ADMIN before creating VPSes."
    fi
  fi
}

# Grant the panel account access to libvirt and /dev/kvm. Distributions name
# the groups slightly differently, so only touch groups that actually exist.
ensure_service_groups() {
  command -v usermod >/dev/null 2>&1 || return 0
  id bluekvm >/dev/null 2>&1 || return 0
  local grp
  for grp in libvirt libvirt-qemu kvm; do
    if getent group "$grp" >/dev/null 2>&1; then
      usermod -aG "$grp" bluekvm 2>/dev/null || true
    fi
  done
}

# Resolve the group QEMU runs as from qemu.conf, falling back to the common
# distribution names. Echoes the group name; empty when nothing matches.
qemu_group() {
  local conf="${BLUEKVM_QEMU_CONF:-/etc/libvirt/qemu.conf}" name
  if [ -f "$conf" ]; then
    name="$(sed -n 's/^[[:space:]]*group[[:space:]]*=[[:space:]]*["'\'']\?\([^"'\'']*\).*/\1/p' "$conf" | tail -1)"
    [ -n "$name" ] && getent group "$name" >/dev/null 2>&1 && { echo "$name"; return 0; }
  fi
  for name in libvirt-qemu kvm libvirt; do
    getent group "$name" >/dev/null 2>&1 && { echo "$name"; return 0; }
  done
  return 0
}

# Give the hypervisor group read/write access to VM storage. On systemd hosts
# libvirt dynamic DAC already handles this, so this is a belt-and-braces step
# that makes init-less containers work without manual chgrp/chmod.
prepare_storage_permissions() {
  local grp
  grp="$(qemu_group)"
  [ -n "$grp" ] || return 0
  local dir
  # QEMU needs traverse permission on the root and container directories too;
  # fixing only a qcow2 file still fails with EACCES during domain start.
  for dir in "$DATA_DIR" "$DATA_DIR/vms" "$DATA_DIR/templates" "$DATA_DIR/backups"; do
    [ -d "$dir" ] || continue
    chgrp "$grp" "$dir" 2>/dev/null || true
    chmod 2750 "$dir" 2>/dev/null || true
  done
  for dir in "$DATA_DIR/vms" "$DATA_DIR/templates" "$DATA_DIR/backups"; do
    [ -d "$dir" ] || continue
    chgrp -R "$grp" "$dir" 2>/dev/null || true
    find "$dir" -type d -exec chmod 2750 {} + 2>/dev/null || true
    find "$dir" -type f -exec chmod 660 {} + 2>/dev/null || true
  done
}

# Install the official, statically-linked sshx.io client in a root-owned
# executable location. Hosted SSHX is an explicit panel feature: failure to
# fetch the client is actionable and must not produce a fake terminal URL.
install_sshx_client() {
  local target="/usr/local/bin/sshx" arch temp
  if [ -x "$target" ]; then
    "$target" --version >/dev/null 2>&1 && { ok "SSHX client available"; return 0; }
    err "Existing SSHX executable failed its version check; refusing to overwrite it"
    return 1
  fi
  [ ! -e "$target" ] || { err "Existing $target is not executable; refusing to overwrite it"; return 1; }
  case "$(uname -m)" in
    x86_64) arch=x86_64 ;;
    aarch64|arm64) arch=aarch64 ;;
    *) err "SSHX binary unavailable for this architecture"; return 1 ;;
  esac
  temp="$(mktemp -d)" || return 1
  chmod 700 "$temp"
  info "Downloading the official hosted SSHX client"
  # Upstream currently publishes unversioned binaries without checksums. Fetch
  # via HTTPS and extract only the expected file, never execute a download script.
  if ! curl --fail --silent --show-error --location --max-time 120 \
    "https://s3.amazonaws.com/sshx/sshx-${arch}-unknown-linux-musl.tar.gz" -o "$temp/sshx.tar.gz" ||
    ! tar -xOzf "$temp/sshx.tar.gz" sshx > "$temp/sshx" || [ ! -s "$temp/sshx" ]; then
    rm -rf "$temp"
    err "Could not download/extract the official SSHX client"
    return 1
  fi
  chmod 755 "$temp" "$temp/sshx"
  # Never execute a freshly downloaded third-party binary as root.
  if ! runuser -u bluekvm -- "$temp/sshx" --version >/dev/null 2>&1; then
    rm -rf "$temp"
    err "Downloaded SSHX client failed its version check"
    return 1
  fi
  install -o root -g root -m 755 "$temp/sshx" "$target"
  rm -rf "$temp"
  ok "SSHX client installed"
}

# In init-less containers libvirt may keep using its distribution QEMU user
# even after qemu.conf was edited (the running daemon has not reloaded it).
# Grant only that named user access to panel-managed VM/template trees. Default
# ACLs make future disks, seed ISOs and downloaded backing images accessible.
# This is not a substitute for libvirt DAC on normal production hosts.
prepare_container_qemu_acl() {
  is_container || return 0
  local entry uid tree
  entry="$(getent passwd libvirt-qemu 2>/dev/null || getent passwd qemu 2>/dev/null || true)"
  [ -n "$entry" ] || { warn "QEMU runtime user not found; verify storage and KVM access manually"; return 0; }
  uid="$(printf '%s' "$entry" | cut -d: -f3)"
  command -v setfacl >/dev/null 2>&1 || { warn "setfacl missing; QEMU access could not be configured"; return 0; }
  setfacl -m "u:$uid:--x" "$DATA_DIR" || { warn "Cannot grant QEMU storage traversal"; return 0; }
  tree="$DATA_DIR/vms"
  if [ -d "$tree" ]; then
    find "$tree" -type d -exec setfacl -m "u:$uid:r-x,d:u:$uid:rwx" {} + || warn "Cannot set QEMU directory ACLs on $tree"
    find "$tree" -type f -exec setfacl -m "u:$uid:rw-" {} + || warn "Cannot set QEMU file ACLs on $tree"
  fi
  tree="$DATA_DIR/templates"
  if [ -d "$tree" ]; then
    find "$tree" -type d -exec setfacl -m "u:$uid:r-x,d:u:$uid:r-x" {} + || warn "Cannot set QEMU directory ACLs on $tree"
    find "$tree" -type f -exec setfacl -m "u:$uid:r--" {} + || warn "Cannot set QEMU file ACLs on $tree"
  fi
  if [ -e /dev/kvm ]; then
    if ! setfacl -m "u:$uid:rw-" /dev/kvm; then
      warn "Could not grant QEMU access to /dev/kvm; check host device policy."
    elif command -v setpriv >/dev/null 2>&1; then
      if ! setpriv --reuid="$uid" --regid="$(printf '%s' "$entry" | cut -d: -f4)" --clear-groups -- \
        python3 -c 'import os; fd=os.open("/dev/kvm", os.O_RDWR); os.close(fd)' 2>/dev/null; then
        warn "QEMU user cannot open /dev/kvm; host device policy or permissions may block KVM."
      fi
    else
      warn "setpriv missing; QEMU /dev/kvm access could not be verified."
    fi
  fi
}

# The apt-provided python3-libvirt binding lives in the system dist-packages
# tree; a default isolated venv cannot import it. This verifies the binding is
# visible and emits an actionable warning (the venv is created with
# --system-site-packages by the installer).
verify_libvirt_binding() {
  local venv_python="$1"
  if "$venv_python" -c 'import libvirt' >/dev/null 2>&1; then
    ok "libvirt Python binding visible in virtualenv"
    return 0
  fi
  warn "libvirt Python binding not visible inside the virtualenv"
  warn "Install it for the same interpreter, e.g.: apt-get install -y python3-libvirt"
  warn "then re-run the installer (the venv is built with --system-site-packages)."
}

is_container() {
  [ "${BLUEKVM_FORCE_CONTAINER:-}" = "1" ] && return 0
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
