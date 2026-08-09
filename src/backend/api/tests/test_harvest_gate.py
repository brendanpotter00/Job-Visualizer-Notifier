"""E7 Phase 2 gate unit tests — pure, no DB.

Constructs ``JobListing`` rows + ``HarvestEvidence`` + ``Baseline`` directly and
drives ``run_gate`` / ``verify_harvest`` so every BUILD-PLAN §3 check is pinned
without a database or a network call. Covers both oracles (declared_probed,
self_consistent), the zero-proof chain, and the Phase-3 ``NotImplementedError``
seam.
"""

from __future__ import annotations

import pytest

from api.services.custom_baseline import Baseline
from api.services.harvest_meta import HarvestEvidence
from api.services.harvest_verification import (
    UNVERIFIED,
    VERIFIED,
    HarvestGateError,
    run_gate,
    verify_harvest,
)
from scripts.shared.models import JobListing


def _job(i: int) -> JobListing:
    return JobListing(
        id=str(i), title="Engineer", company="c", location="Remote",
        url=f"https://x/{i}", source_id="custom:c", details={},
        posted_on=None, created_at="2025-01-01T00:00:00.000Z",
        first_seen_at="2025-01-01T00:00:00.000Z",
        last_seen_at="2025-01-01T00:00:00.000Z", consecutive_misses=0,
        details_scraped=True, status="OPEN", has_matched=False,
        ai_metadata={}, closed_on=None,
    )


def _jobs(n: int) -> list[JobListing]:
    return [_job(i) for i in range(n)]


def _baseline(median: float | None) -> Baseline:
    return Baseline(median_records=median, run_count=0, min_ratio=0.5)


# --- declared_probed --------------------------------------------------------

def test_declared_probed_exact_verifies():
    jobs = _jobs(65)
    ev = HarvestEvidence.single_shot(declared_total=65)
    gate = run_gate(jobs, ev, oracle_kind="declared_probed")
    v = verify_harvest("declared_probed", gate, ev, _baseline(None))
    assert v.verdict == VERIFIED
    assert v.reason == "declared_exact"
    assert v.tolerance_used == 0.0
    assert v.oracle_total == 65


def test_declared_probed_cap_hit_is_unverified():
    """The Target shape: declared 11,960, harvested 2,000, cap_hit=True."""
    jobs = _jobs(2000)
    ev = HarvestEvidence(
        declared_total=11960, cap_hit=True, terminated_cleanly=False,
        page_advance_ok=True, pages_fetched=100,
    )
    gate = run_gate(jobs, ev, oracle_kind="declared_probed")
    v = verify_harvest("declared_probed", gate, ev, _baseline(None))
    assert v.verdict == UNVERIFIED
    assert v.reason == "cap_hit"
    assert v.cap_hit is True
    assert v.declared_total == 11960


def test_declared_probed_undercount_is_count_mismatch():
    jobs = _jobs(900)
    ev = HarvestEvidence.single_shot(declared_total=1000)
    gate = run_gate(jobs, ev, oracle_kind="declared_probed")
    v = verify_harvest("declared_probed", gate, ev, _baseline(None))
    assert v.verdict == UNVERIFIED
    assert v.reason == "count_mismatch"


def test_declared_probed_overcount_is_over_harvest():
    jobs = _jobs(1100)
    ev = HarvestEvidence.single_shot(declared_total=1000)
    gate = run_gate(jobs, ev, oracle_kind="declared_probed")
    v = verify_harvest("declared_probed", gate, ev, _baseline(None))
    assert v.verdict == UNVERIFIED
    assert v.reason == "over_harvest"


def test_declared_probed_page_advance_failure_is_unverified():
    jobs = _jobs(1000)
    ev = HarvestEvidence(
        declared_total=1000, cap_hit=False, terminated_cleanly=True,
        page_advance_ok=False, pages_fetched=50,
    )
    gate = run_gate(jobs, ev, oracle_kind="declared_probed")
    v = verify_harvest("declared_probed", gate, ev, _baseline(None))
    assert v.verdict == UNVERIFIED
    assert v.reason == "page_advance_failed"


# --- self_consistent --------------------------------------------------------

def test_self_consistent_within_band_verifies():
    jobs = _jobs(1000)
    ev = HarvestEvidence.single_shot(declared_total=None)
    gate = run_gate(jobs, ev, oracle_kind="self_consistent")
    v = verify_harvest("self_consistent", gate, ev, _baseline(1000))
    assert v.verdict == VERIFIED
    assert v.reason == "self_consistent_ok"
    assert v.oracle_total is None


def test_self_consistent_first_run_no_median_verifies():
    """No trailing median yet → the delta check is skipped; the single-shot run
    still VERIFIES (closing is separately gated by the 3-run streak)."""
    jobs = _jobs(500)
    ev = HarvestEvidence.single_shot(declared_total=None)
    gate = run_gate(jobs, ev, oracle_kind="self_consistent")
    v = verify_harvest("self_consistent", gate, ev, _baseline(None))
    assert v.verdict == VERIFIED
    assert v.reason == "self_consistent_ok"


def test_self_consistent_delta_anomaly_is_unverified():
    jobs = _jobs(300)
    ev = HarvestEvidence.single_shot(declared_total=None)
    gate = run_gate(jobs, ev, oracle_kind="self_consistent")
    v = verify_harvest("self_consistent", gate, ev, _baseline(1000))
    assert v.verdict == UNVERIFIED
    assert v.reason == "delta_anomaly"


def test_self_consistent_cap_is_unverified():
    """Eightfold hit its 1,000 cap → cap_hit dominates even for self_consistent."""
    jobs = _jobs(1000)
    ev = HarvestEvidence(
        declared_total=1000, cap_hit=True, terminated_cleanly=False,
        page_advance_ok=True, pages_fetched=100,
    )
    gate = run_gate(jobs, ev, oracle_kind="self_consistent")
    v = verify_harvest("self_consistent", gate, ev, _baseline(1000))
    assert v.verdict == UNVERIFIED
    assert v.reason == "cap_hit"


# --- zero-proof chain -------------------------------------------------------

def test_zero_with_declared_zero_is_zero_proven():
    ev = HarvestEvidence.single_shot(declared_total=0)
    gate = run_gate([], ev, oracle_kind="declared_probed")
    assert gate.is_zero is True
    v = verify_harvest("declared_probed", gate, ev, _baseline(None))
    assert v.verdict == VERIFIED
    assert v.reason == "zero_proven"


def test_zero_with_no_declared_total_is_zero_unproven():
    """Marcus & Millichap: a Lever ``200 []`` — the zero cannot be proven."""
    ev = HarvestEvidence.single_shot(declared_total=None)
    gate = run_gate([], ev, oracle_kind="self_consistent")
    assert gate.is_zero is True
    v = verify_harvest("self_consistent", gate, ev, _baseline(None))
    assert v.verdict == UNVERIFIED
    assert v.reason == "zero_unproven"


def test_zero_with_positive_declared_total_raises():
    """Declared > 0 but 0 rows is a contradiction → FAILED (run_gate raises)."""
    ev = HarvestEvidence.single_shot(declared_total=5)
    with pytest.raises(HarvestGateError):
        run_gate([], ev, oracle_kind="declared_probed")


# --- structural + Phase-3 seam ----------------------------------------------

def test_duplicate_ids_are_deduped_by_run_gate():
    jobs = _jobs(3) + [_job(0)]  # id "0" repeated
    ev = HarvestEvidence.single_shot(declared_total=3)
    gate = run_gate(jobs, ev, oracle_kind="declared_probed")
    assert gate.records_harvested == 3
    assert gate.id_dedup_dropped == 1


def test_phase3_oracle_raises_not_implemented():
    jobs = _jobs(10)
    ev = HarvestEvidence.single_shot(declared_total=10)
    gate = run_gate(jobs, ev, oracle_kind="facet_sum")
    with pytest.raises(NotImplementedError):
        verify_harvest("facet_sum", gate, ev, _baseline(None))
