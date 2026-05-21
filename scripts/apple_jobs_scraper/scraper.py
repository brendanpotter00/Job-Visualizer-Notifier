"""
Core scraping logic for Apple Jobs using Playwright browser automation

This scraper uses a hybrid approach:
- HTML parsing for search results (pagination)
- JSON API for job details (reliable, structured data)
"""

import logging
import asyncio
import random
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, AsyncIterator
from playwright.async_api import Page

# Wait strategy for Apple's careers site. Apple emits continuous analytics
# polling, so wait_until="networkidle" (the BaseScraper default) reliably
# burns its 30s timeout before falling back to domcontentloaded. Going
# straight to domcontentloaded saves ~30s per pagination step. See
# docs/implementations/appleScraperHangFix/PLAN.md.
_APPLE_GOTO_WAIT_UNTIL = "domcontentloaded"

# Add shared module to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.base_scraper import BaseScraper
from shared.constants import SourceId
from shared.models import JobListing
from shared.source_registry import register_verifier, unregister_verifier
from shared.utils import get_iso_timestamp

from .config import (
    BASE_URL,
    SEARCH_PATH,
    LOCATION_FILTER,
    MAX_PAGES,
    PAGE_LOAD_TIMEOUT,
    REQUEST_DELAY_MIN,
    REQUEST_DELAY_MAX,
    INCLUDE_TITLE_KEYWORDS,
    EXCLUDE_TITLE_KEYWORDS,
)
from .parser import (
    extract_job_cards_from_list,
    extract_job_id_from_url,
    check_has_next_page,
    JobCardExtractionError,
)
from .api_client import (
    fetch_job_details,
    get_apply_url,
    set_apple_verifier_page,
    verify_url_alive as apple_verify_url_alive,
    JobDetailsFetchError,
)

logger = logging.getLogger(__name__)


class AppleJobsScraper(BaseScraper):
    """Main scraper class for Apple Careers (extends BaseScraper)"""

    SOURCE_ID = SourceId.APPLE

    def __init__(self, headless: bool = True, detail_scrape: bool = False):
        super().__init__(headless, detail_scrape)
        # Dedicated Playwright page used by the URL verifier during the
        # close-detection phase. Created lazily on the first session-establish
        # call so the verifier can issue ``page.evaluate`` against Apple's
        # detail API (which requires a real browser context — see
        # ``api_client._FETCH_JS``).
        self._verifier_page: Optional[Page] = None

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Drop the module-level verifier reference BEFORE the browser
        # context is torn down by the base class, so any in-flight verify
        # call sees ``None`` rather than a closed page.
        set_apple_verifier_page(None)
        if self._verifier_page is not None:
            try:
                await self._verifier_page.close()
            except Exception:
                logger.warning(
                    "Failed to close Apple verifier page cleanly", exc_info=True,
                )
            finally:
                self._verifier_page = None
        await super().__aexit__(exc_type, exc_val, exc_tb)

    async def setup_close_verifier(self) -> None:
        """Spin up the Apple URL-verifier page before the close phase.

        Called from ``incremental.run_incremental_scrape`` after phase 1
        completes. The verifier itself lives in ``api_client`` and reads
        the page reference via the module-level ``_VERIFIER_PAGE``. Safe
        to call multiple times — ``_ensure_verifier_page`` is idempotent.
        """
        await self._ensure_verifier_page()

    async def _ensure_verifier_page(self) -> None:
        """Create + register the verifier page on first use.

        Idempotent: subsequent calls are no-ops. Fail-safe: if the verifier
        page can't be set up (transient navigation error, context torn down,
        etc.) we log at ERROR and UNREGISTER the Apple verifier from the
        registry — otherwise the verifier would return ``"unknown"`` for
        every call and the close path's ``unknown_policy="skip"`` (auto-
        selected when a verifier is registered) would silently disable
        Apple close-detection entirely. Unregistering lets the close path
        fall through to legacy close-on-threshold behavior instead, which
        is no worse than pre-fix behavior. On a healthy retry next run the
        module's import-time ``register_verifier`` call would re-arm the
        verifier — but since each scrape runs in a fresh subprocess, the
        registration is fresh anyway. We re-register explicitly here in
        case the module was imported under a single long-lived process
        (e.g., tests) where the prior failure left the registry empty.
        """
        if self._verifier_page is not None or self.context is None:
            return
        try:
            self._verifier_page = await self.context.new_page()
            await self.navigate_to_page(
                self._verifier_page, BASE_URL + SEARCH_PATH, PAGE_LOAD_TIMEOUT,
            )
        except Exception:
            logger.error(
                "Apple URL verifier page setup failed — UNREGISTERING the "
                "Apple verifier so close-detection falls through to legacy "
                "close-on-threshold for this run (otherwise every Apple "
                "close would be silently skipped). Investigate the page-"
                "setup error before relying on the verifier again.",
                exc_info=True,
            )
            # Clean up the half-created page so __aexit__'s close attempt
            # doesn't double-fault.
            if self._verifier_page is not None:
                try:
                    await self._verifier_page.close()
                except Exception:
                    pass
                self._verifier_page = None
            set_apple_verifier_page(None)
            unregister_verifier(SourceId.APPLE)
            return
        set_apple_verifier_page(self._verifier_page)
        # Re-arm the registry in case a prior failed setup in the same
        # process unregistered us. No-op on the common (fresh-subprocess)
        # path where the import-time register_verifier already ran.
        register_verifier(SourceId.APPLE, apple_verify_url_alive)
        logger.info(
            "Apple URL verifier page initialized — close-detection will "
            "probe Apple's detail API before flipping rows to CLOSED",
        )

    async def _random_delay(self):
        """Override to use Apple-specific delay configuration"""
        delay = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
        logger.debug(f"Waiting {delay:.2f} seconds before next request")
        await asyncio.sleep(delay)

    async def navigate_to_page(self, page: Page, url: str, timeout: int = 30000):
        """Apple-specific navigation: skip networkidle waiting.

        Apple's careers site polls analytics endpoints continuously, so the
        base class's `wait_until="networkidle"` always hits its timeout
        before falling back. Use `domcontentloaded` directly — it fires as
        soon as the HTML document is parsed, which is sufficient because
        the job list `<ul>` is server-rendered.

        Mirrors the base class's single-retry resilience so a transient
        TLS/connection blip doesn't skip a full pagination step. Without
        the retry, `scrape_query`'s outer consecutive_errors loop would
        log the failure and walk to the next page number, silently
        dropping ~20 jobs.
        """
        try:
            await page.goto(url, wait_until=_APPLE_GOTO_WAIT_UNTIL, timeout=timeout)
        except Exception as e:
            logger.warning(f"Error navigating to {url}: {e}, retrying...")
            await page.goto(url, wait_until=_APPLE_GOTO_WAIT_UNTIL, timeout=timeout)

    def get_company_name(self) -> str:
        """Return company identifier"""
        return "apple"

    def build_search_url(self, search_query: str, page_num: int) -> str:
        """
        Build Apple Careers search URL

        Note: Apple's search doesn't require keywords - we just filter by location
        and paginate through all results, then filter by title keywords.
        """
        url = f"{BASE_URL}{SEARCH_PATH}?location={LOCATION_FILTER}"

        if page_num > 1:
            url += f"&page={page_num}"

        return url

    async def extract_job_cards(self, page: Page) -> List[Dict[str, Any]]:
        """Extract job listings from Apple search results page"""
        job_cards = await extract_job_cards_from_list(page)
        # Ensure 'id' field is set (required by incremental.py)
        for job in job_cards:
            if "id" not in job:
                job["id"] = extract_job_id_from_url(job.get("job_url", "")) or "unknown"
        return job_cards

    async def extract_job_details(self, page: Page, job_url: str) -> Dict[str, Any]:
        """
        Extract detailed information using Apple's API

        Instead of parsing HTML, we use the JSON API which is more reliable.
        """
        job_id = extract_job_id_from_url(job_url)
        if not job_id:
            logger.warning(f"Could not extract job ID from URL: {job_url}")
            return {}

        return await fetch_job_details(page, job_id)

    def get_search_queries(self) -> List[str]:
        """
        Return search queries

        Apple's search uses location filtering, not keyword search.
        We return an empty query and filter by title keywords instead.
        """
        return [""]  # Single empty query - we scrape all US jobs then filter

    def filter_job(self, job_title: str) -> bool:
        """Filter job by title keywords using include/exclude keyword lists"""
        title_lower = job_title.lower()

        # Check for exclusion keywords first
        if any(kw.lower() in title_lower for kw in EXCLUDE_TITLE_KEYWORDS):
            return False

        # Check for inclusion keywords
        return any(kw.lower() in title_lower for kw in INCLUDE_TITLE_KEYWORDS)

    async def scrape_query(
        self, search_query: str, max_jobs: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Scrape all jobs for Apple (single query with pagination)

        Args:
            search_query: Not used for Apple (we scrape all US jobs)
            max_jobs: Maximum number of jobs to collect

        Returns:
            List of job dictionaries
        """
        logger.info("Scraping Apple jobs with US location filter")
        all_jobs = []
        page_num = 1
        consecutive_errors = 0
        max_consecutive_errors = 3

        page = await self.context.new_page()

        try:
            while page_num <= MAX_PAGES:
                logger.info(f"Scraping page {page_num}")

                # Build URL with page number
                url = self.build_search_url("", page_num)

                try:
                    # Navigate to page
                    await self.navigate_to_page(page, url, PAGE_LOAD_TIMEOUT)
                    consecutive_errors = 0
                except Exception as nav_error:
                    consecutive_errors += 1
                    logger.warning(
                        f"Navigation error on page {page_num} ({consecutive_errors}/{max_consecutive_errors}): {nav_error}"
                    )
                    if consecutive_errors >= max_consecutive_errors:
                        logger.error(
                            f"Too many consecutive navigation errors, stopping pagination. "
                            f"Collected {len(all_jobs)} jobs before failure."
                        )
                        break
                    # Create a fresh page — crashed pages can't be reused
                    await page.close()
                    page = await self.context.new_page()
                    page_num += 1
                    await self._random_delay()
                    continue

                # Wait a bit for dynamic content to load
                await asyncio.sleep(1)

                # Extract job cards from list page
                try:
                    job_cards = await self.extract_job_cards(page)
                except JobCardExtractionError as e:
                    # Critical extraction failure - stop pagination and log
                    logger.error(f"Job card extraction failed on page {page_num}: {e}")
                    break

                # Per-page instrumentation for the Apple set-drift investigation.
                # The 2026-05-21 false-close incident showed 5 jobs sharing the
                # same ``last_seen_at`` millisecond — strong signal that one
                # page's worth of jobs straddles a boundary and migrates between
                # scrape ticks. Logging the per-page ID set at DEBUG makes it
                # possible to diff two consecutive runs and pinpoint the
                # drifting IDs. See ``docs/incidents/2026-05-21-apple-eightfold-
                # false-close/`` (when written).
                if logger.isEnabledFor(logging.DEBUG):
                    page_ids = sorted(c.get("id", "?") for c in job_cards)
                    logger.debug(
                        "Apple page %d: %d raw cards, ids=%s",
                        page_num, len(job_cards), page_ids,
                    )

                if not job_cards:
                    # WARN, not INFO — silent termination on an empty page is
                    # the failure mode we suspect for Apple's set drift. If
                    # this fires mid-pagination (page_num < expected max), it
                    # means the scrape ended without exhausting the dataset
                    # and the close phase is about to false-close the missing
                    # jobs. Layer 1 verifier mitigates the user-visible bug;
                    # this WARN gives operators a grep-able signal to
                    # diagnose the underlying cause.
                    logger.warning(
                        "Apple pagination terminated on empty page_num=%d "
                        "(total collected=%d). If page_num is small, "
                        "investigate whether Apple's HTML structure changed "
                        "or pagination boundary shifted.",
                        page_num, len(all_jobs),
                    )
                    break

                logger.info(f"Found {len(job_cards)} jobs on page {page_num}")

                # Filter jobs by title keywords
                filtered_jobs = [
                    job
                    for job in job_cards
                    if self.filter_job(job.get("title", ""))
                ]

                logger.info(
                    f"After filtering: {len(filtered_jobs)} software/data jobs"
                )

                all_jobs.extend(filtered_jobs)

                # Check if we've hit max_jobs limit
                if max_jobs and len(all_jobs) >= max_jobs:
                    logger.info(f"Reached max jobs limit: {max_jobs}")
                    all_jobs = all_jobs[:max_jobs]
                    break

                # Check for next page
                has_next = await check_has_next_page(page)
                if has_next is None:
                    # Check failed - log warning and stop to avoid infinite loop or data loss
                    logger.warning("Failed to check for next page, stopping pagination")
                    break
                if not has_next:
                    logger.info("No next page available")
                    break

                page_num += 1

                # Rate limiting delay
                await self._random_delay()

        finally:
            await page.close()

        logger.info(f"Completed Apple scrape: {len(all_jobs)} jobs collected")
        return all_jobs

    async def _establish_session(self, page: Page) -> None:
        """Navigate to Apple jobs site to establish session for API calls"""
        await self.navigate_to_page(page, BASE_URL + SEARCH_PATH, PAGE_LOAD_TIMEOUT)

    async def _fetch_job_details(
        self,
        job_cards: List[Dict[str, Any]],
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Core detail-fetching logic shared by batch and streaming modes.

        Args:
            job_cards: List of job dictionaries from search results

        Yields:
            Enriched job dictionaries with details merged in
        """
        page = await self.context.new_page()
        total = len(job_cards)

        await self._establish_session(page)

        try:
            for i, job_card in enumerate(job_cards, 1):
                job_id = job_card.get("id")
                if not job_id:
                    logger.warning(f"Job {i}/{total}: No ID, skipping")
                    yield job_card
                    continue

                logger.info(
                    f"Fetching details {i}/{total}: {job_card.get('title', 'Unknown')}"
                )

                try:
                    details = await fetch_job_details(page, job_id)
                    yield {**job_card, **details}
                except JobDetailsFetchError as e:
                    # API/network failure - log and yield original card with failure flag
                    logger.error(f"Detail fetch failed for {job_id}: {e}")
                    yield {**job_card, "_detail_fetch_failed": True}
                except Exception as e:
                    # Unexpected error - log and yield original card with failure flag
                    logger.error(f"Unexpected error fetching details for {job_id}: {e}")
                    yield {**job_card, "_detail_fetch_failed": True}

                await self._random_delay()
        finally:
            await page.close()

    async def scrape_job_details_batch(
        self, job_cards: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Scrape detailed information for a batch of jobs using API.

        Args:
            job_cards: List of job dictionaries from search results

        Returns:
            List of enriched job dictionaries with full details
        """
        return [job async for job in self._fetch_job_details(job_cards)]

    def transform_to_job_model(self, job_data: Dict[str, Any]) -> JobListing:
        """Transform scraped data to JobListing model (database schema)"""
        job_url = job_data.get("job_url", "")
        job_id = job_data.get("id") or extract_job_id_from_url(job_url) or "unknown"

        created_at = get_iso_timestamp()

        # Get posted date from API response
        posted_on = job_data.get("posted_on")

        # Build details JSONB with all extended job information
        details = {
            "minimum_qualifications": job_data.get("minimum_qualifications", []),
            "preferred_qualifications": job_data.get("preferred_qualifications", []),
            "description": job_data.get("description"),
            "job_summary": job_data.get("job_summary"),
            "responsibilities": job_data.get("responsibilities"),
            "team_names": job_data.get("team_names", []),
            "team": job_data.get("team"),
            "salary_range": job_data.get("salary_range"),
            "is_remote_eligible": job_data.get("is_remote_eligible", False),
            "apply_url": get_apply_url(job_id),
            "job_type": job_data.get("job_type"),
            "employment_type": job_data.get("employment_type"),
            "locations": job_data.get("locations", []),
            "raw": job_data,  # Original scraped data for debugging
        }

        job = JobListing(
            id=job_id,
            title=job_data.get("title", ""),
            company="apple",
            location=job_data.get("location"),
            url=job_url,
            source_id=SourceId.APPLE,
            details=details,
            posted_on=posted_on,
            created_at=created_at,
            closed_on=None,
            status="OPEN",
            has_matched=False,
            ai_metadata={},
            # Incremental tracking fields (will be set by caller if using DB mode)
            first_seen_at=created_at,
            last_seen_at=created_at,
            consecutive_misses=0,
            details_scraped=False,
        )
        return job

    def deduplicate_jobs(self, jobs: List[Dict[str, Any]]) -> List[JobListing]:
        """
        Remove duplicates and transform to JobListing models

        Note: Same job in multiple locations are kept as separate entries
        since they have different job IDs (e.g., 200640732-0836 vs 200640732-3337)
        """
        seen_ids = set()
        unique_jobs = []

        for job_data in jobs:
            job_id = job_data.get("id", "")
            if job_id and job_id not in seen_ids:
                seen_ids.add(job_id)
                job_model = self.transform_to_job_model(job_data)
                unique_jobs.append(job_model)

        logger.info(
            f"Deduplicated: {len(jobs)} jobs -> {len(unique_jobs)} unique jobs"
        )
        return unique_jobs

    async def scrape_job_details_streaming(
        self,
        job_cards: List[Dict[str, Any]],
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Apple-specific streaming implementation using JSON API.

        Overrides base class to use API-based detail fetching (job_id)
        instead of page navigation (job_url). Establishes session first.

        Args:
            job_cards: List of job card dicts from search results

        Yields:
            Enriched job dictionaries with details merged in
        """
        async for job in self._fetch_job_details(job_cards):
            yield job
