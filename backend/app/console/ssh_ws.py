"""Authenticated WebSocket SSH terminal for VPS instances.

Threat model mirrors the VNC console proxy:
  * Browsers cannot do raw SSH, so the panel bridges a WebSocket to an
    asyncssh connection running on the node that can reach the guest's
    private/NAT IP address.
  * The browser presents a single-use, 60-second "ssh" console token minted
    by POST /api/vps/{id}/ssh-session after normal cookie authentication.
  * The VM password stays encrypted in the database and is decrypted only
    inside this process — it is never sent to the browser.
  * Guest host keys are not pinned (panel-provisioned guests on private
    networks); the connection never leaves the node and no key is stored.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

import asyncssh
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..database import SessionLocal
from ..models import ConsoleSession, User, VPS, VPSStatus
from ..security import decrypt_secret, hash_token
from ..virtualization.manager import manager

log = logging.getLogger("bluekvm.console.ssh")
router = APIRouter()


def _valid_ssh_session(db, token: str) -> ConsoleSession | None:
    session = db.query(ConsoleSession).filter(
        ConsoleSession.token_hash == hash_token(token)
    ).first()
    if not session or session.kind != "ssh":
        return None
    if session.revoked_at is not None or session.used_at is not None:
        return None
    now = datetime.now(timezone.utc)
    expires = session.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < now:
        return None
    user = db.get(User, session.user_id)
    if not user or not user.is_active:
        return None
    return session


class _SSHClient(asyncssh.SSHClient):
    """Minimal client; asyncssh drives auth and key exchange internally."""

    def __init__(self) -> None:
        self.conn: asyncssh.SSHClientConnection | None = None

    def connection_made(self, conn: asyncssh.SSHClientConnection) -> None:
        self.conn = conn


class _TerminalSession(asyncssh.SSHClientSession):
    """Pumps SSH stdout/stderr into the browser WebSocket."""

    def __init__(self, ws: WebSocket) -> None:
        self._ws = ws
        self._closed = False

    def data_received(self, data: str, datatype: asyncssh.DataType) -> None:
        if self._closed:
            return
        asyncio.create_task(self._safe_send(data))

    async def _safe_send(self, data: str) -> None:
        try:
            await self._ws.send_text(data)
        except Exception:  # browser already gone
            self._closed = True

    def exit_status_received(self, status: int) -> None:
        asyncio.create_task(self._safe_send(f"\r\n[session exited with status {status}]\r\n"))

    def connection_lost(self, exc: Exception | None) -> None:
        self._closed = True


async def _run_terminal(ws: WebSocket, vps: VPS, host: str, username: str, password: str) -> None:
    rows = int(ws.query_params.get("rows", "24"))
    cols = int(ws.query_params.get("cols", "120"))
    rows = max(10, min(rows, 200))
    cols = max(20, min(cols, 400))

    client = _SSHClient()
    try:
        conn, _ = await asyncio.wait_for(
            asyncssh.create_connection(
                lambda: client,
                host=host,
                port=22,
                username=username,
                password=password,
                known_hosts=None,  # private panel network; no key persistence
                connect_timeout=10,
            ),
            timeout=12,
        )
    except (OSError, asyncssh.Error, asyncio.TimeoutError) as exc:
        await ws.close(code=4503, reason=f"SSH connection failed: {exc}")
        return

    try:
        chan, session = await conn.create_session(
            lambda: _TerminalSession(ws),
            term_type="xterm-256color",
            term_size=(rows, cols, 0, 0),
        )
        await ws.accept()
        log.info("SSH terminal attached to VPS %s (%s@%s)", vps.id, username, host)

        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break
            if chan.is_closed():
                break
            text = message.get("text")
            if text is None:
                continue
            # JSON control frames handle resize; everything else is raw stdin
            if text.startswith("{"):
                try:
                    control = json.loads(text)
                except json.JSONDecodeError:
                    control = None
                if isinstance(control, dict) and control.get("type") == "resize":
                    new_cols = int(control.get("cols", cols))
                    new_rows = int(control.get("rows", rows))
                    chan.change_terminal_size(new_rows, new_cols)
                    continue
            chan.write(text)
    except WebSocketDisconnect:
        pass
    except (OSError, asyncssh.Error) as exc:
        log.warning("SSH terminal error for VPS %s: %s", vps.id, exc)
    finally:
        try:
            conn.close()
        except Exception:
            pass


@router.websocket("/ws/ssh")
async def ssh_terminal(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token", "")
    db = SessionLocal()
    session = None
    try:
        session = _valid_ssh_session(db, token)
        if not session:
            await websocket.close(code=4401)
            return
        vps = db.get(VPS, session.vps_id)
        if not vps or vps.status == VPSStatus.DELETED:
            await websocket.close(code=4404)
            return
        if not vps.init_password_encrypted:
            await websocket.close(code=4501, reason="No stored credential for this VPS")
            return

        # Consume the token immediately (single use)
        session.used_at = datetime.now(timezone.utc)
        db.commit()

        try:
            driver = manager.get_driver(vps.node)
            host = vps.ip_address or driver.get_guest_ip(vps.name, vps.mac_address)
        except Exception as exc:  # noqa: BLE001
            log.warning("SSH target unavailable for vps=%s: %s", vps.id, exc)
            await websocket.close(code=4500)
            return
        if not host:
            await websocket.close(
                code=4502,
                reason="Guest IP not available yet (no DHCP lease / agent response)",
            )
            return

        try:
            password = decrypt_secret(vps.init_password_encrypted)
        except ValueError:
            await websocket.close(code=4501, reason="Stored credential cannot be decrypted")
            return

        await _run_terminal(
            websocket, vps, host=host,
            username=vps.cloud_init_user or "ubuntu", password=password,
        )
    finally:
        if session is not None:
            session.revoked_at = datetime.now(timezone.utc)
            db.commit()
        db.close()
