"""
Unit tests for BaseScraper.initialize_browser defensive cleanup.

Verifies that when a later step of the three-step browser initialization
sequence (playwright.start -> chromium.launch -> browser.new_context) raises,
the partial state from earlier steps is torn down before the exception
propagates. Without this cleanup, Python's async-with would not call
__aexit__ (because __aenter__ raised), and the playwright driver / browser
would leak — causing PID/thread accumulation in long-running containers
(see docs/implementations/scraperPthreadExhaustionFix/PLAN.md).

Also pins the post-pass-1 contract: cleanup awaits are themselves wrapped
in try/except BaseException + asyncio.wait_for, attribute nulling lives in
finally, and a secondary failure (or hang) during cleanup must NOT mask
the original exception.
"""

import asyncio
import logging

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
    launch_side_effect: BaseException | None = None,
    new_context_side_effect: BaseException | None = None,
    browser_close_side_effect: BaseException | None = None,
    playwright_stop_side_effect: BaseException | None = None,
):
    """
    Build a mock chain mirroring:

        playwright = await async_playwright().start()
        browser    = await playwright.chromium.launch(...)
        context    = await browser.new_context(...)

    Cleanup methods (browser.close, playwright.stop) are also mockable so
    we can pin behavior when they themselves raise or hang.

    Returns (async_playwright_callable, playwright_obj, browser_obj, context_obj)
    so individual mocks can be asserted on.
    """
    context_obj = MagicMock(name="context")

    browser_obj = MagicMock(name="browser")
    if browser_close_side_effect is not None:
        browser_obj.close = AsyncMock(
            name="browser.close",
            side_effect=browser_close_side_effect,
        )
    else:
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
    if playwright_stop_side_effect is not None:
        playwright_obj.stop = AsyncMock(
            name="playwright.stop",
            side_effect=playwright_stop_side_effect,
        )
    else:
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
    @pytest.mark.parametrize(
        "exc",
        [
            RuntimeError("launch failed"),
            asyncio.CancelledError(),
        ],
        ids=["RuntimeError", "CancelledError"],
    )
    async def test_launch_failure_stops_playwright(self, exc):
        """Case A: chromium.launch raises -> outer except cleans up playwright.

        Parametrized over both Exception and BaseException-tier failures
        (CancelledError) to lock in the BaseException contract — a future
        refactor that tightens to `except Exception` would silently re-leak
        under cancellation.
        """
        async_pw, playwright_obj, browser_obj, _context_obj = (
            _build_async_playwright_mock(launch_side_effect=exc)
        )

        scraper = _DummyScraper(headless=True, detail_scrape=False)

        with patch("shared.base_scraper.async_playwright", async_pw):
            with pytest.raises(type(exc)) as excinfo:
                await scraper.initialize_browser()

        # The original exception must propagate, not whatever the cleanup did.
        if isinstance(exc, asyncio.CancelledError):
            assert isinstance(excinfo.value, asyncio.CancelledError)
        else:
            assert str(excinfo.value) == "launch failed"

        playwright_obj.stop.assert_awaited_once()
        browser_obj.close.assert_not_called()
        assert scraper.playwright is None
        assert scraper.browser is None
        assert scraper.context is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "exc",
        [
            RuntimeError("new_context failed"),
            asyncio.CancelledError(),
        ],
        ids=["RuntimeError", "CancelledError"],
    )
    async def test_new_context_failure_closes_browser_and_stops_playwright(self, exc):
        """Case B: browser.new_context raises -> browser closed AND playwright stopped.

        Parametrized over Exception and CancelledError for the same reason as
        Case A.
        """
        async_pw, playwright_obj, browser_obj, _context_obj = (
            _build_async_playwright_mock(new_context_side_effect=exc)
        )

        scraper = _DummyScraper(headless=True, detail_scrape=False)

        with patch("shared.base_scraper.async_playwright", async_pw):
            with pytest.raises(type(exc)) as excinfo:
                await scraper.initialize_browser()

        if isinstance(exc, asyncio.CancelledError):
            assert isinstance(excinfo.value, asyncio.CancelledError)
        else:
            assert str(excinfo.value) == "new_context failed"

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


class TestInitializeBrowserCleanupHandlerRaises:
    """
    Pin the post-pass-1 contract: when the cleanup itself fails (raises or
    hangs), the ORIGINAL exception still propagates, attribute nulling in
    `finally` still runs, and the cleanup failure is logged at error-level.
    Without these guarantees a secondary failure would silently mask the
    real diagnostic.
    """

    @pytest.mark.asyncio
    async def test_launch_failure_with_playwright_stop_also_raising(self, caplog):
        """If chromium.launch raises AND playwright.stop also raises, the original
        exception propagates, self.playwright is None, and the cleanup
        failure is logged at error level."""
        original = RuntimeError("launch failed")
        cleanup = RuntimeError("stop failed")
        async_pw, playwright_obj, browser_obj, _context_obj = (
            _build_async_playwright_mock(
                launch_side_effect=original,
                playwright_stop_side_effect=cleanup,
            )
        )

        scraper = _DummyScraper(headless=True, detail_scrape=False)

        with caplog.at_level(logging.ERROR, logger="shared.base_scraper"):
            with patch("shared.base_scraper.async_playwright", async_pw):
                with pytest.raises(RuntimeError, match="launch failed") as excinfo:
                    await scraper.initialize_browser()

        # The original exception, not the cleanup exception, propagates.
        assert excinfo.value is original
        # finally guarantees attribute is nulled even when cleanup raised.
        assert scraper.playwright is None
        assert scraper.browser is None
        assert scraper.context is None
        # Cleanup failure was logged.
        assert any(
            "playwright.stop() failed" in record.getMessage()
            and record.levelno >= logging.ERROR
            for record in caplog.records
        ), f"Expected error log for playwright.stop failure; got: {caplog.records!r}"

    @pytest.mark.asyncio
    async def test_new_context_failure_with_browser_close_also_raising(self, caplog):
        """If new_context raises AND browser.close also raises, the original
        exception propagates, both browser and playwright attributes are
        nulled, and the cleanup failure is logged."""
        original = RuntimeError("new_context failed")
        cleanup = RuntimeError("close failed")
        async_pw, playwright_obj, browser_obj, _context_obj = (
            _build_async_playwright_mock(
                new_context_side_effect=original,
                browser_close_side_effect=cleanup,
            )
        )

        scraper = _DummyScraper(headless=True, detail_scrape=False)

        with caplog.at_level(logging.ERROR, logger="shared.base_scraper"):
            with patch("shared.base_scraper.async_playwright", async_pw):
                with pytest.raises(RuntimeError, match="new_context failed") as excinfo:
                    await scraper.initialize_browser()

        assert excinfo.value is original
        assert scraper.browser is None
        assert scraper.playwright is None
        assert scraper.context is None
        # browser.close failure logged; playwright.stop still ran successfully.
        assert any(
            "browser.close() failed" in record.getMessage()
            and record.levelno >= logging.ERROR
            for record in caplog.records
        ), f"Expected error log for browser.close failure; got: {caplog.records!r}"
        playwright_obj.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_playwright_stop_hangs_does_not_block_forever(self, caplog):
        """If playwright.stop hangs, asyncio.wait_for must time it out. The
        original launch exception still propagates, self.playwright is None,
        and the timeout surfaces in logs. Bound the test itself with
        asyncio.wait_for so a regression doesn't hang CI."""
        original = RuntimeError("launch failed")

        async def _hang():
            await asyncio.sleep(60)

        async_pw, playwright_obj, browser_obj, _context_obj = (
            _build_async_playwright_mock(launch_side_effect=original)
        )
        # Override stop to actually hang (the helper accepts a side_effect
        # that is a callable returning a coroutine when used with AsyncMock).
        playwright_obj.stop = AsyncMock(name="playwright.stop", side_effect=_hang)

        scraper = _DummyScraper(headless=True, detail_scrape=False)

        async def _run():
            with patch("shared.base_scraper.async_playwright", async_pw):
                with pytest.raises(RuntimeError, match="launch failed") as excinfo:
                    await scraper.initialize_browser()
            # Original exception propagates, not TimeoutError.
            assert excinfo.value is original

        with caplog.at_level(logging.ERROR, logger="shared.base_scraper"):
            # Bound the whole test under wait_for so a regression that
            # actually blocks fails fast instead of hanging CI.
            await asyncio.wait_for(_run(), timeout=20.0)

        # finally clause must still null the attribute even though stop hung.
        assert scraper.playwright is None
        # Cleanup-failure log captures the wait_for TimeoutError.
        assert any(
            "playwright.stop() failed" in record.getMessage()
            and record.levelno >= logging.ERROR
            for record in caplog.records
        ), f"Expected error log for playwright.stop timeout; got: {caplog.records!r}"


class TestInitializeBrowserAsyncWithPropagation:
    """
    Pin the language-contract guarantee that __aexit__ is NOT called when
    __aenter__ raises. The whole defensive-cleanup architecture depends on
    this; if a future Python or pytest-asyncio change ever broke it, the
    in-init cleanup we added would still fire, but the contract test would
    catch any drift in expectations.
    """

    @pytest.mark.asyncio
    async def test_aenter_failure_does_not_call_aexit(self):
        """When chromium.launch raises inside __aenter__, the exception
        propagates out of `async with`, __aexit__ is NOT called, and yet
        all attributes are still None because initialize_browser's own
        finally clauses cleaned up.
        """
        original = RuntimeError("launch failed")
        async_pw, playwright_obj, browser_obj, _context_obj = (
            _build_async_playwright_mock(launch_side_effect=original)
        )

        aexit_mock = AsyncMock(name="__aexit__", return_value=None)

        with patch("shared.base_scraper.async_playwright", async_pw):
            with patch.object(_DummyScraper, "__aexit__", aexit_mock):
                with pytest.raises(RuntimeError, match="launch failed"):
                    async with _DummyScraper(headless=True, detail_scrape=False) as _scraper:
                        # Body should never execute; __aenter__ raised.
                        pytest.fail("async-with body ran despite __aenter__ raising")

        # Language contract: __aexit__ MUST NOT be called when __aenter__ raises.
        aexit_mock.assert_not_called()
        # Defense-in-depth: in-init cleanup still ran (playwright stopped).
        playwright_obj.stop.assert_awaited_once()


class TestCloseBrowserAfterPartialInit:
    """
    A subprocess wrapper might catch the init exception and explicitly call
    close_browser as a belt-and-suspenders teardown. After our fix,
    close_browser must be safe (no-op) because attribute nulling in
    initialize_browser's finally already ran.
    """

    @pytest.mark.asyncio
    async def test_close_browser_after_launch_failure_is_safe(self):
        original = RuntimeError("launch failed")
        async_pw, playwright_obj, browser_obj, _context_obj = (
            _build_async_playwright_mock(launch_side_effect=original)
        )

        scraper = _DummyScraper(headless=True, detail_scrape=False)

        with patch("shared.base_scraper.async_playwright", async_pw):
            with pytest.raises(RuntimeError, match="launch failed"):
                await scraper.initialize_browser()

        # Should not raise — all attributes are None, close_browser's
        # null-checks short-circuit each branch.
        await scraper.close_browser()

        # Defensive: confirm no double-stop was attempted.
        playwright_obj.stop.assert_awaited_once()  # only the in-init cleanup
        browser_obj.close.assert_not_called()
