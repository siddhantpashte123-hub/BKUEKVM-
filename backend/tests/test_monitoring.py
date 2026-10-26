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


def test_metrics_timeseries_endpoint(admin_client):
    from app.services.metrics import record_sample

    record_sample()
    body = admin_client.get("/api/dashboard/metrics").json()
    assert "timeseries" in body
    assert body["memory"]["percent"] >= 0
