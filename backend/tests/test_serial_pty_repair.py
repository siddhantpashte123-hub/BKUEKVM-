"""Non-destructive repair of existing serial PTY configurations."""
import importlib.util
from pathlib import Path
from xml.dom import minidom

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "repair-serial-pty.py"
spec = importlib.util.spec_from_file_location("repair_serial_pty", SCRIPT)
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)

DOMAIN = b'''<domain xmlns:qemu="http://libvirt.org/schemas/domain/qemu/1.0">
 <name>blue</name><uuid>example-uuid</uuid>
 <devices>
  <disk type="file"><source file="/vms/blue/disk.qcow2"/></disk>
  <serial type="pty"><source path="/dev/pts/1"/><target port="0"/></serial>
  <console type="pty"><target type="serial" port="0"/></console>
  <interface type="network"><source network="default"/></interface>
 </devices><qemu:commandline><qemu:arg value="kept"/></qemu:commandline>
</domain>'''


def test_repair_replaces_only_matching_serial_pty():
    doc = minidom.parseString(repair.repaired_xml(DOMAIN))
    assert doc.getElementsByTagName("uuid")[0].firstChild.nodeValue == "example-uuid"
    assert doc.getElementsByTagName("disk")[0].getElementsByTagName("source")[0].getAttribute("file") == "/vms/blue/disk.qcow2"
    assert doc.getElementsByTagName("interface")[0].getElementsByTagName("source")[0].getAttribute("network") == "default"
    assert doc.getElementsByTagName("serial")[0].getAttribute("type") == "null"
    assert not doc.getElementsByTagName("console")
    assert doc.getElementsByTagName("qemu:arg")[0].getAttribute("value") == "kept"


def test_repair_refuses_multiple_serials_or_unrelated_console():
    with pytest.raises(ValueError):
        repair.repaired_xml(DOMAIN.replace(b'</devices>', b'<serial type="pty"><target port="1"/></serial></devices>'))
    with pytest.raises(ValueError):
        repair.repaired_xml(DOMAIN.replace(b'type="serial" port="0"', b'type="virtio" port="0"'))


def test_runtime_pty_error_is_actionable_without_changing_domain(monkeypatch):
    from app.virtualization.base import HypervisorError
    from app.virtualization.libvirt_driver import LibvirtDriver

    class Domain:
        def isActive(self):
            return False

        def XMLDesc(self):
            return '<domain><devices/></domain>'

        def create(self):
            raise RuntimeError('Failed to create PTY: Permission denied')

    driver = LibvirtDriver('qemu:///system', '/tmp/vms')
    monkeypatch.setattr(driver, '_lookup', lambda _: Domain())
    with pytest.raises(HypervisorError, match='configuration was not changed'):
        driver.start('blue')


def test_repair_requires_explicit_apply_and_refuses_running_vm(monkeypatch, capsys):
    monkeypatch.setattr(repair.os, "geteuid", lambda: 0)
    monkeypatch.setattr(repair.sys, "argv", ["repair", "blue", "--apply"])
    calls = []

    def run(*args):
        calls.append(args)
        return b"running\n"

    monkeypatch.setattr(repair, "run_virsh", run)
    with pytest.raises(RuntimeError, match="must be shut off"):
        repair.main()
    assert calls == [("domstate", "blue")]
