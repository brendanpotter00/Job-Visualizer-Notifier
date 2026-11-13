"""SC-01 — selecting the PARENT category must not narrow to labelled rows.

The regression this exists for is the easy one to ship: a subcategory column
arrives, somebody adds it to the category predicate "for consistency", and
`?category=software_engineering` quietly stops returning the 65% of SWE rows
nobody has labelled yet. The user's own words for this case were "selecting
Software Engineering returns jobs across ALL its subcategories" — including the
ones that have none.

The two rows that carry the case are `J-NULL` (never evaluated) and `J-EMPTY`
(evaluated, no specialty applies). Both MUST be in a parent-category result and
both MUST be absent the moment a subcategory filter is active — which is SC-06.
"""

from __future__ import annotations

import fixtures
from conftest import by_id, dump_json, result_keys, search


def test_sc01_parent_category_returns_every_subcategory_including_unlabelled(
    http, case_dir
):
    body = search(
        http,
        status="OPEN",
        category=fixtures.SWE_CATEGORY,
        company=fixtures.PRIMARY_COMPANY.id,
        limit=100,
    )
    dump_json(case_dir / "response.json", body)
    got = result_keys(body)

    assert got == fixtures.PRIMARY_SWE_KEYS, (
        "selecting the Software Engineering PARENT did not return every one of its "
        f"rows.\n  missing: {sorted(fixtures.PRIMARY_SWE_KEYS - got)}\n  "
        f"unexpected: {sorted(got - fixtures.PRIMARY_SWE_KEYS)}\n"
        "A parent-category selection must be the UNION of its subcategories plus the "
        "rows that carry none — never just the labelled ones."
    )


def test_sc01_parent_category_includes_the_null_and_the_empty_row(http):
    """Named separately from the set assertion above so a regression that drops
    exactly these two reads as what it is, rather than as a set-diff to squint at."""
    body = search(
        http,
        status="OPEN",
        category=fixtures.SWE_CATEGORY,
        company=fixtures.PRIMARY_COMPANY.id,
        limit=100,
    )
    rows = by_id(body)

    assert "J-NULL" in rows, (
        "a SWE row whose enrichment_subcategories is NULL (never evaluated — the "
        "backfill queue, and on day 0 that is EVERY row) was dropped by a "
        "parent-category selection"
    )
    assert "J-EMPTY" in rows, (
        "a SWE row whose enrichment_subcategories is '{}' (evaluated, no specialty "
        "applies — a TERMINAL state, not a pending one) was dropped by a "
        "parent-category selection"
    )


def test_sc01_parent_category_does_not_reach_outside_its_category(http):
    """The control. A filter that returned everything would pass the two cases
    above for the wrong reason."""
    body = search(
        http,
        status="OPEN",
        category=fixtures.SWE_CATEGORY,
        company=fixtures.PRIMARY_COMPANY.id,
        limit=100,
    )
    got = result_keys(body)

    assert "J-PM" not in got, (
        "a product_manager row came back under ?category=software_engineering — the "
        "category predicate is not filtering at all"
    )
    assert got < fixtures.PRIMARY_ALL_KEYS, (
        "the SWE selection returned every row the company owns, so it proves nothing: "
        "the fixture corpus must contain at least one non-SWE row for this to be a test"
    )


def test_sc01_no_category_filter_returns_the_non_swe_row_too(http):
    """And the mirror: with NO category filter the PM row is there, so its absence
    above is the filter working rather than the row missing from the database."""
    body = search(http, status="OPEN", company=fixtures.PRIMARY_COMPANY.id, limit=100)
    got = result_keys(body)

    assert got == fixtures.PRIMARY_ALL_KEYS, (
        "an unfiltered read of the fixture company did not return all of its rows.\n"
        f"  missing: {sorted(fixtures.PRIMARY_ALL_KEYS - got)}\n"
        f"  unexpected: {sorted(got - fixtures.PRIMARY_ALL_KEYS)}"
    )
