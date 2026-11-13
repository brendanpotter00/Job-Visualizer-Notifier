"""SC-06 — NULL and `'{}'` are different, end to end.

Two states, one column, and collapsing them is a one-character change:

    NULL   "nobody has evaluated this row yet"   -> still in the backfill queue
    '{}'   "evaluated, no specialty applies"     -> TERMINAL

`JobListingResponse.subcategories` is declared `list[str] | None = None` and
NOT `default_factory=list` for exactly this reason. A default of `[]` would
erase the distinction for every unenriched row the moment it crossed the wire,
and the backfill queue — which is read off "is it NULL?" — would report itself
complete on day 0.

The filter side is the mirror image: `&&` is NULL for NULL and false for
`'{}'`, so an active subcategory filter hides BOTH. That is the sharpest
difference between this dimension and `category`/`level`, which hide only
their NULLs, and it is why the reveal flag exists at all — mid-backfill, an
active filter hides every not-yet-labelled SWE row.

NO UI SPEC. `null` versus `[]` is a wire-format fact with no rendered
difference: `JobChipsSection` falls back to the category chip for both. A UI
assertion for a non-UI fact is a lie (PLAN.md §3), so this case lives on one
tier only and CASES.md says so.
"""

from __future__ import annotations

import fixtures
from conftest import DB_DSN, by_id, db, dump_json, result_keys, search


def test_sc06_the_database_really_holds_the_two_distinct_states(db_conn):
    """The fixture assertion. Everything below is meaningless if psycopg2
    flattened `[]` to NULL on the way in — and that is a plausible seeding bug,
    not a hypothetical one."""
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT id, enrichment_subcategories AS subs,"
            "       enrichment_subcategories IS NULL AS is_null"
            "  FROM job_listings WHERE source_id = %s AND id = ANY(%s)",
            (fixtures.SOURCE_ID, ["J-NULL", "J-EMPTY"]),
        )
        rows = {r["id"]: r for r in cur.fetchall()}

    assert rows["J-NULL"]["is_null"] is True, (
        "J-NULL was seeded with a non-NULL array — the fixture meant SQL NULL "
        "('never evaluated') and got something else"
    )
    assert rows["J-EMPTY"]["is_null"] is False, (
        "J-EMPTY was seeded as NULL rather than as '{}' — psycopg2 flattened the "
        "empty list, and the two states this case is about are the same row"
    )
    assert rows["J-EMPTY"]["subs"] == [], (
        f"J-EMPTY holds {rows['J-EMPTY']['subs']!r}, expected an empty array"
    )


def test_sc06_null_serializes_as_null_and_empty_serializes_as_empty_list(
    http, case_dir
):
    """The wire contract, read off the real response body."""
    body = search(
        http, status="OPEN", category=fixtures.SWE_CATEGORY,
        company=fixtures.PRIMARY_COMPANY.id, limit=100,
    )
    dump_json(case_dir / "serialization.json", body)
    rows = by_id(body)

    assert "subcategories" in rows["J-NULL"], (
        "the `subcategories` key is missing from the response entirely. It must be "
        "PRESENT and null — an absent key and a null value read the same in "
        "JavaScript but not to a typed client or a cache diff."
    )
    assert rows["J-NULL"]["subcategories"] is None, (
        f"J-NULL serialized as {rows['J-NULL']['subcategories']!r}, expected null. "
        "A `default_factory=list` on JobListingResponse.subcategories turns every "
        "never-evaluated row into an evaluated-and-empty one at the boundary, and "
        "the backfill queue reads itself as complete."
    )
    assert rows["J-EMPTY"]["subcategories"] == [], (
        f"J-EMPTY serialized as {rows['J-EMPTY']['subcategories']!r}, expected []. "
        "The terminal 'we looked, nothing applies' state must not come back as null "
        "— that would put the row back in the backfill queue forever."
    )
    assert rows["J-PAIR"]["subcategories"] == ["infrastructure_platform", "backend"], (
        f"J-PAIR serialized as {rows['J-PAIR']['subcategories']!r}. The array is "
        "ORDERED — index 0 is the primary, and the chip row renders it first — so "
        "the order must survive the wire, not just the membership."
    )


def test_sc06_an_active_subcategory_filter_hides_both(http):
    """`&&` is false for `'{}'` and NULL for NULL. Both drop out."""
    got = result_keys(
        search(http, status="OPEN", subcategory="backend",
               company=fixtures.PRIMARY_COMPANY.id, limit=100)
    )
    assert "J-NULL" not in got, (
        "a never-evaluated row survived an active subcategory filter. `NULL && x` is "
        "NULL, which WHERE treats as false — a row that came back means the "
        "predicate grew a COALESCE or an IS NULL escape hatch."
    )
    assert "J-EMPTY" not in got, (
        "an evaluated-but-empty row survived an active subcategory filter. `'{}' && x` "
        "is false; a row that came back means the predicate is not the overlap operator."
    )


def test_sc06_both_are_reachable_with_no_subcategory_filter(http):
    """The mirror, so "hidden" is the filter working rather than the rows being
    absent. This is also the only assertion in the file that would catch a seed
    that silently wrote nine rows instead of eleven."""
    got = result_keys(
        search(http, status="OPEN", category=fixtures.SWE_CATEGORY,
               company=fixtures.PRIMARY_COMPANY.id, limit=100)
    )
    assert {"J-NULL", "J-EMPTY"} <= got, (
        f"the NULL and '{{}}' rows are not in an unfiltered SWE read: got {sorted(got)}"
    )


def test_sc06_the_subcategory_dimension_hides_harder_than_level(http):
    """The difference from `category`/`level`, stated as a test.

    `enrichment_level = ANY(...)` is NULL for an unenriched row — so a level
    filter hides NULLs too. But `J-EMPTY` has a level, so a level filter KEEPS
    it while a subcategory filter drops it. That gap is the whole reason the
    reveal flag exists, and a change that made `&&` fall back to "match empty
    arrays" would erase it while leaving every other case in this section green.
    """
    by_level = result_keys(
        search(http, status="OPEN", level="mid",
               company=fixtures.PRIMARY_COMPANY.id, limit=100)
    )
    assert {"J-NULL", "J-EMPTY"} <= by_level, (
        "a LEVEL filter dropped the rows with no subcategory. It must not: those rows "
        "have a level, and the level predicate knows nothing about the array column. "
        f"Got {sorted(by_level)}"
    )

    by_subcategory = result_keys(
        search(http, status="OPEN", subcategory="backend",
               company=fixtures.PRIMARY_COMPANY.id, limit=100)
    )
    assert not ({"J-NULL", "J-EMPTY"} & by_subcategory), (
        "the same two rows survived a SUBCATEGORY filter. The subcategory dimension "
        "hides strictly harder than the level one; if it stopped, an active filter "
        "mid-backfill would start returning unlabelled rows as though they matched."
    )


def test_sc06_a_null_row_is_not_resurrected_by_an_empty_filter_value(http):
    """The empty-string edge. `?subcategory=` with no value must not be read as
    "filter on the empty array", which would match `'{}'` and nothing else."""
    resp = http.get("/api/jobs/search", params=[
        ("status", "OPEN"),
        ("company", fixtures.PRIMARY_COMPANY.id),
        ("subcategory", ""),
        ("limit", "100"),
    ])
    # Either a 422 (the slug pattern rejects it) or a 200 that ignores it are
    # defensible; silently filtering to the empty-array rows is not.
    assert resp.status_code in (200, 422), (
        f"?subcategory= (empty) answered {resp.status_code}: {resp.text[:300]}"
    )
    if resp.status_code == 200:
        got = {job["id"] for job in resp.json()["jobs"]}
        assert got != fixtures.keys("J-EMPTY"), (
            "an empty ?subcategory= value was read as 'match the empty array' and "
            "returned exactly the evaluated-but-empty row"
        )
