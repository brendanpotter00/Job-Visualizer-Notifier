"""The verification gate + verdict for custom-company harvests (E7).

Phase 2 grows the Phase-1 *minimal* gate into the BUILD-PLAN §3 check set, wiring
the only two oracles the ATS clients can feed:

* ``declared_probed`` — the ATS API's own trusted independent total, compared
  EXACTLY (tolerance 0) against the post-dedup unique-id count. Greenhouse
  (``meta.total``) and Workday (``total``).
* ``self_consistent`` — for ATSs with no trustworthy total (Ashby, Lever, Gem,
  Eightfold): a run is complete iff it terminated cleanly (not a cap), pages
  advanced with disjoint id-sets, and the count sits within the delta band of the
  trailing-run median. Passing makes the *run* VERIFIED; CLOSING additionally
  needs a 3-consecutive-VERIFIED streak, enforced in the leaf task.
* ``none`` — the **history-delta** oracle, and the newest of the three. For a
  DISCOVERED board whose recipe declares no total and does not paginate. Until
  this existed the answer for such a board was ``no_oracle`` forever, so it could
  never increment a miss and never close a job: every filled role stayed OPEN
  forever and the board's count only ever went up. A run VERIFIES iff the stored
  REQUEST shows no sign of having read one page of a longer list (check 13) and
  the count is consistent with the board's own history (check 12). Reachable only
  when the caller passes the recipe — see :func:`verify_harvest`. CLOSING
  additionally needs a 5-consecutive-VERIFIED streak and the id-churn guard.

The two functions split by what each may do:

* :func:`run_gate` — the *structural* pass (checks 2 zero-aware, 3, 7-dedupe, 8).
  Raises :class:`HarvestGateError` (→ FAILED) ONLY on a genuinely broken run.
* :func:`verify_harvest` — the *verdict* pass (checks 5, 6, 7-vs-total, 9, 10, 11,
  12, 13). Returns VERIFIED | UNVERIFIED and NEVER raises.

A third function, :func:`read_untruncated`, sits OUTSIDE that ladder and is not part
of it: it answers a strictly weaker question ("did anything in this run say the read
stopped early?") for the one read-only, non-destructive consumer that needs a
complete-looking title set rather than a proven-complete one. It licences nothing.
Only ``verify_harvest`` returning VERIFIED may ever close a job.

The verdict ladder (BUILD-PLAN §1.1):

* ``FAILED``     — a gate check raised. The leaf task writes nothing destructive,
                   records the run, and re-raises so Procrastinate retries. A
                   FAILED (non-executed) run is NOT a miss.
* ``UNVERIFIED`` — rows were harvested but completeness could not be proven. The
                   leaf task upserts + refreshes last_seen ONLY; it NEVER
                   increments misses and NEVER closes.
* ``VERIFIED``   — every applicable gate check passed. Only a VERIFIED run may
                   ever close a job (and only then ANDed with every safety guard).

The load-bearing invariant, unchanged from Phase 1: *a job is never closed by a
run that could not prove it saw the whole board.*
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from scripts.shared.models import JobListing

from .harvest_meta import HarvestEvidence
from .recipe_schema import HTTP_HTML

if TYPE_CHECKING:  # avoid any import cycle; only the type is needed here
    from .custom_baseline import Baseline

# --- Verdicts ----------------------------------------------------------------
VERIFIED = "VERIFIED"
UNVERIFIED = "UNVERIFIED"
FAILED = "FAILED"

# The floor for check 2's non-empty path (used only when jobs are present but
# below the floor — a Phase-3 seam). A 0-row harvest is NOT force-raised here; it
# routes to the zero-proof chain (check 11) in verify_harvest.
DEFAULT_EXPECTED_MIN_JOBS = 1

# --- Effective oracle mapping (DECISION D2) ---------------------------------
# The gate derives the oracle from the ATS PROVIDER at gate time, NOT from the
# stored ``company_scripts.oracle_kind``. This lets Phase-1 rows seeded with
# ``oracle_kind='none'`` graduate with no backfill/migration: a Greenhouse
# company is ``declared_probed`` because it *is* Greenhouse, full stop.
_DECLARED_PROBED_PROVIDERS = frozenset({"greenhouse", "workday"})
_SELF_CONSISTENT_PROVIDERS = frozenset({"ashby", "lever", "gem", "eightfold"})

# --- the delta band (check 12) ----------------------------------------------
# A run is a delta anomaly when its record count moves too far from the
# trailing-run median of prior VERIFIED harvests. Shared by ``self_consistent``
# and by ``none`` (the history-delta oracle below) — one band, one derivation,
# one set of tests. Only applied once a median exists (>= 1 prior VERIFIED run).
#
# THE LOW SIDE IS THE ONE THAT MATTERS and it is the reason this file changed.
# An over-read cannot wrong-close (extra rows only get upserted); an under-read
# is precisely how live jobs disappear. So the low side is a DISJUNCTION of two
# rules and a run trips if EITHER fires:
#
#   (a) n < median * 0.5                       — the original hard floor, kept
#                                                verbatim so nothing that was
#                                                refused before is now allowed;
#   (b) n < median * 0.85 AND (median - n) >= 15 — the new rule.
#
# WHY 0.85 AND 15, AND WHY THE ``AND``. Measured on prod ``scrape_runs``,
# 2026-06-01 -> 2026-08-29, one run per company-hour (the custom cadence is now
# 1 h), guard-skipped runs excluded, each run scored against the median of its
# own preceding 14 runs: n = 271,053 scored runs across the published fleet.
#
#   ratio to trailing median      p0.5% 0.9167   p1% 0.9504   p5% 0.9871
#                                 p50   1.0000   p99 1.0460   p99.9 1.1555
#
# Ratio alone is unusable on small boards: 659 runs fall below 0.85, and the
# companies that supply them are ``slack`` (median 16), ``browserbase`` (9),
# ``posthog`` (18), ``gem`` (11), ``light`` (8) — a 9-job board that posts 6 is
# not a truncation, it is Tuesday. ANDing an absolute drop of >= 15 removes all
# of that: 429 runs remain, and 404 of those 429 are n == 0, i.e. total outages
# the ``empty_scrape`` guard already refuses.
#
# So the entire NEW population this band refuses is 25 runs in 271,053 (0.009%),
# and every one of them was inspected:
#
#   * ``apple`` x 5 — 2460/3688, 2585/3577, 2722/3760, 2819/3774, 2859/3577.
#     These ARE the real Apple truncations that ``incremental.py``'s own
#     calibration note names. Refusing them is the point.
#   * ``paypal`` x 19 and ``airtable`` x 1 — genuine step shrinks (87 from 112,
#     112 from 142, 169 from 201). Handled by the settled-step release below.
#
# 0.85 and 15 are not new numbers: they are ``SCRAPER_GUARD_MIN_RATIO`` and
# ``SCRAPER_GUARD_MIN_ABS_DROP`` from ``scripts/shared/incremental.py``, which
# were calibrated independently against 455,317 runs and landed on the same
# knee. This band is that guard's rule shape re-pointed at a different baseline:
# the guard scores the harvest against ``active_count`` (what the DB holds), this
# scores it against the trailing median (what the BOARD has been returning). They
# are ANDed at close time, never substituted.
_DELTA_HARD_LOW_RATIO = 0.5
_DELTA_LOW_RATIO = 0.85
_DELTA_MIN_ABS_DROP = 15
_DELTA_HIGH_RATIO = 2.0

# SETTLED STEP CHANGE — how a real layoff is told apart from a broken read.
# Without a release, a VERIFIED-only median latches forever: a board that
# legitimately drops 1,074 -> 600 is out of band, so it never VERIFIES, so no
# VERIFIED run ever enters the median, so it is out of band forever. That would
# freeze most boards eventually — 19 of the 25 runs above are that shape.
#
# The discriminator is in the prod data, not invented: a real shrink HOLDS its
# new number, a truncation WANDERS. Of the 5 Apple truncations, 0 were preceded
# by 4 runs of the identical count. Of the 19 PayPal step shrinks, 6 were — and
# those 6 are exactly the settled ones. So: a run outside the band is admitted
# anyway iff the previous 4 harvests returned the IDENTICAL count. Zero of the
# known-real truncations in 271,053 runs would be released by that rule.
#
# It is a re-baseline, not a close: the released run still needs the VERIFIED
# streak, the safety guard, the churn guard, two consecutive misses and the
# 1.5x-cadence wall-clock floor before anything closes.
#
# SIZED IN BOTH RUNS AND HOURS, and that is not belt-and-braces. The measurement
# above is "four consecutive HOURLY observations of the identical count" — both
# halves of that sentence are load-bearing, and a bare run count keeps only one
# of them. If the cadence were shortened to 15 minutes, four runs would be one
# hour of evidence rather than four, and a board that stalls for an hour would
# re-baseline. If it were lengthened back to a day, four runs would be four days
# — stronger, and correctly so. So the requirement is the CONJUNCTION: at least
# ``_SETTLED_MIN_RUNS`` prior harvests AND at least ``_SETTLED_MIN_HOURS`` of
# wall clock spanned by them. At the shipped 1 h cadence the two coincide at 4,
# which is exactly what was measured; at any other cadence the stricter one wins.
_SETTLED_MIN_RUNS = 4
_SETTLED_MIN_HOURS = 4.0

# The cadence assumed when a caller does not say. It is the shipped default
# (``custom_companies_service.DEFAULT_CADENCE_HOURS``), NOT imported from there —
# this module is deliberately free of service-layer imports, and a wrong guess
# here can only make the two spans LONGER (a smaller assumed cadence means more
# runs required), which is the safe direction.
_DEFAULT_CADENCE_HOURS = 1.0


def settled_prior_runs(cadence_hours: float = _DEFAULT_CADENCE_HOURS) -> int:
    """How many PRIOR harvests must have returned an identical count before a
    step change is treated as real (and before a round count reads as a page
    limit). See the constant block: runs AND hours, whichever is stricter.

    Both consumers degrade SAFELY when ``custom_baseline``'s window is shorter
    than this returns. ``_settled_step_change`` requires a full run of matches
    and gets fewer, so it refuses the release; ``_limit_pinned`` checks ``all()``
    over fewer values and so refuses MORE often. Neither can silently widen.
    """
    cadence = max(float(cadence_hours), 1e-6)
    return max(_SETTLED_MIN_RUNS, math.ceil(_SETTLED_MIN_HOURS / cadence))

# Phase-3 oracles — now WIRED (Phase 3a). Each is an exact-match (tolerance-0)
# oracle whose total rides ``evidence.declared_total``, computed upstream by
# ``recipe_runner`` (facet_sum = single-valued facet Σ, header = X-WP-Total-style
# int, sitemap = <loc> count). They share ``_verify_oracle_total`` with
# ``declared_probed`` — the run VERIFIES iff the post-dedup count equals the total.
_PHASE_3_ORACLES = frozenset({"facet_sum", "header", "sitemap"})

# Every exact-match oracle: the Phase-2 ``declared_probed`` plus the three Phase-3
# oracles. All compare the post-dedup count to a trusted total at tolerance 0.
_EXACT_ORACLES = _PHASE_3_ORACLES | {"declared_probed"}

# The two oracles with NO trusted total, whose completeness claim is historical
# rather than structural. Both are gated at close time by a consecutive-VERIFIED
# streak and by the id-churn guard (see ``tasks.fetch_custom_company``).
HISTORICAL_ORACLES = frozenset({"self_consistent", "none"})

# --- the page-shape tells (check 13), i.e. how ``none`` stops being fatal -----
# ``discover.synthesize_recipe`` stores ``oracle_kind='none'`` for a recipe with
# no declared total AND no pagination, on the grounds that "a single request that
# returns page one of an unknown-length board is indistinguishable from one that
# returns the whole board". That is true of the RESPONSE. It is NOT true of the
# REQUEST, and the request is stored right next to it.
#
# Measured on the four discovered boards in the owner's dev DB:
#
#   Walmart      POST careers.walmart.com/api/graphql, body ... "job_page": 0
#                -> 10 records. A page index in the request, no paginate step:
#                   this recipe reads page one of a paginated endpoint, and the
#                   board has thousands of jobs. THIS is the board that must
#                   never close, and 13a is what refuses it.
#   Goldman      body "pageNumber": 0, "pageSize": 20 -> 20 records (also
#                refused three other ways: declared 1074 vs 20 harvested,
#                page_advance_ok=False, and empty_scrape at 1.8% of active).
#   Atlassian    GET /endpoint/careers/listings, no params -> 232 records.
#   Jane Street  GET /jobs/main.json, no params -> 233 records.
#
# So the tell separates the two live shapes cleanly on real data, and it is a
# statement about what the request ASKED FOR rather than a guess about the reply.
#
# Three checks, in order of how much they claim:
#
#   13a offset family — the request carries a page-index/offset parameter and the
#       recipe has no ``paginate_*`` step. The endpoint is paginated BY ITS OWN
#       INTERFACE and we are reading one page of it. Permanent refusal.
#   13b size family — the request carries an explicit page-SIZE parameter and the
#       harvest returned exactly that many rows. The read hit the ceiling it
#       asked for. (A size of 1,000 that returns 232 is the opposite: positive
#       evidence, and it passes.)
#   13c implicit limit — no parameter at all, but the count is exactly a common
#       page size AND the board has returned that same number on every harvest we
#       have. A server-side default limit is the only thing that pins a count to
#       a round number forever; a real board's count drifts off it. The cost of a
#       false positive is near zero BY CONSTRUCTION: if the count never moves and
#       the id set never moves, there is nothing to close anyway.
_PAGE_OFFSET_PARAMS = frozenset({
    "page", "pagenumber", "pageno", "pageindex", "pagenum", "offset",
    "start", "startindex", "startrow", "startat", "skip", "from",
    "cursor", "after", "searchafter", "scroll",
})
_PAGE_SIZE_PARAMS = frozenset({
    "pagesize", "limit", "perpage", "pagelimit", "size", "rows", "count",
    "maxresults", "top", "num", "first", "results", "hitsperpage", "length",
})
# Suffixes that make a key a page index whatever it is prefixed with — Walmart's
# ``job_page`` (and its siblings ``content_page`` / ``future_roles_page``) would
# never appear in a fixed list, so the list is backed up by the shape of the name.
_PAGE_OFFSET_SUFFIXES = ("page", "offset", "pagenumber", "pageindex")
# Page sizes a server picks when the client did not. Deliberately round numbers
# only: a limit that is not round is not a limit anybody configured.
_COMMON_PAGE_SIZES = frozenset({
    10, 15, 20, 24, 25, 30, 40, 50, 60, 75, 100, 120, 150, 200, 250, 500, 1000,
})


def _normalize_param(name: str) -> str:
    """``job_page`` / ``page-Number`` / ``pageSize`` -> ``jobpage`` /
    ``pagenumber`` / ``pagesize``. Case and separators carry no meaning across
    board APIs, so they are removed before matching."""
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _request_params(fetch: dict[str, Any]) -> dict[str, Any]:
    """Every normalized parameter name the stored ``fetch`` step sends, with its
    value: the URL query string plus every LEAF slot of a JSON body.

    Body traversal is ``recipe_runner.iter_body_params`` — the same walker the
    pagination cursor merge uses — so "where a parameter lives in this body" has
    exactly one definition in the codebase. On a duplicate name the shallowest
    wins, which is that walker's breadth-first guarantee.
    """
    from urllib.parse import parse_qsl, urlsplit

    from .recipe_runner import iter_body_params

    params: dict[str, Any] = {}
    for key, value in parse_qsl(urlsplit(str(fetch.get("url") or "")).query):
        params.setdefault(_normalize_param(key), value)
    for _path, key, value in iter_body_params(fetch.get("body")):
        params.setdefault(_normalize_param(key), value)
    return params


def _as_int(value: Any) -> int | None:
    """The int a request parameter carries, or None. Strings count — a query
    string has no types, so ``?limit=20`` is the same claim as ``"limit": 20``.
    ``bool`` is excluded because ``True == 1`` would make a flag look like a page
    size of one."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def page_shape_refusal(recipe: dict[str, Any], n: int) -> str | None:
    """Checks 13a/13b — does the stored REQUEST say this read was one page?

    Returns the verdict reason to refuse under, or ``None`` if the request shows
    no sign of being page-limited. Pure, and safe on a malformed recipe: anything
    it cannot read is simply not a tell. This function may only ever make a
    verdict stricter — it never licences one.

    A recipe that DOES paginate is out of scope and returns ``None``: its
    completeness is judged by checks 5 and 6 (``cap_hit`` / ``page_advance_ok``),
    which are strictly stronger, and a paginating recipe is not ``none`` anyway.
    """
    steps = recipe.get("steps")
    if not isinstance(steps, list):
        return None
    if any(
        isinstance(step, dict) and str(step.get("op") or "").startswith("paginate_")
        for step in steps
    ):
        return None
    fetch = next(
        (s for s in steps if isinstance(s, dict) and s.get("op") == "fetch"), None
    )
    if fetch is None:
        return None

    params = _request_params(fetch)

    # 13a — a page index / offset in the request, and nothing advancing it.
    for key in params:
        if key in _PAGE_OFFSET_PARAMS or key.endswith(_PAGE_OFFSET_SUFFIXES):
            return "page_param_unpaginated"

    # 13b — an explicit page size, and the harvest came back exactly that big.
    for key, value in params.items():
        if key in _PAGE_SIZE_PARAMS and _as_int(value) == n:
            return "page_limit_reached"

    return None


def _limit_pinned(
    n: int, baseline: "Baseline", cadence_hours: float = _DEFAULT_CADENCE_HOURS
) -> bool:
    """Check 13c — has this board's count been pinned to a round page size?

    True iff ``n`` is one of the sizes a server defaults to AND the board has
    returned that identical number on its recent harvests. With no history the
    ``all()`` is vacuous and a round count refuses on its own, which is the safe
    direction on a board's first runs (they can never close regardless).

    THE WINDOW IS :func:`settled_prior_runs` ON PURPOSE, and it must not be widened.
    It is the same run length the settled-step release uses, and the coupling is
    the point: a count that has held one value long enough to be released as a
    genuine board shrink is, if that value is a round page size, at least as
    likely to be a scraper jammed against a server default. Give this check a
    LONGER window than the release and there is a gap between them where a board
    that jams at 100 satisfies the release, VERIFIES, and starts closing the
    hundreds of jobs it stopped being able to see. Same window, no gap: a
    settled step change can never re-baseline onto a page-size number.
    """
    if n not in _COMMON_PAGE_SIZES:
        return False
    return all(
        count == n
        for count in baseline.recent_records[: settled_prior_runs(cadence_hours)]
    )


class HarvestGateError(ValueError):
    """A hard structural-gate failure (dup ids, or a declared>0 vs 0-rows
    contradiction). Subclasses ``ValueError`` so the leaf task's narrow
    ``except`` records it as a FAILED run and lets Procrastinate retry. A FAILED
    run performs NO destructive writes and is explicitly NOT a miss.
    """


@dataclass(frozen=True)
class GateResult:
    """What the structural gate produced from a raw harvest.

    ``jobs`` is the post-dedup list actually written; ``records_harvested`` is
    ``len(jobs)``; ``id_dedup_dropped`` is how many duplicate-id rows check 7
    removed; ``is_zero`` is True for a legitimately-empty harvest that routed to
    the zero-proof chain (check 11) instead of raising.
    """

    jobs: list[JobListing]
    records_harvested: int
    id_dedup_dropped: int
    is_zero: bool = False


@dataclass(frozen=True)
class HarvestVerdict:
    """The gate's decision, its machine-readable reason, and the evidence the
    decision was computed from (mapped straight onto ``company_harvests``)."""

    verdict: str
    reason: str
    tolerance_used: float = 0.0
    oracle_total: int | None = None
    declared_total: int | None = None
    cap_hit: bool = False
    page_advance_ok: bool | None = None


def effective_oracle_kind(provider: str) -> str:
    """The oracle the gate uses for an ATS ``provider`` (DECISION D2).

    ``declared_probed`` for Greenhouse/Workday (trusted total); ``self_consistent``
    for Ashby/Lever/Gem/Eightfold (no trusted total). An unrecognized provider
    maps to ``'none'`` → UNVERIFIED, the safe default (it can never verify, so it
    can never close).
    """
    p = (provider or "").lower()
    if p in _DECLARED_PROBED_PROVIDERS:
        return "declared_probed"
    if p in _SELF_CONSISTENT_PROVIDERS:
        return "self_consistent"
    return "none"


def run_gate(
    jobs: list[JobListing],
    evidence: HarvestEvidence,
    *,
    oracle_kind: str,
    error_keys: tuple[str, ...] = ("error", "errors"),
    expected_min_jobs: int = DEFAULT_EXPECTED_MIN_JOBS,
) -> GateResult:
    """Structural pass — checks 2 (zero-aware), 3, 7-dedupe, 8. FAILED-only.

    Raises :class:`HarvestGateError` (→ FAILED) ONLY on:

    * **Check 2/10 (zero contradiction)**: 0 rows harvested while the ATS's
      trusted total says jobs exist (``declared_total > 0``). Rows and total
      disagree in a way that means a transport/parse anomaly — retry.
    * **Check 8 (unique key)**: the post-dedup ``id`` set is not unique — only
      reachable on a logic error after check 7.

    A 0-row harvest whose total is 0 or unknown is NOT raised: it routes to the
    zero-proof chain (check 11) in :func:`verify_harvest` via ``is_zero=True``.

    ``error_keys`` is a Phase-3 seam (check 3 — a fatal ``error``/``errors`` key
    in a 200 body): the rows reaching here are already-transformed ``JobListing``
    objects with no error channel, so the check is a documented no-op until Phase
    3 scripts feed raw payloads through a richer gate. ``expected_min_jobs`` is
    likewise reserved (the only floor exercised in Phase 2 is the zero split).
    """
    # Check 2 (zero-aware) + check 10 (contradiction is fatal in both directions).
    if len(jobs) == 0:
        declared = evidence.declared_total
        if declared is not None and declared > 0:
            raise HarvestGateError(
                f"harvest returned 0 rows but the ATS declared {declared} "
                f"job(s) exist (check 2/10 contradiction) — transport/parse "
                f"anomaly, refusing to treat as a completed run"
            )
        # Zero is potentially provable (declared 0, or no trusted total). Hand it
        # to the zero-proof chain; do NOT raise.
        return GateResult(jobs=[], records_harvested=0, id_dedup_dropped=0, is_zero=True)

    # Check 7 — dedupe by id, keeping first occurrence (document order).
    seen: set[str] = set()
    deduped: list[JobListing] = []
    for job in jobs:
        if job.id in seen:
            continue
        seen.add(job.id)
        deduped.append(job)
    id_dedup_dropped = len(jobs) - len(deduped)

    # Check 8 — assert the key field is unique post-dedup (defensive backstop).
    ids = [job.id for job in deduped]
    if len(ids) != len(set(ids)):
        raise HarvestGateError(
            "id field is not unique after dedupe (check 8) — logic error"
        )

    return GateResult(
        jobs=deduped,
        records_harvested=len(deduped),
        id_dedup_dropped=id_dedup_dropped,
    )


def verify_harvest(
    oracle_kind: str,
    harvest: GateResult,
    evidence: HarvestEvidence,
    baseline: "Baseline",
    *,
    recipe: dict[str, Any] | None = None,
    cadence_hours: float = _DEFAULT_CADENCE_HOURS,
) -> HarvestVerdict:
    """Verdict pass — checks 5, 6, 7-vs-total, 9, 10, 11, 12, 13. Never raises.

    ``oracle_kind`` is the EFFECTIVE oracle: for ATS companies the caller derives
    it from the provider (see :func:`effective_oracle_kind`); for a Phase-3
    discovered company it is the STORED ``company_scripts.oracle_kind``
    (``facet_sum``/``header``/``sitemap``/``self_consistent``/``none``). Returns
    VERIFIED or UNVERIFIED and NEVER raises — an unwired oracle degrades to
    UNVERIFIED, the safe default (it can never verify, so it can never close).

    ``cadence_hours`` is how often this company is harvested, and the two
    history-shaped checks read it rather than a bare run count so that editing the
    schedule cannot silently change what they mean — see :func:`settled_prior_runs`.

    ``recipe`` is the stored script, and passing it is what upgrades
    ``oracle_kind='none'`` from "permanently UNVERIFIED" to the history-delta
    oracle (:func:`_verify_history_delta`). **NO RECIPE, NO COMPLETENESS CLAIM**:
    the default is ``None``, so every caller that does not pass one — the six
    public ATS crons and the custom ATS path, where ``none`` means "unrecognized
    provider" rather than "single-request discovered board" — keeps the old
    ``no_oracle`` behaviour byte for byte. The new oracle is reachable only from
    the discovered-transport branch that has a recipe to reason about.
    """
    if oracle_kind == "none" and recipe is None:
        # An ATS provider we do not recognize, or a caller with nothing to
        # reason about. Unchanged from Phase 2: never claim completeness.
        return HarvestVerdict(UNVERIFIED, "no_oracle")
    if oracle_kind not in _EXACT_ORACLES and oracle_kind not in HISTORICAL_ORACLES:
        # Unknown/unwired oracle: never claim completeness we cannot prove.
        return HarvestVerdict(UNVERIFIED, "no_oracle")

    # Check 11 — zero-proof chain (only for a 0-row harvest).
    if harvest.is_zero:
        return _zero_proof(evidence)

    n = harvest.records_harvested

    # Check 5 — a pagination cap means completeness is unproven. This is exactly
    # where Target lands: declared 11,960, harvested 2,000, cap_hit=True.
    if evidence.cap_hit:
        return HarvestVerdict(
            UNVERIFIED, "cap_hit",
            declared_total=evidence.declared_total,
            cap_hit=True,
            page_advance_ok=evidence.page_advance_ok,
        )

    # Check 6 — a page that re-served prior ids (offset-wrap) is unproven. Keep
    # the rows (UNVERIFIED, not FAILED — FAILED would discard a valid partial).
    if evidence.page_advance_ok is False:
        return HarvestVerdict(
            UNVERIFIED, "page_advance_failed",
            declared_total=evidence.declared_total,
            page_advance_ok=False,
        )

    if oracle_kind == "declared_probed":
        return _verify_declared_probed(n, evidence)
    if oracle_kind in _PHASE_3_ORACLES:
        # facet_sum / header / sitemap — same exact-match ladder, distinct verdict
        # reason so the harvest audit row shows a Phase-3 oracle drove the verdict
        # (the oracle_kind column records WHICH one). Any cap / page-advance failure
        # already short-circuited above.
        return _verify_oracle_total(n, evidence, verified_reason="oracle_exact")
    if oracle_kind == "none":
        # ``recipe is None`` was rejected at the top, so this is a discovered
        # board with a stored request to reason about.
        assert recipe is not None
        return _verify_history_delta(n, evidence, baseline, recipe, cadence_hours)
    return _verify_self_consistent(n, evidence, baseline, cadence_hours)


def _verify_oracle_total(
    n: int, evidence: HarvestEvidence, *, verified_reason: str = "declared_exact"
) -> HarvestVerdict:
    """The exact-match (tolerance-0) ladder shared by every trusted-total oracle.

    Pass iff a trusted total exists AND ``len(deduped) == declared_total``, with no
    cap and no advance failure (both already checked by the caller). Under-count →
    ``count_mismatch`` (check 7/10); over-count → ``over_harvest`` (check 10 — a
    widened filter; the upsert is still safe, approximation may only add).

    Reused by ``declared_probed`` (Greenhouse/Workday ``meta.total``) and by the
    Phase-3 oracles (``facet_sum``/``header``/``sitemap``), whose total the runner
    computed into ``evidence.declared_total``. ``verified_reason`` distinguishes the
    two provenances on the VERIFIED row.
    """
    declared = evidence.declared_total
    if declared is None:
        # A trusted-total oracle with no total on this run cannot prove
        # completeness — treat as a count mismatch (we have rows but no oracle).
        return HarvestVerdict(UNVERIFIED, "count_mismatch")
    if n < declared:
        return HarvestVerdict(
            UNVERIFIED, "count_mismatch",
            oracle_total=declared, declared_total=declared,
        )
    if n > declared:
        return HarvestVerdict(
            UNVERIFIED, "over_harvest",
            oracle_total=declared, declared_total=declared,
        )
    return HarvestVerdict(
        VERIFIED, verified_reason,
        oracle_total=declared, declared_total=declared,
    )


def _verify_declared_probed(n: int, evidence: HarvestEvidence) -> HarvestVerdict:
    """Check 9 for ``declared_probed`` — EXACT match against the trusted total.

    NOTE (review Finding 4 — intentional, documented): unlike ``self_consistent``,
    ``declared_probed`` has NO trailing-median delta band — it VERIFIES on an
    exact ``n == declared_total`` regardless of how far the total moved from prior
    runs. A collapsing authoritative total (a Greenhouse board that legitimately
    reports 1000→50 in one night, matched exactly) is therefore caught NOT here
    but by the per-company safety guard (``min_ratio``) in the leaf task, which
    blocks the close when the board shrinks too fast. The oracle proves the run
    saw the whole board; the guard decides whether the shrink is trustworthy.
    """
    return _verify_oracle_total(n, evidence, verified_reason="declared_exact")


def _verify_self_consistent(
    n: int,
    evidence: HarvestEvidence,
    baseline: "Baseline",
    cadence_hours: float = _DEFAULT_CADENCE_HOURS,
) -> HarvestVerdict:
    """Check 9 + 12 for ``self_consistent`` — no trusted total, so completeness
    is the self-consistency conjunction plus the trailing-median delta band.

    ``cap_hit`` and ``page_advance_ok is False`` are already handled by the
    caller (checks 5, 6). Here: the loop must have terminated cleanly, and the
    count must sit within the delta band of the trailing-run median (when one
    exists). ``oracle_total`` stays None (there is no oracle count); Eightfold's
    ``count`` is carried as ``declared_total`` for the record but never trusted.
    """
    if not evidence.terminated_cleanly:
        return HarvestVerdict(
            UNVERIFIED, "not_terminated_cleanly",
            declared_total=evidence.declared_total,
            page_advance_ok=evidence.page_advance_ok,
        )

    # Check 12 — delta vs trailing-run median (only when a median exists).
    if not in_delta_band(n, baseline, cadence_hours):
        return HarvestVerdict(
            UNVERIFIED, "delta_anomaly",
            declared_total=evidence.declared_total,
            page_advance_ok=evidence.page_advance_ok,
        )

    return HarvestVerdict(
        VERIFIED, "self_consistent_ok",
        declared_total=evidence.declared_total,
        page_advance_ok=evidence.page_advance_ok,
    )


def _settled_step_change(
    n: int, baseline: "Baseline", cadence_hours: float
) -> bool:
    """Have the last :func:`settled_prior_runs` harvests all returned exactly
    ``n``? See the constant block: a real board shrink HOLDS its new number, a
    truncation WANDERS, and that is measured, not assumed.

    Requires a FULL run of identical counts — a board with less history than
    that has not settled anything and gets no release.
    """
    required = settled_prior_runs(cadence_hours)
    prior = baseline.recent_records[:required]
    if len(prior) < required:
        return False
    return all(count == n for count in prior)


def in_delta_band(
    n: int, baseline: "Baseline", cadence_hours: float = _DEFAULT_CADENCE_HOURS
) -> bool:
    """Check 12 — is ``n`` close enough to the trailing VERIFIED median to be a
    board that moved rather than a read that broke?

    Vacuously True with no median (a board's first runs cannot close anyway —
    ``first_verified_run`` and the VERIFIED streak both block them). Otherwise
    out of band on EITHER low rule or the high rule, then rescued only by a
    settled step change. Exported (no underscore) because the simulation test
    replays real harvest histories through exactly this function; there is no
    second copy of the arithmetic to drift from it.
    """
    median = baseline.median_records
    if median is None or median <= 0:
        return True

    hard_low = n < median * _DELTA_HARD_LOW_RATIO
    soft_low = (
        n < median * _DELTA_LOW_RATIO and (median - n) >= _DELTA_MIN_ABS_DROP
    )
    high = n > median * _DELTA_HIGH_RATIO
    if not (hard_low or soft_low or high):
        return True
    return _settled_step_change(n, baseline, cadence_hours)


def _verify_history_delta(
    n: int,
    evidence: HarvestEvidence,
    baseline: "Baseline",
    recipe: dict[str, Any],
    cadence_hours: float = _DEFAULT_CADENCE_HOURS,
) -> HarvestVerdict:
    """Checks 12 + 13 for ``oracle_kind='none'`` — the history-delta oracle.

    THE PROBLEM THIS SOLVES. Discovery stores ``none`` for a recipe with no
    declared total and no pagination, and until now ``verify_harvest`` answered
    ``no_oracle`` for it forever. Every board discovered that way — Walmart,
    Atlassian, Jane Street — was therefore UNVERIFIED on every run it would ever
    make, which means it could never increment a miss and never close a job. The
    product consequence is the one that actually matters: filled roles stay OPEN
    forever, counts only drift upward, and the board lies to the user.

    WHAT IT CLAIMS, AND WHAT IT DOES NOT. ``declared_probed`` proves completeness
    ("an independent source said 232 and we harvested 232"). This proves nothing
    of the kind. It says: *this board has consistently returned about this many
    rows, its request does not look like one page of a longer list, and this run
    is consistent with that history.* That is EMPIRICAL rather than deductive, so
    it is hedged three ways the structural oracles are not — the page-shape tells
    below, a stricter close-time VERIFIED streak
    (``_NO_ORACLE_STREAK_REQUIRED``), and the id-churn guard, both in
    ``tasks.fetch_custom_company``.

    Order is deliberate: the tells that say "this read was structurally short"
    run BEFORE the statistical band, because a board that is always truncated has
    a perfectly stable history of truncated counts and would sail through a
    band alone. That is the Walmart shape exactly.
    """
    # Check 13d — ``http_html`` cannot earn an EMPIRICAL oracle, because the one
    # piece of evidence this oracle leans on is a constant there.
    #
    # Every other check below is hedging around ``terminated_cleanly``: the
    # history-delta oracle proves nothing deductively, so it needs "the sweep ran to a
    # short page" to be a real statement about the board before the page-shape tells
    # and the delta band are worth anything. ``recipe_runner._run_http_html`` issues
    # ONE request and hard-codes ``terminated_cleanly=True`` — it has no sweep, so it
    # cannot know whether that document was the whole board or page one of forty. The
    # gate below is therefore VACUOUS on this transport, and a vacuous gate in front of
    # a statistical band is how a permanently truncated board acquires a perfectly
    # stable history of truncated counts and sails through (the Walmart shape, which
    # this function's own docstring names as the thing to avoid).
    #
    # The concrete failure it forecloses: a paginating careers page whose records live
    # in the served document. ``capture.discover`` emits ``http_html`` for it (sources
    # 2 and 6 — the document became a candidate) and DROPS the pagination step, because
    # ``validate_recipe`` forbids paging on this transport. So we read page one nightly
    # and forever. Jobs that rotate off page one are still open on page two, but they
    # are absent from two consecutive runs — and with a VERIFIED verdict the leaf task
    # closes them. That is a wrong close, which is the one thing this module exists to
    # prevent.
    #
    # This does NOT make ``http_html`` unclosable. It makes it closable only on a
    # TRUSTED TOTAL — ``declared_probed`` / ``facet_sum`` / ``header`` / ``sitemap``,
    # every one of which demands ``n == declared_total`` exactly, which a page-one read
    # of a longer board cannot satisfy. Proof beats a stable history here; nothing else
    # does.
    if str(recipe.get("transport") or "") == HTTP_HTML:
        return HarvestVerdict(
            UNVERIFIED, "html_no_sweep_evidence",
            declared_total=evidence.declared_total,
            page_advance_ok=evidence.page_advance_ok,
        )

    if not evidence.terminated_cleanly:
        return HarvestVerdict(
            UNVERIFIED, "not_terminated_cleanly",
            declared_total=evidence.declared_total,
            page_advance_ok=evidence.page_advance_ok,
        )

    # Check 13a/13b — the request's own shape says this was one page.
    shape = page_shape_refusal(recipe, n)
    if shape is not None:
        return HarvestVerdict(
            UNVERIFIED, shape,
            declared_total=evidence.declared_total,
            page_advance_ok=evidence.page_advance_ok,
        )

    # Check 13c — no parameter, but the count is pinned to a round page size.
    if _limit_pinned(n, baseline, cadence_hours):
        return HarvestVerdict(
            UNVERIFIED, "page_limit_pinned",
            declared_total=evidence.declared_total,
            page_advance_ok=evidence.page_advance_ok,
        )

    # Check 12 — the count is consistent with what this board has been returning.
    if not in_delta_band(n, baseline, cadence_hours):
        return HarvestVerdict(
            UNVERIFIED, "delta_anomaly",
            declared_total=evidence.declared_total,
            page_advance_ok=evidence.page_advance_ok,
        )

    return HarvestVerdict(
        VERIFIED, "history_delta_ok",
        declared_total=evidence.declared_total,
        page_advance_ok=evidence.page_advance_ok,
    )


def _zero_proof(evidence: HarvestEvidence) -> HarvestVerdict:
    """Check 11 — can a 0-row harvest be *proven* genuinely empty?

    * ``declared_total == 0`` on a live 200 (a trusted ATS declaring zero) →
      VERIFIED ``zero_proven``. It still closes nothing this run: the leaf task's
      ``empty_scrape`` safety guard trips on ``jobs_seen=0``, matching the
      2026-03-29 lesson that a board→0 on a single run is indistinguishable from
      a scraper outage.
    * ``declared_total is None`` (Ashby/Lever/Gem/Eightfold — Marcus & Millichap
      is a Lever ``200 []``) → the zero cannot be proven from the payload. The
      canonical-backlink / brand-present signals that COULD prove it are Phase-3
      DOM checks. So UNVERIFIED ``zero_unproven`` → never closes.

    The ``declared_total > 0`` contradiction never reaches here — ``run_gate``
    raised it as FAILED.

    Phase 3: add canonical_backlink + brand signals to this chain (the leaf
    caller and verdict shape do not change).
    """
    if evidence.declared_total == 0 and evidence.transport_ok:
        return HarvestVerdict(
            VERIFIED, "zero_proven", oracle_total=0, declared_total=0,
        )
    return HarvestVerdict(UNVERIFIED, "zero_unproven")


# --- Comparability, which is NOT verification --------------------------------
# UNVERIFIED reasons that mean "no proof was AVAILABLE", as opposed to "the read
# stopped early". ``no_oracle`` is the entire list, and it is the whole of what
# :func:`read_untruncated` adds over ``verdict == VERIFIED``.
#
# Every other UNVERIFIED reason is, or may be, a SHORT READ and is excluded:
# ``cap_hit`` (a ceiling stopped the sweep), ``page_advance_failed`` (offset
# wrap), ``not_terminated_cleanly`` (ran out of page budget), ``count_mismatch``
# (n < a trusted total — a PROVEN short read), ``delta_anomaly`` (the count moved
# far enough off the trailing median that the data is likelier wrong than the
# board), ``over_harvest`` (n > the trusted total — not short, but the filter
# widened, so the set is not the board's set either) and ``zero_unproven``.
#
# The three check-13 reasons — ``page_param_unpaginated``, ``page_limit_reached``
# and ``page_limit_pinned`` — are excluded for the same reason, and their
# exclusion is a deliberate behaviour CHANGE, not an oversight. Before the
# history-delta oracle a Walmart-shaped board answered ``no_oracle`` and was
# therefore treated as comparable; its ten rows were being offered to the
# published-board matcher as if they were the whole board. They are not, and now
# the matcher is told so.
_UNTRUNCATED_UNVERIFIED_REASONS = frozenset({"no_oracle"})


def read_untruncated(verdict: HarvestVerdict, evidence: HarvestEvidence) -> bool:
    """Did this run read the whole of what its recipe knows how to read?

    **THIS IS NOT A VERDICT AND IT LICENCES NOTHING DESTRUCTIVE.** ``VERIFIED``
    remains the only thing that may close a job, increment a miss, or move
    ``health_state`` / ``tracking_started_at``. No close-path code calls this
    function, and none may ever start to. Read the two claims side by side:

    * ``VERIFIED``          — "an independent source told us how many jobs this
                              board has, and we harvested exactly that many."
    * ``read_untruncated``  — "nothing in this run says the read stopped early."

    The second is NEGATIVE evidence, and negative evidence is the correct strength
    for a read-only comparison whose worst outcome is one dismissible banner (E7
    unit 10 — :mod:`api.services.published_board_match`). It is nowhere near strong
    enough to delete a user's jobs, which is why the close ladder in
    ``fetch_custom_company`` still branches on ``verdict != VERIFIED`` and on
    nothing else.

    **Why the gap exists at all.** A board that returns its whole catalogue in ONE
    request — lifeatspotify, Atlassian, Jane Street, SpaceX, Rockstar — is stored
    with ``oracle_kind='none'`` by discovery, deliberately: one response holding 79
    jobs is indistinguishable from page one of a 400-job board that never mentioned
    its length (``capture/discover.synthesize_recipe``, "the one place discovery
    may not be generous"). That ambiguity is real and unresolvable *from the
    harvest alone*, which is why this weaker question existed before the
    history-delta oracle did. It has narrowed since: a ``none`` board that clears
    checks 12 and 13 now reaches VERIFIED on its own, and one that fails check 13
    is now correctly reported as NOT comparable. What is left in the gap is the
    genuinely unproven middle — an unrecognized ATS provider, or a stored script
    edited out of sync with its ``oracle_kind`` column. For those the run still
    issued its one request, got a 200, and mapped every record in the body.
    Nothing was cut off *by us*, and "cut off by us" is the failure the comparison
    actually cares about.

    The conjunction below is what "not cut off by us" means, and it is read off the
    EVIDENCE rather than the verdict — deliberately. ``verify_harvest`` returns
    ``no_oracle`` before it ever reaches check 5 or check 6, so the ``HarvestVerdict``
    for such a run carries the *defaults* for these three fields; reading them off
    the verdict would quietly always be true.

    * ``cap_hit`` — a ceiling (window, record, or wall-clock budget) stopped it;
    * ``terminated_cleanly`` — it ended on a short/empty page rather than
      exhausting its page budget;
    * ``page_advance_ok is False`` — a page re-served ids we already had.

    For the single-request class all three are constants (no sweep, no cap, one
    page), so for THOSE boards this reduces to "the verdict reason was
    ``no_oracle``". They are still checked, because ``oracle_kind='none'`` is not a
    synonym for "no pagination": an unrecognized ATS provider (see
    :func:`effective_oracle_kind`) and a stored script edited out of sync with its
    ``oracle_kind`` column both reach ``no_oracle`` with a real sweep behind them,
    and a capped sweep is exactly the shape whose title set must not be compared.

    A ``FAILED`` run is never comparable: it wrote no rows, so the OPEN set sitting
    in the database is somebody else's run, not this one's.
    """
    if verdict.verdict == FAILED:
        return False
    if evidence.cap_hit:
        return False
    if not evidence.terminated_cleanly:
        return False
    if evidence.page_advance_ok is False:
        return False
    if verdict.verdict == VERIFIED:
        return True
    return verdict.reason in _UNTRUNCATED_UNVERIFIED_REASONS
