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

from api.services.recipe_schema import RecipeError, validate_recipe

_FIXTURES = Path(__file__).parent / "fixtures" / "recipes"


def _load(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text())


# --- valid multi-primitive scripts round-trip -------------------------------

@pytest.mark.parametrize(
    "name", ["amazon_global.json", "meta.json", "ycombinator.json", "janestreet.json"]
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
