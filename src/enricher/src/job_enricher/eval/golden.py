"""Build + load the golden set.

`build_golden_set` pulls a stratified raw sample from JVN into golden/seed/ as
UNLABELED rows (label_source empty). A human (or judge-bootstrap + spot check)
fills category/level/tags/locations. Only rows with label_source='human' count
as ground truth for the regression gate; judge-bootstrapped rows are advisory.
"""

from __future__ import annotations

import json
from pathlib import Path

from job_enricher.store import REPO_ROOT

SEED_DIR = REPO_ROOT / "golden" / "seed"
SCORECARD_DIR = REPO_ROOT / "golden" / "scorecards"
SEED_FILE = SEED_DIR / "golden.json"


def build_golden_set(n: int = 150, stratify: str = "company") -> Path:
    from job_enricher.jvn_client import JVNClient

    SEED_DIR.mkdir(parents=True, exist_ok=True)
    jobs = JVNClient().sample(n=n, stratify=stratify)
    existing = {r["job_listing_id"]: r for r in load_seed()}
    rows = []
    for j in jobs:
        prev = existing.get(j["job_listing_id"], {})
        rows.append(
            {
                "job_listing_id": j["job_listing_id"],
                "source_id": j["source_id"],
                "title": j["title"],
                "company": j["company"],
                "raw_location": j["raw_location"],
                "description_html": j["description_html"],
                # labels — preserved if already present, else blank for a human
                "label_source": prev.get("label_source", ""),
                "category": prev.get("category"),
                "level": prev.get("level"),
                "level_includes": prev.get("level_includes"),
                "tags": prev.get("tags"),
                "locations": prev.get("locations"),
            }
        )
    SEED_FILE.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return SEED_FILE


def load_seed() -> list[dict]:
    if not SEED_FILE.exists():
        return []
    return json.loads(SEED_FILE.read_text(encoding="utf-8"))


def load_truth(human_only: bool = True) -> list[dict]:
    rows = load_seed()
    labeled = [r for r in rows if r.get("category") or r.get("level")]
    if human_only:
        labeled = [r for r in labeled if r.get("label_source") == "human"]
    return labeled


def _level_includes_for(level: str | None) -> list[str] | None:
    if level is None:
        return None
    return ["new_grad", "entry"] if level == "new_grad" else [level]


def merge_corrections(corrections: list[dict]) -> dict[str, int]:
    """Fold JVN admin (human) corrections into the golden seed.

    Corrections are matched to golden rows by the composite
    (source_id, job_listing_id) pair. A matched row gets its category/level/
    tags replaced by the corrected values (level_includes re-derived from the
    level hierarchy) and its label_source upgraded to 'human' — this is how
    the admin triage queue turns into real gold labels over time.

    Returns {"matched", "upgraded", "unmatched"}:
      - matched    corrections that found a golden row
      - upgraded   golden rows actually changed (labels and/or label_source)
      - unmatched  corrections with no golden row (not an error — the golden
                   set is a sample, corrections cover the whole corpus)
    """
    rows = load_seed()
    by_key = {(r.get("source_id"), r.get("job_listing_id")): r for r in rows}
    matched = 0
    upgraded = 0
    unmatched = 0
    for c in corrections:
        key = (c.get("source_id"), c.get("job_listing_id"))
        row = by_key.get(key)
        if row is None:
            unmatched += 1
            continue
        matched += 1
        changed = row.get("label_source") != "human"
        for facet in ("category", "level", "tags"):
            if facet in c and row.get(facet) != c[facet]:
                row[facet] = c[facet]
                changed = True
        if "level" in c:
            row["level_includes"] = _level_includes_for(c.get("level"))
        row["label_source"] = "human"
        if changed:
            upgraded += 1
    if matched:
        SEED_FILE.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return {"matched": matched, "upgraded": upgraded, "unmatched": unmatched}
