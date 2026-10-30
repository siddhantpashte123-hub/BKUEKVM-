"""Regression tests for the installer upgrade's existing-config branch."""
import os
from pathlib import Path
import subprocess

import pytest


INSTALLER = Path(__file__).resolve().parents[2] / "installer" / "install.sh"


@pytest.mark.parametrize("port", ["8080", "8090", "8989"])
def test_upgrade_loads_but_never_rewrites_existing_configuration(tmp_path, port):
    config = tmp_path / ".env"
    content = ("BLUEKVM_SECRET_KEY=existing_secret\n"
               "BLUEKVM_CREDENTIAL_KEY=existing_fernet_key\n"
               "DATABASE_URL=sqlite:///existing.db\n"
               "BLUEKVM_ADMIN_USERNAME=existing_admin\n"
               f"BLUEKVM_PORT={port}\n")
    config.write_text(content)
    script = INSTALLER.read_text()
    start = script.index('  if [ "$UPGRADE" -eq 1 ]; then\n', script.index('# ------------------------------------------------------------- secrets/env'))
    end = script.index('\n  else\n', start)
    upgrade_branch = script[start:end] + '\n  fi\n'
    command = (
        'set -eu\nUPGRADE=1\nPANEL_PORT=8080\n'
        'ok() { :; }\ndie() { echo "$*" >&2; exit 1; }\n'
        + upgrade_branch
        + 'printf "%s|%s|%s|%s|%s" "$BLUEKVM_SECRET_KEY" "$BLUEKVM_CREDENTIAL_KEY" '
          '"$DATABASE_URL" "$ADMIN_USERNAME" "$PANEL_PORT"\n'
    )
    result = subprocess.run(
        ["bash", "-c", command], env={**os.environ, "ENV_FILE": str(config)},
        text=True, capture_output=True, check=True,
    )
    assert result.stdout == f"existing_secret|existing_fernet_key|sqlite:///existing.db|existing_admin|{port}"
    assert config.read_text() == content


def test_source_deploy_never_deletes_or_copies_existing_env():
    source = INSTALLER.read_text()
    deploy = source.split('# ------------------------------------------------------------- application --', 1)[1].split('  install -d -m 755 "$INSTALL_DIR/installer"', 1)[0]
    assert "--delete" not in deploy
    assert deploy.count("--exclude '.env'") == 2
    assert 'git clone "https://github.com/${GITHUB_REPO}.git" "$SOURCE_TMP/source"' in deploy
