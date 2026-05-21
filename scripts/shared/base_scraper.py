"""
Abstract base class for company-specific scrapers

Provides shared browser automation, rate limiting, and transformation logic.
Company-specific scrapers extend this class and implement abstract methods.
"""

import logging
import asyncio
import random
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, AsyncIterator
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

logger = logging.getLogger(__name__)

# Browser configuration for anti-detection
BROWSER_CONFIG = {
    "viewport": {"width": 1920, "height": 1080},
    "user_agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "locale": "en-US",
}

# Cleanup-await timeouts (seconds). Module-level so tests can override them
# without changing function signatures. Production values are picked to be
# generous enough that a healthy teardown never times out, while still
# bounded so a hung Playwright driver under PID exhaustion surfaces as
# TimeoutError instead of blocking the scraper subprocess indefinitely.
CONTEXT_CLOSE_TIMEOUT = 5.0
BROWSER_CLOSE_TIMEOUT = 10.0
PLAYWRIGHT_STOP_TIMEOUT = 15.0

assert (
    CONTEXT_CLOSE_TIMEOUT > 0
    and BROWSER_CLOSE_TIMEOUT > 0
    and PLAYWRIGHT_STOP_TIMEOUT > 0
), (
    "Cleanup timeouts must be positive; use a large value to disable, "
    "not 0 or negative (which causes asyncio.wait_for to fire instantly)"
)


def _safe_log_cleanup_failure(message: str, *args) -> None:
    """Log a cleanup failure without ever raising back to the caller.

    Cleanup blocks must complete the per-step finally + pending-cancellation
    re-raise contract even if the logging subsystem itself fails (full disk
    on a FileHandler, socket dropout on a RemoteHandler, etc.). Swallowing
    logger errors is the right tradeoff: a missing log line is preferable
    to a missed cancellation re-raise.
    """
    try:
        logger.error(message, *args)
    except Exception:
        pass


class BaseScraper(ABC):
    """
    Abstract base class for all company scrapers

    Subclasses must implement:
    - get_company_name(): Return company identifier (e.g., "google")
    - build_search_url(): Build URL for search query and page number
    - extract_job_cards(): Extract job listings from search results page
    - extract_job_details(): Extract detailed info from job detail page (optional)
    """

    def __init__(self, headless: bool = True, detail_scrape: bool = False):
        """
        Initialize scraper

        Args:
            headless: Run browser in headless mode
            detail_scrape: Whether to scrape individual job detail pages
        """
        self.headless = headless
        self.detail_scrape = detail_scrape
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None

    # ========== Abstract Methods (must be implemented by subclasses) ==========

    @abstractmethod
    def get_company_name(self) -> str:
        """
        Return company identifier (e.g., "google", "apple")

        Returns:
            Company name string
        """
        pass

    @abstractmethod
    def build_search_url(self, search_query: str, page_num: int) -> str:
        """
        Build company-specific search URL

        Args:
            search_query: Search term (e.g., "software engineer")
            page_num: Page number (1-indexed)

        Returns:
            Full URL string
        """
        pass

    @abstractmethod
    async def extract_job_cards(self, page: Page) -> List[Dict[str, Any]]:
        """
        Extract job listings from search results page

        Args:
            page: Playwright page object

        Returns:
            List of job dictionaries with basic info (id, title, url, location)
        """
        pass

    @abstractmethod
    async def extract_job_details(self, page: Page, job_url: str) -> Dict[str, Any]:
        """
        Extract detailed information from job detail page

        Args:
            page: Playwright page object
            job_url: URL of job detail page

        Returns:
            Dictionary with detailed job info (qualifications, description, etc.)
        """
        pass

    @abstractmethod
    def get_search_queries(self) -> List[str]:
        """
        Return list of search queries for this company

        Returns:
            List of search query strings
        """
        pass

    def filter_job(self, job_title: str) -> bool:
        """
        Determine if a job should be included based on title.

        Default implementation includes all jobs. Subclasses can override
        to implement custom filtering logic.

        Args:
            job_title: Job title string

        Returns:
            True if job should be included, False otherwise
        """
        return True

    async def setup_close_verifier(self) -> None:
        """Hook for subclasses to install a URL verifier before the close phase.

        Called from ``incremental.run_incremental_scrape`` between phase 1
        (list scrape) and phase 4 (close detection). Default is a no-op —
        only the Apple scraper currently overrides this to spin up a
        dedicated Playwright page that the registered verifier in
        ``apple_jobs_scraper.api_client`` reads from.

        Implementations SHOULD be idempotent. They MAY raise — the caller
        in ``incremental.run_incremental_scrape`` wraps this call in a
        try/except and logs at WARN, then proceeds without the verifier.
        A failed verifier setup is a best-effort fallback to legacy
        threshold-only close behavior, which is no worse than the pre-fix
        code path. Subclasses that own a registered verifier (e.g.,
        Apple) SHOULD call ``unregister_verifier(source_id)`` on setup
        failure so the close path actually falls back instead of
        silently disabling itself (the verifier would otherwise return
        ``"unknown"`` for every call and ``unknown_policy="skip"`` would
        veto every close).
        """
        return None

    # ========== Concrete Methods (shared implementation) ==========

    async def __aenter__(self):
        """Async context manager entry"""
        await self.initialize_browser()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close_browser()

    async def initialize_browser(self):
        """Launch headless Chromium browser with anti-detection measures.

        Each step after playwright.start() is wrapped in a try/except BaseException
        so that a failure in a later step tears down the partial state from earlier
        steps. Without this, async-with cannot help us — Python does not call
        __aexit__ when __aenter__ raises, so any partially-allocated playwright
        driver / browser would be leaked. We use BaseException (not Exception)
        so asyncio.CancelledError and KeyboardInterrupt also trigger cleanup.

        Cleanup awaits (browser.close, playwright.stop) are themselves wrapped
        in try/except BaseException with logging so a secondary failure during
        cleanup does not mask the original exception, and bounded with
        asyncio.wait_for using the module-level BROWSER_CLOSE_TIMEOUT /
        PLAYWRIGHT_STOP_TIMEOUT constants so a hung cleanup surfaces as
        TimeoutError instead of blocking the subprocess. Attribute nulling
        runs in `finally` so partial state is dropped even if cleanup raises
        or hangs.
        """
        logger.info("Initializing browser...")

        self.playwright = await async_playwright().start()
        try:
            self.browser = await self.playwright.chromium.launch(
                headless=self.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                ],
            )
            try:
                self.context = await self.browser.new_context(
                    viewport=BROWSER_CONFIG["viewport"],
                    user_agent=BROWSER_CONFIG["user_agent"],
                    locale=BROWSER_CONFIG["locale"],
                )
            except BaseException:
                try:
                    try:
                        await asyncio.wait_for(
                            self.browser.close(), timeout=BROWSER_CLOSE_TIMEOUT
                        )
                    except BaseException as cleanup_exc:
                        _safe_log_cleanup_failure(
                            "browser.close() failed during initialize_browser cleanup; "
                            "original exception will still propagate: %r",
                            cleanup_exc,
                        )
                finally:
                    self.browser = None
                raise
        except BaseException:
            try:
                try:
                    await asyncio.wait_for(
                        self.playwright.stop(), timeout=PLAYWRIGHT_STOP_TIMEOUT
                    )
                except BaseException as cleanup_exc:
                    _safe_log_cleanup_failure(
                        "playwright.stop() failed during initialize_browser cleanup; "
                        "original exception will still propagate: %r",
                        cleanup_exc,
                    )
            finally:
                self.playwright = None
            raise

        logger.info("Browser initialized successfully")

    async def close_browser(self):
        """Close browser and cleanup.

        Each await (context.close, browser.close, playwright.stop) is
        independently guarded with try/except BaseException + logging and
        bounded with asyncio.wait_for using the module-level
        CONTEXT_CLOSE_TIMEOUT / BROWSER_CLOSE_TIMEOUT /
        PLAYWRIGHT_STOP_TIMEOUT constants, so that a failure or hang in one
        step does not prevent the subsequent steps from running.

        Each step's attribute (`self.context`, `self.browser`,
        `self.playwright`) is nulled in `finally` after its await, so that a
        subsequent call (e.g. wrapper-driven belt-and-suspenders teardown
        after `__aexit__`) becomes a safe no-op rather than re-attempting
        cleanup on already-closed handles — which would produce spurious
        error logs and waste up to PLAYWRIGHT_STOP_TIMEOUT seconds on stale
        `playwright.stop()` calls.

        Cancellation propagation: if `asyncio.CancelledError` or
        `KeyboardInterrupt` is caught at any step, we still run the
        subsequent steps (the do-not-revert contract) and re-raise the
        cancellation after teardown finishes. The most recent cancellation
        is the live one — earlier cancellations are superseded by virtue of
        us continuing to await past them.

        Success log: `"Browser closed"` at INFO fires only when at least
        one step actually ran AND no step failed. If any step
        failed/timed out/was cancelled, a WARNING `"Browser teardown
        finished with errors above"` fires instead so operators don't get
        a misleading clean-shutdown signal. A no-op double-close (all
        three handles already None) emits no log at all — operators
        relying on `INFO: Browser closed` as a one-per-shutdown marker
        would otherwise see false positives.
        """
        had_failure = False
        attempted_anything = False
        pending_cancellation: BaseException | None = None

        if self.context:
            attempted_anything = True
            try:
                try:
                    await asyncio.wait_for(
                        self.context.close(), timeout=CONTEXT_CLOSE_TIMEOUT
                    )
                except BaseException as cleanup_exc:
                    had_failure = True
                    if isinstance(cleanup_exc, (asyncio.CancelledError, KeyboardInterrupt)):
                        pending_cancellation = cleanup_exc
                    _safe_log_cleanup_failure(
                        "context.close() failed during close_browser; continuing teardown: %r",
                        cleanup_exc,
                    )
            finally:
                self.context = None
        if self.browser:
            attempted_anything = True
            try:
                try:
                    await asyncio.wait_for(
                        self.browser.close(), timeout=BROWSER_CLOSE_TIMEOUT
                    )
                except BaseException as cleanup_exc:
                    had_failure = True
                    if isinstance(cleanup_exc, (asyncio.CancelledError, KeyboardInterrupt)):
                        pending_cancellation = cleanup_exc
                    _safe_log_cleanup_failure(
                        "browser.close() failed during close_browser; continuing teardown: %r",
                        cleanup_exc,
                    )
            finally:
                self.browser = None
        if self.playwright:
            attempted_anything = True
            try:
                try:
                    await asyncio.wait_for(
                        self.playwright.stop(), timeout=PLAYWRIGHT_STOP_TIMEOUT
                    )
                except BaseException as cleanup_exc:
                    had_failure = True
                    if isinstance(cleanup_exc, (asyncio.CancelledError, KeyboardInterrupt)):
                        pending_cancellation = cleanup_exc
                    _safe_log_cleanup_failure(
                        "playwright.stop() failed during close_browser; continuing teardown: %r",
                        cleanup_exc,
                    )
            finally:
                self.playwright = None

        if not attempted_anything:
            # Nothing was open; silent no-op (e.g. double close_browser, or
            # close_browser called after a partial-init failure that
            # already nulled all handles). pending_cancellation cannot be
            # set here because we never entered any of the three branches.
            return
        if had_failure:
            logger.warning("Browser teardown finished with errors above")
        else:
            logger.info("Browser closed")

        if pending_cancellation is not None:
            raise pending_cancellation

    async def navigate_to_page(self, page: Page, url: str, timeout: int = 30000):
        """
        Navigate to URL with error handling

        Args:
            page: Playwright page object
            url: URL to navigate to
            timeout: Timeout in milliseconds
        """
        try:
            await page.goto(url, wait_until="networkidle", timeout=timeout)
        except Exception as e:
            logger.warning(f"Error navigating to {url}: {e}, retrying...")
            # Retry once with domcontentloaded
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout)

    async def scrape_all_queries(self, max_jobs: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Scrape all search queries (used for incremental mode)

        Args:
            max_jobs: Maximum number of jobs to collect (optional)

        Returns:
            List of all job dictionaries from all queries
        """
        all_jobs = []
        search_queries = self.get_search_queries()

        for query in search_queries:
            jobs = await self.scrape_query(query, max_jobs)
            all_jobs.extend(jobs)

            if max_jobs and len(all_jobs) >= max_jobs:
                all_jobs = all_jobs[:max_jobs]
                break

        return all_jobs

    async def _random_delay(self, min_seconds: float = 2.0, max_seconds: float = 5.0):
        """
        Rate limiting delay between requests.

        Subclasses can override this to use their own delay configuration.

        Args:
            min_seconds: Minimum delay (default 2.0)
            max_seconds: Maximum delay (default 5.0)
        """
        delay = random.uniform(min_seconds, max_seconds)
        logger.debug(f"Waiting {delay:.2f} seconds before next request")
        await asyncio.sleep(delay)

    async def scrape_job_details_streaming(
        self,
        job_cards: List[Dict[str, Any]],
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Async generator that yields enriched jobs one at a time as they're scraped.

        Allows jobs to be processed (e.g., written to database) as they're scraped
        rather than waiting for all jobs to complete. Reduces memory usage and
        enables partial progress saving.

        Args:
            job_cards: List of job card dicts from search results

        Yields:
            Enriched job dictionaries with details merged in
        """
        page = await self.context.new_page()
        total = len(job_cards)

        try:
            for i, job_card in enumerate(job_cards, 1):
                job_url = job_card.get("job_url")
                if not job_url:
                    logger.warning(f"Job {i}/{total}: No URL, skipping")
                    yield job_card
                    continue

                logger.info(f"Scraping details {i}/{total}: {job_card.get('title', 'Unknown')}")

                try:
                    details = await self.extract_job_details(page, job_url)
                    yield {**job_card, **details}
                except Exception as e:
                    logger.error(f"Error scraping details for {job_url}: {e}")
                    yield job_card

                await self._random_delay()
        finally:
            await page.close()
