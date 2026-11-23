"""Taxonomy contract tests: the 17 subcategory slugs and `validate_subcategories`.

The enum assertions here freeze the slug set against a typo. The slugs must be
byte-identical in six places (see `taxonomy.SUBCATEGORIES`' comment); this file
owns the intra-repo half of that guard and `tests/test_cross_repo_parity.py`
owns the cross-repo half.
"""

from __future__ import annotations

import pytest

from job_enricher import taxonomy as tax

# The canonical list, alphabetical, typed out ONCE as a literal so a change to
# the frozenset has to be made deliberately in two places.
CANONICAL_SUBCATEGORY_SLUGS = [
    "ai_engineering",
    "backend",
    "data_engineering",
    "devops_sre",
    "embedded_systems",
    "forward_deployed",
    "frontend",
    "full_stack",
    "growth_engineering",
    "infrastructure_platform",
    "ml_engineering",
    "mobile",
    "product_engineering",
    "qa_testing",
    "quantitative",
    "robotics_autonomy",
    "security",
]


class TestSubcategoryEnum:
    def test_exactly_seventeen(self):
        assert len(tax.SUBCATEGORIES) == 17

    def test_sorted_equals_the_canonical_literal(self):
        assert sorted(tax.SUBCATEGORIES) == CANONICAL_SUBCATEGORY_SLUGS

    def test_disjoint_from_categories_and_levels(self):
        assert not (tax.SUBCATEGORIES & tax.CATEGORIES)
        assert not (tax.SUBCATEGORIES & tax.LEVELS)

    def test_sources_are_exactly_the_five(self):
        assert tax.SUBCATEGORY_SOURCES == frozenset(
            {"rule", "classify", "backfill", "judge", "human"}
        )

    def test_parent_and_max(self):
        assert tax.SUBCATEGORY_PARENT == "software_engineering"
        assert tax.MAX_SUBCATEGORIES == 2


SWE = "software_engineering"


class TestValidateSubcategories:
    def test_happy_path(self):
        assert tax.validate_subcategories(SWE, ["backend", "frontend"]) == (
            ["backend", "frontend"],
            [],
            [],
        )

    def test_unknown_slug_lands_in_bad(self):
        # `ai_ml` is a REAL dead slug: it was killed in r2 when AI split into
        # ai_engineering / ml_engineering. It is the correct unknown-slug fixture.
        subs, bad, warnings = tax.validate_subcategories(SWE, ["ai_ml"])
        assert subs == []
        assert bad == [("subcategories", "ai_ml")]
        assert warnings == []

    def test_non_swe_parent_with_a_list_is_nulled(self):
        subs, bad, _ = tax.validate_subcategories("business_ops", ["backend"])
        assert subs is None
        assert bad

    def test_non_swe_parent_with_ALL_INVALID_slugs_is_nulled_the_same_way(self):
        """⚠ THE SAME LEAK, THE SAME ANSWER. This branch used to be gated on the
        slugs that SURVIVED validation, so an all-invalid list emptied `slugs`,
        the leak rule never fired, and the row came back `[]` — TERMINAL,
        "evaluated, none apply" — while the identical row carrying a VALID slug
        came back None. A hallucinated slug on a row that is not even
        software_engineering must not be what marks that row evaluated forever."""
        subs, bad, warnings = tax.validate_subcategories("business_ops", ["nonsense_slug"])
        assert subs is None
        assert subs != []
        assert bad          # still a hallucination -> needs_human
        assert warnings == []

    def test_non_swe_parent_with_junk_ELEMENTS_is_nulled_the_same_way(self):
        subs, bad, _ = tax.validate_subcategories("growth", [7, {"a": 1}])
        assert subs is None
        assert bad

    def test_an_EXPLICIT_empty_list_on_a_non_swe_row_stays_empty(self):
        """The other side of the rule, and it must not move: `[]` is RAIL D's
        deliberate output in `cli._merge_judge` — a non-SWE row WAS evaluated and
        the answer is 'not applicable', so it LEAVES the backfill queue rather
        than sitting in it forever."""
        assert tax.validate_subcategories("business_ops", []) == ([], [], [])

    def test_a_SWE_row_whose_slugs_all_drop_still_becomes_empty_not_null(self):
        """§1.2 A: 'if every slug drops the value becomes `[]`, not null'. The
        leak rule must not reach across and null a genuine SWE row."""
        subs, bad, _ = tax.validate_subcategories(SWE, ["nonsense_slug"])
        assert subs == []
        assert bad

    def test_category_none_with_a_list_is_nulled(self):
        subs, bad, _ = tax.validate_subcategories(None, ["backend"])
        assert subs is None
        assert bad

    def test_bare_string_is_wrapped(self):
        assert tax.validate_subcategories(SWE, "backend")[0] == ["backend"]

    @pytest.mark.parametrize("value", [{"a": 1}, 7, True, 3.5])
    def test_non_list_never_raises_and_nulls(self, value):
        subs, bad, warnings = tax.validate_subcategories(SWE, value)
        assert subs is None
        assert bad and bad[0][0] == "subcategories"
        assert warnings == []

    def test_non_string_element_lands_in_bad(self):
        subs, bad, _ = tax.validate_subcategories(SWE, ["backend", 7])
        assert subs == ["backend"]
        assert bad == [("subcategories", "7")]

    def test_truncation_warns_and_is_never_bad(self):
        subs, bad, warnings = tax.validate_subcategories(
            SWE, ["backend", "frontend", "security"]
        )
        assert subs == ["backend", "frontend"]
        assert bad == []  # truncation must NEVER set needs_human
        assert len(warnings) == 1
        assert "truncated" in warnings[0]

    def test_full_stack_suppresses_its_halves_with_a_warning_not_bad(self):
        subs, bad, warnings = tax.validate_subcategories(SWE, ["full_stack", "frontend"])
        assert subs == ["full_stack"]
        assert bad == []
        assert len(warnings) == 1
        assert "exclusive" in warnings[0]

    def test_dedup_preserves_first_seen_order(self):
        subs, bad, _ = tax.validate_subcategories(SWE, ["backend", "backend", "frontend"])
        assert subs == ["backend", "frontend"]
        assert bad == []

    def test_tri_state_empty_list_stays_empty(self):
        # THE TRI-STATE ASSERTION. `[]` = evaluated, no specialty applies —
        # TERMINAL, it leaves the backfill queue forever.
        assert tax.validate_subcategories(SWE, []) == ([], [], [])

    def test_tri_state_none_stays_none(self):
        # `None` = never evaluated. This IS the backfill queue.
        assert tax.validate_subcategories(SWE, None) == (None, [], [])

    def test_none_on_a_non_swe_row_also_stays_none(self):
        assert tax.validate_subcategories("growth", None) == (None, [], [])


def test_validate_facets_arity_is_unchanged():
    # Unpacked POSITIONALLY at cli.py:440 and cli.py:1038, and imported by
    # tests/test_scoring.py. Widening it would break both silently.
    category, level, bad = tax.validate_facets("software_engineering", "senior")
    assert (category, level, bad) == ("software_engineering", "senior", [])


# ---- ENR-TAX-2: the D3 rubric split + provenance ---------------------------
# THE SIZE BUDGET AND THE PROVENANCE TEST ARE THE TWO LOAD-BEARING ONES.
# v6 measured 24,479 chars / 24,619 bytes / 157 lines; the D3 target was ~28,785
# and the rejected inline design would have been ~32,285. The budget assertion is
# what stops someone quietly moving the detailed rubric back into section 1b.
#
# RE-MEASURED at 34,072 chars, and raised to the next 500. TWO independent causes,
# neither of them rubric creep into §1b:
#   +5,041  main's MTS work (#21) — sections 1, 2 and 6, which this branch only
#           inherited at the rebase onto `main`.
#     +579  the 15 -> 17 subcategory widening: two §1b table rows and two rails.
# ⚠ Still the same rule: if this goes red, move the detail to SUBCATEGORIES.md.
# Raise it only after re-measuring AND naming what legitimately grew.
SKILL_MD_MAX_CHARS = 34_500


class TestRubricSplit:
    def test_declared_version_is_v7(self):
        assert tax.declared_version() == "v7"

    def test_the_prohibition_this_epic_repeals_is_gone(self):
        assert "No sub-specialties" not in tax.read_skill()

    def test_top_level_qualifiers_landed(self):
        skill = tax.read_skill()
        assert "Never mint a seventh TOP-LEVEL category" in skill
        assert "separate TOP-LEVEL project_manager category" in skill
        assert "no top-level forward-deployed category" in skill

    def test_section_1b_exists_and_the_heading_order_is_unchanged(self):
        skill = tax.read_skill()
        assert "## 1b." in skill
        headings = [
            line.split(".")[0].removeprefix("## ").strip()
            for line in skill.splitlines()
            if line.startswith("## ")
        ]
        assert headings == ["1", "1b", "2", "3", "4", "5", "6", "7"]

    def test_skill_carries_all_seventeen_slugs(self):
        skill = tax.read_skill()
        for slug in tax.SUBCATEGORIES:
            assert f"`{slug}`" in skill, slug

    def test_rubric_is_non_empty_complete_and_shorter_than_the_skill(self):
        rubric = tax.read_subcategory_rubric()
        assert rubric.strip()
        for slug in tax.SUBCATEGORIES:
            assert f"`{slug}`" in rubric, slug
        assert "exclusive" in rubric
        assert "do you change the weights" in rubric
        # D3's whole point: the detailed rubric is the file the classify lane
        # does NOT pay for, and it must stay smaller than SKILL.md.
        assert len(rubric) < len(tax.read_skill())

    def test_read_subcategory_rubric_RAISES_when_missing(self, tmp_path, monkeypatch):
        """⚠ It must RAISE, not return ''. A silent empty rubric is what makes
        the backfill lane label from nothing while reporting success."""
        monkeypatch.setattr(tax, "SUBCATEGORY_RUBRIC_PATH", tmp_path / "nope.md")
        with pytest.raises(FileNotFoundError):
            tax.read_subcategory_rubric()

    def test_skill_md_stays_under_the_size_budget(self):
        """⚠ A failure here means someone moved detail back into section 1b. The
        fix is to move it to SUBCATEGORIES.md, NOT to raise this constant."""
        assert len(tax.read_skill()) < SKILL_MD_MAX_CHARS


class TestProvenance:
    def test_taxonomy_version_moves_when_the_rubric_changes(self, tmp_path, monkeypatch):
        """THE REGRESSION TEST FOR THE HOLE D3 OPENS. With a SKILL.md-only hash,
        editing SUBCATEGORIES.md would change the rubric that produced a label
        without moving the version recorded beside it."""
        before = tax.taxonomy_version()
        temp = tmp_path / "SUBCATEGORIES.md"
        temp.write_text(tax.read_subcategory_rubric() + "\n<!-- edited -->\n")
        monkeypatch.setattr(tax, "SUBCATEGORY_RUBRIC_PATH", temp)
        assert tax.taxonomy_version() != before

    def test_taxonomy_version_keeps_the_parseable_shape(self):
        import re

        assert re.match(r"^v\d+\+[0-9a-f]{12}$", tax.taxonomy_version())

    def test_content_hash_stays_skill_md_only(self, tmp_path, monkeypatch):
        """⚠ Deliberately unchanged by D3: the v6 baseline must stay reproducible
        from a git blob, which only works while this hashes exactly one file."""
        before = tax.content_hash()
        temp = tmp_path / "SUBCATEGORIES.md"
        temp.write_text(tax.read_subcategory_rubric() + "\n<!-- edited -->\n")
        monkeypatch.setattr(tax, "SUBCATEGORY_RUBRIC_PATH", temp)
        assert tax.content_hash() == before


# ---- ENR-TAX-3: the sandboxed agent specs ----------------------------------
# ⚠ These two files are the prompt for the SANDBOXED sub-agent fan-out — the path
# production keeps for Claude as prompt-injection hardening — and they restate the
# output contract INDEPENDENTLY of prompts.py. Leaving them at v6 would mean the
# sandboxed path silently never emits subcategories.

def _agent(name: str) -> str:
    from job_enricher.store import REPO_ROOT

    return (REPO_ROOT / ".claude" / "agents" / f"{name}.md").read_text(encoding="utf-8")


class TestAgentSpecs:
    def test_both_specs_name_subcategories(self):
        assert "subcategories" in _agent("classifier")
        assert "subcategories" in _agent("judge")

    def test_judge_names_subcategories_inside_the_corrections_whitelist(self):
        """⚠ The judge structurally cannot correct a facet not named there."""
        text = _agent("judge")
        clause = text[text.index("in `corrections` (any of"):]
        assert "`subcategories`" in clause.split(");")[0]

    def test_classifier_points_at_section_1b(self):
        assert "section 1b" in _agent("classifier")

    def test_NEITHER_spec_names_the_detailed_rubric_file(self):
        """THE D3 GUARD. These agents have Read access, so pointing them at the
        detailed rubric would be ONE line — and it would (a) reintroduce the whole
        token cost the split removes, on the exact lane it protects, and (b)
        desynchronize the sandboxed classify lane from the in-process one,
        confounding the v6-vs-v7 A/B by making the two production engines see
        different rubrics."""
        assert "SUBCATEGORIES.md" not in _agent("classifier")
        assert "SUBCATEGORIES.md" not in _agent("judge")

    def test_both_specs_still_pin_themselves_to_skill_md(self):
        for name in ("classifier", "judge"):
            assert ".claude/skills/taxonomy/SKILL.md" in _agent(name), name


# ---- ENR-PAR-1: the INTRA-REPO drift guard ---------------------------------
#
# Blocker #6 is enum drift on a codebase where it HAS ALREADY HAPPENED: JVN's
# job_categories has 7 rows, `taxonomy.CATEGORIES` has 6, and the frontend
# fallback has 7 — all three re-verified. D3 adds a FIFTH surface to guard,
# because the slugs now live in TWO markdown files instead of one.
#
# ⚠ THE ONE GUARD THIS FILE CANNOT PROVIDE is a live check of JVN's
# `/api/jobs/facets` against `tax.SUBCATEGORIES`. That is `ENR-PAR-2`, in
# `tests/test_cross_repo_parity.py` plus `cli parity-check`. Nothing here crosses
# the repo boundary, which is precisely how the 6-vs-7 drift survived.

def _slug_cells(table_text: str) -> set[str]:
    """Every `| `slug` |` cell in a markdown table body."""
    import re

    return set(re.findall(r"^\|\s*`([a-z_]+)`\s*\|", table_text, re.MULTILINE))


def _section_1b(skill: str) -> str:
    start = skill.index("## 1b.")
    rest = skill[start:]
    return rest[: rest.index("\n## ")]


class TestIntraRepoParity:
    def test_1_section_1b_table_matches_the_frozenset_BOTH_DIRECTIONS(self):
        """A one-way check misses a slug added only to the file."""
        cells = _slug_cells(_section_1b(tax.read_skill()))
        assert cells == set(tax.SUBCATEGORIES)

    def test_2_subcategories_md_table_matches_the_frozenset_BOTH_DIRECTIONS(self):
        """⚠ THE ASSERTION D3 MAKES NECESSARY: two files, two tables, one frozenset."""
        cells = _slug_cells(tax.read_subcategory_rubric())
        assert cells == set(tax.SUBCATEGORIES)

    def test_3_ollama_enum_is_the_sorted_frozenset_AS_AN_ORDERED_LIST(self):
        """This is WHY ENR-ENG-3 builds the schema from the frozenset rather than
        typing a literal."""
        from job_enricher.engines.ollama import _SUBCATEGORY_SCHEMA

        enum = _SUBCATEGORY_SCHEMA["items"]["properties"]["subcategories"]["items"]["enum"]
        assert enum == sorted(tax.SUBCATEGORIES)

    def test_4_the_two_prompts_see_exactly_what_they_should(self):
        from job_enricher.engines.prompts import (
            build_classify_prompt,
            build_subcategory_prompt,
            reset_taxonomy_cache,
        )

        reset_taxonomy_cache()
        job = {
            "job_listing_id": "1", "source_id": "gh", "title": "SWE",
            "company": "Acme", "raw_location": "SF", "tags": ["backend"],
            "clean_description": "build things",
        }
        classify = build_classify_prompt([job])
        subcat = build_subcategory_prompt([job])
        rubric = tax.read_subcategory_rubric()

        # the compact section 1b DOES reach the model through the inlining...
        for slug in tax.SUBCATEGORIES:
            assert slug in classify, slug
            assert slug in subcat, slug
        # ...and the split HELD: the detailed rubric is in one prompt, not both
        assert rubric not in classify
        assert "Silicon Validation Software Engineer" not in classify
        assert "Silicon Validation Software Engineer" in subcat

    def test_5_the_two_files_must_not_version_drift_apart(self):
        import re

        skill_v = tax.declared_version()
        m = re.search(r"^version:\s*(\S+)\s*$", tax.read_subcategory_rubric(), re.MULTILINE)
        assert m is not None, "SUBCATEGORIES.md has no frontmatter version:"
        assert m.group(1) == skill_v
        assert "No sub-specialties" not in tax.read_skill()
        assert skill_v == "v7"

    def test_taxonomy_version_moves_when_subcategories_md_changes(self, tmp_path, monkeypatch):
        before = tax.taxonomy_version()
        temp = tmp_path / "SUBCATEGORIES.md"
        temp.write_text(tax.read_subcategory_rubric() + "\n<!-- drift -->\n")
        monkeypatch.setattr(tax, "SUBCATEGORY_RUBRIC_PATH", temp)
        assert tax.taxonomy_version() != before
