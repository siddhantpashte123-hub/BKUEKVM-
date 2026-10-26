#!/usr/bin/env bash
# BLUEKVM PANNEL — safe uninstaller.
# By default only panel software and services are removed. VMs, images,
# backups and the database are PRESERVED and require explicit opt-in.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo .)"
if [ -f "$SCRIPT_DIR/lib.sh" ]; then
  # shellcheck source=lib.sh
  . "$SCRIPT_DIR/lib.sh"
else
  TMP_LIB="$(mktemp -t bluekvm-lib.XXXXXX.sh)"
  curl -fsSL "https://raw.githubusercontent.com/siddhantpashte123-hub/BKUEKVM-/main/installer/lib.sh" -o "$TMP_LIB" && . "$TMP_LIB"
fi

require_root

printf "%b" "${C_RED}"
cat <<'WARN'
========================================
       BLUEKVM PANNEL UNINSTALLER
========================================
WARN
printf "%b" "${C_RESET}"
warn "This stops and removes panel services and application files."
warn "By default VMs, OS images, backups and database data are PRESERVED."
echo
printf "Type UNINSTALL to continue: "
read -r CONFIRM
[ "$CONFIRM" = "UNINSTALL" ] || die "Uninstall aborted — nothing was changed."

# ------------------------------------------------------------- services ------
for svc in "${SERVICES[@]}"; do
  if systemctl list-unit-files "$svc.service" >/dev/null 2>&1; then
    info "Stopping and disabling $svc"
    systemctl disable --now "$svc" 2>/dev/null || true
    rm -f "/etc/systemd/system/$svc.service"
  fi
done
systemctl daemon-reload 2>/dev/null || true
ok "Panel services removed (libvirtd and unrelated services are untouched)"

# ------------------------------------------------------- explicit data choices --
REMOVE_APP=0
REMOVE_DATA=0
REMOVE_VMS=0
echo
printf "Remove application files at %s? [y/N]: " "$INSTALL_DIR"
read -r R1; [ "$R1" = "y" ] || [ "$R1" = "Y" ] && REMOVE_APP=1

printf "Remove panel DATABASE and settings (VMs remain)? [y/N]: "
read -r R2; [ "$R2" = "y" ] || [ "$R2" = "Y" ] && REMOVE_DATA=1

printf "%b" "${C_RED}Also delete ALL virtual machine disks, templates and backups under %s? [y/N]:%b " "$DATA_DIR" "$C_RESET"
read -r R3
if [ "$R3" = "y" ] || [ "$R3" = "Y" ]; then
  printf "This cannot be undone. Type DELETE-VMS to confirm: "
  read -r R4
  [ "$R4" = "DELETE-VMS" ] && REMOVE_VMS=1 || warn "VM data will be preserved."
fi

if [ "$REMOVE_APP" -eq 1 ]; then
  # Never follow symlinks; only the known application directory
  if [ -d "$INSTALL_DIR" ] && [ "$(realpath "$INSTALL_DIR")" != "/" ]; then
    rm -rf "$INSTALL_DIR"
    ok "Application files removed"
  fi
else
  info "Keeping $INSTALL_DIR"
fi

if [ "$REMOVE_DATA" -eq 1 ]; then
  rm -f "$DATA_DIR/bluekvm.db"
  info "If PostgreSQL is used, drop it manually with: dropdb bluekvm && dropuser bluekvm"
  ok "Panel database removed"
fi

if [ "$REMOVE_VMS" -eq 1 ]; then
  # Refuse to touch anything outside the managed data tree
  case "$DATA_DIR" in
    /var/lib/bluekvm*) rm -rf "$DATA_DIR/vms" "$DATA_DIR/templates" "$DATA_DIR/backups"; ok "VM disks, templates and backups deleted" ;;
    *) err "Refusing to delete unexpected path: $DATA_DIR" ;;
  esac
else
  info "Preserving $DATA_DIR (VMs, templates, backups)"
fi

rm -f /etc/nginx/sites-enabled/bluekvm* 2>/dev/null || true
id bluekvm >/dev/null 2>&1 && info "Service account 'bluekvm' retained for file ownership; remove manually with 'userdel bluekvm' if desired"
ok "Uninstall complete."
