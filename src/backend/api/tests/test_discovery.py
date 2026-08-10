"""E7 Phase 3b — the discovery agent. $0: MOCKED author + FIXTURE observation.

Proves the observe→author→validate→replay→gate loop and the "bounded and loud"
invariant (≤2 attempts, then REFUSE) without a single real LLM call or a live
browser run:

* a good report + a canned VALID recipe → discover validates + replays (agent-free,
  against the committed amazon.jobs capture) + gates it → ok, transport, oracle_kind;
* a first-attempt INVALID recipe → retry with the error fed back → success on 2;
* two bad attempts → REFUSE with the reason recorded (no third attempt);
* a keyless env → MissingAnthropicKeyError → REFUSE with NO attempt burned;
* the author's JSON schema IS the recipe vocabulary (browser ops unemittable);
* observe() drives its (injected) browser, never a live site.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from api.services import recipe_schema
from api.services.discovery import author as author_mod
from api.services.discovery import observer as observer_mod
from api.services.discovery.discover import discover

pytestmark = pytest.mark.asyncio

_FIX = Path(__file__).parent / "fixtures"
_AMAZON_CAPTURE = json.loads((_FIX / "captures" / "amazon_global.json").read_text())
_AMAZON_REPORT = json.loads((_FIX / "discovery" / "amazon_report.json").read_text())


def _canned_amazon_recipe() -> dict:
    """A VALID recipe that replays cleanly against the committed amazon capture:
    single fetch, facet_sum oracle (is_intern → 22,191), rows from ``jobs``."""
    return {
        "script_version": 1,
        "transport": "http_json",
        "expected_min_jobs": 5,
        "steps": [
            {"op": "fetch", "method": "GET",
             "url": "https://www.amazon.jobs/en/search.json?facets[]=is_intern", "headers": {}},
            {"op": "extract_json_path", "records_path": "jobs",
             "fields": {"id": "id_icims", "title": "title",
                        "url": "https://www.amazon.jobs{job_path}"}},
            {"op": "dedupe_key", "field": "id"},
        ],
        "oracle": {"kind": "facet_sum", "facet_path": "facets.is_intern",
                   "single_valued": True, "window_cap": 10000, "total_path": "hits"},
    }


def _client_factory(payload: dict):
    def factory() -> httpx.Client:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload)
        return httpx.Client(transport=httpx.MockTransport(handler))
    return factory


async def _fixture_observe(url: str) -> dict:
    return _AMAZON_REPORT


# --- accept ------------------------------------------------------------------

async def test_discover_accepts_valid_recipe() -> None:
    async def author(report, *, previous_error=None):
        assert report == _AMAZON_REPORT   # the fixture observation reached the author
        return _canned_amazon_recipe()

    outcome = await discover(
        "https://www.amazon.jobs/en/search",
        observe_fn=_fixture_observe,
        author_fn=author,
        http_client_factory=_client_factory(_AMAZON_CAPTURE),
    )
    assert outcome.ok
    assert outcome.transport == "http_json"
    assert outcome.oracle_kind == "facet_sum"
    assert outcome.attempts == 1
    assert outcome.script is not None
    assert outcome.script["steps"][0]["op"] == "fetch"


# --- retry then succeed ------------------------------------------------------

async def test_discover_retries_then_succeeds() -> None:
    seen_errors: list[str | None] = []

    async def author(report, *, previous_error=None):
        seen_errors.append(previous_error)
        if len(seen_errors) == 1:
            return {"script_version": 99, "nonsense": True}   # invalid → RecipeError
        return _canned_amazon_recipe()

    outcome = await discover(
        "https://www.amazon.jobs/en/search",
        observe_fn=_fixture_observe,
        author_fn=author,
        http_client_factory=_client_factory(_AMAZON_CAPTURE),
    )
    assert outcome.ok
    assert outcome.attempts == 2
    assert seen_errors[0] is None            # first attempt has no prior error
    assert seen_errors[1] and "RecipeError" in seen_errors[1]  # fed back verbatim


# --- refuse ------------------------------------------------------------------

async def test_discover_two_failures_refuses() -> None:
    attempts_seen = 0

    async def author(report, *, previous_error=None):
        nonlocal attempts_seen
        attempts_seen += 1
        return {"script_version": 1, "totally": "invalid"}   # never validates

    outcome = await discover(
        "https://www.amazon.jobs/en/search",
        observe_fn=_fixture_observe,
        author_fn=author,
        http_client_factory=_client_factory(_AMAZON_CAPTURE),
    )
    assert outcome.ok is False
    assert outcome.attempts == 2
    assert attempts_seen == 2                 # bounded — no third attempt
    assert outcome.refuse_reason and "RecipeError" in outcome.refuse_reason
    assert outcome.script is None


async def test_discover_keyless_refuses_without_burning_an_attempt() -> None:
    async def author(report, *, previous_error=None):
        raise author_mod.MissingAnthropicKeyError("anthropic_api_key is not configured")

    outcome = await discover(
        "https://www.amazon.jobs/en/search",
        observe_fn=_fixture_observe,
        author_fn=author,
        http_client_factory=_client_factory(_AMAZON_CAPTURE),
    )
    assert outcome.ok is False
    assert outcome.attempts == 0              # keyless → no attempt burned
    assert outcome.refuse_reason and "missing_api_key" in outcome.refuse_reason


async def test_discover_refuses_a_replay_failure() -> None:
    """A schema-valid recipe that RAISES at replay (a records_path that doesn't
    resolve against the served payload) is refused, not accepted."""
    async def author(report, *, previous_error=None):
        bad = _canned_amazon_recipe()
        bad["steps"][1]["records_path"] = "does_not_exist"
        return bad

    outcome = await discover(
        "https://www.amazon.jobs/en/search",
        observe_fn=_fixture_observe,
        author_fn=author,
        http_client_factory=_client_factory(_AMAZON_CAPTURE),
    )
    assert outcome.ok is False
    assert outcome.refuse_reason and "RecipeExecutionError" in outcome.refuse_reason


# --- author-contract: schema IS the recipe vocabulary ------------------------

def test_author_output_schema_is_the_recipe_vocabulary() -> None:
    schema = author_mod.RECIPE_OUTPUT_SCHEMA
    step_ops = set(schema["properties"]["steps"]["items"]["properties"]["op"]["enum"])
    expected_ops = set(recipe_schema._OP_VALIDATORS) - set(recipe_schema._BROWSER_OPS)
    assert step_ops == expected_ops
    # The Phase-4 browser/click ops are NOT emittable by the model.
    assert "click_sequence" not in step_ops
    assert not (step_ops & set(recipe_schema._BROWSER_OPS))

    assert set(schema["properties"]["transport"]["enum"]) == set(recipe_schema.TRANSPORTS)
    assert set(schema["properties"]["oracle"]["properties"]["kind"]["enum"]) == set(
        recipe_schema.ORACLE_KINDS
    )


# --- observation path (injected fake browser; never a live site) -------------

async def test_observe_uses_injected_capture() -> None:
    captured_url = {}

    async def fake_capture(url: str) -> dict:
        captured_url["url"] = url
        return {"entry_url": url, "job_like_json_responses": []}

    report = await observer_mod.observe("https://acme.example/careers", capture_fn=fake_capture)
    assert captured_url["url"] == "https://acme.example/careers"
    assert report["entry_url"] == "https://acme.example/careers"


def test_build_report_ranks_job_like_arrays() -> None:
    responses = [{
        "method": "GET", "url": "https://x/api/search.json", "status": 200,
        "content_type": "application/json", "resource_type": "xhr",
        "body": {"jobs": [{"id": 1, "title": "Engineer", "location": "Remote",
                           "job_path": "/j/1"}], "total": 1},
    }]
    report = observer_mod.build_report(
        entry_url="https://x", page_title="t", nav_error=None,
        wall_seconds=1.0, responses=responses, html="<html></html>",
    )
    assert report["job_like_json_responses"]
    top = report["job_like_json_responses"][0]
    assert top["record_arrays"][0]["path"] == "jobs"
    assert top["counts"] == {"total": 1}
