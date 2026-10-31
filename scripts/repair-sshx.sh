#!/usr/bin/env bash
# Explicit repair for the observed zero-byte SSHX client. Never replaces a
# nonempty executable; preserves the empty original and does not touch VMs.
set -euo pipefail
[ "${1:-}" = --apply ] && [ "$#" -eq 1 ] || { echo 'Usage: sudo bash repair-sshx.sh --apply' >&2; exit 2; }
[ "$(id -u)" -eq 0 ] || { echo 'Run as root or with sudo.' >&2; exit 1; }
target=/usr/local/bin/sshx
[ -f "$target" ] && [ ! -L "$target" ] && [ ! -s "$target" ] || {
  echo 'SSHX is not an empty regular file; refusing to replace it.' >&2; exit 1;
}
id bluekvm >/dev/null 2>&1 || { echo 'Panel user bluekvm not found.' >&2; exit 1; }
case "$(uname -m)" in
  x86_64) arch=x86_64 ;;
  aarch64|arm64) arch=aarch64 ;;
  *) echo 'Unsupported architecture.' >&2; exit 1 ;;
esac
umask 077
temp=$(mktemp -d)
new=''
cleanup() { rm -rf -- "$temp"; [ -z "$new" ] || rm -f -- "$new"; }
trap cleanup EXIT
# Upstream provides no pinned checksum for this download. This is the same
# official upstream distribution used by the existing BLUEKVM installer.
curl --fail --silent --show-error --location --max-time 120 \
  "https://s3.amazonaws.com/sshx/sshx-${arch}-unknown-linux-musl.tar.gz" -o "$temp/sshx.tar.gz"
tar -xOzf "$temp/sshx.tar.gz" sshx > "$temp/sshx"
[ -s "$temp/sshx" ] || { echo 'Downloaded SSHX executable is empty.' >&2; exit 1; }
chmod 755 "$temp" "$temp/sshx"
if ! runuser -u bluekvm -- "$temp/sshx" --version 2>/dev/null | grep -qE '^sshx[[:space:]]'; then
  echo 'Downloaded SSHX executable failed its unprivileged version check.' >&2; exit 1
fi
# Recheck before preserving/replacing so a changed installation is not lost.
[ -f "$target" ] && [ ! -L "$target" ] && [ ! -s "$target" ] || {
  echo 'SSHX changed during download; refusing to overwrite it.' >&2; exit 1;
}
backup=$(mktemp -d /usr/local/bin/.sshx-backup.XXXXXX)
cp -p -- "$target" "$backup/sshx"
new=$(mktemp /usr/local/bin/.sshx-new.XXXXXX)
install -o root -g root -m 755 "$temp/sshx" "$new"
mv -fT -- "$new" "$target"
new=''
echo "SSHX installed. Original empty file preserved at $backup/sshx"
echo 'Try Open SSHX again; hosted relay connectivity still needs verification.'
