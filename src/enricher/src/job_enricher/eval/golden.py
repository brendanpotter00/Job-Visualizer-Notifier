"""Build + load the golden set.

`build_golden_set` pulls a stratified raw sample from JVN into golden/seed/ as
UNLABELED rows (label_source empty). A human (or judge-bootstrap + spot check)
fills category/level/tags/locations. Only rows with label_source='human' count
as ground truth for the regression gate; judge-bootstrapped rows are advisory.

⚠ DRAFT LABELS ARE v6's OWN OUTPUT. `label_source='draft'` means the row was
judge-bootstrapped by the pipeline, so scoring against them measures AGREEMENT
WITH v6, not accuracy — a genuinely better v7 scores WORSE. report.py stamps
that on every `--allow-draft` headline.

TWO POOLS, TWO DENOMINATORS. The category pool is gated on `label_source`; the
subcategory pool is gated on `gold_subcategory_provenance`, a SEPARATE column
with a DISJOINT vocabulary (`human | human_audited | prelabel_agreed |
contract`). ⚠ It is deliberately not named `subcategory_source` — that name
belongs to the WRITE path (`rule | classify | backfill | judge | human`) and two
similarly-named columns with disjoint enums is exactly how a gate ends up
admitting rows it should not. Decoupling them is what lets each facet gate on
its own honest denominator.
"""

from __future__ import annotations

import json
from pathlib import Path

from job_enricher.store import REPO_ROOT

SEED_DIR = REPO_ROOT / "golden" / "seed"
SCORECARD_DIR = REPO_ROOT / "golden" / "scorecards"
REVIEW_DIR = REPO_ROOT / "golden" / "review"
SEED_FILE = SEED_DIR / "golden.json"

SUBCATEGORY_PARENT = "software_engineering"

# Provenances admitted into the subcategory gate pool WITHOUT an audit.
_GOLD_SOURCES: frozenset[str] = frozenset({"human", "human_audited"})
# Admitted ONLY when `golden/seed/<facet>_audit.json` reports `passed: true`.
_AUDITED_SOURCE = "prelabel_agreed"
# ⚠ NEVER admitted. `stamp_contract_rows` sets this on the 150 non-SWE rows so
# `subcategory_leak_rate` is measurable at zero model cost — but they carry NO
# information about the subcategory taxonomy, so admitting them would clear
# GATE_MIN_N=50 on an empty pool. That is the fake-n trap.
_CONTRACT_SOURCE = "contract"

# The six fields that come FROM JVN on every `build_golden_set` refresh. Every
# other key on a seed row is a LABEL and must survive the rebuild.
_JVN_SOURCED_FIELDS = (
    "job_listing_id", "source_id", "title", "company", "raw_location",
    "description_html",
)

# The label side of a seed row, with its blank defaults. ⚠ This is a DEFAULT
# floor, never an overwrite: `build_golden_set` merges it UNDER the previous row.
_LABEL_DEFAULTS: dict = {
    "label_source": "",
    "category": None,
    "level": None,
    "level_includes": None,
    "tags": None,
    "locations": None,
    # --- subcategory facet -------------------------------------------------
    "subcategories": None,
    "gold_subcategory_provenance": None,
    # --- generic per-facet pre-label provenance (facet in {category, subcategory})
    "category_prelabel": None,
    "category_prelabel_model": None,
    "category_prelabel_confidence": None,
    "subcategory_prelabel": None,
    "subcategory_prelabel_model": None,
    "subcategory_prelabel_confidence": None,
    # ⚠ THERE IS NO HOLDOUT TODAY: all 273 rows serve as dev AND test, and the
    # v6 SKILL.md few-shots were drawn from golden rows. Any v7 few-shot must be
    # marked split='train' and is then EXCLUDED from every gate pool.
    "split": None,
}


def build_golden_set(n: int = 150, stratify: str = "company") -> Path:
    """Refresh the JVN-sourced half of every seed row, PRESERVING all labels.

    ⚠ THE LANDMINE THIS FIXES. The old implementation rebuilt each row from a
    12-key literal, so any key outside that literal was DESTROYED on the next
    run. Measured against the live seed: the key union is SIXTEEN and the
    rebuild destroyed FOUR — `clean_description`, `department`, `hard_case`,
    `human_decision`. It silently loses work; there is no error and no diff to
    read afterwards. The merge below is `{defaults, **prev, **fresh}` where
    `fresh` is ONLY the six JVN-sourced fields, so an unknown key is carried
    through untouched by construction.
    """
    from job_enricher.jvn_client import JVNClient

    SEED_DIR.mkdir(parents=True, exist_ok=True)
    jobs = JVNClient().sample(n=n, stratify=stratify)
    existing = {r["job_listing_id"]: r for r in load_seed()}
    rows = []
    for j in jobs:
        prev = existing.get(j["job_listing_id"], {})
        fresh = {k: j.get(k) for k in _JVN_SOURCED_FIELDS}
        rows.append({**_LABEL_DEFAULTS, **prev, **fresh})
    SEED_FILE.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return SEED_FILE


def load_seed() -> list[dict]:
    if not SEED_FILE.exists():
        return []
    return json.loads(SEED_FILE.read_text(encoding="utf-8"))


def save_seed(rows: list[dict]) -> Path:
    SEED_DIR.mkdir(parents=True, exist_ok=True)
    SEED_FILE.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return SEED_FILE


PARAM_AUDIT_DEFAULT_THRESHOLD_DOC = (
    "PARAM_AUDIT_MAX = max(0.05, min(0.15, ceil(PARAM_PRELABEL_ERROR_RATE/0.05)*0.05)); "
    "PARAM_PRELABEL_ERROR_RATE comes from category_audit.json (EV-2b)"
)


def audit_path(facet: str) -> Path:
    return SEED_DIR / f"{facet}_audit.json"


def audit_passed(facet: str) -> bool:
    """⚠ MISSING FILE == NOT PASSED. The whole promotion mechanism hangs on this
    default: a `prelabel_agreed` row is a row a MODEL labelled and a regex
    agreed with, and it may only enter the gate pool once a human-reviewed
    sample has measured the pre-labeller's error rate at or below threshold. A
    missing/unreadable audit file means that measurement never happened."""
    path = audit_path(facet)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return False
    return isinstance(data, dict) and data.get("passed") is True


def _admitted_subcategory_sources() -> frozenset[str]:
    if audit_passed("subcategory"):
        return _GOLD_SOURCES | {_AUDITED_SOURCE}
    return _GOLD_SOURCES


def load_truth(human_only: bool = True, facet: str | None = None) -> list[dict]:
    """Gold rows for the scorer.

    ``facet=None`` (the default) is the CATEGORY/level/tags/location pool, gated
    on ``label_source``.

    ``facet='subcategory'`` is a SEPARATE pool with its own denominator: SWE
    parent + a non-null ``subcategories`` + an admitted
    ``gold_subcategory_provenance``. ⚠ Contract rows are NEVER admitted (see
    ``_CONTRACT_SOURCE``), and ``prelabel_agreed`` rows only when the audit
    passed.

    ⚠ The base predicate used to be `category or level`, which made a
    SUBCATEGORY-ONLY correction invisible to the loader — the row had gold and
    the pool did not see it. `subcategories is not None` is now part of it.

    ``split='train'`` rows are excluded from every pool: they are the rows a v7
    few-shot may be drawn from, and scoring against your own few-shots is not a
    gate.
    """
    rows = [r for r in load_seed() if r.get("split") != "train"]
    if facet == "subcategory":
        admitted = _admitted_subcategory_sources()
        return [
            r for r in rows
            if r.get("category") == SUBCATEGORY_PARENT
            and r.get("subcategories") is not None
            and r.get("gold_subcategory_provenance") in admitted
        ]
    labeled = [
        r for r in rows
        if r.get("category") or r.get("level") or r.get("subcategories") is not None
    ]
    if human_only:
        labeled = [r for r in labeled if r.get("label_source") == "human"]
    return labeled


def stamp_contract_rows() -> int:
    """Set `subcategories: []` + provenance `'contract'` on every NON-SWE row.

    Free — zero model calls. It is what makes `subcategory_leak_rate` measurable:
    without a gold value on the non-SWE rows the scorer has nothing to compare a
    leaked prediction against.

    ⚠ These rows must NEVER be admitted by `load_truth(facet='subcategory')`.
    150 of the 285 seed rows are non-SWE, so admitting them would clear
    `GATE_MIN_N = 50` three times over on a pool carrying ZERO information about
    the subcategory taxonomy. That is the fake-n trap, and `_CONTRACT_SOURCE`
    being absent from `_admitted_subcategory_sources()` is the guard.

    Returns the number of rows changed. Idempotent.
    """
    rows = load_seed()
    changed = 0
    for row in rows:
        if row.get("category") == SUBCATEGORY_PARENT:
            continue
        if (
            row.get("subcategories") == []
            and row.get("gold_subcategory_provenance") == _CONTRACT_SOURCE
        ):
            continue
        row["subcategories"] = []
        row["gold_subcategory_provenance"] = _CONTRACT_SOURCE
        changed += 1
    if changed:
        save_seed(rows)
    return changed


def _level_includes_for(level: str | None) -> list[str] | None:
    if level is None:
        return None
    return ["new_grad", "entry"] if level == "new_grad" else [level]


def merge_corrections(corrections: list[dict]) -> dict[str, int]:
    """Fold JVN admin (human) corrections into the golden seed.

    Corrections are matched to golden rows by the composite
    (source_id, job_listing_id) pair. A matched row gets its category/level/
    tags/subcategories replaced by the corrected values (level_includes
    re-derived from the level hierarchy) and its label_source upgraded to
    'human' — this is how the admin triage queue turns into real gold labels
    over time.

    ⚠ AN ABSENT FACET KEY NEVER OVERWRITES AN EXISTING LABEL. The `if facet in c`
    guard is the tolerant parse: a correction that says nothing about
    subcategories leaves the gold subcategories alone. A pre-v7 correction has
    no `subcategories` key at all, so replaying the whole correction history
    cannot null the facet.

    ⚠ THE ARROW NEVER RUNS BACKWARDS. A correction that moves a row OFF
    `software_engineering` forces `subcategories = []` with provenance
    `'contract'` in the SAME write — a subcategory on a non-SWE row is not gold,
    it is a leak, and leaving the old list there would score it as gold.

    ⚠ NO-APPEND, DECIDED AND WRITTEN DOWN (see EV-16, which implements the
    parked worklist): unmatched corrections are NOT appended to the seed as new
    rows. Three verified reasons — (1) `/corrections` returns no description
    text, so an appended row would classify TITLE-ONLY, which the prompt caps at
    confidence <= 0.5 and `TITLE_ONLY_MAX_CONFIDENCE` clamps in code, depressing
    accuracy and distorting calibration for reasons unrelated to the taxonomy;
    (2) the feed's `tags` are enricher-origin, so appending them as gold `tags`
    is self-labelling into `tags_token_f1`, a GATED facet; (3) appending between
    the v6 and v7 arms breaks the row-set identity the paired test needs. They
    are PARKED, not discarded.

    Returns {"matched", "upgraded", "unmatched", "parked", "subcategory_upgraded"}.

    ⚠ `subcategory_upgraded` is counted SEPARATELY from `upgraded` on purpose:
    a pre-v7 feed (no `subcategories` key at all) still upgrades category gold,
    so `upgraded=N` alone cannot tell a caller whether any SUBCATEGORY gold was
    written. `cli golden-merge` prints it and refuses when the feed is missing
    the v7 keys.
    """
    rows = load_seed()
    by_key = {(r.get("source_id"), r.get("job_listing_id")): r for r in rows}
    matched = 0
    upgraded = 0
    subcategory_upgraded = 0
    unmatched: list[dict] = []
    for c in corrections:
        key = (c.get("source_id"), c.get("job_listing_id"))
        row = by_key.get(key)
        if row is None:
            unmatched.append(c)
            continue
        matched += 1
        changed = row.get("label_source") != "human"
        for facet in ("category", "level", "tags", "subcategories"):
            if facet in c and row.get(facet) != c[facet]:
                row[facet] = c[facet]
                changed = True
        if "subcategories" in c:
            row["gold_subcategory_provenance"] = "human"
        if "level" in c:
            row["level_includes"] = _level_includes_for(c.get("level"))
        row["label_source"] = "human"
        if row.get("category") != SUBCATEGORY_PARENT:
            row["subcategories"] = []
            row["gold_subcategory_provenance"] = _CONTRACT_SOURCE
        if changed:
            upgraded += 1
        if "subcategories" in c and row.get("gold_subcategory_provenance") == "human":
            subcategory_upgraded += 1
    if matched:
        save_seed(rows)
    parked = park_unmatched(unmatched)
    return {
        "matched": matched,
        "upgraded": upgraded,
        "unmatched": len(unmatched),
        "parked": parked,
        "subcategory_upgraded": subcategory_upgraded,
    }


UNMATCHED_WORKLIST = REVIEW_DIR / "unmatched-corrections.json"

# ⚠ THE EXACT CHANGE THAT WOULD LET US REVISIT NO-APPEND, recorded and NOT
# built: add `{DESCRIPTION_SQL} AS description_html` to JVN's
# `list_corrections_since` SELECT and echo it in the response dict. Only then
# does an appended row classify on the same input the seeded rows do, and only
# then is `--append-unmatched` buildable.
_NO_APPEND_FOLLOWUP = "JVN list_corrections_since: SELECT description_html"


def park_unmatched(corrections: list[dict]) -> int:
    """Append unmatched corrections to a worklist. ⚠ NOT DISCARDED, PARKED.

    Append-only and DEDUPED on the (source_id, job_listing_id) pair, so
    replaying the correction feed cannot grow the file without bound. Returns
    the number of NEW entries written.

    The admin correction loop is a SUSTAINING mechanism, not a bootstrap: the
    triage queue pages `enriched_at DESC` over ~76k listings against 273 seeded
    rows — a ~0.36% hit rate that produced 21 gold rows in a year. Anything
    claiming this feed alone reaches GATE_MIN_N=50 is wrong; EV-2b and EV-9b
    are the bootstrap.
    """
    if not corrections:
        return 0
    existing: list[dict] = []
    if UNMATCHED_WORKLIST.exists():
        try:
            loaded = json.loads(UNMATCHED_WORKLIST.read_text(encoding="utf-8"))
            existing = [e for e in loaded if isinstance(e, dict)]
        except (ValueError, OSError):
            existing = []
    seen = {(e.get("source_id"), e.get("job_listing_id")) for e in existing}
    added = 0
    for c in corrections:
        key = (c.get("source_id"), c.get("job_listing_id"))
        if key in seen:
            continue
        seen.add(key)
        existing.append(c)
        added += 1
    if added:
        UNMATCHED_WORKLIST.parent.mkdir(parents=True, exist_ok=True)
        UNMATCHED_WORKLIST.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    return added
