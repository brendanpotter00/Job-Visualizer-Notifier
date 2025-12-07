"""
Unit tests for calculate_job_diff function (shared/incremental.py)
"""

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.incremental import calculate_job_diff


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
