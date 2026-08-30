"""E7 Phase 3a/3c — the closed-vocabulary script validator. Pure, no DB, no network.

Proves: every valid op round-trips; each browser transport / ``click_sequence`` is
rejected with a capability message; malformed shapes are rejected naming the field;
cardinality (one fetch / <=1 pagination / one extraction / one oracle) is enforced;
unknown keys fail loudly; and transport/oracle_kind column mismatch is caught
(validate-on-read protection).

Phase 3c adds the ``browser_fetch`` transport, whose whole schema surface is one
extra top-level key: ``origin_url`` is REQUIRED for it and REJECTED for the two HTTP
transports. The Phase-4 rejections (``page_fetch``/``page_request``/``dom``/
``browser_dom``/``click_sequence``) are re-asserted here precisely because
``browser_fetch`` is adjacent to them and must not be read as opening that door.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from api.services.recipe_schema import (
    BROWSER_FETCH_MAX_PAGES,
    CANONICAL_OPTIONAL_FIELDS,
    CANONICAL_REQUIRED_FIELDS,
    RecipeError,
    dig_records,
    validate_recipe,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "recipes"


def _load(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text())


# --- valid multi-primitive scripts round-trip -------------------------------

@pytest.mark.parametrize(
    "name",
    [
        "amazon_global.json", "meta.json", "ycombinator.json", "janestreet.json",
        # The captured-board corpus ``test_recipe_corpus_regression`` replays. Every
        # one is a REAL stored recipe, so a schema change that would have rejected a
        # board we already track fails here rather than at 3am.
        "goldman_sachs.json", "microsoft.json", "amazon_search.json",
        "atlassian.json", "spotify.json",
    ],
)
def test_valid_multiprimitive_scripts_validate(name: str) -> None:
    script = _load(name)
    assert validate_recipe(script) is script


def test_amazon_is_a_rich_multiprimitive_script() -> None:
    """The Amazon reference exercises fetch + paginate_facet + extract + parse_date
    + dedupe + the assert family + a facet_sum oracle — the multi-primitive shape."""
    script = _load("amazon_global.json")
    ops = [s["op"] for s in script["steps"]]
    assert "fetch" in ops
    assert "paginate_facet" in ops  # the NEW Amazon escape from the 10k hits cap
    assert "extract_json_path" in ops
    assert "assert_cap_not_hit" in ops
    assert script["oracle"]["kind"] == "facet_sum"
    assert script["oracle"]["single_valued"] is True


# --- the exclusions: click_sequence + browser transports --------------------

def test_click_sequence_op_is_rejected() -> None:
    script = _load("ycombinator.json")
    script["steps"].append({"op": "click_sequence", "selectors": ["a.next"]})
    with pytest.raises(RecipeError, match="click"):
        validate_recipe(script)


@pytest.mark.parametrize("bad_transport", ["page_fetch", "page_request", "dom", "browser_dom"])
def test_browser_transports_are_rejected(bad_transport: str) -> None:
    script = _load("janestreet.json")
    script["transport"] = bad_transport
    with pytest.raises(RecipeError, match="Phase 4"):
        validate_recipe(script)


@pytest.mark.parametrize("bad_op", ["page_fetch", "dom", "browser_dom", "page_request"])
def test_browser_ops_are_rejected(bad_op: str) -> None:
    script = _load("janestreet.json")
    script["steps"].append({"op": bad_op})
    with pytest.raises(RecipeError, match="Phase 4"):
        validate_recipe(script)


def test_paginate_cursor_is_rejected_as_unimplemented() -> None:
    """cursor pagination is NAMED in the shape but unimplemented — it must reject
    with a capability message, not crash the runner later (E7 3b review, Finding 2)."""
    script = _load("ycombinator.json")
    script["steps"].insert(
        1, {"op": "paginate_cursor", "cursor_path": "next", "param": "cursor", "max_pages": 5}
    )
    with pytest.raises(RecipeError, match="not implemented"):
        validate_recipe(script)


# --- validate-on-read: JSONB must not drift from company_scripts columns ------

def test_transport_column_mismatch_rejected_on_read() -> None:
    """The read path threads the stored ``transport`` column; a JSONB that
    disagrees is rejected (E7 3b review, Finding 3)."""
    script = _load("amazon_global.json")   # transport == 'http_json'
    with pytest.raises(RecipeError, match="company_scripts.transport"):
        validate_recipe(script, transport="http_html")


def test_oracle_kind_column_mismatch_rejected_on_read() -> None:
    script = _load("amazon_global.json")   # oracle.kind == 'facet_sum'
    with pytest.raises(RecipeError, match="company_scripts.oracle_kind"):
        validate_recipe(script, oracle_kind="header")


# --- malformed shapes -------------------------------------------------------

def test_wrong_version_rejected() -> None:
    script = _load("janestreet.json")
    script["script_version"] = 2
    with pytest.raises(RecipeError, match="script_version"):
        validate_recipe(script)


def test_non_https_fetch_url_rejected() -> None:
    script = _load("janestreet.json")
    script["steps"][0]["url"] = "http://insecure.example/main.json"
    with pytest.raises(RecipeError, match="https"):
        validate_recipe(script)


def test_missing_required_field_rejected() -> None:
    script = _load("janestreet.json")
    del script["steps"][1]["fields"]["id"]
    with pytest.raises(RecipeError, match="fields.id"):
        validate_recipe(script)


def test_unknown_key_in_step_rejected() -> None:
    script = _load("janestreet.json")
    script["steps"][0]["typo_key"] = "boom"
    with pytest.raises(RecipeError, match="unknown key"):
        validate_recipe(script)


def test_unknown_op_rejected() -> None:
    script = _load("janestreet.json")
    script["steps"].append({"op": "teleport"})
    with pytest.raises(RecipeError, match="closed vocabulary"):
        validate_recipe(script)


def test_two_pagination_steps_rejected() -> None:
    script = _load("amazon_global.json")
    script["steps"].append({"op": "paginate_offset", "param": "o", "page_size": 10, "max_pages": 5})
    with pytest.raises(RecipeError, match="at most one pagination"):
        validate_recipe(script)


def test_two_extraction_steps_rejected() -> None:
    script = _load("janestreet.json")
    script["steps"].append({"op": "extract_json_path", "records_path": "x",
                            "fields": {"id": "id", "title": "t", "url": "u"}})
    with pytest.raises(RecipeError, match="exactly one extraction"):
        validate_recipe(script)


def test_missing_fetch_rejected() -> None:
    script = _load("janestreet.json")
    script["steps"] = [s for s in script["steps"] if s["op"] != "fetch"]
    with pytest.raises(RecipeError, match="fetch"):
        validate_recipe(script)


def test_empty_steps_rejected() -> None:
    script = _load("janestreet.json")
    script["steps"] = []
    with pytest.raises(RecipeError, match="non-empty list"):
        validate_recipe(script)


def test_facet_sum_oracle_must_be_single_valued() -> None:
    script = _load("amazon_global.json")
    script["oracle"]["single_valued"] = False
    with pytest.raises(RecipeError, match="single_valued"):
        validate_recipe(script)


def test_unknown_oracle_kind_rejected() -> None:
    script = _load("janestreet.json")
    script["oracle"] = {"kind": "vibes"}
    with pytest.raises(RecipeError, match="oracle.kind"):
        validate_recipe(script)


# --- validate-on-read: transport / oracle_kind column agreement -------------

def test_transport_column_mismatch_rejected() -> None:
    script = _load("janestreet.json")  # transport http_json
    with pytest.raises(RecipeError, match="company_scripts.transport"):
        validate_recipe(script, transport="http_html")


def test_oracle_kind_column_mismatch_rejected() -> None:
    script = _load("amazon_global.json")  # oracle facet_sum
    with pytest.raises(RecipeError, match="company_scripts.oracle_kind"):
        validate_recipe(script, oracle_kind="header")


def test_columns_matching_pass() -> None:
    script = _load("amazon_global.json")
    assert validate_recipe(script, transport="http_json", oracle_kind="facet_sum") is script


def test_validate_on_read_rejects_a_drifted_stored_script() -> None:
    """A stored script mutated to an invalid shape must be rejected before the
    runner touches it (company_scripts.script is data that drifts)."""
    script = _load("amazon_global.json")
    stored = copy.deepcopy(script)
    stored["steps"][0]["url"] = "ftp://evil/exfil"  # tampered on disk
    with pytest.raises(RecipeError):
        validate_recipe(stored)


# --- E7 Phase 3c: the browser_fetch transport + origin_url -------------------

def test_browser_fetch_script_validates() -> None:
    """The real TikTok capture shape: the SAME steps grammar http_json uses, plus
    origin_url — no new op, no new extraction kind."""
    script = _load("tiktok_browser_fetch.json")
    assert validate_recipe(script) is script
    assert script["transport"] == "browser_fetch"
    assert script["origin_url"].startswith("https://")
    ops = [s["op"] for s in script["steps"]]
    assert ops[0] == "fetch"
    assert "paginate_offset" in ops and "extract_json_path" in ops


def test_browser_fetch_columns_matching_pass() -> None:
    """validate-on-read with the company_scripts columns (invariant 5)."""
    script = _load("tiktok_browser_fetch.json")
    assert validate_recipe(
        script, transport="browser_fetch", oracle_kind="declared_probed"
    ) is script


def test_browser_fetch_transport_column_mismatch_rejected() -> None:
    script = _load("tiktok_browser_fetch.json")
    with pytest.raises(RecipeError, match="company_scripts.transport"):
        validate_recipe(script, transport="http_json")


def test_browser_fetch_without_origin_url_rejected() -> None:
    """No origin means nothing to navigate to — the executor could not run it."""
    script = _load("tiktok_browser_fetch.json")
    del script["origin_url"]
    with pytest.raises(RecipeError, match="origin_url is required"):
        validate_recipe(script)


def test_browser_fetch_non_https_origin_url_rejected() -> None:
    script = _load("tiktok_browser_fetch.json")
    script["origin_url"] = "http://lifeattiktok.com/"
    with pytest.raises(RecipeError, match="origin_url must be an https"):
        validate_recipe(script)


def test_browser_fetch_empty_origin_url_rejected() -> None:
    script = _load("tiktok_browser_fetch.json")
    script["origin_url"] = ""
    with pytest.raises(RecipeError, match="origin_url"):
        validate_recipe(script)


@pytest.mark.parametrize("name", ["janestreet.json", "ycombinator.json"])
def test_origin_url_on_an_http_transport_rejected(name: str) -> None:
    """An origin_url on http_json/http_html means the author mislabelled the
    transport; silently ignoring it would store a board that never gets its origin."""
    script = _load(name)
    script["origin_url"] = "https://careers.example/"
    with pytest.raises(RecipeError, match="only valid for transport 'browser_fetch'"):
        validate_recipe(script)


def test_browser_fetch_html_extraction_rejected() -> None:
    """The subprocess returns raw JSON bodies — there is no markup for extract_css
    to read, so the pairing must fail at write time, not at 3am."""
    script = _load("tiktok_browser_fetch.json")
    script["steps"] = [
        s for s in script["steps"] if s["op"] != "extract_json_path"
    ] + [{"op": "extract_css", "record_selector": ".job",
          "field_selectors": {"id": "@data-id", "title": ".t", "url": "a@href"}}]
    with pytest.raises(RecipeError, match="extract_json_path"):
        validate_recipe(script)


def test_browser_fetch_facet_pagination_rejected() -> None:
    script = _load("tiktok_browser_fetch.json")
    script["steps"] = [s for s in script["steps"] if s["op"] != "paginate_offset"]
    script["steps"].insert(1, {
        "op": "paginate_facet", "facet_param": "dept", "facet_values": ["eng"],
        "page_size": 10, "max_pages_per_facet": 2,
    })
    with pytest.raises(RecipeError, match="paginate_facet"):
        validate_recipe(script)


def test_browser_fetch_page_budget_over_the_tier_ceiling_is_rejected() -> None:
    """The stored harvest budget is DERIVED per board now, so it can be large — and
    ``browser_fetch`` cannot honour large. Rejecting it in the SCHEMA (write AND read)
    rather than leaving it to the parent's ``min(max_pages, ceiling)`` clamp is the
    load-bearing part: a clamped sweep still reports a terminus, so a silently
    truncated browser harvest looks exactly like a finished one — which is how a
    partial board gets certified and the rest of it closed."""
    script = _load("tiktok_browser_fetch.json")
    (paginate,) = [s for s in script["steps"] if s["op"] == "paginate_offset"]
    paginate["max_pages"] = BROWSER_FETCH_MAX_PAGES + 1
    with pytest.raises(RecipeError, match="at most 25 pages"):
        validate_recipe(script)

    paginate["max_pages"] = BROWSER_FETCH_MAX_PAGES
    validate_recipe(script)                       # exactly at the ceiling is fine

    # ...and the SAME budget on the http tier is not the schema's business: 100 pages
    # of httpx is ~60s, which is what the tiers differ on.
    http = _load("janestreet.json")
    http["steps"].insert(1, {
        "op": "paginate_offset", "param": "offset", "page_size": 100, "max_pages": 100,
    })
    validate_recipe(http)


def test_browser_fetch_does_not_open_the_phase4_door() -> None:
    """Adding browser_fetch must not admit the drive-the-DOM capabilities next to
    it: the page_*/dom transports and click_sequence stay rejected."""
    for bad_transport in ("page_fetch", "page_request", "dom", "browser_dom"):
        script = _load("tiktok_browser_fetch.json")
        script["transport"] = bad_transport
        with pytest.raises(RecipeError, match="Phase 4"):
            validate_recipe(script)
    script = _load("tiktok_browser_fetch.json")
    script["steps"].append({"op": "click_sequence", "selectors": ["a.next"]})
    with pytest.raises(RecipeError, match="Phase 4"):
        validate_recipe(script)


# --- the records_path wildcard (the whole-board path on a grouped payload) ---

def test_the_wildcard_records_path_is_the_union_of_every_group() -> None:
    """``*.postings`` reads all 14 of binance's department groups, not one of them.

    THE MEASURED PARTIAL READ this segment exists for: the whole board was already in
    the captured response, and every concrete path into it — ``4.postings`` — is one
    department. Both halves are asserted here, because the value of the union is exactly
    the difference between them."""
    payload = [
        {"title": "Eng", "postings": [{"id": "a"}, {"id": "b"}]},
        {"title": "Ops", "postings": [{"id": "c"}]},
        {"title": "Empty", "postings": []},
    ]
    assert dig_records(payload, "0.postings") == [{"id": "a"}, {"id": "b"}]
    assert dig_records(payload, "*.postings") == [{"id": "a"}, {"id": "b"}, {"id": "c"}]

    # ...and with a head in front of the wildcard, and a tail behind it.
    nested = {"data": {"groups": [
        {"bucket": {"jobs": [{"id": "a"}]}},
        {"bucket": {"jobs": [{"id": "b"}]}},
    ]}}
    assert dig_records(nested, "data.groups.*.bucket.jobs") == [{"id": "a"}, {"id": "b"}]


def test_the_wildcard_also_unwraps_one_record_per_element() -> None:
    """The PER-ELEMENT WRAPPER, which is a whole ATS family rather than one board.

    Elasticsearch answers ``hits.hits: [{_index, _id, _score, _source: {...}, sort}]``
    and Relay answers ``edges: [{cursor, node: {...}}]`` — the job is one level INSIDE
    each element, so the tail resolves to a dict per element instead of to a list.
    Measured on ``www-api.ibm.com/search/api/v2``: ``hits.total.value = 1806``, 30
    records at ``hits.hits[]._source``, and not one concrete path in the payload can
    name them.
    """
    elastic = {"hits": {"total": {"value": 1806}, "hits": [
        {"_index": "careers", "_id": "1", "_score": 1.0,
         "_source": {"title": "SRE", "url": "https://x/1"}, "sort": [1]},
        {"_index": "careers", "_id": "2", "_score": 1.0,
         "_source": {"title": "PM", "url": "https://x/2"}, "sort": [2]},
    ]}}
    assert dig_records(elastic, "hits.hits.*._source") == [
        {"title": "SRE", "url": "https://x/1"},
        {"title": "PM", "url": "https://x/2"},
    ]

    relay = {"data": {"jobs": {"edges": [
        {"cursor": "a", "node": {"id": "1", "title": "SRE"}},
        {"cursor": "b", "node": {"id": "2", "title": "PM"}},
    ]}}}
    assert dig_records(relay, "data.jobs.edges.*.node") == [
        {"id": "1", "title": "SRE"}, {"id": "2", "title": "PM"},
    ]


def test_the_two_wildcard_shapes_can_be_mixed_in_one_payload() -> None:
    """A list tail concatenates, a dict tail is one record. Both, same wildcard, and
    neither shape may quietly eat the other: a scalar tail is still nothing."""
    payload = [
        {"postings": [{"id": "a"}, {"id": "b"}], "node": {"id": "n1"}, "n": 3},
        {"postings": [{"id": "c"}], "node": {"id": "n2"}, "n": 4},
    ]
    assert dig_records(payload, "*.postings") == [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    assert dig_records(payload, "*.node") == [{"id": "n1"}, {"id": "n2"}]
    assert dig_records(payload, "*.n") == []


def test_a_group_that_does_not_carry_the_array_is_skipped_not_fatal() -> None:
    """A grouped board legitimately ships one shapeless group beside a dozen good ones;
    refusing the whole board over it would be the wrong trade. Emptiness is still caught
    — by the callers' own non-empty check, which is the RAISES-never-empty contract."""
    payload = [{"postings": [{"id": "a"}]}, {"title": "no postings key"}, "not an object"]
    assert dig_records(payload, "*.postings") == [{"id": "a"}]
    assert dig_records([{"title": "x"}], "*.postings") == []


def test_a_wildcard_over_something_that_is_not_a_list_raises() -> None:
    with pytest.raises(RecipeError, match="not a list to iterate"):
        dig_records({"groups": {"a": 1}}, "groups.*.jobs")


def test_dig_records_leaves_a_plain_path_to_dig() -> None:
    """No wildcard, no new behaviour. Every board that works today now resolves its
    records through this function, so the un-wildcarded path has to stay byte-identical
    — including the failure message a drifted stored row depends on."""
    payload = {"data": {"jobs": [{"id": "a"}]}, "hits": 3}
    assert dig_records(payload, "data.jobs") == [{"id": "a"}]
    assert dig_records(payload, "hits") == 3
    assert dig_records(payload, "") is payload
    with pytest.raises(RecipeError, match="missing key"):
        dig_records(payload, "data.nope")


@pytest.mark.parametrize(
    "bad_path, message",
    [
        ("*.groups.*.jobs", "at most one"),
        ("groups.*", "names no records"),      # trailing wildcard names no key
        ("*", "names no records"),
    ],
)
def test_an_unrunnable_wildcard_path_is_rejected_on_write_and_on_read(
    bad_path: str, message: str
) -> None:
    """A second ``*`` is an unbounded cross-product over a payload a stranger's board
    authored, and a trailing one names no records at all. Both are rejected where every
    other unrunnable recipe is — in the validator, which runs on write AND on every
    nightly read of a stored row."""
    script = _load("janestreet.json")
    (extract,) = [s for s in script["steps"] if s["op"] == "extract_json_path"]
    extract["records_path"] = bad_path
    with pytest.raises(RecipeError, match=message):
        validate_recipe(script)

    extract["records_path"] = "*.postings"     # ...and one wildcard is accepted
    validate_recipe(script)


# --- unit 7: the canonical optional set carries ``description`` ---

def test_the_canonical_optional_fields_are_the_set_discovery_can_emit() -> None:
    """Documentation with a job: the discovery author's structured output is a CLOSED
    object over exactly these names, because Anthropic strict mode forbids dynamic keys.

    ``description`` has exactly one reader and that reader is not optional: it is what
    the enrichment claim reads (``DESCRIPTION_SQL`` COALESCEs over
    ``details->>'description'``). Dropping it from the tuple fails here."""
    assert CANONICAL_REQUIRED_FIELDS == ("id", "title", "url")
    assert "description" in CANONICAL_OPTIONAL_FIELDS
    assert "department" not in CANONICAL_OPTIONAL_FIELDS


def test_a_recipe_captured_under_any_older_field_set_still_validates() -> None:
    """The stored recipes were captured under several different field sets — including
    ones carrying ``department``, a field the capture schema no longer emits.
    ``_v_fields`` requires the mandatory three and constrains nothing else on purpose —
    a read-path check over possibly-drifted stored data — so moving the capture set must
    never turn a recipe already in the database into a nightly RecipeError, in either
    direction."""
    script = _load("janestreet.json")
    (extract,) = [s for s in script["steps"] if s["op"] == "extract_json_path"]
    extract["fields"]["department"] = "category"
    assert validate_recipe(script) is script

    del extract["fields"]["department"]
    extract["fields"]["description"] = "overview"
    assert validate_recipe(script) is script

    extract["fields"]["department"] = "category"
    assert validate_recipe(script) is script


# --- the http_html landmine -------------------------------------------------

def test_an_html_recipe_may_not_claim_to_paginate() -> None:
    """THE LANDMINE, and it is worth a test even though nothing emits it today.

    ``recipe_runner._run_http_html`` does not paginate: it issues ONE request and
    hardcodes ``pages_fetched=1, cap_hit=False, terminated_cleanly=True`` — i.e. it
    reports a page-one-only read as a clean, complete sweep. A stored html recipe
    carrying a paginate step would validate; the runner would ignore the step; the
    completeness gate would read "terminated cleanly, no cap" as self-consistent and
    VERIFY it; and a VERIFIED harvest is allowed to close. Every job past page one would
    be closed, every night, by a recipe that looks like it paginates.

    Discovery emits no ``http_html``, which is exactly why the rule belongs in the schema
    rather than in somebody's memory."""
    script = _load("ycombinator.json")
    assert script["transport"] == "http_html"
    script["steps"].insert(
        1, {"op": "paginate_page", "param": "page", "page_size": 50, "max_pages": 10}
    )
    with pytest.raises(RecipeError, match="does not paginate"):
        validate_recipe(script)


def test_an_html_recipe_without_pagination_is_untouched() -> None:
    """The rule may only ever refuse the pairing. A one-request html recipe is exactly
    as storable as it was."""
    script = _load("ycombinator.json")
    assert validate_recipe(script) is script


def test_the_html_pagination_rule_is_re_asserted_on_every_read() -> None:
    """validate-on-READ is the half that matters for a landmine: the recipe that trips
    this will be a JSONB row somebody edited, not one discovery wrote."""
    script = _load("ycombinator.json")
    script["steps"].insert(
        1, {"op": "paginate_offset", "param": "start", "page_size": 50, "max_pages": 4}
    )
    with pytest.raises(RecipeError, match="does not paginate"):
        validate_recipe(script, transport="http_html", oracle_kind=script["oracle"]["kind"])
