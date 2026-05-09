"""Single source of truth for structured (JSON) logging across backend + scripts.

Emits one JSON object per record. Used by:
- Scrapers (every run emits a `scraper_run_complete` event via run_summary.emit)
- Backend access middleware (Unit 8) — `http_request` event
- Backend critical-path logs (Unit 9) — `scraper_subprocess_complete`,
  `auto_scraper_cycle`, auth failures

Stdlib only — no external dep. Calling `setup_structured_logging` is idempotent
per-process; subsequent calls update the level but do not stack handlers.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

_RESERVED_RECORD_ATTRS: frozenset[str] = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "asctime", "taskName",
})


class JsonFormatter(logging.Formatter):
    """Format each log record as a single-line JSON object.

    Schema (stable; documented in CLAUDE.md after Unit 10):
        ts:      ISO 8601 UTC with microseconds, e.g. "2026-05-07T12:34:56.789012Z"
        level:   "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL"
        service: caller-supplied service name
        logger:  the `logging.Logger.name`
        msg:     the formatted log message
        ...:     any keyword passed via `extra={...}` is merged in flat
    """

    def __init__(self, service: str) -> None:
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc)
        envelope: dict[str, Any] = {
            "ts": ts.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "level": record.levelname,
            "service": self._service,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        for key, value in record.__dict__.items():
            if key in _RESERVED_RECORD_ATTRS or key.startswith("_"):
                continue
            if key in envelope:
                continue
            envelope[key] = value

        if record.exc_info:
            envelope["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            envelope["stack_info"] = self.formatStack(record.stack_info)

        return json.dumps(envelope, default=str, ensure_ascii=False)


def setup_structured_logging(
    service: str, level: str = "INFO"
) -> logging.Logger:
    """Configure root logger to emit JSON to stdout. Returns the root logger.

    Idempotent: safe to call multiple times in the same process. The JSON
    handler is installed exactly once (identified by an attribute marker);
    repeat calls only update the level.
    """
    root = logging.getLogger()
    root.setLevel(level.upper())

    marker = "_structured_handler_installed"
    for handler in root.handlers:
        if getattr(handler, marker, False):
            handler.setLevel(level.upper())
            return root

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter(service=service))
    handler.setLevel(level.upper())
    setattr(handler, marker, True)
    root.addHandler(handler)
    return root
