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

## Hosted SSHX terminals and the recovery VNC bridge

- **Open SSHX** requires normal panel cookie authentication, `vps:read` permission and
  per-VPS ownership/operator authorization. It also requires a running VPS, a discovered
  private guest IP and a stored provisioning credential.
- VM passwords are generated or collected at provisioning time, Fernet-encrypted in the
  `vps.init_password_encrypted` column, and decrypted only in the panel worker while it
  writes a private (`0600`) one-session OpenSSH AskPass file. Passwords never reach the
  browser, URL, process command line, audit record, or application logs; the file is
  deleted when the session ends.
- The panel opens SSH from its own node to the guest private/NAT address and attaches it
  to the official hosted `sshx.io` client. No raw guest SSH or VNC port is public.
- SSHX uses a bearer URL. BLUEKVM returns it once to the authorized new tab and deliberately
  never persists it; it has no share UI and kills the relay after 15 minutes. **Do not
  share the URL** — anyone holding it can access the terminal while the relay is alive.
- The OpenSSH guest connection uses trust-on-first-use (`accept-new`) with a per-VPS
  known-hosts file. A changed key is refused, but the first connection is not independently
  authenticated; use a trusted guest network and verify host keys out of band.
- `console_sessions.kind=sshx` plus `sshx.open` audit events retain user/VPS/expiry lifecycle
  evidence without storing the external URL. Shutdown also terminates all active SSHX relays.
  A forced API crash can leave temporary credential files in the protected runtime directory;
  inspect and clean them before restarting. The external `timeout` bounds relay lifetime.
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
