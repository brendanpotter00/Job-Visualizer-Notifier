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
        # The live amazon.jobs list payload carries a 4.5 KB ``description`` on 10/10
        # records; this fixture's were trimmed before it existed as a mappable field,
        # so the honest answer against these bytes is null. The real thing is exercised
        # against the Atlassian fixture below.
        "description": None,
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
    assert selection.field_map["location"] == "normalized_location"
    assert selection.field_map["posted_at"] == "posted_date"
    assert "description" not in selection.field_map          # answered null
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
            "description": None,
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
            "description": None,
        },
        "pagination": None,
    }
    selection = await rs.select_request(
        _candidates("tiktok"), create_message=_answering(answer)
    )
    assert "location" not in selection.field_map
    # Only the OPTIONAL mapping goes; the board is still perfectly trackable.
    assert selection.field_map["title"] == "title"


@pytest.mark.asyncio
async def test_a_list_of_location_strings_is_kept_not_pruned() -> None:
    """The over-prune this check used to commit, on the board that exposed it. Atlassian
    publishes ``locations`` as a list of plain strings; the model maps it correctly, and
    the prune then deleted the ONLY location mapping the board had — so all 235 jobs
    stored a NULL location and went ``normalization_status='failed'``, silently, with
    nothing in the recipe to show a location had ever been found. A list of scalars is
    multi-value data the runner folds to ``"a; b"``, so it must survive."""
    answer = {
        "chosen_request_index": 0,
        "records_path": "",
        "field_map": {
            "id": "id", "title": "title",
            "url": "portalJobPost.portalUrl",
            "location": "locations",          # a list of plain strings — KEEP
            "posted_at": None,
            "description": None,
        },
        "pagination": None,
    }
    selection = await rs.select_request(
        _candidates("atlassian"), create_message=_answering(answer)
    )
    assert selection.field_map["location"] == "locations"


# --- unit 7: the field map learns ``description``, and forgets ``department`` ---
#
# The single reason custom-company jobs got ZERO enrichment rows. The claim in
# ``routers/internal_enrichment`` has no source filter — the only thing excluding
# them is ``enrichment_monitor.DESCRIPTION_SQL IS NOT NULL``, which reads
# ``details->>'description'`` — and the selection schema was a CLOSED six-key object
# with no description key, so the model could not answer with one even while looking
# straight at it. The Atlassian fixture below is the live payload's own first two
# records: 1,523 and 757 characters of ``<p>``-heavy ``overview`` HTML.

_ATLASSIAN_DESCRIPTION_ANSWER = {
    "chosen_request_index": 0,
    "records_path": "",
    "field_map": {
        "id": "id", "title": "title",
        "url": "portalJobPost.portalUrl",
        "location": "locations",
        "posted_at": None,
        "description": "overview",
    },
    "pagination": None,
}


@pytest.mark.asyncio
async def test_a_real_description_mapping_is_stored_and_survives_the_prune() -> None:
    """A long HTML string is a SCALAR, not a container, so the prune that ate
    Atlassian's ``locations`` has no claim on it. Asserted rather than assumed —
    ``_prune_non_scalar_optionals`` is the exact check that already deleted one
    correctly-mapped field on this exact board."""
    selection = await rs.select_request(
        _candidates("atlassian"),
        create_message=_answering(_ATLASSIAN_DESCRIPTION_ANSWER),
    )
    assert selection.field_map["description"] == "overview"

    # And it renders as the real thing the runner will store: >1 KB of HTML prose.
    records = rs.dig_records(_candidates("atlassian")[0].payload, "")
    rendered = rs.render_row_field(records[0], "description", "overview")
    assert isinstance(rendered, str)
    assert len(rendered) > 700 and "<p>" in rendered


@pytest.mark.asyncio
async def test_a_container_valued_description_is_still_pruned() -> None:
    """The failure mode the prune exists for, on the description key: ``portalJobPost``
    is an object, and storing it writes a Python repr into ``details->>'description'``
    — which the enrichment claim would then treat as a real description and hand the
    classifier a dict spelling. Absent is better."""
    answer = {
        **_ATLASSIAN_DESCRIPTION_ANSWER,
        "field_map": {
            **_ATLASSIAN_DESCRIPTION_ANSWER["field_map"],
            "description": "portalJobPost",       # the container, not a leaf
        },
    }
    selection = await rs.select_request(
        _candidates("atlassian"), create_message=_answering(answer)
    )
    assert "description" not in selection.field_map
    assert selection.field_map["location"] == "locations"      # the rest is untouched


@pytest.mark.asyncio
async def test_a_list_valued_description_is_pruned_not_folded() -> None:
    """``location``/``department``/``company`` are the runner's multi-value fields; a
    description is not one of them. A board publishing a LIST where a description should
    be has been mapped one level too high, and joining unrelated prose into one blob
    would hand the classifier a description no job actually has."""
    answer = {
        **_ATLASSIAN_DESCRIPTION_ANSWER,
        "field_map": {
            **_ATLASSIAN_DESCRIPTION_ANSWER["field_map"],
            "description": "locations",           # a list of plain strings
        },
    }
    selection = await rs.select_request(
        _candidates("atlassian"), create_message=_answering(answer)
    )
    assert "description" not in selection.field_map


def test_the_closed_key_set_carries_description_and_not_department() -> None:
    """Anthropic strict mode forbids dynamic keys, so ``field_map`` is a closed object
    and the key set lives in THREE places that must agree: the pydantic envelope, the
    JSON schema, and the prompt that tells the model what to look for. A key present in
    two of them and missing from the third is a mapping the model is asked for and then
    silently cannot return — which is exactly how ``description`` was unreachable."""
    schema = rs.build_message_params(_candidates("amazon"))["output_config"]["format"]
    fields = schema["schema"]["properties"]["field_map"]
    assert fields["additionalProperties"] is False
    assert set(fields["properties"]) == {
        "id", "title", "url", "location", "posted_at", "description",
    }
    assert set(fields["required"]) == set(fields["properties"])
    assert set(rs._FieldMap.model_fields) == set(fields["properties"])
    # The bullet form, not a bare substring: the prompt still says "departments" while
    # explaining grouped boards, and still lists "description" among the record key
    # names a board might use. What must be true is that each is (or is not) a FIELD
    # the model is being asked to map.
    assert "- description:" in rs.SYSTEM_PROMPT
    assert "department:" not in rs.SYSTEM_PROMPT


def test_the_prompt_asks_for_the_field_that_differs_between_jobs() -> None:
    """A measured fix, not a style note. Asked for Atlassian's description the model
    first answered ``overview`` — the field that opens 'Working at Atlassian…' on every
    posting: 294 characters of shared boilerplate and only 154 DISTINCT texts across 248
    records. It passes ``DESCRIPTION_SQL IS NOT NULL`` and tells a classifier nothing.
    The schema allows exactly ONE path, so the tie-break has to live in the prompt, and
    it has to be something the model can DECIDE from the sample records it is shown."""
    prompt = rs.SYSTEM_PROMPT
    assert "THIS ROLE" in prompt and "COMPANY" in prompt
    assert "CHANGES between them" in prompt


@pytest.mark.asyncio
async def test_a_department_answer_is_ignored_rather_than_stored() -> None:
    """A model still answering with the retired key must not smuggle it back into a
    stored recipe — the envelope ignores unknown keys, and the optional-field walk only
    looks at names the closed set names."""
    answer = {
        **_ATLASSIAN_DESCRIPTION_ANSWER,
        "field_map": {
            **_ATLASSIAN_DESCRIPTION_ANSWER["field_map"], "department": "category",
        },
    }
    selection = await rs.select_request(
        _candidates("atlassian"), create_message=_answering(answer)
    )
    assert "department" not in selection.field_map
    assert selection.field_map["description"] == "overview"


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
            "location": None, "posted_at": None, "description": None,
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
    assert issubclass(rs.NoJobsFeedError, rs.RequestSelectionError)


# --- the url mapping ---------------------------------------------------------

@pytest.mark.asyncio
async def test_a_url_mapping_that_is_not_a_link_refuses() -> None:
    """``url`` is the third REQUIRED field and was the only one never rendered, so a
    mapping onto a bare requisition code was stored unchallenged — ``map_records``
    resolves a value against ``base_url`` only when it starts with ``/``, so every job
    on the board got ``A215432`` as its link. Measured on a real lifeattiktok run."""
    answer = {**_AMAZON_ANSWER,
              "field_map": {**_AMAZON_ANSWER["field_map"], "url": "id_icims"}}
    with pytest.raises(rs.RequestSelectionError, match="renders no usable link"):
        await rs.select_request(_candidates("amazon"), create_message=_answering(answer))


@pytest.mark.asyncio
@pytest.mark.parametrize("spec", ["job_path", "https://www.amazon.jobs{job_path}"])
async def test_a_relative_path_or_a_template_is_a_usable_link(spec: str) -> None:
    """The two shapes a real board actually gives us: a leading-slash path ``base_url``
    resolves, and a template the model builds. Both must pass, or the check above
    would refuse boards we can read."""
    answer = {**_AMAZON_ANSWER,
              "field_map": {**_AMAZON_ANSWER["field_map"], "url": spec}}
    selection = await rs.select_request(
        _candidates("amazon"), create_message=_answering(answer)
    )
    assert selection.field_map["url"] == spec


# --- "none of these is a jobs feed" ------------------------------------------

@pytest.mark.asyncio
async def test_the_model_can_answer_that_none_of_them_is_a_jobs_feed() -> None:
    """The refusal branch. Without it the schema REQUIRES an index, so a round left
    with only a filter catalogue must name it — and that forced answer then passes
    every downstream check, because the acceptance gate compares the replay against
    that same array. ``None`` must reach the caller as its own exception, not as a
    sentinel index nobody remembers to test for."""
    answer = {
        "chosen_request_index": None,
        "records_path": "",
        "field_map": {"id": "", "title": "", "url": "",
                      "location": None, "posted_at": None, "description": None},
        "pagination": None,
    }
    with pytest.raises(rs.NoJobsFeedError, match="is a list of job postings"):
        await rs.select_request(_candidates("amazon"), create_message=_answering(answer))


def test_the_prompt_and_schema_both_offer_the_refusal_branch() -> None:
    """A nullable field the prompt never mentions is a branch the model never takes."""
    params = rs.build_message_params(_candidates("amazon"))
    schema = params["output_config"]["format"]["schema"]
    assert schema["properties"]["chosen_request_index"]["type"] == ["integer", "null"]
    assert "chosen_request_index: null" in params["system"]


# --- a failed CALL is a failed round, not a crash ----------------------------

@pytest.mark.asyncio
async def test_an_sdk_error_becomes_a_selection_error() -> None:
    """``max_retries=0`` means a 529/overload reaches us on the first blip. Uncaught it
    escapes ``discover``'s round loop entirely and permanently refuses a trackable
    board on a transient LLM outage — so it has to arrive as the exception the caller
    already knows how to re-ask after."""
    import httpx
    from anthropic import InternalServerError

    async def _overloaded(params: dict[str, Any]) -> Any:
        raise InternalServerError(
            "overloaded",
            response=httpx.Response(
                529, request=httpx.Request("POST", "https://api.anthropic.com")
            ),
            body=None,
        )

    with pytest.raises(rs.RequestSelectionError, match="the selector call failed"):
        await rs.select_request(_candidates("amazon"), create_message=_overloaded)


@pytest.mark.asyncio
async def test_a_missing_key_is_still_a_key_error_not_a_call_failure(monkeypatch) -> None:
    """The SDK-error wrap must not swallow the degradation path: a missing key still
    has to arrive as ``SelectorKeyMissingError`` so the caller refuses WITHOUT counting
    an attempt."""
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    with pytest.raises(rs.SelectorKeyMissingError):
        await rs.select_request(_candidates("amazon"))


# --- the grouped payload (binance): offer the WHOLE board, not one group ----

def test_a_grouped_board_offers_the_union_and_ranks_it_over_a_single_group() -> None:
    """binance.com's real shape, trimmed: 4 department groups of 2/1/4/3 postings.

    The pre-filter used to rank ``2.postings`` top — the biggest single group — and
    everything downstream then agreed with it, because every later check compares the
    replay against that same array. What was lost is visible in the numbers here: the
    winner must be the union of all four groups, not the largest of them."""
    candidates = _candidates("grouped")
    feed = next(c for c in candidates if "jobs-lever" in c.url)

    assert feed.records_path == "*.postings"
    assert feed.record_count == 10                       # 2 + 1 + 4 + 3
    assert len(feed.records) == 10
    assert len({r["id"] for r in feed.records}) == 10     # every group, no duplicates
    # ...and the largest single group, which is what it beat.
    assert max(len(g["postings"]) for g in feed.payload) == 4


def test_the_union_is_only_offered_when_it_beats_every_single_group() -> None:
    """One group carrying the array is not a grouped board — offering ``*.jobs`` beside
    ``0.jobs`` there would spend one of the model's six candidate slots on the same
    records under a second name."""
    one_group_has_it = [{"jobs": [{"id": "a", "title": "t", "url": "/u"}]}, {"jobs": []}]
    paths = []
    rs._walk_record_arrays(one_group_has_it, "", 0, paths)
    assert [p for p, *_ in paths if "*" in p] == []

    two_groups_have_it = [
        {"jobs": [{"id": "a", "title": "t", "url": "/u"}]},
        {"jobs": [{"id": "b", "title": "t", "url": "/u"}]},
    ]
    paths = []
    rs._walk_record_arrays(two_groups_have_it, "", 0, paths)
    assert ("*.jobs", 2) in [(p, n) for p, n, *_ in paths]


def test_the_union_counts_every_group_not_the_five_the_walk_recurses_into() -> None:
    """The recursion samples five children of a list; the union may not. binance ships
    FOURTEEN groups, so a count taken over five of them would understate the board by
    exactly the amount this whole path exists to recover."""
    groups = [
        {"postings": [{"id": f"{g}-{i}", "title": "t", "url": "/u"} for i in range(3)]}
        for g in range(14)
    ]
    paths = []
    rs._walk_record_arrays(groups, "", 0, paths)
    assert ("*.postings", 42) in [(p, n) for p, n, *_ in paths]


def test_the_prompt_tells_the_model_what_a_star_path_means() -> None:
    """The pre-filter offers ``*.postings``; a model that does not know what the segment
    means would 'correct' it back to a single group, which is the exact bug. The
    deterministic widening in ``discover`` is the guarantee — this is what keeps it from
    having to fire."""
    assert "'*.postings'" in rs.SYSTEM_PROMPT
    listing = rs.build_message_params(_candidates("grouped"))["messages"][0]["content"]
    assert "records_path: *.postings" in listing
