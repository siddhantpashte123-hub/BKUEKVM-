"""Real KVM/QEMU driver built on the libvirt Python API.

The driver is imported lazily so the rest of the panel (API, monitoring,
UI) keeps working on hosts without libvirt installed — capability checks
then honestly report KVM as unavailable.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from .base import (
    HypervisorDriver,
    HypervisorError,
    KVMUnavailableError,
    NetworkInfo,
    PoolInfo,
    VMInfo,
    VMSpec,
    VMStats,
    PowerState,
)
from .capabilities import detect_capabilities
from .cloudinit import build_seed_iso

LIBVIRT_STATE_MAP = {
    0: PowerState.RUNNING,
    1: PowerState.BLOCKED,
    2: PowerState.PAUSED,
    3: PowerState.SHUTDOWN,
    4: PowerState.SHUTOFF,
    5: PowerState.SHUTOFF,
    6: PowerState.CRASHED,
    7: PowerState.PAUSED,
}


def generate_mac() -> str:
    # 52:54:00 is the QEMU/KVM locally-administered OUI prefix
    return "52:54:00:%02x:%02x:%02x" % tuple(os.urandom(3))


class LibvirtDriver(HypervisorDriver):
    def __init__(self, uri: str, storage_dir: str) -> None:
        self.uri = uri
        self.storage_dir = storage_dir
        self.auth_secret: str = ""
        self._conn = None

    # ------------------------------------------------------------- connection
    def _connect(self):
        if self._conn is not None:
            try:
                self._conn.getHostname()
                return self._conn
            except Exception:
                self._conn = None
        try:
            import libvirt  # noqa: PLC0415
        except ImportError as exc:
            raise KVMUnavailableError(
                "libvirt Python bindings are not installed on this node "
                "(install the python3-libvirt system package)."
            ) from exc
        try:
            if self.auth_secret:
                secret = self.auth_secret

                def _auth(credentials, _user_data):
                    for cred in credentials:
                        if cred[0] in (
                            libvirt.VIR_CRED_PASSPHRASE,
                            libvirt.VIR_CRED_NOECHOPROMPT,
                        ):
                            cred[4] = secret
                    return 0

                self._conn = libvirt.openAuth(
                    self.uri,
                    [[libvirt.VIR_CRED_PASSPHRASE, libvirt.VIR_CRED_NOECHOPROMPT], "", ""],
                    _auth,
                    0,
                )
            else:
                self._conn = libvirt.open(self.uri)
        except Exception as exc:  # libvirt.libvirtError
            raise KVMUnavailableError(
                f"Cannot connect to libvirt at {self._safe_uri()}: {exc}. "
                "Ensure libvirtd is running and the panel service has access "
                "(e.g. membership of the libvirt group)."
            ) from exc
        if self._conn is None:
            raise KVMUnavailableError(f"libvirt rejected connection to {self._safe_uri()}")
        return self._conn

    def _safe_uri(self) -> str:
        # Never embed credentials into error messages or logs
        return self.uri.split("@")[-1] if "@" in self.uri else self.uri

    def test_connection(self) -> dict:
        caps = detect_capabilities()
        if not caps.kvm_available:
            raise KVMUnavailableError(
                f"KVM is not usable on this node: {caps.kvm_reason}. "
                "Enable nested virtualization on your host, or register a KVM-capable node."
            )
        conn = self._connect()
        info = {
            "hostname": conn.getHostname(),
            "libvirt_version": ".".join(str(x) for x in conn.getVersion()),
            "hypervisor": conn.getType(),
            "capabilities": caps.to_dict(),
        }
        try:
            node = conn.getInfo()
            info["node"] = {
                "model": node[0],
                "memory_mb": node[1],
                "cpus": node[2],
                "mhz": node[3],
                "arch": node[4],
            }
        except Exception:
            pass
        return info

    # ------------------------------------------------------------- domain XML
    @staticmethod
    def _domain_xml(spec: VMSpec, disk_path: str, seed_path: str, mac: str) -> str:
        interface = (
            f'<interface type="bridge"> <source bridge="{escape(spec.bridge)}"/> '
            f'<mac address="{mac}"/> <model type="virtio"/> </interface>'
            if spec.bridge
            else f'<interface type="network"> <source network="{escape(spec.libvirt_network)}"/> '
            f'<mac address="{mac}"/> <model type="virtio"/> </interface>'
        )
        return f"""<domain type='kvm'>
  <name>{escape(spec.name)}</name>
  <memory unit='MiB'>{spec.ram_mb}</memory>
  <currentMemory unit='MiB'>{spec.ram_mb}</currentMemory>
  <vcpu placement='static'>{spec.vcpus}</vcpu>
  <os>
    <type arch='x86_64' machine='q35'>hvm</type>
    <boot dev='hd'/>
  </os>
  <features><acpi/><apic/></features>
  <cpu mode='host-model' check='partial'/>
  <clock offset='utc'><timer name='rtc' tickpolicy='catchup'/></clock>
  <on_poweroff>destroy</on_poweroff>
  <on_reboot>restart</on_reboot>
  <on_crash>restart</on_crash>
  <devices>
    <disk type='file' device='disk'>
      <driver name='qemu' type='qcow2' discard='unmap'/>
      <source file='{escape(disk_path)}'/>
      <target dev='vda' bus='virtio'/>
    </disk>
    <disk type='file' device='cdrom'>
      <driver name='qemu' type='raw'/>
      <source file='{escape(seed_path)}'/>
      <target dev='sr0' bus='sata'/>
      <readonly/>
    </disk>
    {interface}
    <graphics type='vnc' port='-1' autoport='yes' listen='127.0.0.1'>
      <listen type='address' address='127.0.0.1'/>
    </graphics>
    <console type='pty'><target type='serial' port='0'/></console>
    <channel type='unix'><target type='virtio' name='org.qemu.guest_agent.0'/></channel>
    <memballoon model='virtio'/>
    <rng model='virtio'><backend model='random'>/dev/urandom</backend></rng>
  </devices>
</domain>"""

    # ------------------------------------------------------------- lifecycle
    def define_vm(self, spec: VMSpec) -> VMInfo:
        caps = detect_capabilities()
        if not caps.kvm_available:
            raise KVMUnavailableError(
                f"KVM is not usable on this node: {caps.kvm_reason}. "
                "VM creation blocked — no simulated machine is created."
            )
        if not caps.qemu_img:
            raise HypervisorError("qemu-img is not installed on the node.")

        storage = Path(spec.storage_dir or self.storage_dir)
        storage.mkdir(parents=True, exist_ok=True)
        vm_dir = storage / spec.name
        vm_dir.mkdir(parents=True, mode=0o750, exist_ok=True)
        disk_path = vm_dir / "disk.qcow2"
        seed_path = vm_dir / "cloud-init-seed.iso"

        if not Path(spec.base_image_path).exists():
            raise HypervisorError(
                f"Base template image is missing: {spec.base_image_path}. "
                "Download the OS template before creating a VPS."
            )

        # Backing qcow2 linked to the verified cloud image, then resized.
        cmd = [
            caps.qemu_img, "create", "-f", "qcow2", "-F", "qcow2",
            "-b", os.path.abspath(spec.base_image_path), str(disk_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180, check=False)
        if result.returncode != 0:
            raise HypervisorError(f"qemu-img create failed: {result.stderr.strip()}")
        resize = [caps.qemu_img, "resize", str(disk_path), f"{spec.disk_gb}G"]
        result = subprocess.run(resize, capture_output=True, text=True, timeout=180, check=False)
        if result.returncode != 0:
            raise HypervisorError(f"qemu-img resize failed: {result.stderr.strip()}")
        os.chmod(disk_path, 0o600)

        mac = spec.mac_address or generate_mac()
        build_seed_iso(
            output_path=str(seed_path),
            instance_id=f"bluekvm-{spec.name}-{uuid.uuid4().hex[:8]}",
            hostname=spec.hostname,
            ssh_public_key=spec.ssh_public_key,
            default_user=spec.cloud_init_user,
            password=spec.cloud_init_password,
            mac_address=mac,
            use_dhcp=not spec.mac_address,
        )

        xml = self._domain_xml(spec, str(disk_path), str(seed_path), mac)
        conn = self._connect()
        try:
            domain = conn.defineXML(xml)
        except Exception as exc:
            raise HypervisorError(f"libvirt rejected the domain definition: {exc}") from exc
        info = self._info_from_domain(domain)
        info.metadata["mac_address"] = mac
        info.metadata["disk_path"] = str(disk_path)
        info.metadata["seed_path"] = str(seed_path)
        return info

    def _lookup(self, name: str):
        conn = self._connect()
        try:
            return conn.lookupByName(name)
        except Exception as exc:
            raise HypervisorError(f"Domain '{name}' is not defined on this node: {exc}") from exc

    def start(self, name: str) -> None:
        domain = self._lookup(name)
        if domain.isActive():
            return
        try:
            domain.create()
        except Exception as exc:
            raise HypervisorError(f"Failed to start '{name}': {exc}") from exc

    def power_off(self, name: str) -> None:
        domain = self._lookup(name)
        if not domain.isActive():
            return
        try:
            domain.destroy()
        except Exception as exc:
            raise HypervisorError(f"Force stop failed for '{name}': {exc}") from exc

    def shutdown(self, name: str, timeout: int = 60) -> None:
        domain = self._lookup(name)
        if not domain.isActive():
            return
        try:
            domain.shutdown()
        except Exception as exc:
            raise HypervisorError(f"Graceful shutdown failed for '{name}': {exc}") from exc
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not domain.isActive():
                return
            time.sleep(1)
        raise HypervisorError(
            f"Guest '{name}' did not shut down within {timeout}s. "
            "Use Force Stop if required."
        )

    def restart(self, name: str) -> None:
        domain = self._lookup(name)
        try:
            domain.reboot(0)
        except Exception as exc:
            raise HypervisorError(f"Restart failed for '{name}': {exc}") from exc

    def delete(self, name: str, purge_disks: bool = True) -> None:
        conn = self._connect()
        try:
            domain = conn.lookupByName(name)
        except Exception:
            domain = None
        disk_paths: list[str] = []
        if domain is not None:
            xml = domain.XMLDesc()
            root = ET.fromstring(xml)
            for disk in root.findall(".//devices/disk"):
                source = disk.find("source")
                if source is not None and source.get("file"):
                    disk_paths.append(source.get("file"))
            if domain.isActive():
                domain.destroy()
            # Remove all managed save states / snapshots before undefining
            try:
                domain.undefineFlags(
                    __import__("libvirt").VIR_DOMAIN_UNDEFINE_MANAGED_SAVE
                    | __import__("libvirt").VIR_DOMAIN_UNDEFINE_SNAPSHOTS_METADATA
                    | __import__("libvirt").VIR_DOMAIN_UNDEFINE_NVRAM
                )
            except Exception:
                try:
                    domain.undefine()
                except Exception as exc:
                    raise HypervisorError(f"Undefine failed for '{name}': {exc}") from exc

        if purge_disks:
            # Only remove files that live inside the configured VM storage tree.
            base = Path(self.storage_dir).resolve()
            for raw in disk_paths:
                path = Path(raw).resolve()
                if base not in path.parents:
                    continue
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            vm_dir = base / name
            if vm_dir.exists() and vm_dir.is_dir():
                shutil.rmtree(vm_dir, ignore_errors=True)

    # ------------------------------------------------------------- inspection
    def _info_from_domain(self, domain) -> VMInfo:
        state, _ = domain.state()
        xml = domain.XMLDesc()
        root = ET.fromstring(xml)
        vcpu = root.findtext("vcpu", "0")
        memory = root.findtext("memory", "0")
        graphics = root.find(".//devices/graphics")
        host = port = socket = ""
        if graphics is not None:
            host = graphics.get("listen", "127.0.0.1")
            port = graphics.get("port", "0")
            socket = graphics.get("socket", "")
        return VMInfo(
            name=domain.name(),
            uuid=domain.UUIDString(),
            state=LIBVIRT_STATE_MAP.get(state, PowerState.UNKNOWN),
            vcpus=int(vcpu or 0),
            ram_mb=int(memory or 0),
            console_host=host,
            console_port=int(port or 0),
            console_socket=socket,
        )

    def get_info(self, name: str) -> VMInfo:
        return self._info_from_domain(self._lookup(name))

    def get_stats(self, name: str) -> VMStats:
        domain = self._lookup(name)
        stats = VMStats(available=True)
        try:
            info = domain.getInfo()
            stats.ram_total_mb = info[1]
            cpu_stats = domain.getCPUStats(True, 0)
            if cpu_stats:
                # cpu_time is cumulative nanoseconds; expose a bounded utilisation figure
                stats.cpu_percent = round(
                    min((cpu_stats[0].get("cpu_time", 0) / 1e9) / max(info[2], 1) * 100, 100.0), 2
                )
            mem = domain.memoryStats()
            if "rss" in mem:
                stats.ram_used_mb = float(mem["rss"]) / 1024
            try:
                block = domain.blockStats("vda")
                stats.disk_used_bytes = block[1] if block else None
            except Exception:
                stats.disk_used_bytes = None
            try:
                net = domain.interfaceStats("vnet0")
                stats.network_rx_bytes, stats.network_tx_bytes = net[0], net[4]
            except Exception:
                stats.network_rx_bytes = stats.network_tx_bytes = None
        except Exception as exc:  # stats are best-effort, never fatal
            stats.available = False
            stats.reason = str(exc)
        return stats

    def list_domains(self) -> list[VMInfo]:
        conn = self._connect()
        result = []
        for domain in conn.listAllDomains(0):
            try:
                result.append(self._info_from_domain(domain))
            except Exception:
                continue
        return result

    def list_pools(self) -> list[PoolInfo]:
        conn = self._connect()
        pools = []
        for pool in conn.listAllStoragePools(0):
            info = pool.info()
            pools.append(
                PoolInfo(
                    name=pool.name(),
                    pool_type=pool.XMLDesc().split('type="')[1].split('"')[0] if 'type="' in pool.XMLDesc() else "unknown",
                    capacity_bytes=info[1],
                    used_bytes=info[2],
                    available_bytes=info[3],
                    active=pool.isActive(),
                )
            )
        return pools

    def list_networks(self) -> list[NetworkInfo]:
        conn = self._connect()
        networks = []
        for net in conn.listAllNetworks(0):
            xml = ET.fromstring(net.XMLDesc())
            bridge = xml.find("bridge")
            ip = xml.find("ip")
            dhcp = xml.find(".//dhcp")
            forward = xml.find("forward")
            networks.append(
                NetworkInfo(
                    name=net.name(),
                    bridge=bridge.get("bridge", "") if bridge is not None else "",
                    network_type=forward.get("mode", "nat") if forward is not None else "isolated",
                    active=net.isActive(),
                    subnet=ip.get("address", "") if ip is not None else "",
                    dhcp_enabled=dhcp is not None,
                )
            )
        return networks

    # ------------------------------------------------------------- snapshots
    def create_snapshot(self, name: str, snapshot_name: str) -> str:
        domain = self._lookup(name)
        xml = (
            f"<domainsnapshot><name>{escape(snapshot_name)}</name>"
            "<description>BLUEKVM PANNEL managed snapshot</description></domainsnapshot>"
        )
        try:
            snap = domain.snapshotCreateXML(xml, 0)
            return snap.getName()
        except Exception as exc:
            raise HypervisorError(f"Snapshot creation failed for '{name}': {exc}") from exc

    def delete_snapshot(self, name: str, snapshot_name: str) -> None:
        domain = self._lookup(name)
        try:
            snap = domain.snapshotLookupByName(snapshot_name, 0)
            snap.delete(0)
        except Exception as exc:
            raise HypervisorError(f"Snapshot deletion failed: {exc}") from exc

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
