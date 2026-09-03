"""E7 Phase 3c — the ``browser_fetch`` replay tier.

Replays a board's CAPTURED jobs API request from inside our own headless Chromium, on
the board's own origin, for the boards whose otherwise-deterministic JSON API refuses
a plain ``httpx`` call (origin check / cookie gate / request signing — TikTok). Same
recipe grammar as ``http_json`` plus a required ``origin_url``; same
``(rows, HarvestEvidence)`` out; same UNCHANGED Phase-2 gate downstream.

Only :mod:`._browser_fetch_main` imports ``playwright``, and only ever as a
subprocess — importing THIS package must leave the replay worker agent-free, which
``api/tests/test_recipe_runner_import_guard.py`` proves by AST walk. Do not import
the subprocess module from here.
"""

from __future__ import annotations

from .runner import run_browser_fetch

__all__ = ["run_browser_fetch"]
