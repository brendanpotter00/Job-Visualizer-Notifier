"""SCHEMA-15: the cross-repo taxonomy artifact, and the JVN half of the check.

WHY THIS FILE EXISTS
--------------------
Every other taxonomy guard in this repo is INTRA-repo — code vs migration
(`TestTaxonomyParity`), code vs API (`test_facets_catalog`), code vs itself
(`test_taxonomy_constants`). The enricher has its own intra-repo guards. Nothing
compared ACROSS the two repos, which is exactly how the live drift survived:
`job_categories` had 7 seeded rows, `CATEGORY_SLUGS` had 7, and the enricher's
`taxonomy.CATEGORIES` had 6, for months, with every test green on both sides.

`src/backend/taxonomy.json` is the ONE artifact both repos read. This file is the
JVN half: it asserts FOUR-WAY equality in one place —

    taxonomy.json  ==  enrichment_writer's slug sets
                   ==  the migration seeds
                   ==  what get_facets actually returns

so editing ANY ONE of the four alone fails here. The ENR half (`ENR-PAR-2`)
vendors this file with a recorded sha256 and asserts set equality against its own
constants.

Runs in the existing `backend` CI job (`cd src/backend && pytest`) with no
workflow change.

PHASE-1 WINDOW: the subcategory arm against the DATABASE is EMPTY-OR-EQUAL, not
equality. `job_subcategories` ships unseeded on purpose (seeding it is what
publishes the public dropdown), so an equality assertion here would be a false
green against a fixture that seeds what production does not have. SCHEMA-9
tightens it to `==` in the phase-2 PR.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.services.enrichment_monitor import get_facets
from api.services.enrichment_writer import (
    CATEGORY_SLUGS,
    LEVEL_SLUGS,
    SUBCATEGORY_PARENT,
    SUBCATEGORY_SLUGS,
    SUBCATEGORY_SOURCES,
)

from .test_internal_enrichment import _enrichment_isolation  # noqa: F401 — autouse

_SRC_BACKEND = Path(__file__).resolve().parents[2]
_ARTIFACT = _SRC_BACKEND / "taxonomy.json"


@pytest.fixture(scope="module")
def artifact() -> dict:
    assert _ARTIFACT.exists(), (
        f"{_ARTIFACT} is missing. Regenerate it with "
        "`cd src/backend && python tools/generate_taxonomy_artifact.py` — it is "
        "GENERATED from the migrations + enrichment_writer, never hand-typed."
    )
    return json.loads(_ARTIFACT.read_text())


def _slugs(rows: list[dict]) -> set[str]:
    return {row["slug"] for row in rows}


class TestArtifactMatchesCode:
    """Arm 1: taxonomy.json == the code constants."""

    def test_categories(self, artifact):
        assert _slugs(artifact["categories"]) == set(CATEGORY_SLUGS)

    def test_levels(self, artifact):
        assert _slugs(artifact["levels"]) == set(LEVEL_SLUGS)

    def test_subcategories(self, artifact):
        assert _slugs(artifact["subcategories"]) == set(SUBCATEGORY_SLUGS)

    def test_subcategory_sources(self, artifact):
        """⚠ THE ONE ENUM WITH NO OTHER PARITY TEST ANYWHERE.

        `subcategory_source` is also the column a SCOPED ROLLBACK keys on — if
        the two repos disagree about its values, an admin reset for 'backfill'
        silently matches zero rows while reporting success.
        """
        assert set(artifact["subcategory_sources"]) == set(SUBCATEGORY_SOURCES)
        assert artifact["subcategory_sources"] == sorted(SUBCATEGORY_SOURCES)


class TestArtifactMatchesMigrations:
    """Arm 2: taxonomy.json == the migration seeds (minus REMOVED_CATEGORIES)."""

    def test_categories_match_the_seed_minus_removals(self, artifact):
        from .test_internal_enrichment import _load_enrichment_migration

        seed = _load_enrichment_migration()
        retire = _load_enrichment_migration("*retire_project_manager_category*.py")
        expected = {slug for slug, _label, _order in seed.CATEGORY_SEED}
        expected -= set(retire.REMOVED_CATEGORIES)
        assert _slugs(artifact["categories"]) == expected

    def test_levels_match_the_seed_plus_additions(self, artifact):
        from .test_internal_enrichment import _load_enrichment_migration

        seed = _load_enrichment_migration()
        intern = _load_enrichment_migration("*add_intern_level*.py")
        expected = {slug for slug, _l, _r, _p in seed.LEVEL_SEED}
        expected |= {slug for slug, _l, _r, _p in intern.ADDED_LEVELS}
        assert _slugs(artifact["levels"]) == expected

    def test_category_labels_and_order_match_the_seed(self, artifact):
        from .test_internal_enrichment import _load_enrichment_migration

        seed = _load_enrichment_migration()
        seeded = {slug: (label, order) for slug, label, order in seed.CATEGORY_SEED}
        for row in artifact["categories"]:
            assert (row["label"], row["sort_order"]) == seeded[row["slug"]]


class TestArtifactMatchesTheApi:
    """Arm 3: taxonomy.json == what get_facets actually serves."""

    def test_categories_and_levels(self, artifact, db_conn):
        facets = get_facets(db_conn)
        assert _slugs(facets["categories"]) == _slugs(artifact["categories"])
        assert _slugs(facets["levels"]) == _slugs(artifact["levels"])

    def test_subcategories_are_empty_or_equal(self, artifact, db_conn):
        """PHASE-1 WINDOW. `job_subcategories` ships EMPTY, so this is a
        subset-or-equal check; SCHEMA-9 tightens it to `==` once prod is seeded.
        An equality assertion today would only pass against a fixture that seeds
        the table — i.e. against a state production is not in."""
        facets = get_facets(db_conn)
        served = _slugs(facets.get("subcategories", []))
        assert served <= _slugs(artifact["subcategories"])
        if served:
            assert served == _slugs(artifact["subcategories"])


class TestArtifactShape:
    def test_every_row_has_the_four_keys(self, artifact):
        for facet in ("categories", "levels", "subcategories"):
            for row in artifact[facet]:
                assert set(row) == {"slug", "label", "sort_order", "parent_slug"}
                assert isinstance(row["label"], str) and row["label"]

    def test_every_subcategory_hangs_off_the_one_parent(self, artifact):
        parents = {row["parent_slug"] for row in artifact["subcategories"]}
        assert parents == {SUBCATEGORY_PARENT}
        assert SUBCATEGORY_PARENT in _slugs(artifact["categories"])

    def test_categories_carry_no_parent(self, artifact):
        assert {row["parent_slug"] for row in artifact["categories"]} == {None}

    def test_subcategory_sort_order_is_dense_and_alphabetical(self, artifact):
        rows = sorted(artifact["subcategories"], key=lambda r: r["sort_order"])
        assert [r["sort_order"] for r in rows] == list(range(15))
        assert [r["slug"] for r in rows] == sorted(SUBCATEGORY_SLUGS)

    def test_the_three_dimensions_are_pairwise_disjoint(self, artifact):
        cats = _slugs(artifact["categories"])
        levels = _slugs(artifact["levels"])
        subs = _slugs(artifact["subcategories"])
        assert cats.isdisjoint(levels)
        assert cats.isdisjoint(subs)
        assert levels.isdisjoint(subs)


def test_the_artifact_is_reproducible_from_its_inputs():
    """⚠ THE ONE THAT MAKES THE OTHERS HONEST.

    The committed file must be byte-reconstructible from the migrations + the
    code constants. Without this, someone could hand-edit `taxonomy.json` into
    agreement and the four-way check would pass while the artifact had become a
    fourth independent copy of the taxonomy — the exact thing it exists to
    prevent.
    """
    import importlib.util

    generator_path = _SRC_BACKEND / "tools" / "generate_taxonomy_artifact.py"
    spec = importlib.util.spec_from_file_location("gen_taxonomy", generator_path)
    assert spec is not None and spec.loader is not None
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)

    expected = json.dumps(gen.build_artifact(), indent=2) + "\n"
    assert _ARTIFACT.read_text() == expected, (
        "taxonomy.json is out of date or was hand-edited. Regenerate it: "
        "cd src/backend && python tools/generate_taxonomy_artifact.py"
    )
