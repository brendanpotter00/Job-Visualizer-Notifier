"""Per-company harvest baseline for custom companies (E7 Phase 2, §4.5).

Derived ON THE FLY from ``company_harvests`` — NO new table, NO stored column, so
there is no stale-value bug and ``company_harvests`` stays the single source of
truth. Two things come out of it:

* ``median_records`` — the trailing-window median of ``records_harvested`` over
  VERIFIED harvests. Feeds the delta band (gate check 12).
* ``recent_records`` — the trailing-window record counts over **every** harvest,
  newest first, whatever its verdict. Two checks need the unfiltered series and
  cannot use the VERIFIED-only median: the settled-step-change release (a board
  that has held one new number for several runs in a row has really shrunk) and
  the implicit-page-limit tell (a count pinned to a round page size run after
  run). A board that has never VERIFIED — which is every discovered board today
  — has an EMPTY VERIFIED window, so a check that only read the median would be
  blind on exactly the boards this exists for.
* ``min_ratio`` — the PER-COMPANY safety-guard ratio that overrides the global
  ``SCRAPER_GUARD_MIN_RATIO`` (0.85, tuned for the 30-min public cron cadence)
  for custom companies only. Daily companies need a learned baseline, not the
  fleet default.

  PROD-VERIFY: the ``p01`` calibration is meaningless until a company has ~14
  daily runs (2-3 weeks of prod data) and CANNOT be validated locally — locally
  ``min_ratio`` is always the 0.5 floor. The tests here prove the *arithmetic*
  (0.5 until 14 runs; the clamp/floor math on a synthetic 14-run history), not
  the tuning quality.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from psycopg2.extensions import connection as Connection

# The 1st-percentile day-over-day retention is only meaningful once a company has
# this many VERIFIED daily runs; below it, use the conservative floor.
_CALIBRATION_MIN_RUNS = 14
# Guard-ratio floor/ceiling. The floor (0.5) is what every custom company runs at
# until it is calibrated; the ceiling (0.85) is the global default — a learned
# ratio never exceeds it (a company that never truncates keeps the fleet default,
# it does not get a *looser* guard than the public crons).
_MIN_RATIO_FLOOR = 0.5
_MIN_RATIO_CEIL = 0.85
# Slack subtracted from the observed p01 so normal daily jitter does not trip the
# guard (mirrors the §4.5 formula ``min(0.85, p01 - 0.05)``).
_P01_SLACK = 0.05


@dataclass(frozen=True)
class Baseline:
    """Trailing-window harvest stats for one custom company.

    ``median_records`` is None until at least one VERIFIED harvest exists.
    ``run_count`` is how many VERIFIED harvests the window saw (capped at the
    window). ``min_ratio`` is the per-company safety-guard ratio (§4.5).
    ``recent_records`` is the newest-first record counts of the last
    ``recent_window`` harvests of ANY verdict (see the module docstring); it
    defaults to empty so every existing positional construction keeps working.
    """

    median_records: float | None
    run_count: int
    min_ratio: float
    recent_records: tuple[int, ...] = ()


def _median(values: list[int]) -> float:
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return float(s[mid])
    return (s[mid - 1] + s[mid]) / 2.0


def _percentile_nearest_rank(values: list[float], q: float) -> float:
    """Nearest-rank percentile. Deterministic and interpolation-free so the
    synthetic-history tests can assert exact values; for the small samples this
    sees (≤13 ratios) the 1st percentile is effectively the minimum."""
    s = sorted(values)
    rank = max(1, math.ceil(q * len(s)))
    return s[rank - 1]


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def compute_baseline(
    conn: Connection, company_id: str, *, window: int = 14, recent_window: int = 14,
) -> Baseline:
    """Read the last ``window`` VERIFIED harvests and derive the baseline.

    ``min_ratio`` per §4.5:

        run_count < 14   -> 0.5 (conservative until calibrated)
        run_count >= 14  -> clamp(min(0.85, p01 - 0.05), 0.5, 0.85)

    where ``p01`` is the 1st percentile of the consecutive day-over-day retention
    ratios ``r_i = min(1.0, records[i] / records[i-1])`` over the VERIFIED
    harvests in chronological order.

    ``recent_window`` sizes the SECOND, unfiltered series (``recent_records``) —
    the last N harvests whatever their verdict. It is read in the same round trip
    but as its own query, because the two windows answer different questions: the
    median must never see an unproven run, and the step-change / page-limit tells
    must see every run.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT records_harvested
            FROM company_harvests
            WHERE company_id = %s AND verdict = 'VERIFIED'
            ORDER BY started_at DESC
            LIMIT %s
            """,
            (company_id, window),
        )
        # Rows come back newest-first; keep that for run_count/median and reverse
        # for the chronological ratio walk below.
        newest_first = [int(r["records_harvested"]) for r in cursor.fetchall()]
        # The unfiltered series. Deliberately NOT verdict-filtered: an UNVERIFIED
        # run is still an observation of what the board returned, and both
        # consumers (settled step change, page-limit pinning) are asking exactly
        # "what has this board been returning lately?", not "what have we proven".
        cursor.execute(
            """
            SELECT records_harvested
            FROM company_harvests
            WHERE company_id = %s AND verdict <> 'FAILED'
            ORDER BY started_at DESC
            LIMIT %s
            """,
            (company_id, recent_window),
        )
        recent_records = tuple(int(r["records_harvested"]) for r in cursor.fetchall())
    finally:
        # SELECT-only — never leave the caller's connection idle-in-transaction.
        conn.rollback()

    run_count = len(newest_first)
    median_records = _median(newest_first) if newest_first else None

    if run_count < _CALIBRATION_MIN_RUNS:
        return Baseline(
            median_records=median_records, run_count=run_count,
            min_ratio=_MIN_RATIO_FLOOR, recent_records=recent_records,
        )

    chronological = list(reversed(newest_first))
    ratios: list[float] = []
    for i in range(1, len(chronological)):
        prev = chronological[i - 1]
        curr = chronological[i]
        if prev <= 0:
            continue  # cannot form a ratio against a zero-record prior
        ratios.append(min(1.0, curr / prev))

    if not ratios:
        min_ratio = _MIN_RATIO_FLOOR
    else:
        p01 = _percentile_nearest_rank(ratios, 0.01)
        min_ratio = _clamp(
            min(_MIN_RATIO_CEIL, p01 - _P01_SLACK), _MIN_RATIO_FLOOR, _MIN_RATIO_CEIL,
        )

    return Baseline(
        median_records=median_records, run_count=run_count, min_ratio=min_ratio,
        recent_records=recent_records,
    )
