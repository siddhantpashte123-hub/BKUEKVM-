"""Shared test helpers (not collected as a test module)."""
from __future__ import annotations


def drain_tasks(max_iterations: int = 50) -> int:
    """Process every queued task oldest-first until the queue is empty."""
    from app.services.worker import worker_iteration

    processed = 0
    for _ in range(max_iterations):
        if not worker_iteration():
            break
        processed += 1
    return processed
