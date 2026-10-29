# Architecture

## Components

### Backend (`backend/`)

FastAPI application split into explicit layers:

| Module | Responsibility |
|---|---|
| `app/main.py` | App factory, lifespan, router wiring, SPA hosting, exception mapping |
| `app/config.py` | Environment-driven settings (`BLUEKVM_*`, `DATABASE_URL`) |
| `app/models.py` | 16 SQLAlchemy models — the authoritative metadata store |
| `app/api/` | Thin HTTP routers for auth, VPS, nodes, templates, networks, storage, backups, users, logs, monitoring, settings, dashboard |
| `app/deps.py` | Session authentication, CSRF enforcement, permission and ownership checks |
| `app/virtualization/` | Capability detection, driver contract, real libvirt driver, node manager |
| `app/services/` | Provisioning state machine, worker loop, backups, templates, metrics, audit |
| `app/console/` | Authenticated WebSocket ↔ localhost VNC bridge |
| `app/alembic/` | Database migrations |

### Virtualization driver

`HypervisorDriver` defines the restricted contract (`define_vm`, `start`, `shutdown`,
`restart`, `delete`, snapshots, pools, networks, stats). `LibvirtDriver` implements it
against the libvirt Python API:

1. `qemu-img create` builds a backing qcow2 from the verified template, then resizes it.
2. cloud-init renders `user-data`, `meta-data` and optional `network-config`, packaged
   into a NoCloud seed ISO (`cloud-localds`, `genisoimage` or `xorriso`).
3. A libvirt domain XML defines virtio disk/network, host-model CPU and VNC graphics
   bound to `127.0.0.1` with an auto port.
4. Lifecycle and verification use libvirt state codes mapped to panel statuses.

When KVM is unavailable, `detect_capabilities()` reports the precise reason and
provisioning raises `KVMUnavailableError` → HTTP 409. No simulated VM is ever created.
The in-memory fake driver exists solely under `backend/tests/`.

### Provisioning and the worker

Every long operation is a durable `tasks` row (`queued → running → succeeded/failed`)
with JSON steps and append-only logs. The worker claims the oldest queued task
atomically (`UPDATE ... WHERE status='queued'`), so restarts and duplicate submissions
never double-provision. It runs embedded in the API during development and as the
standalone `bluekvm-worker` service in production.

The hypervisor remains the source of truth for power state; `DriverManager.sync_vps_state`
reconciles database statuses against libvirt on every lifecycle transition.

### Hosted SSHX terminals

A panel-authenticated user with access to a running VPS requests
`POST /api/vps/{id}/sshx-session`. The server discovers the guest IP and launches
an official SSHX client with a temporary OpenSSH launcher and private AskPass
credential. The URL is returned once to a new tab and is not stored by the panel.
SSHX links are bearer links: anyone possessing the URL can use it while active.
The relay is stopped on expiry (15 minutes by default) or normal panel shutdown.
The hosted service and a reachable guest SSH daemon are required.

A localhost-only VNC bridge remains as an unlinked recovery endpoint.

### Frontend (`frontend/`)

React 18 + TypeScript + Vite + Tailwind, with:

- A token-free fetch wrapper relying on same-origin cookies plus CSRF headers.
- Polling hooks for live metrics and task progress, with explicit loading/empty/error
  and disconnected states on every page.
- A strict black/electric-blue design token system in `tailwind.config.js`.
- The SSHX hand-off page obtains one short-lived hosted URL, then navigates the new tab
  to `sshx.io`; no terminal emulator or guest password is bundled into the frontend.

### Data model highlights

- `vps` joins nodes, templates, owners and networks; `public_id` (UUID) is the external key.
- `tasks`/`backups`/`audit_logs`/`login_history` give full operational history.
- `ip_allocations` enforces unique addresses per network.
- `nodes` store Fernet-encrypted credentials and live capability snapshots.

## Request lifecycle (VPS creation)

```
POST /api/vps ── auth + permission + Pydantic validation
   ├─ idempotency key lookup (duplicate submission returns the existing VPS)
   ├─ template readiness + node placement (real capacity check)
   └─ INSERT vps(pending) + INSERT task(queued)
worker claims task
   ├─ reserve resources / placement
   ├─ qemu-img disk + cloud-init seed + libvirt defineXML
   ├─ domain.start()
   ├─ sync_vps_state() verifies "running" from libvirt
   └─ task succeeded / vps running  (or explicit error with step logs)
```
