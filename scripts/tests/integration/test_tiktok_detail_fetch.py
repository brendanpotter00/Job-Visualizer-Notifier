"""Tests for the TikTok pass-through detail phase."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.batch_writer import BatchWriter
from tiktok_jobs_scraper.scraper import TikTokJobsScraper


@pytest.fixture
def scraper():
    s = TikTokJobsScraper(headless=True, detail_scrape=False)
    s.context = AsyncMock()
    s._random_delay = AsyncMock()
    return s


@pytest.mark.asyncio
class TestStreamingPassThrough:
    async def test_yields_cards_unchanged(self, scraper, sample_tiktok_job_data):
        cards = [sample_tiktok_job_data, dict(sample_tiktok_job_data, id="222")]
        assert [j async for j in scraper.scrape_job_details_streaming(cards)] == cards

    async def test_preserves_order(self, scraper):
        cards = [{"id": str(i), "title": f"j{i}"} for i in range(5)]
        out = [j async for j in scraper.scrape_job_details_streaming(cards)]
        assert [j["id"] for j in out] == ["0", "1", "2", "3", "4"]

    async def test_empty(self, scraper):
        assert [j async for j in scraper.scrape_job_details_streaming([])] == []

    async def test_opens_no_page_and_takes_no_delay(self, scraper, sample_tiktok_job_data):
        _ = [j async for j in scraper.scrape_job_details_streaming([sample_tiktok_job_data])]
        scraper.context.new_page.assert_not_called()
        scraper._random_delay.assert_not_awaited()

    async def test_cards_without_url_still_yielded(self, scraper):
        cards = [{"title": "no id or url"}]
        assert [j async for j in scraper.scrape_job_details_streaming(cards)] == cards

    async def test_batch_matches_streaming(self, scraper, sample_tiktok_job_data):
        assert await scraper.scrape_job_details_batch([sample_tiktok_job_data]) == [
            sample_tiktok_job_data
        ]


@pytest.mark.asyncio
class TestDetailsScrapedFlag:
    @pytest.mark.parametrize("detail_scrape", [True, False])
    async def test_flag_follows_batch_writer(self, sample_tiktok_job_data, detail_scrape):
        s = TikTokJobsScraper(headless=True, detail_scrape=detail_scrape)
        writer = BatchWriter(
            db_conn=MagicMock(), scraper=s, batch_size=50,
            detail_scrape=detail_scrape, use_upsert=True,
        )
        writer.add_job(sample_tiktok_job_data, "2026-08-09T00:00:00+00:00")
        assert writer.get_buffer_size() == 1
        buffered = writer._buffer[0]
        assert buffered.details_scraped is detail_scrape
        assert buffered.details["description"]
