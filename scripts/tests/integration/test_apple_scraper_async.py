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
from apple_jobs_scraper.parser import JobCardExtractionError, ZeroResultsPageError
from apple_jobs_scraper.api_client import JobSearchError
from apple_jobs_scraper.config import PAGE_MAX_ATTEMPTS, PAGE_RETRY_BACKOFF_S


@pytest.fixture
def no_sleep():
    """Skip the walk's real sleeps (settle + retry backoff) and expose them.

    Patches the scraper's own ``_sleep`` hook, not ``asyncio.sleep``, which
    would replace it for the whole process during the test.
    """
    sleep = AsyncMock()
    with patch("apple_jobs_scraper.scraper._sleep", sleep):
        yield sleep


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
    async def test_scrape_query_no_results(self, mock_context, mock_page, no_sleep):
        """A page that never yields cards is retried, then RAISES.

        It is never read as "board is empty": Apple's zero-results flake looks
        exactly like this, and an empty return would hand the incremental
        close phase a board with nothing on it.
        """
        scraper = AppleJobsScraper(headless=True, detail_scrape=False)
        scraper.context = mock_context
        scraper.navigate_to_page = AsyncMock()

        with patch(
            "apple_jobs_scraper.scraper.extract_job_cards_from_list",
            AsyncMock(return_value=[]),
        ):
            with pytest.raises(JobSearchError, match="page 1 failed all"):
                await scraper.scrape_query("", max_jobs=None)

        assert scraper.navigate_to_page.await_count == PAGE_MAX_ATTEMPTS


class TestScrapeQueryErrorRecovery:
    """Tests for error handling and recovery"""

    @pytest.mark.asyncio
    async def test_scrape_query_navigation_error_recovery(
        self, mock_context, mock_page, sample_job_cards, no_sleep
    ):
        """A transient navigation error is retried on the SAME page."""
        scraper = AppleJobsScraper(headless=True, detail_scrape=False)
        scraper.context = mock_context
        scraper._random_delay = AsyncMock()

        # First navigation fails, the retry succeeds
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

        assert len(result) == 2
        # Page 1 both times: the old code skipped ahead to page 2 and silently
        # dropped page 1's jobs.
        urls = [c.args[1] for c in scraper.navigate_to_page.await_args_list]
        assert urls == [scraper.build_search_url("", 1)] * 2

    @pytest.mark.asyncio
    async def test_scrape_query_consecutive_errors_stops(
        self, mock_context, mock_page, no_sleep
    ):
        """A page that never loads is retried PAGE_MAX_ATTEMPTS times, then raises."""
        scraper = AppleJobsScraper(headless=True, detail_scrape=False)
        scraper.context = mock_context
        scraper._random_delay = AsyncMock()

        # All navigations fail
        scraper.navigate_to_page = AsyncMock(side_effect=Exception("Network error"))

        with pytest.raises(JobSearchError, match="navigation error"):
            await scraper.scrape_query("", max_jobs=None)

        assert scraper.navigate_to_page.call_count == PAGE_MAX_ATTEMPTS

    @pytest.mark.asyncio
    async def test_scrape_query_extraction_error_stops(
        self, mock_context, mock_page, no_sleep
    ):
        """A list that stays unreadable is retried, then raises. It never returns []."""
        scraper = AppleJobsScraper(headless=True, detail_scrape=False)
        scraper.context = mock_context
        scraper.navigate_to_page = AsyncMock()

        with patch(
            "apple_jobs_scraper.scraper.extract_job_cards_from_list",
            AsyncMock(side_effect=JobCardExtractionError("Page structure changed")),
        ):
            with pytest.raises(JobSearchError, match="Page structure changed"):
                await scraper.scrape_query("", max_jobs=None)


class TestZeroResultsFlakeRetry:
    """Apple's search backend intermittently serves its zero-results template
    for a page that has 20 jobs, and a re-request gets the real page.

    From 2026-09-22 ~16:00Z this hit roughly 1 page in 10. Because one bad page
    abandoned the whole ~228-page walk, no Apple run completed after that.
    These tests pin the fix: retry the same page, never skip it, and fail
    loudly only when every attempt misses.
    See docs/incidents/2026-09-22-apple-zero-results-flake.md.
    """

    @staticmethod
    def _scraper(mock_context):
        scraper = AppleJobsScraper(headless=True, detail_scrape=False)
        scraper.context = mock_context
        scraper.navigate_to_page = AsyncMock()
        scraper._random_delay = AsyncMock()
        return scraper

    @pytest.mark.asyncio
    async def test_flaky_page_is_retried_and_walk_completes(
        self, mock_context, mock_page, sample_job_cards, no_sleep
    ):
        """3-page board; page 2 flakes twice. Every page lands, no truncation."""
        scraper = self._scraper(mock_context)
        flake = ZeroResultsPageError("Apple served its zero-results template")

        with patch(
            "apple_jobs_scraper.scraper.extract_job_cards_from_list",
            AsyncMock(
                side_effect=[
                    sample_job_cards,  # page 1
                    flake,  # page 2, attempt 1
                    flake,  # page 2, attempt 2
                    sample_job_cards,  # page 2, attempt 3
                    sample_job_cards,  # page 3
                ]
            ),
        ), patch(
            "apple_jobs_scraper.scraper.get_total_pages",
            AsyncMock(return_value=3),
        ), patch(
            "apple_jobs_scraper.scraper.check_has_next_page",
            AsyncMock(side_effect=[True, True, False]),
        ):
            result = await scraper.scrape_query("", max_jobs=None)

        assert len(result) == 6
        urls = [c.args[1] for c in scraper.navigate_to_page.await_args_list]
        assert urls == [
            scraper.build_search_url("", 1),
            scraper.build_search_url("", 2),
            scraper.build_search_url("", 2),
            scraper.build_search_url("", 2),
            scraper.build_search_url("", 3),
        ]

    @pytest.mark.asyncio
    async def test_retries_back_off_increasingly(
        self, mock_context, mock_page, sample_job_cards, no_sleep
    ):
        """Retry sleeps grow, so a throttling Apple gets breathing room."""
        scraper = self._scraper(mock_context)
        flake = ZeroResultsPageError("zero-results")

        with patch(
            "apple_jobs_scraper.scraper.extract_job_cards_from_list",
            AsyncMock(side_effect=[flake, flake, flake, sample_job_cards]),
        ), patch(
            "apple_jobs_scraper.scraper.get_total_pages",
            AsyncMock(return_value=1),
        ), patch(
            "apple_jobs_scraper.scraper.check_has_next_page",
            AsyncMock(return_value=False),
        ):
            await scraper.scrape_query("", max_jobs=None)

        # Drop the fixed 1s settle sleeps; what's left is the backoff.
        backoffs = [c.args[0] for c in no_sleep.await_args_list if c.args[0] != 1]
        assert len(backoffs) == 3
        assert backoffs == sorted(backoffs)
        # Each is its configured base times a 1.0–1.5x jitter.
        for actual, base in zip(backoffs, PAGE_RETRY_BACKOFF_S):
            assert 1.0 <= actual / base <= 1.5

    @pytest.mark.asyncio
    async def test_each_retry_uses_a_fresh_page(
        self, mock_context, mock_page, sample_job_cards, no_sleep
    ):
        scraper = self._scraper(mock_context)

        with patch(
            "apple_jobs_scraper.scraper.extract_job_cards_from_list",
            AsyncMock(side_effect=[ZeroResultsPageError("z"), sample_job_cards]),
        ), patch(
            "apple_jobs_scraper.scraper.get_total_pages",
            AsyncMock(return_value=1),
        ), patch(
            "apple_jobs_scraper.scraper.check_has_next_page",
            AsyncMock(return_value=False),
        ):
            await scraper.scrape_query("", max_jobs=None)

        # 1 page for the walk + 1 fresh page for the retry
        assert mock_context.new_page.await_count == 2

    @pytest.mark.asyncio
    async def test_retry_survives_a_page_that_refuses_to_close(
        self, sample_job_cards, no_sleep
    ):
        """A crashed page can raise on close(); that must not cost the retry."""
        crashed = AsyncMock()
        crashed.close = AsyncMock(side_effect=Exception("Target crashed"))
        fresh = AsyncMock()
        context = AsyncMock()
        context.new_page = AsyncMock(side_effect=[crashed, fresh])
        scraper = self._scraper(context)

        with patch(
            "apple_jobs_scraper.scraper.extract_job_cards_from_list",
            AsyncMock(side_effect=[ZeroResultsPageError("z"), sample_job_cards]),
        ), patch(
            "apple_jobs_scraper.scraper.get_total_pages",
            AsyncMock(return_value=1),
        ), patch(
            "apple_jobs_scraper.scraper.check_has_next_page",
            AsyncMock(return_value=False),
        ):
            result = await scraper.scrape_query("", max_jobs=None)

        assert len(result) == 2
        fresh.close.assert_awaited()

    @pytest.mark.asyncio
    async def test_persistent_zero_results_raises_and_never_skips_ahead(
        self, mock_context, mock_page, sample_job_cards, no_sleep
    ):
        """Page 2 never recovers: raise, and never try page 3 with a hole behind it."""
        scraper = self._scraper(mock_context)
        flake = ZeroResultsPageError("zero-results")

        with patch(
            "apple_jobs_scraper.scraper.extract_job_cards_from_list",
            AsyncMock(side_effect=[sample_job_cards] + [flake] * PAGE_MAX_ATTEMPTS),
        ), patch(
            "apple_jobs_scraper.scraper.get_total_pages",
            AsyncMock(return_value=228),
        ), patch(
            "apple_jobs_scraper.scraper.check_has_next_page",
            AsyncMock(return_value=True),
        ):
            with pytest.raises(JobSearchError, match="page 2 failed all") as exc:
                await scraper.scrape_query("", max_jobs=None)

        assert "zero-results template" in str(exc.value)
        urls = [c.args[1] for c in scraper.navigate_to_page.await_args_list]
        assert scraper.build_search_url("", 3) not in urls
        assert urls.count(scraper.build_search_url("", 2)) == PAGE_MAX_ATTEMPTS

    @pytest.mark.asyncio
    async def test_exhausted_retries_close_every_page_they_opened(self, no_sleep):
        """The last retry page is never handed back to the caller (we raise
        instead), so _load_page_cards must close it itself."""
        pages = [AsyncMock() for _ in range(PAGE_MAX_ATTEMPTS)]
        context = AsyncMock()
        context.new_page = AsyncMock(side_effect=pages)
        scraper = self._scraper(context)

        with patch(
            "apple_jobs_scraper.scraper.extract_job_cards_from_list",
            AsyncMock(side_effect=ZeroResultsPageError("zero-results")),
        ):
            with pytest.raises(JobSearchError, match="page 1 failed all"):
                await scraper.scrape_query("", max_jobs=None)

        for p in pages:
            p.close.assert_awaited()

    @pytest.mark.asyncio
    async def test_close_failure_in_finally_does_not_mask_page_failure(
        self, no_sleep
    ):
        """If the original page refuses a second close, the propagating
        JobSearchError (which names the real cause) must survive."""
        stubborn = AsyncMock()
        stubborn.close = AsyncMock(side_effect=RuntimeError("close failed"))
        others = [AsyncMock() for _ in range(PAGE_MAX_ATTEMPTS - 1)]
        context = AsyncMock()
        context.new_page = AsyncMock(side_effect=[stubborn, *others])
        scraper = self._scraper(context)

        with patch(
            "apple_jobs_scraper.scraper.extract_job_cards_from_list",
            AsyncMock(side_effect=ZeroResultsPageError("zero-results")),
        ):
            with pytest.raises(JobSearchError, match="SCRAPER PAGE FAILURE"):
                await scraper.scrape_query("", max_jobs=None)

    @pytest.mark.asyncio
    async def test_page_one_failure_raises_instead_of_returning_empty(
        self, mock_context, mock_page, no_sleep
    ):
        """Page 1 failing used to return [] (no page count read yet, so no
        truncation check) and trip the empty_scrape guard, which the
        health-watch then reported as a latched guard. It must raise like any
        other page."""
        scraper = self._scraper(mock_context)

        with patch(
            "apple_jobs_scraper.scraper.extract_job_cards_from_list",
            AsyncMock(side_effect=ZeroResultsPageError("zero-results")),
        ):
            with pytest.raises(JobSearchError, match="page 1 failed all"):
                await scraper.scrape_query("", max_jobs=None)


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


class TestScrapeQueryTruncationRaises:
    """scrape_query RAISES on a truncated walk (2026-08-28 pagination incident).

    When Apple advertises a page count (get_total_pages) and the walk ends far
    short of it, the run must raise rather than return a short list that the
    incremental close phase could reap. Mirrors tiktok/amazon's JobSearchError
    contract; verified upstream to record an errored run without mass-closing.
    """

    @pytest.mark.asyncio
    async def test_raises_when_walk_truncated_below_advertised_pages(
        self, mock_context, mock_page, sample_job_cards
    ):
        """total-pages says 226, walk stops after page 1 -> JobSearchError."""
        scraper = AppleJobsScraper(headless=True, detail_scrape=False)
        scraper.context = mock_context
        scraper.navigate_to_page = AsyncMock()
        scraper._random_delay = AsyncMock()

        with patch(
            "apple_jobs_scraper.scraper.extract_job_cards_from_list",
            AsyncMock(return_value=sample_job_cards),
        ), patch(
            "apple_jobs_scraper.scraper.get_total_pages",
            AsyncMock(return_value=226),
        ), patch(
            "apple_jobs_scraper.scraper.check_has_next_page",
            AsyncMock(return_value=False),  # the bug: stops after page 1
        ):
            with pytest.raises(JobSearchError, match="TRUNCATION"):
                await scraper.scrape_query("", max_jobs=None)

    @pytest.mark.asyncio
    async def test_no_raise_when_total_pages_unknown(
        self, mock_context, mock_page, sample_job_cards
    ):
        """No advertised page count -> cannot assert truncation -> return, no raise.

        Pins the documented fallback: without the oracle we defer to the
        incremental guard + health-watch A3, not a false alarm.
        """
        scraper = AppleJobsScraper(headless=True, detail_scrape=False)
        scraper.context = mock_context
        scraper.navigate_to_page = AsyncMock()
        scraper._random_delay = AsyncMock()

        with patch(
            "apple_jobs_scraper.scraper.extract_job_cards_from_list",
            AsyncMock(return_value=sample_job_cards),
        ), patch(
            "apple_jobs_scraper.scraper.get_total_pages",
            AsyncMock(return_value=None),
        ), patch(
            "apple_jobs_scraper.scraper.check_has_next_page",
            AsyncMock(return_value=False),
        ):
            result = await scraper.scrape_query("", max_jobs=None)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_max_jobs_stop_does_not_raise(
        self, mock_context, mock_page, sample_job_cards
    ):
        """A deliberate max_jobs stop on a large board is not a truncation."""
        scraper = AppleJobsScraper(headless=True, detail_scrape=False)
        scraper.context = mock_context
        scraper.navigate_to_page = AsyncMock()
        scraper._random_delay = AsyncMock()

        with patch(
            "apple_jobs_scraper.scraper.extract_job_cards_from_list",
            AsyncMock(return_value=sample_job_cards * 5),  # 10 jobs on page 1
        ), patch(
            "apple_jobs_scraper.scraper.get_total_pages",
            AsyncMock(return_value=226),
        ), patch(
            "apple_jobs_scraper.scraper.check_has_next_page",
            AsyncMock(return_value=True),
        ):
            result = await scraper.scrape_query("", max_jobs=3)

        assert len(result) == 3
