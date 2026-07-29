"""
Unit tests for calculate_job_diff and evaluate_safety_guard (shared/incremental.py)
"""

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.incremental import (
    SAFETY_GUARD_RATIO,
    SCRAPER_GUARD_MIN_ABS_DROP,
    SCRAPER_GUARD_MIN_RATIO,
    calculate_job_diff,
    evaluate_safety_guard,
)


class TestCalculateJobDiff:
    """Tests for calculate_job_diff function"""

    def test_calculate_job_diff_all_new(self):
        """All current IDs are new (none in database)"""
        current_ids = {"job-001", "job-002", "job-003"}
        active_known_ids = set()  # Empty database

        new_jobs, still_active, missing_jobs = calculate_job_diff(current_ids, active_known_ids)

        assert new_jobs == {"job-001", "job-002", "job-003"}
        assert still_active == set()
        assert missing_jobs == set()

    def test_calculate_job_diff_all_existing(self):
        """All current IDs exist in database"""
        current_ids = {"job-001", "job-002", "job-003"}
        active_known_ids = {"job-001", "job-002", "job-003"}

        new_jobs, still_active, missing_jobs = calculate_job_diff(current_ids, active_known_ids)

        assert new_jobs == set()
        assert still_active == {"job-001", "job-002", "job-003"}
        assert missing_jobs == set()

    def test_calculate_job_diff_all_missing(self):
        """Database IDs not in current scrape"""
        current_ids = set()  # Empty scrape results
        active_known_ids = {"job-001", "job-002", "job-003"}

        new_jobs, still_active, missing_jobs = calculate_job_diff(current_ids, active_known_ids)

        assert new_jobs == set()
        assert still_active == set()
        assert missing_jobs == {"job-001", "job-002", "job-003"}

    def test_calculate_job_diff_mixed(self):
        """Combination of new, active, and missing jobs"""
        current_ids = {"job-002", "job-003", "job-004", "job-005"}
        active_known_ids = {"job-001", "job-002", "job-003"}

        new_jobs, still_active, missing_jobs = calculate_job_diff(current_ids, active_known_ids)

        # job-004, job-005 are new (in current but not in DB)
        assert new_jobs == {"job-004", "job-005"}

        # job-002, job-003 are still active (in both)
        assert still_active == {"job-002", "job-003"}

        # job-001 is missing (in DB but not in current)
        assert missing_jobs == {"job-001"}

    def test_calculate_job_diff_empty_current(self):
        """Empty current scrape returns all DB jobs as missing"""
        current_ids = set()
        active_known_ids = {"job-001", "job-002"}

        new_jobs, still_active, missing_jobs = calculate_job_diff(current_ids, active_known_ids)

        assert new_jobs == set()
        assert still_active == set()
        assert missing_jobs == {"job-001", "job-002"}

    def test_calculate_job_diff_empty_known(self):
        """Empty database returns all current jobs as new"""
        current_ids = {"job-001", "job-002"}
        active_known_ids = set()

        new_jobs, still_active, missing_jobs = calculate_job_diff(current_ids, active_known_ids)

        assert new_jobs == {"job-001", "job-002"}
        assert still_active == set()
        assert missing_jobs == set()

    def test_calculate_job_diff_both_empty(self):
        """Both empty returns all empty sets"""
        current_ids = set()
        active_known_ids = set()

        new_jobs, still_active, missing_jobs = calculate_job_diff(current_ids, active_known_ids)

        assert new_jobs == set()
        assert still_active == set()
        assert missing_jobs == set()

    def test_calculate_job_diff_no_overlap(self):
        """Completely different sets (no overlap)"""
        current_ids = {"job-100", "job-101", "job-102"}
        active_known_ids = {"job-001", "job-002", "job-003"}

        new_jobs, still_active, missing_jobs = calculate_job_diff(current_ids, active_known_ids)

        assert new_jobs == {"job-100", "job-101", "job-102"}
        assert still_active == set()
        assert missing_jobs == {"job-001", "job-002", "job-003"}

    def test_calculate_job_diff_single_job(self):
        """Single job scenarios"""
        # Single new job
        new_jobs, still_active, missing = calculate_job_diff({"job-001"}, set())
        assert new_jobs == {"job-001"}
        assert still_active == set()
        assert missing == set()

        # Single existing job
        new_jobs, still_active, missing = calculate_job_diff({"job-001"}, {"job-001"})
        assert new_jobs == set()
        assert still_active == {"job-001"}
        assert missing == set()

        # Single missing job
        new_jobs, still_active, missing = calculate_job_diff(set(), {"job-001"})
        assert new_jobs == set()
        assert still_active == set()
        assert missing == {"job-001"}

    def test_calculate_job_diff_large_sets(self):
        """Performance check with larger sets"""
        # Create sets with 1000 jobs each
        current_ids = {f"job-{i:04d}" for i in range(500, 1500)}
        active_known_ids = {f"job-{i:04d}" for i in range(0, 1000)}

        new_jobs, still_active, missing_jobs = calculate_job_diff(current_ids, active_known_ids)

        # Jobs 0-499 are missing
        assert len(missing_jobs) == 500
        # Jobs 500-999 are still active
        assert len(still_active) == 500
        # Jobs 1000-1499 are new
        assert len(new_jobs) == 500


class TestEvaluateSafetyGuard:
    """Tests for evaluate_safety_guard — the single source of truth for the
    scraper safety guard, shared by ``run_incremental_scrape`` and all six
    ``src/backend/api/tasks/fetch_*_company.py`` leaf tasks.

    Every number below is a REAL production observation from the audit of
    134,777 successful runs over 129 companies (2026-07-07 -> 2026-07-28),
    not a made-up boundary. The point of this class is that a future tweak
    to the ratio or the absolute-drop floor immediately shows which live
    company it would have started (or stopped) protecting.
    """

    # --- the seven real Apple truncations (base board ~3,550 OPEN) --------

    def test_apple_truncation_2585_of_3550_is_partial(self):
        """The 73%-of-normal Apple run. Under the OLD 0.1-only guard this
        sailed straight through into the destructive close phase."""
        assert evaluate_safety_guard(2585, 3550) == "partial_scrape"

    def test_apple_truncation_2859_of_3550_is_partial(self):
        """Hardest real case: ~80.5% of the board. This is the run that
        forces SCRAPER_GUARD_MIN_RATIO to be 0.85 rather than 0.80 — at
        0.80 this truncation slips through."""
        assert evaluate_safety_guard(2859, 3550) == "partial_scrape"

    # --- normal variance that must NOT trip -------------------------------

    @pytest.mark.parametrize(
        "jobs_seen,active_count,why",
        [
            (3490, 3550, "Apple, ordinary day-to-day churn (98%)"),
            (3617, 3550, "Apple, board grew — never a truncation"),
            (769, 798, "Google's real 96% run; the plan's named non-trip case"),
            (300, 336, "Microsoft, 89% — above the ratio, no trip"),
        ],
    )
    def test_normal_variance_does_not_trip(self, jobs_seen, active_count, why):
        assert evaluate_safety_guard(jobs_seen, active_count) is None, why

    def test_microsoft_336_to_280_does_trip_partial(self):
        """DELIBERATE DEVIATION FROM THE PLAN — documented, not an oversight.

        The plan listed ``(280, 336)`` ("Microsoft's genuine 336->280 hiring
        drift") among the cases expected to return ``None``. That is
        arithmetically impossible alongside catching the 2859/3550 Apple
        truncation:

            280 / 336 = 0.8333  ->  below SCRAPER_GUARD_MIN_RATIO (0.85)
            336 - 280 = 56      ->  at/above SCRAPER_GUARD_MIN_ABS_DROP (15)

        so rule (b) fires. Lowering the ratio to 0.80 to make it pass would
        let 2859/3550 (0.805) through — the exact failure this change
        exists to prevent. See ``test_apple_truncation_2859_of_3550``.

        The plan's own "no auto-release" trade-off note describes this case
        exactly ("a genuine >15% one-shot shrink on a >=100-job board locks
        that company out"), so tripping here is the designed behavior; only
        the plan's expected value was wrong. Note the prod figure was drift
        ACROSS DAYS — each individual run compares against the then-current
        active count, so no single production run ever presented the helper
        with (280, 336).
        """
        assert evaluate_safety_guard(280, 336) == "partial_scrape"

    # --- small boards: the absolute-drop floor is what saves them ---------

    def test_small_board_ratio_breach_without_absolute_drop_is_ignored(self):
        """22 of 30 is only 73% — a ratio-only guard would fire constantly on
        small boards. The 15-job absolute floor (drop is 8) suppresses it."""
        assert evaluate_safety_guard(22, 30) is None

    def test_small_board_near_total_failure_is_empty_scrape(self):
        """Rule (a) still protects small boards from a true outage:
        2 < 0.1 * 30 = 3."""
        assert evaluate_safety_guard(2, 30) == "empty_scrape"

    # --- cold start --------------------------------------------------------

    @pytest.mark.parametrize("jobs_seen", [0, 5])
    def test_cold_start_never_trips(self, jobs_seen):
        """Nothing in the DB means nothing to protect and nothing to close.
        Must hold for an empty scrape AND a first successful scrape."""
        assert evaluate_safety_guard(jobs_seen, 0) is None

    # --- reason codes are distinct ----------------------------------------

    def test_total_outage_reports_empty_not_partial(self):
        """A 0-job scrape must be reported as ``empty_scrape`` even though it
        also satisfies rule (b) — operators triage a dead scraper very
        differently from a truncated one."""
        assert evaluate_safety_guard(0, 3550) == "empty_scrape"

    # --- constants are pinned ---------------------------------------------

    def test_legacy_safety_guard_ratio_is_still_one_tenth(self):
        """SAFETY_GUARD_RATIO stays 0.1. It is no longer the primary gate,
        but it is what distinguishes ``empty_scrape`` from
        ``partial_scrape``; silently widening it would collapse the two
        reason codes into one and destroy the triage signal.

        Pinned as a literal on purpose — asserting it against itself would
        pass for any value."""
        assert SAFETY_GUARD_RATIO == 0.1

    def test_partial_guard_constants_match_the_prod_calibration(self):
        """0.85 / 15 are the calibrated values: on 134,777 prod runs they
        trip exactly 7 times, all of them real Apple truncations, with zero
        false positives. Retuning either one requires re-running that
        analysis — this assertion is the tripwire."""
        assert SCRAPER_GUARD_MIN_RATIO == 0.85
        assert SCRAPER_GUARD_MIN_ABS_DROP == 15
