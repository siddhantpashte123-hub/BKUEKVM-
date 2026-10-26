"""Role-based access control enforcement."""


def _create_user(client, username: str, role_name: str, password: str = "V1ewer!Strong99x"):
    roles = {r["name"]: r["id"] for r in client.get("/api/users/roles").json()}
    return client.post(
        "/api/users",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": password,
            "role_id": roles[role_name],
        },
    )


def test_viewer_cannot_create_vps_or_users(admin_client, client, ready_template):
    resp = _create_user(admin_client, "viewer1", "Read-Only Viewer")
    assert resp.status_code == 201

    login = client.post(
        "/api/auth/login", json={"username": "viewer1", "password": "V1ewer!Strong99x"}
    )
    assert login.status_code == 200

    # Read access works
    assert client.get("/api/vps").status_code == 200
    assert client.get("/api/dashboard/summary").status_code == 200

    # Write access denied
    forbidden = client.post(
        "/api/vps",
        json={
            "name": "should-fail",
            "hostname": "should-fail",
            "template_id": ready_template.id,
            "vcpus": 1,
            "ram_mb": 512,
            "disk_gb": 10,
        },
    )
    assert forbidden.status_code == 403
    assert client.get("/api/users").status_code == 403
    assert client.get("/api/audit-logs").status_code == 403


def test_vps_manager_can_provision_but_not_manage_users(admin_client, client, ready_template):
    resp = _create_user(admin_client, "manager1", "VPS Manager")
    assert resp.status_code == 201
    client.post(
        "/api/auth/login", json={"username": "manager1", "password": "V1ewer!Strong99x"}
    )
    allowed = client.post(
        "/api/vps",
        json={
            "name": "manager-vm",
            "hostname": "manager-vm",
            "template_id": ready_template.id,
            "vcpus": 1,
            "ram_mb": 512,
            "disk_gb": 10,
        },
    )
    assert allowed.status_code == 201
    assert client.get("/api/users").status_code == 403


def test_scoped_user_only_sees_owned_vps(admin_client, client, ready_template, db):
    from app.models import User

    _create_user(admin_client, "scoped1", "Read-Only Viewer")
    scoped = db.query(User).filter(User.username == "scoped1").first()

    # Perform ALL admin work before switching the shared client's session
    owned = admin_client.post(
        "/api/vps",
        json={
            "name": "scoped-owned",
            "hostname": "scoped-owned",
            "template_id": ready_template.id,
            "vcpus": 1,
            "ram_mb": 512,
            "disk_gb": 10,
            "owner_id": scoped.id,
        },
    )
    assert owned.status_code == 201
    admin_client.post(
        "/api/vps",
        json={
            "name": "scoped-other",
            "hostname": "scoped-other",
            "template_id": ready_template.id,
            "vcpus": 1,
            "ram_mb": 512,
            "disk_gb": 10,
        },
    )

    # Now switch the shared client to the restricted user
    client.post(
        "/api/auth/login", json={"username": "scoped1", "password": "V1ewer!Strong99x"}
    )
    visible = client.get("/api/vps").json()
    names = {v["name"] for v in visible["items"]}
    assert "scoped-owned" in names
    assert "scoped-other" not in names


def test_superadmin_has_wildcard_permissions(admin_client):
    perms = admin_client.get("/api/auth/permissions").json()["permissions"]
    assert "*" in perms
