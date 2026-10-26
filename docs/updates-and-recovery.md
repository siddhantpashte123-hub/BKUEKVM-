# Updates and recovery

## Update procedure

The update script (`scripts/update.sh`, copied to `/opt/bluekvm/scripts/`) performs a
safe, staged upgrade:

1. **Record current version** from the running API.
2. **Back up configuration** — copy `.env` and dump PostgreSQL metadata
   (`pg_dump bluekvm`) into `/var/backups/bluekvm/<timestamp>/`.
3. **Fetch the approved release** — `git pull` on the deployment clone (or a verified
   release tarball; checksum verification is recommended).
4. **Install dependencies** — recreate/refresh the Python virtual environment and
   rebuild the frontend.
5. **Apply migrations** — `alembic upgrade head` inside a transaction where the
   database supports it.
6. **Restart services** — `bluekvm-worker` then `bluekvm-api`.
7. **Verify health** — poll `/health/ready`; fail loudly if the database or API is down.

VM disks, templates and backups under `/var/lib/bluekvm` are never touched by updates.

### Run an update

```bash
sudo bash /opt/bluekvm/scripts/update.sh
```

## Backup policy

| Asset | Location | Treatment |
|---|---|---|
| Application config/secrets | `/opt/bluekvm/.env` | Copied before every update |
| Database metadata | PostgreSQL `bluekvm` (or SQLite file) | `pg_dump` / file copy |
| VM disks | `/var/lib/bluekvm/vms` | Independent qcow2 backups via the Backups page |
| OS images | `/var/lib/bluekvm/templates` | Re-downloadable; checksum-verified |
| Guest backups | `/var/lib/bluekvm/backups` | Retained; configurable retention (default 7) |

## Recovery

### Failed application update

1. The health check failing leaves the previous release intact in git:
   ```bash
   cd /opt/bluekvm && git log --oneline -5
   sudo git -C /opt/bluekvm checkout <previous-tag>
   cd backend && . .venv/bin/activate && alembic downgrade -1   # only if the migration supports rollback
   sudo systemctl restart bluekvm-worker bluekvm-api
   ```
2. Restore the database dump if a migration cannot be rolled back:
   ```bash
   sudo systemctl stop bluekvm-api bluekvm-worker
   sudo -u postgres psql -c "DROP DATABASE bluekvm;" && sudo -u postgres createdb -O bluekvm bluekvm
   sudo -u postgres psql bluekvm < /var/backups/bluekvm/<ts>/bluekvm.sql
   sudo systemctl start bluekvm-worker bluekvm-api
   ```
3. Re-run the installer status option to confirm every check is green.

### Lost panel host, intact VM storage

The panel treats libvirt as the source of truth for running domains. On a replacement
host:

1. Reinstall the panel and restore the database dump.
2. Re-register the storage location (or mount the old `/var/lib/bluekvm`).
3. Re-register the KVM node and run *Verify connection*; storage pools and networks are
   re-synced from libvirt automatically.

### Destructive migration policy

Migrations are additive where possible. Any migration that drops data must ship with:

- an explicit downgrade path or a data-preserving migration script,
- a pre-migration `pg_dump` step in the update script,
- a note in the release description.

The installer never runs destructive migrations automatically without a reachable
backup directory.
