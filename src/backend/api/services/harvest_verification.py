"""The verification gate + verdict for custom-company harvests (E7).

This is the module Phase 2 extends. In Phase 1 it ships only the *minimal* gate
— checks 1, 2, 7-dedup, and 8 from BUILD-PLAN §3 — plus the load-bearing rule
that a harvest with ``oracle_kind='none'`` is always **UNVERIFIED**.

The verdict ladder (BUILD-PLAN §1.1):

* ``FAILED``     — transport/parse error, or a gate check raised. The leaf task
                   writes nothing destructive, records the run, and re-raises so
                   Procrastinate retries. A FAILED (non-executed) run is NOT a
                   miss.
* ``UNVERIFIED`` — rows were harvested but completeness could not be proven (no
                   oracle exists yet). The leaf task upserts + refreshes
                   last_seen ONLY. It NEVER increments misses and NEVER closes.
* ``VERIFIED``   — every applicable gate check passed exactly. Phase 2+ only;
                   unreachable in Phase 1 because no oracle is wired.

Why UNVERIFIED still upserts: the ``ON CONFLICT`` clause is purely protective
(``status='OPEN'``, ``closed_on=NULL``, ``consecutive_misses=0``). Writing the
rows we *did* get can only move jobs away from closure — we distrust the
*absence* of the rest, not the presence of these.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from scripts.shared.models import JobListing

# --- Verdicts ----------------------------------------------------------------
VERIFIED = "VERIFIED"
UNVERIFIED = "UNVERIFIED"
FAILED = "FAILED"

# The floor for check 2. A custom company is only created after its add-time
# probe returned job_count > 0, so a harvest that comes back empty is a
# transport/board anomaly, not a legitimately empty board (proving a board is
# genuinely at zero is the Phase-2 "zero-proof chain", check 11). Raising here
# lands the run FAILED — it writes nothing destructive and is not a miss —
# rather than letting an empty list reach the destructive path.
DEFAULT_EXPECTED_MIN_JOBS = 1


class HarvestGateError(ValueError):
    """A hard minimal-gate failure (empty harvest, below floor, or dup ids).

    Subclasses ``ValueError`` so the leaf task's narrow ``except`` tuple records
    it as a failed run and lets Procrastinate retry. Per the ladder a FAILED run
    performs NO destructive writes and is explicitly NOT counted as a miss.
    """


@dataclass(frozen=True)
class GateResult:
    """What the minimal gate produced from a raw harvest.

    ``jobs`` is the post-dedup list actually written; ``records_harvested`` is
    ``len(jobs)``; ``id_dedup_dropped`` is how many duplicate-id rows check 7
    removed (recorded on ``company_harvests`` so a noisy source is visible).
    """

    jobs: list[JobListing]
    records_harvested: int
    id_dedup_dropped: int


def run_minimal_gate(
    jobs: list[JobListing],
    *,
    expected_min_jobs: int = DEFAULT_EXPECTED_MIN_JOBS,
) -> GateResult:
    """Checks 1, 2, 7-dedup and 8 — every step fatal (raises, never returns []).

    * **Check 1 (transport)** is implicit: reaching this function means the ATS
      client returned without raising, i.e. the HTTP/transport status was in the
      allowed set. A transport failure raised earlier and is a FAILED run.
    * **Check 2 (non-empty + floor)**: ``len(jobs) < expected_min_jobs`` RAISES.
      Never returns ``[]`` — an empty/short harvest must not reach the write
      path where (in later phases) it could drive closures.
    * **Check 7 (dedupe)**: drop later rows sharing an ``id`` (keep first seen).
    * **Check 8 (unique key)**: assert the post-dedup ``id`` set is unique — a
      defensive backstop; after check 7 it can only fail on a logic error.
    """
    if len(jobs) < expected_min_jobs:
        raise HarvestGateError(
            f"harvest returned {len(jobs)} row(s), below the expected minimum "
            f"of {expected_min_jobs}; refusing to treat an empty/short harvest "
            f"as a completed run"
        )

    # Check 7 — dedupe by id, keeping first occurrence (document order).
    seen: set[str] = set()
    deduped: list[JobListing] = []
    for job in jobs:
        if job.id in seen:
            continue
        seen.add(job.id)
        deduped.append(job)
    id_dedup_dropped = len(jobs) - len(deduped)

    # Check 8 — assert the key field is unique post-dedup.
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


@dataclass(frozen=True)
class HarvestVerdict:
    """The gate's decision plus a machine-readable reason."""

    verdict: str
    reason: str


def verify_harvest(
    script: Mapping[str, object],
    harvest: GateResult,
    baseline: object | None = None,
) -> HarvestVerdict:
    """Decide VERIFIED / UNVERIFIED / FAILED for a harvest that passed the gate.

    Phase 1: a company's ``oracle_kind`` is always ``'none'`` (a one-primitive
    ATS-client script cannot prove completeness), so this always returns
    UNVERIFIED. ``baseline`` (trailing-run stats, per-company learned ratios) is
    reserved for the Phase-2 oracles and self-consistency checks; it is unused
    here and accepted so the signature is stable across phases.

    ``script`` is the ``company_scripts`` row as a mapping (it carries
    ``oracle_kind``). Anything other than a recognized, wired oracle stays
    UNVERIFIED — the safe default is to never claim completeness we cannot prove.
    """
    oracle_kind = str(script.get("oracle_kind") or "none")
    if oracle_kind == "none":
        return HarvestVerdict(UNVERIFIED, "no_oracle")
    # Phase 2 wires the real oracles (facet_sum / header / sitemap /
    # self_consistent). Until then, an unrecognized/unwired oracle is UNVERIFIED
    # — never VERIFIED by default.
    return HarvestVerdict(UNVERIFIED, "oracle_not_wired")
