"""DISCOVERY SIDE — the one-time, at-add-time agent (E7 Phase 3b).

This package is the ONLY place in the backend that touches the LLM
(``author`` → Anthropic Sonnet) or the browser (``observer`` → local Playwright,
run OUT OF PROCESS). It turns an arbitrary careers page into a stored, replayable
``company_scripts.script`` by:

    observe (browser)  →  author (LLM)  →  validate (recipe_schema)
                       →  replay (recipe_runner, AGENT-FREE)  →  gate (Phase 2)

and accepts only a script that survives the same deterministic path the nightly
replay uses. It never runs at replay time. The import-guard tests
(``test_recipe_runner_import_guard``) prove ``recipe_runner`` and the replay leaf
task's ``tasks/`` closure never import this package's browser/LLM drivers; the
observer's Playwright runs in a subprocess so the browser driver never even lands
in the worker's ``sys.modules``.
"""

from __future__ import annotations

from .discover import discover
from .models import DiscoveryOutcome

__all__ = ["discover", "DiscoveryOutcome"]
