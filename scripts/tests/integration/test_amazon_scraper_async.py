"""
Integration tests for AmazonJobsScraper.scrape_query pagination.

This is the heart of the scraper: a wrong stop condition silently truncates the
scrape, and a thin scrape falsely CLOSES jobs via the consecutive-misses
lifecycle (see docs/incidents/2026-03-29-mass-job-closure.md).
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from amazon_jobs_scraper import scraper as amazon_scraper_module
from amazon_jobs_scraper.api_client import JobSearchError
from amazon_jobs_scraper.scraper import AmazonJobsScraper


@pytest.fixture
def mock_page():
    page = AsyncMock()
    page.close = AsyncMock()
    return page


@pytest.fixture
def mock_context(mock_page):
    context = AsyncMock()
    context.new_page = AsyncMock(return_value=mock_page)
    return context


@pytest.fixture
def scraper(mock_context):
    s = AmazonJobsScraper(headless=True, detail_scrape=False)
    s.context = mock_context
    s._establish_session = AsyncMock()
    s._random_delay = AsyncMock()
    return s


def _result(cards, raw_count=None, hits=None):
    """Build what fetch_search_results returns."""
    return {
        "jobs": cards,
        "raw_count": len(cards) if raw_count is None else raw_count,
        "hits": hits,
        "error": None,
        "skipped_missing_id": 0,
        "skipped_missing_title": 0,
    }


def _cards(n, offset=0):
    return [
        {
            "id": str(10_000_000 + offset + i),
            "title": f"Software Development Engineer {offset + i}",
            "job_url": f"https://www.amazon.jobs/en/jobs/{10_000_000 + offset + i}/sde",
        }
        for i in range(n)
    ]


@pytest.mark.asyncio
class TestStopConditions:
    async def test_stops_on_empty_page(self, scraper):
        pages = [_result(_cards(100)), _result([], raw_count=0)]
        with patch.object(
            amazon_scraper_module, "fetch_search_results", AsyncMock(side_effect=pages)
        ) as fetch:
            jobs = await scraper.scrape_query("software engineer")
        assert fetch.await_count == 2
        assert len(jobs) == 100

    async def test_stops_on_short_page(self, scraper):
        pages = [_result(_cards(100)), _result(_cards(3, 100))]
        with patch.object(
            amazon_scraper_module, "fetch_search_results", AsyncMock(side_effect=pages)
        ) as fetch:
            jobs = await scraper.scrape_query("software engineer")
        assert fetch.await_count == 2
        assert len(jobs) == 103

    async def test_stops_when_offset_reaches_hits(self, scraper):
        pages = [_result(_cards(100), hits=150), _result(_cards(50, 100), hits=150)]
        with patch.object(
            amazon_scraper_module, "fetch_search_results", AsyncMock(side_effect=pages)
        ) as fetch:
            jobs = await scraper.scrape_query("software engineer")
        assert fetch.await_count == 2
        assert len(jobs) == 150

    async def test_exact_boundary_hits_200_makes_no_third_call(self, scraper):
        """offset(100) + 100 >= 200 must stop without a third request."""
        pages = [_result(_cards(100), hits=200), _result(_cards(100, 100), hits=200)]
        with patch.object(
            amazon_scraper_module, "fetch_search_results", AsyncMock(side_effect=pages)
        ) as fetch:
            jobs = await scraper.scrape_query("software engineer")
        assert fetch.await_count == 2
        assert len(jobs) == 200

    @pytest.mark.parametrize("hits", [None, "1303"])
    async def test_non_int_hits_falls_through_to_short_page(self, scraper, hits):
        pages = [_result(_cards(100), hits=hits), _result(_cards(5, 100), hits=hits)]
        with patch.object(
            amazon_scraper_module, "fetch_search_results", AsyncMock(side_effect=pages)
        ) as fetch:
            jobs = await scraper.scrape_query("software engineer")
        assert fetch.await_count == 2
        assert len(jobs) == 105


@pytest.mark.asyncio
class TestErrorHandling:
    async def test_consecutive_error_bail_raises_instead_of_returning_partial(
        self, scraper
    ):
        """A gave-up run must RAISE, never return a short list.

        Returning what it collected is indistinguishable from "the board really
        shrank", and the incremental lifecycle closes the difference. One Amazon
        page is ~8% of the board, which is *under* the 15% partial_scrape guard,
        so the guard cannot be relied on to catch this.
        """
        with patch.object(
            amazon_scraper_module,
            "fetch_search_results",
            AsyncMock(side_effect=JobSearchError("boom")),
        ) as fetch:
            with pytest.raises(JobSearchError, match="consecutive fetch failures"):
                await scraper.scrape_query("software engineer")
        assert fetch.await_count == 3

    async def test_partial_collection_is_discarded_not_returned(self, scraper):
        """The dangerous shape: 12 good pages, then failure. Must not return 1200."""
        pages = [_result(_cards(100, i * 100)) for i in range(12)]
        side_effects = [*pages, *([JobSearchError("blip")] * 3)]
        with patch.object(
            amazon_scraper_module, "fetch_search_results", AsyncMock(side_effect=side_effects)
        ):
            with pytest.raises(JobSearchError) as exc:
                await scraper.scrape_query("software engineer")
        # The message must name the real cause and the loss, so an operator is
        # not sent hunting MAX_PAGES.
        assert "consecutive fetch failures" in str(exc.value)
        assert "1200 jobs had been collected" in str(exc.value)

    async def test_error_retries_same_offset_and_resets_counter(self, scraper):
        """Skipping ahead on error would silently drop 100 jobs (~8% of the board)."""
        side_effects = [
            JobSearchError("t1"),
            JobSearchError("t2"),
            _result(_cards(100)),
            _result([], raw_count=0),
        ]
        with patch.object(
            amazon_scraper_module, "fetch_search_results", AsyncMock(side_effect=side_effects)
        ) as fetch:
            jobs = await scraper.scrape_query("software engineer")

        offsets = [c.args[2] for c in fetch.await_args_list]
        assert offsets == [0, 0, 0, 100], f"expected same-offset retries, got {offsets}"
        assert len(jobs) == 100

    async def test_page_closed_even_when_loop_raises(self, scraper, mock_page):
        """The page must be closed on the failing path, not just the happy one."""
        with patch.object(
            amazon_scraper_module,
            "fetch_search_results",
            AsyncMock(side_effect=RuntimeError("hard failure")),
        ):
            with pytest.raises(JobSearchError):
                await scraper.scrape_query("software engineer")
        mock_page.close.assert_awaited()

    async def test_api_error_envelope_raises_and_is_not_end_of_results(self, scraper):
        """HTTP 200 + {"error": ..., "jobs": null} must not read as a clean finish.

        Amazon really does answer this way (e.g. "Cannot return more than 10000
        results at once"). Treating it as an empty page silently truncates the
        run and logs it as success.
        """
        pages = [
            _result(_cards(100)),
            {
                "jobs": [],
                "raw_count": 0,
                "hits": 0,
                "error": "Rate exceeded",
                "skipped_missing_id": 0,
                "skipped_missing_title": 0,
            },
        ]
        with patch.object(
            amazon_scraper_module, "fetch_search_results", AsyncMock(side_effect=pages)
        ):
            with pytest.raises(JobSearchError, match="Rate exceeded"):
                await scraper.scrape_query("software engineer")


@pytest.mark.asyncio
class TestPaginationBehaviour:
    async def test_page_cap_raises_and_names_max_pages(self, scraper):
        """Exhausting the page budget is a truncation, so it must be fatal too."""
        full = _result(_cards(100))
        with patch.object(amazon_scraper_module, "MAX_PAGES", 3):
            with patch.object(
                amazon_scraper_module,
                "fetch_search_results",
                AsyncMock(side_effect=[full, full, full]),
            ) as fetch:
                with pytest.raises(JobSearchError, match="MAX_PAGES"):
                    await scraper.scrape_query("software engineer")
        assert fetch.await_count == 3

    async def test_error_bail_does_not_blame_max_pages(self, scraper):
        """Regression: the bail used to be reported as a MAX_PAGES cap.

        It hit page 1 of a 50-page budget, so pointing the operator at MAX_PAGES
        sends them to fix the one thing that was not the cause.
        """
        with patch.object(
            amazon_scraper_module,
            "fetch_search_results",
            AsyncMock(side_effect=JobSearchError("boom")),
        ):
            with pytest.raises(JobSearchError) as exc:
                await scraper.scrape_query("software engineer")
        assert "MAX_PAGES" not in str(exc.value)

    async def test_no_cap_warning_on_natural_stop(self, scraper, caplog):
        pages = [_result(_cards(100)), _result(_cards(2, 100))]
        with patch.object(
            amazon_scraper_module, "fetch_search_results", AsyncMock(side_effect=pages)
        ):
            with caplog.at_level("WARNING"):
                await scraper.scrape_query("software engineer")
        assert "truncated" not in caplog.text

    async def test_dedupes_across_pages(self, scraper):
        """sort=recent shifts the window, so pages can overlap."""
        page0 = _cards(100)
        page1 = page0[80:] + _cards(80, 200)  # 20 repeats + 80 fresh
        pages = [_result(page0), _result(page1), _result([], raw_count=0)]
        with patch.object(
            amazon_scraper_module, "fetch_search_results", AsyncMock(side_effect=pages)
        ):
            jobs = await scraper.scrape_query("software engineer")
        ids = [j["id"] for j in jobs]
        assert len(ids) == len(set(ids)), "duplicate ids leaked through"
        assert len(jobs) == 180

    async def test_max_jobs_truncates_and_stops_early(self, scraper):
        with patch.object(
            amazon_scraper_module,
            "fetch_search_results",
            AsyncMock(side_effect=[_result(_cards(100))]),
        ) as fetch:
            jobs = await scraper.scrape_query("software engineer", max_jobs=40)
        assert len(jobs) == 40
        assert fetch.await_count == 1

    async def test_filtered_page_does_not_stop_pagination(self, scraper):
        """Stop conditions must read raw_count, never the post-filter length."""
        page0 = [
            dict(c, title="Technical Recruiter" if i < 60 else c["title"])
            for i, c in enumerate(_cards(100))
        ]
        pages = [_result(page0), _result(_cards(4, 100))]
        with patch.object(
            amazon_scraper_module, "fetch_search_results", AsyncMock(side_effect=pages)
        ) as fetch:
            jobs = await scraper.scrape_query("software engineer")
        assert fetch.await_count == 2, "a heavily filtered page is not a short page"
        assert len(jobs) == 44


@pytest.mark.asyncio
class TestSession:
    async def test_establishes_same_origin_session_first(self, mock_context, mock_page):
        """No CORS header on search.json — the page must be on amazon.jobs."""
        s = AmazonJobsScraper(headless=True, detail_scrape=False)
        s.context = mock_context
        s._random_delay = AsyncMock()
        s.navigate_to_page = AsyncMock()

        with patch.object(
            amazon_scraper_module,
            "fetch_search_results",
            AsyncMock(side_effect=[_result([], raw_count=0)]),
        ):
            with patch.object(amazon_scraper_module.asyncio, "sleep", AsyncMock()):
                await s.scrape_query("software engineer")

        s.navigate_to_page.assert_awaited_once()
        assert s.navigate_to_page.await_args[0][1].startswith("https://www.amazon.jobs")
