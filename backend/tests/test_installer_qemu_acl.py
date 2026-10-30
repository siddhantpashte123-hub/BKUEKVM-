"""Container-specific installer access and readiness regressions."""
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def test_container_acl_covers_existing_and_future_vm_and_template_files(tmp_path):
    data = tmp_path / "data"
    (data / "vms" / "blue").mkdir(parents=True)
    (data / "templates").mkdir()
    (data / "vms" / "blue" / "disk.qcow2").touch()
    (data / "templates" / "base.qcow2").touch()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    trace = tmp_path / "acl.log"
    stub = bindir / "setfacl"
    stub.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$TRACE"\n')
    stub.chmod(0o755)
    command = '''
. "$LIB"
DATA_DIR="$TARGET_DATA"
is_container() { return 0; }
getent() { echo 'libvirt-qemu:x:64055:107::/nonexistent:/usr/sbin/nologin'; }
prepare_container_qemu_acl
'''
    subprocess.run(["bash", "-ec", command], check=True, env={
        **os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "LIB": str(ROOT / "installer/lib.sh"),
        "TARGET_DATA": str(data), "TRACE": str(trace),
    }, capture_output=True, text=True)
    output = trace.read_text()
    assert "u:64055:--x" in output
    assert "d:u:64055:rwx" in output
    assert "u:64055:rw-" in output
    assert "u:64055:r--" in output
    assert "disk.qcow2" in output and "base.qcow2" in output


def test_readiness_accepts_compact_json():
    command = r'''printf '%s\n' '{"status":"ready"}' | grep -qE '"status"[[:space:]]*:[[:space:]]*"ready"' '''
    subprocess.run(["bash", "-ec", command], check=True)
    assert "grep -qE '\"status\"[[:space:]]*:[[:space:]]*\"ready\"'" in (ROOT / "installer/install.sh").read_text()
