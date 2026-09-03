"""E7 Phase 2 Task C — per-company baseline arithmetic.

PROD-VERIFY note: the ``p01`` tuning cannot be validated locally (it needs ~14
daily prod runs). These tests prove the ARITHMETIC only — the 0.5 floor until 14
runs, the clamp/floor math on a synthetic 14-run history, the median, and that
only VERIFIED harvests count.
"""

from __future__ import annotations

import pytest
from psycopg2 import sql

from api.services.custom_baseline import compute_baseline


def _insert_harvest(db_conn, company_id, records, verdict, day):
    cur = db_conn.cursor()
    started = f"2025-01-{day:02d}T00:00:00.000Z"
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (company_id, run_id, started_at, completed_at, "
            "verdict, verdict_reason, records_harvested, oracle_kind) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
        ).format(sql.Identifier("company_harvests")),
        (company_id, f"run-{company_id}-{day}", started, started, verdict,
         "x", records, "self_consistent"),
    )
    db_conn.commit()


def test_recent_records_is_not_verdict_filtered(db_conn):
    """**The window the page-limit tell reads, and why it cannot be the median's.**

    ``median_records`` is VERIFIED-only, on purpose — an unproven run must never
    become the baseline a later run is measured against. But the two checks that
    ask "what has this board been RETURNING lately?" need the opposite: a board
    that has never verified (which is every discovered board on the day this
    lands, Walmart included) has an EMPTY verified window, and a check that read
    the median there would be blind on exactly the boards it exists for.
    """
    cid = "u-baselinerecent1"
    for day, rec in enumerate([10, 10, 10, 10, 10], start=1):
        _insert_harvest(db_conn, cid, rec, "UNVERIFIED", day)
    b = compute_baseline(db_conn, cid)
    assert b.median_records is None, "no VERIFIED run may ever produce a median"
    assert b.run_count == 0
    assert b.recent_records == (10, 10, 10, 10, 10), (
        "the unfiltered window must still see the board's five UNVERIFIED reads"
    )


def test_recent_records_excludes_failed_runs(db_conn):
    """A FAILED run harvested nothing and wrote nothing — it is explicitly not a
    miss, and it is not an observation of the board either. Letting its zero into
    the window would poison both consumers: a run of zeros looks exactly like a
    settled step change, and a zero next to a real count breaks the identical-run
    test that the page-limit tell depends on."""
    cid = "u-baselinerecent2"
    _insert_harvest(db_conn, cid, 233, "VERIFIED", 1)
    _insert_harvest(db_conn, cid, 0, "FAILED", 2)
    _insert_harvest(db_conn, cid, 233, "VERIFIED", 3)
    b = compute_baseline(db_conn, cid)
    assert 0 not in b.recent_records
    assert b.recent_records == (233, 233)


def test_recent_records_is_newest_first(db_conn):
    """Ordering is load-bearing: both consumers slice a PREFIX of this tuple to
    mean "the most recent N harvests". Oldest-first would silently make them read
    a board's ancient history instead."""
    cid = "u-baselinerecent3"
    for day, rec in enumerate([100, 200, 300], start=1):
        _insert_harvest(db_conn, cid, rec, "VERIFIED", day)
    assert compute_baseline(db_conn, cid).recent_records == (300, 200, 100)


def test_min_ratio_is_floor_below_14_runs(db_conn):
    cid = "u-baseline01"
    for day, rec in enumerate([1000, 400, 1000, 200, 1000], start=1):
        _insert_harvest(db_conn, cid, rec, "VERIFIED", day)
    b = compute_baseline(db_conn, cid)
    assert b.run_count == 5
    # Below 14 calibrated runs, min_ratio is the conservative 0.5 floor even
    # though the raw deltas (200/1000 = 0.2) would otherwise push it lower.
    assert b.min_ratio == 0.5


def test_stable_history_calibrates_to_ceiling(db_conn):
    cid = "u-baseline02"
    for day in range(1, 15):  # 14 VERIFIED runs, all 1000 → ratios all 1.0
        _insert_harvest(db_conn, cid, 1000, "VERIFIED", day)
    b = compute_baseline(db_conn, cid)
    assert b.run_count == 14
    # p01 = 1.0 → min(0.85, 0.95) = 0.85 → the ceiling.
    assert b.min_ratio == pytest.approx(0.85)


def test_single_deep_drop_floors_min_ratio(db_conn):
    cid = "u-baseline03"
    # One 1000→400 drop (ratio 0.4); everything else stable.
    recs = [1000] * 7 + [400] + [1000] * 6
    for day, rec in enumerate(recs, start=1):
        _insert_harvest(db_conn, cid, rec, "VERIFIED", day)
    b = compute_baseline(db_conn, cid)
    # p01 = 0.4 → min(0.85, 0.35) = 0.35 → clamped up to the 0.5 floor.
    assert b.min_ratio == 0.5


def test_moderate_drop_clamps_between_floor_and_ceiling(db_conn):
    cid = "u-baseline04"
    # One 1000→700 drop (ratio 0.70) is the only sub-1.0 ratio.
    recs = [1000] * 7 + [700] + [1000] * 6
    for day, rec in enumerate(recs, start=1):
        _insert_harvest(db_conn, cid, rec, "VERIFIED", day)
    b = compute_baseline(db_conn, cid)
    # p01 = 0.70 → min(0.85, 0.65) = 0.65 (inside the band).
    assert b.min_ratio == pytest.approx(0.65)


def test_median_over_verified_only(db_conn):
    cid = "u-baseline05"
    _insert_harvest(db_conn, cid, 10, "VERIFIED", 1)
    _insert_harvest(db_conn, cid, 20, "VERIFIED", 2)
    _insert_harvest(db_conn, cid, 30, "VERIFIED", 3)
    # Non-VERIFIED rows must NOT drag the median or the run_count.
    _insert_harvest(db_conn, cid, 9999, "UNVERIFIED", 4)
    _insert_harvest(db_conn, cid, 1, "FAILED", 5)
    b = compute_baseline(db_conn, cid)
    assert b.run_count == 3
    assert b.median_records == 20.0
    assert b.min_ratio == 0.5  # still < 14 runs


def test_no_history_is_none_median_and_floor(db_conn):
    b = compute_baseline(db_conn, "u-baseline99")
    assert b.median_records is None
    assert b.run_count == 0
    assert b.min_ratio == 0.5
