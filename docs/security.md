# Security model

## Authentication and sessions

- Passwords are hashed with **bcrypt** via passlib. No default password exists; the
  installer generates a random one unless `BLUEKVM_ADMIN_PASSWORD` is supplied.
- Login issues an opaque, high-entropy session token. Only its **SHA-256 hash** is
  stored in `api_sessions`; a database dump cannot replay sessions.
- Sessions carry an expiry (`BLUEKVM_SESSION_TTL_MINUTES`) and can be revoked
  individually or per user. Every login attempt is recorded in `login_history`.
- Login is protected by a sliding-window **rate limiter** keyed on client IP
  (default 8 attempts/minute → HTTP 429).

## CSRF

The session cookie is `HttpOnly`, `SameSite=Lax`, and `Secure` whenever HTTPS is
enabled. State-changing requests additionally require a double-submit CSRF token:
the non-HttpOnly `bluekvm_csrf` cookie echoed in the `X-CSRF-Token` header. The check
is enforced server-side in `app/deps.py` and disabled only in local development.

## Authorization

Four seeded roles (`app/bootstrap.py`):

| Role | Scope |
|---|---|
| Super Administrator | Wildcard — all permissions |
| Administrator | Full management, users and settings |
| VPS Manager | VPS lifecycle, templates (read), backups, monitoring |
| Read-Only Viewer | Read access, no audit log access, no mutations |

Every API route declares a required permission through `require_permission(...)`.
Scoped users only see VPS rows whose `owner_id` matches their account, and console
sessions re-check VPS ownership before minting a token.

## Virtualization isolation

- The web process never executes shell commands with user input. All hypervisor
  operations go through the `HypervisorDriver` service layer; libvirt APIs and
  fixed-argument subprocess calls (`qemu-img`, ISO builders) are the only entry points.
- Hostnames and domain names are validated against allow-lists and XML-escaped before
  reaching libvirt, preventing command/XML injection.
- VM disks live only under the configured storage tree; deletion refuses paths outside
  that tree.
- libvirt management endpoints must never be publicly exposed. Remote nodes use
  `qemu+tls://` with secrets stored **Fernet-encrypted** in the database; the plaintext
  is never returned to the browser or written to logs. A redaction filter strips secret
  fields from log records.

## Browser terminals (SSH) and the recovery VNC bridge

- Browsers cannot send headers on WebSocket handshakes, so terminal access uses a
  single-use, 60-second token bound to one user and one VPS (`console_sessions.kind`
  distinguishes `ssh` from `vnc`).
- VM passwords are generated or collected at provisioning time, Fernet-encrypted in the
  `vps.init_password_encrypted` column, and decrypted only inside the SSH WebSocket
  worker. They are never returned by any API (the create response carries a generated
  password exactly once) and never reach browser JavaScript.
- The SSH connection originates from the panel node toward the guest's private/NAT
  address; no raw SSH or VNC port is exposed publicly. Guest host keys are not pinned
  because guests live on the panel-owned private network and no key is persisted.
- The VNC bridge stays bound to `127.0.0.1` QEMU ports only; the proxy refuses non-local
  targets and closes with explicit policy codes (4401 unauthenticated,
  4500–4503 hypervisor/connection failures).

## Data handling

- No secrets, `.env` files, keys or credentials are committed to the repository
  (see `.gitignore` and `.env.example`).
- Audit logs record every administrative action with IP address and sanitized details;
  passwords, tokens and credentials are redacted.
- Destructive operations require typed confirmation server-side (VPS deletion must
  echo the VPS name; uninstall requires typing `UNINSTALL`, VM data removal `DELETE-VMS`).

## Deployment hardening checklist

- [ ] TLS via nginx (see `deployment/nginx-bluekvm.conf.example`) and HSTS.
- [ ] `BLUEKVM_COOKIE_SECURE=1`, strong random `BLUEKVM_SECRET_KEY` and Fernet key.
- [ ] Firewall: expose only 80/443 (and 8080 if intentionally direct); block libvirt.
- [ ] Run services as the unprivileged `bluekvm` account in the `libvirt` group.
- [ ] Keep PostgreSQL on localhost with a generated role password.
- [ ] Pin template SHA-256 checksums before production use.
