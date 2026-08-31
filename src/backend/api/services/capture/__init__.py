"""DISCOVERY SIDE — deterministic API capture (E7 Phase 3b, the capture pivot).

Open a pasted careers URL in a browser ONCE, record its network traffic, have Claude
Haiku 4.5 pick the jobs request and map its fields ONCE, synthesize a deterministic
recipe, prove it replays from our production environment, and store it. Runtime never
calls an LLM again — the nightly harvest is ``recipe_runner`` (``http_json``) or
``browser_fetch``, both deterministic. A board with no capturable API is REFUSED.

This package REPLACED ``services/browser_agent`` (the Stagehand DOM tier, which re-read
a rendered page with an LLM every 24h and has been retired). What survived the swap is
:class:`~api.services.discovery.models.DiscoveryOutcome`, which is transport-agnostic.

The load-bearing boundary, identical to the replay side's: ``playwright`` is imported
ONLY by the child :mod:`._capture_main` (spawned as a SUBPROCESS), NEVER by this
package's in-process modules. Importing this package therefore does NOT make a browser
driver resident in the shared Procrastinate worker — the ``recipe_runner`` import-guard
tests prove it, and that is exactly why the session runs out of process. ``anthropic``
IS reachable from here, deliberately: this package is where the one LLM call lives, and
the runtime guard tolerates a co-resident LLM SDK (see
``recipe_runner._RUNTIME_FORBIDDEN_MODULES``) while the static guards prove the REPLAY
code cannot reach it.
"""

from __future__ import annotations

from ..discovery.models import DiscoveryOutcome
from .discover import discover
from .network_capture import CaptureError, CaptureResult, capture_board

__all__ = [
    "CaptureError",
    "CaptureResult",
    "DiscoveryOutcome",
    "capture_board",
    "discover",
]
