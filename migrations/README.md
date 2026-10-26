# migrations/

Database migrations are maintained with Alembic inside `backend/alembic/` (kept next to
the application so `alembic.ini` and the virtual environment align):

```bash
cd backend && . .venv/bin/activate
alembic upgrade head      # apply all migrations
alembic revision -m "..." # author a new migration
alembic history           # inspect the revision chain
```

This directory is retained in the repository root as the canonical pointer for operators
looking for database migration tooling; see `docs/updates-and-recovery.md` for the
safe-update and rollback policy.
