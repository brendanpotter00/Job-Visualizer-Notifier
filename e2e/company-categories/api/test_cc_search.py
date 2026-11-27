"""CC-01..CC-05 — `GET /api/jobs/search?company_category=...`.

The failure this section exists for is SILENT: a filter that is dropped
somewhere (the proxy, the router, a truthiness check on an empty membership)
comes back as an ordinary UNFILTERED 200. So every case asserts an EXACT set
over nine seeded rows, and every case has a decoy: `CC-DECOY`, a SWE job at a
company in no company type, must never come back under any type.
"""

from __future__ import annotations

from conftest import dump_json, fixtures, result_keys, search, search_raw


def test_cc01_one_type_returns_members_only(http, case_dir):
    body = search(http, company_category="big_tech", limit=100)
    dump_json(case_dir / "big_tech.json", body)
    got = result_keys(body)
    expected = fixtures.expected_for(["big_tech"])
    assert expected == fixtures.keys(
        "CC-GOOGLE", "CC-APPLE", "CC-MICROSOFT", "CC-NETFLIX", "CC-ANTHROPIC", "CC-GOOGLE-PM"
    )
    assert got == expected, f"?company_category=big_tech returned {sorted(got)}, expected {sorted(expected)}"
    assert "CC-DECOY" not in got
    # The mirror: unfiltered, the decoy IS there, so its absence above is the filter.
    assert result_keys(search(http, limit=100)) == fixtures.ALL_KEYS


def test_cc02_two_types_or(http):
    got = result_keys(search(http, company_category=["ai_labs", "fintech"], limit=100))
    expected = fixtures.expected_for(["ai_labs", "fintech"])
    assert expected == fixtures.keys("CC-GOOGLE", "CC-GOOGLE-PM", "CC-ANTHROPIC", "CC-STRIPE", "CC-RAMP")
    assert got == expected, (
        f"?company_category=ai_labs&company_category=fintech returned {sorted(got)}, expected "
        f"{sorted(expected)} (ANY of the types)"
    )


def test_cc03_ands_with_category_and_level(http):
    got = result_keys(
        search(
            http,
            company_category="big_tech",
            category=fixtures.SWE,
            level="senior",
            limit=100,
        )
    )
    expected = fixtures.expected_for(["big_tech"], category=[fixtures.SWE], level=["senior"])
    assert expected == fixtures.keys("CC-GOOGLE", "CC-APPLE", "CC-NETFLIX", "CC-ANTHROPIC")
    assert got == expected, (
        f"big_tech + software_engineering + senior returned {sorted(got)}, expected {sorted(expected)}. "
        "CC-MICROSOFT (mid) and CC-GOOGLE-PM (product manager) are the AND decoys; "
        "CC-STRIPE (senior SWE, not Big Tech) is the company-type decoy"
    )


def test_cc04_an_unknown_type_returns_nothing_not_everything(http):
    body = search(http, company_category="not_a_type", limit=100)
    assert body["jobs"] == [], (
        f"an unknown company type returned {sorted(result_keys(body))}; it must match nothing. "
        "Returning rows means an empty membership was read as 'no filter'"
    )
    # A malformed slug is a 422, never a silent widen.
    bad = search_raw(http, company_category="Big Tech", limit=100)
    assert bad.status_code == 422, f"a malformed company type answered {bad.status_code}: {bad.text[:300]}"


def test_cc05_a_keyset_walk_over_one_type_is_complete(http, case_dir):
    expected = fixtures.expected_for(["big_tech"])
    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        body = search(http, company_category="big_tech", limit=2, cursor=cursor)
        pages += 1
        seen.extend(job["id"] for job in body["jobs"])
        dump_json(case_dir / f"page-{pages}.json", body)
        cursor = body.get("nextCursor")
        if not cursor:
            break
        assert pages < 10, "the walk did not end"
    assert pages >= 3, f"a 2-per-page walk over {len(expected)} rows took only {pages} page(s)"
    assert len(seen) == len(set(seen)), f"the walk returned a row twice: {seen}"
    assert set(seen) == expected, f"the walk returned {sorted(seen)}, expected {sorted(expected)}"
