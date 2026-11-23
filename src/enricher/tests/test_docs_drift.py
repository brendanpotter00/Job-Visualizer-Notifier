"""EV-17: docs that go stale silently.

Every assertion here guards a claim a reader will ACT on. STRATIFICATION.md is
the only artifact telling a future reader what the sample covers, and it had
been wrong about the row count and the category enum for long enough that the
file's own note half-admitted it.
"""

import re

from job_enricher.eval.golden import load_seed
from job_enricher.store import REPO_ROOT
from job_enricher.taxonomy import CATEGORIES, SUBCATEGORIES

STRATIFICATION = REPO_ROOT / "golden" / "seed" / "STRATIFICATION.md"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
EVAL_INIT = REPO_ROOT / "src" / "job_enricher" / "eval" / "__init__.py"

# Slugs that were in STRATIFICATION.md's matrix but have NEVER been v6 or v7
# category slugs. This is the specific regression the "no slug outside it" rule
# exists to catch.
RETIRED_CATEGORY_SLUGS = ("data_engineer", "business", "project_manager")


def _strat() -> str:
    return STRATIFICATION.read_text(encoding="utf-8")


def test_every_subcategory_slug_appears_in_the_stratification_table():
    text = _strat()
    missing = [s for s in sorted(SUBCATEGORIES) if f"`{s}`" not in text]
    assert missing == [], missing
    assert len(SUBCATEGORIES) == 17


def test_every_category_slug_appears_and_no_retired_slug_does():
    """⚠ This is what catches `data_engineer` / `business` regressing back in."""
    text = _strat()
    missing = [c for c in sorted(CATEGORIES) if c not in text]
    assert missing == [], missing
    for retired in RETIRED_CATEGORY_SLUGS:
        # word-boundary: `business` must not match inside `business_ops`, and
        # `data_engineer` must not match inside `data_engineering`.
        # Blockquote lines are the CHANGE NOTE explaining what was removed —
        # prose about the fix, not data. Everything else is the sample.
        hits = [
            line for line in text.splitlines()
            if not line.lstrip().startswith(">")
            and re.search(rf"\b{retired}\b", line)
        ]
        assert hits == [], (retired, hits)


def test_the_stated_total_row_count_matches_the_seed():
    rows = load_seed()
    assert rows, "no golden seed committed"
    m = re.search(r"Total rows:\s*\*\*(\d+)\*\*", _strat())
    assert m, "STRATIFICATION.md no longer states a total row count"
    assert int(m.group(1)) == len(rows)


def test_the_false_cross_repo_gate_claim_is_gone_from_eval_init():
    """⚠ Nothing in JVN re-verifies this gate. A plan assuming a second,
    independent check is relying on a mechanism that does not exist."""
    text = EVAL_INIT.read_text(encoding="utf-8")
    assert "identical everywhere" not in text
    assert "FALSE" in text and "JVN" in text


def test_claude_md_no_longer_claims_the_gate_runs_in_jvn():
    text = CLAUDE_MD.read_text(encoding="utf-8")
    assert "here, in the personal dir, and in JVN identically" not in text
    assert "Verified FALSE" in text


def test_claude_md_documents_both_pools_and_the_new_commands():
    text = CLAUDE_MD.read_text(encoding="utf-8")
    for needle in (
        "load_truth(facet='subcategory')",
        "gold_subcategory_provenance",
        "human_audited",
        "prelabel_agreed",
        "contract",
        "weak_rule",
        "subcategory-weak-baseline",
        "review-build",
        "review-render",
        "review-apply",
        "prelabel --facet",
    ):
        assert needle in text, needle


def test_the_engine_comparison_advisory_status_names_what_retires_it():
    text = (REPO_ROOT / "docs" / "ENGINE-COMPARISON.md").read_text(encoding="utf-8")
    assert "ADVISORY (n=21 < the gate's 50-row floor)" in text
    assert "EV-2b" in text
    assert "NET-NEGATIVE" in text


def test_claude_md_no_longer_calls_the_weak_baseline_a_day_one_gate():
    """⚠ It never was one. The rule labeler needs no human labels, but scoring
    it needs a non-empty `load_truth(facet='subcategory')` — 0 rows until
    EV-9b. CLAUDE.md used to advertise it as 'the day-one G2 gate, zero human
    labels' while the protocol doc's own P5/G2 rows said CANNOT RUN until P4."""
    text = CLAUDE_MD.read_text(encoding="utf-8")
    assert "the day-one G2 gate" not in text
    assert "NOT a day-one gate" in text
    assert "gate_ready" in text
    protocol = (REPO_ROOT / "docs" / "EVAL-V6-V7-PROTOCOL.md").read_text(encoding="utf-8")
    assert "**CANNOT RUN** — needs P4" in protocol
