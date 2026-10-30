"""Installer must not mix NodeSource nodejs with distro npm."""
import os
from pathlib import Path
import subprocess

import pytest

LIB = Path(__file__).resolve().parents[2] / "installer" / "lib.sh"
INSTALLER = Path(__file__).resolve().parents[2] / "installer" / "install.sh"


def executable(path, content):
    path.write_text("#!/bin/sh\n" + content + "\n")
    path.chmod(0o755)


def setup_commands(tmp_path, *, node_version=None, npm=False, package_version="22.23.4-1nodesource1"):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if node_version:
        executable(bin_dir / "node", f'echo "{node_version}"')
    if npm:
        executable(bin_dir / "npm", 'echo "10.8.0"')
    executable(bin_dir / "dpkg-query", f'echo "{package_version}"')
    # Mock apt: install distribution node/npm without touching the host.
    executable(bin_dir / "apt-get", '''
printf '%s\\n' "$*" >> "$APT_LOG"
case "$*" in
  *nodejs*) printf '#!/bin/sh\\necho v20.19.0\\n' > "$FAKE_BIN/node"; /bin/chmod +x "$FAKE_BIN/node" ;;
  *npm*) printf '#!/bin/sh\\necho 10.8.0\\n' > "$FAKE_BIN/npm"; /bin/chmod +x "$FAKE_BIN/npm" ;;
esac''')
    log = tmp_path / "apt.log"
    env = {**os.environ, "PATH": str(bin_dir), "APT_LOG": str(log), "FAKE_BIN": str(bin_dir)}
    result = subprocess.run(
        ["/bin/bash", "-c", '. "$1"; ensure_debian_nodejs_npm', "_", str(LIB)],
        capture_output=True, text=True, env=env,
    )
    return result, log.read_text() if log.exists() else ""


def test_nodesource_existing_node_and_npm_never_requests_distro_npm(tmp_path):
    result, apt = setup_commands(tmp_path, node_version="v22.23.4", npm=True)
    assert result.returncode == 0, result.stderr
    assert "Node.js v22.23.4" in result.stdout
    assert apt == ""


def test_distro_node_without_npm_installs_only_npm(tmp_path):
    result, apt = setup_commands(tmp_path, node_version="v20.19.0", package_version="20.19.0+dfsg")
    assert result.returncode == 0, result.stderr
    assert "npm" in apt
    assert "nodejs" not in apt


def test_fresh_node_and_npm_are_installed_separately(tmp_path):
    result, apt = setup_commands(tmp_path, package_version="20.19.0+dfsg")
    assert result.returncode == 0, result.stderr
    assert len(apt.splitlines()) == 2
    assert "nodejs" in apt.splitlines()[0]
    assert "npm" in apt.splitlines()[1]


def test_nodesource_missing_npm_fails_without_replacing_node(tmp_path):
    result, apt = setup_commands(tmp_path, node_version="v22.23.4")
    assert result.returncode != 0
    assert "NodeSource" in result.stderr
    assert apt == ""


def test_old_node_is_rejected_without_package_mutation(tmp_path):
    result, apt = setup_commands(tmp_path, node_version="v16.20.2", npm=True)
    assert result.returncode != 0
    assert "18 or newer" in result.stderr
    assert apt == ""


def test_debian_package_list_does_not_install_nodejs_and_npm_together():
    source = INSTALLER.read_text()
    block = source.split('if [ "$DISTRO_FAMILY" = "debian" ]; then', 1)[1].split('elif [ "$DISTRO_FAMILY" = "rhel" ]', 1)[0]
    assert "ensure_debian_nodejs_npm" in block
    assert "nodejs npm" not in block
