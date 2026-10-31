"""Offline mocked tests: no actual SSHX download or host files are modified."""
import os
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]


def test_installer_rejects_empty_existing_client():
    text = (ROOT / 'installer/lib.sh').read_text()
    existing = text.split('install_sshx_client() {', 1)[1].split('  case ', 1)[0]
    assert '[ -s "$target" ]' in existing
    assert "grep -qE '^sshx[[:space:]]'" in existing
    assert 'refusing to overwrite' in existing


def test_repair_only_replaces_empty_file_and_preserves_backup(tmp_path):
    target = tmp_path / 'sshx'
    target.touch()
    target.chmod(0o755)
    source = (ROOT / 'scripts/repair-sshx.sh').read_text()
    source = source.replace('target=/usr/local/bin/sshx', f'target={target}')
    source = source.replace('/usr/local/bin/.sshx-backup.XXXXXX', f'{tmp_path}/.sshx-backup.XXXXXX')
    source = source.replace('/usr/local/bin/.sshx-new.XXXXXX', f'{tmp_path}/.sshx-new.XXXXXX')
    script = tmp_path / 'repair.sh'
    script.write_text(source)
    binary = tmp_path / 'fake' / 'sshx'
    binary.parent.mkdir()
    binary.write_text('#!/bin/sh\necho sshx 0.4.1\n')
    archive = tmp_path / 'archive.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        tar.add(binary, arcname='sshx')
    stubs = tmp_path / 'stubs'
    stubs.mkdir()
    commands = {
        'id': 'if [ "$1" = "-u" ]; then echo 0; fi; exit 0',
        'curl': 'while [ "$1" != "-o" ]; do shift; done; cp "$ARCHIVE" "$2"',
        'runuser': 'shift 3; exec "$@"',
        'install': 'shift 6; cp "$1" "$2"; chmod 755 "$2"',
    }
    for name, body in commands.items():
        path = stubs / name
        path.write_text('#!/bin/sh\n' + body + '\n')
        path.chmod(0o755)
    env = {**os.environ, 'PATH': f'{stubs}:/usr/bin:/bin', 'ARCHIVE': str(archive)}
    result = subprocess.run(['bash', str(script), '--apply'], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert target.read_text() == binary.read_text()
    backups = list(tmp_path.glob('.sshx-backup.*/sshx'))
    assert len(backups) == 1 and backups[0].stat().st_size == 0
    second = subprocess.run(['bash', str(script), '--apply'], env=env, capture_output=True, text=True)
    assert second.returncode != 0
    assert target.read_text() == binary.read_text()
