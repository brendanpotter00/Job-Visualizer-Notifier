"""
Integration tests for MicrosoftJobsScraper async methods

Tests scrape_query() and related async functionality with mocked Playwright.
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from microsoft_jobs_scraper.scraper import MicrosoftJobsScraper
from microsoft_jobs_scraper.parser import JobCardExtractionError
from microsoft_jobs_scraper.api_client import JobSearchError


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
    """Sample job cards as returned from API or HTML parsing"""
    return [
        {
            "id": "1970393556642428",
            "title": "Software Engineer II",
            "job_url": "https://apply.careers.microsoft.com/careers?position_id=1970393556642428",
            "location": "Redmond, WA, USA",
            "posted_date": "2024-12-15",
            "job_number": "200016306",
            "company": "microsoft",
        },
        {
            "id": "1970393556642429",
            "title": "Data Scientist",
            "job_url": "https://apply.careers.microsoft.com/careers?position_id=1970393556642429",
            "location": "Seattle, WA, USA",
            "posted_date": "2024-12-14",
            "job_number": "200016307",
            "company": "microsoft",
        },
    ]


class TestScrapeQuerySinglePage:
    """Tests for scrape_query with single page of results"""

    @pytest.mark.asyncio
    async def test_scrape_query_single_page_api_success(self, mock_context, mock_page, sample_job_cards):
        """API returns jobs, no more pages"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)
        scraper.context = mock_context
        scraper.navigate_to_page = AsyncMock()
        scraper._establish_session = AsyncMock()

        with patch.object(
            scraper,
            "_fetch_page_jobs",
            AsyncMock(return_value=(sample_job_cards, False, "API")),
        ):
            result = await scraper.scrape_query("software engineer", max_jobs=None)

        assert len(result) == 2
        assert result[0]["id"] == "1970393556642428"
        assert result[1]["id"] == "1970393556642429"
        mock_page.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_scrape_query_filters_non_software_jobs(self, mock_context, mock_page):
        """Jobs filtered by title keywords"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)
        scraper.context = mock_context
        scraper.navigate_to_page = AsyncMock()
        scraper._establish_session = AsyncMock()

        mixed_jobs = [
            {
                "id": "1234567890",
                "title": "Software Engineer",
                "job_url": "https://apply.careers.microsoft.com/careers?position_id=1234567890",
                "company": "microsoft",
            },
            {
                "id": "0987654321",
                "title": "Account Executive",  # Should be filtered out
                "job_url": "https://apply.careers.microsoft.com/careers?position_id=0987654321",
                "company": "microsoft",
            },
            {
                "id": "1111111111",
                "title": "Data Scientist",
                "job_url": "https://apply.careers.microsoft.com/careers?position_id=1111111111",
                "company": "microsoft",
            },
        ]

        with patch.object(
            scraper,
            "_fetch_page_jobs",
            AsyncMock(return_value=(mixed_jobs, False, "API")),
        ):
            result = await scraper.scrape_query("", max_jobs=None)

        assert len(result) == 2
        titles = [j["title"] for j in result]
        assert "Software Engineer" in titles
        assert "Data Scientist" in titles
        assert "Account Executive" not in titles


class TestScrapeQueryPagination:
    """Tests for scrape_query pagination handling"""

    @pytest.mark.asyncio
    async def test_scrape_query_multiple_pages(self, mock_context, mock_page, sample_job_cards):
        """has_more triggers pagination"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)
        scraper.context = mock_context
        scraper.navigate_to_page = AsyncMock()
        scraper._establish_session = AsyncMock()
        scraper._random_delay = AsyncMock()

        page_1_cards = sample_job_cards.copy()
        page_2_cards = [
            {
                "id": "2222222222",
                "title": "Backend Engineer",
                "job_url": "https://apply.careers.microsoft.com/careers?position_id=2222222222",
                "location": "Austin, TX, USA",
                "company": "microsoft",
            }
        ]

        fetch_mock = AsyncMock(side_effect=[
            (page_1_cards, True, "API"),
            (page_2_cards, False, "API"),
        ])

        with patch.object(scraper, "_fetch_page_jobs", fetch_mock):
            result = await scraper.scrape_query("", max_jobs=None)

        assert len(result) == 3
        assert fetch_mock.call_count == 2

    @pytest.mark.asyncio
    async def test_scrape_query_stops_when_no_more(self, mock_context, mock_page, sample_job_cards):
        """Stops when has_more=False"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)
        scraper.context = mock_context
        scraper.navigate_to_page = AsyncMock()
        scraper._establish_session = AsyncMock()
        scraper._random_delay = AsyncMock()

        fetch_mock = AsyncMock(return_value=(sample_job_cards, False, "API"))

        with patch.object(scraper, "_fetch_page_jobs", fetch_mock):
            result = await scraper.scrape_query("", max_jobs=None)

        assert len(result) == 2
        assert fetch_mock.call_count == 1
        scraper._random_delay.assert_not_called()

    @pytest.mark.asyncio
    async def test_scrape_query_calls_random_delay(self, mock_context, mock_page, sample_job_cards):
        """Delay called between pages"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)
        scraper.context = mock_context
        scraper.navigate_to_page = AsyncMock()
        scraper._establish_session = AsyncMock()
        scraper._random_delay = AsyncMock()

        page_1_cards = sample_job_cards.copy()
        page_2_cards = [
            {
                "id": "3333333333",
                "title": "ML Engineer",
                "job_url": "https://apply.careers.microsoft.com/careers?position_id=3333333333",
                "company": "microsoft",
            }
        ]

        fetch_mock = AsyncMock(side_effect=[
            (page_1_cards, True, "API"),
            (page_2_cards, False, "API"),
        ])

        with patch.object(scraper, "_fetch_page_jobs", fetch_mock):
            await scraper.scrape_query("", max_jobs=None)

        # Delay called once between page 1 and page 2
        assert scraper._random_delay.call_count == 1


class TestScrapeQueryMaxJobsLimit:
    """Tests for max_jobs limit"""

    @pytest.mark.asyncio
    async def test_scrape_query_max_jobs_truncates(self, mock_context, mock_page, sample_job_cards):
        """Returns max_jobs limit"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)
        scraper.context = mock_context
        scraper.navigate_to_page = AsyncMock()
        scraper._establish_session = AsyncMock()

        # Return many jobs on first page
        many_job_cards = sample_job_cards * 5  # 10 jobs total

        with patch.object(
            scraper,
            "_fetch_page_jobs",
            AsyncMock(return_value=(many_job_cards, True, "API")),
        ):
            result = await scraper.scrape_query("", max_jobs=3)

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_scrape_query_max_jobs_stops_early(self, mock_context, mock_page, sample_job_cards):
        """Stops pagination early when max_jobs reached"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)
        scraper.context = mock_context
        scraper.navigate_to_page = AsyncMock()
        scraper._establish_session = AsyncMock()
        scraper._random_delay = AsyncMock()

        many_job_cards = sample_job_cards * 3  # 6 jobs

        fetch_mock = AsyncMock(return_value=(many_job_cards, True, "API"))

        with patch.object(scraper, "_fetch_page_jobs", fetch_mock):
            result = await scraper.scrape_query("", max_jobs=5)

        assert len(result) == 5
        # Should stop after first page since we got enough jobs
        assert fetch_mock.call_count == 1


class TestScrapeQueryErrorRecovery:
    """Tests for error handling and recovery"""

    @pytest.mark.asyncio
    async def test_scrape_query_recovers_from_single_error(
        self, mock_context, mock_page, sample_job_cards
    ):
        """Recovers after one error"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)
        scraper.context = mock_context
        scraper.navigate_to_page = AsyncMock()
        scraper._establish_session = AsyncMock()
        scraper._random_delay = AsyncMock()

        # First call fails, second succeeds
        fetch_mock = AsyncMock(side_effect=[
            Exception("Network timeout"),
            (sample_job_cards, False, "API"),
        ])

        with patch.object(scraper, "_fetch_page_jobs", fetch_mock):
            result = await scraper.scrape_query("", max_jobs=None)

        # Should have recovered and collected jobs
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_scrape_query_consecutive_errors_stops(self, mock_context, mock_page):
        """Stops after 3 consecutive errors"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)
        scraper.context = mock_context
        scraper.navigate_to_page = AsyncMock()
        scraper._establish_session = AsyncMock()
        scraper._random_delay = AsyncMock()

        # All calls fail
        fetch_mock = AsyncMock(side_effect=Exception("Network error"))

        with patch.object(scraper, "_fetch_page_jobs", fetch_mock):
            result = await scraper.scrape_query("", max_jobs=None)

        # Should stop after 3 consecutive errors and return empty list
        assert result == []
        assert fetch_mock.call_count == 3

    @pytest.mark.asyncio
    async def test_scrape_query_empty_page_stops(self, mock_context, mock_page):
        """Empty results stops pagination"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)
        scraper.context = mock_context
        scraper.navigate_to_page = AsyncMock()
        scraper._establish_session = AsyncMock()

        with patch.object(
            scraper,
            "_fetch_page_jobs",
            AsyncMock(return_value=([], False, "API")),
        ):
            result = await scraper.scrape_query("", max_jobs=None)

        assert result == []

    @pytest.mark.asyncio
    async def test_scrape_query_extraction_error_continues(self, mock_context, mock_page, sample_job_cards):
        """Continues collecting jobs from successful pages even with extraction errors"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)
        scraper.context = mock_context
        scraper.navigate_to_page = AsyncMock()
        scraper._establish_session = AsyncMock()
        scraper._random_delay = AsyncMock()

        # First page succeeds, second fails with extraction error, third succeeds
        fetch_mock = AsyncMock(side_effect=[
            (sample_job_cards, True, "API"),
            Exception("Extraction error"),
            ([{"id": "9999", "title": "Cloud Engineer", "job_url": "url", "company": "microsoft"}], False, "API"),
        ])

        with patch.object(scraper, "_fetch_page_jobs", fetch_mock):
            result = await scraper.scrape_query("", max_jobs=None)

        # Should have collected jobs from page 1 and page 3
        assert len(result) == 3


class TestFetchPageJobsApiFirst:
    """Tests for _fetch_page_jobs API-first behavior"""

    @pytest.mark.asyncio
    async def test_fetch_page_jobs_api_success(self, mock_page, sample_job_cards):
        """Returns (jobs, has_more, 'API') on success"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)

        api_response = {
            "jobs": sample_job_cards,
            "has_more": True,
        }

        with patch(
            "microsoft_jobs_scraper.scraper.fetch_search_results",
            AsyncMock(return_value=api_response),
        ):
            jobs, has_more, source = await scraper._fetch_page_jobs(
                mock_page, "software engineer", 1
            )

        assert len(jobs) == 2
        assert has_more is True
        assert source == "API"

    @pytest.mark.asyncio
    async def test_fetch_page_jobs_api_failure_falls_back(self, mock_page, sample_job_cards):
        """HTML fallback on JobSearchError"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)
        scraper.navigate_to_page = AsyncMock()

        with patch(
            "microsoft_jobs_scraper.scraper.fetch_search_results",
            AsyncMock(side_effect=JobSearchError("API failed")),
        ), patch.object(
            scraper,
            "extract_job_cards",
            AsyncMock(return_value=sample_job_cards),
        ), patch(
            "microsoft_jobs_scraper.scraper.check_has_next_page",
            AsyncMock(return_value=True),
        ):
            jobs, has_more, source = await scraper._fetch_page_jobs(
                mock_page, "software engineer", 1
            )

        assert len(jobs) == 2
        assert has_more is True
        assert source == "HTML"
        scraper.navigate_to_page.assert_called_once()


class TestExtractJobCards:
    """Tests for extract_job_cards wrapper method"""

    @pytest.mark.asyncio
    async def test_extract_job_cards_sets_id_from_url(self, mock_page):
        """Missing ID extracted from URL"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)

        # Job card missing 'id' field but has job_url
        job_cards_no_id = [
            {
                "title": "Software Engineer",
                "job_url": "https://apply.careers.microsoft.com/careers?position_id=5555555555",
                "company": "microsoft",
            }
        ]

        with patch(
            "microsoft_jobs_scraper.scraper.extract_job_cards_from_list",
            AsyncMock(return_value=job_cards_no_id),
        ):
            result = await scraper.extract_job_cards(mock_page)

        assert len(result) == 1
        assert result[0]["id"] == "5555555555"

    @pytest.mark.asyncio
    async def test_extract_job_cards_preserves_existing_id(self, mock_page):
        """Existing ID preserved"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)

        job_cards_with_id = [
            {
                "id": "1234567890",
                "title": "Data Scientist",
                "job_url": "https://apply.careers.microsoft.com/careers?position_id=9999999999",
                "company": "microsoft",
            }
        ]

        with patch(
            "microsoft_jobs_scraper.scraper.extract_job_cards_from_list",
            AsyncMock(return_value=job_cards_with_id),
        ):
            result = await scraper.extract_job_cards(mock_page)

        assert len(result) == 1
        assert result[0]["id"] == "1234567890"  # Original ID preserved


class TestExtractJobDetails:
    """Tests for extract_job_details method"""

    @pytest.mark.asyncio
    async def test_extract_job_details_valid_url(self, mock_page):
        """Calls fetch_job_details for valid URL"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)
        job_url = "https://apply.careers.microsoft.com/careers?position_id=1970393556642428"

        mock_details = {
            "title": "Software Engineer",
            "position_id": "1970393556642428",
            "description": "Work on amazing projects",
        }

        with patch(
            "microsoft_jobs_scraper.scraper.fetch_job_details",
            AsyncMock(return_value=mock_details),
        ):
            result = await scraper.extract_job_details(mock_page, job_url)

        assert result == mock_details

    @pytest.mark.asyncio
    async def test_extract_job_details_invalid_url(self, mock_page):
        """Returns empty dict for invalid URL"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)
        job_url = "https://careers.microsoft.com/search?location=usa"

        result = await scraper.extract_job_details(mock_page, job_url)

        assert result == {}
