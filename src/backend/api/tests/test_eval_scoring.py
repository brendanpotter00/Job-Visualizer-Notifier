"""Unit tests for the PURE location-eval scorer (api/eval/scoring.py).

Runs in the normal backend suite: no API key, no network, no anthropic import.
"""

from __future__ import annotations

from api.eval.scoring import (
    CONFIDENCE_FLOOR,
    compare_case,
    find_regressions,
    normalize_fields,
    score_case,
    summarize,
)


def _loc(kind, city=None, region=None, country=None, remote_scope=None, confidence=0.9):
    return {
        "canonical_name": "x", "kind": kind, "city": city, "region": region,
        "country": country, "remote_scope": remote_scope, "confidence": confidence,
    }


# ---- normalize_fields -------------------------------------------------------

def test_normalize_fields_lowercases_city_uppercases_codes():
    t = normalize_fields(_loc("city", city="  San   Francisco ", region="ca", country="us"))
    assert t == ("city", "san francisco", "CA", "US", None)


def test_usa_aliases_to_us():
    assert normalize_fields(_loc("city", country="USA"))[3] == "US"
    assert normalize_fields(_loc("city", country="United States of America"))[3] == "US"
    assert normalize_fields(_loc("country", country="United Kingdom"))[3] == "GB"


def test_region_full_name_is_not_aliased():
    # short codes are promised; a full "California" stays distinct from "CA" — signal.
    assert normalize_fields(_loc("region", region="California"))[2] == "CALIFORNIA"
    assert normalize_fields(_loc("region", region="CA"))[2] == "CA"


def test_remote_scope_geography_is_compared():
    # the schema fix: region/country-scoped remotes are distinguished.
    az = normalize_fields(_loc("remote", region="AZ", country="US", remote_scope="us"))
    generic = normalize_fields(_loc("remote", country="US", remote_scope="us"))
    assert az != generic


# ---- compare_case -----------------------------------------------------------

def test_exact_single_match_passes():
    exp = [_loc("city", city="Austin", region="TX", country="US")]
    prod = [_loc("city", city="austin", region="tx", country="usa")]
    assert compare_case(exp, prod)["passed"] is True


def test_multi_location_order_independent():
    a = _loc("city", city="Sunnyvale", region="CA", country="US")
    b = _loc("city", city="Kirkland", region="WA", country="US")
    assert compare_case([a, b], [b, a])["passed"] is True


def test_mismatch_fails_and_reports_diff():
    exp = [_loc("city", city="Austin", region="TX", country="US")]
    prod = [_loc("city", city="Dallas", region="TX", country="US")]
    res = compare_case(exp, prod)
    assert res["passed"] is False
    assert res["missing"] and res["extra"]


def test_primary_mismatch_when_first_differs_even_if_set_equal():
    a = _loc("city", city="Sunnyvale", region="CA", country="US")
    b = _loc("city", city="Kirkland", region="WA", country="US")
    res = compare_case([a, b], [b, a])  # same set, swapped primary
    assert res["passed"] is True
    assert res["primary_match"] is False


def test_count_sensitive_multiset():
    a = _loc("city", city="NYC", region="NY", country="US")
    assert compare_case([a], [a, a])["passed"] is False  # duplicate produced


# ---- score_case / confidence floor -----------------------------------------

def test_score_case_below_floor_flagged():
    case = {"id": "c1", "raw": "Various", "expected": [_loc("country", country="US")]}
    prod = [_loc("country", country="US", confidence=CONFIDENCE_FLOOR - 0.1)]
    r = score_case(case, prod)
    assert r["below_floor"] is True
    assert r["max_confidence"] == CONFIDENCE_FLOOR - 0.1


def test_score_case_at_floor_not_flagged():
    case = {"id": "c2", "raw": "X", "expected": [_loc("country", country="US")]}
    r = score_case(case, [_loc("country", country="US", confidence=CONFIDENCE_FLOOR)])
    assert r["below_floor"] is False


def test_score_case_gating_error_is_fail():
    case = {"id": "e1", "raw": "boom", "gating": True, "expected": [_loc("city", city="X")]}
    r = score_case(case, None, error="LocationLLMError: unparseable")
    assert r["verdict"] == "error"
    assert r["passed"] is False


# ---- regressions + summarize ------------------------------------------------

def test_find_regressions_only_pass_to_fail():
    baseline = [{"id": "a", "passed": True}, {"id": "b", "passed": True}, {"id": "c", "passed": False}]
    current = [{"id": "a", "passed": True}, {"id": "b", "passed": False}, {"id": "c", "passed": True}]
    assert find_regressions(current, baseline) == ["b"]  # c improving is not a regression


def test_find_regressions_ignores_non_gating_flips():
    # a non-gating case that passed then fails is informational noise, not a regression.
    baseline = [{"id": "g", "passed": True}, {"id": "n", "passed": True}]
    current = [
        {"id": "g", "passed": False, "gating": True},
        {"id": "n", "passed": False, "gating": False},
    ]
    assert find_regressions(current, baseline) == ["g"]


def test_summarize_headline_and_categories():
    results = [
        score_case({"id": "1", "category": "city", "expected": [_loc("city", city="A")]},
                   [_loc("city", city="A")]),
        score_case({"id": "2", "category": "city", "expected": [_loc("city", city="B")]},
                   [_loc("city", city="WRONG")]),
        score_case({"id": "3", "category": "remote", "gating": False,
                    "expected": [_loc("remote", remote_scope="us")]},
                   [_loc("remote", remote_scope="us")]),
    ]
    s = summarize(results)
    assert s["gating_total"] == 2  # case 3 is informational
    assert s["gating_pass"] == 1
    assert s["gating_accuracy"] == 0.5
    assert s["by_category"]["city"] == {"pass": 1, "total": 2}
    assert "remote" not in s["by_category"]  # non-gating excluded from category accuracy
