"""Abstract hypervisor driver contract.

All virtualization operations go through this restricted service layer.
The web process never invokes shell commands with user-controlled input;
drivers receive validated specification objects and use libvirt APIs or
fixed-argument subprocess calls only.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class PowerState(str, Enum):
    RUNNING = "running"
    BLOCKED = "blocked"
    PAUSED = "paused"
    SHUTDOWN = "shutdown"
    SHUTOFF = "shutoff"
    CRASHED = "crashed"
    UNDEFINED = "undefined"
    UNKNOWN = "unknown"


@dataclass
class VMSpec:
    name: str
    hostname: str
    vcpus: int
    ram_mb: int
    disk_gb: int
    base_image_path: str
    libvirt_network: str
    bridge: str = ""
    ssh_public_key: str = ""
    cloud_init_user: str = "ubuntu"
    cloud_init_password: str = ""
    storage_dir: str = ""
    mac_address: str = ""


@dataclass
class VMInfo:
    name: str
    uuid: str = ""
    state: PowerState = PowerState.UNKNOWN
    vcpus: int = 0
    ram_mb: int = 0
    console_host: str = ""
    console_port: int = 0
    console_socket: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class VMStats:
    cpu_percent: float | None = None
    ram_used_mb: float | None = None
    ram_total_mb: int = 0
    disk_used_bytes: int | None = None
    network_rx_bytes: int | None = None
    network_tx_bytes: int | None = None
    available: bool = False
    reason: str = ""


@dataclass
class PoolInfo:
    name: str
    pool_type: str
    capacity_bytes: int
    used_bytes: int
    available_bytes: int
    active: bool


@dataclass
class NetworkInfo:
    name: str
    bridge: str
    network_type: str
    active: bool
    subnet: str = ""
    dhcp_enabled: bool = False


class HypervisorError(Exception):
    """Raised for hypervisor-level failures with actionable messages."""


class KVMUnavailableError(HypervisorError):
    """Raised when the host cannot create KVM-based virtual machines."""


class HypervisorDriver(ABC):
    uri: str

    @abstractmethod
    def test_connection(self) -> dict:
        """Verify connectivity and return hypervisor information."""

    @abstractmethod
    def define_vm(self, spec: VMSpec) -> VMInfo:
        """Create disk, cloud-init media and a persistent libvirt domain."""

    @abstractmethod
    def start(self, name: str) -> None: ...

    @abstractmethod
    def power_off(self, name: str) -> None: ...

    @abstractmethod
    def shutdown(self, name: str, timeout: int = 60) -> None: ...

    @abstractmethod
    def restart(self, name: str) -> None: ...

    @abstractmethod
    def delete(self, name: str, purge_disks: bool = True) -> None: ...

    @abstractmethod
    def get_info(self, name: str) -> VMInfo: ...

    @abstractmethod
    def get_stats(self, name: str) -> VMStats: ...

    @abstractmethod
    def list_domains(self) -> list[VMInfo]: ...

    @abstractmethod
    def list_pools(self) -> list[PoolInfo]: ...

    @abstractmethod
    def list_networks(self) -> list[NetworkInfo]: ...

    @abstractmethod
    def create_snapshot(self, name: str, snapshot_name: str) -> str: ...

    @abstractmethod
    def delete_snapshot(self, name: str, snapshot_name: str) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    # ------------------------------------------------- optional capabilities
    # Concrete defaults keep test doubles / alternative drivers working
    # without forcing every implementation to override them.
    def get_guest_ip(self, name: str, mac: str = "") -> str:
        """Return the guest's first IPv4 address, or '' when unknown."""
        return ""

    def ensure_default_network(self) -> str:
        """Ensure the default NAT network exists and is started.

        Returns one of: active | defined | unsupported | unavailable.
        """
        return "unsupported"
