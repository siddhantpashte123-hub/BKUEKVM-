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
