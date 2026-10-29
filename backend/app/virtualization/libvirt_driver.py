"""Real KVM/QEMU driver built on the libvirt Python API.

The driver is imported lazily so the rest of the panel (API, monitoring,
UI) keeps working on hosts without libvirt installed — capability checks
then honestly report KVM as unavailable.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

log = logging.getLogger("bluekvm.virt.libvirt")

DEFAULT_NETWORK_XML = """<network>
  <name>default</name>
  <forward mode='nat'/>
  <bridge name='virbr0' stp='on' delay='0'/>
  <ip address='192.168.122.1' netmask='255.255.255.0'>
    <dhcp><range start='192.168.122.2' end='192.168.122.254'/></dhcp>
  </ip>
</network>"""

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


def format_libvirt_version(version: int) -> str:
    """libvirt encodes versions as a single integer (e.g. 10000000 -> 10.0.0).

    conn.getVersion() returns an int, not an iterable — iterating it raises
    "'int' object is not iterable", which only surfaced on a real libvirtd.
    """
    try:
        value = int(version)
    except (TypeError, ValueError):
        return str(version)
    return f"{value // 1_000_000}.{(value // 1_000) % 1_000}.{value % 1_000}"


def hypervisor_gid() -> int | None:
    """Resolve the gid QEMU drops privileges to (qemu.conf group, then common names)."""
    import grp

    candidates: list[str] = []
    qemu_conf = Path("/etc/libvirt/qemu.conf")
    if qemu_conf.exists():
        for line in qemu_conf.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == "group":
                name = value.strip().strip('"').strip("'")
                if name and name not in candidates:
                    candidates.append(name)
    candidates.extend(["libvirt-qemu", "kvm", "libvirt"])
    for name in candidates:
        try:
            return grp.getgrnam(name).gr_gid
        except KeyError:
            continue
    return None


def grant_hypervisor_access(vm_dir: Path, *files: Path) -> None:
    """Give the QEMU group access to VM storage.

    On normal systemd hosts libvirt's dynamic DAC relabels files itself and
    this is a harmless no-op. In manually-started daemon containers that
    mechanism is absent, so without this QEMU fails with
    "Cannot access storage file ... Permission denied".
    """
    gid = hypervisor_gid()
    try:
        vm_dir.mkdir(parents=True, exist_ok=True)
        if gid is not None:
            os.chown(vm_dir, -1, gid)
            for path in files:
                if path.exists():
                    os.chown(path, -1, gid)
        os.chmod(vm_dir, 0o2750)  # setgid: new files inherit the hypervisor group
        for path in files:
            if path.exists():
                os.chmod(path, 0o660)
    except (PermissionError, OSError):
        # Non-root panel: rely entirely on libvirt's dynamic ownership.
        pass


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

    def test_connection(self, verify_local_kvm: bool = True) -> dict:
        caps = detect_capabilities()
        # The local /dev/kvm probe only applies to the node running this
        # process. External nodes (qemu+ssh://...) own their own KVM stack.
        if verify_local_kvm and not caps.kvm_available:
            raise KVMUnavailableError(
                f"KVM is not usable on this node: {caps.kvm_reason}. "
                "Enable nested virtualization on your host, or register a KVM-capable node."
            )
        conn = self._connect()
        info = {
            "hostname": conn.getHostname(),
            "libvirt_version": format_libvirt_version(conn.getVersion()),
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
      <target dev='sda' bus='sata'/>
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

        # Hand disk + seed ISO to the QEMU group so the dropped-privilege
        # process can open them in containers without libvirt dynamic DAC.
        grant_hypervisor_access(vm_dir, disk_path, seed_path)

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

    # ----------------------------------------------------- guest addressing
    @staticmethod
    def _first_ipv4(address_map: dict) -> str:
        for iface in address_map.values():
            if not isinstance(iface, dict):
                continue
            for addr in iface.get("addrs") or []:
                ip = addr.get("addr", "")
                if ip and ":" not in ip and not ip.startswith("127."):
                    return ip
        return ""

    def get_guest_ip(self, name: str, mac: str = "") -> str:
        """Discover the guest IPv4 address.

        Order: qemu-guest-agent -> libvirt lease table -> per-network
        DHCP leases. Always best-effort: returns '' instead of raising so
        callers can surface an honest "address not available yet" state.
        """
        try:
            import libvirt  # noqa: PLC0415

            domain = self._lookup(name)
            for source in (
                libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_AGENT,
                libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE,
            ):
                try:
                    ip = self._first_ipv4(domain.interfaceAddresses(source, 0))
                    if ip:
                        return ip
                except Exception:  # agent not ready / no lease yet
                    continue
            conn = self._connect()
            mac_l = mac.lower()
            for net in conn.listAllNetworks(0):
                try:
                    for lease in net.DHCPLeases():
                        if mac_l and lease.get("mac", "").lower() != mac_l:
                            continue
                        ip = lease.get("ipaddr", "")
                        if ip and ":" not in ip:
                            return ip
                except Exception:
                    continue
        except HypervisorError:
            raise
        except Exception as exc:  # discovery must never break provisioning
            log.debug("guest IP discovery failed for %s: %s", name, exc)
        return ""

    def ensure_default_network(self) -> str:
        """Define + start the standard 'default' NAT network if missing."""
        try:
            conn = self._connect()
            try:
                net = conn.networkLookupByName("default")
            except Exception:
                try:
                    net = conn.networkDefineXML(DEFAULT_NETWORK_XML)
                except Exception as exc:
                    log.warning("could not define default network: %s", exc)
                    return "unavailable"
            try:
                net.setAutostart(True)
            except Exception:
                pass
            if not net.isActive():
                try:
                    net.create()
                except Exception as exc:
                    # Typical in unprivileged containers (CAP_NET_ADMIN missing)
                    log.warning("default network defined but not startable: %s", exc)
                    return "defined"
            return "active"
        except Exception as exc:
            log.warning("ensure_default_network failed: %s", exc)
            return "unavailable"

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
