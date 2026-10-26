"""Real host metrics via psutil.

Unavailable counters are reported as None so the UI can show "unavailable"
instead of inventing numbers. Host metrics are distinct from per-VM stats.
"""
from __future__ import annotations

import shutil
import time

import psutil


def host_metrics() -> dict:
    cpu_percent = psutil.cpu_percent(interval=0.1)
    vm = psutil.virtual_memory()
    disk = shutil.disk_usage("/")
    net = psutil.net_io_counters()
    load = psutil.getloadavg() if hasattr(psutil, "getloadavg") else (0.0, 0.0, 0.0)
    return {
        "cpu": {
            "percent": cpu_percent,
            "cores_logical": psutil.cpu_count(logical=True) or 0,
            "cores_physical": psutil.cpu_count(logical=False) or 0,
            "load_average": {"1m": round(load[0], 2), "5m": round(load[1], 2), "15m": round(load[2], 2)},
        },
        "memory": {
            "total_bytes": vm.total,
            "used_bytes": vm.used,
            "available_bytes": vm.available,
            "percent": vm.percent,
        },
        "disk": {
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "free_bytes": disk.free,
            "percent": round(disk.used / disk.total * 100, 2) if disk.total else 0.0,
        },
        "network": {
            "bytes_sent": net.bytes_sent,
            "bytes_recv": net.bytes_recv,
            "packets_sent": net.packets_sent,
            "packets_recv": net.packets_recv,
        },
        "boot_time": psutil.boot_time(),
        "collected_at": time.time(),
    }


def cpu_timeseries(seconds: int = 60) -> list[dict]:
    """Small in-process ring buffer for recent CPU/RAM history."""
    buffer = _ring_buffer()
    return buffer[-seconds:]


_RING: list[dict] = []


def _ring_buffer() -> list[dict]:
    return _RING


def record_sample() -> dict:
    sample = {
        "ts": time.time(),
        "cpu_percent": psutil.cpu_percent(interval=None),
        "mem_percent": psutil.virtual_memory().percent,
    }
    _RING.append(sample)
    if len(_RING) > 300:  # keep five minutes at 1s cadence
        _RING.pop(0)
    return sample
