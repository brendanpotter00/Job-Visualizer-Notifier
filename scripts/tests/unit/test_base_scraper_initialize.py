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
        # Pin exception identity so a future regression that catches and
        # re-raises a fresh instance would fail (matching the rigor of the
        # cleanup-handler-raises tests).
        assert excinfo.value is exc

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

        # Pin identity (see Case A above for rationale).
        assert excinfo.value is exc

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
    async def test_playwright_stop_hangs_does_not_block_forever(
        self, caplog, monkeypatch
    ):
        """If playwright.stop hangs, asyncio.wait_for must time it out. The
        original launch exception still propagates, self.playwright is None,
        and the timeout surfaces in logs. Bound the test itself with
        asyncio.wait_for so a regression doesn't hang CI.

        Pins production wait_for actually firing by:
          (a) overriding PLAYWRIGHT_STOP_TIMEOUT to 0.5s via monkeypatch
              (timeout fires almost immediately instead of waiting 15s); and
          (b) asserting caplog records a TimeoutError, which can only be
              produced by asyncio.wait_for actually firing — a regression
              that removes the wait_for would log the underlying hang
              forever and time out the outer 2s bound instead.
        """
        # Override the production timeout so the test exercises the real
        # wait_for code path on a fast budget. If a future refactor removes
        # the wait_for, the inner _hang() would block past the 2s outer
        # bound and fail loudly via TimeoutError on _run().
        monkeypatch.setattr(
            "shared.base_scraper.PLAYWRIGHT_STOP_TIMEOUT", 0.5
        )

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
            # Bound the whole test below the would-be-hang sleep (60s) but
            # well above the patched production timeout (0.5s) so the
            # production wait_for has time to fire and log before this
            # outer guard would. A regression that removes the wait_for
            # would hit this 2s bound and fail with TimeoutError.
            await asyncio.wait_for(_run(), timeout=2.0)

        # finally clause must still null the attribute even though stop hung.
        assert scraper.playwright is None
        # Cleanup-failure log captures the wait_for TimeoutError.
        assert any(
            "playwright.stop() failed" in record.getMessage()
            and record.levelno >= logging.ERROR
            for record in caplog.records
        ), f"Expected error log for playwright.stop timeout; got: {caplog.records!r}"
        # Pin that the production wait_for actually fired (not just that
        # _some_ cleanup error was logged): the captured cleanup_exc must
        # be a TimeoutError, which only asyncio.wait_for produces in this
        # path. A regression that drops wait_for would record the
        # never-completing hang as a different exception type (or never
        # log at all).
        assert any(
            "TimeoutError" in record.getMessage()
            and record.levelno >= logging.ERROR
            for record in caplog.records
        ), (
            "Expected TimeoutError reference in cleanup-failure log "
            "(proves asyncio.wait_for fired); got: "
            f"{[r.getMessage() for r in caplog.records]!r}"
        )


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


def _populate_scraper_with_mocks(
    *,
    context_close_side_effect: BaseException | None = None,
    browser_close_side_effect: BaseException | None = None,
    playwright_stop_side_effect: BaseException | None = None,
):
    """Build a scraper whose three live handles are AsyncMock-backed so
    close_browser exercises the real per-step hardening code without
    needing to run initialize_browser first.

    Returns (scraper, context_mock, browser_mock, playwright_mock)
    so tests can assert on the underlying close/stop AsyncMocks.
    """
    context_mock = MagicMock(name="context")
    if context_close_side_effect is not None:
        context_mock.close = AsyncMock(
            name="context.close", side_effect=context_close_side_effect
        )
    else:
        context_mock.close = AsyncMock(name="context.close")

    browser_mock = MagicMock(name="browser")
    if browser_close_side_effect is not None:
        browser_mock.close = AsyncMock(
            name="browser.close", side_effect=browser_close_side_effect
        )
    else:
        browser_mock.close = AsyncMock(name="browser.close")

    playwright_mock = MagicMock(name="playwright")
    if playwright_stop_side_effect is not None:
        playwright_mock.stop = AsyncMock(
            name="playwright.stop", side_effect=playwright_stop_side_effect
        )
    else:
        playwright_mock.stop = AsyncMock(name="playwright.stop")

    scraper = _DummyScraper(headless=True, detail_scrape=False)
    scraper.context = context_mock
    scraper.browser = browser_mock
    scraper.playwright = playwright_mock
    return scraper, context_mock, browser_mock, playwright_mock


class TestCloseBrowserStepHardening:
    """
    Pin the close_browser per-step hardening contract:

      * If any one of (context.close, browser.close, playwright.stop)
        raises, the subsequent steps STILL run (do-not-revert S1 contract).
      * The failure is logged at error level.
      * close_browser does NOT re-raise the failure.
      * All three attributes are None afterward (Fix 1: per-step finally
        nulling).
      * A subsequent close_browser call is a no-op (no awaits attempted on
        already-None handles), proving Fix 1 prevents stale-handle
        re-attempts.
      * Cancellation propagation (Fix 2): CancelledError caught at any
        step is re-raised AFTER all subsequent steps run.
      * Conditional success log (Fix 3): INFO "Browser closed" only when
        no step failed; WARNING otherwise.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "failing_step",
        ["context", "browser", "playwright"],
    )
    async def test_step_failure_runs_subsequent_steps(
        self, failing_step, caplog
    ):
        """For each of the three steps, raising RuntimeError must NOT abort
        the teardown — the remaining close/stop awaits still run, the
        failure is logged at error, close_browser returns normally (no
        re-raise), and all three attributes are nulled."""
        kwargs = {
            f"{failing_step}_close_side_effect"
            if failing_step != "playwright"
            else "playwright_stop_side_effect": RuntimeError(f"{failing_step} failed"),
        }
        scraper, ctx, br, pw = _populate_scraper_with_mocks(**kwargs)

        with caplog.at_level(logging.ERROR, logger="shared.base_scraper"):
            # Must not re-raise; runtime failures are logged and swallowed.
            await scraper.close_browser()

        # All three steps ran regardless of which one failed.
        ctx.close.assert_awaited_once()
        br.close.assert_awaited_once()
        pw.stop.assert_awaited_once()

        # Per-step finally nulled all three attributes (Fix 1).
        assert scraper.context is None
        assert scraper.browser is None
        assert scraper.playwright is None

        # Failure was logged at error level.
        method_name = "close" if failing_step != "playwright" else "stop"
        expected_substr = f"{failing_step}.{method_name}() failed"
        assert any(
            expected_substr in record.getMessage()
            and record.levelno >= logging.ERROR
            for record in caplog.records
        ), (
            f"Expected error log matching {expected_substr!r}; got: "
            f"{[r.getMessage() for r in caplog.records]!r}"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "step_index",
        [0, 1, 2],
        ids=["context", "browser", "playwright"],
    )
    @pytest.mark.parametrize(
        "exc_type",
        [asyncio.CancelledError, KeyboardInterrupt],
        ids=["CancelledError", "KeyboardInterrupt"],
    )
    async def test_cancellation_at_step_runs_remaining_then_re_raises(
        self, step_index, exc_type, caplog
    ):
        """Cancellation × all-three-steps × (CancelledError, KeyboardInterrupt).

        For each combination: the cancellation at the chosen step must
        NOT abort teardown — every subsequent close/stop AsyncMock still
        runs (do-not-revert contract: subsequent awaits MUST run even if
        an earlier one fails), and the cancellation propagates out of
        close_browser AFTER all three steps have finished. Per-step
        finally nulling held in all cases.

        pending_cancellation overwrites with the most-recent across the
        three steps, so when only one step raises we re-raise that one;
        the parametrize sweep pins propagation regardless of which step
        is the cancellation source.
        """
        kwargs: dict[str, BaseException] = {}
        side_effect_keys = (
            "context_close_side_effect",
            "browser_close_side_effect",
            "playwright_stop_side_effect",
        )
        kwargs[side_effect_keys[step_index]] = exc_type()

        scraper, ctx, br, pw = _populate_scraper_with_mocks(**kwargs)

        with caplog.at_level(logging.ERROR, logger="shared.base_scraper"):
            with pytest.raises(exc_type):
                await scraper.close_browser()

        # All three steps still ran despite the cancellation at step_index.
        ctx.close.assert_awaited_once()
        br.close.assert_awaited_once()
        pw.stop.assert_awaited_once()

        # Per-step finally nulled all three attributes.
        assert scraper.context is None
        assert scraper.browser is None
        assert scraper.playwright is None

    @pytest.mark.asyncio
    async def test_double_close_browser_is_no_op(self, caplog):
        """First call tears down all three handles cleanly. Second call
        finds all attributes None, runs no awaits, and does not log a
        spurious error — proving Fix 1's per-step nulling prevents
        stale-handle re-attempts (the asymmetry that motivated this fix)."""
        scraper, ctx, br, pw = _populate_scraper_with_mocks()

        await scraper.close_browser()

        ctx.close.assert_awaited_once()
        br.close.assert_awaited_once()
        pw.stop.assert_awaited_once()
        assert scraper.context is None
        assert scraper.browser is None
        assert scraper.playwright is None

        # Second call: must be a complete no-op. Reset call counts on the
        # underlying mocks (still reachable via local refs) so we can
        # confirm no further awaits are attempted.
        ctx.close.reset_mock()
        br.close.reset_mock()
        pw.stop.reset_mock()

        with caplog.at_level(logging.ERROR, logger="shared.base_scraper"):
            await scraper.close_browser()

        ctx.close.assert_not_called()
        br.close.assert_not_called()
        pw.stop.assert_not_called()
        # No error logs — null-check short-circuits each branch.
        assert not [
            r for r in caplog.records if r.levelno >= logging.ERROR
        ], f"Expected no error logs on no-op double close; got: {caplog.records!r}"

    @pytest.mark.asyncio
    async def test_double_close_browser_emits_no_logs(self, caplog):
        """Strict tightening of test_double_close_browser_is_no_op: the
        second call (with all attrs already None from the first call's
        per-step finally nulling) must emit NO log records at INFO level
        or higher.

        The existing no-op test only asserted no ERROR-level records;
        this one pins the new attempted_anything gate from Fix 3 — a
        regression that re-introduces unconditional INFO 'Browser
        closed' on no-op double-close would re-introduce the false-
        positive shutdown signal that misleads operators."""
        scraper, ctx, br, pw = _populate_scraper_with_mocks()

        # First call with attrs populated → INFO 'Browser closed' fires.
        with caplog.at_level(logging.INFO, logger="shared.base_scraper"):
            await scraper.close_browser()
        first_call_records = list(caplog.records)
        first_call_info = [
            r for r in first_call_records
            if r.levelno == logging.INFO and "Browser closed" in r.getMessage()
        ]
        assert first_call_info, (
            "Expected first close_browser call (with populated handles) "
            "to emit INFO 'Browser closed'; got: "
            f"{[(r.levelname, r.getMessage()) for r in first_call_records]!r}"
        )

        # Reset captured records so we can isolate what the second call emits.
        caplog.clear()

        # Second call: all three attrs are None, attempted_anything stays
        # False, so the function returns early before any log line.
        with caplog.at_level(logging.INFO, logger="shared.base_scraper"):
            await scraper.close_browser()

        # Second call must emit NO records at INFO or higher.
        second_call_high_records = [
            r for r in caplog.records if r.levelno >= logging.INFO
        ]
        assert not second_call_high_records, (
            "No-op double-close must emit no INFO/WARNING/ERROR records "
            "(attempted_anything gate from Fix 3); got: "
            f"{[(r.levelname, r.getMessage()) for r in second_call_high_records]!r}"
        )

        # Sanity: no awaits attempted on already-None handles.
        ctx.close.assert_awaited_once()  # only the first call
        br.close.assert_awaited_once()
        pw.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_success_logs_info_browser_closed(self, caplog):
        """Fix 3: when no step fails, INFO 'Browser closed' fires (not
        the WARNING fallback)."""
        scraper, ctx, br, pw = _populate_scraper_with_mocks()

        with caplog.at_level(logging.DEBUG, logger="shared.base_scraper"):
            await scraper.close_browser()

        info_records = [
            r for r in caplog.records
            if r.levelno == logging.INFO and "Browser closed" in r.getMessage()
        ]
        warning_records = [
            r for r in caplog.records
            if r.levelno == logging.WARNING
            and "teardown finished with errors" in r.getMessage()
        ]
        assert info_records, (
            f"Expected INFO 'Browser closed' log on clean teardown; got: "
            f"{[(r.levelname, r.getMessage()) for r in caplog.records]!r}"
        )
        assert not warning_records, (
            f"Did NOT expect WARNING fallback log on clean teardown; got: "
            f"{[(r.levelname, r.getMessage()) for r in caplog.records]!r}"
        )

    @pytest.mark.asyncio
    async def test_failure_logs_warning_not_info(self, caplog):
        """Fix 3: when any step fails, WARNING 'teardown finished with
        errors above' fires INSTEAD of INFO 'Browser closed' — so
        operators don't see a misleading clean-shutdown signal."""
        scraper, ctx, br, pw = _populate_scraper_with_mocks(
            browser_close_side_effect=RuntimeError("browser failed"),
        )

        with caplog.at_level(logging.DEBUG, logger="shared.base_scraper"):
            await scraper.close_browser()

        warning_records = [
            r for r in caplog.records
            if r.levelno == logging.WARNING
            and "teardown finished with errors" in r.getMessage()
        ]
        info_records = [
            r for r in caplog.records
            if r.levelno == logging.INFO and "Browser closed" in r.getMessage()
        ]
        assert warning_records, (
            f"Expected WARNING fallback log when a step fails; got: "
            f"{[(r.levelname, r.getMessage()) for r in caplog.records]!r}"
        )
        assert not info_records, (
            f"Did NOT expect INFO 'Browser closed' (lying success log) "
            f"when a step failed; got: "
            f"{[(r.levelname, r.getMessage()) for r in caplog.records]!r}"
        )
