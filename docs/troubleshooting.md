# Troubleshooting

## Installer

| Symptom | Likely cause | Fix |
|---|---|---|
| `Port 8080 is already in use` | Another service occupies the port | `ss -ltnp | grep 8080`, stop it or change `BLUEKVM_PORT` |
| `KVM: no VMX/SVM extensions exposed` | Nested virtualization disabled | Enable nested virt on the host, or register an external KVM node |
| `libvirt rejected connection` | Permissions / daemon not running | `systemctl enable --now libvirtd`; ensure the `bluekvm` user is in the `libvirt` group |
| Health check never ready | Migration or dependency failure | `journalctl -u bluekvm-api -n 200` |
| `dpkg was interrupted` | A previous apt run was killed mid-operation | The installer now repairs this automatically; manually: `sudo dpkg --configure -a && sudo apt-get -f install -y` |
| `error: the configured Python interpreter version (3.14) is newer than PyO3's maximum` | Default `python3` is 3.14, which has no prebuilt wheels for native deps | The installer auto-selects `python3.12`/`python3.11`. If absent: `sudo apt install python3.12 python3.12-venv`, delete the partial venv (`rm -rf /opt/bluekvm/backend/.venv`) and re-run |
| `fatal: detected dubious ownership in repository` | `/opt/bluekvm` is owned by a different UID (common in containers) | The installer now whitelists the path via `git config --global --add safe.directory /opt/bluekvm` automatically |
| `"systemd" is not running in this container` | Container image without systemd | The installer detects this and writes `/opt/bluekvm/start-panel.sh` (runs uvicorn with the embedded worker); use it under tmux/supervisord/compose |
| Create VPS wizard: `No KVM-capable online node is registered` | libvirtd is stopped, the venv cannot `import libvirt`, or the panel user lacks libvirt group access | See the dedicated section below |

## "No KVM-capable online node is registered"

The wizard refuses to create a fake VM when no node reports a working libvirt
connection. Work through these checks on the host:

1. **libvirtd must be running**
   ```bash
   # systemd host
   sudo systemctl enable --now libvirtd
   # container / WSL (no systemd)
   sudo service libvirtd start || sudo service virtqemud start
   ls -l /var/run/libvirt/libvirt-sock   # socket must exist
   ```
2. **The panel virtualenv must see the libvirt Python binding.** The binding is
   shipped by the distro (`apt install python3-libvirt`), not PyPI, so the venv is
   created with `--system-site-packages`. Verify:
   ```bash
   /opt/bluekvm/backend/.venv/bin/python -c 'import libvirt; print(libvirt.virGetVersion())'
   ```
   If that fails, recreate the venv:
   ```bash
   sudo rm -rf /opt/bluekvm/backend/.venv
   python3.12 -m venv --system-site-packages /opt/bluekvm/backend/.venv
   /opt/bluekvm/backend/.venv/bin/pip install -r /opt/bluekvm/backend/requirements.txt
   ```
3. **Permissions** — the `bluekvm` account must be in the `libvirt` group
   (the installer runs `usermod -aG libvirt,kvm bluekvm` automatically):
   ```bash
   groups bluekvm
   ```
4. **Re-run the node probe** (or click *Verify connection* under Virtualization Nodes):
   ```bash
   cd /opt/bluekvm/backend && . .venv/bin/activate
   set -a; . /opt/bluekvm/.env; set +a
   python /opt/bluekvm/scripts/node-healthcheck.py
   ```
   It prints `status=online kvm_ready=True` when fixed, or the precise reason
   (missing `/dev/kvm`, socket permission, binding import error) otherwise.
5. Restart the panel after any of the above:
   ```bash
   sudo systemctl restart bluekvm-api bluekvm-worker   # systemd
   # or, in a container:
   pkill -f 'uvicorn app.main:app'; /opt/bluekvm/start-panel.sh &
   ```

## Services

```bash
systemctl status bluekvm-api bluekvm-worker
journalctl -u bluekvm-api -f
tail -f /var/log/bluekvm/bluekvm.log
```

Restart safely:

```bash
sudo systemctl restart bluekvm-worker bluekvm-api
```

## Database

- Verify connectivity: `curl -s localhost:8080/health/ready`.
- Apply migrations manually:
  ```bash
  cd /opt/bluekvm/backend && . .venv/bin/activate && alembic upgrade head
  ```
- Never edit database rows by hand while the worker is running; pause
  `bluekvm-worker` first.

## VPS provisioning

- **`Template is not ready`** — download and verify the image under *OS Templates*.
  A checksum mismatch marks the template `verification_failed` and blocks all VMs.
- **`No KVM-capable online node`** — no registered node reports `/dev/kvm` access.
  Check *System Monitoring → Service health* and run *Verify connection* on the node.
- **Task stuck in `queued`** — the worker is stopped: `systemctl status bluekvm-worker`.
- **Task failed mid-provisioning** — open *Background Tasks* for step-level logs.
  The VM is marked `error`; fix the cause and use *Reinstall OS* or delete and recreate.
- **VM created but won't boot** — open the noVNC console; cloud-init seed failures appear
  on the serial console. Confirm the template image boots standalone.

## Console

- **Close code 4401** — console token expired or was already consumed; reconnect to mint
  a fresh single-use token.
- **4503 / cannot reach VNC** — the QEMU VNC port isn't listening on localhost yet; wait
  for the domain to finish starting, or check `virsh domxml <name>`.
- **Black screen** — the guest may be at a text console or rebooting; send
  Ctrl+Alt+Del from the console toolbar.
- Browsers forbid headers on WebSocket handshakes, hence the short-lived token query
  parameter; tokens live 60 seconds and are bound to one user and one VPS.

## Networking

- **`network 'default' is not active` when starting a VPS** — BLUEKVM retries
  activation before every start, so update/restart the panel and click **Start**
  again. For an immediate repair on a trusted KVM host, inspect and activate it:
  ```bash
  sudo virsh -c qemu:///system net-list --all
  sudo virsh -c qemu:///system net-start default
  sudo virsh -c qemu:///system net-autostart default
  ```
  If `net-start` says `operation not permitted`, the container lacks
  `CAP_NET_ADMIN`; a libvirt NAT bridge cannot run there. Use a privileged KVM
  host or register an external KVM node — do not expose a raw guest SSH/VNC port
  as a workaround.
- Guests with no DHCP lease: confirm the libvirt network is active
  (`virsh net-list --all`) and the bridge name matches the node's network.
- The panel never edits the host's primary network configuration automatically.
  Bridged networking requires an existing host bridge (e.g. `br0`).

## Containers without systemd (Codespaces, Docker, WSL)

The installer now handles these automatically, but the same steps work manually
after a daemon or image reset:

1. **Start libvirt without an init system** — monolithic daemon first, then the
   modular set:
   ```bash
   mkdir -p /run/libvirt
   libvirtd -d 2>/dev/null || for d in virtlogd virtlockd virtnodedevd \
     virtnetworkd virtstoraged virtqemud virtproxyd; do
     command -v "$d" >/dev/null && pgrep -x "$d" >/dev/null || "$d" --daemon
   done
   ls -l /run/libvirt/libvirt-sock
   ```
2. **PTY / storage "Permission denied"** — in a single-tenant test container,
   run QEMU as root via an idempotent `/etc/libvirt/qemu.conf` override
   (`user = "root"` / `group = "root"`, marker `BLUEKVM container override`) and
   relax devpts: `mount -o remount,ptmxmode=0666 /dev/pts`. Never do this on a
   multi-tenant production host.
3. **Default NAT network** — the installer defines and starts it; manually:
   `virsh -c qemu:///system net-define <net.xml> && virsh ... net-start default`.
   Unprivileged containers lacking `CAP_NET_ADMIN` can't start it; the driver
   then falls back to libvirt `type=user` networking.
4. **Storage access** — VM disks/seed ISOs are chgrp'ed to the QEMU group with
   `2750`/`660` modes automatically; verify with
   `ls -l /var/lib/bluekvm/vms/<name>/`.

## Hosted SSHX terminal

| Symptom | Cause | Fix |
| --- | --- | --- |
| `409 VPS is not running` | VM stopped or still provisioning | Start the VPS and wait for `running` |
| `409 Guest IP address is not available yet` | No DHCP lease and no qemu-guest-agent report | Wait a minute and retry; check `virsh net-dhcp-leases default`; install `qemu-guest-agent` in the image for faster discovery |
| `503 SSHX client is not installed` | Installer predates SSHX support or outbound installation failed | Re-run the latest installer update; it installs the official `/usr/local/bin/sshx` client |
| SSHX page says guest login/connection failed | Guest sshd is not ready, port 22 is blocked, or its credential changed after provisioning | Wait for cloud-init; log in as `ubuntu` (not `root`) using the creation password. Use the localhost-only recovery bridge to repair an unreachable guest. |
| SSHX link no longer works | Its local relay exited or the 15-minute owner-issued session TTL ended | Return to the panel and open a fresh SSHX session. Do not share the hosted URL. |

## Resetting administrator access

```bash
cd /opt/bluekvm/backend && . .venv/bin/activate
python - <<'PY'
from app.database import SessionLocal
from app.models import User
from app.security import hash_password
db = SessionLocal()
u = db.query(User).filter(User.username == 'admin').one()
u.password_hash = hash_password('New!StrongPass123')
db.commit(); print('password reset')
PY
```

All other sessions are revoked the next time the password is changed through the UI.
