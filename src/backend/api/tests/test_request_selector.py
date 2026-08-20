"""E7 capture pivot — the pre-filter + the ONE Haiku pick-and-map call. $0.

No network, no browser, no LLM: the fixtures under ``fixtures/discovery/`` are real
capture-shaped reports (Amazon-like clean public GET, TikTok-like signed POST, and a
board that fires only analytics/config), and the Anthropic client is replaced by a fake
that returns a canned response object.

What these prove, and why each matters:

* the DETERMINISTIC pre-filter is what bounds the prompt — analytics/config/filter
  traffic never reaches the model, so the one paid call stays small and reproducible;
* the model's answer is UNTRUSTED — a hallucinated index, a ``records_path`` that does
  not resolve in the bytes we actually captured, a field map that renders no id/title,
  non-JSON text and a schema violation must each REFUSE, never crash and never store;
* a missing ``ANTHROPIC_API_KEY`` degrades BEFORE any client is constructed, so a
  misconfigured deployment burns no attempt and no money.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from api.config import settings
from api.services.capture import request_selector as rs
from api.services.capture.network_capture import _responses_from_report

# Marked per-test rather than module-wide: half of these are the PURE pre-filter,
# and a blanket asyncio mark on a sync test is a pytest warning, not a no-op.

_FIXTURES = Path(__file__).parent / "fixtures" / "discovery"


def _capture(name: str) -> list[Any]:
    report = json.loads((_FIXTURES / f"{name}_capture.json").read_text())
    return _responses_from_report(report)


def _candidates(name: str) -> list[rs.Candidate]:
    return rs.prefilter_candidates(_capture(name))


def _fake_response(payload: Any) -> SimpleNamespace:
    """A stand-in for the Anthropic Messages response, shaped for
    ``llm_client.extract_text_content`` (text blocks joined)."""
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)], stop_reason="end_turn"
    )


def _answering(payload: Any, *, calls: list[dict] | None = None):
    async def _create(params: dict[str, Any]) -> SimpleNamespace:
        if calls is not None:
            calls.append(params)
        return _fake_response(payload)
    return _create


_AMAZON_ANSWER = {
    "chosen_request_index": 0,
    "records_path": "jobs",
    "field_map": {
        "id": "id_icims",
        "title": "title",
        "url": "https://www.amazon.jobs{job_path}",
        "location": "normalized_location",
        "posted_at": "posted_date",
        "department": "job_category",
    },
    "pagination": {"style": "offset", "param": "offset", "page_size": 10},
}


# --- step 3: the deterministic pre-filter ------------------------------------

def test_prefilter_keeps_only_the_job_shaped_response() -> None:
    """Amazon's capture is three responses; only ``search.json`` carries job records.
    Dropping the other two is what keeps the paid call cheap AND deterministic."""
    candidates = _candidates("amazon")
    assert len(candidates) == 1
    only = candidates[0]
    assert only.index == 0
    assert only.records_path == "jobs"
    assert only.record_count == 10
    assert only.method == "GET"
    assert "search.json" in only.url


def test_prefilter_finds_a_nested_records_path_and_ranks_the_jobs_feed_first() -> None:
    """TikTok's capture has TWO job-ish arrays — the filter catalogue and the real
    ``data.job_post_list``. Ranking by shape + count puts the jobs feed at index 0, so
    even a model that answered "0" without reading would land on the right one."""
    candidates = _candidates("tiktok")
    assert len(candidates) == 2
    assert candidates[0].records_path == "data.job_post_list"
    assert candidates[0].record_count == 10
    assert candidates[0].method == "POST"
    assert candidates[1].records_path == "data.job_category_list"


def test_prefilter_drops_a_board_with_no_jobs_feed() -> None:
    """The Meta case: analytics + feature flags + a session probe. No array of job
    objects anywhere, so there is nothing to select and discovery must refuse rather
    than hand the model noise to pick from."""
    assert _candidates("noise") == []


def test_prefilter_ignores_non_2xx_responses() -> None:
    responses = _capture("amazon")
    broken = [r.__class__(**{**r.__dict__, "status": 403}) for r in responses]
    assert rs.prefilter_candidates(broken) == []


# --- step 4: the one LLM call ------------------------------------------------

def test_build_message_params_pins_the_request_shape() -> None:
    """One source of truth for model/prompt/schema — a second builder would let the
    tests pass against a request production does not send."""
    params = rs.build_message_params(_candidates("amazon"))
    assert params["model"] == rs.HAIKU_MODEL == "claude-haiku-4-5-20251001"
    assert params["max_tokens"] == rs.MAX_TOKENS
    fmt = params["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["schema"]["additionalProperties"] is False
    # The candidate list is IN the prompt (index, method, url, records_path, samples).
    prompt = params["messages"][0]["content"]
    assert "[0] GET https://www.amazon.jobs/en/search.json" in prompt
    assert "records_path: jobs (10 records)" in prompt


@pytest.mark.asyncio
async def test_correct_pick_and_map() -> None:
    calls: list[dict] = []
    selection = await rs.select_request(
        _candidates("amazon"), create_message=_answering(_AMAZON_ANSWER, calls=calls)
    )
    assert len(calls) == 1                       # ONE call, ever
    assert selection.chosen_request_index == 0
    assert selection.records_path == "jobs"
    assert selection.field_map["id"] == "id_icims"
    assert selection.field_map["url"] == "https://www.amazon.jobs{job_path}"
    assert selection.field_map["department"] == "job_category"
    assert selection.pagination is not None
    assert (selection.pagination.style, selection.pagination.param) == ("offset", "offset")


@pytest.mark.asyncio
async def test_maps_a_post_board_with_nested_fields() -> None:
    answer = {
        "chosen_request_index": 0,
        "records_path": "data.job_post_list",
        "field_map": {
            "id": "id", "title": "title",
            "url": "https://lifeattiktok.com/search/{id}",
            "location": "city_info.en_name", "posted_at": None,
            "department": "job_category.en_name",
        },
        "pagination": {"style": "offset", "param": "offset", "page_size": 10},
    }
    selection = await rs.select_request(
        _candidates("tiktok"), create_message=_answering(answer)
    )
    assert selection.field_map["location"] == "city_info.en_name"
    # A null optional is DROPPED, not stored as the string "None" — recipe_rows would
    # otherwise write "None" into every job's posted_on.
    assert "posted_at" not in selection.field_map


@pytest.mark.asyncio
async def test_hallucinated_index_refuses() -> None:
    answer = {**_AMAZON_ANSWER, "chosen_request_index": 7}
    with pytest.raises(rs.RequestSelectionError, match="not one of the 1 candidates"):
        await rs.select_request(_candidates("amazon"), create_message=_answering(answer))


@pytest.mark.asyncio
async def test_records_path_that_does_not_resolve_refuses() -> None:
    """The cheapest hallucination to catch: a plausible path that is not in the bytes
    we recorded. Catching it here costs nothing; catching it at 3am costs a FAILED run
    every night."""
    answer = {**_AMAZON_ANSWER, "records_path": "data.results"}
    with pytest.raises(rs.RequestSelectionError, match="does not resolve"):
        await rs.select_request(_candidates("amazon"), create_message=_answering(answer))


@pytest.mark.asyncio
async def test_records_path_resolving_to_a_non_list_refuses() -> None:
    answer = {**_AMAZON_ANSWER, "records_path": "hits"}
    with pytest.raises(rs.RequestSelectionError, match="non-empty list"):
        await rs.select_request(_candidates("amazon"), create_message=_answering(answer))


@pytest.mark.asyncio
async def test_field_map_that_renders_no_id_or_title_refuses() -> None:
    """``map_records`` silently DROPS a row missing id or title, so a bad map produces a
    zero-row replay — the one outcome that must never be mistaken for 'no jobs today'."""
    answer = {**_AMAZON_ANSWER,
              "field_map": {**_AMAZON_ANSWER["field_map"], "id": "requisition_number"}}
    with pytest.raises(rs.RequestSelectionError, match="renders no usable scalar id/title"):
        await rs.select_request(_candidates("amazon"), create_message=_answering(answer))


@pytest.mark.asyncio
async def test_a_non_scalar_optional_field_is_dropped_not_stored() -> None:
    """Measured against the real board: asked for TikTok's location the model reaches for
    ``city_info`` (an object) rather than ``city_info.en_name``. Storing that writes
    ``{'en_name': 'San Jose'}`` into every job's location, which the normalization
    cascade then tries to canonicalize as a place. An ABSENT location is strictly better
    than a Python repr, so the optional mapping is dropped."""
    answer = {
        "chosen_request_index": 0,
        "records_path": "data.job_post_list",
        "field_map": {
            "id": "id", "title": "title",
            "url": "https://lifeattiktok.com/search/{id}",
            "location": "city_info",                 # the container, not the leaf
            "posted_at": None,
            "department": "job_category.en_name",    # the leaf — kept
        },
        "pagination": None,
    }
    selection = await rs.select_request(
        _candidates("tiktok"), create_message=_answering(answer)
    )
    assert "location" not in selection.field_map
    assert selection.field_map["department"] == "job_category.en_name"


@pytest.mark.asyncio
async def test_a_non_scalar_id_refuses_rather_than_being_dropped() -> None:
    """The required three are NOT prunable. A dict-valued id would become the dedupe and
    close key as a Python repr — a board we cannot identify is one we refuse, not one we
    half-read."""
    answer = {
        "chosen_request_index": 0,
        "records_path": "data.job_post_list",
        "field_map": {
            "id": "city_info", "title": "title",
            "url": "https://lifeattiktok.com/search/{id}",
            "location": None, "posted_at": None, "department": None,
        },
        "pagination": None,
    }
    with pytest.raises(rs.RequestSelectionError, match="no usable scalar id/title"):
        await rs.select_request(_candidates("tiktok"), create_message=_answering(answer))


def test_the_prompt_shows_exact_field_names_and_parsed_query_params() -> None:
    """Both are measured fixes, not decoration. Given only a truncated sample the model
    invented ``position_title`` for a record whose key is ``title``; and given a
    character-truncated URL it answered "no pagination" for amazon.jobs, whose ``offset``
    parameter sits behind a dozen ``facets[]`` entries."""
    prompt = rs.build_message_params(_candidates("amazon"))["messages"][0]["content"]
    assert "record fields: id, id_icims, title, job_path" in prompt
    assert "query params: sort=recent, offset=0, result_limit=10" in prompt
    assert "position_title" not in prompt


@pytest.mark.asyncio
async def test_non_json_text_refuses() -> None:
    with pytest.raises(rs.RequestSelectionError, match="non-JSON"):
        await rs.select_request(
            _candidates("amazon"), create_message=_answering("I think it is the first one!")
        )


@pytest.mark.asyncio
async def test_schema_violation_refuses() -> None:
    with pytest.raises(rs.RequestSelectionError, match="failed schema validation"):
        await rs.select_request(
            _candidates("amazon"),
            create_message=_answering({"chosen_request_index": 0, "records_path": "jobs"}),
        )


@pytest.mark.asyncio
async def test_empty_text_content_refuses() -> None:
    async def _create(params: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(content=[], stop_reason="max_tokens")

    with pytest.raises(rs.RequestSelectionError, match="no text content"):
        await rs.select_request(_candidates("amazon"), create_message=_create)


@pytest.mark.asyncio
async def test_unusable_pagination_hint_is_dropped_not_fatal() -> None:
    """Harvesting page one of a board is a real (if partial) recipe — the completeness
    gate simply never calls such a run VERIFIED, so it can never close a job. Refusing
    the whole board over a bad paging guess would be strictly worse."""
    answer = {**_AMAZON_ANSWER,
              "pagination": {"style": "offset", "param": "  ", "page_size": 0}}
    selection = await rs.select_request(
        _candidates("amazon"), create_message=_answering(answer)
    )
    assert selection.pagination is None


@pytest.mark.asyncio
async def test_no_candidates_refuses_without_calling_the_model() -> None:
    async def _boom(params: dict[str, Any]) -> SimpleNamespace:
        raise AssertionError("the model must not be called with nothing to choose from")

    with pytest.raises(rs.RequestSelectionError, match="no job-shaped"):
        await rs.select_request([], create_message=_boom)


@pytest.mark.asyncio
async def test_missing_api_key_degrades_before_any_client_is_built(monkeypatch) -> None:
    """Graceful degradation, copied from the location cascade: read the key at CALL
    time, raise BEFORE constructing a client, and burn no retries. A deployment without
    a key is our misconfiguration, not evidence that the board is untrackable."""
    monkeypatch.setattr(settings, "anthropic_api_key", None)

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("no Anthropic client may be constructed without a key")

    monkeypatch.setattr(rs, "AsyncAnthropic", _boom)
    with pytest.raises(rs.SelectorKeyMissingError):
        await rs.select_request(_candidates("amazon"))


def test_key_missing_error_is_a_selection_error() -> None:
    """The caller catches the specific one FIRST (to refuse without counting an
    attempt) and the general one second; the subclass relationship is what keeps a
    reordered except-chain from silently swallowing the distinction."""
    assert issubclass(rs.SelectorKeyMissingError, rs.RequestSelectionError)
