"""
Unit tests for calculate_job_diff and evaluate_safety_guard (shared/incremental.py)
"""

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.incremental import (
    SAFETY_GUARD_RATIO,
    SCRAPER_GUARD_DEFAULTS,
    SCRAPER_GUARD_MAX_CONSECUTIVE_SKIPS,
    SCRAPER_GUARD_MIN_ABS_DROP,
    SCRAPER_GUARD_MIN_RATIO,
    _guard_env,
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
        """2859/3550 = 0.8053. This is the run that rules OUT a 0.80
        threshold: 0.80 * 3565 = 2852 < 2859, so at 0.80 a real Apple
        truncation slips through untouched."""
        assert evaluate_safety_guard(2859, 3550) == "partial_scrape"

    def test_tightest_real_truncation_3111_of_3798_is_partial(self):
        """THE tightest real truncation in the full prod history — apple,
        2026-05-14, 3111/3798 = 0.8191.

        This is the number that sets the actual working margin: 0.8191 vs
        the 0.85 threshold is **3.1 points**, not the ~4.5 you would infer
        from treating 2859/3550 (0.805) as the worst case. Any proposal to
        lower SCRAPER_GUARD_MIN_RATIO has to clear THIS run, not that one.
        """
        assert evaluate_safety_guard(3111, 3798) == "partial_scrape"

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

    def test_partial_guard_defaults_match_the_prod_calibration(self):
        """0.85 / 15 are the calibrated values.

        Verified twice against prod: on the 3-week window (134,777 runs)
        they trip exactly 7 times, all real Apple truncations; on the full
        455,317-run history they trip 33 times — 27 apple, 6 google, zero
        for the other 128 companies. 0.85 is the knee: the last threshold
        with no non-apple/google trips at all. Retuning either number
        requires re-running that analysis; this assertion is the tripwire.

        Deliberately asserts the DEFAULTS, not the resolved module
        constants. The resolved values honor
        ``SCRAPER_GUARD_MIN_RATIO`` / ``SCRAPER_GUARD_MIN_ABS_DROP`` env
        overrides, and an operator using that escape hatch during an
        incident must not also turn CI red — which asserting the resolved
        value would do.
        """
        assert SCRAPER_GUARD_DEFAULTS["SCRAPER_GUARD_MIN_RATIO"] == 0.85
        assert SCRAPER_GUARD_DEFAULTS["SCRAPER_GUARD_MIN_ABS_DROP"] == 15
        assert SCRAPER_GUARD_DEFAULTS["SCRAPER_GUARD_MAX_CONSECUTIVE_SKIPS"] == 3

    def test_unset_env_resolves_to_the_defaults(self):
        """With no env override in play (the CI/prod-default case) the
        resolved constants must equal the calibrated defaults — otherwise
        the test above would pin a dict nobody reads."""
        import os

        for name in SCRAPER_GUARD_DEFAULTS:
            if name in os.environ:
                pytest.skip(f"{name} is overridden in this environment")
        assert SCRAPER_GUARD_MIN_RATIO == 0.85
        assert SCRAPER_GUARD_MIN_ABS_DROP == 15
        assert SCRAPER_GUARD_MAX_CONSECUTIVE_SKIPS == 3

    # --- exact boundaries (mutation killers) ------------------------------
    #
    # Several docstrings claim the guard's boundaries are "pinned". Before
    # these two tests that was false: no case sat exactly ON either
    # boundary, so both `>=` -> `>` on the drop floor and `<` -> `<=` on
    # the ratio survived the whole suite untouched.

    def test_ratio_boundary_is_strict_less_than(self):
        """Exactly 85% must NOT trip. Kills the `<` -> `<=` mutation.

        85 of 100: the drop is 15 (at the floor), so the ONLY thing keeping
        this from tripping is that the ratio test is a strict ``<``.
        (0.85 * 100 is exactly 85.0 in IEEE-754 — no float fuzz here, so
        the boundary really is exact and worth pinning.)
        """
        assert 0.85 * 100 == 85.0, "float representation changed; revisit"
        assert evaluate_safety_guard(85, 100) is None

    def test_ratio_one_below_the_boundary_does_trip(self):
        """The other side of the same boundary: 84 of 100 trips."""
        assert evaluate_safety_guard(84, 100) == "partial_scrape"

    def test_absolute_drop_floor_is_inclusive(self):
        """A drop of exactly 15 must trip. Kills the `>=` -> `>` mutation.

        35 of 50 breaches the ratio (35 < 42.5) and the drop is exactly
        SCRAPER_GUARD_MIN_ABS_DROP, so the inclusive comparison is the only
        thing deciding the outcome.
        """
        assert (50 - 35) == SCRAPER_GUARD_MIN_ABS_DROP
        assert evaluate_safety_guard(35, 50) == "partial_scrape"

    def test_absolute_drop_one_below_the_floor_does_not_trip(self):
        """36 of 50 breaches the ratio too (36 < 42.5) — only the 14-job
        drop being under the floor saves it. Pins the other side."""
        assert 36 < SCRAPER_GUARD_MIN_RATIO * 50
        assert evaluate_safety_guard(36, 50) is None


class TestBoundedAutoRelease:
    """Tests for the auto-release that stops a PERMANENT board shrink from
    latching a company out forever.

    Without it, a company that genuinely cuts 25% of its reqs trips rule
    (b) on every subsequent run — the stale OPEN rows keep ``active_count``
    high — and is frozen out of ingestion AND lifecycle indefinitely. On
    prod that is a 10.8% risk on the first recovered run after 30 days dead
    and 18.5% after 56, which collides directly with Unit 3: the daily
    stale-scraper alert exists to get a human to repair a dead scraper, and
    the repaired scraper would have had a double-digit chance of instantly
    re-latching and looking identical to still-broken.
    """

    def test_below_the_limit_still_trips(self):
        """N-1 consecutive skips is not yet evidence of a permanent shrink."""
        assert (
            evaluate_safety_guard(150, 200, consecutive_partial_skips=2)
            == "partial_scrape"
        )

    def test_at_the_limit_releases(self):
        """The Nth consecutive identical truncation is taken as a real
        shrink and one run is allowed through to reconcile."""
        assert evaluate_safety_guard(150, 200, consecutive_partial_skips=3) is None

    def test_above_the_limit_still_releases(self):
        """Defensive: a counter that overshoots (e.g. the limit was lowered
        via env between runs) must not flip back to latching."""
        assert evaluate_safety_guard(150, 200, consecutive_partial_skips=99) is None

    def test_empty_scrape_is_never_released(self):
        """Rule (a) has no auto-release, at any skip count. A scrape
        returning under 10% of the board is never a legitimate shrink —
        it is an outage, and freezing is the correct response."""
        assert (
            evaluate_safety_guard(5, 200, consecutive_partial_skips=999)
            == "empty_scrape"
        )

    def test_release_does_not_apply_to_a_healthy_run(self):
        """A healthy run returns None regardless — the release path must
        not change the answer for runs that were never going to trip."""
        assert evaluate_safety_guard(199, 200, consecutive_partial_skips=99) is None

    def test_default_skip_count_is_zero(self):
        """Callers that don't plumb history get the plain stateless rules,
        so a caller which forgets the parameter fails SAFE (latched), never
        open (released)."""
        assert evaluate_safety_guard(150, 200) == "partial_scrape"


class TestGuardEnvOverrides:
    """Tests for ``_guard_env`` — the operator escape hatch.

    The one moment someone reaches for these env vars is a live incident,
    which is exactly when a crash or a footgun is least affordable.
    """

    def test_unparseable_value_falls_back_instead_of_raising(self, caplog):
        """``SCRAPER_GUARD_MIN_RATIO=oops`` must NOT raise.

        A bare ``float()`` here raises ValueError at module import, and all
        six ATS leaf tasks import this module — so FastAPI would fail to
        start and Railway would crash-loop the entire API over a typo in a
        scraper tuning knob.
        """
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"SCRAPER_GUARD_MIN_RATIO": "oops"}):
            with caplog.at_level("ERROR"):
                value = _guard_env("SCRAPER_GUARD_MIN_RATIO", 0.0, 1.0, cast=float)

        assert value == 0.85
        assert "not a valid float" in caplog.text

    def test_percentage_typo_is_clamped_not_obeyed(self, caplog):
        """``SCRAPER_GUARD_MIN_RATIO=85`` (percent, not ratio) is an easy
        3am mistake. Obeyed literally it makes ``jobs_seen < 85 * active``
        true for every company on every run — freezing all 129 scrapers at
        once. Clamped to 1.0 it is merely very strict."""
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"SCRAPER_GUARD_MIN_RATIO": "85"}):
            with caplog.at_level("ERROR"):
                value = _guard_env("SCRAPER_GUARD_MIN_RATIO", 0.0, 1.0, cast=float)

        assert value == 1.0
        assert "outside the sane range" in caplog.text

    def test_negative_abs_drop_is_clamped_to_one(self, caplog):
        """A drop floor of 0 or below would make rule (b) fire on any run
        where jobs_seen <= active, i.e. constantly."""
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"SCRAPER_GUARD_MIN_ABS_DROP": "-5"}):
            with caplog.at_level("ERROR"):
                value = _guard_env(
                    "SCRAPER_GUARD_MIN_ABS_DROP", 1, 1_000_000, cast=int
                )

        assert value == 1

    def test_valid_override_is_honored(self):
        """The hatch must actually work when used correctly."""
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"SCRAPER_GUARD_MIN_RATIO": "0.5"}):
            assert _guard_env("SCRAPER_GUARD_MIN_RATIO", 0.0, 1.0, cast=float) == 0.5
