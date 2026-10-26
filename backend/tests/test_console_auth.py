"""Console session authorization and the WebSocket VNC bridge."""
import socketserver
import threading

import pytest
from starlette.websockets import WebSocketDisconnect

from tests.helpers import drain_tasks


class _EchoHandler(socketserver.BaseRequestHandler):
    def handle(self):
        while True:
            data = self.request.recv(4096)
            if not data:
                break
            self.request.sendall(data)


class _ThreadedEchoServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True


def _start_echo_server():
    server = _ThreadedEchoServer(("127.0.0.1", 0), _EchoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_console_token_required(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/console"):
            pass
    assert exc.value.code == 4401


def test_console_token_is_single_use(admin_client, fake_driver):
    created = admin_client.post(
        "/api/vps",
        json={
            "name": "console-vm",
            "hostname": "console-vm",
            "template_id": 1,
            "vcpus": 1,
            "ram_mb": 512,
            "disk_gb": 10,
        },
    ).json()
    drain_tasks()

    server, thread = _start_echo_server()
    fake_driver.console_port = server.server_address[1]
    # Driver info is built lazily; point the existing domain at the echo port
    fake_driver.domains["console-vm"].console_port = server.server_address[1]
    try:
        session = admin_client.post(
            f"/api/vps/{created['public_id']}/console-session"
        ).json()
        assert session["ws_path"].startswith("/ws/console?token=")

        with admin_client.websocket_connect(session["ws_path"]) as ws:
            ws.send_bytes(b"hello-vnc")
            assert ws.receive_bytes() == b"hello-vnc"

        # Replaying the consumed token must fail
        with pytest.raises(WebSocketDisconnect) as exc2:
            with admin_client.websocket_connect(session["ws_path"]):
                pass
        assert exc2.value.code == 4401
    finally:
        server.shutdown()


def test_console_session_requires_vps_access(admin_client, db, client):
    # Create a second non-privileged user who owns nothing
    roles = {r["name"]: r["id"] for r in admin_client.get("/api/users/roles").json()}
    admin_client.post(
        "/api/users",
        json={
            "username": "lonelyviewer",
            "email": "lonely@example.com",
            "password": "V1ewer!Strong99x",
            "role_id": roles["Read-Only Viewer"],
        },
    )
    admin_client.post(
        "/api/vps",
        json={
            "name": "owned-by-admin",
            "hostname": "owned-by-admin",
            "template_id": 1,
            "vcpus": 1,
            "ram_mb": 512,
            "disk_gb": 10,
        },
    )
    drain_tasks()
    target = admin_client.get("/api/vps?search=owned-by-admin").json()["items"][0]

    client.post(
        "/api/auth/login", json={"username": "lonelyviewer", "password": "V1ewer!Strong99x"}
    )
    resp = client.post(f"/api/vps/{target['public_id']}/console-session")
    assert resp.status_code == 403
