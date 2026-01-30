"""
Unit tests for TikTok Jobs parser functions (tiktok_jobs_scraper/parser.py)
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tiktok_jobs_scraper.parser import (
    extract_job_id_from_url,
    parse_salary_range,
    parse_qualifications,
    get_apply_url,
    get_job_detail_url,
    _transform_job_data,
)


class TestExtractJobIdFromUrl:
    """Tests for extract_job_id_from_url function"""

    def test_extract_job_id_full_url(self):
        """Extracts job ID from full URL"""
        url = "https://lifeattiktok.com/search/7579201004205164805"
        assert extract_job_id_from_url(url) == "7579201004205164805"

    def test_extract_job_id_relative_url(self):
        """Extracts job ID from relative URL"""
        url = "/search/7579201004205164805"
        assert extract_job_id_from_url(url) == "7579201004205164805"

    def test_extract_job_id_invalid_url(self):
        """Returns None for invalid URL"""
        assert extract_job_id_from_url("https://lifeattiktok.com/search") is None
        assert extract_job_id_from_url("https://lifeattiktok.com/") is None
        assert extract_job_id_from_url("") is None

    def test_extract_job_id_non_numeric(self):
        """Returns None for non-numeric job ID"""
        url = "/search/not-a-number"
        assert extract_job_id_from_url(url) is None

    def test_extract_job_id_with_query_params(self):
        """Extracts job ID even with query params"""
        url = "/search/7579201004205164805?tab=details"
        assert extract_job_id_from_url(url) == "7579201004205164805"


class TestParseSalaryRange:
    """Tests for parse_salary_range function"""

    def test_parse_salary_range_standard(self):
        """Parses standard salary range"""
        text = "The salary range is $118657 - $259200 annually."
        assert parse_salary_range(text) == "$118657 - $259200"

    def test_parse_salary_range_with_commas(self):
        """Parses salary with comma separators"""
        text = "Base pay: $118,657 - $259,200 per year"
        assert parse_salary_range(text) == "$118,657 - $259,200"

    def test_parse_salary_range_no_salary(self):
        """Returns None when no salary found"""
        text = "Great opportunity to join our team!"
        assert parse_salary_range(text) is None

    def test_parse_salary_range_empty(self):
        """Returns None for empty/None input"""
        assert parse_salary_range("") is None
        assert parse_salary_range(None) is None


class TestParseQualifications:
    """Tests for parse_qualifications function"""

    def test_parse_qualifications_newline_separated(self):
        """Parses newline-separated qualifications"""
        text = "Bachelor's degree required\n5+ years of experience\nStrong Python skills"
        result = parse_qualifications(text)

        assert len(result) == 3
        assert "Bachelor's degree" in result[0]
        assert "5+ years" in result[1]
        assert "Python skills" in result[2]

    def test_parse_qualifications_bullet_separated(self):
        """Parses bullet-separated qualifications"""
        text = "• Bachelor's degree required• 5+ years of experience• Strong Python skills"
        result = parse_qualifications(text)

        assert len(result) >= 2

    def test_parse_qualifications_dash_separated(self):
        """Parses dash-separated qualifications"""
        text = "- Bachelor's degree required- 5+ years of experience"
        result = parse_qualifications(text)

        assert len(result) >= 1

    def test_parse_qualifications_empty(self):
        """Returns empty list for empty input"""
        assert parse_qualifications("") == []
        assert parse_qualifications(None) == []

    def test_parse_qualifications_filters_short(self):
        """Filters out short entries"""
        text = "Short\nThis is a qualification that is long enough to be included"
        result = parse_qualifications(text)

        # Only the long one should be included
        assert len(result) == 1


class TestGetApplyUrl:
    """Tests for get_apply_url function"""

    def test_get_apply_url(self):
        """Builds correct apply URL"""
        job_id = "7579201004205164805"
        expected = "https://careers.tiktok.com/resume/7579201004205164805/apply"
        assert get_apply_url(job_id) == expected

    def test_get_apply_url_various_ids(self):
        """Works with different job IDs"""
        test_cases = [
            ("1234567890", "https://careers.tiktok.com/resume/1234567890/apply"),
            ("9999999999999999999", "https://careers.tiktok.com/resume/9999999999999999999/apply"),
        ]
        for job_id, expected in test_cases:
            assert get_apply_url(job_id) == expected


class TestGetJobDetailUrl:
    """Tests for get_job_detail_url function"""

    def test_get_job_detail_url(self):
        """Builds correct job detail URL"""
        job_id = "7579201004205164805"
        expected = "https://lifeattiktok.com/search/7579201004205164805"
        assert get_job_detail_url(job_id) == expected


class TestTransformJobData:
    """Tests for _transform_job_data function"""

    def test_transform_job_data_complete(self):
        """Transforms complete job data"""
        raw_data = {
            "id": "7579201004205164805",
            "title": "Software Engineer - USDS",
            "location": "San Jose",
            "category": "Technology",
            "employment_type": "Regular",
            "href": "/search/7579201004205164805",
        }

        result = _transform_job_data(raw_data)

        assert result["id"] == "7579201004205164805"
        assert result["title"] == "Software Engineer - USDS"
        assert result["location"] == "San Jose"
        assert result["category"] == "Technology"
        assert result["employment_type"] == "Regular"
        assert result["company"] == "tiktok"
        assert "lifeattiktok.com" in result["job_url"]

    def test_transform_job_data_minimal(self):
        """Transforms minimal job data"""
        raw_data = {
            "id": "12345",
            "title": "Engineer",
            "href": "/search/12345",
        }

        result = _transform_job_data(raw_data)

        assert result["id"] == "12345"
        assert result["title"] == "Engineer"
        assert result["location"] is None

    def test_transform_job_data_no_id(self):
        """Returns None when no ID"""
        raw_data = {
            "title": "Engineer",
            "href": "/search/12345",
        }

        result = _transform_job_data(raw_data)
        assert result is None

    def test_transform_job_data_full_url(self):
        """Handles full URL in href"""
        raw_data = {
            "id": "12345",
            "title": "Engineer",
            "href": "https://lifeattiktok.com/search/12345",
        }

        result = _transform_job_data(raw_data)

        assert result["job_url"] == "https://lifeattiktok.com/search/12345"
