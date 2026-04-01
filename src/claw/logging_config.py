"""Structured logging for CLAW — JSON formatter + context propagation.

Provides a JSON log formatter that enriches standard log records with
structured fields (task_id, agent_id, session_id, cycle_level, model,
elapsed_ms, tokens, cost_usd).  Context fields are injected via a
thread-local store so every logger in the process gets them automatically.

Usage:
    from claw.logging_config import setup_logging, set_context, clear_context

    setup_logging(verbose=True, json_mode=True, log_file="cam_events.jsonl")

    set_context(task_id="t-123", agent_id="claude", session_id="s-abc")
    logger.info("Task dispatched")  # includes task_id, agent_id, session_id
    clear_context()
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Thread-local context store
# ---------------------------------------------------------------------------

_local = threading.local()

# Fields that can be set via set_context() and injected into every log record.
_CONTEXT_FIELDS = (
    "task_id",
    "agent_id",
    "session_id",
    "cycle_level",
    "model",
    "project_id",
)

# Extra numeric fields that individual log calls can attach via the `extra` dict.
_METRIC_FIELDS = (
    "elapsed_ms",
    "tokens",
    "cost_usd",
)


def set_context(**kwargs: Any) -> None:
    """Set context fields that will be injected into all subsequent log records.

    Only fields in _CONTEXT_FIELDS are accepted; unknown keys are ignored.
    Call clear_context() when the scope ends (e.g. after a task completes).
    """
    for key in _CONTEXT_FIELDS:
        if key in kwargs:
            setattr(_local, key, kwargs[key])


def clear_context() -> None:
    """Remove all context fields from the thread-local store."""
    for key in _CONTEXT_FIELDS:
        if hasattr(_local, key):
            delattr(_local, key)


def get_context() -> dict[str, Any]:
    """Return a snapshot of the current context (for testing/debugging)."""
    return {k: getattr(_local, k) for k in _CONTEXT_FIELDS if hasattr(_local, k)}


# ---------------------------------------------------------------------------
# Context filter — attaches thread-local fields to log records
# ---------------------------------------------------------------------------

class ClawContextFilter(logging.Filter):
    """Injects thread-local context fields into every LogRecord.

    Attach this filter to a handler or the root logger so that formatters
    can access context fields like ``record.task_id``.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        for key in _CONTEXT_FIELDS:
            if not hasattr(record, key):
                setattr(record, key, getattr(_local, key, None))
        return True


# ---------------------------------------------------------------------------
# JSON formatter
# ---------------------------------------------------------------------------

class ClawJsonFormatter(logging.Formatter):
    """Emit one JSON object per log line with structured fields.

    Output shape::

        {
            "ts": "2026-04-01T12:34:56.789Z",
            "level": "INFO",
            "logger": "claw.cycle",
            "msg": "Task dispatched",
            "task_id": "t-123",
            "agent_id": "claude",
            ...
        }
    """

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        # Context fields (from ClawContextFilter or set directly)
        for key in _CONTEXT_FIELDS:
            val = getattr(record, key, None)
            if val is not None:
                entry[key] = val

        # Metric fields (from extra={} on individual log calls)
        for key in _METRIC_FIELDS:
            val = getattr(record, key, None)
            if val is not None:
                entry[key] = val

        # Exception info
        if record.exc_info and record.exc_info[1] is not None:
            entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(entry, default=str)


# ---------------------------------------------------------------------------
# Setup function — replaces _setup_logging() in cli
# ---------------------------------------------------------------------------

def setup_logging(
    verbose: bool = False,
    json_mode: bool = False,
    log_file: Optional[str] = None,
) -> None:
    """Configure the root logger for CLAW.

    Args:
        verbose: If True, set level to DEBUG; otherwise INFO.
        json_mode: If True, use ClawJsonFormatter; otherwise plain text.
        log_file: If provided, add a FileHandler writing JSON lines to this path.
    """
    level = logging.DEBUG if verbose else logging.INFO
    root = logging.getLogger()

    # Clear existing handlers and filters to avoid duplicates on repeated calls
    root.handlers.clear()
    root.filters = [f for f in root.filters if not isinstance(f, ClawContextFilter)]
    root.setLevel(level)

    # Context filter — add to each handler so it runs when child-logger
    # records bubble up via callHandlers() → handler.handle()
    context_filter = ClawContextFilter()

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.addFilter(context_filter)

    if json_mode:
        console_handler.setFormatter(ClawJsonFormatter())
    else:
        console_handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
                datefmt="%H:%M:%S",
            )
        )

    root.addHandler(console_handler)

    # Optional file handler (always JSON for machine parsing)
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)  # capture everything in file
        file_handler.addFilter(ClawContextFilter())
        file_handler.setFormatter(ClawJsonFormatter())
        root.addHandler(file_handler)
