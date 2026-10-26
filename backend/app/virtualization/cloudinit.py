"""cloud-init image generation.

Renders NoCloud user-data / meta-data / network-config and packages them
into a seed ISO. Only fixed argument vectors are passed to subprocess —
never a shell — so user-supplied VPS names cannot inject commands.
"""
from __future__ import annotations

import ipaddress
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

from .base import HypervisorError


def _validate_hostname(hostname: str) -> str:
    cleaned = hostname.strip().lower()
    if not cleaned or len(cleaned) > 253:
        raise HypervisorError("Invalid hostname")
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789-.")
    if any(ch not in allowed for ch in cleaned):
        raise HypervisorError("Hostname contains invalid characters")
    return cleaned


def render_user_data(
    hostname: str,
    ssh_public_key: str = "",
    default_user: str = "ubuntu",
    password: str = "",
) -> str:
    users = [
        {
            "name": default_user,
            "sudo": "ALL=(ALL) NOPASSWD:ALL",
            "shell": "/bin/bash",
            "lock_passwd": False,
        }
    ]
    if ssh_public_key:
        users[0]["ssh_authorized_keys"] = [ssh_public_key.strip()]
    user_data: dict = {
        "hostname": _validate_hostname(hostname),
        "manage_etc_hosts": True,
        "users": users,
        "ssh_pwauth": bool(password),
        "package_update": False,
        "runcmd": [],
    }
    if password:
        user_data["chpasswd"] = {
            "expire": False,
            "list": [f"{default_user}:{password}"],
        }
    return "#cloud-config\n" + yaml.safe_dump(user_data, sort_keys=False)


def render_meta_data(instance_id: str, hostname: str) -> str:
    return yaml.safe_dump(
        {"instance-id": instance_id, "local-hostname": _validate_hostname(hostname)},
        sort_keys=False,
    )


def render_network_config(
    mac_address: str,
    use_dhcp: bool = True,
    address: str = "",
    gateway: str = "",
    dns: list[str] | None = None,
) -> str | None:
    if use_dhcp:
        config = {
            "version": 2,
            "ethernets": {
                "eth0": {"match": {"macaddress": mac_address.lower()}, "set-name": "eth0", "dhcp4": True}
            },
        }
    else:
        iface = ipaddress.ip_interface(address)
        eth = {
            "match": {"macaddress": mac_address.lower()},
            "set-name": "eth0",
            "dhcp4": False,
            "addresses": [str(iface)],
        }
        if gateway:
            eth["routes"] = [{"to": "default", "via": gateway}]
        if dns:
            eth["nameservers"] = {"addresses": dns}
        config = {"version": 2, "ethernets": {"eth0": eth}}
    return yaml.safe_dump(config, sort_keys=False)


def build_seed_iso(
    output_path: str,
    instance_id: str,
    hostname: str,
    ssh_public_key: str,
    default_user: str,
    password: str,
    mac_address: str,
    use_dhcp: bool,
    static_address: str = "",
    gateway: str = "",
) -> str:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="bluekvm-cidata-") as tmp:
        tmpdir = Path(tmp)
        (tmpdir / "user-data").write_text(
            render_user_data(hostname, ssh_public_key, default_user, password), encoding="utf-8"
        )
        (tmpdir / "meta-data").write_text(render_meta_data(instance_id, hostname), encoding="utf-8")
        net_cfg = render_network_config(mac_address, use_dhcp, static_address, gateway)
        if net_cfg:
            (tmpdir / "network-config").write_text(net_cfg, encoding="utf-8")

        if shutil.which("cloud-localds"):
            cmd = ["cloud-localds", str(output), str(tmpdir / "user-data"), str(tmpdir / "meta-data")]
            if net_cfg:
                cmd += ["--network-config", str(tmpdir / "network-config")]
        elif shutil.which("genisoimage"):
            cmd = [
                "genisoimage", "-output", str(output), "-volid", "cidata", "-joliet", "-rock",
                str(tmpdir),
            ]
        elif shutil.which("xorriso"):
            cmd = [
                "xorriso", "-as", "mkisofs", "-output", str(output), "-volid", "cidata",
                "-joliet", "-rock", str(tmpdir),
            ]
        else:
            raise HypervisorError(
                "No cloud-init ISO tool found. Install cloud-image-utils (cloud-localds) "
                "or genisoimage/xorriso on the node."
            )

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
        if result.returncode != 0 or not output.exists():
            raise HypervisorError(f"cloud-init seed ISO creation failed: {result.stderr.strip()}")
        os.chmod(output, 0o600)
    return str(output)
