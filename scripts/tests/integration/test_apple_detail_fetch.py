"""
Integration tests for AppleJobsScraper detail fetching methods

Tests _fetch_job_details(), scrape_job_details_batch(), and scrape_job_details_streaming().
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from apple_jobs_scraper.scraper import AppleJobsScraper
from apple_jobs_scraper.api_client import JobDetailsFetchError


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


@pytest.fixture
def sample_api_details():
    """Sample API response details"""
    return {
        "title": "Software Engineer, Machine Learning",
        "job_id": "200640732-0836",
        "description": "Work on cutting-edge ML systems",
        "job_summary": "Join our ML team",
        "responsibilities": "Design and implement ML pipelines",
        "minimum_qualifications": ["BS in CS", "3+ years experience"],
        "preferred_qualifications": ["PhD preferred"],
        "salary_range": "$175,000 - $295,000",
        "is_remote_eligible": False,
        "location": "Cupertino, California, United States",
    }


class TestFetchJobDetailsCore:
    """Tests for _fetch_job_details() core method"""

    @pytest.mark.asyncio
    async def test_fetch_job_details_enriches_cards(
        self, mock_context, mock_page, sample_job_cards, sample_api_details
    ):
        """Merges API details into job cards"""
        scraper = AppleJobsScraper(headless=True, detail_scrape=True)
        scraper.context = mock_context
        scraper._random_delay = AsyncMock()
        scraper.navigate_to_page = AsyncMock()

        with patch(
            "apple_jobs_scraper.scraper.fetch_job_details",
            AsyncMock(return_value=sample_api_details),
        ):
            results = []
            async for job in scraper._fetch_job_details(sample_job_cards[:1]):
                results.append(job)

        assert len(results) == 1
        # Original fields preserved
        assert results[0]["id"] == "200640732-0836"
        assert results[0]["team"] == "ML/AI"
        # API details merged in
        assert results[0]["description"] == "Work on cutting-edge ML systems"
        assert results[0]["salary_range"] == "$175,000 - $295,000"

    @pytest.mark.asyncio
    async def test_fetch_job_details_handles_missing_id(
        self, mock_context, mock_page
    ):
        """Skips jobs without ID, yields original card"""
        scraper = AppleJobsScraper(headless=True, detail_scrape=True)
        scraper.context = mock_context
        scraper._random_delay = AsyncMock()
        scraper.navigate_to_page = AsyncMock()

        job_without_id = [
            {
                "title": "Software Engineer",
                "job_url": "https://jobs.apple.com/en-us/details/123/software-engineer",
                "company": "apple",
            }
        ]

        with patch(
            "apple_jobs_scraper.scraper.fetch_job_details",
            AsyncMock(),
        ) as mock_fetch:
            results = []
            async for job in scraper._fetch_job_details(job_without_id):
                results.append(job)

        assert len(results) == 1
        assert results[0]["title"] == "Software Engineer"
        # fetch_job_details should NOT have been called since no ID
        mock_fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_job_details_api_error_sets_flag(
        self, mock_context, mock_page, sample_job_cards
    ):
        """Sets _detail_fetch_failed on API error"""
        scraper = AppleJobsScraper(headless=True, detail_scrape=True)
        scraper.context = mock_context
        scraper._random_delay = AsyncMock()
        scraper.navigate_to_page = AsyncMock()

        with patch(
            "apple_jobs_scraper.scraper.fetch_job_details",
            AsyncMock(side_effect=JobDetailsFetchError("API Error")),
        ):
            results = []
            async for job in scraper._fetch_job_details(sample_job_cards[:1]):
                results.append(job)

        assert len(results) == 1
        assert results[0]["_detail_fetch_failed"] is True
        # Original fields still present
        assert results[0]["id"] == "200640732-0836"

    @pytest.mark.asyncio
    async def test_fetch_job_details_unexpected_error_sets_flag(
        self, mock_context, mock_page, sample_job_cards
    ):
        """Sets _detail_fetch_failed on unexpected error"""
        scraper = AppleJobsScraper(headless=True, detail_scrape=True)
        scraper.context = mock_context
        scraper._random_delay = AsyncMock()
        scraper.navigate_to_page = AsyncMock()

        with patch(
            "apple_jobs_scraper.scraper.fetch_job_details",
            AsyncMock(side_effect=Exception("Unexpected error")),
        ):
            results = []
            async for job in scraper._fetch_job_details(sample_job_cards[:1]):
                results.append(job)

        assert len(results) == 1
        assert results[0]["_detail_fetch_failed"] is True


class TestScrapeJobDetailsBatch:
    """Tests for scrape_job_details_batch() method"""

    @pytest.mark.asyncio
    async def test_scrape_job_details_batch_returns_list(
        self, mock_context, mock_page, sample_job_cards, sample_api_details
    ):
        """Returns list of enriched jobs"""
        scraper = AppleJobsScraper(headless=True, detail_scrape=True)
        scraper.context = mock_context
        scraper._random_delay = AsyncMock()
        scraper.navigate_to_page = AsyncMock()

        with patch(
            "apple_jobs_scraper.scraper.fetch_job_details",
            AsyncMock(return_value=sample_api_details),
        ):
            result = await scraper.scrape_job_details_batch(sample_job_cards)

        assert isinstance(result, list)
        assert len(result) == 2
        # Both jobs enriched
        assert result[0]["description"] == "Work on cutting-edge ML systems"
        assert result[1]["description"] == "Work on cutting-edge ML systems"

    @pytest.mark.asyncio
    async def test_scrape_job_details_batch_empty_list(
        self, mock_context, mock_page
    ):
        """Handles empty job list"""
        scraper = AppleJobsScraper(headless=True, detail_scrape=True)
        scraper.context = mock_context
        scraper.navigate_to_page = AsyncMock()

        result = await scraper.scrape_job_details_batch([])

        assert result == []

    @pytest.mark.asyncio
    async def test_scrape_job_details_batch_closes_page(
        self, mock_context, mock_page, sample_job_cards, sample_api_details
    ):
        """Ensures page is closed after batch operation"""
        scraper = AppleJobsScraper(headless=True, detail_scrape=True)
        scraper.context = mock_context
        scraper._random_delay = AsyncMock()
        scraper.navigate_to_page = AsyncMock()

        with patch(
            "apple_jobs_scraper.scraper.fetch_job_details",
            AsyncMock(return_value=sample_api_details),
        ):
            await scraper.scrape_job_details_batch(sample_job_cards)

        mock_page.close.assert_called_once()


class TestScrapeJobDetailsStreaming:
    """Tests for scrape_job_details_streaming() method"""

    @pytest.mark.asyncio
    async def test_scrape_job_details_streaming_yields_one_at_a_time(
        self, mock_context, mock_page, sample_job_cards, sample_api_details
    ):
        """Yields jobs one at a time"""
        scraper = AppleJobsScraper(headless=True, detail_scrape=True)
        scraper.context = mock_context
        scraper._random_delay = AsyncMock()
        scraper.navigate_to_page = AsyncMock()

        with patch(
            "apple_jobs_scraper.scraper.fetch_job_details",
            AsyncMock(return_value=sample_api_details),
        ):
            count = 0
            async for job in scraper.scrape_job_details_streaming(sample_job_cards):
                count += 1
                # Verify each job is yielded
                assert "id" in job
                assert job["description"] == "Work on cutting-edge ML systems"

        assert count == 2

    @pytest.mark.asyncio
    async def test_scrape_job_details_streaming_respects_delay(
        self, mock_context, mock_page, sample_job_cards, sample_api_details
    ):
        """Calls delay between each job"""
        scraper = AppleJobsScraper(headless=True, detail_scrape=True)
        scraper.context = mock_context
        scraper._random_delay = AsyncMock()
        scraper.navigate_to_page = AsyncMock()

        with patch(
            "apple_jobs_scraper.scraper.fetch_job_details",
            AsyncMock(return_value=sample_api_details),
        ):
            async for _ in scraper.scrape_job_details_streaming(sample_job_cards):
                pass

        # Delay called for each job (2 jobs = 2 delays)
        assert scraper._random_delay.call_count == 2

    @pytest.mark.asyncio
    async def test_scrape_job_details_streaming_establishes_session(
        self, mock_context, mock_page, sample_job_cards, sample_api_details
    ):
        """Establishes session before fetching details"""
        scraper = AppleJobsScraper(headless=True, detail_scrape=True)
        scraper.context = mock_context
        scraper._random_delay = AsyncMock()
        scraper.navigate_to_page = AsyncMock()

        with patch(
            "apple_jobs_scraper.scraper.fetch_job_details",
            AsyncMock(return_value=sample_api_details),
        ):
            async for _ in scraper.scrape_job_details_streaming(sample_job_cards):
                pass

        # navigate_to_page should be called first to establish session
        scraper.navigate_to_page.assert_called()


class TestEstablishSession:
    """Tests for _establish_session() method"""

    @pytest.mark.asyncio
    async def test_establish_session_navigates_to_search(self, mock_page):
        """Navigates to Apple jobs search page"""
        scraper = AppleJobsScraper(headless=True, detail_scrape=False)
        scraper.navigate_to_page = AsyncMock()

        await scraper._establish_session(mock_page)

        scraper.navigate_to_page.assert_called_once()
        call_args = scraper.navigate_to_page.call_args[0]
        assert "jobs.apple.com" in call_args[1]
        assert "/search" in call_args[1]
