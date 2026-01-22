"""
Unit tests for Microsoft Jobs parser functions (microsoft_jobs_scraper/parser.py)
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from microsoft_jobs_scraper.parser import (
    extract_position_id_from_url,
    extract_job_cards_from_list,
    check_has_next_page,
    _parse_job_element,
    JobCardExtractionError,
)


class TestExtractPositionIdFromUrl:
    """Tests for extract_position_id_from_url function"""

    def test_extract_position_id_from_query_param(self):
        """Extracts ID from position_id query parameter"""
        url = "https://apply.careers.microsoft.com/careers?position_id=1970393556642428&domain=microsoft.com"
        assert extract_position_id_from_url(url) == "1970393556642428"

    def test_extract_position_id_relative_url(self):
        """Works with relative URL"""
        url = "/careers?position_id=1234567890&domain=microsoft.com"
        assert extract_position_id_from_url(url) == "1234567890"

    def test_extract_position_id_from_path(self):
        """Extracts ID from /positions/ path"""
        url = "https://apply.careers.microsoft.com/positions/1970393556642428"
        assert extract_position_id_from_url(url) == "1970393556642428"

    def test_extract_position_id_from_position_path(self):
        """Extracts ID from /position/ path (singular)"""
        url = "/position/9876543210/details"
        assert extract_position_id_from_url(url) == "9876543210"

    def test_extract_position_id_various_ids(self):
        """Works with different position IDs"""
        test_cases = [
            ("?position_id=1111111111111111", "1111111111111111"),
            ("?position_id=2222222222222222&other=param", "2222222222222222"),
            ("/positions/3333333333333333/apply", "3333333333333333"),
        ]
        for url, expected_id in test_cases:
            assert extract_position_id_from_url(url) == expected_id

    def test_extract_position_id_empty_url(self):
        """Returns None for empty URL"""
        assert extract_position_id_from_url("") is None
        assert extract_position_id_from_url(None) is None

    def test_extract_position_id_no_match(self):
        """Returns None if no position ID in URL"""
        assert extract_position_id_from_url("https://careers.microsoft.com/search") is None
        assert extract_position_id_from_url("https://microsoft.com/jobs") is None
        assert extract_position_id_from_url("/careers?query=software") is None

    def test_extract_position_id_malformed_url(self):
        """Returns None for malformed URL"""
        assert extract_position_id_from_url("not-a-url") is None
        assert extract_position_id_from_url("/careers?position_id=") is None


class TestPositionIdFormats:
    """Tests for different Microsoft position ID formats"""

    def test_large_numeric_id(self):
        """Handles large numeric position IDs"""
        # Microsoft uses large numeric IDs
        url = "?position_id=1970393556642428"
        result = extract_position_id_from_url(url)

        assert result == "1970393556642428"
        assert len(result) == 16  # Typical length

    def test_position_id_with_additional_params(self):
        """Position ID extracted correctly with other query params"""
        url = "?domain=microsoft.com&position_id=1234567890123456&locale=en"
        result = extract_position_id_from_url(url)

        assert result == "1234567890123456"

    def test_position_id_first_param(self):
        """Position ID as first parameter"""
        url = "?position_id=9999999999999999&domain=microsoft.com"
        result = extract_position_id_from_url(url)

        assert result == "9999999999999999"


class TestExtractJobCardsFromList:
    """Tests for extract_job_cards_from_list async function"""

    @pytest.mark.asyncio
    async def test_extract_job_cards_returns_empty_when_no_selector_found(self):
        """Returns empty list when no job card selector is found"""
        mock_page = AsyncMock()
        mock_page.wait_for_selector.side_effect = Exception("Timeout")

        result = await extract_job_cards_from_list(mock_page)

        assert result == []

    @pytest.mark.asyncio
    async def test_extract_job_cards_returns_empty_when_no_elements(self):
        """Returns empty list when selector found but no elements"""
        mock_page = AsyncMock()
        mock_page.wait_for_selector.return_value = True
        mock_page.query_selector_all.return_value = []

        result = await extract_job_cards_from_list(mock_page)

        assert result == []

    @pytest.mark.asyncio
    async def test_extract_job_cards_parses_elements(self):
        """Successfully parses job elements"""
        mock_page = AsyncMock()
        mock_page.wait_for_selector.return_value = True

        mock_element = AsyncMock()
        mock_element.evaluate.return_value = {
            "title": "Software Engineer",
            "href": "/careers?position_id=1234567890&domain=microsoft.com",
            "positionId": "1234567890",
            "location": "Seattle, WA",
            "postedDate": "2024-12-15",
            "jobNumber": "200012345",
        }
        mock_page.query_selector_all.return_value = [mock_element]

        result = await extract_job_cards_from_list(mock_page)

        assert len(result) == 1
        assert result[0]["id"] == "1234567890"
        assert result[0]["title"] == "Software Engineer"
        assert result[0]["location"] == "Seattle, WA"
        assert result[0]["company"] == "microsoft"

    @pytest.mark.asyncio
    async def test_extract_job_cards_handles_parse_errors(self):
        """Continues parsing when individual element fails"""
        mock_page = AsyncMock()
        mock_page.wait_for_selector.return_value = True

        mock_element1 = AsyncMock()
        mock_element1.evaluate.side_effect = Exception("Parse error")

        mock_element2 = AsyncMock()
        mock_element2.evaluate.return_value = {
            "title": "Data Scientist",
            "href": "/careers?position_id=9876543210",
            "positionId": "9876543210",
            "location": "Redmond, WA",
            "postedDate": None,
            "jobNumber": None,
        }

        mock_page.query_selector_all.return_value = [mock_element1, mock_element2]

        result = await extract_job_cards_from_list(mock_page)

        assert len(result) == 1
        assert result[0]["id"] == "9876543210"

    @pytest.mark.asyncio
    async def test_extract_job_cards_returns_empty_when_all_fail_internally(self):
        """Returns empty list when all elements fail to parse internally

        Note: _parse_job_element catches exceptions internally and returns None,
        so JobCardExtractionError is not raised for internal parse failures.
        """
        mock_page = AsyncMock()
        mock_page.wait_for_selector.return_value = True

        mock_element1 = AsyncMock()
        mock_element1.evaluate.side_effect = Exception("Parse error 1")

        mock_element2 = AsyncMock()
        mock_element2.evaluate.side_effect = Exception("Parse error 2")

        mock_page.query_selector_all.return_value = [mock_element1, mock_element2]

        result = await extract_job_cards_from_list(mock_page)

        assert result == []


class TestCheckHasNextPage:
    """Tests for check_has_next_page async function"""

    @pytest.mark.asyncio
    async def test_check_has_next_page_returns_true_when_enabled(self):
        """Returns True when next button exists and is enabled"""
        mock_page = AsyncMock()
        mock_button = AsyncMock()
        mock_button.get_attribute.return_value = None  # No disabled attribute
        mock_page.query_selector.return_value = mock_button

        result = await check_has_next_page(mock_page)

        assert result is True

    @pytest.mark.asyncio
    async def test_check_has_next_page_returns_false_when_disabled(self):
        """Returns False when next button is disabled"""
        mock_page = AsyncMock()
        mock_button = AsyncMock()
        mock_button.get_attribute.side_effect = lambda attr: "true" if attr == "disabled" else None
        mock_page.query_selector.return_value = mock_button

        result = await check_has_next_page(mock_page)

        assert result is False

    @pytest.mark.asyncio
    async def test_check_has_next_page_returns_false_when_aria_disabled(self):
        """Returns False when next button has aria-disabled=true"""
        mock_page = AsyncMock()
        mock_button = AsyncMock()
        mock_button.get_attribute.side_effect = lambda attr: "true" if attr == "aria-disabled" else None
        mock_page.query_selector.return_value = mock_button

        result = await check_has_next_page(mock_page)

        assert result is False

    @pytest.mark.asyncio
    async def test_check_has_next_page_returns_false_when_no_button(self):
        """Returns False when no next page button found"""
        mock_page = AsyncMock()
        mock_page.query_selector.return_value = None

        result = await check_has_next_page(mock_page)

        assert result is False

    @pytest.mark.asyncio
    async def test_check_has_next_page_returns_none_on_error(self):
        """Returns None when check fails with exception"""
        mock_page = AsyncMock()
        mock_page.query_selector.side_effect = Exception("Page error")

        result = await check_has_next_page(mock_page)

        assert result is None

    @pytest.mark.asyncio
    async def test_check_has_next_page_checks_load_more(self):
        """Checks for Load More button if no next button"""
        mock_page = AsyncMock()

        # First 5 calls return None (no next button), then Load More found
        call_count = [0]
        async def mock_query_selector(selector):
            call_count[0] += 1
            if "Load More" in selector or "Show More" in selector:
                mock_button = AsyncMock()
                mock_button.get_attribute.return_value = None
                return mock_button
            return None

        mock_page.query_selector.side_effect = mock_query_selector

        result = await check_has_next_page(mock_page)

        assert result is True


class TestParseJobElement:
    """Tests for _parse_job_element async function"""

    @pytest.mark.asyncio
    async def test_parse_job_element_returns_job_data(self):
        """Successfully parses job element with all fields"""
        mock_element = AsyncMock()
        mock_element.evaluate.return_value = {
            "title": "Cloud Engineer",
            "href": "https://apply.careers.microsoft.com/careers?position_id=5555555555",
            "positionId": "5555555555",
            "location": "Austin, TX",
            "postedDate": "2024-12-10",
            "jobNumber": "200099999",
        }

        result = await _parse_job_element(mock_element)

        assert result is not None
        assert result["id"] == "5555555555"
        assert result["title"] == "Cloud Engineer"
        assert result["location"] == "Austin, TX"
        assert result["posted_date"] == "2024-12-10"
        assert result["job_number"] == "200099999"
        assert result["company"] == "microsoft"

    @pytest.mark.asyncio
    async def test_parse_job_element_returns_none_when_no_position_id(self):
        """Returns None when position ID cannot be extracted"""
        mock_element = AsyncMock()
        mock_element.evaluate.return_value = {
            "title": "Some Job",
            "href": "/careers",
            "positionId": None,
            "location": "Seattle",
            "postedDate": None,
            "jobNumber": None,
        }

        result = await _parse_job_element(mock_element)

        assert result is None

    @pytest.mark.asyncio
    async def test_parse_job_element_returns_none_on_evaluate_error(self):
        """Returns None when evaluate fails"""
        mock_element = AsyncMock()
        mock_element.evaluate.side_effect = Exception("Evaluation failed")

        result = await _parse_job_element(mock_element)

        assert result is None

    @pytest.mark.asyncio
    async def test_parse_job_element_handles_relative_url(self):
        """Makes relative URLs absolute"""
        mock_element = AsyncMock()
        mock_element.evaluate.return_value = {
            "title": "ML Engineer",
            "href": "/careers?position_id=7777777777",
            "positionId": "7777777777",
            "location": None,
            "postedDate": None,
            "jobNumber": None,
        }

        result = await _parse_job_element(mock_element)

        assert result is not None
        assert result["job_url"].startswith("https://")
        assert "position_id=7777777777" in result["job_url"]

    @pytest.mark.asyncio
    async def test_parse_job_element_handles_empty_href(self):
        """Creates fallback URL when href is empty"""
        mock_element = AsyncMock()
        mock_element.evaluate.return_value = {
            "title": "Security Engineer",
            "href": "",
            "positionId": "8888888888",
            "location": "Remote",
            "postedDate": None,
            "jobNumber": None,
        }

        result = await _parse_job_element(mock_element)

        assert result is not None
        assert result["id"] == "8888888888"
        assert "pid=8888888888" in result["job_url"]

    @pytest.mark.asyncio
    async def test_parse_job_element_returns_none_when_evaluate_returns_none(self):
        """Returns None when evaluate returns None"""
        mock_element = AsyncMock()
        mock_element.evaluate.return_value = None

        result = await _parse_job_element(mock_element)

        assert result is None
