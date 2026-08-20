"""Discovery value objects (E7).

Since the capture pivot the discovery ENGINE lives in :mod:`api.services.capture`
(record a careers page's network traffic once, one Haiku call to pick + map the jobs
request, then prove the synthesized recipe replays). It replaced the Stagehand
browser-agent tier, which itself had replaced a local-Playwright observer + a
Sonnet-authors-JSON loop — all removed. What remains here is the transport-agnostic
:class:`DiscoveryOutcome` result type, which has outlived all three engines precisely
because it names no transport; it is kept at this path so its importers (the discovery
task, the service, the tests) need no change on the next swap either.
"""

from __future__ import annotations

from .models import DiscoveryOutcome

__all__ = ["DiscoveryOutcome"]
