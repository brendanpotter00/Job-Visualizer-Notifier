"""Discovery value objects (E7).

Since the Stagehand pivot the discovery ENGINE lives in
:mod:`api.services.browser_agent` (one bounded Browserbase Stagehand session
replaces the old local-Playwright ``observer`` + Sonnet-authors-JSON ``author`` +
``discover`` loop, all removed). What remains here is the transport-agnostic
:class:`DiscoveryOutcome` result type — kept in place so its many importers (the
discovery task, the service, the tests) need no path change.
"""

from __future__ import annotations

from .models import DiscoveryOutcome

__all__ = ["DiscoveryOutcome"]
