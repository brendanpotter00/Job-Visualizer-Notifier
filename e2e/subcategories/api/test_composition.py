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

And the ONE deliberate exception to "every dimension ANDs" (bottom of this
file): a subcategory is a software-engineering specialty, so beside another
selected category it narrows only the SWE rows and that category keeps all of
its rows.
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


# --- The specialty scope (onboarding PR, PLAN.md §7 of e2e/onboarding) --------
#
# A subcategory is a SOFTWARE ENGINEERING specialty, so it narrows only the
# software rows. Another selected category keeps ALL of its rows. This replaced
# the old rule ("a subcategory paired with the wrong parent is unsatisfiable"),
# deliberately: the first-sign-in questions let a reader pick Product Manager
# AND Backend, and under the old rule that answer hid every Product Manager job.
# `subcategory` with no category, and `software_engineering` alone, are
# unchanged — SC-02 and SC-04 pin those and are untouched.


def _primary_keys_in_category(category: str) -> set[str]:
    """The primary company's rows of one category, straight off the fixture
    table — the oracle, not a second query against the code under test."""
    return {
        j.key for j in fixtures.JOBS
        if j.company is fixtures.PRIMARY_COMPANY and j.category == category
    }


def test_sc03_a_specialty_beside_another_role_keeps_all_that_roles_rows(http, case_dir):
    """`category=product_manager&subcategory=backend` returns EXACTLY the
    product-manager rows: the specialty does not narrow a role it is not a
    specialty of. Mirror: no software-engineering row at all, so it did not
    simply drop the category clause either."""
    body = search(http, status="OPEN", category=fixtures.NON_SWE_CATEGORY,
                  subcategory="backend", company=fixtures.PRIMARY_COMPANY.id, limit=100)
    dump_json(case_dir / "pm-plus-backend.json", body)
    got = result_keys(body)

    expected = _primary_keys_in_category(fixtures.NON_SWE_CATEGORY)
    assert expected == fixtures.keys("J-PM"), "fixture drift: SC-03 expects one PM row, J-PM"
    assert got == expected, (
        f"?category=product_manager&subcategory=backend returned {sorted(got)}; expected exactly "
        f"the product-manager rows {sorted(expected)}. A specialty must narrow only software "
        "engineering rows — under the OLD rule this was empty, which hid every Product "
        "Manager job from a reader who also picked Backend"
    )
    swe_leak = got & fixtures.PRIMARY_SWE_KEYS
    assert not swe_leak, (
        f"software-engineering rows {sorted(swe_leak)} came back with only product_manager "
        "selected — the category clause was dropped"
    )
    # The same rows as the category alone: the specialty changed nothing here.
    pm_alone = result_keys(search(http, status="OPEN", category=fixtures.NON_SWE_CATEGORY,
                                  company=fixtures.PRIMARY_COMPANY.id, limit=100))
    assert got == pm_alone


def test_sc03_with_two_roles_the_specialty_narrows_only_the_swe_rows(http, case_dir):
    """`category=software_engineering&category=product_manager&subcategory=backend`
    returns the PM rows PLUS exactly the SWE rows matching `backend` — with its
    `full_stack` widening — and no other SWE row."""
    body = search(http, status="OPEN",
                  category=[fixtures.SWE_CATEGORY, fixtures.NON_SWE_CATEGORY],
                  subcategory="backend", company=fixtures.PRIMARY_COMPANY.id, limit=100)
    dump_json(case_dir / "swe-pm-plus-backend.json", body)
    got = result_keys(body)

    swe_backend = fixtures.expected_for_subcategory("backend", company=fixtures.PRIMARY_COMPANY)
    pm_rows = _primary_keys_in_category(fixtures.NON_SWE_CATEGORY)
    expected = pm_rows | swe_backend
    assert got == expected, (
        f"SWE + PM + backend returned {sorted(got)}; expected the PM rows {sorted(pm_rows)} "
        f"plus exactly the backend SWE rows {sorted(swe_backend)}"
    )
    # The decoys: every other SWE row — a different specialty, NULL, '{}' — must
    # stay narrowed out. A specialty that stopped narrowing SWE rows once a second
    # role was picked would let them all back in.
    other_swe = fixtures.PRIMARY_SWE_KEYS - swe_backend
    assert other_swe >= fixtures.keys("J-MOBILE", "J-SECURITY", "J-NULL", "J-EMPTY", "J-FRONTEND")
    leaked = got & other_swe
    assert not leaked, (
        f"SWE rows outside `backend` {sorted(leaked)} came back — the specialty stopped "
        "narrowing software engineering once a second role was selected"
    )
    assert "J-FULLSTACK" in got, "the full_stack widening was lost in the two-role scope"
