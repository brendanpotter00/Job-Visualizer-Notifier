"""
Tests for the Amazon pass-through detail phase.

Amazon's list payload already carries the description, so
``scrape_job_details_streaming`` must yield cards untouched and — critically —
must NOT open a page or sleep. The BaseScraper default would do both, once per
job, which for a ~1,300 job board is 45-110 minutes of pure waiting.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from amazon_jobs_scraper.scraper import AmazonJobsScraper
from shared.batch_writer import BatchWriter


@pytest.fixture
def scraper():
    s = AmazonJobsScraper(headless=True, detail_scrape=False)
    s.context = AsyncMock()
    s._random_delay = AsyncMock()
    return s


@pytest.mark.asyncio
class TestStreamingPassThrough:
    async def test_yields_cards_unchanged(self, scraper, sample_amazon_job_data):
        cards = [sample_amazon_job_data, dict(sample_amazon_job_data, id="222")]
        out = [j async for j in scraper.scrape_job_details_streaming(cards)]
        assert out == cards

    async def test_preserves_order(self, scraper):
        cards = [{"id": str(i), "title": f"j{i}"} for i in range(5)]
        out = [j async for j in scraper.scrape_job_details_streaming(cards)]
        assert [j["id"] for j in out] == ["0", "1", "2", "3", "4"]

    async def test_empty_input(self, scraper):
        assert [j async for j in scraper.scrape_job_details_streaming([])] == []

    async def test_opens_no_page_and_takes_no_delay(self, scraper, sample_amazon_job_data):
        """The performance contract, asserted rather than assumed."""
        _ = [j async for j in scraper.scrape_job_details_streaming([sample_amazon_job_data])]
        scraper.context.new_page.assert_not_called()
        scraper._random_delay.assert_not_awaited()

    async def test_cards_without_url_or_id_still_yielded(self, scraper):
        """Unlike the base class, nothing is skipped for a missing job_url."""
        cards = [{"title": "no id or url"}]
        out = [j async for j in scraper.scrape_job_details_streaming(cards)]
        assert out == cards

    async def test_batch_form_matches_streaming(self, scraper, sample_amazon_job_data):
        cards = [sample_amazon_job_data]
        assert await scraper.scrape_job_details_batch(cards) == cards


@pytest.mark.asyncio
class TestDetailsScrapedFlag:
    """BatchWriter overwrites details_scraped with its own detail_scrape value.

    Pinned so the flag/reality relationship is a decision rather than a
    surprise: the description is present either way, because it arrives in the
    list payload.
    """

    @pytest.mark.parametrize("detail_scrape", [True, False])
    async def test_flag_follows_batch_writer_not_the_transform(
        self, sample_amazon_job_data, detail_scrape
    ):
        s = AmazonJobsScraper(headless=True, detail_scrape=detail_scrape)
        writer = BatchWriter(
            db_conn=MagicMock(),
            scraper=s,
            batch_size=50,
            detail_scrape=detail_scrape,
            use_upsert=True,
        )
        writer.add_job(sample_amazon_job_data, "2026-08-09T00:00:00+00:00")

        assert writer.get_buffer_size() == 1
        buffered = writer._buffer[0]
        assert buffered.details_scraped is detail_scrape
        # The description is present regardless of the flag.
        assert buffered.details["description"]
