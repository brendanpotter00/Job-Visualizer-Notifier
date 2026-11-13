"""SC-04 — the `full_stack` widening is ONE-WAY.

    frontend -> {frontend, full_stack}
    backend  -> {backend,  full_stack}
    full_stack -> {full_stack}          <- and NOT back the other way

The asymmetry is the feature. A reader who asks for full-stack work must not
get every frontend job back; a reader who asks for frontend work should still
see the full-stack roles they could do. Make it symmetric and `full_stack`
becomes a synonym for "software engineering", which is the failure this case
exists to catch — and it is a failure that a "did my matches come back?" test
cannot see, because the symmetric version returns a SUPERSET.

SOLE EXPANDER. The expansion happens in `job_search.expand_subcategories` and
nowhere else on this path: `buildSearchJobsArgs` sends the user's selection
verbatim. That is why the API tier asserts the widened RESULT rather than a
widened query string — the wire still carries one slug.
"""

from __future__ import annotations

import pytest

import fixtures
from conftest import dump_json, result_keys, search


@pytest.mark.parametrize(
    "slug,expected_keys",
    [
        ("frontend", {"J-FRONTEND", "J-FULLSTACK"}),
        ("backend", {"J-BACKEND", "J-BACKEND-MID", "J-PAIR", "J-FULLSTACK"}),
    ],
)
def test_sc04_frontend_and_backend_each_also_surface_full_stack(
    http, case_dir, slug, expected_keys
):
    body = search(
        http, status="OPEN", subcategory=slug,
        company=fixtures.PRIMARY_COMPANY.id, limit=100,
    )
    dump_json(case_dir / f"{slug}.json", body)
    got = result_keys(body)

    assert "J-FULLSTACK" in got, (
        f"?subcategory={slug} did not surface the Full Stack row. The widening "
        f"({slug} ⊃ full_stack) is the one thing this dimension does beyond plain "
        "membership, and it is gone."
    )
    assert got == expected_keys, (
        f"?subcategory={slug} returned {sorted(got)}, expected {sorted(expected_keys)}"
    )
    # The oracle, computed from the fixture table and EXPECTED_WIDENING rather
    # than from the code under test — so this is not `expand_subcategories`
    # being compared to itself.
    assert got == fixtures.expected_for_subcategory(slug), (
        "the result disagrees with the widening table declared in fixtures.py"
    )


def test_sc04_full_stack_alone_stays_exact(http, case_dir):
    """The load-bearing half. Everything above would still pass if the relation
    were symmetric."""
    body = search(
        http, status="OPEN", subcategory="full_stack",
        company=fixtures.PRIMARY_COMPANY.id, limit=100,
    )
    dump_json(case_dir / "full_stack.json", body)
    got = result_keys(body)

    assert got == fixtures.keys("J-FULLSTACK"), (
        f"?subcategory=full_stack returned {sorted(got)}, expected exactly "
        "['J-FULLSTACK']. The widening must be ONE-WAY: a reader asking "
        "specifically for full-stack work does not want every frontend and backend "
        "job back."
    )
    assert "J-FRONTEND" not in got, (
        "?subcategory=full_stack returned the Frontend row — the widening has become "
        "symmetric, which makes full_stack a synonym for the whole category"
    )
    assert "J-BACKEND" not in got, (
        "?subcategory=full_stack returned the Backend row — the widening has become "
        "symmetric"
    )


def test_sc04_the_widening_does_not_leak_into_unrelated_slugs(http):
    """Only `frontend` and `backend` widen. A slug that picked up `full_stack`
    by accident — say because the expansion map got a default of "add
    full_stack" — would show up here."""
    for slug in ("mobile", "security", "infrastructure_platform"):
        got = result_keys(
            search(http, status="OPEN", subcategory=slug,
                   company=fixtures.PRIMARY_COMPANY.id, limit=100)
        )
        assert "J-FULLSTACK" not in got, (
            f"?subcategory={slug} surfaced the Full Stack row. Only `frontend` and "
            f"`backend` widen (SUBCATEGORY_FILTER_EXPANSION has exactly two keys); "
            f"{slug} must stay exact."
        )
        assert got == fixtures.expected_for_subcategory(slug), (
            f"?subcategory={slug} returned {sorted(got)}, which disagrees with the "
            "widening table declared in fixtures.py"
        )


def test_sc04_selecting_both_sides_is_the_union_not_a_double_expansion(http):
    """`?subcategory=frontend&subcategory=full_stack`.

    The expansion is order-preserving and de-duplicating, so this must equal the
    union of the two single-slug answers. A double expansion (the client
    pre-expanding AND the server expanding) would not change THIS result — but
    it is what persists `['backend','full_stack']` into a user's saved filters
    and chips, which is why the module docstring names the sole-expander rule.
    """
    frontend = result_keys(
        search(http, status="OPEN", subcategory="frontend",
               company=fixtures.PRIMARY_COMPANY.id, limit=100)
    )
    full_stack = result_keys(
        search(http, status="OPEN", subcategory="full_stack",
               company=fixtures.PRIMARY_COMPANY.id, limit=100)
    )
    both = result_keys(
        search(http, status="OPEN", subcategory=["frontend", "full_stack"],
               company=fixtures.PRIMARY_COMPANY.id, limit=100)
    )
    assert both == frontend | full_stack, (
        f"?subcategory=frontend&subcategory=full_stack returned {sorted(both)}, "
        f"expected the union {sorted(frontend | full_stack)}"
    )
    assert both == frontend, (
        "frontend already widens to include full_stack, so adding full_stack "
        "explicitly must be a no-op on the result set"
    )
