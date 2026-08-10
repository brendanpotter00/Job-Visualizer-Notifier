"""E7 Stagehand pivot — the browser-agent discovery orchestrator. $0: runner MOCKED.

Proves the "one bounded session IS the acceptance replay+gate" loop and the bounded-
and-loud invariant (≤2 attempts, then REFUSE) with no Browserbase session and no LLM
call: the runner (which would spawn the paid subprocess) is injected as a fake.
"""

from __future__ import annotations

from typing import Any

import pytest

from api.services.browser_agent.discover import discover
from api.services.browser_agent.schema import validate_browser_agent_script
from api.services.harvest_meta import HarvestEvidence
from api.services.recipe_runner import RecipeExecutionError

pytestmark = pytest.mark.asyncio

_URL = "https://www.ycombinator.com/companies/raindrop/jobs"


def _good_rows() -> list[dict[str, Any]]:
    return [
        {"id": "/companies/raindrop/jobs/security-engineer", "title": "Security Engineer",
         "url": "/companies/raindrop/jobs/security-engineer", "location": "SF"},
        {"id": "/companies/raindrop/jobs/ml-engineer", "title": "ML Engineer",
         "url": "/companies/raindrop/jobs/ml-engineer", "location": "SF"},
    ]


def _clean_evidence() -> HarvestEvidence:
    return HarvestEvidence(
        declared_total=None, cap_hit=False, terminated_cleanly=True,
        page_advance_ok=None, pages_fetched=1,
    )


# --- accept ------------------------------------------------------------------

async def test_discover_accepts_and_stores_browser_agent_transport() -> None:
    seen_scripts: list[dict] = []

    async def fake_run(script):
        seen_scripts.append(script)
        assert script["transport"] == "browser_agent"
        assert script["entry_url"] == _URL
        return _good_rows(), _clean_evidence()

    outcome = await discover(_URL, run_agent=fake_run)

    assert outcome.ok
    assert outcome.transport == "browser_agent"
    assert outcome.oracle_kind == "self_consistent"
    assert outcome.attempts == 1
    assert outcome.script is not None
    assert outcome.script["script_version"] == 2
    assert outcome.script["id_field"] == "url"
    assert outcome.script["pagination"]["max_pages"] == 3
    # The stored artifact is itself valid against the write-path schema.
    validate_browser_agent_script(
        outcome.script, transport="browser_agent", oracle_kind="self_consistent"
    )


# --- retry then succeed (the crux: sharper instruction on a row-index id) -----

async def test_discover_retries_with_a_sharper_instruction_then_succeeds() -> None:
    seen_instructions: list[str] = []

    async def fake_run(script):
        seen_instructions.append(script["extract"]["instruction"])
        if len(seen_instructions) == 1:
            # attempt 1: the extract returned DOM row-indices → runner raised.
            raise RecipeExecutionError("browser-agent id '0-650' is a DOM row-index")
        return _good_rows(), _clean_evidence()

    outcome = await discover(_URL, run_agent=fake_run)

    assert outcome.ok
    assert outcome.attempts == 2
    assert len(seen_instructions) == 2
    # Attempt 2 uses the SHARPER instruction that names the href, not the row position.
    assert "row number or position" in seen_instructions[1]
    assert seen_instructions[0] != seen_instructions[1]


# --- refuse ------------------------------------------------------------------

async def test_discover_two_failures_refuse() -> None:
    attempts = 0

    async def fake_run(script):
        nonlocal attempts
        attempts += 1
        raise RecipeExecutionError("browser-agent id is a DOM row-index")

    outcome = await discover(_URL, run_agent=fake_run)

    assert outcome.ok is False
    assert outcome.attempts == 2
    assert attempts == 2                    # bounded — no third attempt
    assert outcome.script is None
    assert outcome.refuse_reason and "RecipeExecutionError" in outcome.refuse_reason


async def test_discover_zero_rows_refuse() -> None:
    """Belt-and-braces: if the (faked) runner ever returned an empty harvest, the gate
    is zero → REFUSE (in production the runner RAISES on zero rows first)."""
    async def fake_run(script):
        return [], _clean_evidence()

    outcome = await discover(_URL, run_agent=fake_run)
    assert outcome.ok is False
    assert outcome.attempts == 2
    assert outcome.refuse_reason and "HarvestGateError" in outcome.refuse_reason


async def test_discover_subprocess_failure_refuses() -> None:
    async def fake_run(script):
        raise RecipeExecutionError("browser-agent subprocess timed out after 120.0s")

    outcome = await discover(_URL, run_agent=fake_run)
    assert outcome.ok is False
    assert outcome.refuse_reason and "timed out" in outcome.refuse_reason
