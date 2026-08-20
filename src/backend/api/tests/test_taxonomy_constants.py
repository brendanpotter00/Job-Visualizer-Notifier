"""SCHEMA-3a: freeze the subcategory taxonomy constants.

`services/enrichment_writer.py` is the CODE ARBITER for the three facet
dimensions — the migration seed, the frontend fallback constant, the enricher's
`taxonomy.SUBCATEGORIES` and the ollama response schema all have to agree with
it. These are pure-constant assertions: no DB, no app, no migration, so they run
in the bare `cd src/backend && pytest` step and fail on the branch that
introduces the typo rather than at seed time.

The sorted-list assertion is the load-bearing one. A count check alone passes a
rename; a set check alone passes a reordering of the seed's sort_order.
"""

from __future__ import annotations

from api.services.enrichment_writer import (
    CATEGORY_SLUGS,
    DEFAULT_SUBCATEGORY_SOURCE,
    LEVEL_SLUGS,
    MAX_SUBCATEGORIES,
    SUBCATEGORY_FILTER_EXPANSION,
    SUBCATEGORY_PARENT,
    SUBCATEGORY_SLUGS,
    SUBCATEGORY_SOURCES,
)

# The canonical 15, in the exact order the seed migration writes them
# (sort_order 0..14). Duplicated here ON PURPOSE — a test that derives its
# expectation from the code under test asserts nothing.
EXPECTED_SUBCATEGORY_SLUGS = [
    "ai_engineering",
    "backend",
    "data_engineering",
    "devops_sre",
    "embedded_systems",
    "forward_deployed",
    "frontend",
    "full_stack",
    "infrastructure_platform",
    "ml_engineering",
    "mobile",
    "qa_testing",
    "quantitative",
    "robotics_autonomy",
    "security",
]


def test_there_are_exactly_fifteen_subcategories() -> None:
    assert len(SUBCATEGORY_SLUGS) == 15


def test_subcategory_slugs_match_the_canonical_list_exactly() -> None:
    """Freezes the enum against a typo, a rename and a reordering at once."""
    assert sorted(SUBCATEGORY_SLUGS) == EXPECTED_SUBCATEGORY_SLUGS


def test_subcategories_are_disjoint_from_the_other_two_dimensions() -> None:
    """The arrow never runs backwards: no slug means two different things."""
    assert SUBCATEGORY_SLUGS.isdisjoint(CATEGORY_SLUGS)
    assert SUBCATEGORY_SLUGS.isdisjoint(LEVEL_SLUGS)


def test_the_parent_is_a_real_category() -> None:
    assert SUBCATEGORY_PARENT == "software_engineering"
    assert SUBCATEGORY_PARENT in CATEGORY_SLUGS


def test_max_subcategories_is_two() -> None:
    assert MAX_SUBCATEGORIES == 2


def test_filter_expansion_has_exactly_two_keys_and_both_reach_full_stack() -> None:
    """One-way: selecting Full Stack stays exact, so it is not a key."""
    assert set(SUBCATEGORY_FILTER_EXPANSION) == {"frontend", "backend"}
    for selected, expanded in SUBCATEGORY_FILTER_EXPANSION.items():
        assert selected in expanded
        assert "full_stack" in expanded
    assert "full_stack" not in SUBCATEGORY_FILTER_EXPANSION


def test_every_expansion_slug_is_a_real_subcategory() -> None:
    for expanded in SUBCATEGORY_FILTER_EXPANSION.values():
        assert set(expanded) <= SUBCATEGORY_SLUGS


def test_subcategory_sources_are_exactly_the_five() -> None:
    """`backfill_failed` is deliberately absent — a failed row stays NULL."""
    assert SUBCATEGORY_SOURCES == {"rule", "classify", "backfill", "judge", "human"}
    assert DEFAULT_SUBCATEGORY_SOURCE in SUBCATEGORY_SOURCES
