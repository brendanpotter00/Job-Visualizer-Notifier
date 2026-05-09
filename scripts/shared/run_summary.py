"""Per-scraper-run summary log.

Every scraper run emits exactly ONE `event="scraper_run_complete"` log line
at exit. Wired in Units 3, 4, 5, 6. Unit 1 only ships the model and emit().
"""

from __future__ import annotations

import logging
from typing import Literal, Optional

from pydantic import BaseModel

ExitReason = Literal["success", "error", "timeout", "cancelled"]


class RunSummary(BaseModel):
    """Stable schema for the `scraper_run_complete` log event."""

    company: str
    run_id: str
    mode: Literal["incremental", "full", "json"]
    exit_reason: ExitReason
    jobs_seen: Optional[int] = None
    new_jobs: Optional[int] = None
    updated_jobs: Optional[int] = None
    closed_jobs: Optional[int] = None
    details_fetched: Optional[int] = None
    error_count: int = 0
    duration_ms: int


def emit(logger: logging.Logger, summary: RunSummary) -> None:
    """Log the run summary as a single INFO record.

    Fields are flattened onto the JSON envelope via `extra={...}` so each
    becomes a top-level key in the structured log line.
    """
    logger.info(
        "scraper run complete",
        extra={"event": "scraper_run_complete", **summary.model_dump()},
    )
