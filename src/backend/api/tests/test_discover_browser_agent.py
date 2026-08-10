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
    # Href-less board (like YC raindrop): the runner selected id_field='title', so the
    # returned rows are keyed on the title and their url falls back to the entry_url.
    return [
        {"id": "Security Engineer", "title": "Security Engineer",
         "url": _URL, "location": "SF"},
        {"id": "ML Engineer", "title": "ML Engineer", "url": _URL, "location": "SF"},
    ]


def _clean_evidence() -> HarvestEvidence:
    return HarvestEvidence(
        declared_total=None, cap_hit=False, terminated_cleanly=True,
        page_advance_ok=None, pages_fetched=1,
    )


def _fake_run(rows, evidence, id_field):
    """Build a fake SELECTING runner returning (rows, evidence, chosen_id_field)."""
    async def _run(script):
        assert script["transport"] == "browser_agent"
        return rows, evidence, id_field
    return _run


# --- accept ------------------------------------------------------------------

async def test_discover_accepts_and_stores_selected_title_id_field() -> None:
    """A href-less board is accepted with the runner's SELECTED id_field='title',
    and discovery STORES that choice in the artifact."""
    outcome = await discover(
        _URL, run_agent=_fake_run(_good_rows(), _clean_evidence(), "title")
    )

    assert outcome.ok
    assert outcome.transport == "browser_agent"
    assert outcome.oracle_kind == "self_consistent"
    assert outcome.attempts == 1
    assert outcome.script is not None
    assert outcome.script["script_version"] == 2
    assert outcome.script["id_field"] == "title"     # the SELECTED field, stored
    assert outcome.script["pagination"]["max_pages"] == 3
    # The stored artifact is itself valid against the write-path schema.
    validate_browser_agent_script(
        outcome.script, transport="browser_agent", oracle_kind="self_consistent"
    )


async def test_discover_stores_url_id_field_for_a_real_href_board() -> None:
    href_rows = [
        {"id": "/jobs/a", "title": "A", "url": "/jobs/a", "location": "SF"},
        {"id": "/jobs/b", "title": "B", "url": "/jobs/b", "location": "NY"},
    ]
    outcome = await discover(
        _URL, run_agent=_fake_run(href_rows, _clean_evidence(), "url")
    )
    assert outcome.ok
    assert outcome.script is not None
    assert outcome.script["id_field"] == "url"


# --- retry then succeed (the crux: sharper instruction on a row-index id) -----

async def test_discover_retries_with_a_sharper_instruction_then_succeeds() -> None:
    seen_instructions: list[str] = []

    async def fake_run(script):
        seen_instructions.append(script["extract"]["instruction"])
        if len(seen_instructions) == 1:
            # attempt 1: no stable id field (element-refs, non-distinct) → runner raised.
            raise RecipeExecutionError("browser-agent extract yielded no stable id field")
        return _good_rows(), _clean_evidence(), "title"

    outcome = await discover(_URL, run_agent=fake_run)

    assert outcome.ok
    assert outcome.attempts == 2
    assert len(seen_instructions) == 2
    # Attempt 2 uses the SHARPER instruction (distinct full titles + real hrefs).
    assert "distinct" in seen_instructions[1]
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
        return [], _clean_evidence(), "title"

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
