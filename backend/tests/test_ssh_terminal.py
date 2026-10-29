"""Browser SSH terminal: credential handling, session tokens, WS auth."""
from importlib.metadata import metadata
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version
from starlette.websockets import WebSocketDisconnect

from app.security import decrypt_secret, generate_password
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
        "name": "ssh-vm",
        "hostname": "ssh-vm",
        "template_id": 1,
        "vcpus": 1,
        "ram_mb": 512,
        "disk_gb": 10,
    }
    payload.update(overrides)
    return client.post("/api/vps", json=payload)


# ------------------------------------------------------------- unit checks
def test_asyncssh_cryptography_requirement_is_resolvable():
    """Keep the installer pins compatible with AsyncSSH's upstream metadata.

    This guards the dependency-resolution failure which otherwise stops a fresh
    panel installation before migrations or services can be started.
    """
    requirements_path = Path(__file__).parents[1] / "requirements.txt"
    requirements = {
        requirement.name.lower(): requirement
        for line in requirements_path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
        for requirement in (Requirement(line),)
    }
    pinned_crypto = requirements["cryptography"]
    assert pinned_crypto.specifier == SpecifierSet("==48.0.1")
    pinned_version = Version("48.0.1")

    asyncssh_crypto_requirement = next(
        Requirement(item)
        for item in metadata("asyncssh").get_all("Requires-Dist") or []
        if Requirement(item).name.lower() == "cryptography"
    )
    assert pinned_version in asyncssh_crypto_requirement.specifier


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


def test_ssh_session_requires_running_vps(admin_client):
    created = _create_vps(admin_client, name="ssh-stopped", hostname="ssh-stopped").json()
    # Before the worker runs, the VPS is still pending -> 409
    resp = admin_client.post(f"/api/vps/{created['public_id']}/ssh-session")
    assert resp.status_code == 409


def test_ssh_session_token_flow_and_single_use(admin_client, fake_driver):
    created = _create_vps(admin_client, name="ssh-flow", hostname="ssh-flow").json()
    drain_tasks()

    # Fake driver reports a guest IP for the discovery endpoint
    fake_driver.get_guest_ip = lambda name, mac="": "192.168.122.42"

    ip_resp = admin_client.get(f"/api/vps/{created['public_id']}/guest-ip")
    assert ip_resp.status_code == 200
    assert ip_resp.json()["ip_address"] == "192.168.122.42"
    assert ip_resp.json()["username"] == "ubuntu"

    session = admin_client.post(
        f"/api/vps/{created['public_id']}/ssh-session"
    ).json()
    assert session["kind"] == "ssh"
    assert session["ws_path"].startswith("/ws/ssh?token=")

    # No token -> rejected
    with pytest.raises(WebSocketDisconnect) as exc:
        with admin_client.websocket_connect("/ws/ssh"):
            pass
    assert exc.value.code == 4401

    # A VNC-kind token must not be accepted on the SSH endpoint
    vnc = admin_client.post(
        f"/api/vps/{created['public_id']}/console-session"
    ).json()
    with pytest.raises(WebSocketDisconnect) as exc2:
        with admin_client.websocket_connect(vnc["ws_path"].replace("/ws/console", "/ws/ssh")):
            pass
    assert exc2.value.code == 4401

    # The SSH token itself is valid and single-use: without a reachable SSH
    # server it is still consumed, then replay fails at the auth layer.
    with pytest.raises(WebSocketDisconnect):
        with admin_client.websocket_connect(session["ws_path"]) as ws:
            ws.receive()
    with pytest.raises(WebSocketDisconnect) as exc3:
        with admin_client.websocket_connect(session["ws_path"]):
            pass
    assert exc3.value.code == 4401


def test_guest_ip_409_when_unknown(admin_client):
    created = _create_vps(admin_client, name="no-ip-vm", hostname="no-ip-vm").json()
    drain_tasks()
    # Base driver default returns "" -> honest 409, never a fabricated address
    resp = admin_client.get(f"/api/vps/{created['public_id']}/guest-ip")
    assert resp.status_code == 409
    assert "not available yet" in resp.json()["detail"]
