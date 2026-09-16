"""SC-03 — the subcategory dimension ANDs with every other filter.

A new dimension is the classic place an OR leaks in. The shape of the bug is
always the same: the new predicate gets appended to the wrong list, or is
`OR`ed onto the existing WHERE, and the result is a filter that WIDENS when
the user narrows. Both decoys below match exactly one side of the conjunction,
so an OR shows up as a row that should not be there rather than as a count.

Two compositions, because they fail differently:
  * subcategory + LEVEL   — two enrichment facets, same table, adjacent code
  * subcategory + COMPANY — a facet and a scope, and the scope is also what
                            every other case in this section relies on to
                            isolate its fixtures
"""

from __future__ import annotations

import fixtures
from conftest import dump_json, result_keys, search


def test_sc03_subcategory_and_level_compose_with_and(http, case_dir):
    body = search(
        http,
        status="OPEN",
        subcategory="backend",
        level="senior",
        company=fixtures.PRIMARY_COMPANY.id,
        limit=100,
    )
    dump_json(case_dir / "backend-senior.json", body)
    got = result_keys(body)

    # J-BACKEND is {backend} @ senior. J-PAIR is {infrastructure_platform,
    # backend} @ senior. J-FULLSTACK is senior but is only reachable through the
    # widening, which DOES apply to `backend` — so it belongs in the expected set.
    expected = fixtures.keys("J-BACKEND", "J-PAIR", "J-FULLSTACK")
    assert got == expected, (
        f"?subcategory=backend&level=senior returned {sorted(got)}, expected "
        f"{sorted(expected)}"
    )


def test_sc03_a_row_matching_only_the_subcategory_is_excluded(http):
    """`J-BACKEND-MID` carries {backend} at level `mid`. It is the AND decoy: it
    satisfies the subcategory and fails the level, so an OR returns it."""
    got = result_keys(
        search(http, status="OPEN", subcategory="backend", level="senior",
               company=fixtures.PRIMARY_COMPANY.id, limit=100)
    )
    assert "J-BACKEND-MID" not in got, (
        "J-BACKEND-MID is {backend} at level=mid and came back under "
        "?subcategory=backend&level=senior. The two dimensions are OR-ing, not "
        "AND-ing — the filter WIDENS when the user narrows."
    )

    # ...and the mirror, so the exclusion is the level filter working rather than
    # the row being absent from the corpus.
    at_mid = result_keys(
        search(http, status="OPEN", subcategory="backend", level="mid",
               company=fixtures.PRIMARY_COMPANY.id, limit=100)
    )
    assert at_mid == fixtures.keys("J-BACKEND-MID"), (
        f"?subcategory=backend&level=mid returned {sorted(at_mid)}; expected exactly "
        "['J-BACKEND-MID'] — the row excluded above must be reachable at its own level"
    )


def test_sc03_a_row_matching_only_the_level_is_excluded(http):
    """The other direction of the same conjunction. `J-SECURITY` is senior but
    carries {security}, so a filter that dropped the subcategory clause entirely
    would return it."""
    got = result_keys(
        search(http, status="OPEN", subcategory="backend", level="senior",
               company=fixtures.PRIMARY_COMPANY.id, limit=100)
    )
    assert "J-SECURITY" not in got, (
        "J-SECURITY is level=senior with {security} and came back under "
        "?subcategory=backend&level=senior — the subcategory clause was dropped"
    )


def test_sc03_subcategory_and_company_compose_with_and(http, case_dir):
    """`J-OTHER-BACK` carries {backend} and differs from `J-BACKEND` in exactly
    one attribute: its company. So it is the cleanest possible decoy for the
    scope half of the conjunction."""
    primary = search(
        http, status="OPEN", subcategory="backend",
        company=fixtures.PRIMARY_COMPANY.id, limit=100,
    )
    dump_json(case_dir / "backend-primary-company.json", primary)
    primary_keys = result_keys(primary)

    assert "J-OTHER-BACK" not in primary_keys, (
        f"J-OTHER-BACK belongs to {fixtures.OTHER_COMPANY.id} and came back under "
        f"?subcategory=backend&company={fixtures.PRIMARY_COMPANY.id} — the company "
        "scope is not AND-ing with the subcategory filter"
    )

    other = result_keys(
        search(http, status="OPEN", subcategory="backend",
               company=fixtures.OTHER_COMPANY.id, limit=100)
    )
    assert other == fixtures.keys("J-OTHER-BACK"), (
        f"?subcategory=backend&company={fixtures.OTHER_COMPANY.id} returned "
        f"{sorted(other)}; expected exactly ['J-OTHER-BACK'] — the row excluded above "
        "must be reachable under its own company"
    )


def test_sc03_dropping_the_company_scope_returns_both_companies(http):
    """The control for every OTHER case in this section.

    Almost every query here carries `?company=`, which is only legitimate if
    that scope really is an AND rather than a no-op. Same filter without it must
    return the union across both companies — if it did not, the scoping used
    everywhere else would be hiding rows for a reason nobody had checked.
    """
    got = result_keys(search(http, status="OPEN", subcategory="backend", limit=100))
    expected = fixtures.expected_for_subcategory("backend", company=None)
    assert got == expected, (
        f"?subcategory=backend with NO company scope returned {sorted(got)}, expected "
        f"the union across both fixture companies {sorted(expected)}"
    )
    assert "J-OTHER-BACK" in got, (
        "the unscoped read did not include the other company's row, so the company "
        "scope used by the rest of this section is not actually narrowing anything"
    )


def test_sc03_three_dimensions_still_and(http):
    """category + subcategory + level. The parent category is redundant with the
    subcategory by construction (every slug implies `software_engineering`), and
    redundant-but-consistent must not change the answer — that is what the UI
    sends, since ticking a child auto-checks its parent."""
    two = result_keys(
        search(http, status="OPEN", subcategory="backend", level="senior",
               company=fixtures.PRIMARY_COMPANY.id, limit=100)
    )
    three = result_keys(
        search(http, status="OPEN", category=fixtures.SWE_CATEGORY,
               subcategory="backend", level="senior",
               company=fixtures.PRIMARY_COMPANY.id, limit=100)
    )
    assert three == two, (
        "adding the parent category alongside a subcategory changed the result set. "
        "The UI ALWAYS sends both (ticking a child auto-checks its parent), so this "
        f"is the request shape the product makes: got {sorted(three)}, expected "
        f"{sorted(two)}"
    )

    mismatched = result_keys(
        search(http, status="OPEN", category=fixtures.NON_SWE_CATEGORY,
               subcategory="backend", company=fixtures.PRIMARY_COMPANY.id, limit=100)
    )
    assert mismatched == set(), (
        "a subcategory paired with the WRONG parent category returned rows. Every "
        "slug implies software_engineering, so this conjunction is unsatisfiable and "
        f"must be empty — got {sorted(mismatched)}"
    )
