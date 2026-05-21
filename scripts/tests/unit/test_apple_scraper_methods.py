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


class TestEnsureVerifierPage:
    """The Apple verifier-page setup is load-bearing for close-detection.

    Three branches that MUST be pinned:
      - Setup succeeds → registry has Apple verifier registered.
      - Setup fails (context.new_page raises, or navigate fails) →
        registry is empty for Apple, so the close path falls through to
        legacy threshold-only close-on-threshold instead of silently
        disabling all Apple closes (the verifier would otherwise return
        "unknown" for every call and unknown_policy="skip" would veto
        every close).
      - __aexit__ unregisters → next scraper instance in the same process
        sees a fresh registry rather than a leftover real-callable + None
        page combo.
    """

    @pytest.fixture(autouse=True)
    def _isolate_registry(self):
        """Per-test registry isolation. Each test starts with the
        import-time registration (Apple verifier present) and ends
        without contaminating sibling tests.
        """
        from shared.source_registry import (
            _VERIFIERS,
            clear_verifiers_for_testing,
            register_verifier,
        )
        from shared.constants import SourceId
        from apple_jobs_scraper.api_client import verify_url_alive

        snapshot = dict(_VERIFIERS)
        yield
        clear_verifiers_for_testing()
        for sid, verifier in snapshot.items():
            register_verifier(sid, verifier)

    @pytest.mark.asyncio
    async def test_setup_failure_unregisters_apple_verifier(self):
        """If _ensure_verifier_page can't create the page (new_page raises),
        the Apple verifier MUST be unregistered so process_missing_ids
        auto-selects unknown_policy="close" (legacy threshold-only) for
        the rest of the run instead of skipping every close.
        """
        from shared.constants import SourceId
        from shared.source_registry import get_verifier, _unknown_verifier

        scraper = AppleJobsScraper.__new__(AppleJobsScraper)
        scraper._verifier_page = None
        scraper.context = MagicMock()
        scraper.context.new_page = AsyncMock(
            side_effect=RuntimeError("playwright context torn down"),
        )

        await scraper._ensure_verifier_page()

        # Registry MUST fall back to the no-op fallback. Otherwise
        # has_verifier=True and every Apple close gets silently skipped.
        assert get_verifier(SourceId.APPLE) is _unknown_verifier

    @pytest.mark.asyncio
    async def test_setup_failure_keeps_verifier_page_none(self):
        """If _ensure_verifier_page raises after new_page succeeded but
        before navigate completed, the half-created page MUST be cleaned
        up so __aexit__'s teardown doesn't double-fault.
        """
        scraper = AppleJobsScraper.__new__(AppleJobsScraper)
        scraper._verifier_page = None
        scraper.context = MagicMock()
        half_created = MagicMock()
        half_created.close = AsyncMock()
        scraper.context.new_page = AsyncMock(return_value=half_created)
        scraper.navigate_to_page = AsyncMock(
            side_effect=RuntimeError("navigation failed"),
        )

        await scraper._ensure_verifier_page()

        assert scraper._verifier_page is None
        half_created.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_setup_success_keeps_verifier_registered(self):
        """Happy path: new_page + navigate both succeed → registry retains
        the real Apple verifier. (Also pins the re-arm-after-prior-failure
        contract on line ~150 of scraper.py.)
        """
        from shared.constants import SourceId
        from shared.source_registry import get_verifier, _unknown_verifier

        scraper = AppleJobsScraper.__new__(AppleJobsScraper)
        scraper._verifier_page = None
        scraper.context = MagicMock()
        page = MagicMock()
        scraper.context.new_page = AsyncMock(return_value=page)
        scraper.navigate_to_page = AsyncMock()

        await scraper._ensure_verifier_page()

        assert scraper._verifier_page is page
        assert get_verifier(SourceId.APPLE) is not _unknown_verifier
