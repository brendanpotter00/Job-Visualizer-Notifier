"""Discovery result value object (E7 Phase 3b). Dependency-free."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DiscoveryOutcome:
    """The result of one ``discover(url)`` run.

    ``ok`` True carries a validated, replay-proven ``script`` plus the ``transport``
    and ``oracle_kind`` columns to store. ``ok`` False carries a ``refuse_reason``
    (the loud REFUSE: validation error / gate FAILED / capability-not-in-vocabulary /
    missing key). ``attempts`` counts the authoring attempts spent (0 when the LLM
    key was unset — no attempt burned). ``cost_note`` is a human string for the
    audit row, never load-bearing.

    ``progress`` is the TERMINAL 4-step checklist blob
    (:mod:`api.services.discovery.progress`) — every step's specific result plus either
    a job preview or the named step that failed. It rides the outcome rather than being
    written by the engine because the row's state flip (``discovering`` → tracked /
    refused) and its final checklist must land in the SAME statement: a checklist
    written separately, after the flip, is a straggler that can resurrect "still
    working" on a board we already refused.
    """

    ok: bool
    script: dict[str, Any] | None = None
    transport: str | None = None
    oracle_kind: str | None = None
    refuse_reason: str | None = None
    attempts: int = 0
    cost_note: str | None = None
    progress: dict[str, Any] | None = None
