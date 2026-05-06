"""
Unit tests for AppleJobsScraper methods that override BaseScraper behavior.

These pin behavioral choices that don't have a fixture-level test elsewhere —
in particular the Apple-specific page.goto strategy, which is load-bearing for
the appleScraperHangFix work (see docs/implementations/appleScraperHangFix/PLAN.md).
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from apple_jobs_scraper.scraper import AppleJobsScraper, _APPLE_GOTO_WAIT_UNTIL


@pytest.fixture
def scraper():
    """AppleJobsScraper with __init__ skipped — we only need methods."""
    return AppleJobsScraper.__new__(AppleJobsScraper)


@pytest.fixture
def page():
    p = MagicMock()
    p.goto = AsyncMock()
    return p


class TestNavigateToPage:
    """The Apple `navigate_to_page` override is the load-bearing override
    for the page.goto strategy: networkidle never fires within 30 s on
    Apple's analytics-chatty careers site, so we go straight to
    domcontentloaded. A regression that drops this override (e.g. someone
    deleting the method "because the base class works") would silently
    re-introduce ~30 s of dead time per pagination step."""

    def test_apple_wait_until_constant_is_domcontentloaded(self):
        """Pin the constant value so the test below catches a sneaky
        constant rename without changing this assertion."""
        assert _APPLE_GOTO_WAIT_UNTIL == "domcontentloaded"

    @pytest.mark.asyncio
    async def test_navigate_to_page_uses_domcontentloaded(self, scraper, page):
        await scraper.navigate_to_page(page, "https://jobs.apple.com/x", timeout=30000)

        page.goto.assert_awaited_once()
        kwargs = page.goto.call_args.kwargs
        assert kwargs["wait_until"] == "domcontentloaded"
        assert kwargs["timeout"] == 30000

    @pytest.mark.asyncio
    async def test_navigate_to_page_passes_through_timeout(self, scraper, page):
        await scraper.navigate_to_page(page, "https://jobs.apple.com/x", timeout=12345)

        kwargs = page.goto.call_args.kwargs
        assert kwargs["timeout"] == 12345

    @pytest.mark.asyncio
    async def test_navigate_to_page_retries_once_on_first_failure(self, scraper, page):
        """Mirrors BaseScraper.navigate_to_page: a single retry survives
        transient TLS/connection blips. Without the retry,
        scrape_query's outer consecutive_errors loop walks to the next
        page number and silently drops the failed page's ~20 jobs.
        """
        attempts = {"n": 0}

        async def _goto(*args, **kwargs):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("transient TLS blip")

        page.goto = AsyncMock(side_effect=_goto)

        await scraper.navigate_to_page(page, "https://jobs.apple.com/x")

        assert attempts["n"] == 2
        # Both attempts use the same wait_until — Apple's analytics chatter
        # makes networkidle-then-domcontentloaded a non-strategy here.
        for call in page.goto.call_args_list:
            assert call.kwargs["wait_until"] == "domcontentloaded"

    @pytest.mark.asyncio
    async def test_navigate_to_page_propagates_second_failure(self, scraper, page):
        """If both attempts fail, the exception must reach `scrape_query`
        so its consecutive_errors loop can record and bound the failure.
        Swallowing it here would let the scraper proceed against an
        unloaded page and produce empty job extractions silently.
        """
        page.goto = AsyncMock(side_effect=RuntimeError("connection refused"))

        with pytest.raises(RuntimeError, match="connection refused"):
            await scraper.navigate_to_page(page, "https://jobs.apple.com/x")

        assert page.goto.await_count == 2
