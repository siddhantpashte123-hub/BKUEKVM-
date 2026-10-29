"""Driver registry: node selection, health checks and VM state reconciliation."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Node, NodeStatus, VPS, VPSStatus
from ..security import decrypt_secret
from .base import HypervisorDriver, KVMUnavailableError, PowerState
from .capabilities import detect_capabilities
from .libvirt_driver import LibvirtDriver

log = logging.getLogger("bluekvm.virt")

_POWER_TO_STATUS = {
    PowerState.RUNNING: VPSStatus.RUNNING,
    PowerState.PAUSED: VPSStatus.RUNNING,
    PowerState.BLOCKED: VPSStatus.RUNNING,
    PowerState.SHUTOFF: VPSStatus.STOPPED,
    PowerState.SHUTDOWN: VPSStatus.STOPPED,
    PowerState.CRASHED: VPSStatus.ERROR,
}


class DriverManager:
    def __init__(self) -> None:
        self._drivers: dict[int, HypervisorDriver] = {}

    def get_driver(self, node: Node) -> HypervisorDriver:
        cached = self._drivers.get(node.id)
        if cached is not None:
            return cached
        secret = ""
        if node.credential_encrypted:
            try:
                secret = decrypt_secret(node.credential_encrypted)
            except ValueError:
                secret = ""
        driver = LibvirtDriver(
            uri=node.libvirt_uri,
            storage_dir=settings.vm_storage_dir if node.is_local else f"{settings.vm_storage_dir}/node-{node.id}",
        )
        if secret:
            driver.auth_secret = secret  # consumed via openAuth in _connect
        self._drivers[node.id] = driver
        return driver

    def invalidate(self, node_id: int) -> None:
        driver = self._drivers.pop(node_id, None)
        if driver:
            driver.close()

    # ------------------------------------------------------------ health --
    def health_check(self, db: Session, node: Node) -> Node:
        caps = detect_capabilities()
        if node.is_local:
            # Local node: the host's own /dev/kvm open() probe is authoritative.
            node.kvm_ready = caps.kvm_available
        driver = self.get_driver(node)
        try:
            # External nodes own their KVM stack — never gate them on this
            # host's local /dev/kvm capabilities.
            info = driver.test_connection(verify_local_kvm=node.is_local)
            node.status = NodeStatus.ONLINE
            node.last_error = ""
            # A successful remote libvirt handshake proves KVM readiness there.
            node.kvm_ready = True
            node.hypervisor_version = info.get("libvirt_version", "")
            node_info = info.get("node", {})
            node.cpu_cores = node_info.get("cpus", node.cpu_cores) or node.cpu_cores
            node.ram_mb = node_info.get("memory_mb", node.ram_mb) or node.ram_mb
            node.capabilities = __import__("json").dumps(info.get("capabilities", {}))
            if node.is_local:
                network_state = driver.ensure_default_network()
                log.info("default network on node %s: %s", node.name, network_state)
            self._sync_pools_and_networks(db, node, driver)
        except KVMUnavailableError as exc:
            node.status = NodeStatus.OFFLINE
            node.last_error = str(exc)
            log.warning("Node %s KVM unavailable: %s", node.name, exc)
        except Exception as exc:
            node.status = NodeStatus.OFFLINE
            node.last_error = f"{type(exc).__name__}: {exc}"
            log.warning("Node %s health check failed: %s", node.name, exc)
        node.last_health_at = datetime.now(timezone.utc)
        db.commit()
        return node

    def _sync_pools_and_networks(self, db: Session, node: Node, driver: HypervisorDriver) -> None:
        from ..models import Network, StoragePool  # local import avoids circularity

        try:
            for pool in driver.list_pools():
                existing = db.query(StoragePool).filter_by(node_id=node.id, name=pool.name).first()
                if existing:
                    existing.capacity_bytes = pool.capacity_bytes
                    existing.used_bytes = pool.used_bytes
                    existing.status = "active" if pool.active else "inactive"
                else:
                    db.add(
                        StoragePool(
                            node_id=node.id, name=pool.name, pool_type=pool.pool_type,
                            path="", capacity_bytes=pool.capacity_bytes,
                            used_bytes=pool.used_bytes,
                            status="active" if pool.active else "inactive",
                        )
                    )
            for net in driver.list_networks():
                existing = db.query(Network).filter_by(node_id=node.id, name=net.name).first()
                if existing:
                    existing.bridge = net.bridge
                    existing.status = "active" if net.active else "inactive"
                    existing.subnet = net.subnet or existing.subnet
                    existing.dhcp_enabled = net.dhcp_enabled
                else:
                    db.add(
                        Network(
                            node_id=node.id, name=net.name, network_type=net.network_type,
                            bridge=net.bridge, subnet=net.subnet, dhcp_enabled=net.dhcp_enabled,
                            status="active" if net.active else "inactive",
                        )
                    )
            db.commit()
        except Exception as exc:
            log.warning("Pool/network sync failed for node %s: %s", node.name, exc)

    # ----------------------------------------------------- reconciliation --
    def sync_vps_state(self, vps: VPS, driver: HypervisorDriver | None = None) -> VPS:
        # Deleted VMS are never reconciled; provisioning VMs MUST be reconciled
        # so the provisioner can verify that the guest actually reached running.
        if vps.status in (VPSStatus.DELETING, VPSStatus.DELETED):
            return vps
        node = vps.node
        driver = driver or self.get_driver(node)
        try:
            info = driver.get_info(vps.name)
            vps.power_state = info.state.value
            new_status = _POWER_TO_STATUS.get(info.state)
            if new_status:
                vps.status = new_status
            vps.last_error = ""
        except Exception as exc:
            vps.power_state = PowerState.UNDEFINED.value
            vps.status = VPSStatus.ERROR
            vps.last_error = str(exc)
        return vps

    # ------------------------------------------------------------ placement --
    def find_placement(
        self, db: Session, vcpus: int, ram_mb: int, disk_gb: int, node_id: int | None = None
    ) -> Node:
        query = db.query(Node).filter(Node.status != NodeStatus.DISABLED)
        if node_id is not None:
            node = query.filter(Node.id == node_id).first()
            if not node:
                raise KVMUnavailableError("Selected node does not exist.")
            if node.status != NodeStatus.ONLINE or not node.kvm_ready:
                raise KVMUnavailableError(
                    f"Node '{node.name}' is not ready (status={node.status.value}, "
                    f"KVM={'ready' if node.kvm_ready else 'unavailable'}). {node.last_error}"
                )
            return node

        candidates = query.filter(Node.status == NodeStatus.ONLINE, Node.kvm_ready.is_(True)).all()
        if not candidates:
            raise KVMUnavailableError(
                "No KVM-capable online node is registered. On hosts without nested "
                "virtualization, register an external KVM node under Virtualization Nodes."
            )
        disk_bytes = disk_gb * 1024 ** 3
        for node in candidates:
            committed_ram = sum(v.ram_mb for v in node.vps_instances if v.status != VPSStatus.DELETED)
            committed_cpu = sum(v.vcpus for v in node.vps_instances if v.status != VPSStatus.DELETED)
            committed_disk = sum(v.disk_gb for v in node.vps_instances if v.status != VPSStatus.DELETED)
            capacity_gb = self._node_disk_capacity_gb(db, node)
            if (
                committed_cpu + vcpus <= max(node.cpu_cores, vcpus)
                and committed_ram + ram_mb <= max(node.ram_mb, ram_mb)
                and (committed_disk + disk_gb) * 1024 ** 3 <= capacity_gb * 1024 ** 3
            ):
                return node
        raise KVMUnavailableError(
            "No online node has enough free CPU/RAM/disk for the requested allocation."
        )

    @staticmethod
    def _node_disk_capacity_gb(db: Session, node: Node) -> int:
        from ..models import StoragePool
        import shutil

        pools = db.query(StoragePool).filter_by(node_id=node.id).all()
        if pools:
            return max(1, sum(p.capacity_bytes for p in pools) // 1024 ** 3)
        if node.is_local:
            target = Path(settings.vm_storage_dir)
            try:
                target.mkdir(parents=True, exist_ok=True)
            except OSError:
                while not target.exists() and target != target.parent:
                    target = target.parent
            try:
                return shutil.disk_usage(str(target)).total // 1024 ** 3
            except OSError:
                pass
        return 0


manager = DriverManager()
