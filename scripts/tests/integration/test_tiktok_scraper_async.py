"""
Integration tests for TikTokJobsScraper.scrape_query pagination.

A wrong stop condition silently truncates the scrape, and a thin scrape falsely
CLOSES jobs via the consecutive-misses lifecycle (see
docs/incidents/2026-03-29-mass-job-closure.md).
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tiktok_jobs_scraper import scraper as tiktok_scraper_module
from tiktok_jobs_scraper.api_client import JobSearchError
from tiktok_jobs_scraper.scraper import TikTokJobsScraper

US = "San Jose, California, United States of America"
SG = "Singapore, Singapore, Singapore"


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
    s = TikTokJobsScraper(headless=True, detail_scrape=False)
    s.context = mock_context
    s._establish_session = AsyncMock()
    s._random_delay = AsyncMock()
    return s


def _result(cards, raw_count=None, total=None):
    return {
        "jobs": cards,
        "raw_count": len(cards) if raw_count is None else raw_count,
        "total": total,
        "skipped_missing_id": 0,
        "skipped_missing_title": 0,
    }


def _cards(n, offset=0, location=US, title="Software Engineer"):
    return [
        {
            "id": str(7_600_000_000_000_000_000 + offset + i),
            "title": f"{title} {offset + i}",
            "job_url": f"https://lifeattiktok.com/search/{7_600_000_000_000_000_000 + offset + i}",
            "location": location,
        }
        for i in range(n)
    ]


@pytest.mark.asyncio
class TestStopConditions:
    async def test_stops_on_empty_page(self, scraper):
        pages = [_result(_cards(100)), _result([], raw_count=0)]
        with patch.object(
            tiktok_scraper_module, "fetch_search_results", AsyncMock(side_effect=pages)
        ) as fetch:
            jobs = await scraper.scrape_query("software engineer")
        assert fetch.await_count == 2
        assert len(jobs) == 100

    async def test_stops_on_short_page(self, scraper):
        pages = [_result(_cards(100)), _result(_cards(16, 100))]
        with patch.object(
            tiktok_scraper_module, "fetch_search_results", AsyncMock(side_effect=pages)
        ) as fetch:
            jobs = await scraper.scrape_query("software engineer")
        assert fetch.await_count == 2
        assert len(jobs) == 116

    async def test_stops_when_offset_reaches_total(self, scraper):
        pages = [_result(_cards(100), total=150), _result(_cards(50, 100), total=150)]
        with patch.object(
            tiktok_scraper_module, "fetch_search_results", AsyncMock(side_effect=pages)
        ) as fetch:
            jobs = await scraper.scrape_query("software engineer")
        assert fetch.await_count == 2
        assert len(jobs) == 150

    async def test_exact_boundary_makes_no_third_call(self, scraper):
        pages = [_result(_cards(100), total=200), _result(_cards(100, 100), total=200)]
        with patch.object(
            tiktok_scraper_module, "fetch_search_results", AsyncMock(side_effect=pages)
        ) as fetch:
            jobs = await scraper.scrape_query("software engineer")
        assert fetch.await_count == 2
        assert len(jobs) == 200

    @pytest.mark.parametrize("total", [None, "716"])
    async def test_non_int_total_falls_through(self, scraper, total):
        pages = [_result(_cards(100), total=total), _result(_cards(5, 100), total=total)]
        with patch.object(
            tiktok_scraper_module, "fetch_search_results", AsyncMock(side_effect=pages)
        ) as fetch:
            jobs = await scraper.scrape_query("software engineer")
        assert fetch.await_count == 2
        assert len(jobs) == 105


@pytest.mark.asyncio
class TestErrorHandling:
    async def test_consecutive_error_bail_raises_instead_of_returning_partial(
        self, scraper
    ):
        """An exhausted retry budget must raise, never return a short list.

        Returning [] (or a partial list) hands the incremental lifecycle
        something indistinguishable from "every job is gone" and it closes the
        whole board. See docs/incidents/2026-03-29-mass-job-closure.md.
        """
        with patch.object(
            tiktok_scraper_module,
            "fetch_search_results",
            AsyncMock(side_effect=JobSearchError("api error code=1001")),
        ) as fetch:
            with pytest.raises(JobSearchError, match="consecutive fetch failures"):
                await scraper.scrape_query("software engineer")
        assert fetch.await_count == 3

    async def test_partial_collection_is_discarded_not_returned(self, scraper):
        """Two good pages then an outage: the 200 collected jobs are discarded.

        This is the blind spot the partial_scrape guard cannot cover — losing
        the tail of the board is well above its ~85% trip threshold.
        """
        pages = [_result(_cards(100)), _result(_cards(100, 100))]
        side_effects = [*pages, *([JobSearchError("blip")] * 3)]
        with patch.object(
            tiktok_scraper_module, "fetch_search_results", AsyncMock(side_effect=side_effects)
        ):
            with pytest.raises(JobSearchError) as exc:
                await scraper.scrape_query("software engineer")
        assert "200 jobs had been collected" in str(exc.value)
        assert "consecutive fetch failures" in str(exc.value)

    async def test_error_retries_same_offset_and_resets_counter(self, scraper):
        """Skipping ahead on error would silently drop 100 jobs."""
        side_effects = [
            JobSearchError("t1"),
            JobSearchError("t2"),
            _result(_cards(100)),
            _result([], raw_count=0),
        ]
        with patch.object(
            tiktok_scraper_module, "fetch_search_results", AsyncMock(side_effect=side_effects)
        ) as fetch:
            jobs = await scraper.scrape_query("software engineer")

        offsets = [c.args[2] for c in fetch.await_args_list]
        assert offsets == [0, 0, 0, 100], f"expected same-offset retries, got {offsets}"
        assert len(jobs) == 100

    async def test_page_closed_even_when_loop_raises(self, scraper, mock_page):
        with patch.object(
            tiktok_scraper_module,
            "fetch_search_results",
            AsyncMock(side_effect=RuntimeError("hard failure")),
        ):
            with pytest.raises(JobSearchError):
                await scraper.scrape_query("software engineer")
        mock_page.close.assert_awaited()


@pytest.mark.asyncio
class TestFilteringDuringPagination:
    async def test_non_us_jobs_are_dropped(self, scraper):
        page0 = _cards(60, 0, location=US) + _cards(40, 60, location=SG)
        pages = [_result(page0, raw_count=100), _result(_cards(2, 100))]
        with patch.object(
            tiktok_scraper_module, "fetch_search_results", AsyncMock(side_effect=pages)
        ):
            jobs = await scraper.scrape_query("software engineer")
        assert all("United States" in j["location"] for j in jobs)
        assert len(jobs) == 62

    async def test_filtered_page_does_not_stop_pagination(self, scraper):
        """Stop conditions must read raw_count, never the post-filter length."""
        page0 = _cards(100, 0, location=SG)  # every row filtered out
        pages = [_result(page0, raw_count=100), _result(_cards(3, 100))]
        with patch.object(
            tiktok_scraper_module, "fetch_search_results", AsyncMock(side_effect=pages)
        ) as fetch:
            jobs = await scraper.scrape_query("software engineer")
        assert fetch.await_count == 2, "a fully filtered page is not a short page"
        assert len(jobs) == 3

    async def test_non_technical_titles_dropped(self, scraper):
        page0 = _cards(50, 0) + _cards(50, 50, title="Technical Recruiter")
        pages = [_result(page0, raw_count=100), _result([], raw_count=0)]
        with patch.object(
            tiktok_scraper_module, "fetch_search_results", AsyncMock(side_effect=pages)
        ):
            jobs = await scraper.scrape_query("software engineer")
        assert len(jobs) == 50

    async def test_dedupes_across_pages(self, scraper):
        page0 = _cards(100)
        page1 = page0[80:] + _cards(80, 200)
        pages = [_result(page0), _result(page1, raw_count=100), _result([], raw_count=0)]
        with patch.object(
            tiktok_scraper_module, "fetch_search_results", AsyncMock(side_effect=pages)
        ):
            jobs = await scraper.scrape_query("software engineer")
        ids = [j["id"] for j in jobs]
        assert len(ids) == len(set(ids))
        assert len(jobs) == 180

    async def test_max_jobs_truncates(self, scraper):
        with patch.object(
            tiktok_scraper_module, "fetch_search_results",
            AsyncMock(side_effect=[_result(_cards(100))]),
        ) as fetch:
            jobs = await scraper.scrape_query("software engineer", max_jobs=25)
        assert len(jobs) == 25
        assert fetch.await_count == 1


@pytest.mark.asyncio
class TestPageCapAndSession:
    async def test_page_cap_raises_rather_than_shipping_a_truncated_run(self, scraper):
        """Exhausting the page budget means the board outgrew MAX_PAGES.

        Returning what was collected would silently drop the tail and let
        close-detection reap it, so this raises instead.
        """
        full = _result(_cards(100))
        with patch.object(tiktok_scraper_module, "MAX_PAGES", 3):
            with patch.object(
                tiktok_scraper_module, "fetch_search_results",
                AsyncMock(side_effect=[full, full, full]),
            ) as fetch:
                with pytest.raises(JobSearchError, match="MAX_PAGES"):
                    await scraper.scrape_query("software engineer")
        assert fetch.await_count == 3

    async def test_natural_stop_does_not_raise(self, scraper):
        """The clean end-of-results path must stay non-raising."""
        pages = [_result(_cards(100)), _result(_cards(2, 100))]
        with patch.object(
            tiktok_scraper_module, "fetch_search_results", AsyncMock(side_effect=pages)
        ):
            jobs = await scraper.scrape_query("software engineer")
        assert len(jobs) == 102

    async def test_establishes_same_origin_session_first(self, mock_context):
        """No CORS header on the API — the page must be on lifeattiktok.com."""
        s = TikTokJobsScraper(headless=True, detail_scrape=False)
        s.context = mock_context
        s._random_delay = AsyncMock()
        s.navigate_to_page = AsyncMock()

        with patch.object(
            tiktok_scraper_module, "fetch_search_results",
            AsyncMock(side_effect=[_result([], raw_count=0)]),
        ):
            with patch.object(tiktok_scraper_module.asyncio, "sleep", AsyncMock()):
                await s.scrape_query("software engineer")

        s.navigate_to_page.assert_awaited_once()
        assert s.navigate_to_page.await_args[0][1].startswith("https://lifeattiktok.com")
