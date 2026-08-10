"""Browser-agent side — bounded Browserbase Stagehand discovery + replay (E7 pivot).

Stagehand is BOTH the discovery engine and the nightly runtime: one bounded cloud
session (navigate → observe → extract → act, ≤ 3 pages) reads a rendered careers page
that the deleted Sonnet-authors-JSON path could not.

The load-bearing boundary: ``stagehand``/``browserbase`` are imported ONLY by the
child :mod:`._stagehand_main` (spawned as a SUBPROCESS), NEVER by this package's
in-process modules (:mod:`.runner`, :mod:`.discover`, :mod:`.schema`). Importing this
package therefore does NOT make a browser/agent driver resident in the shared
Procrastinate worker — the ``recipe_runner`` import-guard tests prove it. That is
exactly why the session runs out of process.
"""

from __future__ import annotations

from ..discovery.models import DiscoveryOutcome
from .discover import discover
from .runner import run_browser_agent

__all__ = ["discover", "run_browser_agent", "DiscoveryOutcome"]
