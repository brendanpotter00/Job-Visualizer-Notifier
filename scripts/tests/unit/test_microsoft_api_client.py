"""
Unit tests for Microsoft Jobs API client functions (microsoft_jobs_scraper/api_client.py)
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from microsoft_jobs_scraper.api_client import (
    parse_qualifications,
    extract_salary,
    get_apply_url,
    fetch_job_details,
    fetch_search_results,
    JobDetailsFetchError,
    JobSearchError,
    _parse_position_from_search,
    _parse_details_response,
    _format_location,
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

    def test_parse_qualifications_with_html(self):
        """Handles HTML-formatted text"""
        text = "<li>Bachelor's degree</li><li>5+ years experience</li>"
        result = parse_qualifications(text)

        assert len(result) == 2
        assert "Bachelor's degree" in result[0]
        assert "5+ years experience" in result[1]

    def test_parse_qualifications_with_bullets(self):
        """Handles bullet-point formatted text"""
        text = "• First qualification\n• Second qualification\n• Third qualification"
        result = parse_qualifications(text)

        assert len(result) >= 2  # Bullets are used as separators

    def test_parse_qualifications_list_input(self):
        """Handles list input directly"""
        quals = ["Bachelor's degree", "5+ years experience", "Python skills"]
        result = parse_qualifications(quals)

        assert result == quals


class TestExtractSalary:
    """Tests for extract_salary function"""

    def test_extract_salary_from_salary_range(self):
        """Extracts salary from salaryRange field"""
        data = {"salaryRange": "$141,800 - $258,600"}
        assert extract_salary(data) == "$141,800 - $258,600"

    def test_extract_salary_from_base_pay(self):
        """Extracts salary from basePay field"""
        data = {"basePay": "$150,000 - $200,000"}
        assert extract_salary(data) == "$150,000 - $200,000"

    def test_extract_salary_from_min_max(self):
        """Extracts salary from min/max fields"""
        data = {"minSalary": 100000, "maxSalary": 150000}
        result = extract_salary(data)
        assert result is not None
        assert "100,000" in result
        assert "150,000" in result

    def test_extract_salary_no_salary(self):
        """Returns None when no salary found"""
        data = {"description": "Great opportunity to join our team!"}
        assert extract_salary(data) is None

    def test_extract_salary_empty_data(self):
        """Returns None for empty data"""
        assert extract_salary({}) is None


class TestGetApplyUrl:
    """Tests for get_apply_url function"""

    def test_get_apply_url(self):
        """Builds correct apply URL"""
        position_id = "1970393556642428"
        expected = "https://apply.careers.microsoft.com/careers/apply?pid=1970393556642428"
        assert get_apply_url(position_id) == expected

    def test_get_apply_url_various_ids(self):
        """Works with different position IDs"""
        test_cases = [
            ("1234567890", "https://apply.careers.microsoft.com/careers/apply?pid=1234567890"),
            ("9876543210", "https://apply.careers.microsoft.com/careers/apply?pid=9876543210"),
        ]
        for position_id, expected in test_cases:
            assert get_apply_url(position_id) == expected


class TestParsePositionFromSearch:
    """Tests for _parse_position_from_search function"""

    def test_parse_position_basic(self):
        """Parses basic position data"""
        pos = {
            "id": "1970393556642428",
            "title": "Software Engineer",
            "location": "Seattle, WA, USA",
            "postedDate": "2024-12-15",
            "jobNumber": "200016306",
        }

        result = _parse_position_from_search(pos)

        assert result is not None
        assert result["id"] == "1970393556642428"
        assert result["title"] == "Software Engineer"
        assert result["location"] == "Seattle, WA, USA"
        assert result["posted_date"] == "2024-12-15"
        assert result["job_number"] == "200016306"
        assert result["company"] == "microsoft"

    def test_parse_position_nested_location(self):
        """Handles nested location structure"""
        pos = {
            "id": "1234567890",
            "title": "Data Scientist",
            "location": {
                "city": "Redmond",
                "state": "WA",
                "country": "USA",
            },
        }

        result = _parse_position_from_search(pos)

        assert result is not None
        assert "Redmond" in result["location"]
        assert "WA" in result["location"]

    def test_parse_position_location_list(self):
        """Handles location as list"""
        pos = {
            "id": "1234567890",
            "title": "Program Manager",
            "location": [
                {"city": "Seattle", "state": "WA", "country": "USA"},
                {"city": "Redmond", "state": "WA", "country": "USA"},
            ],
        }

        result = _parse_position_from_search(pos)

        assert result is not None
        assert "Seattle" in result["location"]

    def test_parse_position_missing_id(self):
        """Returns None for missing ID"""
        pos = {"title": "Software Engineer", "location": "Seattle"}
        assert _parse_position_from_search(pos) is None

    def test_parse_position_alternative_fields(self):
        """Handles alternative field names"""
        pos = {
            "id": "9876543210",  # Microsoft uses 'id' field
            "name": "Cloud Engineer",
            "locations": [{"city": "Austin", "state": "TX", "country": "USA"}],
            "createdTs": "2024-12-10",
            "displayJobId": "REQ123456",
        }

        result = _parse_position_from_search(pos)

        assert result is not None
        assert result["id"] == "9876543210"
        assert result["title"] == "Cloud Engineer"
        assert result["job_number"] == "REQ123456"
        assert "Austin" in result["location"]


class TestParseDetailsResponse:
    """Tests for _parse_details_response function"""

    def test_parse_details_complete(self):
        """Parses complete details response"""
        data = {
            "position": {
                "title": "Software Engineer II",
                "jobNumber": "200016306",
                "description": "Work on Azure services",
                "responsibilities": "Design and implement solutions",
                "minimumQualifications": "BS in CS\n3+ years experience",
                "preferredQualifications": "MS preferred",
                "location": "Redmond, WA, USA",
                "salaryRange": "$120,000 - $180,000",
                "workSite": "Hybrid",
                "travel": "10%",
                "profession": "Engineering",
                "discipline": "Software Development",
                "roleType": "Individual Contributor",
                "employmentType": "Full-time",
                "postedDate": "2024-12-15",
            }
        }

        result = _parse_details_response(data, "1234567890")

        assert result["title"] == "Software Engineer II"
        assert result["position_id"] == "1234567890"
        assert result["job_number"] == "200016306"
        assert result["description"] == "Work on Azure services"
        assert len(result["minimum_qualifications"]) == 2
        assert result["salary_range"] == "$120,000 - $180,000"
        assert result["work_site"] == "Hybrid"

    def test_parse_details_minimal(self):
        """Handles minimal response"""
        data = {"title": "Simple Job"}

        result = _parse_details_response(data, "1234567890")

        assert result["title"] == "Simple Job"
        assert result["position_id"] == "1234567890"
        assert result["minimum_qualifications"] == []
        assert result["preferred_qualifications"] == []

    def test_parse_details_preserves_raw(self):
        """Preserves raw API response"""
        data = {"title": "Test Job", "customField": "custom value"}

        result = _parse_details_response(data, "123")

        assert "raw_api_response" in result
        assert result["raw_api_response"] == data

    def test_parse_details_with_data_wrapper(self):
        """Handles API response wrapped in 'data' key (Microsoft's actual format)"""
        data = {
            "status": 200,
            "error": {"errorCode": "", "errorDescription": ""},
            "data": {
                "name": "Software Engineer II",
                "location": "United States, California, Mountain View",
                "jobNumber": "1234567",
                "description": "Join our team",
                "minimumQualifications": "BS in CS",
            }
        }

        result = _parse_details_response(data, "1970393556642428")

        assert result["title"] == "Software Engineer II"
        assert result["position_id"] == "1970393556642428"
        assert result["location"] == "United States, California, Mountain View"
        assert result["job_number"] == "1234567"
        assert result["description"] == "Join our team"


class TestFetchSearchResults:
    """Tests for fetch_search_results async function"""

    @pytest.mark.asyncio
    async def test_fetch_search_results_success(self, mock_playwright_page, microsoft_search_response):
        """Successfully fetches and parses search results"""
        mock_playwright_page.evaluate = AsyncMock(return_value=microsoft_search_response)

        result = await fetch_search_results(mock_playwright_page, "software engineer", 0)

        assert len(result["jobs"]) == 2
        assert result["total_count"] == 100
        assert result["has_more"] is True
        mock_playwright_page.evaluate.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_search_results_empty(self, mock_playwright_page):
        """Handles empty results"""
        mock_playwright_page.evaluate = AsyncMock(return_value={"positions": [], "totalCount": 0})

        result = await fetch_search_results(mock_playwright_page, "nonexistent query", 0)

        assert result["jobs"] == []
        assert result["has_more"] is False

    @pytest.mark.asyncio
    async def test_fetch_search_results_network_error(self, mock_playwright_page):
        """Raises JobSearchError on network error"""
        mock_playwright_page.evaluate = AsyncMock(side_effect=Exception("Network timeout"))

        with pytest.raises(JobSearchError) as exc_info:
            await fetch_search_results(mock_playwright_page, "software engineer", 0)

        assert "Network timeout" in str(exc_info.value)


class TestFetchJobDetails:
    """Tests for fetch_job_details async function"""

    @pytest.mark.asyncio
    async def test_fetch_job_details_success(self, mock_playwright_page, microsoft_details_response):
        """Successfully fetches and parses job details"""
        mock_playwright_page.evaluate = AsyncMock(return_value=microsoft_details_response)

        result = await fetch_job_details(mock_playwright_page, "1234567890")

        assert result["title"] == "Software Engineer II"
        assert result["job_number"] == "200016306"
        assert result["salary_range"] == "$130,000 - $190,000"
        assert len(result["minimum_qualifications"]) == 2
        mock_playwright_page.evaluate.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_job_details_network_error(self, mock_playwright_page):
        """Raises JobDetailsFetchError on network error"""
        mock_playwright_page.evaluate = AsyncMock(side_effect=Exception("Network timeout"))

        with pytest.raises(JobDetailsFetchError) as exc_info:
            await fetch_job_details(mock_playwright_page, "1234567890")

        assert "1234567890" in str(exc_info.value)
        assert "Network timeout" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_fetch_job_details_http_error(self, mock_playwright_page):
        """Raises JobDetailsFetchError on HTTP error"""
        mock_playwright_page.evaluate = AsyncMock(side_effect=Exception("HTTP 404"))

        with pytest.raises(JobDetailsFetchError) as exc_info:
            await fetch_job_details(mock_playwright_page, "nonexistent")

        assert "nonexistent" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_fetch_job_details_rate_limited(self, mock_playwright_page):
        """Raises JobDetailsFetchError on rate limiting"""
        mock_playwright_page.evaluate = AsyncMock(side_effect=Exception("HTTP 429"))

        with pytest.raises(JobDetailsFetchError) as exc_info:
            await fetch_job_details(mock_playwright_page, "1234567890")

        assert "429" in str(exc_info.value)


class TestFormatLocation:
    """Tests for _format_location function"""

    def test_format_location_string_passthrough(self):
        """String location returned as-is"""
        result = _format_location("Seattle, WA, USA")

        assert result == "Seattle, WA, USA"

    def test_format_location_dict_full(self):
        """Dict with city, state, country formatted correctly"""
        loc = {"city": "Redmond", "state": "WA", "country": "USA"}

        result = _format_location(loc)

        assert "Redmond" in result
        assert "WA" in result
        assert "USA" in result
        assert result == "Redmond, WA, USA"

    def test_format_location_dict_partial(self):
        """Dict with city and country (no state)"""
        loc = {"city": "London", "country": "UK"}

        result = _format_location(loc)

        assert "London" in result
        assert "UK" in result
        assert result == "London, UK"

    def test_format_location_dict_city_only(self):
        """Dict with only city"""
        loc = {"city": "Seattle"}

        result = _format_location(loc)

        assert result == "Seattle"

    def test_format_location_list_single(self):
        """List with single location uses first item"""
        loc = [{"city": "Austin", "state": "TX", "country": "USA"}]

        result = _format_location(loc)

        assert "Austin" in result
        assert "TX" in result

    def test_format_location_list_multiple(self):
        """List with multiple locations uses first item"""
        loc = [
            {"city": "Seattle", "state": "WA", "country": "USA"},
            {"city": "Redmond", "state": "WA", "country": "USA"},
        ]

        result = _format_location(loc)

        # Should use first location
        assert "Seattle" in result

    def test_format_location_empty_none(self):
        """None returns empty string"""
        result = _format_location(None)

        assert result == ""

    def test_format_location_empty_string(self):
        """Empty string returns empty string"""
        result = _format_location("")

        assert result == ""

    def test_format_location_empty_dict(self):
        """Empty dict returns empty string"""
        result = _format_location({})

        assert result == ""
