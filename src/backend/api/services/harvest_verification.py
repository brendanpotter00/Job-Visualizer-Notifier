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

The two functions split by what each may do:

* :func:`run_gate` — the *structural* pass (checks 2 zero-aware, 3, 7-dedupe, 8).
  Raises :class:`HarvestGateError` (→ FAILED) ONLY on a genuinely broken run.
* :func:`verify_harvest` — the *verdict* pass (checks 5, 6, 7-vs-total, 9, 10, 11,
  12). Returns VERIFIED | UNVERIFIED and NEVER raises.

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

from dataclasses import dataclass
from typing import TYPE_CHECKING

from scripts.shared.models import JobListing

from .harvest_meta import HarvestEvidence

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

# --- self_consistent delta band (check 12) ----------------------------------
# A self_consistent run is a delta anomaly if its record count falls outside
# [median * LOW, median * HIGH] of the trailing-run median. Symmetric-ish band:
# a board halving or doubling in a single run is the "wrong data, not missing
# data" signal the self-consistency oracle exists to catch. Only applied once a
# median exists (>= 1 prior VERIFIED run); the very first run skips it (and can
# only VERIFY, never close, because closing also needs the 3-run streak).
_SELF_CONSISTENT_DELTA_LOW_RATIO = 0.5
_SELF_CONSISTENT_DELTA_HIGH_RATIO = 2.0

# Phase-3 oracles — now WIRED (Phase 3a). Each is an exact-match (tolerance-0)
# oracle whose total rides ``evidence.declared_total``, computed upstream by
# ``recipe_runner`` (facet_sum = single-valued facet Σ, header = X-WP-Total-style
# int, sitemap = <loc> count). They share ``_verify_oracle_total`` with
# ``declared_probed`` — the run VERIFIES iff the post-dedup count equals the total.
_PHASE_3_ORACLES = frozenset({"facet_sum", "header", "sitemap"})

# Every exact-match oracle: the Phase-2 ``declared_probed`` plus the three Phase-3
# oracles. All compare the post-dedup count to a trusted total at tolerance 0.
_EXACT_ORACLES = _PHASE_3_ORACLES | {"declared_probed"}


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
) -> HarvestVerdict:
    """Verdict pass — checks 5, 6, 7-vs-total, 9, 10, 11, 12. Never raises.

    ``oracle_kind`` is the EFFECTIVE oracle: for ATS companies the caller derives
    it from the provider (see :func:`effective_oracle_kind`); for a Phase-3
    discovered company it is the STORED ``company_scripts.oracle_kind``
    (``facet_sum``/``header``/``sitemap``/``self_consistent``). Returns VERIFIED or
    UNVERIFIED and NEVER raises — an unwired oracle degrades to UNVERIFIED, the safe
    default (it can never verify, so it can never close).
    """
    if oracle_kind not in _EXACT_ORACLES and oracle_kind != "self_consistent":
        # Unknown/unwired oracle (e.g. an unrecognized provider): never claim
        # completeness we cannot prove.
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
    return _verify_self_consistent(n, evidence, baseline)


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
    n: int, evidence: HarvestEvidence, baseline: "Baseline"
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
    median = baseline.median_records
    if median is not None and median > 0:
        low = median * _SELF_CONSISTENT_DELTA_LOW_RATIO
        high = median * _SELF_CONSISTENT_DELTA_HIGH_RATIO
        if not (low <= n <= high):
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
    may not be generous"). That ambiguity is real and unresolvable from the
    harvest, so those boards stay UNVERIFIED forever and close nothing, forever.
    But it does not follow that their title set is unusable: the run issued its one
    request, got a 200, and mapped every record in the body. Nothing was cut off
    *by us*, and "cut off by us" is the failure the comparison actually cares
    about.

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
