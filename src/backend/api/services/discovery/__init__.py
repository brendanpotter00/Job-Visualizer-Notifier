"""Discovery value objects (E7).

Since the capture pivot the discovery ENGINE lives in :mod:`api.services.capture`
(record a careers page's network traffic once, one Haiku call to pick + map the jobs
request, then prove the synthesized recipe replays). It replaced the Stagehand
browser-agent tier, which itself had replaced a local-Playwright observer + a
Sonnet-authors-JSON loop — all removed. What remains here is the transport-agnostic
:class:`DiscoveryOutcome` result type, which has outlived all three engines precisely
because it names no transport; it is kept at this path so its importers (the discovery
task, the service, the tests) need no change on the next swap either.

Beside it lives :mod:`.progress` — the 4-step checklist vocabulary the discovery-progress
UI renders. Same reasoning: the four steps are named for what a USER can act on, not for
whichever engine happens to produce them, so they outlive the engine too.
"""

from __future__ import annotations

from .models import DiscoveryOutcome
from .progress import DISCOVERY_STEPS, ProgressLedger, initial_snapshot, read_progress

__all__ = [
    "DISCOVERY_STEPS",
    "DiscoveryOutcome",
    "ProgressLedger",
    "initial_snapshot",
    "read_progress",
]
