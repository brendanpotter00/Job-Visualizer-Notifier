"""
Unit tests for utility functions (google_jobs_scraper/utils.py)
"""

import pytest
import re
from datetime import datetime

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from google_jobs_scraper.utils import (
    should_include_job,
    extract_job_id_from_url,
    get_iso_timestamp
)


class TestShouldIncludeJob:
    """Tests for should_include_job function"""

    @pytest.fixture
    def include_keywords(self):
        return ["software", "engineer", "developer", "data"]

    @pytest.fixture
    def exclude_keywords(self):
        return ["recruiter", "sales", "manager", "intern"]

    def test_should_include_job_matches_include(self, include_keywords, exclude_keywords):
        """Title with include keyword returns True"""
        assert should_include_job("Software Engineer", include_keywords, exclude_keywords) is True
        assert should_include_job("Data Scientist", include_keywords, exclude_keywords) is True
        assert should_include_job("Senior Developer", include_keywords, exclude_keywords) is True

    def test_should_include_job_matches_exclude(self, include_keywords, exclude_keywords):
        """Title with exclude keyword returns False"""
        assert should_include_job("Technical Recruiter", include_keywords, exclude_keywords) is False
        assert should_include_job("Sales Engineer", include_keywords, exclude_keywords) is False
        assert should_include_job("Engineering Manager", include_keywords, exclude_keywords) is False

    def test_should_include_job_exclude_takes_priority(self, include_keywords, exclude_keywords):
        """Exclude wins over include when both match"""
        # "Software Recruiter" has both "software" (include) and "recruiter" (exclude)
        # Exclude should win
        assert should_include_job("Software Recruiter", include_keywords, exclude_keywords) is False
        assert should_include_job("Sales Software Developer", include_keywords, exclude_keywords) is False

    def test_should_include_job_no_match(self, include_keywords, exclude_keywords):
        """No matching keywords returns False"""
        assert should_include_job("Product Designer", include_keywords, exclude_keywords) is False
        assert should_include_job("Marketing Analyst", include_keywords, exclude_keywords) is False

    def test_should_include_job_case_insensitive(self, include_keywords, exclude_keywords):
        """Keywords match case-insensitively"""
        assert should_include_job("SOFTWARE ENGINEER", include_keywords, exclude_keywords) is True
        assert should_include_job("software engineer", include_keywords, exclude_keywords) is True
        assert should_include_job("SoFtWaRe EnGiNeEr", include_keywords, exclude_keywords) is True

        assert should_include_job("RECRUITER", include_keywords, exclude_keywords) is False
        assert should_include_job("INTERN", include_keywords, exclude_keywords) is False

    def test_should_include_job_empty_title(self, include_keywords, exclude_keywords):
        """Empty title returns False"""
        assert should_include_job("", include_keywords, exclude_keywords) is False

    def test_should_include_job_partial_match(self, include_keywords, exclude_keywords):
        """Partial keyword matches work (substring matching)"""
        # "software" is in "software-engineer"
        assert should_include_job("software-engineer-iii", include_keywords, exclude_keywords) is True
        # "developer" is in "developers"
        assert should_include_job("Android Developers Team Lead", include_keywords, exclude_keywords) is True


class TestExtractJobIdFromUrl:
    """Tests for extract_job_id_from_url function"""

    def test_extract_job_id_from_url_valid(self):
        """Extracts ID before first hyphen"""
        url = "https://www.google.com/about/careers/applications/jobs/results/114423471240291014-software-engineer-iii-cloud"
        assert extract_job_id_from_url(url) == "114423471240291014"

    def test_extract_job_id_from_url_different_ids(self):
        """Works with different job IDs"""
        test_cases = [
            ("/jobs/results/12345-test-job", "12345"),
            ("/jobs/results/999-single-word", "999"),
            ("/jobs/results/1234567890123456789-very-long-job-title", "1234567890123456789"),
        ]
        for url, expected_id in test_cases:
            assert extract_job_id_from_url(url) == expected_id

    def test_extract_job_id_from_url_invalid(self):
        """Returns None for malformed URL"""
        # URL with /jobs/results/ but malformed
        assert extract_job_id_from_url("") is None

    def test_extract_job_id_from_url_no_match(self):
        """Returns None if no /jobs/results/ in URL"""
        assert extract_job_id_from_url("https://www.google.com/about/careers") is None
        assert extract_job_id_from_url("https://example.com/job/12345") is None
        assert extract_job_id_from_url("not-a-url") is None

    def test_extract_job_id_from_url_relative(self):
        """Works with relative URLs (requires leading slash)"""
        assert extract_job_id_from_url("/jobs/results/12345-test") == "12345"
        assert extract_job_id_from_url("/jobs/results/67890-another-job") == "67890"


class TestGetIsoTimestamp:
    """Tests for get_iso_timestamp function"""

    def test_get_iso_timestamp_format(self):
        """Returns valid ISO 8601 with Z suffix"""
        timestamp = get_iso_timestamp()

        # Should end with Z
        assert timestamp.endswith("Z")

        # Should be parseable as ISO format (without the Z)
        iso_part = timestamp.rstrip("Z")
        try:
            datetime.fromisoformat(iso_part)
            parsed = True
        except ValueError:
            parsed = False

        assert parsed is True

    def test_get_iso_timestamp_length(self):
        """Timestamp has expected length"""
        timestamp = get_iso_timestamp()

        # ISO format: YYYY-MM-DDTHH:MM:SS.ffffffZ or YYYY-MM-DDTHH:MM:SSZ
        # Minimum: 20 chars (2024-01-15T10:30:00Z)
        # Maximum: 27 chars (2024-01-15T10:30:00.123456Z)
        assert 20 <= len(timestamp) <= 27

    def test_get_iso_timestamp_contains_t_separator(self):
        """Timestamp contains T separator between date and time"""
        timestamp = get_iso_timestamp()
        assert "T" in timestamp

    def test_get_iso_timestamp_is_recent(self):
        """Timestamp is close to current time (within 1 second)"""
        before = datetime.utcnow()
        timestamp = get_iso_timestamp()
        after = datetime.utcnow()

        # Parse the timestamp
        iso_part = timestamp.rstrip("Z")
        ts_datetime = datetime.fromisoformat(iso_part)

        # Should be between before and after
        assert before <= ts_datetime <= after
