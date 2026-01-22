"""
Integration tests for MicrosoftJobsScraper detail fetching methods

Tests scrape_job_details_streaming(), scrape_job_details_batch(), and _establish_session().
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from microsoft_jobs_scraper.scraper import MicrosoftJobsScraper
from microsoft_jobs_scraper.api_client import JobDetailsFetchError


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
    """Sample job cards for testing detail fetching"""
    return [
        {
            "id": "1970393556642428",
            "title": "Software Engineer II",
            "job_url": "https://apply.careers.microsoft.com/careers?position_id=1970393556642428",
            "location": "Redmond, WA, USA",
            "company": "microsoft",
        },
        {
            "id": "1970393556642429",
            "title": "Data Scientist",
            "job_url": "https://apply.careers.microsoft.com/careers?position_id=1970393556642429",
            "location": "Seattle, WA, USA",
            "company": "microsoft",
        },
    ]


@pytest.fixture
def sample_api_details():
    """Sample API response details"""
    return {
        "title": "Software Engineer II",
        "position_id": "1970393556642428",
        "description": "Work on cutting-edge Azure cloud services",
        "responsibilities": "Design and implement cloud solutions",
        "minimum_qualifications": ["BS in CS", "3+ years experience"],
        "preferred_qualifications": ["MS preferred"],
        "salary_range": "$130,000 - $190,000",
        "work_site": "Hybrid",
        "location": "Redmond, WA, USA",
    }


class TestScrapeJobDetailsStreamingCore:
    """Tests for scrape_job_details_streaming() core method"""

    @pytest.mark.asyncio
    async def test_streaming_yields_enriched_jobs(
        self, mock_context, mock_page, sample_job_cards, sample_api_details
    ):
        """API details merged into job cards"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=True)
        scraper.context = mock_context
        scraper._random_delay = AsyncMock()
        scraper._establish_session = AsyncMock()

        with patch(
            "microsoft_jobs_scraper.scraper.fetch_job_details",
            AsyncMock(return_value=sample_api_details),
        ):
            results = []
            async for job in scraper.scrape_job_details_streaming(sample_job_cards[:1]):
                results.append(job)

        assert len(results) == 1
        # Original fields preserved
        assert results[0]["id"] == "1970393556642428"
        assert results[0]["location"] == "Redmond, WA, USA"
        # API details merged in
        assert results[0]["description"] == "Work on cutting-edge Azure cloud services"
        assert results[0]["salary_range"] == "$130,000 - $190,000"

    @pytest.mark.asyncio
    async def test_streaming_yields_one_at_a_time(
        self, mock_context, mock_page, sample_job_cards, sample_api_details
    ):
        """Yields jobs one at a time"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=True)
        scraper.context = mock_context
        scraper._random_delay = AsyncMock()
        scraper._establish_session = AsyncMock()

        with patch(
            "microsoft_jobs_scraper.scraper.fetch_job_details",
            AsyncMock(return_value=sample_api_details),
        ):
            count = 0
            async for job in scraper.scrape_job_details_streaming(sample_job_cards):
                count += 1
                # Verify each job is yielded
                assert "id" in job
                assert job["description"] == "Work on cutting-edge Azure cloud services"

        assert count == 2

    @pytest.mark.asyncio
    async def test_streaming_respects_delay(
        self, mock_context, mock_page, sample_job_cards, sample_api_details
    ):
        """Calls delay between each job"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=True)
        scraper.context = mock_context
        scraper._random_delay = AsyncMock()
        scraper._establish_session = AsyncMock()

        with patch(
            "microsoft_jobs_scraper.scraper.fetch_job_details",
            AsyncMock(return_value=sample_api_details),
        ):
            async for _ in scraper.scrape_job_details_streaming(sample_job_cards):
                pass

        # Delay called for each job (2 jobs = 2 delays)
        assert scraper._random_delay.call_count == 2

    @pytest.mark.asyncio
    async def test_streaming_establishes_session(
        self, mock_context, mock_page, sample_job_cards, sample_api_details
    ):
        """Establishes session before fetching details"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=True)
        scraper.context = mock_context
        scraper._random_delay = AsyncMock()
        scraper._establish_session = AsyncMock()

        with patch(
            "microsoft_jobs_scraper.scraper.fetch_job_details",
            AsyncMock(return_value=sample_api_details),
        ):
            async for _ in scraper.scrape_job_details_streaming(sample_job_cards):
                pass

        # _establish_session should be called once at the start
        scraper._establish_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_streaming_closes_page(
        self, mock_context, mock_page, sample_job_cards, sample_api_details
    ):
        """Cleanup in finally block closes page"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=True)
        scraper.context = mock_context
        scraper._random_delay = AsyncMock()
        scraper._establish_session = AsyncMock()

        with patch(
            "microsoft_jobs_scraper.scraper.fetch_job_details",
            AsyncMock(return_value=sample_api_details),
        ):
            async for _ in scraper.scrape_job_details_streaming(sample_job_cards):
                pass

        mock_page.close.assert_called_once()


class TestScrapeJobDetailsStreamingErrors:
    """Tests for error handling in scrape_job_details_streaming()"""

    @pytest.mark.asyncio
    async def test_streaming_missing_id_skips_fetch(
        self, mock_context, mock_page
    ):
        """Yields original card when ID is missing"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=True)
        scraper.context = mock_context
        scraper._random_delay = AsyncMock()
        scraper._establish_session = AsyncMock()

        job_without_id = [
            {
                "title": "Software Engineer",
                "job_url": "https://apply.careers.microsoft.com/careers?position_id=123",
                "company": "microsoft",
            }
        ]

        with patch(
            "microsoft_jobs_scraper.scraper.fetch_job_details",
            AsyncMock(),
        ) as mock_fetch:
            results = []
            async for job in scraper.scrape_job_details_streaming(job_without_id):
                results.append(job)

        assert len(results) == 1
        assert results[0]["title"] == "Software Engineer"
        # fetch_job_details should NOT have been called since no ID
        mock_fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_streaming_api_error_sets_flag(
        self, mock_context, mock_page, sample_job_cards
    ):
        """Sets _detail_fetch_failed on JobDetailsFetchError"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=True)
        scraper.context = mock_context
        scraper._random_delay = AsyncMock()
        scraper._establish_session = AsyncMock()

        with patch(
            "microsoft_jobs_scraper.scraper.fetch_job_details",
            AsyncMock(side_effect=JobDetailsFetchError("API Error")),
        ):
            results = []
            async for job in scraper.scrape_job_details_streaming(sample_job_cards[:1]):
                results.append(job)

        assert len(results) == 1
        assert results[0]["_detail_fetch_failed"] is True
        # Original fields still present
        assert results[0]["id"] == "1970393556642428"

    @pytest.mark.asyncio
    async def test_streaming_unexpected_error_sets_flag(
        self, mock_context, mock_page, sample_job_cards
    ):
        """Sets _detail_fetch_failed on unexpected error"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=True)
        scraper.context = mock_context
        scraper._random_delay = AsyncMock()
        scraper._establish_session = AsyncMock()

        with patch(
            "microsoft_jobs_scraper.scraper.fetch_job_details",
            AsyncMock(side_effect=Exception("Unexpected error")),
        ):
            results = []
            async for job in scraper.scrape_job_details_streaming(sample_job_cards[:1]):
                results.append(job)

        assert len(results) == 1
        assert results[0]["_detail_fetch_failed"] is True

    @pytest.mark.asyncio
    async def test_streaming_continues_after_error(
        self, mock_context, mock_page, sample_job_cards, sample_api_details
    ):
        """Continues to next job after error"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=True)
        scraper.context = mock_context
        scraper._random_delay = AsyncMock()
        scraper._establish_session = AsyncMock()

        # First job fails, second succeeds
        with patch(
            "microsoft_jobs_scraper.scraper.fetch_job_details",
            AsyncMock(side_effect=[
                JobDetailsFetchError("API Error"),
                sample_api_details,
            ]),
        ):
            results = []
            async for job in scraper.scrape_job_details_streaming(sample_job_cards):
                results.append(job)

        assert len(results) == 2
        # First job has error flag
        assert results[0]["_detail_fetch_failed"] is True
        # Second job has details (no error flag when successful)
        assert "description" in results[1]
        assert "_detail_fetch_failed" not in results[1]


class TestScrapeJobDetailsBatch:
    """Tests for scrape_job_details_batch() method"""

    @pytest.mark.asyncio
    async def test_batch_returns_list(
        self, mock_context, mock_page, sample_job_cards, sample_api_details
    ):
        """Returns list of enriched jobs"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=True)
        scraper.context = mock_context
        scraper._random_delay = AsyncMock()
        scraper._establish_session = AsyncMock()

        with patch(
            "microsoft_jobs_scraper.scraper.fetch_job_details",
            AsyncMock(return_value=sample_api_details),
        ):
            result = await scraper.scrape_job_details_batch(sample_job_cards)

        assert isinstance(result, list)
        assert len(result) == 2
        # Both jobs enriched
        assert result[0]["description"] == "Work on cutting-edge Azure cloud services"
        assert result[1]["description"] == "Work on cutting-edge Azure cloud services"

    @pytest.mark.asyncio
    async def test_batch_empty_input(
        self, mock_context, mock_page
    ):
        """Empty list returns empty"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=True)
        scraper.context = mock_context
        scraper._establish_session = AsyncMock()

        result = await scraper.scrape_job_details_batch([])

        assert result == []

    @pytest.mark.asyncio
    async def test_batch_closes_page(
        self, mock_context, mock_page, sample_job_cards, sample_api_details
    ):
        """Page closed after batch operation"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=True)
        scraper.context = mock_context
        scraper._random_delay = AsyncMock()
        scraper._establish_session = AsyncMock()

        with patch(
            "microsoft_jobs_scraper.scraper.fetch_job_details",
            AsyncMock(return_value=sample_api_details),
        ):
            await scraper.scrape_job_details_batch(sample_job_cards)

        mock_page.close.assert_called_once()


class TestEstablishSession:
    """Tests for _establish_session() method"""

    @pytest.mark.asyncio
    async def test_establish_session_navigates_to_careers(self, mock_page):
        """URL contains /careers"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)
        scraper.navigate_to_page = AsyncMock()

        with patch("asyncio.sleep", AsyncMock()):
            await scraper._establish_session(mock_page)

        scraper.navigate_to_page.assert_called_once()
        call_args = scraper.navigate_to_page.call_args[0]
        assert "careers" in call_args[1]
        assert "microsoft" in call_args[1]

    @pytest.mark.asyncio
    async def test_establish_session_waits_for_load(self, mock_page):
        """Delay after navigation for page to fully load"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)
        scraper.navigate_to_page = AsyncMock()

        with patch("asyncio.sleep", AsyncMock()) as mock_sleep:
            await scraper._establish_session(mock_page)

        # asyncio.sleep should be called to wait for session establishment
        mock_sleep.assert_called_once()
        # Delay should be greater than 0 (SESSION_ESTABLISH_DELAY from config)
        assert mock_sleep.call_args[0][0] > 0
