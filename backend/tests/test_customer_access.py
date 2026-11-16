"""Tenant-facing authorization regression tests (no real hypervisor)."""
from tests.helpers import drain_tasks


def test_customer_only_controls_own_vps(admin_client, client, db, ready_template, fake_driver, monkeypatch):
    from app.models import User
    from app.services.sshx_sessions import sshx_sessions

    roles = {role['name']: role for role in admin_client.get('/api/users/roles').json()}
    assert set(roles['Customer']['permissions']) == {'vps:read', 'vps:power'}
    user = admin_client.post('/api/users', json={
        'username': 'customer-test', 'email': 'customer-test@example.org',
        'password': 'Cust0mer!Strong99', 'role_id': roles['Customer']['id'],
    })
    assert user.status_code == 201
    owner_id = user.json()['id']
    def create(name, owner=None):
        payload = {'name': name, 'hostname': name, 'template_id': ready_template.id,
                   'vcpus': 1, 'ram_mb': 512, 'disk_gb': 10}
        if owner: payload['owner_id'] = owner
        response = admin_client.post('/api/vps', json=payload)
        assert response.status_code == 201, response.text
        return response.json()
    own = create('customer-owned', owner_id)
    other = create('admin-owned')
    drain_tasks()
    other_tasks = admin_client.get(f"/api/vps/{other['public_id']}/tasks").json()
    monkeypatch.setattr(sshx_sessions, 'start', lambda **kwargs: 'https://sshx.io/s/test#private')
    monkeypatch.setattr(fake_driver, 'get_guest_ip', lambda *args: '192.168.122.42', raising=False)
    assert client.post('/api/auth/login', json={
        'username': 'customer-test', 'password': 'Cust0mer!Strong99',
    }).status_code == 200
    visible = client.get('/api/vps').json()['items']
    assert {v['public_id'] for v in visible} == {own['public_id']}
    assert client.get(f"/api/vps/{other['public_id']}").status_code == 403
    for action in ('start', 'stop', 'shutdown', 'restart'):
        assert client.post(f"/api/vps/{own['public_id']}/actions/{action}", json={}).status_code == 200
        assert client.post(f"/api/vps/{other['public_id']}/actions/{action}", json={}).status_code == 403
    assert client.post(f"/api/vps/{own['public_id']}/sshx-session").status_code == 200
    assert client.post(f"/api/vps/{other['public_id']}/sshx-session").status_code == 403
    assert client.delete(f"/api/vps/{own['public_id']}?confirm=customer-owned").status_code == 403
    assert client.post(f"/api/vps/{own['public_id']}/reinstall").status_code == 403
    assert client.post(f"/api/vps/{own['public_id']}/console-session").status_code == 403
    assert client.post('/api/vps', json={'name': 'x'}).status_code == 403
    assert client.get('/api/dashboard/activity').status_code == 403
    assert client.get('/api/dashboard/metrics').status_code == 403
    assert client.get('/api/dashboard/summary').status_code == 403
    for path in ('/api/users', '/api/nodes', '/api/backups', '/api/audit-logs', '/api/settings', '/api/network'):
        assert client.get(path).status_code in (403, 404)
    assert client.get(f"/api/tasks/{other_tasks[0]['id']}").status_code == 404
    assert all(task['vps_id'] == own['id'] for task in client.get('/api/tasks').json())
