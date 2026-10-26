"""Pytest fixtures.

Environment is configured BEFORE application import because settings are
cached at import time. The FakeDriver below is a test-only double standing
in for libvirt: production code paths still use the real LibvirtDriver and
never fake a successful VM.
"""
from __future__ import annotations

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="bluekvm-test-")
os.environ["BLUEKVM_ENV"] = "test"
os.environ["BLUEKVM_COOKIE_SECURE"] = "0"
os.environ["BLUEKVM_CSRF_ENABLED"] = "0"
os.environ["BLUEKVM_ADMIN_USERNAME"] = "admin"
os.environ["BLUEKVM_ADMIN_EMAIL"] = "admin@test.local"
os.environ["BLUEKVM_ADMIN_PASSWORD"] = "Sup3rStr0ng!Passw0rd"
os.environ["BLUEKVM_VM_STORAGE_DIR"] = os.path.join(_TMP, "vms")
os.environ["BLUEKVM_TEMPLATE_DIR"] = os.path.join(_TMP, "templates")
os.environ["BLUEKVM_BACKUP_DIR"] = os.path.join(_TMP, "backups")
os.environ["BLUEKVM_LOG_DIR"] = os.path.join(_TMP, "logs")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP, 'test.db')}"
os.environ["BLUEKVM_EMBEDDED_WORKER"] = "0"
os.environ["BLUEKVM_STARTUP_HEALTHCHECK"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Node,
    NodeStatus,
    OSNodeTemplate,
    StoragePool,
    TemplateStatus,
    User,
)
from app.virtualization.base import (  # noqa: E402
    HypervisorDriver,
    NetworkInfo,
    PoolInfo,
    PowerState,
    VMInfo,
    VMSpec,
    VMStats,
)
from app.virtualization.manager import manager  # noqa: E402


class FakeDriver(HypervisorDriver):
    """Deterministic in-memory hypervisor double (tests only)."""

    def __init__(self) -> None:
        self.uri = "fake:///test"
        self.domains: dict[str, VMInfo] = {}
        self.fail_define: bool = False
        self.console_port: int = 0

    def test_connection(self) -> dict:
        return {"hostname": "fake-node", "libvirt_version": "9.0.0", "hypervisor": "KVM"}

    def define_vm(self, spec: VMSpec) -> VMInfo:
        if self.fail_define:
            from app.virtualization.base import HypervisorError

            raise HypervisorError("Injected define failure")
        import uuid

        info = VMInfo(
            name=spec.name,
            uuid=str(uuid.uuid4()),
            state=PowerState.SHUTOFF,
            vcpus=spec.vcpus,
            ram_mb=spec.ram_mb,
            console_host="127.0.0.1",
            console_port=self.console_port,
        )
        self.domains[spec.name] = info
        return info

    def start(self, name: str) -> None:
        self.domains[name].state = PowerState.RUNNING

    def power_off(self, name: str) -> None:
        self.domains[name].state = PowerState.SHUTOFF

    def shutdown(self, name: str, timeout: int = 60) -> None:
        self.power_off(name)

    def restart(self, name: str) -> None:
        self.domains[name].state = PowerState.RUNNING

    def delete(self, name: str, purge_disks: bool = True) -> None:
        self.domains.pop(name, None)

    def get_info(self, name: str) -> VMInfo:
        if name not in self.domains:
            from app.virtualization.base import HypervisorError

            raise HypervisorError(f"Domain '{name}' is not defined on this node")
        return self.domains[name]

    def get_stats(self, name: str) -> VMStats:
        return VMStats(cpu_percent=1.5, ram_used_mb=128.0, ram_total_mb=512, available=True)

    def list_domains(self) -> list[VMInfo]:
        return list(self.domains.values())

    def list_pools(self) -> list[PoolInfo]:
        return [PoolInfo("default", "dir", 100_000_000_000, 10_000_000_000, 90_000_000_000, True)]

    def list_networks(self) -> list[NetworkInfo]:
        return [NetworkInfo("default", "virbr0", "nat", True, "192.168.122.0", True)]

    def create_snapshot(self, name: str, snapshot_name: str) -> str:
        return snapshot_name

    def delete_snapshot(self, name: str, snapshot_name: str) -> None:
        return None

    def close(self) -> None:
        return None


@pytest.fixture(scope="session", autouse=True)
def _prepare_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    from app.bootstrap import run_bootstrap

    run_bootstrap(db, health_check=False)
    node = db.query(Node).filter(Node.is_local.is_(True)).first()
    node.status = NodeStatus.ONLINE
    node.kvm_ready = True
    node.cpu_cores = 32
    node.ram_mb = 65536
    # A 10 TiB registered pool so placement uses declared pool capacity
    if not db.query(StoragePool).filter_by(node_id=node.id).first():
        db.add(
            StoragePool(
                node_id=node.id, name="test-pool", pool_type="dir",
                path=os.environ["BLUEKVM_VM_STORAGE_DIR"],
                capacity_bytes=10 * 1024 ** 4, used_bytes=0, status="active",
            )
        )
    template = db.query(OSNodeTemplate).first()
    template.status = TemplateStatus.READY
    template.image_path = os.path.join(os.environ["BLUEKVM_TEMPLATE_DIR"], "fake.qcow2")
    open(template.image_path, "wb").write(b"fake-image")
    db.commit()
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    from app.ratelimit import login_limiter

    login_limiter.reset()
    yield
    login_limiter.reset()


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def fake_driver(monkeypatch):
    driver = FakeDriver()
    monkeypatch.setattr(manager, "get_driver", lambda node: driver)
    return driver


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin_client(client):
    resp = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "Sup3rStr0ng!Passw0rd"},
    )
    assert resp.status_code == 200, resp.text
    return client


@pytest.fixture
def admin_user(db):
    return db.query(User).filter(User.username == "admin").first()


@pytest.fixture
def ready_template(db):
    return db.query(OSNodeTemplate).first()


def drain_tasks(max_iterations: int = 50) -> int:
    """Process every queued task (oldest first) until the queue is empty."""
    from app.services.worker import worker_iteration

    processed = 0
    for _ in range(max_iterations):
        if not worker_iteration():
            break
        processed += 1
    return processed


@pytest.fixture
def drain():
    return drain_tasks
