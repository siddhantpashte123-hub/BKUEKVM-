"""Regression tests for damaged virtualenv detection and opt-in repair.

System commands in the repair tests are stubs. No real services or package
managers are touched, and the temporary install is not a real libvirt host.
"""
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "installer/lib.sh"
REPAIR = ROOT / "scripts/repair-venv.sh"


def executable(path: Path, body: str):
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(0o755)


def test_core_venv_checks_both_imports_and_uvicorn_executable(tmp_path):
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    executable(venv / "bin/python", 'exit "${FAKE_IMPORT_EXIT:-0}"')
    executable(venv / "bin/uvicorn", 'exit "${FAKE_UVICORN_EXIT:-0}"')
    command = '. "$1"; venv_core_usable "$2"'

    def check(**variables):
        return subprocess.run(
            ["bash", "-c", command, "_", str(LIB), str(venv)],
            env={**os.environ, **variables}, capture_output=True,
        ).returncode

    assert check() == 0
    assert check(FAKE_IMPORT_EXIT="1") != 0
    assert check(FAKE_UVICORN_EXIT="1") != 0
    (venv / "bin/uvicorn").write_text("not an executable format\n")
    # The same corrupt script reports an exec-format failure from bash.
    assert check() != 0


def setup_repair(tmp_path):
    install = tmp_path / "install"
    backend = install / "backend"
    old = backend / ".venv/bin"
    old.mkdir(parents=True)
    executable(old / "python", 'echo 3.10')
    (backend / ".venv/sentinel").write_text("original venv")
    (backend / "requirements.txt").write_text("sqlalchemy==2.0.36\n")
    (install / ".env").write_text("BLUEKVM_PORT=8989\nDATABASE_URL=unchanged\n")
    disk = tmp_path / "vm-disk.qcow2"
    disk.write_text("unchanged disk")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "commands.log"
    executable(bin_dir / "id", 'if [ "$1" = "-u" ]; then echo 0; fi; exit 0')
    executable(bin_dir / "systemctl", '''
printf 'systemctl %s\\n' "$*" >> "$TEST_LOG"
case "$1" in show) echo loaded ;; esac
exit 0''')
    executable(bin_dir / "runuser", 'shift 3; exec "$@"')
    executable(bin_dir / "chown", 'printf "chown %s\\n" "$*" >> "$TEST_LOG"; exit 0')
    executable(bin_dir / "curl", 'echo \'{"status":"ready"}\'')
    executable(bin_dir / "sleep", 'exit 0')
    executable(bin_dir / "python3.10", r'''
if [ "$1" = "-c" ]; then exit 0; fi
if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
  target="$4"
  /bin/mkdir -p "$target/bin"
  /bin/cat > "$target/bin/python" <<'PY'
#!/bin/sh
if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then
  printf 'pip %s\n' "$*" >> "$TEST_LOG"
  if [ "${FAIL_PIP:-0}" = 1 ] && [ "$3" = "install" ]; then exit 1; fi
fi
exit 0
PY
  /bin/cat > "$target/bin/uvicorn" <<'UV'
#!/bin/sh
exit 0
UV
  /bin/chmod +x "$target/bin/python" "$target/bin/uvicorn"
  exit 0
fi
exit 1''')
    env = {
        **os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin", "BLUEKVM_INSTALL_DIR": str(install),
        "TEST_LOG": str(log),
    }
    return install, disk, log, env


def test_installer_checks_existing_venv_before_modifying_it():
    source = (ROOT / "installer/install.sh").read_text()
    start = source.index('  if [ -e "$VENV" ]; then')
    end = source.index('  "$VENV/bin/python" -m pip install --upgrade pip', start)
    block = source[start:end]
    assert 'venv_core_usable "$VENV" || die' in block
    assert '"$PYTHON_BIN" -m venv' in block.split('  else\n', 1)[1]
    assert 'rm -rf' not in block and 'mv ' not in block


def test_repair_requires_explicit_apply(tmp_path):
    install, disk, log, env = setup_repair(tmp_path)
    result = subprocess.run(["bash", str(REPAIR)], capture_output=True, text=True, env=env)
    assert result.returncode != 0
    assert not log.exists()
    assert (install / "backend/.venv/sentinel").read_text() == "original venv"
    assert disk.read_text() == "unchanged disk"


def test_repair_backs_up_old_venv_and_checks_services(tmp_path):
    install, disk, log, env = setup_repair(tmp_path)
    before = (install / ".env").read_bytes()
    result = subprocess.run(["bash", str(REPAIR), "--apply"], capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr + result.stdout
    backups = list((install / "backend").glob(".venv-backup.*/original-venv/sentinel"))
    assert len(backups) == 1 and backups[0].read_text() == "original venv"
    assert (install / ".env").read_bytes() == before
    assert disk.read_text() == "unchanged disk"
    commands = log.read_text()
    assert "systemctl stop bluekvm-api.service bluekvm-worker.service" in commands
    assert "psycopg[binary]==3.2.10" in commands
    assert "systemctl start bluekvm-api.service bluekvm-worker.service" in commands
    assert "readiness check passed" in result.stdout


def test_invalid_configured_port_aborts_before_stopping_services(tmp_path):
    install, disk, log, env = setup_repair(tmp_path)
    (install / ".env").write_text("BLUEKVM_PORT=invalid\n")
    result = subprocess.run(["bash", str(REPAIR), "--apply"], capture_output=True, text=True, env=env)
    assert result.returncode != 0
    assert "Invalid panel port" in result.stderr
    assert "systemctl stop" not in log.read_text()
    assert (install / "backend/.venv/sentinel").read_text() == "original venv"
    assert disk.read_text() == "unchanged disk"


def test_repair_failure_preserves_backup_and_does_not_start_services(tmp_path):
    install, disk, log, env = setup_repair(tmp_path)
    before = (install / ".env").read_bytes()
    result = subprocess.run(["bash", str(REPAIR), "--apply"], capture_output=True, text=True,
                            env={**env, "FAIL_PIP": "1"})
    assert result.returncode != 0
    backups = list((install / "backend").glob(".venv-backup.*/original-venv/sentinel"))
    assert len(backups) == 1 and backups[0].read_text() == "original venv"
    assert (install / ".env").read_bytes() == before
    assert disk.read_text() == "unchanged disk"
    assert "systemctl start" not in log.read_text()
    assert "Previous venv is preserved" in result.stderr
