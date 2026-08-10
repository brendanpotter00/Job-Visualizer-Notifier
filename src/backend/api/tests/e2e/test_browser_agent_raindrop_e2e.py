"""E7 Stagehand pivot — the ONE paid end-to-end browser-agent run. NOT $0. NEVER CI.

The single authorized real run: a REAL bounded Browserbase Stagehand session against
YC raindrop (the page the deleted Sonnet-authors-JSON path failed on), driven through
the production ``discover`` → ``run_browser_agent`` → gate path. It costs ~cents and
needs ``BROWSERBASE_API_KEY`` / ``BROWSERBASE_PROJECT_ID`` / ``ANTHROPIC_API_KEY`` (in
the worktree-root ``.env.local``).

Guarded by ``RUN_BROWSER_AGENT_E2E=1`` so it is SKIPPED by default and never runs in
the suite / CI. Run it exactly once (the ORCHESTRATOR does — the IMPLEMENT agent does
NOT), from the worktree root:

    RUN_BROWSER_AGENT_E2E=1 PYTHONPATH=src/backend:. \\
      .venv/bin/python -m pytest \\
      src/backend/api/tests/e2e/test_browser_agent_raindrop_e2e.py -s -v

A pass proves: one bounded (≤3-page) Browserbase session read real jobs off the
rendered page, the ids passed the stable-id proof (no ``"0-650"`` row indices), the
gate accepted, and the stored artifact is a valid ``browser_agent`` / ``script_version=2``
/ ``self_consistent`` script.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_BROWSER_AGENT_E2E") != "1",
    reason="paid real Browserbase + real Sonnet run; set RUN_BROWSER_AGENT_E2E=1 to run once",
)

# The exact page the old path was reported to fail on (BUILD-PLAN raindrop 9/9).
RAINDROP_URL = "https://www.ycombinator.com/companies/raindrop/jobs"

# Worktree root holds the gitignored .env.local with the Browserbase/Anthropic creds.
_WORKTREE_ROOT = Path(__file__).resolve().parents[5]


def _load_creds_into_env() -> None:
    """Load the worktree-root .env.local creds into ``os.environ`` + ``settings`` so
    the run works regardless of the pytest CWD (the runner injects them into the
    subprocess env). Never prints them."""
    from dotenv import dotenv_values

    from api.config import settings

    env = dotenv_values(_WORKTREE_ROOT / ".env.local")
    for key, attr in (
        ("BROWSERBASE_API_KEY", "browserbase_api_key"),
        ("BROWSERBASE_PROJECT_ID", "browserbase_project_id"),
        ("ANTHROPIC_API_KEY", "anthropic_api_key"),
    ):
        value = env.get(key) or os.environ.get(key)
        assert value, f"{key} must be set for the paid E2E"
        os.environ[key] = value
        setattr(settings, attr, value)


@pytest.mark.timeout(300)
@pytest.mark.asyncio
async def test_browser_agent_raindrop_end_to_end() -> None:
    _load_creds_into_env()

    from api.services.browser_agent import discover

    outcome = await discover(RAINDROP_URL)

    assert outcome.attempts <= 2
    if not outcome.ok:
        pytest.fail(f"browser-agent discovery REFUSED YC raindrop: {outcome.refuse_reason}")

    assert outcome.transport == "browser_agent"
    assert outcome.oracle_kind == "self_consistent"
    assert outcome.script is not None
    assert outcome.script["script_version"] == 2
    # YC raindrop's rows are click-to-open with no per-job href, so the runner
    # correctly falls back from 'url' to a title-based id — any of the valid fields
    # is acceptable for a live board.
    assert outcome.script["id_field"] in ("url", "title", "title|location")
    pagination = outcome.script.get("pagination")
    assert pagination is None or pagination["max_pages"] <= 3
    print(
        f"\nBROWSER-AGENT E2E OK: transport={outcome.transport} "
        f"oracle={outcome.oracle_kind} attempts={outcome.attempts} note={outcome.cost_note}"
    )
