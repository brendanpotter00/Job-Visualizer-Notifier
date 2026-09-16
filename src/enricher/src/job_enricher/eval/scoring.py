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

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

# Canonical slug sets live in taxonomy.py (single source of truth, shared with
# the write-back validation path). Imported here so the scorer and the ingest
# validator can never drift apart.
from job_enricher.eval.params import PARAM_MIN_CLASS_SUPPORT
from job_enricher.taxonomy import (  # noqa: F401  (LEVELS re-exported)
    CATEGORIES,
    LEVELS,
    MAX_SUBCATEGORIES,
    SUBCATEGORIES,
    SUBCATEGORY_PARENT,
)

# level -> the filter set it should satisfy (mirrors SKILL.md level_includes).
# `intern` is standalone (its own filter only) — NOT a subset of new_grad/entry.
# Production routes the judge below this confidence
# (`JUDGE_CONFIDENCE_CEILING_DEFAULT`, enrich_config.py). The scorer's own
# calibration split stays at its 0.80 default for comparability with every
# committed baseline; this constant governs the judge-VOLUME channels only.
JUDGE_CONFIDENCE_CEILING = 0.85

LEVEL_INCLUDES: dict[str, set[str]] = {
    "intern": {"intern"},
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
    # --- subcategory facet (SWE parent only) --------------------------------
    # ⚠ A SEPARATE DENOMINATOR, on purpose. This facet is scored on a strict
    # SUBSET of the rows every other facet is scored on (gold category ==
    # software_engineering AND a non-null gold subcategory list), so sharing
    # `category.n` would silently report a subcategory number over a pool that
    # never had a subcategory label.
    subcategory_primary: FacetScore = field(default_factory=FacetScore)
    subcategory_primary_nonempty: FacetScore = field(default_factory=FacetScore)
    subcategory_parent_correct: FacetScore = field(default_factory=FacetScore)
    subcategory_set: PRF = field(default_factory=PRF)
    subcategory_per_class: dict[str, PRF] = field(default_factory=lambda: defaultdict(PRF))
    subcategory_jaccard_sum: float = 0.0
    subcategory_jaccard_n: int = 0
    subcategory_gold_n: int = 0
    subcategory_pred_nonempty_n: int = 0
    # leak: a non-empty subcategory prediction on a NON-SWE gold row. Its own
    # denominator (`subcategory_nonswe_n`) because it is measured over the rows
    # the facet is NOT scored on.
    subcategory_leaks: int = 0
    subcategory_nonswe_n: int = 0
    subcategory_cardinality_sum: int = 0
    subcategory_over_cap: int = 0
    subcategory_nulled: int = 0
    subcategory_exclusivity_violations: int = 0
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
    # ⚠ A SEPARATE CALIBRATION PAIR for the subcategory facet, keyed off
    # `subcategory_confidence` and NEVER the shared `confidence`. Folding them
    # together is what would let subcategory uncertainty bleed into the number
    # that routes the judge at 0.85.
    conf_error_below_sub: int = 0
    conf_below_total_sub: int = 0
    # --- judge-VOLUME channels (EV-14) --------------------------------------
    # ⚠ Measured at the PRODUCTION ceiling, not at `conf_threshold`. This is the
    # direct driver of `_needs_judge`, and at ~92 s per judged row on a lane
    # already near 100% duty cycle a shift here is a schedule change, not a
    # rounding difference.
    conf_below_ceiling: int = 0
    conf_ceiling_total: int = 0
    needs_human_n: int = 0
    needs_human_total: int = 0
    # judge agreement — κ between the judge's pass/fail verdict and whether the
    # PRE-judge (classify-only) labels matched gold. Requires the judge-off
    # prediction file; None when unavailable.
    judge_kappa_prejudge: float | None = None
    # per-item latency samples (ms) captured upstream by the engine. Descriptive
    # only (never gated) — the scorer stays pure, so these arrive as prediction
    # data and we just summarize them.
    classify_latencies_ms: list[int] = field(default_factory=list)
    judge_latencies_ms: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category_accuracy": round(self.category.accuracy, 4),
            "category_f1_macro": round(self._macro_f1(), 4),
            # ⚠ A SECOND key, not a redefinition. Measured on the seed, `growth`
            # and `hardware_engineer` have exactly 2 rows each and BOTH are
            # already human with zero draft rows available — so on the human
            # pool each carries a full 1/6 of a GATED facet off two rows, where
            # one flip moves the macro by 0.083, FOUR TIMES the gate epsilon.
            "category_f1_macro_supported": round(
                self._macro_f1(PARAM_MIN_CLASS_SUPPORT), 4
            ),
            "category_f1_macro_excluded_classes": self._excluded_classes(
                PARAM_MIN_CLASS_SUPPORT
            ),
            # --- subcategory facet (SWE parent only; own denominator) --------
            # Mirrors the tags_jaccard convention: both-empty counts CORRECT.
            "subcategory_primary_accuracy": round(self.subcategory_primary.accuracy, 4),
            # ⚠ THE GATED ONE. Gold-non-empty rows only, so a model that
            # abstains on everything cannot inflate the headline with free
            # both-empty hits.
            "subcategory_primary_accuracy_nonempty": round(
                self.subcategory_primary_nonempty.accuracy, 4
            ),
            "subcategory_set_f1": round(self.subcategory_set.f1, 4),
            "subcategory_set_precision": round(self.subcategory_set.precision, 4),
            "subcategory_set_recall": round(self.subcategory_set.recall, 4),
            "subcategory_jaccard": round(
                self.subcategory_jaccard_sum / self.subcategory_jaccard_n, 4
            ) if self.subcategory_jaccard_n else 1.0,
            "subcategory_f1_macro": round(self._subcategory_macro_f1(), 4),
            # ⚠ A COMPACT 15-KEY FLOAT MAP, not a PRF matrix: JVN caps the
            # pushed scorecard at 16KB and a full matrix would blow it.
            "subcategory_f1_per_class": self._subcategory_f1_per_class(),
            "subcategory_accuracy_given_parent_correct": round(
                self.subcategory_parent_correct.accuracy, 4
            ),
            "subcategory_coverage": round(
                self.subcategory_pred_nonempty_n / self.subcategory_gold_n, 4
            ) if self.subcategory_gold_n else 0.0,
            "subcategory_leak_rate": round(
                self.subcategory_leaks / self.subcategory_nonswe_n, 4
            ) if self.subcategory_nonswe_n else 0.0,
            "subcategory_nonswe_n": self.subcategory_nonswe_n,
            "subcategory_cardinality_mean": round(
                self.subcategory_cardinality_sum / self.subcategory_gold_n, 4
            ) if self.subcategory_gold_n else 0.0,
            "subcategory_over_cap": self.subcategory_over_cap,
            "subcategory_exclusivity_violations": self.subcategory_exclusivity_violations,
            "subcategory_nulled_rate": round(
                self.subcategory_nulled / self.subcategory_gold_n, 4
            ) if self.subcategory_gold_n else 0.0,
            "subcategory_n": self.subcategory_gold_n,
            # --- judge-volume channels ---------------------------------------
            "conf_below_ceiling_share": round(
                self.conf_below_ceiling / self.conf_ceiling_total, 4
            ) if self.conf_ceiling_total else None,
            "conf_ceiling": JUDGE_CONFIDENCE_CEILING,
            "needs_human_rate": round(
                self.needs_human_n / self.needs_human_total, 4
            ) if self.needs_human_total else None,
            "calibration_error_rate_below_sub": round(
                self.conf_error_below_sub / self.conf_below_total_sub, 4
            ) if self.conf_below_total_sub else None,
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
            "classify_latency_ms": _latency_stats(self.classify_latencies_ms),
            "judge_latency_ms": _latency_stats(self.judge_latencies_ms),
            "n": self.category.n,
        }

    def _subcategory_macro_f1(self) -> float:
        """Macro-F1 over the SUPPORTED subcategory classes, mirroring
        `_macro_f1` exactly. Averaging over the 13 slugs a thin pool never sees
        would report a number governed by absence rather than by quality."""
        supported = [p for p in self.subcategory_per_class.values() if (p.tp + p.fp + p.fn) > 0]
        if not supported:
            return 0.0
        return sum(p.f1 for p in supported) / len(supported)

    def _subcategory_f1_per_class(self) -> dict[str, float]:
        """slug -> F1, for the supported classes only. Compact by design."""
        return {
            slug: round(prf.f1, 4)
            for slug, prf in sorted(self.subcategory_per_class.items())
            if (prf.tp + prf.fp + prf.fn) > 0
        }

    def _macro_f1(self, min_support: int = 1) -> float:
        """Macro-F1 over the categories with SUPPORT (tp+fp+fn >= min_support).
        Averaging over zero-support classes structurally dilutes the metric —
        with half the taxonomy unused, a 10-point regression in a live class
        moved the old all-classes average by less than the gate epsilon.

        ⚠ THE DEFAULT STAYS 1. `category_f1_macro` and `baseline.json`'s
        committed 0.679 must remain byte-identical; the support floor is
        reported as a SECOND key, never by redefining the first."""
        supported = [
            p for p in self.category_per_class.values()
            if (p.tp + p.fp + p.fn) >= max(1, min_support)
        ]
        if not supported:
            return 0.0
        return sum(p.f1 for p in supported) / len(supported)

    def _excluded_classes(self, min_support: int) -> list[str]:
        """Classes with SOME support but below the floor — named, never hidden."""
        return sorted(
            slug for slug, prf in self.category_per_class.items()
            if 0 < (prf.tp + prf.fp + prf.fn) < max(1, min_support)
        )


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


def _latency_stats(samples: list[int]) -> dict[str, Any] | None:
    """Summarize per-item latency samples (ms). None when no engine attached
    latency (e.g. the legacy agent-produced predictions). Descriptive only."""
    if not samples:
        return None
    ordered = sorted(samples)
    n = len(ordered)

    def pct(q: float) -> int:
        return ordered[min(n - 1, int(q * (n - 1) + 0.5))]

    return {
        "n": n,
        "mean": round(sum(ordered) / n, 1),
        "p50": pct(0.50),
        "p95": pct(0.95),
        "max": ordered[-1],
    }


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

        # latency (descriptive; captured upstream by the engine, may be absent)
        cl = pred.get("classify_latency_ms")
        if isinstance(cl, (int, float)):
            sc.classify_latencies_ms.append(int(cl))
        jl = pred.get("judge_latency_ms")
        if isinstance(jl, (int, float)):
            sc.judge_latencies_ms.append(int(jl))

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

        # subcategory — SWE parent only, on its own denominator
        # ⚠ THE GUARD IS THE POINT. A non-SWE gold row and an UNLABELLED gold
        # row are both SKIPPED, never counted wrong. That rule lives HERE, in
        # the scorer, and not in the prompt: a prompt cannot stop a metric from
        # being computed over rows that have no answer, and a facet scored over
        # rows it does not apply to reports a number nobody can act on.
        p_sub_raw = pred.get("subcategories")
        g_sub = gold.get("subcategories")
        if g_cat == SUBCATEGORY_PARENT and g_sub is not None:
            sc.subcategory_gold_n += 1
            p_sub = list(p_sub_raw) if isinstance(p_sub_raw, list) else []
            if p_sub_raw is None:
                sc.subcategory_nulled += 1
            if p_sub:
                sc.subcategory_pred_nonempty_n += 1
            sc.subcategory_cardinality_sum += len(p_sub)
            if len(p_sub) > MAX_SUBCATEGORIES:
                sc.subcategory_over_cap += 1
            if "full_stack" in p_sub and ({"frontend", "backend"} & set(p_sub)):
                sc.subcategory_exclusivity_violations += 1

            # primary = element 0; both-empty counts CORRECT (tags_jaccard
            # convention). The *_nonempty variant excludes those free hits.
            p_primary = p_sub[0] if p_sub else None
            g_primary = g_sub[0] if g_sub else None
            sc.subcategory_primary.n += 1
            primary_correct = p_primary == g_primary
            if primary_correct:
                sc.subcategory_primary.correct += 1
            if g_sub:
                sc.subcategory_primary_nonempty.n += 1
                if primary_correct:
                    sc.subcategory_primary_nonempty.correct += 1
            # conditional on the parent being right — separates "wrong
            # specialty" from "wrong category, so the specialty never had a
            # chance".
            if cat_correct:
                sc.subcategory_parent_correct.n += 1
                if primary_correct:
                    sc.subcategory_parent_correct.correct += 1

            # ⚠ ORDER-INSENSITIVE set intersection over the 0-2 sets: ['a','b']
            # and ['b','a'] are the same answer, and `primary` is where order
            # is scored.
            p_set, g_set = set(p_sub), set(g_sub)
            sc.subcategory_set.tp += len(p_set & g_set)
            sc.subcategory_set.fp += len(p_set - g_set)
            sc.subcategory_set.fn += len(g_set - p_set)
            union = len(p_set | g_set)
            sc.subcategory_jaccard_sum += 1.0 if union == 0 else len(p_set & g_set) / union
            sc.subcategory_jaccard_n += 1
            for slug in SUBCATEGORIES:
                prf = sc.subcategory_per_class[slug]
                in_p, in_g = slug in p_set, slug in g_set
                if in_p and in_g:
                    prf.tp += 1
                elif in_p:
                    prf.fp += 1
                elif in_g:
                    prf.fn += 1

            # calibration on the SUBCATEGORY confidence only
            sub_conf = pred.get("subcategory_confidence")
            if sub_conf is not None and sub_conf < conf_threshold:
                sc.conf_below_total_sub += 1
                sc.conf_error_below_sub += int(p_set != g_set)
        elif g_cat is not None and g_cat != SUBCATEGORY_PARENT:
            # THE LEAK BRANCH — a separate measurement over a separate
            # denominator. `stamp_contract_rows` is what makes it non-zero-cost
            # to have gold here at all.
            sc.subcategory_nonswe_n += 1
            if isinstance(p_sub_raw, list) and p_sub_raw:
                sc.subcategory_leaks += 1

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

        # --- judge VOLUME, measured at the production ceiling ----------------
        # ⚠ CHANNEL (c) IS THE ONE NOBODY SCOPED. The separate
        # `subcategory_confidence` field protects the 0.85 routing from
        # subcategory uncertainty bleeding into `confidence` — but it does NOT
        # protect the second path: `validate_subcategories` nulls a bad slug,
        # the invalid-slug path flags `needs_human`, and `_needs_judge` returns
        # True on `needs_human` REGARDLESS of confidence. So hallucinated slugs
        # buy judge volume even with a separate confidence field, and
        # `needs_human_rate` beside `conf_below_ceiling_share` is what makes
        # that visible.
        if conf_for_ceiling := pred.get("confidence"):
            sc.conf_ceiling_total += 1
            if conf_for_ceiling < JUDGE_CONFIDENCE_CEILING:
                sc.conf_below_ceiling += 1
        if "needs_human" in pred:
            sc.needs_human_total += 1
            sc.needs_human_n += int(bool(pred["needs_human"]))

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
        "location_primary_accuracy", "subcategory_set_f1",
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


def exact_binomial_two_sided(k: int, n: int) -> float | None:
    """Exact two-sided binomial p for `k` successes in `n` trials at p=0.5.

    ⚠ STDLIB ONLY — `math.comb`, no scipy and no numpy (both verified absent
    from pyproject.toml). The module's "pure, no network, fully unit-testable"
    contract is what lets the gate run in CI and in a bare checkout, and a
    dependency here would quietly end that.

    Returns None when n == 0 (no discordant pairs — nothing to test).
    """
    if n <= 0:
        return None
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return min(1.0, 2.0 * tail)


def paired_facet_deltas(
    current_predictions: list[dict[str, Any]],
    baseline_predictions: list[dict[str, Any]],
    truth: list[dict[str, Any]],
    facets: tuple[str, ...] = ("category", "level"),
) -> dict[str, dict[str, Any]]:
    """McNemar's paired comparison of two prediction sets over the SAME rows.

    ⚠ WHY PAIRED, AND WHY THIS IS NOT OPTIONAL. At n ~= 67 the standard error on
    an accuracy near 0.80 is sqrt(0.8*0.2/67) ~= 0.049, so `regression_gate`'s
    `epsilon = 0.02` sits WELL INSIDE the noise floor: the unpaired gate would
    both fail on noise and miss real regressions. v6 and v7 score the same rows,
    so the correct statistic is the paired one — it conditions on the rows where
    the two arms DISAGREE and throws away the shared variance.

    Per facet returns ``{'b', 'c', 'net', 'n_paired', 'p_value', 'skipped'}``:

    * ``b`` = baseline RIGHT and current WRONG   (regressions)
    * ``c`` = baseline WRONG and current RIGHT   (fixes)
    * ``net`` = ``c - b``  (POSITIVE means the current arm is better)
    * ``p_value`` = the exact two-sided binomial on ``(min(b, c), b + c)``,
      None when there are no discordant pairs.

    Rows missing from ANY of the three sides are SKIPPED and COUNTED, never
    silently treated as agreement.

    ⚠ PURE FUNCTION ONLY. `regression_gate` is deliberately NOT changed to call
    this — EV-12's protocol invokes it as an explicit gate arm, which keeps
    `regression_gate`'s signature and default behaviour frozen against every
    committed baseline.
    """
    truth_by_id = {t["job_listing_id"]: t for t in truth}
    base_by_id = {p["job_listing_id"]: p for p in baseline_predictions}
    out: dict[str, dict[str, Any]] = {}
    for facet in facets:
        b = c = n_paired = skipped = 0
        seen: set[str] = set()
        for pred in current_predictions:
            jid = pred.get("job_listing_id")
            gold = truth_by_id.get(jid)
            base = base_by_id.get(jid)
            if gold is None or base is None:
                skipped += 1
                continue
            seen.add(jid)
            n_paired += 1
            cur_ok = pred.get(facet) == gold.get(facet)
            base_ok = base.get(facet) == gold.get(facet)
            if base_ok and not cur_ok:
                b += 1
            elif cur_ok and not base_ok:
                c += 1
        # rows present in the baseline + truth but ABSENT from the current run
        skipped += sum(
            1 for jid in base_by_id
            if jid in truth_by_id and jid not in seen
        )
        out[facet] = {
            "b": b, "c": c, "net": c - b, "n_paired": n_paired,
            "p_value": exact_binomial_two_sided(min(b, c), b + c),
            "skipped": skipped,
        }
    return out


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

# The facets `regression_gate` enforces, GROUPED. Each group carries its own
# denominator and its own min-n.
#
# ⚠ WHY GROUPS EXIST AT ALL. The gate used to read `n = current.category.n` and
# RETURN on the min_n refusal. With one shared denominator a thin category pool
# would keep the subcategory gate permanently inert — printing a refusal about
# the category pool while the subcategory facet, which may have plenty of rows,
# is never checked. The loop below must therefore NOT short-circuit across
# groups: one group refusing is a finding about that group only.
_FACET_GROUPS: dict[str, tuple[str, ...]] = {
    # BYTE-IDENTICAL to the pre-existing inline tuple. Do not reorder or extend
    # it: `baseline.json`'s committed values are what these compare against.
    "category": (
        "category_accuracy", "category_f1_macro", "level_exact_accuracy",
        "level_filter_consistent_accuracy", "tags_token_f1", "location_primary_accuracy",
    ),
    "subcategory": (
        "subcategory_primary_accuracy_nonempty",
        "subcategory_set_f1",
        "subcategory_f1_macro",
        "subcategory_leak_rate",
    ),
}

# Facets where HIGHER IS WORSE, so the regression comparison inverts.
_INVERTED_FACETS: frozenset[str] = frozenset({"subcategory_leak_rate"})

_DEFAULT_GROUPS: tuple[str, ...] = ("category",)

# Kept as a flat alias so `missing_baseline_facets` and the gate can never
# disagree about what is actually being checked.
_GATED_FACETS: tuple[str, ...] = _FACET_GROUPS["category"]


def gated_facets(groups: Iterable[str] | None = None) -> tuple[str, ...]:
    """Every facet key the gate will compare for `groups` (default: category)."""
    out: list[str] = []
    for g in (groups or _DEFAULT_GROUPS):
        out.extend(_FACET_GROUPS.get(g, ()))
    return tuple(out)


def group_denominator(current: "Scorecard", group: str) -> int:
    """The row count THAT GROUP is scored over. `category.n` is not it for the
    subcategory group — that facet is scored on a strict subset."""
    if group == "subcategory":
        return current.subcategory_gold_n
    return current.category.n


def missing_baseline_facets(
    baseline: dict[str, Any], facets: Iterable[str]
) -> list[str]:
    """Facets the gate WILL NOT CHECK because the baseline has no value for them.

    ⚠ THE SILENT FAILURE THIS EXISTS TO CATCH. `regression_gate` `continue`s over
    any facet whose baseline value is None/absent (see the `if base_v is None`
    branch below). So the moment a NEW facet is added to a gated group, every run
    against an OLD committed baseline prints `eval --gate: PASS` while checking
    NOTHING for that facet — a gate that is structurally green. `run_eval` calls
    this and prints one WARN line per unchecked facet, so the hole is visible in
    the scrollback instead of being inferred from a missing number.
    """
    return [f for f in facets if baseline.get(f) is None]


def regression_gate(
    current: Scorecard, baseline: dict[str, Any],
    epsilon: float = 0.02, min_n: int = GATE_MIN_N,
    groups: Iterable[str] | None = None,
) -> list[str]:
    """Return a list of regressions (empty = pass). A facet regresses if it drops
    more than epsilon below the committed baseline.

    Guards: each GROUP refuses when its OWN denominator is below ``min_n`` (a
    5-row run passing trivially is not a gate). ``tags_f1`` (strict exact
    set-match) is advisory only — it measures granularity disagreement, not
    quality — so the tag facet gated here is the token-level F1.

    ⚠ THE LOOP DOES NOT SHORT-CIRCUIT ACROSS GROUPS. A refusal is a finding
    about the group that refused; the other groups still evaluate. The old
    single `return` on the min-n refusal is precisely what would have kept the
    subcategory gate inert forever behind a thin category pool.

    ``subcategory_leak_rate`` is INVERTED — higher is worse — so its comparison
    is flipped rather than silently reading a rising leak rate as an
    improvement.
    """
    cur = current.to_dict()
    failures: list[str] = []
    for group in (groups or _DEFAULT_GROUPS):
        n = group_denominator(current, group)
        if n < min_n:
            failures.append(
                f"{group} gate refused: only {n} scored row(s) < min_n={min_n} "
                "(too few rows for a meaningful regression check)"
            )
            continue
        for facet in _FACET_GROUPS.get(group, ()):
            base_v = baseline.get(facet)
            cur_v = cur.get(facet)
            if base_v is None or cur_v is None:
                continue
            if facet in _INVERTED_FACETS:
                if cur_v > base_v + epsilon:
                    failures.append(
                        f"{facet}: {cur_v:.4f} > baseline {base_v:.4f} + {epsilon} "
                        "(higher is worse)"
                    )
            elif cur_v < base_v - epsilon:
                failures.append(f"{facet}: {cur_v:.4f} < baseline {base_v:.4f} - {epsilon}")
    return failures
