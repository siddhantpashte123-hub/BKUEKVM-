"""Authenticated WebSocket proxy to per-VM QEMU VNC consoles.

Threat model:
  * Browsers cannot send Authorization headers on WebSocket handshakes, so
    the browser presents a single-use, 60-second console token minted by
    POST /api/vps/{id}/console-session after normal cookie authentication.
  * Raw VNC ports stay bound to 127.0.0.1 and are never exposed publicly;
    all traffic is bridged server-side after authorization.
  * A token is bound to one user and one VPS and is consumed on first use,
    so a leaked token cannot be replayed or redirected to another VM.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..database import SessionLocal
from ..models import ConsoleSession, User, VPS, VPSStatus
from ..security import hash_token
from ..virtualization.manager import manager

log = logging.getLogger("bluekvm.console")
router = APIRouter()


def _valid_session(db, token: str) -> ConsoleSession | None:
    session = db.query(ConsoleSession).filter(
        ConsoleSession.token_hash == hash_token(token)
    ).first()
    if not session or session.revoked_at is not None or session.used_at is not None:
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


async def _pump(ws: WebSocket, tcp_write: asyncio.StreamWriter, tcp_read: asyncio.StreamReader) -> None:
    async def ws_to_tcp() -> None:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                tcp_write.close()
                return
            data = message.get("bytes") or message.get("text")
            if data is None:
                continue
            if isinstance(data, str):
                data = data.encode("latin-1")
            tcp_write.write(data)
            await tcp_write.drain()

    async def tcp_to_ws() -> None:
        while True:
            chunk = await tcp_read.read(4096)
            if not chunk:
                await ws.close()
                return
            await ws.send_bytes(chunk)

    await asyncio.gather(ws_to_tcp(), tcp_to_ws(), return_exceptions=True)


@router.websocket("/ws/console")
async def console_proxy(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token", "")
    db = SessionLocal()
    try:
        session = _valid_session(db, token)
        if not session:
            await websocket.close(code=4401)
            return
        vps = db.get(VPS, session.vps_id)
        if not vps or vps.status == VPSStatus.DELETED:
            await websocket.close(code=4404)
            return

        # Consume the token immediately (single use)
        session.used_at = datetime.now(timezone.utc)
        db.commit()

        try:
            driver = manager.get_driver(vps.node)
            info = driver.get_info(vps.name)
        except Exception as exc:  # noqa: BLE001
            log.warning("Console target unavailable for vps=%s: %s", vps.id, exc)
            await websocket.close(code=4500)
            return

        if not info.console_port or info.console_port <= 0:
            log.warning("VPS %s has no VNC console endpoint", vps.name)
            await websocket.close(code=4501)
            return
        if info.console_host not in ("127.0.0.1", "localhost", "0.0.0.0", "::1"):
            # Remote-node consoles require the documented SSH tunnel; never
            # open arbitrary outbound console connections from the panel.
            log.warning("Refusing console proxy to remote address %s", info.console_host)
            await websocket.close(code=4502)
            return

        try:
            tcp_read, tcp_write = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", info.console_port), timeout=5
            )
        except (OSError, asyncio.TimeoutError) as exc:
            log.warning("Cannot reach VNC 127.0.0.1:%s: %s", info.console_port, exc)
            await websocket.close(code=4503)
            return

        # noVNC negotiates the "binary" subprotocol
        await websocket.accept(subprotocol="binary")
        log.info("Console session %s attached to VPS %s (vnc :%s)", session.id, vps.name, info.console_port)
        try:
            await _pump(websocket, tcp_write, tcp_read)
        except WebSocketDisconnect:
            pass
        finally:
            tcp_write.close()
            session.revoked_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()
