"""
Unit tests for Apple Jobs API client functions (apple_jobs_scraper/api_client.py)
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from apple_jobs_scraper.api_client import (
    parse_qualifications,
    extract_salary,
    format_location,
    get_apply_url,
    fetch_job_details,
    JobDetailsFetchError,
)


class TestParseQualifications:
    """Tests for parse_qualifications function"""

    def test_parse_qualifications_newline_separated(self):
        """Parses newline-separated qualifications"""
        text = "Bachelor's degree in Computer Science\n5+ years experience\nStrong Python skills"
        result = parse_qualifications(text)

        assert len(result) == 3
        assert result[0] == "Bachelor's degree in Computer Science"
        assert result[1] == "5+ years experience"
        assert result[2] == "Strong Python skills"

    def test_parse_qualifications_with_empty_lines(self):
        """Filters out empty lines"""
        text = "First qualification\n\nSecond qualification\n\n\nThird qualification"
        result = parse_qualifications(text)

        assert len(result) == 3
        assert result[0] == "First qualification"
        assert result[1] == "Second qualification"
        assert result[2] == "Third qualification"

    def test_parse_qualifications_empty_string(self):
        """Returns empty list for empty string"""
        assert parse_qualifications("") == []
        assert parse_qualifications(None) == []

    def test_parse_qualifications_single_line(self):
        """Works with single line (no newlines)"""
        text = "Bachelor's degree required"
        result = parse_qualifications(text)

        assert len(result) == 1
        assert result[0] == "Bachelor's degree required"

    def test_parse_qualifications_strips_whitespace(self):
        """Strips leading/trailing whitespace from each line"""
        text = "  Qualification 1  \n  Qualification 2  "
        result = parse_qualifications(text)

        assert result[0] == "Qualification 1"
        assert result[1] == "Qualification 2"


class TestExtractSalary:
    """Tests for extract_salary function"""

    def test_extract_salary_from_posting_data(self):
        """Extracts salary from postingPostLocationData"""
        data = {
            "postingPostLocationData": {
                "Base Pay Range": "$141,800 - $258,600"
            }
        }
        assert extract_salary(data) == "$141,800 - $258,600"

    def test_extract_salary_from_top_level(self):
        """Extracts salary from top-level field"""
        data = {
            "salary": "$150,000 - $200,000"
        }
        assert extract_salary(data) == "$150,000 - $200,000"

    def test_extract_salary_from_description(self):
        """Extracts salary from description text"""
        data = {
            "description": "The base pay range for this role is $120,000-$180,000 annually."
        }
        result = extract_salary(data)
        assert result is not None
        assert "$120,000" in result

    def test_extract_salary_no_salary(self):
        """Returns None when no salary found"""
        data = {
            "description": "Great opportunity to join our team!"
        }
        assert extract_salary(data) is None

    def test_extract_salary_empty_data(self):
        """Returns None for empty data"""
        assert extract_salary({}) is None


class TestFormatLocation:
    """Tests for format_location function"""

    def test_format_location_full(self):
        """Formats location with all components"""
        locations = [{
            "city": "Cupertino",
            "stateProvince": "California",
            "countryName": "United States"
        }]
        assert format_location(locations) == "Cupertino, California, United States"

    def test_format_location_partial(self):
        """Handles missing components"""
        locations = [{
            "city": "Remote",
            "countryName": "United States"
        }]
        assert format_location(locations) == "Remote, United States"

    def test_format_location_city_only(self):
        """Works with city only"""
        locations = [{"city": "Cupertino"}]
        assert format_location(locations) == "Cupertino"

    def test_format_location_empty(self):
        """Returns empty string for empty locations"""
        assert format_location([]) == ""
        assert format_location(None) == ""

    def test_format_location_uses_first(self):
        """Uses first location when multiple provided"""
        locations = [
            {"city": "Cupertino", "stateProvince": "California", "countryName": "United States"},
            {"city": "Seattle", "stateProvince": "Washington", "countryName": "United States"},
        ]
        result = format_location(locations)
        assert "Cupertino" in result
        assert "Seattle" not in result


class TestGetApplyUrl:
    """Tests for get_apply_url function"""

    def test_get_apply_url(self):
        """Builds correct apply URL"""
        job_id = "200640732-0836"
        expected = "https://jobs.apple.com/app/en-us/apply/200640732-0836"
        assert get_apply_url(job_id) == expected

    def test_get_apply_url_various_ids(self):
        """Works with different job IDs"""
        test_cases = [
            ("114438158", "https://jobs.apple.com/app/en-us/apply/114438158"),
            ("200630959-0836", "https://jobs.apple.com/app/en-us/apply/200630959-0836"),
        ]
        for job_id, expected in test_cases:
            assert get_apply_url(job_id) == expected


class TestFetchJobDetails:
    """Tests for fetch_job_details async function"""

    @pytest.fixture
    def mock_page(self):
        """Create mock Playwright page object"""
        return MagicMock()

    @pytest.fixture
    def sample_api_response(self):
        """Sample successful API response"""
        return {
            "res": {
                "postingTitle": "Software Engineer",
                "jobNumber": "200640732-0836",
                "positionId": "12345",
                "description": "Work on cutting-edge systems",
                "jobSummary": "Join our team",
                "responsibilities": "Design and implement solutions",
                "minimumQualifications": "BS in CS\n3+ years experience",
                "preferredQualifications": "MS preferred",
                "teamNames": ["Engineering"],
                "locations": [
                    {"city": "Cupertino", "stateProvince": "California", "countryName": "United States"}
                ],
                "homeOffice": False,
                "postDateInGMT": "2024-12-15T00:00:00Z",
                "jobType": "Full-Time",
                "employmentType": "Individual Contributor",
            }
        }

    @pytest.mark.asyncio
    async def test_fetch_job_details_success(self, mock_page, sample_api_response):
        """Successfully fetches and parses job details"""
        mock_page.evaluate = AsyncMock(return_value=sample_api_response)

        result = await fetch_job_details(mock_page, "200640732-0836")

        assert result["title"] == "Software Engineer"
        assert result["job_id"] == "200640732-0836"
        assert result["location"] == "Cupertino, California, United States"
        assert len(result["minimum_qualifications"]) == 2
        mock_page.evaluate.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_job_details_unexpected_format(self, mock_page):
        """Returns empty dict for unexpected response format"""
        mock_page.evaluate = AsyncMock(return_value={"unexpected": "format"})

        result = await fetch_job_details(mock_page, "200640732-0836")

        assert result == {}

    @pytest.mark.asyncio
    async def test_fetch_job_details_empty_response(self, mock_page):
        """Returns empty dict for empty response"""
        mock_page.evaluate = AsyncMock(return_value=None)

        result = await fetch_job_details(mock_page, "200640732-0836")

        assert result == {}

    @pytest.mark.asyncio
    async def test_fetch_job_details_network_error(self, mock_page):
        """Raises JobDetailsFetchError on network error"""
        mock_page.evaluate = AsyncMock(side_effect=Exception("Network timeout"))

        with pytest.raises(JobDetailsFetchError) as exc_info:
            await fetch_job_details(mock_page, "200640732-0836")

        assert "200640732-0836" in str(exc_info.value)
        assert "Network timeout" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_fetch_job_details_http_error(self, mock_page):
        """Raises JobDetailsFetchError on HTTP error from evaluate"""
        mock_page.evaluate = AsyncMock(side_effect=Exception("HTTP 404"))

        with pytest.raises(JobDetailsFetchError) as exc_info:
            await fetch_job_details(mock_page, "nonexistent-job")

        assert "nonexistent-job" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_fetch_job_details_rate_limited(self, mock_page):
        """Raises JobDetailsFetchError on rate limiting"""
        mock_page.evaluate = AsyncMock(side_effect=Exception("HTTP 429"))

        with pytest.raises(JobDetailsFetchError) as exc_info:
            await fetch_job_details(mock_page, "200640732-0836")

        assert "429" in str(exc_info.value)
