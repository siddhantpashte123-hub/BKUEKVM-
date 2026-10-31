"""Health endpoints, real host metrics and dashboard aggregation."""


def test_liveness_is_public(client):
    resp = client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json()["status"] == "alive"


def test_readiness_checks_database_and_kvm(client):
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["checks"]["database"] == "connected"
    # In this sandbox KVM is genuinely unavailable; the value must be explicit
    assert body["checks"]["kvm"] in ("ready", "unavailable")


def test_host_metrics_are_real(admin_client):
    body = admin_client.get("/api/monitoring/host").json()
    assert body["cpu"]["cores_logical"] >= 1
    assert body["memory"]["total_bytes"] > 0
    assert body["disk"]["total_bytes"] > 0
    assert isinstance(body["network"]["bytes_recv"], int)


def test_service_health_reports_virtualization_state(admin_client):
    body = admin_client.get("/api/monitoring/health").json()
    names = {s["name"] for s in body["services"]}
    assert {"sqlite", "kvm", "libvirt", "worker"}.issubset(names)


def test_dashboard_summary_counts(admin_client, ready_template, fake_driver):
    before = admin_client.get("/api/dashboard/summary").json()
    admin_client.post(
        "/api/vps",
        json={
            "name": "dash-vm",
            "hostname": "dash-vm",
            "template_id": ready_template.id,
            "vcpus": 1,
            "ram_mb": 512,
            "disk_gb": 10,
        },
    )
    after = admin_client.get("/api/dashboard/summary").json()
    assert after["vps_total"] == before["vps_total"] + 1
    assert after["vps_provisioning"] >= 1

    activity = admin_client.get("/api/dashboard/activity").json()
    assert "tasks" in activity and "audit" in activity


def test_dashboard_collector_runs_in_api_when_worker_is_separate(monkeypatch):
    import time
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services.metrics import _RING

    monkeypatch.setenv("BLUEKVM_EMBEDDED_WORKER", "0")
    _RING.clear()
    with TestClient(app) as client:
        response = client.post("/api/auth/login", json={
            "username": "admin", "password": "Sup3rStr0ng!Passw0rd",
        })
        assert response.status_code == 200
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            samples = client.get("/api/dashboard/metrics").json()["timeseries"]
            if len(samples) >= 2:
                break
            time.sleep(0.2)
        assert len(samples) >= 2
        assert samples[-1]["ts"] > samples[0]["ts"]
        assert all(0 <= sample["cpu_percent"] <= 100 for sample in samples)


def test_metrics_timeseries_endpoint(admin_client):
    from app.services.metrics import record_sample

    record_sample()
    body = admin_client.get("/api/dashboard/metrics").json()
    assert "timeseries" in body
    assert body["memory"]["percent"] >= 0
