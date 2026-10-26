"""Structured logging configuration.

Logs to stdout (journald captures it under systemd) and, when writable,
to a rotating file under the configured log directory. Secrets are never
logged by application code; a redaction filter strips common secret fields
as a defence-in-depth measure.
"""
from __future__ import annotations

import logging
import logging.handlers
import re
from pathlib import Path

from .config import settings

SECRET_PATTERN = re.compile(
    r"(?i)(password|passwd|secret|token|api[_-]?key|authorization|cookie)([=:]\s*)([^\s&\"']+)"
)


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = SECRET_PATTERN.sub(r"\1\2***REDACTED***", record.msg)
        return True


def configure_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(level)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    redaction = RedactionFilter()

    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    stream.addFilter(redaction)
    root.addHandler(stream)

    try:
        log_path = Path(settings.log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_path / "bluekvm.log", maxBytes=10 * 1024 * 1024, backupCount=5
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(redaction)
        root.addHandler(file_handler)
    except (PermissionError, OSError):
        # Container / unprivileged dev environments: stdout only
        pass

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
