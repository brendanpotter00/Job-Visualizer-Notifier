"""E7 Phase 3b — the ONE paid end-to-end discovery run. NOT $0. NEVER in CI.

This is the single authorized real run: a REAL local Playwright observation of
``amazon.jobs`` + a REAL Claude Sonnet authoring call, driven through
validate→replay→gate. It costs ~$0.25–1 and requires ``ANTHROPIC_API_KEY`` and a
Chromium install (``playwright install chromium``).

Guarded by ``RUN_DISCOVERY_E2E=1`` so it is SKIPPED by default and never runs in
the suite / CI. Run it exactly once (the orchestrator does), with:

    RUN_DISCOVERY_E2E=1 PYTHONPATH=.:../.. \\
      ../../.venv/bin/python -m pytest api/tests/e2e/test_discovery_amazon_e2e.py -s -v

A pass means the observe→author→validate→replay→gate loop closed against a live
site with a real model — proving the whole Phase-3 pipeline end to end.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DISCOVERY_E2E") != "1",
    reason="paid real-browser + real-Sonnet run; set RUN_DISCOVERY_E2E=1 to run once",
)

# The global board; the discovery agent must find a JSON endpoint + a completeness
# oracle behind it. (BUILD-PLAN §9 pins the true total near 22,191.)
AMAZON_URL = "https://www.amazon.jobs/en/search?base_query=&loc_query="


# Overrides the global 120s pytest-timeout: this does a REAL full-board replay
# (offset pagination over amazon.jobs) after the observe + Sonnet-author steps,
# which alone can take 2-3 minutes. A confirmed run on 2026-08-09 authored a
# valid recipe and entered replay past validate — the 120s default cut it off
# mid-fetch, not a discovery failure.
@pytest.mark.timeout(600)
@pytest.mark.asyncio
async def test_discovery_amazon_end_to_end() -> None:
    from api.config import settings
    from api.services.discovery import discover

    assert settings.anthropic_api_key, "ANTHROPIC_API_KEY must be set for the paid E2E"

    outcome = await discover(AMAZON_URL)

    # The loud contract: either a validated, replay-proven, gated script, or a
    # loud REFUSE with a reason — never a silent half-result.
    assert outcome.attempts <= 2
    if not outcome.ok:
        pytest.fail(f"discovery REFUSED amazon.jobs: {outcome.refuse_reason}")

    assert outcome.transport in ("http_json", "http_html")
    assert outcome.oracle_kind in ("facet_sum", "header", "sitemap", "self_consistent")
    assert outcome.script is not None
    assert outcome.script["steps"][0]["op"] == "fetch"
    print(
        f"\nDISCOVERY E2E OK: transport={outcome.transport} oracle={outcome.oracle_kind} "
        f"attempts={outcome.attempts} note={outcome.cost_note}"
    )
