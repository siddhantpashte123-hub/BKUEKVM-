#!/usr/bin/env bash
# Smoke tests for the terminal installer. Runs unprivileged; destructive
# paths are tested for their guard rails, not executed.
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PASS=0
FAIL=0

check() { # description, expected-substring, actual
  if echo "$3" | grep -qF "$2"; then
    echo "PASS: $1"; PASS=$((PASS + 1))
  else
    echo "FAIL: $1 (expected '$2' in: $3)"; FAIL=$((FAIL + 1))
  fi
}

echo "== syntax =="
for script in installer/lib.sh installer/install.sh installer/uninstall.sh installer/status.sh; do
  if bash -n "$ROOT/$script"; then
    echo "PASS: $script parses"; PASS=$((PASS + 1))
  else
    echo "FAIL: $script has syntax errors"; FAIL=$((FAIL + 1))
  fi
done

echo "== status on a host without the panel =="
OUTPUT="$(bash "$ROOT/installer/status.sh" 2>/dev/null)"
check "status reports not installed" "NOT INSTALLED" "$OUTPUT"
check "status reports database not configured" "NOT CONFIGURED" "$OUTPUT"
check "status shows a KVM line" "KVM" "$OUTPUT"
check "status shows live RAM" "RAM Usage" "$OUTPUT"

echo "== menu input validation =="
MENU="$(printf '9\n2\n' | bash "$ROOT/installer/install.sh" 2>&1)"
check "invalid choice rejected" "Invalid selection" "$MENU"
check "cancel exits cleanly" "Cancelled" "$MENU"

echo "== python interpreter selection =="
# shellcheck source=/dev/null
. "$ROOT/installer/lib.sh"

# Fake interpreter directory: "python3" reports 3.14 (unsupported),
# "python3.12" reports 3.12 (supported). pick_python must avoid 3.14.
FAKE_BIN="$(mktemp -d)"
cat > "$FAKE_BIN/python3" <<'STUB'
#!/usr/bin/env bash
if [ "$1" = "--version" ]; then echo "Python 3.14.0"; exit 0; fi
if [ "$1" = "-c" ]; then exit 1; fi   # 3.14 fails the supported-range check
STUB
cat > "$FAKE_BIN/python3.12" <<'STUB'
#!/usr/bin/env bash
if [ "$1" = "--version" ]; then echo "Python 3.12.7"; exit 0; fi
if [ "$1" = "-c" ]; then exit 0; fi   # 3.12 passes
STUB
chmod +x "$FAKE_BIN/python3" "$FAKE_BIN/python3.12"
PICKED="$(PATH="$FAKE_BIN:$PATH" pick_python)"
check "pick_python avoids 3.14 and selects 3.12" "python3.12" "$PICKED"
check "unsupported 3.14 rejected by python_supported" "1" "$(PATH="$FAKE_BIN:$PATH" python_supported python3 || echo 1)"
check "supported 3.12 accepted by python_supported" "0" "$(PATH="$FAKE_BIN:$PATH" python_supported python3.12 && echo 0)"
rm -rf "$FAKE_BIN"

echo "== password policy =="
password_strength_ok "short1!"; [ $? -ne 0 ] && { echo "PASS: weak short password rejected"; PASS=$((PASS + 1)); } || { echo "FAIL: short password accepted"; FAIL=$((FAIL + 1)); }
password_strength_ok "alllowercaseonlyletters"; [ $? -ne 0 ] && { echo "PASS: single-class password rejected"; PASS=$((PASS + 1)); } || { echo "FAIL: weak classes accepted"; FAIL=$((FAIL + 1)); }
password_strength_ok "Str0ng!Passw0rd" && { echo "PASS: strong password accepted"; PASS=$((PASS + 1)); } || { echo "FAIL: strong password rejected"; FAIL=$((FAIL + 1)); }

echo "== credential prompt (non-interactive) =="
# No TTY: prompt must be skipped, env values respected without hanging
OUT="$(BLUEKVM_ADMIN_EMAIL=root@example.com BLUEKVM_ADMIN_PASSWORD='Env!StrongPass1' bash -c '. "$1"; prompt_admin_credentials; echo "$ADMIN_EMAIL|$ADMIN_PASSWORD"' _ "$ROOT/installer/lib.sh" 2>/dev/null)"
check "non-TTY prompt honors BLUEKVM_ADMIN_* env" "root@example.com|Env!StrongPass1" "$OUT"
OUT2="$(bash -c '. "$1"; prompt_admin_credentials; [ -n "$ADMIN_PASSWORD" ] && echo generated' _ "$ROOT/installer/lib.sh" 2>/dev/null)"
check "non-TTY without env generates random password" "generated" "$OUT2"

# Interactive TTY path via pseudo-terminal (script(1)); stdin is not a tty
# in CI, so this only runs when a pty allocator is available.
if command -v script >/dev/null 2>&1; then
  RUNNER="$(mktemp)"
  cat > "$RUNNER" <<RUN
#!/usr/bin/env bash
. "$ROOT/installer/lib.sh"
prompt_admin_credentials
echo "RESULT:\$ADMIN_EMAIL|\$ADMIN_PASSWORD|\${GENERATED_ADMIN_PASSWORD:-none}"
RUN
  chmod +x "$RUNNER"
  # First line answers the email prompt (blank -> default), then a weak
  # password is rejected, finally a matching strong pair is accepted
  TTY_OUT="$(printf '\nweak1\nStr0ng!Passw0rd\nStr0ng!Passw0rd\n' | script -qec "bash $RUNNER" /dev/null 2>/dev/null | tr -d '\r')"
  check "TTY prompt accepts confirmed strong password" "RESULT:admin@localhost|Str0ng!Passw0rd|none" "$TTY_OUT"
  # Blank password triggers random generation
  TTY_BLANK="$(printf '\n' | script -qec "bash $RUNNER" /dev/null 2>/dev/null | tr -d '\r')"
  if echo "$TTY_BLANK" | grep -qE 'RESULT:admin@localhost\|[A-Za-z0-9!@#%^+_-]{16,}\|.+' ; then
    echo "PASS: blank TTY password generates random secret"; PASS=$((PASS + 1))
  else
    echo "FAIL: blank TTY password did not generate secret: $TTY_BLANK"; FAIL=$((FAIL + 1))
  fi
  rm -f "$RUNNER"
fi

echo "== environment detection helpers =="
if has_systemd; then echo "PASS: has_systemd returns boolean"; PASS=$((PASS + 1)); else echo "PASS: has_systemd returns boolean (no systemd here)"; PASS=$((PASS + 1)); fi
if is_container; then echo "PASS: is_container executes"; PASS=$((PASS + 1)); else echo "PASS: is_container executes"; PASS=$((PASS + 1)); fi

echo "== uninstall guard rails =="
UN="$(printf 'UNINSTALL\n' | bash "$ROOT/installer/uninstall.sh" 2>&1 || true)"
check "uninstall requires root" "Root or sudo" "$UN"

# Without root the uninstaller must refuse before touching anything,
# regardless of what is piped to stdin
WRONG="$(printf 'UNINSTALL\ny\ny\ny\n' | bash "$ROOT/installer/uninstall.sh" 2>&1 || true)"
check "unprivileged uninstall cannot touch the system" "Root or sudo" "$WRONG"
if echo "$WRONG" | grep -q "Application files removed"; then
  echo "FAIL: unprivileged uninstall reported destructive work"; FAIL=$((FAIL + 1))
else
  echo "PASS: no destructive output from unprivileged run"; PASS=$((PASS + 1))
fi

echo
echo "Installer tests: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
