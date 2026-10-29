"""Short-lived, owner-issued SSHX sessions for guest terminals.

The hosted SSHX service is a bearer-link terminal relay. BLUEKVM therefore
never stores the generated URL, never exposes a raw guest port, and destroys
the SSHX process plus its temporary credential material at expiry. The URL is
returned exactly once to a panel user who has already passed per-VPS RBAC.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import re
import select
import shlex
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from ..config import settings

log = logging.getLogger("bluekvm.sshx")

_SSHX_URL_RE = re.compile(r"^https://sshx\.io/[^\s]+$")
_START_TIMEOUT_SECONDS = 15


class SshxSessionError(RuntimeError):
    """An SSHX session could not be launched safely."""


@dataclass
class _RunningSession:
    session_id: int
    process: subprocess.Popen[str]
    workdir: Path
    expires_at: datetime
    expiry_timer: threading.Timer


class SshxSessionManager:
    """Owns hosted SSHX client processes started by this panel process."""

    def __init__(self) -> None:
        self._sessions: dict[int, _RunningSession] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _runtime_root() -> Path:
        root = Path(settings.sshx_runtime_dir)
        try:
            root.mkdir(parents=True, mode=0o700, exist_ok=True)
            os.chmod(root, 0o700)
        except OSError as exc:
            raise SshxSessionError("Could not create the protected SSHX runtime directory") from exc
        return root

    @staticmethod
    def _ssh_binary() -> str:
        ssh = shutil.which("ssh")
        if not ssh:
            raise SshxSessionError("OpenSSH client is not installed on the panel node")
        return ssh

    @staticmethod
    def _sshx_binary() -> str:
        configured = Path(settings.sshx_binary)
        if configured.is_file() and os.access(configured, os.X_OK):
            return str(configured)
        discovered = shutil.which("sshx")
        if discovered:
            return discovered
        raise SshxSessionError(
            "SSHX client is not installed on the panel node. Run the latest BLUEKVM installer update."
        )

    @staticmethod
    def _safe_sshx_url(value: str) -> str | None:
        value = value.strip()
        if not _SSHX_URL_RE.fullmatch(value):
            return None
        parsed = urlparse(value)
        if parsed.scheme != "https" or parsed.hostname != "sshx.io" or not parsed.path:
            return None
        return value

    @staticmethod
    def _write_launcher(workdir: Path, *, host: str, username: str, password: str, known_hosts: Path) -> Path:
        """Write root/private-only SSH AskPass files without secret argv/env values."""
        password_file = workdir / "password"
        askpass = workdir / "askpass"
        launcher = workdir / "connect-guest"

        password_file.write_text(password, encoding="utf-8")
        os.chmod(password_file, 0o600)
        askpass.write_text(f"#!/bin/sh\nexec cat {shlex.quote(str(password_file))}\n", encoding="utf-8")
        os.chmod(askpass, 0o700)

        # host and username come from validated provisioning/libvirt discovery;
        # quote them anyway because this is interpreted by /bin/sh in SSHX.
        ssh = SshxSessionManager._ssh_binary()
        launcher.write_text(
            "#!/bin/sh\n"
            f"export SSH_ASKPASS={shlex.quote(str(askpass))}\n"
            "export SSH_ASKPASS_REQUIRE=force\n"
            "export DISPLAY=bluekvm-sshx\n"
            f"exec {shlex.quote(ssh)} -tt "
            "-o StrictHostKeyChecking=accept-new "
            f"-o {shlex.quote('UserKnownHostsFile=' + str(known_hosts))} "
            "-o GlobalKnownHostsFile=/dev/null "
            "-o LogLevel=ERROR "
            "-o PubkeyAuthentication=no "
            "-o PreferredAuthentications=password,keyboard-interactive "
            "-o PasswordAuthentication=yes "
            "-o KbdInteractiveAuthentication=yes "
            "-o ConnectTimeout=10 "
            f"-- {shlex.quote(username)}@{shlex.quote(host)}\n",
            encoding="utf-8",
        )
        os.chmod(launcher, 0o700)
        return launcher

    @staticmethod
    def _read_url(process: subprocess.Popen[str]) -> str:
        """Read exactly the initial quiet-mode URL without logging the bearer link."""
        if process.stdout is None:
            raise SshxSessionError("SSHX client did not expose its session URL")
        deadline = time.monotonic() + _START_TIMEOUT_SECONDS
        data = b""
        while time.monotonic() < deadline and len(data) < 8192:
            remaining = max(0.0, deadline - time.monotonic())
            readable, _, _ = select.select([process.stdout], [], [], remaining)
            if not readable:
                break
            chunk = os.read(process.stdout.fileno(), 8192 - len(data))
            if not chunk:
                break
            data += chunk
            while b"\n" in data:
                line, data = data.split(b"\n", 1)
                url = SshxSessionManager._safe_sshx_url(line.decode("utf-8", "replace"))
                if url:
                    return url
        raise SshxSessionError("SSHX did not create a hosted session within 15 seconds")

    @staticmethod
    def _discard_output(stream) -> None:
        """Prevent a long-lived child stdout pipe from blocking the SSHX process."""
        try:
            while stream.read(4096):
                pass
        except Exception:
            pass

    @staticmethod
    def _terminate_process(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGINT)
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass

    def _mark_revoked(self, session_id: int) -> None:
        """Best-effort audit state update; cleanup must never leave a process alive."""
        try:
            from ..database import SessionLocal
            from ..models import ConsoleSession

            db = SessionLocal()
            try:
                session = db.get(ConsoleSession, session_id)
                if session and session.revoked_at is None:
                    session.revoked_at = datetime.now(timezone.utc)
                    db.commit()
            finally:
                db.close()
        except Exception:
            log.warning("could not record SSHX session cleanup (session=%s)", session_id)

    def _finalize(self, session_id: int) -> None:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if not session:
            return
        session.expiry_timer.cancel()
        try:
            if session.process.stdout:
                session.process.stdout.close()
        except OSError:
            pass
        shutil.rmtree(session.workdir, ignore_errors=True)
        self._mark_revoked(session_id)
        log.info("SSHX session closed (session=%s)", session_id)

    def _watch(self, session_id: int, process: subprocess.Popen[str]) -> None:
        try:
            process.wait()
        finally:
            self._finalize(session_id)

    def stop(self, session_id: int) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
        if session:
            self._terminate_process(session.process)
            # The watcher normally finalizes. Handle a process which was
            # already reaped by another thread as well.
            self._finalize(session_id)

    def start(
        self,
        *,
        session_id: int,
        vps_name: str,
        host: str,
        username: str,
        password: str,
        expires_at: datetime,
    ) -> str:
        """Launch SSHX and return its hosted URL once, without persisting it."""
        try:
            host = str(ipaddress.IPv4Address(host))
        except ValueError as exc:
            raise SshxSessionError("Guest address must be a valid IPv4 address") from exc
        if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", username):
            raise SshxSessionError("Guest SSH username is invalid")
        now = datetime.now(timezone.utc)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        lifetime = max(1, int((expires_at - now).total_seconds()))

        root = self._runtime_root()
        workdir = Path(tempfile.mkdtemp(prefix="session-", dir=str(root)))
        os.chmod(workdir, 0o700)
        process: subprocess.Popen[str] | None = None
        try:
            # Keep TOFU host keys separate per VPS; changed keys fail closed.
            # The first connection cannot independently authenticate a host key.
            import hashlib
            known_dir = Path(settings.sshx_known_hosts_dir)
            known_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(known_dir, 0o700)
            known_hosts = known_dir / hashlib.sha256(vps_name.encode()).hexdigest()
            launcher = self._write_launcher(
                workdir, host=host, username=username, password=password, known_hosts=known_hosts
            )
            # A separate timeout process caps relay lifetime even if the API
            # process crashes and its in-process expiry timer disappears.
            timeout = shutil.which("timeout")
            if not timeout:
                raise SshxSessionError("GNU timeout is required to enforce SSHX session expiry")
            process = subprocess.Popen(
                [
                    timeout, "--signal=INT", "--kill-after=5s", f"{lifetime}s",
                    self._sshx_binary(), "--quiet", "--name", f"bluekvm-{vps_name}-{session_id}",
                    "--shell", str(launcher),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                start_new_session=True,
                close_fds=True,
                cwd=workdir,
            )
            url = self._read_url(process)
            remaining = (expires_at - datetime.now(timezone.utc)).total_seconds()
            if remaining <= 0:
                raise SshxSessionError("SSHX session expired before it could be opened")
            timer = threading.Timer(remaining, self.stop, args=(session_id,))
            timer.daemon = True
            running = _RunningSession(
                session_id=session_id,
                process=process,
                workdir=workdir,
                expires_at=expires_at,
                expiry_timer=timer,
            )
            with self._lock:
                self._sessions[session_id] = running
            threading.Thread(target=self._discard_output, args=(process.stdout,), daemon=True).start()
            threading.Thread(target=self._watch, args=(session_id, process), daemon=True).start()
            timer.start()
            log.info("SSHX session started (session=%s, vps=%s, expires=%s)", session_id, vps_name, expires_at)
            return url
        except Exception as exc:
            if process is not None:
                self._terminate_process(process)
            shutil.rmtree(workdir, ignore_errors=True)
            if isinstance(exc, SshxSessionError):
                raise
            raise SshxSessionError("Could not start the hosted SSHX terminal") from exc

    def shutdown(self) -> None:
        with self._lock:
            session_ids = list(self._sessions)
        for session_id in session_ids:
            self.stop(session_id)


sshx_sessions = SshxSessionManager()
