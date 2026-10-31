"""Background task worker.

Runs either embedded inside the API process (development / single-node)
or as the standalone ``bluekvm-worker`` systemd service. The polling loop
claims tasks atomically, so running several workers remains safe.
"""
from __future__ import annotations

import asyncio
import logging
import time

from ..database import SessionLocal
from ..models import TaskStatus
from .provisioner import claim_next_task, run_task

log = logging.getLogger("bluekvm.worker")
POLL_INTERVAL = 2.0


def worker_iteration() -> bool:
    """Process at most one task. Returns True when a task was handled."""
    db = SessionLocal()
    try:
        task = claim_next_task(db)
        if not task:
            return False
        log.info("Claimed task %s (%s)", task.id, task.task_type)
        run_task(db, task)
        return True
    finally:
        db.close()


def run_forever() -> None:
    log.info("BLUEKVM worker started (poll every %.1fs)", POLL_INTERVAL)
    while True:
        try:
            worked = worker_iteration()
        except Exception:  # noqa: BLE001 - keep the worker alive
            log.exception("Worker iteration failed")
            worked = False
        time.sleep(0.2 if worked else POLL_INTERVAL)


async def embedded_worker(stop_event: asyncio.Event) -> None:
    log.info("Embedded background worker enabled")
    while not stop_event.is_set():
        try:
            await asyncio.to_thread(worker_iteration)
        except Exception:  # noqa: BLE001
            log.exception("Embedded worker iteration failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL)
        except asyncio.TimeoutError:
            pass


if __name__ == "__main__":
    from ..logging_config import configure_logging

    configure_logging()
    run_forever()
