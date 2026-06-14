"""Pure scoring for the location-normalization golden-set eval.

NO I/O, NO network, NO ``anthropic`` import — stdlib only, so
``tests/test_eval_scoring.py`` runs in the normal backend pytest suite without an
API key or network. The runner (``eval_locations.py``) converts each
``CanonicalLocation`` the live model produces into a plain dict before handing it
here.

Match rule (chosen): **structured fields only**. The compared tuple per location
is ``(kind, city, region, country, remote_scope)``; ``canonical_name`` and
``confidence`` are NOT part of the match. A case PASSES iff the **multiset** of
normalized produced tuples equals the multiset of expected tuples (so
multi-location order does not affect pass/fail).
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

# Mirror tasks/normalize_location.py:CONFIDENCE_FLOOR — results below this would be
# dropped as 'failed' by the real task, so flag them even when fields match.
CONFIDENCE_FLOOR = 0.5

# Obvious country-level equivalences. Expected labels use short codes; this only
# bridges representations a correct model might legitimately vary on (e.g. the
# model returns "USA" where the label says "US"). Keep small and documented — not
# clever. Sub-national region full-names are intentionally NOT aliased: the prompt
# promises short codes, so a full "California" in `region` is signal worth surfacing.
_COUNTRY_ALIASES = {
    "USA": "US",
    "U.S.": "US",
    "U.S.A.": "US",
    "UNITED STATES": "US",
    "UNITED STATES OF AMERICA": "US",
    "AMERICA": "US",
    "UK": "GB",
    "GBR": "GB",
    "UNITED KINGDOM": "GB",
    "GREAT BRITAIN": "GB",
}

_WS = re.compile(r"\s+")


def _get(loc: Any, key: str) -> Any:
    """Field access that works on both dicts and CanonicalLocation-like objects."""
    if isinstance(loc, dict):
        return loc.get(key)
    return getattr(loc, key, None)


def _norm_lower(v: Any) -> str | None:
    if v is None:
        return None
    s = _WS.sub(" ", str(v)).strip().lower()
    return s or None


def _norm_code(v: Any, *, aliases: dict[str, str] | None = None) -> str | None:
    if v is None:
        return None
    s = _WS.sub(" ", str(v)).strip().upper()
    if not s:
        return None
    return aliases.get(s, s) if aliases else s


def normalize_fields(loc: Any) -> tuple:
    """Project one location (dict or object) to its comparison tuple."""
    return (
        _norm_lower(_get(loc, "kind")),
        _norm_lower(_get(loc, "city")),
        _norm_code(_get(loc, "region")),
        _norm_code(_get(loc, "country"), aliases=_COUNTRY_ALIASES),
        _norm_lower(_get(loc, "remote_scope")),
    )


def _multiset(locs: list[Any]) -> Counter:
    return Counter(normalize_fields(loc) for loc in locs)


def compare_case(expected: list[Any], produced: list[Any]) -> dict:
    """Order-independent multiset comparison of structured fields."""
    exp, prod = _multiset(expected), _multiset(produced)
    primary_match: bool | None = None
    if expected and produced:
        primary_match = normalize_fields(produced[0]) == normalize_fields(expected[0])
    return {
        "passed": exp == prod,
        "primary_match": primary_match,
        # tuples present in expected but not produced, and vice-versa (for reports)
        "missing": [list(t) for t in (exp - prod).elements()],
        "extra": [list(t) for t in (prod - exp).elements()],
    }


def max_confidence(produced: list[Any] | None) -> float | None:
    confs = [_get(loc, "confidence") for loc in (produced or [])]
    confs = [c for c in confs if c is not None]
    return max(confs) if confs else None


def score_case(case: dict, produced: list[Any] | None, error: str | None = None) -> dict:
    """Combine one golden case + the model's output (or an error) into a result.

    ``error`` is a classified string like ``"LocationLLMError: ..."`` or
    ``"APIError: ..."`` (the runner sets the prefix); a gating case with an error
    counts as a FAIL.
    """
    gating = case.get("gating", True)
    result: dict[str, Any] = {
        "id": case.get("id"),
        "raw": case.get("raw"),
        "category": case.get("category") or "uncategorized",
        "gating": gating,
        "expected": case.get("expected", []),
        "produced": produced,
        "error": error,
    }
    if error is not None:
        result.update(
            verdict="error", passed=False, primary_match=None,
            missing=[], extra=[], max_confidence=None, below_floor=False,
        )
        return result
    cmp = compare_case(case.get("expected", []), produced or [])
    mc = max_confidence(produced)
    result.update(
        verdict="pass" if cmp["passed"] else "fail",
        passed=cmp["passed"],
        primary_match=cmp["primary_match"],
        missing=cmp["missing"],
        extra=cmp["extra"],
        max_confidence=mc,
        below_floor=(mc is not None and mc < CONFIDENCE_FLOOR),
    )
    return result


def find_regressions(current: list[dict], baseline: list[dict]) -> list[str]:
    """Gating case ids that PASSED in the saved baseline but do NOT pass now.

    Only GATING cases count: non-gating cases are informational and inherently
    flaky under LLM nondeterminism, so a non-gating flip is not a regression.
    """
    base_passed = {r["id"] for r in baseline if r.get("passed")}
    now_by_id = {r["id"]: r for r in current}
    return sorted(
        cid for cid in base_passed
        if cid in now_by_id
        and now_by_id[cid].get("gating", True)
        and not now_by_id[cid].get("passed")
    )


def summarize(results: list[dict]) -> dict:
    """Aggregate per-case results into the run summary (the headline numbers)."""
    gating = [r for r in results if r.get("gating")]
    gating_pass = sum(1 for r in gating if r.get("passed"))
    gating_total = len(gating)

    by_category: dict[str, dict[str, int]] = {}
    for r in gating:
        cat = r.get("category") or "uncategorized"
        bucket = by_category.setdefault(cat, {"pass": 0, "total": 0})
        bucket["total"] += 1
        if r.get("passed"):
            bucket["pass"] += 1

    def _err_count(*needles: str) -> int:
        return sum(
            1 for r in results
            if r.get("error") and any(n in r["error"] for n in needles)
        )

    return {
        "total_cases": len(results),
        "gating_total": gating_total,
        "informational_total": len(results) - gating_total,
        "gating_pass": gating_pass,
        "gating_fail": gating_total - gating_pass,
        "gating_accuracy": (gating_pass / gating_total) if gating_total else None,
        "primary_mismatches": sum(1 for r in results if r.get("primary_match") is False),
        "below_confidence_floor": sum(1 for r in results if r.get("below_floor")),
        "llm_errors": _err_count("LocationLLMError"),
        "api_errors": _err_count("APIError", "APITimeout"),
        "by_category": by_category,
    }
