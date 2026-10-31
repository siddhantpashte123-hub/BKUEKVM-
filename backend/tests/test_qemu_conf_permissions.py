from pathlib import Path
from types import SimpleNamespace

import grp

from app.virtualization.libvirt_driver import grant_hypervisor_access, hypervisor_gid


def test_unreadable_qemu_conf_falls_back_without_aborting_vm_storage(monkeypatch, tmp_path, caplog):
    original_read = Path.read_text

    def read_text(path, *args, **kwargs):
        if str(path) == '/etc/libvirt/qemu.conf':
            raise PermissionError(13, 'Permission denied', str(path))
        return original_read(path, *args, **kwargs)

    def get_group(name):
        if name == 'libvirt-qemu':
            return SimpleNamespace(gr_gid=12345)
        raise KeyError(name)

    monkeypatch.setattr(Path, 'read_text', read_text)
    monkeypatch.setattr(grp, 'getgrnam', get_group)
    monkeypatch.setattr('app.virtualization.libvirt_driver.os.chown', lambda *args: None)
    assert hypervisor_gid() == 12345
    disk = tmp_path / 'disk.qcow2'
    disk.write_bytes(b'data')
    grant_hypervisor_access(tmp_path, disk)
    assert disk.read_bytes() == b'data'
    assert 'using common group names' in caplog.text


def test_readable_custom_group_takes_precedence(monkeypatch):
    monkeypatch.setattr(Path, 'read_text', lambda *args, **kwargs: 'group = "custom-qemu"\n')
    def get_group(name):
        if name == 'custom-qemu':
            return SimpleNamespace(gr_gid=888)
        raise KeyError(name)
    monkeypatch.setattr(grp, 'getgrnam', get_group)
    assert hypervisor_gid() == 888
