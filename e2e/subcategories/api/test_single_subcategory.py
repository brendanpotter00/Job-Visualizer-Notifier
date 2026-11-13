"""SC-02 — one subcategory returns ONLY jobs carrying that slug.

The decoy is the case. Asserting "my matches came back" catches a filter that
returns too little; it does not catch the one that returns too much, and a
filter silently returning everything is indistinguishable from no filter at
all. So every assertion here is a SET EQUALITY against an independently
derived expectation, and `J-SECURITY` is seeded specifically to be the row
carrying a DIFFERENT slug that must be absent.

`mobile` and `security` are used deliberately: neither appears in
`SUBCATEGORY_FILTER_EXPANSION`, so this case cannot pass (or fail) for SC-04's
reason. The widening gets its own case and its own slugs.
"""

from __future__ import annotations

import pytest

import fixtures
from conftest import dump_json, result_keys, search


def test_sc02_a_single_subcategory_returns_exactly_its_own_rows(http, case_dir):
    body = search(
        http,
        status="OPEN",
        subcategory="mobile",
        company=fixtures.PRIMARY_COMPANY.id,
        limit=100,
    )
    dump_json(case_dir / "mobile.json", body)
    got = result_keys(body)

    assert got == fixtures.keys("J-MOBILE"), (
        f"?subcategory=mobile returned {sorted(got)}; expected exactly ['J-MOBILE']. "
        "Anything extra means the overlap predicate is not narrowing; anything "
        "missing means it is narrowing too hard."
    )


def test_sc02_the_decoy_carrying_a_different_slug_is_absent(http):
    """Named for the decoy, so a regression that stops filtering says so."""
    body = search(
        http,
        status="OPEN",
        subcategory="mobile",
        company=fixtures.PRIMARY_COMPANY.id,
        limit=100,
    )
    got = result_keys(body)

    assert "J-SECURITY" not in got, (
        "J-SECURITY carries {security}, not {mobile}, and came back under "
        "?subcategory=mobile — the && is matching rows it should not"
    )
    assert "J-BACKEND" not in got, (
        "J-BACKEND carries {backend} and came back under ?subcategory=mobile"
    )


def test_sc02_the_decoys_own_slug_returns_the_decoy_and_nothing_else(http):
    """The pair is what makes it a filter rather than an ordering. If `mobile`
    returned only J-MOBILE because J-MOBILE happens to sort first, `security`
    returning only J-SECURITY would not also hold."""
    body = search(
        http,
        status="OPEN",
        subcategory="security",
        company=fixtures.PRIMARY_COMPANY.id,
        limit=100,
    )
    got = result_keys(body)

    assert got == fixtures.keys("J-SECURITY"), (
        f"?subcategory=security returned {sorted(got)}; expected exactly ['J-SECURITY']"
    )


def test_sc02_matches_on_a_non_primary_slug_too(http):
    """`enrichment_subcategories` is ORDERED — index 0 is the primary — and `&&`
    is membership, not equality on the first element.

    `J-PAIR` carries `{infrastructure_platform, backend}`. Selecting
    `infrastructure_platform` (its primary) and selecting `backend` (its
    SECOND slug) must both find it. A filter written as `[1] = ANY` or as
    `enrichment_subcategories[1] = %s` would pass the first and fail the second.
    """
    primary = search(
        http, status="OPEN", subcategory="infrastructure_platform",
        company=fixtures.PRIMARY_COMPANY.id, limit=100,
    )
    assert result_keys(primary) == fixtures.keys("J-PAIR"), (
        "selecting a row's PRIMARY subcategory did not find it"
    )

    secondary = search(
        http, status="OPEN", subcategory="backend",
        company=fixtures.PRIMARY_COMPANY.id, limit=100,
    )
    assert "J-PAIR" in result_keys(secondary), (
        "J-PAIR carries {infrastructure_platform, backend} and was NOT returned by "
        "?subcategory=backend — the filter is only looking at the primary slug, so a "
        "job's second specialty is unreachable"
    )


@pytest.mark.parametrize("slug", ["backend", "frontend", "mobile", "security"])
def test_sc02_multiple_values_or_within_the_dimension(http, slug):
    """Repeated `?subcategory=` keys OR together — the declared contract. Asserted
    against the single-value answers so it cannot drift into an AND."""
    single = result_keys(
        search(http, status="OPEN", subcategory=slug,
               company=fixtures.PRIMARY_COMPANY.id, limit=100)
    )
    combined = result_keys(
        search(http, status="OPEN", subcategory=[slug, "qa_testing"],
               company=fixtures.PRIMARY_COMPANY.id, limit=100)
    )
    # No fixture row carries qa_testing, so the union must be unchanged. An AND
    # would empty it; a dropped second value would also leave it unchanged, which
    # is why the next assertion pins a slug that DOES add rows.
    assert combined == single, (
        f"?subcategory={slug}&subcategory=qa_testing changed the result set even "
        f"though no row carries qa_testing — the dimension is not OR-ing"
    )

    with_mobile = result_keys(
        search(http, status="OPEN", subcategory=[slug, "mobile"],
               company=fixtures.PRIMARY_COMPANY.id, limit=100)
    )
    assert with_mobile == single | fixtures.keys("J-MOBILE"), (
        f"?subcategory={slug}&subcategory=mobile did not return the UNION of the two "
        f"— got {sorted(with_mobile)}, expected {sorted(single | {'J-MOBILE'})}"
    )


def test_sc02_an_unknown_slug_matches_nothing_and_is_not_an_error(http):
    """Deliberate contract (`jobs_search.py`): a well-formed but unknown slug is
    not a 422, because validating against the live taxonomy would make a
    taxonomy migration a breaking change for anyone holding a bookmarked URL.
    It simply matches no row."""
    body = search(
        http, status="OPEN", subcategory="not_a_real_slug",
        company=fixtures.PRIMARY_COMPANY.id, limit=100,
    )
    assert result_keys(body) == set(), (
        "an unknown-but-well-formed subcategory slug returned rows — it must match "
        "nothing, the same way an unknown category does"
    )
