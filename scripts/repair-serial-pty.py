#!/usr/bin/env python3
"""Back up and repair a stopped libvirt domain's serial PTY configuration.

No disks or guest data are touched. The user must explicitly supply --apply.
This intentionally refuses unusual serial configurations instead of guessing.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.dom import minidom


def repaired_xml(original: bytes) -> bytes:
    doc = minidom.parseString(original)
    devices_nodes = doc.getElementsByTagName("devices")
    if len(devices_nodes) != 1:
        raise ValueError("Expected exactly one devices element")
    devices = devices_nodes[0]
    children = [n for n in devices.childNodes if n.nodeType == n.ELEMENT_NODE]
    serials = [n for n in children if n.tagName == "serial" and n.getAttribute("type") == "pty"]
    consoles = [n for n in children if n.tagName == "console" and n.getAttribute("type") == "pty"]
    if len(serials) != 1 or len(consoles) > 1:
        raise ValueError("Expected one PTY serial and at most one PTY console; no changes made")
    serial = serials[0]
    targets = serial.getElementsByTagName("target")
    if len(targets) != 1 or targets[0].getAttribute("port") != "0":
        raise ValueError("PTY serial is not the expected port 0; no changes made")
    if consoles:
        targets = consoles[0].getElementsByTagName("target")
        if len(targets) != 1 or targets[0].getAttribute("type") != "serial" or targets[0].getAttribute("port") != "0":
            raise ValueError("PTY console is not the expected serial port 0; no changes made")
    # Build only the replacement serial; leave all other nodes and attributes as
    # received from libvirt, including disks, interfaces, UUID, and metadata.
    replacement = doc.createElement("serial")
    replacement.setAttribute("type", "null")
    target = doc.createElement("target")
    target.setAttribute("port", "0")
    replacement.appendChild(target)
    devices.replaceChild(replacement, serial)
    for console in consoles:
        devices.removeChild(console)
    return doc.toxml(encoding="utf-8")


def run_virsh(*args: str) -> bytes:
    return subprocess.run(
        ["virsh", "-c", "qemu:///system", *args], check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={**os.environ, "LC_ALL": "C"},
    ).stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("domain", help="Exact existing libvirt domain name")
    parser.add_argument("--apply", action="store_true", help="Confirm backup and persistent XML change")
    args = parser.parse_args()
    if not args.apply:
        parser.error("--apply is required; this changes the stopped VM's persistent XML")
    if os.geteuid() != 0:
        raise RuntimeError("Run as root or with sudo")
    state = run_virsh("domstate", args.domain).decode().strip().lower()
    if state != "shut off":
        raise RuntimeError(f"Domain must be shut off (actual state: {state}); no changes made")
    original = run_virsh("dumpxml", args.domain, "--inactive")
    updated = repaired_xml(original)
    backup_dir = Path("/root/bluekvm-domain-backups")
    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(backup_dir, 0o700)
    backup_fd, backup_name = tempfile.mkstemp(prefix="domain-", suffix=".xml", dir=backup_dir)
    with os.fdopen(backup_fd, "wb") as backup:
        backup.write(original)
        backup.flush()
        os.fsync(backup.fileno())
    print(f"Original domain XML backed up to {backup_name}", flush=True)
    # Recheck immediately before define. Do not attempt to stop an active VM.
    state = run_virsh("domstate", args.domain).decode().strip().lower()
    if state != "shut off":
        raise RuntimeError(f"Domain state changed to {state}; backup retained and no change applied")
    fd, candidate = tempfile.mkstemp(prefix="bluekvm-domain-", suffix=".xml")
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(updated)
        result = run_virsh("define", candidate).decode(errors="replace").strip()
        print(result)
        print("Serial PTY replaced with null backend. VM disks were not modified; start the VPS from the panel.")
    finally:
        Path(candidate).unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as exc:
        print(f"libvirt command failed: {exc.stderr.decode(errors='replace').strip()}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Repair not completed: {exc}", file=sys.stderr)
        sys.exit(1)
