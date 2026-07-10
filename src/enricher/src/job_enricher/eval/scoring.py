"""Pure scoring functions — no network, no key, fully unit-testable.

Facets scored: category, level (hierarchy-aware), tags, location.
The level scorer reports BOTH `exact` and `filter_consistent` because of the
new_grad ⊂ entry contract: predicting `entry` for a true `new_grad` is a HIT for
the entry filter but a MISS for the new_grad filter. Also: judge agreement
(Cohen's κ) and a confidence-calibration signal.

Tags are scored several complementary ways because exact set-match is unfair
when gold and prediction disagree on *granularity* rather than *meaning*
(e.g. gold `{motion, planning}` vs pred `{motion-planning}`, or a short
title-token gold set vs a richer real-skill prediction). Reported metrics:
  - `tags_f1` / `tags_precision` / `tags_recall_micro`: strict exact set-match,
    micro-averaged. Kept unchanged for continuity; penalizes granularity gaps.
  - `tags_jaccard`: per-row mean of |pred∩gold| / |pred∪gold|. Both-empty rows
    (union is empty) are defined as 1.0 (both agree there are no tags) and are
    INCLUDED in the mean, mirroring how a perfect agreement should score.
  - `tags_overlap`: per-row mean overlap coefficient |pred∩gold| / min(|pred|,
    |gold|). Rows where either side is empty are SKIPPED (min is 0/undefined).
  - `tags_recall`: per-row mean of |pred∩gold| / |gold|. Rows with empty gold
    are SKIPPED. This is the fair headline recall (macro over rows), distinct
    from the micro `tags_recall_micro`.
  - `tags_token_f1`: micro P/R/F1 after splitting EACH tag on `-` into lowercase
    tokens, so gold `{motion, planning}` vs pred `{motion-planning}` credits both
    tokens instead of scoring zero.
All tag metrics are pure/deterministic — no randomness, no clock, no synonym
map derived from model output.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

# Canonical slug sets live in taxonomy.py (single source of truth, shared with
# the write-back validation path). Imported here so the scorer and the ingest
# validator can never drift apart.
from job_enricher.taxonomy import CATEGORIES, LEVELS  # noqa: F401  (LEVELS re-exported)

# level -> the filter set it should satisfy (mirrors SKILL.md level_includes)
LEVEL_INCLUDES: dict[str, set[str]] = {
    "new_grad": {"new_grad", "entry"},
    "entry": {"entry"},
    "mid": {"mid"},
    "senior": {"senior"},
    "senior_plus": {"senior_plus"},
    "manager": {"manager"},
}


@dataclass
class FacetScore:
    n: int = 0
    correct: int = 0

    @property
    def accuracy(self) -> float:
        return self.correct / self.n if self.n else 0.0


@dataclass
class PRF:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        d = self.tp + self.fp
        return self.tp / d if d else 0.0

    @property
    def recall(self) -> float:
        d = self.tp + self.fn
        return self.tp / d if d else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


@dataclass
class Scorecard:
    category: FacetScore = field(default_factory=FacetScore)
    category_per_class: dict[str, PRF] = field(default_factory=lambda: defaultdict(PRF))
    level_exact: FacetScore = field(default_factory=FacetScore)
    level_filter_consistent: FacetScore = field(default_factory=FacetScore)
    tags: PRF = field(default_factory=PRF)
    tags_token: PRF = field(default_factory=PRF)
    # per-row fair tag aggregates (see module docstring for empty-set handling)
    tags_jaccard_sum: float = 0.0
    tags_jaccard_n: int = 0
    tags_overlap_sum: float = 0.0
    tags_overlap_n: int = 0
    tags_recall_sum: float = 0.0
    tags_recall_n: int = 0
    location_primary: FacetScore = field(default_factory=FacetScore)
    clean_residual_html: int = 0
    # calibration: does low classify-confidence actually predict errors?
    conf_error_below: int = 0
    conf_below_total: int = 0
    conf_error_above: int = 0
    conf_above_total: int = 0
    # judge agreement — κ between the judge's pass/fail verdict and whether the
    # PRE-judge (classify-only) labels matched gold. Requires the judge-off
    # prediction file; None when unavailable.
    judge_kappa_prejudge: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "category_accuracy": round(self.category.accuracy, 4),
            "category_f1_macro": round(self._macro_f1(), 4),
            "level_exact_accuracy": round(self.level_exact.accuracy, 4),
            "level_filter_consistent_accuracy": round(self.level_filter_consistent.accuracy, 4),
            # exact set-match (strict, micro-averaged) — unchanged for continuity
            "tags_f1": round(self.tags.f1, 4),
            "tags_precision": round(self.tags.precision, 4),
            "tags_recall_micro": round(self.tags.recall, 4),
            # fair tag metrics (granularity-tolerant) — see module docstring
            "tags_jaccard": round(self.tags_jaccard_sum / self.tags_jaccard_n, 4)
            if self.tags_jaccard_n else 1.0,
            "tags_overlap": round(self.tags_overlap_sum / self.tags_overlap_n, 4)
            if self.tags_overlap_n else None,
            "tags_recall": round(self.tags_recall_sum / self.tags_recall_n, 4)
            if self.tags_recall_n else 0.0,
            "tags_token_f1": round(self.tags_token.f1, 4),
            "tags_token_precision": round(self.tags_token.precision, 4),
            "tags_token_recall": round(self.tags_token.recall, 4),
            "location_primary_accuracy": round(self.location_primary.accuracy, 4),
            "clean_residual_html": self.clean_residual_html,
            "calibration_error_rate_below": round(
                self.conf_error_below / self.conf_below_total, 4
            ) if self.conf_below_total else None,
            "calibration_error_rate_above": round(
                self.conf_error_above / self.conf_above_total, 4
            ) if self.conf_above_total else None,
            "judge_kappa_prejudge": (
                None if self.judge_kappa_prejudge is None
                else round(self.judge_kappa_prejudge, 4)
            ),
            "n": self.category.n,
        }

    def _macro_f1(self) -> float:
        """Macro-F1 over the categories with SUPPORT (tp+fp+fn > 0). Averaging
        over zero-support classes structurally dilutes the metric — with half
        the taxonomy unused, a 10-point regression in a live class moved the
        old all-classes average by less than the gate epsilon."""
        supported = [p for p in self.category_per_class.values() if (p.tp + p.fp + p.fn) > 0]
        if not supported:
            return 0.0
        return sum(p.f1 for p in supported) / len(supported)


def _norm_tags(tags: Iterable[str] | None) -> set[str]:
    return {t.strip().lower() for t in (tags or []) if t and t.strip()}


def _tag_tokens(tags: set[str]) -> set[str]:
    """Split each already-normalized tag on `-` into its component tokens.

    `{motion-planning}` -> `{motion, planning}`; `{python}` -> `{python}`. Used
    for the token-level tag F1 so hyphenation granularity does not cost credit.
    """
    out: set[str] = set()
    for tag in tags:
        for tok in tag.split("-"):
            tok = tok.strip()
            if tok:
                out.add(tok)
    return out


def _primary_location_key(locations: list[dict[str, Any]] | None) -> str | None:
    if not locations:
        return None
    primary = next((l for l in locations if l.get("isPrimary") or l.get("is_primary")), locations[0])
    return (primary.get("canonicalName") or primary.get("canonical_name") or "").strip().lower() or None


def score(
    predictions: list[dict[str, Any]],
    truth: list[dict[str, Any]],
    conf_threshold: float = 0.80,
    prejudge_predictions: list[dict[str, Any]] | None = None,
) -> Scorecard:
    """predictions and truth are aligned by job_listing_id.

    ``prejudge_predictions`` (the judge-off run of the SAME rows) unlocks
    ``judge_kappa_prejudge``: the judge's verdict is compared against whether
    the PRE-judge labels matched gold. Computing κ on post-correction labels —
    the old behavior — counted every successful correction AGAINST the judge."""
    truth_by_id = {t["job_listing_id"]: t for t in truth}
    sc = Scorecard()

    for pred in predictions:
        gold = truth_by_id.get(pred["job_listing_id"])
        if gold is None:
            continue

        # category
        sc.category.n += 1
        p_cat, g_cat = pred.get("category"), gold.get("category")
        cat_correct = p_cat == g_cat
        if cat_correct:
            sc.category.correct += 1
        for c in CATEGORIES:
            prf = sc.category_per_class[c]
            if p_cat == c and g_cat == c:
                prf.tp += 1
            elif p_cat == c and g_cat != c:
                prf.fp += 1
            elif p_cat != c and g_cat == c:
                prf.fn += 1

        # level — exact + filter-consistent
        sc.level_exact.n += 1
        p_lvl, g_lvl = pred.get("level"), gold.get("level")
        level_correct = p_lvl == g_lvl
        if level_correct:
            sc.level_exact.correct += 1
        sc.level_filter_consistent.n += 1
        if _filter_consistent(p_lvl, g_lvl):
            sc.level_filter_consistent.correct += 1

        # tags — strict exact set P/R/F1 (micro)
        p_tags, g_tags = _norm_tags(pred.get("tags")), _norm_tags(gold.get("tags"))
        inter = len(p_tags & g_tags)
        sc.tags.tp += inter
        sc.tags.fp += len(p_tags - g_tags)
        sc.tags.fn += len(g_tags - p_tags)

        # tags — fair, granularity-tolerant per-row metrics
        union = len(p_tags | g_tags)
        # jaccard: both-empty (union==0) counts as perfect agreement (1.0)
        sc.tags_jaccard_sum += 1.0 if union == 0 else inter / union
        sc.tags_jaccard_n += 1
        # overlap coefficient: only meaningful when BOTH sides are non-empty
        if p_tags and g_tags:
            sc.tags_overlap_sum += inter / min(len(p_tags), len(g_tags))
            sc.tags_overlap_n += 1
        # per-row recall: skip rows with no gold tags
        if g_tags:
            sc.tags_recall_sum += inter / len(g_tags)
            sc.tags_recall_n += 1
        # token-level micro P/R/F1 (split each tag on '-')
        p_tok, g_tok = _tag_tokens(p_tags), _tag_tokens(g_tags)
        sc.tags_token.tp += len(p_tok & g_tok)
        sc.tags_token.fp += len(p_tok - g_tok)
        sc.tags_token.fn += len(g_tok - p_tok)

        # location — primary canonical match
        if gold.get("locations") is not None:
            sc.location_primary.n += 1
            if _primary_location_key(pred.get("locations")) == _primary_location_key(gold.get("locations")):
                sc.location_primary.correct += 1

        # clean sanity
        from job_enricher.clean import has_residual_html

        if pred.get("clean_description") and has_residual_html(pred["clean_description"]):
            sc.clean_residual_html += 1

        # calibration — treat a row as "error" if category OR level wrong
        row_error = not (cat_correct and level_correct)
        conf = pred.get("confidence")
        if conf is not None:
            if conf < conf_threshold:
                sc.conf_below_total += 1
                sc.conf_error_below += int(row_error)
            else:
                sc.conf_above_total += 1
                sc.conf_error_above += int(row_error)

    if prejudge_predictions is not None:
        sc.judge_kappa_prejudge = judge_kappa_prejudge(
            predictions, prejudge_predictions, truth_by_id
        )
    return sc


def judge_lift(
    judged: Scorecard, prejudge: Scorecard,
    facets: tuple[str, ...] = (
        "category_accuracy", "category_f1_macro", "level_exact_accuracy",
        "level_filter_consistent_accuracy", "tags_token_f1",
        "location_primary_accuracy",
    ),
) -> dict[str, float]:
    """Per-facet judge lift: (judge-on score) − (judge-off score). Positive =
    the judge helped; the honest replacement for reading κ off post-correction
    labels."""
    on, off = judged.to_dict(), prejudge.to_dict()
    out: dict[str, float] = {}
    for facet in facets:
        a, b = on.get(facet), off.get(facet)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            out[facet] = round(a - b, 4)
    return out


def _filter_consistent(pred_level: str | None, gold_level: str | None) -> bool:
    """A prediction is filter-consistent if, for EVERY filter the gold level
    should surface under, the predicted level also surfaces — and vice versa,
    except the sanctioned new_grad->entry generalization. Concretely: exact
    match, OR gold=new_grad and pred=entry (surfaces under entry, the safe
    superset). pred=new_grad for gold=entry is NOT consistent (over-narrows)."""
    if pred_level == gold_level:
        return True
    if gold_level == "new_grad" and pred_level == "entry":
        return True
    return False


def judge_kappa_prejudge(
    judged_predictions: list[dict[str, Any]],
    prejudge_predictions: list[dict[str, Any]],
    truth_by_id: dict[str, Any],
) -> float | None:
    """Cohen's κ between the judge's pass/fail verdict and whether the
    PRE-judge (classify-only) category+level matched gold.

    Semantics: the judge "agrees with gold" when it passes a row whose
    pre-judge labels were right, or fails a row whose pre-judge labels were
    wrong. Rows are aligned by job_listing_id across the judged and judge-off
    prediction files; rows missing from either side (or without gold /
    without a verdict) are skipped. This deliberately does NOT reward or
    punish the *correction* itself — see judge_lift for that."""
    pre_by_id = {p["job_listing_id"]: p for p in prejudge_predictions}
    a: list[int] = []  # judge said "pass" (1) / "fail" (0)
    b: list[int] = []  # PRE-judge labels actually correct (1) / wrong (0)
    for pred in judged_predictions:
        jid = pred["job_listing_id"]
        gold = truth_by_id.get(jid)
        pre = pre_by_id.get(jid)
        if gold is None or pre is None or pred.get("judge_pass") is None:
            continue
        a.append(1 if pred["judge_pass"] else 0)
        b.append(
            1 if (
                pre.get("category") == gold.get("category")
                and pre.get("level") == gold.get("level")
            ) else 0
        )
    if len(a) < 2:
        return None
    return cohens_kappa(a, b)


def cohens_kappa(a: list[int], b: list[int]) -> float:
    n = len(a)
    if n == 0:
        return 0.0
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pa1 = sum(a) / n
    pb1 = sum(b) / n
    pe = pa1 * pb1 + (1 - pa1) * (1 - pb1)
    if pe == 1.0:
        return 1.0
    return (po - pe) / (1 - pe)


GATE_MIN_N = 50


def regression_gate(
    current: Scorecard, baseline: dict[str, Any],
    epsilon: float = 0.02, min_n: int = GATE_MIN_N,
) -> list[str]:
    """Return a list of regressions (empty = pass). A facet regresses if it drops
    more than epsilon below the committed baseline.

    Guards: the gate REFUSES runs scoring fewer than ``min_n`` rows (a 5-row
    run passing trivially is not a gate). ``tags_f1`` (strict exact set-match)
    is advisory only — it measures granularity disagreement, not quality — so
    the tag facet gated here is the token-level F1."""
    cur = current.to_dict()
    failures: list[str] = []
    n = current.category.n
    if n < min_n:
        failures.append(
            f"gate refused: only {n} scored row(s) < min_n={min_n} "
            "(too few rows for a meaningful regression check)"
        )
        return failures
    for facet in (
        "category_accuracy", "category_f1_macro", "level_exact_accuracy",
        "level_filter_consistent_accuracy", "tags_token_f1", "location_primary_accuracy",
    ):
        base_v = baseline.get(facet)
        cur_v = cur.get(facet)
        if base_v is None or cur_v is None:
            continue
        if cur_v < base_v - epsilon:
            failures.append(f"{facet}: {cur_v:.4f} < baseline {base_v:.4f} - {epsilon}")
    return failures
