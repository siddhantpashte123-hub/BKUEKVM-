"""Host virtualization capability detection.

Every check here reflects real kernel/hypervisor state. When KVM is not
usable (common inside an unprivileged VPS without nested virtualization),
the panel reports the precise reason instead of pretending VMs can run.
"""
from __future__ import annotations

import os
import platform
import shutil
from dataclasses import dataclass, field


@dataclass
class HostCapabilities:
    arch: str = ""
    kvm_available: bool = False
    kvm_reason: str = ""
    nested_virtualization: bool = False
    nested_detail: str = ""
    libvirt_python: bool = False
    libvirtd_running: bool = False
    qemu_installed: bool = False
    qemu_img: str = ""
    cloud_image_tools: list[str] = field(default_factory=list)
    extras: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "arch": self.arch,
            "kvm_available": self.kvm_available,
            "kvm_reason": self.kvm_reason,
            "nested_virtualization": self.nested_virtualization,
            "nested_detail": self.nested_detail,
            "libvirt_python": self.libvirt_python,
            "libvirtd_running": self.libvirtd_running,
            "qemu_installed": self.qemu_installed,
            "qemu_img": self.qemu_img,
            "cloud_image_tools": self.cloud_image_tools,
            "extras": self.extras,
        }


def _cpu_vmx_svm() -> bool:
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as fh:
            flags_line = [ln for ln in fh if ln.startswith("flags")]
        if not flags_line:
            return False
        flags = flags_line[0].lower()
        return " vmx " in f" {flags} " or " svm " in f" {flags} "
    except OSError:
        return False


def _nested_status() -> tuple[bool, str]:
    base = "/sys/module/"
    for module in ("kvm_intel", "kvm_amd"):
        param = os.path.join(base, module, "parameters", "nested")
        if os.path.exists(param):
            try:
                value = open(param, encoding="utf-8").read().strip()
            except OSError:
                value = "unknown"
            enabled = value in ("Y", "y", "1")
            return enabled, f"{module}.nested={value}"
    return False, "kvm_intel/kvm_amd module parameters not exposed"


def _probe_kvm_device() -> tuple[bool, str]:
    """Open /dev/kvm for real instead of relying on os.access.

    A device node can be visible yet unusable: container device cgroups,
    seccomp or restrictive mounts reject open() even when stat/access look
    fine. Only an actual open(O_RDWR) proves QEMU will be able to use KVM.
    """
    if not os.path.exists("/dev/kvm"):
        if not _cpu_vmx_svm():
            return False, (
                "CPU virtualization extensions (VMX/SVM) not exposed to this host"
            )
        return False, (
            "CPU supports virtualization but /dev/kvm is missing "
            "(KVM modules not loaded or nested virt disabled)"
        )
    try:
        fd = os.open("/dev/kvm", os.O_RDWR)
    except OSError as exc:
        detail = exc.strerror or str(exc)
        return False, (
            f"/dev/kvm exists but cannot be opened ({detail}). "
            "The container device cgroup/seccomp policy is blocking KVM access."
        )
    else:
        os.close(fd)
        if not os.access("/dev/kvm", os.R_OK | os.W_OK):
            return False, "/dev/kvm opens for root but is not read/writable for the hypervisor group (libvirt/kvm)"
        return True, "/dev/kvm present and openable (O_RDWR probe succeeded)"


def detect_capabilities() -> HostCapabilities:
    caps = HostCapabilities(arch=platform.machine() or "unknown")

    # KVM device — real open() probe, not just a permission bit check
    caps.kvm_available, caps.kvm_reason = _probe_kvm_device()

    caps.nested_virtualization, caps.nested_detail = _nested_status()

    # libvirt Python binding
    try:
        import libvirt  # noqa: F401

        caps.libvirt_python = True
    except ImportError:
        caps.libvirt_python = False

    # libvirtd / virtqemud socket
    caps.libvirtd_running = any(
        os.path.exists(p)
        for p in (
            "/var/run/libvirt/libvirt-sock",
            "/run/libvirt/libvirt-sock",
            "/run/libvirt/virtqemud-sock",
        )
    )

    # QEMU and disk tooling
    qemu = shutil.which("qemu-system-x86_64") or shutil.which("qemu-system-aarch64")
    caps.qemu_installed = qemu is not None
    caps.qemu_img = shutil.which("qemu-img") or ""
    caps.cloud_image_tools = [
        tool for tool in ("cloud-localds", "genisoimage", "xorriso", "mkisofs") if shutil.which(tool)
    ]
    return caps
