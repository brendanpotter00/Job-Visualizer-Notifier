"""Phase-0 parameters for the eval harness — every value deliberately left
unmeasured, with the step that measures it named beside it.

⚠ NOTHING HERE IS A MEASUREMENT UNLESS IT SAYS SO. A placeholder baked in as if
it were measured is the failure this file exists to prevent: the number looks
authoritative in a scorecard, in a runbook and in a handoff, and nobody can
tell afterwards which figures came from a run and which came from a guess.
Every placeholder therefore carries the comment shape

    UNMEASURED — placeholder; set by <STEP-ID>

so `grep -rn "UNMEASURED — placeholder"` enumerates the whole set.
"""

from __future__ import annotations

import math

# --- the category pool draw (D1) -------------------------------------------
# Seeded, stratified proportional to the seed's DRAFT category distribution
# (SWE 115 -> 21, business_ops 56 -> 10, data_scientist 48 -> 9,
# product_manager 33 -> 6) with a floor of 5 per stratum. 21 existing human
# rows + 46 = 67, clearing GATE_MIN_N=50 with margin.
# ⚠ `growth` and `hardware_engineer` have ZERO draft rows (both of each are
# already human), so NO draw can raise their support.
# UNMEASURED — placeholder; set by EV-2b
PARAM_CAT_DRAW_N = 46

# The floor of rows drawn per stratum, so a small category is not drawn to zero.
PARAM_STRATUM_FLOOR = 5

# The committed draw seed. Byte-identical re-runs depend on it.
PARAM_DRAW_SEED = 20260820

# --- the pre-labeller's measured error rate --------------------------------
# ⚠ THERE IS NO PRIOR FOR THIS TODAY. It is the FIRST measured answer to "how
# often is a claude-code/opus pre-label wrong", and it is what turns the
# subcategory pass's audit threshold from an invented 0.10 into a derived
# number. Read it off `golden/seed/category_audit.json` once EV-2b has run.
# UNMEASURED — placeholder; set by EV-2b
PARAM_PRELABEL_ERROR_RATE: float | None = None


def derive_audit_max(prelabel_error_rate: float | None) -> float:
    """PARAM_AUDIT_MAX = max(0.05, min(0.15, ceil(rate / 0.05) * 0.05)).

    ⚠ DERIVED, NOT INVENTED. Above this threshold no `prelabel_agreed` row
    enters the gate pool and EV-9b's stop condition fails — which is the
    correct outcome, not a reason to lower it. With no measurement available
    the function returns the CONSERVATIVE floor (0.05), never the ceiling.
    """
    if prelabel_error_rate is None:
        return 0.05
    stepped = math.ceil(prelabel_error_rate / 0.05) * 0.05
    return round(max(0.05, min(0.15, stepped)), 4)


# --- EV-5b / EV-12 G1b ------------------------------------------------------
# The minimum paired net (b - c) that counts as a category regression, PAIRED
# with an exact-binomial p <= 0.05. ⚠ BOTH conditions are required so a 2-vs-0
# flip (p = 0.5) cannot fail the gate.
# UNMEASURED — placeholder; set by EV-5b
PARAM_PAIRED_MIN_NET = 4

# Support floor for the gated macro-F1. ⚠ At the measured composition `growth`
# and `hardware_engineer` sit at 2 rows each, where one flipped row moves that
# class's F1 by 0.5 and the 6-class macro by 0.083 — four times the gate epsilon.
# UNMEASURED — placeholder; set by EV-5b
PARAM_MIN_CLASS_SUPPORT = 5

# --- EV-14 ------------------------------------------------------------------
# Acceptable shift in the share of rows below the judge's confidence ceiling,
# and in the subcategory nulled rate. ⚠ Set against EV-2's OLLAMA histogram —
# NEVER against the 71.8% / 73.5% figures in circulation, which come from a
# 2026-07-08 claude-code artifact on a different engine.
# UNMEASURED — placeholder; set by EV-14
PARAM_CAL_DELTA = 0.05
# UNMEASURED — placeholder; set by EV-14
PARAM_NULL_RATE = 0.03

# --- EV-12 G3 ---------------------------------------------------------------
# ⚠ JUDGMENT CALLS ACROSS 15 CLASSES, NOT DERIVED NUMBERS. The protocol doc
# must label them as opinion. They are written here so the opinion is at least
# in one place rather than restated differently in three documents.
# UNMEASURED — placeholder; set by EV-12
PARAM_G3_PRIMARY_NONEMPTY = 0.65
# UNMEASURED — placeholder; set by EV-12
PARAM_G3_MACRO_F1 = 0.50

# --- EV-13 ------------------------------------------------------------------
# The backfill lane's acceptance floor, deliberately looser than G3 because the
# input is thinner (title + company tags, no description). ⚠ The 0.15 margin is
# a placeholder to be replaced by the first MEASURED title-only number.
# UNMEASURED — placeholder; set by EV-13
PARAM_BACKFILL_FLOOR_MARGIN = 0.15


def derive_backfill_floor(g3_primary: float = PARAM_G3_PRIMARY_NONEMPTY) -> float:
    """The backfill lane's floor = G3's primary threshold minus the margin."""
    return round(g3_primary - PARAM_BACKFILL_FLOOR_MARGIN, 4)
