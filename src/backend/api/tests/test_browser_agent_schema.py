"""E7 Stagehand pivot — the browser-agent artifact schema validator. $0, pure.

Locks the write+read shape check for a ``transport='browser_agent'`` artifact:
``max_pages ≤ 3`` (the bound, §4), a required ``id_field`` (the crux, §3.4), and the
``self_consistent``-only oracle (a rendered page proves no trusted total).
"""

from __future__ import annotations

import copy

import pytest

from api.services.browser_agent.schema import (
    BROWSER_AGENT_SCRIPT_VERSION,
    MAX_PAGES_CAP,
    BrowserAgentScriptError,
    effective_max_pages,
    validate_browser_agent_script,
)


def _valid() -> dict:
    return {
        "script_version": 2,
        "transport": "browser_agent",
        "entry_url": "https://www.ycombinator.com/companies/raindrop/jobs",
        "extract": {
            "instruction": "extract every job posting: title, location, detail url",
            "schema": {"type": "object", "properties": {"jobs": {"type": "array"}}},
        },
        "pagination": {"next_action": "click next", "max_pages": 3},
        "id_field": "url",
        "expected_min_jobs": 1,
        "oracle": {"kind": "self_consistent"},
        "discovered_at": "2026-08-09T00:00:00Z",
        "discovered_by": "stagehand/claude-sonnet-4-5",
    }


def test_valid_artifact_passes_and_echoes() -> None:
    script = _valid()
    assert validate_browser_agent_script(script) is script


def test_valid_artifact_passes_with_matching_columns() -> None:
    validate_browser_agent_script(
        _valid(), transport="browser_agent", oracle_kind="self_consistent"
    )


def test_single_page_artifact_without_pagination_is_valid() -> None:
    script = _valid()
    del script["pagination"]
    validate_browser_agent_script(script)
    assert effective_max_pages(script) == 1


# --- the three required rejections (§8) --------------------------------------

def test_rejects_max_pages_over_cap() -> None:
    script = _valid()
    script["pagination"]["max_pages"] = MAX_PAGES_CAP + 1  # 4 — over the hard cap
    with pytest.raises(BrowserAgentScriptError, match="exceeds the hard cap"):
        validate_browser_agent_script(script)


def test_rejects_missing_id_field() -> None:
    script = _valid()
    del script["id_field"]
    with pytest.raises(BrowserAgentScriptError, match="id_field"):
        validate_browser_agent_script(script)


def test_accepts_title_and_composite_id_fields() -> None:
    for id_field in ("url", "title", "title|location"):
        script = _valid()
        script["id_field"] = id_field
        validate_browser_agent_script(script)


def test_rejects_unknown_id_field_value() -> None:
    script = _valid()
    script["id_field"] = "department"   # not in the closed set
    with pytest.raises(BrowserAgentScriptError, match="id_field must be one of"):
        validate_browser_agent_script(script)


def test_rejects_wrong_oracle() -> None:
    script = _valid()
    script["oracle"] = {"kind": "declared_probed"}  # not allowed for a browser agent
    with pytest.raises(BrowserAgentScriptError, match="oracle.kind"):
        validate_browser_agent_script(script)


# --- other shape checks ------------------------------------------------------

def test_rejects_wrong_script_version() -> None:
    script = _valid()
    script["script_version"] = 1
    with pytest.raises(BrowserAgentScriptError, match="script_version"):
        validate_browser_agent_script(script)


def test_rejects_non_browser_agent_transport() -> None:
    script = _valid()
    script["transport"] = "http_json"
    with pytest.raises(BrowserAgentScriptError, match="transport"):
        validate_browser_agent_script(script)


def test_rejects_transport_column_drift() -> None:
    with pytest.raises(BrowserAgentScriptError, match="!= company_scripts.transport"):
        validate_browser_agent_script(_valid(), transport="http_json")


def test_rejects_oracle_column_drift() -> None:
    with pytest.raises(BrowserAgentScriptError, match="!= company_scripts.oracle_kind"):
        validate_browser_agent_script(_valid(), oracle_kind="facet_sum")


def test_rejects_non_https_entry_url() -> None:
    script = _valid()
    script["entry_url"] = "http://insecure.example/jobs"
    with pytest.raises(BrowserAgentScriptError, match="entry_url"):
        validate_browser_agent_script(script)


def test_rejects_extract_missing_schema() -> None:
    script = _valid()
    del script["extract"]["schema"]
    with pytest.raises(BrowserAgentScriptError, match="extract.schema"):
        validate_browser_agent_script(script)


def test_rejects_unknown_top_level_key() -> None:
    script = _valid()
    script["sneaky"] = True
    with pytest.raises(BrowserAgentScriptError, match="unknown key"):
        validate_browser_agent_script(script)


def test_rejects_non_positive_expected_min_jobs() -> None:
    script = _valid()
    script["expected_min_jobs"] = 0
    with pytest.raises(BrowserAgentScriptError, match="expected_min_jobs"):
        validate_browser_agent_script(script)


# --- effective_max_pages clamps to the hard cap ------------------------------

def test_effective_max_pages_clamps_and_defaults() -> None:
    single = _valid()
    del single["pagination"]
    assert effective_max_pages(single) == 1

    two = _valid()
    two["pagination"]["max_pages"] = 2
    assert effective_max_pages(two) == 2

    # A drifted stored value past the cap is still clamped on read (belt to the
    # write-time rejection).
    drifted = copy.deepcopy(_valid())
    drifted["pagination"]["max_pages"] = 99
    assert effective_max_pages(drifted) == MAX_PAGES_CAP


def test_script_version_constant_is_two() -> None:
    assert BROWSER_AGENT_SCRIPT_VERSION == 2
