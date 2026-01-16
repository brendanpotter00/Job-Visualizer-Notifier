"""
Unit tests for Apple Jobs parser functions with mocked Playwright

Tests extract_job_cards_from_list() and check_has_next_page() with mocked page objects.
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from apple_jobs_scraper.parser import (
    extract_job_cards_from_list,
    check_has_next_page,
    JobCardExtractionError,
)


@pytest.fixture
def mock_page():
    """Create a mock Playwright page object"""
    page = AsyncMock()
    return page


@pytest.fixture
def mock_job_element():
    """Create a mock job list item element"""
    element = AsyncMock()
    return element


class TestExtractJobCardsFromListSuccess:
    """Tests for successful job card extraction"""

    @pytest.mark.asyncio
    async def test_extract_job_cards_from_list_success(self, mock_page):
        """Extracts jobs from mocked page"""
        # Mock the job list selector
        mock_page.wait_for_selector = AsyncMock()

        # Create mock job elements
        mock_element_1 = AsyncMock()
        mock_element_1.evaluate = AsyncMock(
            return_value={
                "title": "Software Engineer",
                "href": "/en-us/details/200640732-0836/software-engineer?team=SFTWR",
                "team": "Engineering",
                "location": "Cupertino, California",
                "postedDate": "Jan 10, 2025",
            }
        )

        mock_element_2 = AsyncMock()
        mock_element_2.evaluate = AsyncMock(
            return_value={
                "title": "Data Scientist",
                "href": "/en-us/details/200640733-0836/data-scientist?team=MLAI",
                "team": "Machine Learning",
                "location": "Austin, Texas",
                "postedDate": "Jan 8, 2025",
            }
        )

        mock_page.query_selector_all = AsyncMock(
            return_value=[mock_element_1, mock_element_2]
        )

        result = await extract_job_cards_from_list(mock_page)

        assert len(result) == 2
        assert result[0]["title"] == "Software Engineer"
        assert result[0]["id"] == "200640732-0836"
        assert result[0]["job_url"] == "https://jobs.apple.com/en-us/details/200640732-0836/software-engineer?team=SFTWR"
        assert result[1]["title"] == "Data Scientist"
        assert result[1]["id"] == "200640733-0836"

    @pytest.mark.asyncio
    async def test_extract_job_cards_from_list_with_complete_data(self, mock_page):
        """Extracts all fields correctly"""
        mock_page.wait_for_selector = AsyncMock()

        mock_element = AsyncMock()
        mock_element.evaluate = AsyncMock(
            return_value={
                "title": "Senior Software Engineer",
                "href": "/en-us/details/123456789-0836/senior-software-engineer?team=CLOUD",
                "team": "Cloud Platform",
                "location": "San Francisco, California, United States",
                "postedDate": "Dec 15, 2024",
            }
        )

        mock_page.query_selector_all = AsyncMock(return_value=[mock_element])

        result = await extract_job_cards_from_list(mock_page)

        assert len(result) == 1
        job = result[0]
        assert job["title"] == "Senior Software Engineer"
        assert job["id"] == "123456789-0836"
        assert job["team"] == "Cloud Platform"
        assert job["location"] == "San Francisco, California, United States"
        assert job["posted_date"] == "Dec 15, 2024"
        assert job["company"] == "apple"


class TestExtractJobCardsFromListEmpty:
    """Tests for empty job card extraction"""

    @pytest.mark.asyncio
    async def test_extract_job_cards_from_list_empty(self, mock_page):
        """Returns empty list when no jobs"""
        mock_page.wait_for_selector = AsyncMock()
        mock_page.query_selector_all = AsyncMock(return_value=[])

        result = await extract_job_cards_from_list(mock_page)

        assert result == []

    @pytest.mark.asyncio
    async def test_extract_job_cards_from_list_null_elements(self, mock_page):
        """Handles elements that return None from evaluate"""
        mock_page.wait_for_selector = AsyncMock()

        mock_element = AsyncMock()
        mock_element.evaluate = AsyncMock(return_value=None)

        mock_page.query_selector_all = AsyncMock(return_value=[mock_element])

        result = await extract_job_cards_from_list(mock_page)

        assert result == []


class TestExtractJobCardsFromListError:
    """Tests for job card extraction errors"""

    @pytest.mark.asyncio
    async def test_extract_job_cards_from_list_selector_timeout(self, mock_page):
        """Raises JobCardExtractionError on selector timeout"""
        mock_page.wait_for_selector = AsyncMock(
            side_effect=Exception("Timeout waiting for selector")
        )

        with pytest.raises(JobCardExtractionError) as exc_info:
            await extract_job_cards_from_list(mock_page)

        assert "Failed to extract job cards" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_extract_job_cards_from_list_all_parse_failures(self, mock_page):
        """Returns empty list when all elements fail to parse (caught internally)"""
        mock_page.wait_for_selector = AsyncMock()

        # Elements that raise exceptions during parsing - caught by _parse_job_element
        # which returns None, so empty list is returned (not an error)
        mock_element_1 = AsyncMock()
        mock_element_1.evaluate = AsyncMock(side_effect=Exception("Parse error"))

        mock_element_2 = AsyncMock()
        mock_element_2.evaluate = AsyncMock(side_effect=Exception("Parse error"))

        mock_page.query_selector_all = AsyncMock(
            return_value=[mock_element_1, mock_element_2]
        )

        # _parse_job_element catches exceptions and returns None, so result is empty list
        result = await extract_job_cards_from_list(mock_page)

        assert result == []

    @pytest.mark.asyncio
    async def test_extract_job_cards_from_list_partial_failures(self, mock_page):
        """Continues on partial parse failures"""
        mock_page.wait_for_selector = AsyncMock()

        # First element fails, second succeeds
        mock_element_1 = AsyncMock()
        mock_element_1.evaluate = AsyncMock(side_effect=Exception("Parse error"))

        mock_element_2 = AsyncMock()
        mock_element_2.evaluate = AsyncMock(
            return_value={
                "title": "Software Engineer",
                "href": "/en-us/details/123456/software-engineer",
                "team": "Engineering",
                "location": "Cupertino",
                "postedDate": "Jan 1, 2025",
            }
        )

        mock_page.query_selector_all = AsyncMock(
            return_value=[mock_element_1, mock_element_2]
        )

        result = await extract_job_cards_from_list(mock_page)

        # Should still return the successful parse
        assert len(result) == 1
        assert result[0]["title"] == "Software Engineer"


class TestCheckHasNextPageTrue:
    """Tests for check_has_next_page returning True"""

    @pytest.mark.asyncio
    async def test_check_has_next_page_true(self, mock_page):
        """Returns True when next button exists and is enabled"""
        mock_button = AsyncMock()
        mock_button.get_attribute = AsyncMock(return_value=None)  # Not disabled
        mock_page.query_selector = AsyncMock(return_value=mock_button)

        result = await check_has_next_page(mock_page)

        assert result is True

    @pytest.mark.asyncio
    async def test_check_has_next_page_button_exists_no_disabled(self, mock_page):
        """Returns True when button exists without disabled attribute"""
        mock_button = AsyncMock()
        mock_button.get_attribute = AsyncMock(return_value=None)
        mock_page.query_selector = AsyncMock(return_value=mock_button)

        result = await check_has_next_page(mock_page)

        assert result is True


class TestCheckHasNextPageFalse:
    """Tests for check_has_next_page returning False"""

    @pytest.mark.asyncio
    async def test_check_has_next_page_false_no_button(self, mock_page):
        """Returns False when no next button exists"""
        mock_page.query_selector = AsyncMock(return_value=None)

        result = await check_has_next_page(mock_page)

        assert result is False

    @pytest.mark.asyncio
    async def test_check_has_next_page_false_disabled(self, mock_page):
        """Returns False when button is disabled"""
        mock_button = AsyncMock()
        mock_button.get_attribute = AsyncMock(return_value="true")  # Disabled
        mock_page.query_selector = AsyncMock(return_value=mock_button)

        result = await check_has_next_page(mock_page)

        assert result is False

    @pytest.mark.asyncio
    async def test_check_has_next_page_false_disabled_empty_string(self, mock_page):
        """Returns False when button has disabled=""  """
        mock_button = AsyncMock()
        mock_button.get_attribute = AsyncMock(return_value="")  # Disabled with empty value
        mock_page.query_selector = AsyncMock(return_value=mock_button)

        result = await check_has_next_page(mock_page)

        assert result is False

    @pytest.mark.asyncio
    async def test_check_has_next_page_handles_exception(self, mock_page):
        """Returns None on exception to signal check failure"""
        mock_page.query_selector = AsyncMock(side_effect=Exception("Page error"))

        result = await check_has_next_page(mock_page)

        assert result is None


class TestExtractJobCardsEdgeCases:
    """Edge cases for job card extraction"""

    @pytest.mark.asyncio
    async def test_extract_job_cards_missing_href(self, mock_page):
        """Skips elements without href"""
        mock_page.wait_for_selector = AsyncMock()

        mock_element = AsyncMock()
        mock_element.evaluate = AsyncMock(
            return_value={
                "title": "Software Engineer",
                "href": None,  # Missing href
                "team": "Engineering",
                "location": "Cupertino",
                "postedDate": "Jan 1, 2025",
            }
        )

        mock_page.query_selector_all = AsyncMock(return_value=[mock_element])

        result = await extract_job_cards_from_list(mock_page)

        # Should skip jobs without href
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_job_cards_invalid_href_format(self, mock_page):
        """Skips elements with invalid href (no /details/)"""
        mock_page.wait_for_selector = AsyncMock()

        mock_element = AsyncMock()
        mock_element.evaluate = AsyncMock(
            return_value={
                "title": "Software Engineer",
                "href": "/en-us/search?location=usa",  # No /details/ in href
                "team": "Engineering",
                "location": "Cupertino",
                "postedDate": "Jan 1, 2025",
            }
        )

        mock_page.query_selector_all = AsyncMock(return_value=[mock_element])

        result = await extract_job_cards_from_list(mock_page)

        # Should skip jobs where job ID can't be extracted
        assert result == []
