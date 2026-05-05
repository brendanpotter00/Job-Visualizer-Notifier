"""
Unit tests for BaseScraper.initialize_browser defensive cleanup.

Verifies that when a later step of the three-step browser initialization
sequence (playwright.start -> chromium.launch -> browser.new_context) raises,
the partial state from earlier steps is torn down before the exception
propagates. Without this cleanup, Python's async-with would not call
__aexit__ (because __aenter__ raised), and the playwright driver / browser
would leak — causing PID/thread accumulation in long-running containers
(see docs/implementations/scraperPthreadExhaustionFix/PLAN.md).
"""

import pytest
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

from playwright.async_api import Page

from shared.base_scraper import BaseScraper


class _DummyScraper(BaseScraper):
    """
    Minimal concrete subclass of the abstract BaseScraper so we can
    instantiate it in tests. All abstract methods are no-ops since we
    only exercise initialize_browser here.
    """

    def get_company_name(self) -> str:
        return "dummy"

    def build_search_url(self, search_query: str, page_num: int) -> str:
        return "https://example.invalid/"

    async def extract_job_cards(self, page: Page) -> List[Dict[str, Any]]:
        return []

    async def extract_job_details(self, page: Page, job_url: str) -> Dict[str, Any]:
        return {}

    def get_search_queries(self) -> List[str]:
        return []


def _build_async_playwright_mock(
    *,
    launch_side_effect: Exception | None = None,
    new_context_side_effect: Exception | None = None,
):
    """
    Build a mock chain mirroring:

        playwright = await async_playwright().start()
        browser    = await playwright.chromium.launch(...)
        context    = await browser.new_context(...)

    Returns (async_playwright_callable, playwright_obj, browser_obj, context_obj)
    so individual mocks can be asserted on.
    """
    context_obj = MagicMock(name="context")

    browser_obj = MagicMock(name="browser")
    browser_obj.close = AsyncMock(name="browser.close")
    if new_context_side_effect is not None:
        browser_obj.new_context = AsyncMock(
            name="browser.new_context",
            side_effect=new_context_side_effect,
        )
    else:
        browser_obj.new_context = AsyncMock(
            name="browser.new_context",
            return_value=context_obj,
        )

    chromium_obj = MagicMock(name="chromium")
    if launch_side_effect is not None:
        chromium_obj.launch = AsyncMock(
            name="chromium.launch",
            side_effect=launch_side_effect,
        )
    else:
        chromium_obj.launch = AsyncMock(
            name="chromium.launch",
            return_value=browser_obj,
        )

    playwright_obj = MagicMock(name="playwright")
    playwright_obj.chromium = chromium_obj
    playwright_obj.stop = AsyncMock(name="playwright.stop")

    starter = MagicMock(name="async_playwright_starter")
    starter.start = AsyncMock(name="starter.start", return_value=playwright_obj)

    async_playwright_callable = MagicMock(
        name="async_playwright_callable",
        return_value=starter,
    )

    return async_playwright_callable, playwright_obj, browser_obj, context_obj


class TestInitializeBrowserCleanup:
    @pytest.mark.asyncio
    async def test_launch_failure_stops_playwright(self):
        """Case A: chromium.launch raises -> outer except cleans up playwright."""
        boom = RuntimeError("launch failed")
        async_pw, playwright_obj, browser_obj, _context_obj = (
            _build_async_playwright_mock(launch_side_effect=boom)
        )

        scraper = _DummyScraper(headless=True, detail_scrape=False)

        with patch("shared.base_scraper.async_playwright", async_pw):
            with pytest.raises(RuntimeError, match="launch failed"):
                await scraper.initialize_browser()

        playwright_obj.stop.assert_awaited_once()
        browser_obj.close.assert_not_called()
        assert scraper.playwright is None
        assert scraper.browser is None
        assert scraper.context is None

    @pytest.mark.asyncio
    async def test_new_context_failure_closes_browser_and_stops_playwright(self):
        """Case B: browser.new_context raises -> browser closed AND playwright stopped."""
        boom = RuntimeError("new_context failed")
        async_pw, playwright_obj, browser_obj, _context_obj = (
            _build_async_playwright_mock(new_context_side_effect=boom)
        )

        scraper = _DummyScraper(headless=True, detail_scrape=False)

        with patch("shared.base_scraper.async_playwright", async_pw):
            with pytest.raises(RuntimeError, match="new_context failed"):
                await scraper.initialize_browser()

        browser_obj.close.assert_awaited_once()
        playwright_obj.stop.assert_awaited_once()
        assert scraper.playwright is None
        assert scraper.browser is None
        assert scraper.context is None

    @pytest.mark.asyncio
    async def test_happy_path_no_cleanup(self):
        """Case C: all three steps succeed, no cleanup methods called, attrs populated."""
        async_pw, playwright_obj, browser_obj, context_obj = (
            _build_async_playwright_mock()
        )

        scraper = _DummyScraper(headless=True, detail_scrape=False)

        with patch("shared.base_scraper.async_playwright", async_pw):
            await scraper.initialize_browser()

        browser_obj.close.assert_not_called()
        playwright_obj.stop.assert_not_called()
        assert scraper.playwright is playwright_obj
        assert scraper.browser is browser_obj
        assert scraper.context is context_obj
