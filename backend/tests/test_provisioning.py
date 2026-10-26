"""End-to-end provisioning workflows via the worker against the test driver."""
from tests.helpers import drain_tasks


def _create(admin_client, name="prov-vm", **kw):
    payload = {
        "name": name,
        "hostname": name,
        "template_id": 1,
        "vcpus": 2,
        "ram_mb": 1024,
        "disk_gb": 20,
    }
    payload.update(kw)
    return admin_client.post("/api/vps", json=payload)


def test_full_provisioning_succeeds_and_verifies_running(admin_client, db, fake_driver):
    resp = _create(admin_client)
    assert resp.status_code == 201
    public_id = resp.json()["public_id"]

    assert drain_tasks() >= 1  # claimed and ran the task

    detail = admin_client.get(f"/api/vps/{public_id}").json()
    assert detail["status"] == "running"
    assert detail["power_state"] == "running"

    tasks = admin_client.get(f"/api/vps/{public_id}/tasks").json()
    task = tasks[0]
    assert task["status"] == "succeeded"
    assert task["progress"] == 100
    step_names = {s["name"] for s in task["steps"]}
    assert {"reserve_resources", "create_disk", "start_vm", "verify_state"}.issubset(step_names)
    assert fake_driver.domains["prov-vm"].state.value == "running"


def test_provisioning_failure_marks_task_and_vps_error(admin_client, db, fake_driver):
    fake_driver.fail_define = True
    resp = _create(admin_client, name="fail-vm")
    public_id = resp.json()["public_id"]
    drain_tasks()

    detail = admin_client.get(f"/api/vps/{public_id}").json()
    assert detail["status"] == "error"
    task = admin_client.get(f"/api/vps/{public_id}/tasks").json()[0]
    assert task["status"] == "failed"
    assert "Injected define failure" in task["error"]


def test_lifecycle_actions_drive_real_driver_states(admin_client, fake_driver):
    public_id = _create(admin_client, name="lifecycle-vm").json()["public_id"]
    drain_tasks()
    assert admin_client.get(f"/api/vps/{public_id}").json()["status"] == "running"

    admin_client.post(f"/api/vps/{public_id}/actions/stop", json={})
    drain_tasks()
    assert admin_client.get(f"/api/vps/{public_id}").json()["status"] == "stopped"

    admin_client.post(f"/api/vps/{public_id}/actions/start", json={})
    drain_tasks()
    assert admin_client.get(f"/api/vps/{public_id}").json()["status"] == "running"

    admin_client.post(f"/api/vps/{public_id}/actions/restart", json={})
    drain_tasks()
    assert fake_driver.domains["lifecycle-vm"].state.value == "running"


def test_delete_workflow_removes_domain(admin_client, db, fake_driver):
    public_id = _create(admin_client, name="delete-me").json()["public_id"]
    drain_tasks()
    assert "delete-me" in fake_driver.domains

    admin_client.delete(f"/api/vps/{public_id}?confirm=delete-me")
    drain_tasks()
    assert "delete-me" not in fake_driver.domains
    detail = admin_client.get(f"/api/vps/{public_id}")
    assert detail.status_code == 404  # deleted VPS hidden from listings


def test_worker_skips_when_queue_empty(db):
    drain_tasks()  # clear anything queued by earlier tests
    from app.services.worker import worker_iteration

    assert worker_iteration() is False


def test_duplicate_task_claim_is_safe(db):
    from app.models import Task, TaskStatus

    task = Task(task_type="start_vps")
    db.add(task)
    db.commit()
    from app.services.provisioner import claim_next_task

    first = claim_next_task(db)
    assert first is not None
    # A second session must not claim the same task
    second = claim_next_task(db)
    assert second is None
    db.refresh(task)
    assert task.status == TaskStatus.RUNNING
