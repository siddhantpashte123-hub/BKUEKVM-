"""Hosted SSHX terminal: credential handling, owner access and relay safety."""
from pathlib import Path

import pytest

from app.security import decrypt_secret, generate_password
from app.services.sshx_sessions import SshxSessionManager, sshx_sessions
from app.virtualization.cloudinit import render_user_data
from app.virtualization.libvirt_driver import (
    format_libvirt_version,
    grant_hypervisor_access,
)
from app.virtualization.base import VMSpec
from app.virtualization.libvirt_driver import LibvirtDriver
from tests.helpers import drain_tasks


def _create_vps(client, **overrides):
    payload = {
        "name": "sshx-vm",
        "hostname": "sshx-vm",
        "template_id": 1,
        "vcpus": 1,
        "ram_mb": 512,
        "disk_gb": 10,
    }
    payload.update(overrides)
    return client.post("/api/vps", json=payload)


# ------------------------------------------------------------- unit checks
def test_sshx_launcher_keeps_password_out_of_shell_text(tmp_path, monkeypatch):
    """Password is only a 0600 file, never a command argument or script literal."""
    monkeypatch.setattr(SshxSessionManager, "_ssh_binary", staticmethod(lambda: "/usr/bin/ssh"))
    password = "DoNotLeak!123"
    launcher = SshxSessionManager._write_launcher(
        tmp_path, host="192.168.122.42", username="ubuntu", password=password,
        known_hosts=tmp_path / "known_hosts",
    )
    secret_file = tmp_path / "password"

    assert password not in launcher.read_text()
    assert secret_file.read_text() == password
    assert (secret_file.stat().st_mode & 0o777) == 0o600
    assert (launcher.stat().st_mode & 0o777) == 0o700
    assert "SSH_ASKPASS_REQUIRE=force" in launcher.read_text()
    assert "StrictHostKeyChecking=accept-new" in launcher.read_text()
    assert "UserKnownHostsFile=" in launcher.read_text()


def test_sshx_manager_returns_hosted_url_and_cleans_secret_files(tmp_path, monkeypatch, db):
    """Exercise the real process lifecycle with a local stand-in SSHX client."""
    from datetime import datetime, timedelta, timezone
    from app.config import settings

    fake_sshx = tmp_path / "sshx"
    fake_sshx.write_text(
        "#!/bin/sh\necho 'https://sshx.io/s/owner-only#private-key'\ntrap 'exit 0' TERM INT\nwhile :; do sleep 1; done\n",
        encoding="utf-8",
    )
    fake_sshx.chmod(0o700)
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setattr(settings, "sshx_binary", str(fake_sshx))
    monkeypatch.setattr(settings, "sshx_runtime_dir", str(runtime_dir))
    monkeypatch.setattr(settings, "sshx_known_hosts_dir", str(tmp_path / "known-hosts"))

    manager = SshxSessionManager()
    url = manager.start(
        session_id=987654,
        vps_name="vm1",
        host="192.168.122.42",
        username="ubuntu",
        password="DoNotLeak!456",
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
    )
    assert url == "https://sshx.io/s/owner-only#private-key"
    workdirs = list(runtime_dir.iterdir())
    assert len(workdirs) == 1
    assert (workdirs[0] / "password").read_text() == "DoNotLeak!456"

    manager.stop(987654)
    assert list(runtime_dir.iterdir()) == []


def test_libvirt_version_integer_formatting():
    # Real conn.getVersion() returns a single int, never an iterable
    assert format_libvirt_version(10000000) == "10.0.0"
    assert format_libvirt_version(9005001) == "9.5.1"
    assert format_libvirt_version("weird") == "weird"


def test_domain_xml_uses_sata_sda_not_sr0():
    spec = VMSpec(
        name="vm1", hostname="vm1", vcpus=1, ram_mb=512, disk_gb=10,
        base_image_path="/tmp/base.qcow2", libvirt_network="default",
        cloud_init_user="ubuntu", cloud_init_password="secret123",
        storage_dir="/tmp/vms",
    )
    xml = LibvirtDriver._domain_xml(spec, "/tmp/vms/vm1/disk.qcow2",
                                    "/tmp/vms/vm1/seed.iso", "52:54:00:aa:bb:cc")
    assert "dev='sda' bus='sata'" in xml
    assert "sr0" not in xml
    assert "dev='vda' bus='virtio'" in xml


def test_start_reactivates_default_network_before_domain(monkeypatch):
    """Existing VMs recover when libvirtd restarts with default NAT inactive."""
    events: list[str] = []

    class Network:
        active = False
        autostart = False

        def isActive(self):
            return self.active

        def setAutostart(self, enabled):
            self.autostart = enabled

        def create(self):
            events.append("network")
            self.active = True

    class Connection:
        def networkLookupByName(self, name):
            assert name == "default"
            return network

    class Domain:
        def isActive(self):
            return False

        def XMLDesc(self):
            return "<domain><devices><interface type='network'><source network='default'/></interface></devices></domain>"

        def create(self):
            events.append("domain")

    network = Network()
    driver = LibvirtDriver("qemu:///system", "/tmp/vms")
    monkeypatch.setattr(driver, "_connect", lambda: Connection())
    monkeypatch.setattr(driver, "_lookup", lambda _name: Domain())

    driver.start("existing-vm")

    assert network.autostart is True
    assert events == ["network", "domain"]


def test_start_explains_default_network_activation_failure(monkeypatch):
    """Containers without CAP_NET_ADMIN get a useful, non-destructive error."""
    from app.virtualization.base import HypervisorError

    class Network:
        def isActive(self):
            return False

        def setAutostart(self, _enabled):
            return None

        def create(self):
            raise RuntimeError("operation not permitted")

    class Connection:
        def networkLookupByName(self, _name):
            return Network()

    class Domain:
        def isActive(self):
            return False

        def XMLDesc(self):
            return "<domain><devices><interface type='network'><source network='default'/></interface></devices></domain>"

        def create(self):
            pytest.fail("domain must not be started without its required network")

    driver = LibvirtDriver("qemu:///system", "/tmp/vms")
    monkeypatch.setattr(driver, "_connect", lambda: Connection())
    monkeypatch.setattr(driver, "_lookup", lambda _name: Domain())

    with pytest.raises(HypervisorError, match="CAP_NET_ADMIN"):
        driver.start("existing-vm")


def test_generated_password_spans_character_classes():
    for _ in range(20):
        pw = generate_password()
        assert len(pw) == 20
        assert any(c.islower() for c in pw)
        assert any(c.isupper() for c in pw)
        assert any(c.isdigit() for c in pw)
        assert not any(c.isspace() for c in pw)


def test_grant_hypervisor_access_sets_group_perms(tmp_path):
    vm_dir = tmp_path / "vm"
    disk = vm_dir / "disk.qcow2"
    vm_dir.mkdir()
    disk.write_text("x")
    grant_hypervisor_access(vm_dir, disk)
    # 0o7777 keeps the setgid bit (0o2000) in scope
    assert (vm_dir.stat().st_mode & 0o7777) == 0o2750
    assert (disk.stat().st_mode & 0o777) == 0o660


def test_kvm_capability_probe_is_honest_without_device():
    from app.virtualization.capabilities import detect_capabilities

    caps = detect_capabilities()
    # Sandbox/CI has no /dev/kvm: the open()-based probe must report
    # unavailable with a reason instead of pretending VMs can run.
    if caps.kvm_available:
        pytest.skip("host exposes usable /dev/kvm")
    assert caps.kvm_reason


def test_cloud_init_renders_password_for_default_user():
    user_data = render_user_data(hostname="h1", default_user="ubuntu", password="Blue!Pass2026")
    assert "chpasswd:" in user_data
    assert "ubuntu:Blue!Pass2026" in user_data
    assert "ssh_pwauth: true" in user_data


# ------------------------------------------------------------- API behaviour
def test_blank_password_is_generated_and_shown_once(admin_client, db):
    resp = _create_vps(admin_client, name="pwgen-vm", hostname="pwgen-vm")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["has_password"] is True
    generated = body["generated_password"]
    assert generated and len(generated) >= 16

    # The secret is never returned again on normal reads
    detail = admin_client.get(f"/api/vps/{body['public_id']}").json()
    assert detail["has_password"] is True
    assert detail["generated_password"] is None
    assert "init_password_encrypted" not in detail

    # Stored value is encrypted, not plaintext
    from app.models import VPS
    vps = db.query(VPS).filter(VPS.public_id == body["public_id"]).one()
    assert vps.init_password_encrypted
    assert generated not in vps.init_password_encrypted
    assert decrypt_secret(vps.init_password_encrypted) == generated


def test_explicit_password_is_encrypted(admin_client, db):
    resp = _create_vps(
        admin_client, name="explicit-pw-vm", hostname="explicit-pw-vm",
        cloud_init_password="My!StrongPass99",
    )
    assert resp.status_code == 201
    assert resp.json()["generated_password"] is None
    from app.models import VPS
    vps = db.query(VPS).filter(VPS.name == "explicit-pw-vm").one()
    assert decrypt_secret(vps.init_password_encrypted) == "My!StrongPass99"


def test_sshx_session_requires_running_vps(admin_client):
    created = _create_vps(admin_client, name="sshx-stopped", hostname="sshx-stopped").json()
    # Before the worker runs, the VPS is still pending -> 409.
    resp = admin_client.post(f"/api/vps/{created['public_id']}/sshx-session")
    assert resp.status_code == 409


def test_sshx_session_is_owner_authorized_and_url_is_not_persisted(admin_client, db, fake_driver, monkeypatch):
    created = _create_vps(admin_client, name="sshx-flow", hostname="sshx-flow").json()
    drain_tasks()
    fake_driver.get_guest_ip = lambda name, mac="": "192.168.122.42"

    started: dict = {}

    def start_fake(**kwargs):
        started.update(kwargs)
        return "https://sshx.io/s/owner-only-example#private-key"

    monkeypatch.setattr(sshx_sessions, "start", start_fake)
    response = admin_client.post(f"/api/vps/{created['public_id']}/sshx-session")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["kind"] == "sshx"
    assert body["sshx_url"] == "https://sshx.io/s/owner-only-example#private-key"
    assert "console_token" not in body
    assert "ws_path" not in body
    assert started["host"] == "192.168.122.42"
    assert started["username"] == "ubuntu"

    # The bearer URL never lands in BLUEKVM database state or audit details.
    from app.models import AuditLog, ConsoleSession

    session = db.query(ConsoleSession).filter(ConsoleSession.vps_id == created["id"]).one()
    assert session.kind == "sshx"
    assert session.used_at is not None
    assert session.revoked_at is None
    assert "sshx.io" not in session.token_hash
    audit = db.query(AuditLog).filter(AuditLog.action == "sshx.open").order_by(AuditLog.id.desc()).first()
    assert audit is not None
    assert "sshx.io" not in audit.details


def test_sshx_session_409_when_guest_ip_unknown(admin_client, fake_driver):
    created = _create_vps(admin_client, name="sshx-no-ip", hostname="sshx-no-ip").json()
    drain_tasks()
    resp = admin_client.post(f"/api/vps/{created['public_id']}/sshx-session")
    assert resp.status_code == 409
    assert "Guest IP address is not available" in resp.json()["detail"]


def test_guest_ip_409_when_unknown(admin_client):
    created = _create_vps(admin_client, name="no-ip-vm", hostname="no-ip-vm").json()
    drain_tasks()
    # Base driver default returns "" -> honest 409, never a fabricated address
    resp = admin_client.get(f"/api/vps/{created['public_id']}/guest-ip")
    assert resp.status_code == 409
    assert "not available yet" in resp.json()["detail"]
