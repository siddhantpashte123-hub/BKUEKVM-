"""VPS API validation, filtering, idempotency and destructive-action guards."""
import pytest


def _payload(**overrides):
    base = {
        "name": "vm-api-test",
        "hostname": "vm-api-test",
        "template_id": 1,
        "vcpus": 1,
        "ram_mb": 512,
        "disk_gb": 10,
    }
    base.update(overrides)
    return base


def test_create_vps_validates_input(admin_client, ready_template):
    bad = admin_client.post("/api/vps", json=_payload(vcpus=0))
    assert bad.status_code == 422


def test_create_vps_rejects_unready_template(admin_client, db):
    from app.models import OSNodeTemplate, TemplateStatus

    template = OSNodeTemplate(
        name="Unready Ubuntu",
        os_family="ubuntu",
        version="99.04",
        image_url="https://example.com/unready.img",
        status=TemplateStatus.NOT_DOWNLOADED,
    )
    db.add(template)
    db.commit()
    resp = admin_client.post("/api/vps", json=_payload(name="unready-vm", template_id=template.id))
    assert resp.status_code == 409
    assert "not ready" in resp.json()["detail"]


def test_create_vps_fails_honestly_when_no_node_available(admin_client, db, ready_template):
    from app.models import Node, NodeStatus

    node = db.query(Node).first()
    original = (node.status, node.kvm_ready)
    node.status = NodeStatus.OFFLINE
    node.kvm_ready = False
    db.commit()
    try:
        resp = admin_client.post("/api/vps", json=_payload(name="no-node-vm"))
        assert resp.status_code in (409, 400)
        assert "KVM" in resp.json()["detail"] or "node" in resp.json()["detail"].lower()
    finally:
        node.status, node.kvm_ready = original
        db.commit()


def test_create_vps_queues_task(admin_client, ready_template, fake_driver):
    resp = admin_client.post("/api/vps", json=_payload(name="queued-vm"))
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "pending"
    tasks = admin_client.get(f"/api/vps/{body['public_id']}/tasks").json()
    assert any(t["task_type"] == "create_vps" and t["status"] == "queued" for t in tasks)


def test_duplicate_idempotency_key_returns_same_vps(admin_client, ready_template, fake_driver):
    payload = _payload(name="idempotent-vm", idempotency_key="key-123")
    first = admin_client.post("/api/vps", json=payload)
    second = admin_client.post("/api/vps", json=payload)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


def test_duplicate_name_conflict(admin_client, ready_template, fake_driver):
    admin_client.post("/api/vps", json=_payload(name="dup-name"))
    resp = admin_client.post("/api/vps", json=_payload(name="dup-name", hostname="other"))
    assert resp.status_code == 409


def test_list_search_filter_and_pagination(admin_client, ready_template, fake_driver):
    for i in range(3):
        admin_client.post(
            "/api/vps",
            json=_payload(name=f"list-vm-{i}", hostname=f"list-vm-{i}"),
        )
    resp = admin_client.get("/api/vps?search=list-vm&page_size=2")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 3
    assert len(body["items"]) == 2
    assert body["pages"] >= 2

    filtered = admin_client.get("/api/vps?status=pending")
    assert all(item["status"] == "pending" for item in filtered.json()["items"])


def test_delete_requires_name_confirmation(admin_client, ready_template, fake_driver):
    created = admin_client.post("/api/vps", json=_payload(name="confirm-delete")).json()
    bad = admin_client.delete(f"/api/vps/{created['public_id']}?confirm=wrong")
    assert bad.status_code == 400
    ok = admin_client.delete(f"/api/vps/{created['public_id']}?confirm=confirm-delete")
    assert ok.status_code == 200


def test_unknown_vps_returns_404(admin_client):
    assert admin_client.get("/api/vps/does-not-exist").status_code == 404
