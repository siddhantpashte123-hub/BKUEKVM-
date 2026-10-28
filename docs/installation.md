# Installation guide

## 1. Prerequisites

- A fresh Ubuntu 22.04/24.04 or Debian 12 host (RHEL-family package names differ and
  are handled on a best-effort basis).
- Root or passwordless sudo.
- At least 2 GB RAM and 20 GB free disk for the panel; add capacity for guest VMs.
- For local VMs: accessible `/dev/kvm`. Inside a VPS, ask the provider for **nested
  virtualization**; otherwise register an external KVM node after installation.

## 2. Run the installer

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/siddhantpashte123-hub/BKUEKVM-/main/installer/install.sh)
```

The installer menu offers:

1. **INSTALL PANNEL** — full guided installation.
2. **CANCEL** — exits without changing anything.
3. **UNINSTALL PANNEL** — safe removal; VMs and data are preserved unless explicitly requested.
4. **PANNEL STATUS** — real checks for installation, services, port, web, database and KVM.

### What installation does

1. Verifies root, distribution, architecture, RAM/disk, KVM and port 8080.
2. Repairs any interrupted package state (`dpkg --configure -a`) automatically.
3. Installs QEMU/KVM, libvirt, PostgreSQL, nginx, Python, Node.js and image tooling.
4. Deploys the application under `/opt/bluekvm` and creates a `bluekvm` service account.
5. Selects a supported Python interpreter (3.10–3.13; 3.12 preferred) so all native
   dependencies install from prebuilt wheels — Python 3.14 is deliberately avoided
   because wheel coverage is incomplete and source builds require a Rust toolchain.
6. Builds the React frontend and the Python virtual environment.
7. Creates the PostgreSQL database/role (or falls back to SQLite with a warning).
8. Generates a 256-bit app secret and a Fernet credential key.
9. Interactively prompts for the administrator **email and password** (TTY installs):
   the password is hidden, confirmed, and must be 12+ characters with three character
   classes. Leaving it blank generates a random one shown **once**.
10. Writes `/opt/bluekvm/.env` with `0600` permissions.
11. Runs Alembic migrations (`alembic upgrade head`).
12. On systemd hosts, installs and starts `bluekvm-api` and `bluekvm-worker`; in
    containers/WSL it writes `/opt/bluekvm/start-panel.sh` and launches the panel
    with the embedded worker instead.
13. Polls `http://127.0.0.1:8080/health/ready` until healthy and prints the result.

### Administrator credentials

Interactive install (recommended) — the installer asks:

```
Administrator account setup
Administrator email [admin@localhost]:
Administrator password (min 12 chars, blank = generate one): ********
Confirm password: ********
```

Non-interactive/CI pre-seeding skips the prompts entirely:

```bash
sudo BLUEKVM_ADMIN_USERNAME=admin \
     BLUEKVM_ADMIN_EMAIL=ops@example.com \
     BLUEKVM_ADMIN_PASSWORD='Strong!Passw0rd-123' \
  bash install.sh
```

Piped installs (`curl | bash`) without a TTY and without environment variables receive
a random password printed once in the final installation summary.

## 3. First login

Open `http://<server-ip>:8080`, sign in, then:

1. Download and verify an OS template under **OS Templates**.
2. Confirm the local node is online under **Virtualization Nodes**, or register an
   external KVM node (`qemu+tls://node/system` with an encrypted credential).
3. Use **Create VPS** to provision your first machine.

## 4. HTTPS (recommended)

The panel listens on plain HTTP on port 8080 by default. Terminate TLS with nginx:

```bash
sudo cp /opt/bluekvm/deployment/nginx-bluekvm.conf.example /etc/nginx/sites-available/bluekvm
# Edit server_name and paths, then:
sudo ln -s /etc/nginx/sites-available/bluekvm /etc/nginx/sites-enabled/
sudo certbot --nginx -d panel.example.com
```

Set `BLUEKVM_COOKIE_SECURE=1` (default in production) and set `BLUEKVM_PUBLIC_URL` to
the HTTPS URL. The nginx config includes the WebSocket upgrade headers the noVNC
console requires.

## 5. Container deployment

A multi-stage `Dockerfile` and `compose.yaml` are provided. Local KVM from a container
needs `/dev/kvm`, the libvirt socket and the `libvirt` group — see the comments in
`compose.yaml`. Most hosted VPS environments should instead use the external-node model.

## 6. Post-install verification

```bash
sudo bash /opt/bluekvm/installer/status.sh
curl -s http://127.0.0.1:8080/health/ready | python3 -m json.tool
journalctl -u bluekvm-api -u bluekvm-worker -f
```
