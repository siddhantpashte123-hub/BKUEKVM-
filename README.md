# BLUEKVM PANNEL

**Production-ready, self-hosted VPS hosting and virtualization management platform.**

BLUEKVM PANNEL creates and manages **real KVM/QEMU virtual machines** through libvirt,
with a pure **Black + Electric Blue** web dashboard, an interactive terminal installer,
background provisioning, role-based access control and an authenticated browser SSH terminal.

---

## One-command installation

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/siddhantpashte123-hub/BKUEKVM-/main/installer/install.sh)
```

The installer displays an interactive menu:

```
╔══════════════════════════════════════════════╗
║              BLUEKVM PANNEL                  ║
║                 INSTALLER                    ║
╠══════════════════════════════════════════════╣
║  1. INSTALL PANNEL                           ║
║  2. CANCEL                                   ║
║  3. UNINSTALL PANNEL                         ║
║  4. PANNEL STATUS                            ║
╚══════════════════════════════════════════════╝
```

> **Production security note:** instead of piping remote code into bash, download a
> [versioned release](https://github.com/siddhantpashte123-hub/BKUEKVM-/releases),
> verify its checksum, then run the verified `install.sh` locally.

After installation open `http://<server-ip>:8080` and sign in with the administrator
credentials printed by the installer (no default password is ever shipped). On an
interactive terminal the installer prompts for the administrator email and password
(hidden input + confirmation; blank generates a random one); piped/CI installs can
pre-seed `BLUEKVM_ADMIN_EMAIL` and `BLUEKVM_ADMIN_PASSWORD`. The installer requires a
supported Python (3.10–3.13, 3.12 preferred) and selects it automatically — Python 3.14
is avoided because native dependency wheels are not yet published for it.

### Requirements

| Requirement | Minimum | Recommended |
|---|---|---|
| OS | Ubuntu 22.04 / Debian 12 | Ubuntu 24.04 |
| Architecture | x86_64 / arm64 | x86_64 |
| RAM | 2 GB (panel only) | 4 GB+ |
| Disk | 20 GB free | 50 GB+ SSD |
| KVM | `/dev/kvm` accessible for local VMs | nested virt enabled on hosted VPS |

Without KVM (typical inside an unprivileged VPS), the panel installs and runs, honestly
reports virtualization as unavailable, and can manage **external KVM nodes** registered
through *Virtualization Nodes*. It never simulates a successful VM.

---

## What works

- **Real KVM lifecycle** — define, start, graceful shutdown, force stop, restart, delete,
  reinstall, via libvirt with qcow2 disks and cloud-init NoCloud seed ISOs.
- **6-step Create VPS wizard** — OS, details, resources, networking, node placement, review;
  idempotent submissions and server-side capacity validation.
- **Durable background worker** — queued tasks with timestamped steps, logs and progress;
  safe restarts and duplicate-claim protection.
- **Hosted SSHX terminal** — Open SSHX creates an authorized, time-limited
  `sshx.io` bearer link and opens it in a new tab. The panel does not persist the link;
  anyone with it can access the session, so do not share it. No raw guest SSH port is exposed.
- **RBAC** — Super Administrator, Administrator, VPS Manager, Read-Only Viewer; per-VPS
  ownership scoping; session revocation and login history.
- **OS templates** — curated Ubuntu/Debian cloud images with streamed download and
  SHA-256 verification before provisioning is allowed.
- **Backups** — verified full qcow2 backups (distinct from libvirt snapshots), restore
  and retention.
- **Monitoring** — real psutil host metrics, service health, node KVM readiness, audit trail.
- **Installer** — install / cancel / safe uninstall (preserves VMs by default) / live status.

## Architecture

```
Browser (React + Vite + Tailwind)
   │  cookie auth + CSRF token, SSHX hand-off
   ▼
FastAPI (Uvicorn :8080)  ── systemd: bluekvm-api
   ├── REST routers (/api/...)
   ├── SSHX session launcher + recovery VNC proxy (/ws/console)
   └── service layer (audit, metrics, templates, backups)
            │
   bluekvm-worker (systemd)  ── durable task queue in PostgreSQL
            │
   DriverManager ── LibvirtDriver (qemu:///system or qemu+tls://node)
            │
   libvirt / QEMU-KVM, qcow2 storage, cloud-init, VNC (127.0.0.1)
```

See [docs/architecture.md](docs/architecture.md) for details.

## Repository layout

```
├── backend/            FastAPI app, libvirt driver, worker, Alembic, pytest
├── frontend/           React + TypeScript + Vite + Tailwind, SSHX hand-off
├── installer/          install.sh (menu), uninstall.sh, status.sh, lib.sh
├── deployment/         systemd units, nginx TLS example
├── docs/               installation, troubleshooting, security, updates
├── scripts/            dev launcher, checksum helper, update script
├── tests/              installer smoke tests
├── Dockerfile          container image (multi-stage)
├── compose.yaml        PostgreSQL + panel example
└── .env.example        documented configuration template
```

## Documentation

- [Installation](docs/installation.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Security model](docs/security.md)
- [Updates and recovery](docs/updates-and-recovery.md)
- [Architecture](docs/architecture.md)

## Development

```bash
./scripts/run-dev.sh                 # API on :8080, Vite on :5173
cd backend && pytest                 # 38 backend tests (SQLite + test driver)
cd frontend && npm run build         # type-check and production build
./tests/installer_test.sh            # installer guard-rail tests
```

The test suite uses a documented in-memory **test driver double** for provisioning
workflows. Production code paths only ever use the real `LibvirtDriver`; when KVM is
absent, operations fail with an actionable error instead of faking success.

## License

MIT — see [LICENSE](LICENSE).
