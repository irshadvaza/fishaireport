"""
observability.py
-----------------
Lightweight, dependency-free observability: structured (JSON-line) logging to
a rotating file + console, and a timing helper for instrumenting the STT/LLM
calls and other key operations. Every event is also mirrored into SQLite
(utils/db.py's app_events table) so the Admin/Ops dashboard page can query
recent activity without parsing log files.

This is the "roll your own" version appropriate for a small self-hosted app.
For a real production/enterprise deployment, the natural upgrade path is to
ship these same structured log lines to a real observability backend (Azure
Application Insights / OpenTelemetry, Datadog, ELK, etc.) instead of — or in
addition to — the local file; see README.md section "Observability" for how.
"""

import os
import json
import time
import logging
import datetime
from logging.handlers import RotatingFileHandler
from contextlib import contextmanager

LOG_DIR = os.getenv("LOG_DIR", "logs")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
_LOGGER_NAME = "fisheries_app"


class _JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "level": record.levelname,
            "message": record.getMessage(),
        }
        # Anything passed via logger.info(..., extra={"event": {...}}) gets merged in,
        # so log_event() below can attach structured fields (event_type, username, etc).
        if hasattr(record, "event"):
            payload.update(record.event)
        return json.dumps(payload, default=str)


def get_logger() -> logging.Logger:
    """Returns the app's logger, configuring handlers exactly once. Streamlit re-runs
    the whole script on every interaction, so this MUST be idempotent — re-adding
    handlers on every rerun would duplicate every log line forever."""
    logger = logging.getLogger(_LOGGER_NAME)
    if logger.handlers:
        return logger  # already configured earlier in this process

    logger.setLevel(LOG_LEVEL)
    os.makedirs(LOG_DIR, exist_ok=True)

    file_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, "app.log"), maxBytes=5_000_000, backupCount=5
    )
    file_handler.setFormatter(_JsonFormatter())
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(_JsonFormatter())
    logger.addHandler(console_handler)

    logger.propagate = False
    return logger


def log_event(event_type: str, status: str = "ok", username: str = None, role: str = None,
              duration_ms: float = None, **meta):
    """Writes one structured event to the log file/console AND to SQLite (app_events),
    so it's queryable from the Admin/Ops page without grepping log files."""
    logger = get_logger()
    event = {
        "event_type": event_type,
        "status": status,
        "username": username,
        "role": role,
        "duration_ms": round(duration_ms, 1) if duration_ms is not None else None,
        **meta,
    }
    level = logging.WARNING if status != "ok" else logging.INFO
    logger.log(level, event_type, extra={"event": event})

    try:
        from utils.db import log_event_db  # local import avoids a circular import at module load time
        log_event_db(event_type=event_type, status=status, username=username, role=role,
                     duration_ms=duration_ms, meta=meta)
    except Exception:
        # Observability must never be the reason the actual app request fails.
        logger.exception("Failed to persist event to app_events table")


@contextmanager
def timed_operation(event_type: str, username: str = None, role: str = None, **meta):
    """Context manager that logs how long a block took, and whether it succeeded.
    Usage:
        with timed_operation("stt_transcribe", username=staff_user):
            transcript = stt.transcribe(path)
    """
    start = time.perf_counter()
    try:
        yield
    except Exception as e:
        duration_ms = (time.perf_counter() - start) * 1000
        log_event(event_type, status="error", username=username, role=role,
                  duration_ms=duration_ms, error=str(e), **meta)
        raise
    else:
        duration_ms = (time.perf_counter() - start) * 1000
        log_event(event_type, status="ok", username=username, role=role,
                  duration_ms=duration_ms, **meta)
