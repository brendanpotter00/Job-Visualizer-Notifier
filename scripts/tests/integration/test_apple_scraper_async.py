"""
Integration tests for AppleJobsScraper async methods

Tests scrape_query() and related async functionality with mocked Playwright.
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from apple_jobs_scraper.scraper import AppleJobsScraper
from apple_jobs_scraper.parser import JobCardExtractionError


@pytest.fixture
def mock_page():
    """Create a mock Playwright page object"""
    page = AsyncMock()
    page.close = AsyncMock()
    return page


@pytest.fixture
def mock_context(mock_page):
    """Create a mock browser context"""
    context = AsyncMock()
    context.new_page = AsyncMock(return_value=mock_page)
    return context


@pytest.fixture
def sample_job_cards():
    """Sample job cards as returned from extract_job_cards_from_list"""
    return [
        {
            "id": "200640732-0836",
            "title": "Software Engineer, Machine Learning",
            "job_url": "https://jobs.apple.com/en-us/details/200640732-0836/software-engineer-ml",
            "team": "ML/AI",
            "location": "Cupertino, California, United States",
            "company": "apple",
        },
        {
            "id": "200640733-0836",
            "title": "Data Scientist",
            "job_url": "https://jobs.apple.com/en-us/details/200640733-0836/data-scientist",
            "team": "Analytics",
            "location": "Austin, Texas, United States",
            "company": "apple",
        },
    ]


class TestScrapeQuerySinglePage:
    """Tests for scrape_query with single page of results"""

    @pytest.mark.asyncio
    async def test_scrape_query_single_page(self, mock_context, mock_page, sample_job_cards):
        """Single page of results returns jobs"""
        scraper = AppleJobsScraper(headless=True, detail_scrape=False)
        scraper.context = mock_context
        scraper.navigate_to_page = AsyncMock()

        with patch(
            "apple_jobs_scraper.scraper.extract_job_cards_from_list",
            AsyncMock(return_value=sample_job_cards),
        ), patch(
            "apple_jobs_scraper.scraper.check_has_next_page",
            AsyncMock(return_value=False),
        ):
            result = await scraper.scrape_query("", max_jobs=None)

        assert len(result) == 2
        assert result[0]["id"] == "200640732-0836"
        assert result[1]["id"] == "200640733-0836"
        mock_page.close.assert_called_once()


class TestScrapeQueryPagination:
    """Tests for scrape_query pagination handling"""

    @pytest.mark.asyncio
    async def test_scrape_query_pagination(self, mock_context, mock_page, sample_job_cards):
        """Multiple pages collected correctly"""
        scraper = AppleJobsScraper(headless=True, detail_scrape=False)
        scraper.context = mock_context
        scraper.navigate_to_page = AsyncMock()
        scraper._random_delay = AsyncMock()

        # First page has 2 jobs, second page has 1 job, then no more pages
        page_1_cards = sample_job_cards.copy()
        page_2_cards = [
            {
                "id": "200640734-0836",
                "title": "Backend Engineer",
                "job_url": "https://jobs.apple.com/en-us/details/200640734-0836/backend-engineer",
                "team": "Platform",
                "location": "Cupertino, California, United States",
                "company": "apple",
            }
        ]

        extract_mock = AsyncMock(side_effect=[page_1_cards, page_2_cards])
        has_next_mock = AsyncMock(side_effect=[True, False])

        with patch(
            "apple_jobs_scraper.scraper.extract_job_cards_from_list",
            extract_mock,
        ), patch(
            "apple_jobs_scraper.scraper.check_has_next_page",
            has_next_mock,
        ):
            result = await scraper.scrape_query("", max_jobs=None)

        assert len(result) == 3
        assert extract_mock.call_count == 2
        assert has_next_mock.call_count == 2


class TestScrapeQueryMaxJobsLimit:
    """Tests for max_jobs limit"""

    @pytest.mark.asyncio
    async def test_scrape_query_max_jobs_limit(self, mock_context, mock_page, sample_job_cards):
        """Stops at max_jobs limit"""
        scraper = AppleJobsScraper(headless=True, detail_scrape=False)
        scraper.context = mock_context
        scraper.navigate_to_page = AsyncMock()

        # Return many jobs on first page
        many_job_cards = sample_job_cards * 5  # 10 jobs total

        with patch(
            "apple_jobs_scraper.scraper.extract_job_cards_from_list",
            AsyncMock(return_value=many_job_cards),
        ), patch(
            "apple_jobs_scraper.scraper.check_has_next_page",
            AsyncMock(return_value=True),
        ):
            result = await scraper.scrape_query("", max_jobs=3)

        assert len(result) == 3


class TestScrapeQueryNoResults:
    """Tests for empty results"""

    @pytest.mark.asyncio
    async def test_scrape_query_no_results(self, mock_context, mock_page):
        """Empty page returns empty list"""
        scraper = AppleJobsScraper(headless=True, detail_scrape=False)
        scraper.context = mock_context
        scraper.navigate_to_page = AsyncMock()

        with patch(
            "apple_jobs_scraper.scraper.extract_job_cards_from_list",
            AsyncMock(return_value=[]),
        ):
            result = await scraper.scrape_query("", max_jobs=None)

        assert result == []


class TestScrapeQueryErrorRecovery:
    """Tests for error handling and recovery"""

    @pytest.mark.asyncio
    async def test_scrape_query_navigation_error_recovery(
        self, mock_context, mock_page, sample_job_cards
    ):
        """Recovers from transient navigation errors"""
        scraper = AppleJobsScraper(headless=True, detail_scrape=False)
        scraper.context = mock_context
        scraper._random_delay = AsyncMock()

        # First navigation fails, second succeeds
        scraper.navigate_to_page = AsyncMock(
            side_effect=[Exception("Network timeout"), None]
        )

        with patch(
            "apple_jobs_scraper.scraper.extract_job_cards_from_list",
            AsyncMock(return_value=sample_job_cards),
        ), patch(
            "apple_jobs_scraper.scraper.check_has_next_page",
            AsyncMock(return_value=False),
        ):
            result = await scraper.scrape_query("", max_jobs=None)

        # Should have recovered and collected jobs from page 2
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_scrape_query_consecutive_errors_stops(self, mock_context, mock_page):
        """Stops after 3 consecutive navigation errors"""
        scraper = AppleJobsScraper(headless=True, detail_scrape=False)
        scraper.context = mock_context
        scraper._random_delay = AsyncMock()

        # All navigations fail
        scraper.navigate_to_page = AsyncMock(side_effect=Exception("Network error"))

        result = await scraper.scrape_query("", max_jobs=None)

        # Should stop after max consecutive errors (3) and return empty list
        assert result == []
        # Should have attempted 3 times before stopping
        assert scraper.navigate_to_page.call_count == 3

    @pytest.mark.asyncio
    async def test_scrape_query_extraction_error_stops(self, mock_context, mock_page):
        """Stops on JobCardExtractionError"""
        scraper = AppleJobsScraper(headless=True, detail_scrape=False)
        scraper.context = mock_context
        scraper.navigate_to_page = AsyncMock()

        with patch(
            "apple_jobs_scraper.scraper.extract_job_cards_from_list",
            AsyncMock(side_effect=JobCardExtractionError("Page structure changed")),
        ):
            result = await scraper.scrape_query("", max_jobs=None)

        assert result == []


class TestExtractJobCards:
    """Tests for extract_job_cards wrapper method"""

    @pytest.mark.asyncio
    async def test_extract_job_cards_sets_id(self, mock_page):
        """Ensures ID field is set from URL when missing"""
        scraper = AppleJobsScraper(headless=True, detail_scrape=False)

        # Job card missing 'id' field
        job_cards_no_id = [
            {
                "title": "Software Engineer",
                "job_url": "https://jobs.apple.com/en-us/details/123456789/software-engineer",
                "company": "apple",
            }
        ]

        with patch(
            "apple_jobs_scraper.scraper.extract_job_cards_from_list",
            AsyncMock(return_value=job_cards_no_id),
        ):
            result = await scraper.extract_job_cards(mock_page)

        assert len(result) == 1
        assert result[0]["id"] == "123456789"  # Extracted from URL


class TestExtractJobDetails:
    """Tests for extract_job_details method"""

    @pytest.mark.asyncio
    async def test_extract_job_details_with_valid_url(self, mock_page):
        """Fetches details via API for valid URL"""
        scraper = AppleJobsScraper(headless=True, detail_scrape=False)
        job_url = "https://jobs.apple.com/en-us/details/200640732-0836/software-engineer"

        mock_details = {
            "title": "Software Engineer",
            "job_id": "200640732-0836",
            "description": "Work on amazing projects",
        }

        with patch(
            "apple_jobs_scraper.scraper.fetch_job_details",
            AsyncMock(return_value=mock_details),
        ):
            result = await scraper.extract_job_details(mock_page, job_url)

        assert result == mock_details

    @pytest.mark.asyncio
    async def test_extract_job_details_invalid_url(self, mock_page):
        """Returns empty dict for invalid URL"""
        scraper = AppleJobsScraper(headless=True, detail_scrape=False)
        job_url = "https://jobs.apple.com/en-us/search?location=usa"

        result = await scraper.extract_job_details(mock_page, job_url)

        assert result == {}


class TestRandomDelay:
    """Tests for _random_delay method"""

    @pytest.mark.asyncio
    async def test_random_delay_uses_apple_config(self):
        """Delay uses Apple-specific configuration"""
        scraper = AppleJobsScraper(headless=True, detail_scrape=False)

        with patch("asyncio.sleep", AsyncMock()) as mock_sleep:
            await scraper._random_delay()

            mock_sleep.assert_called_once()
            # Verify delay is within expected range (2-5 seconds from config)
            delay = mock_sleep.call_args[0][0]
            assert 2.0 <= delay <= 5.0
