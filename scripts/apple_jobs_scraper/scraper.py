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
from shared.posted_date import effective_posted_date, parse_posted_date
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
    get_total_pages,
    parse_card_posted_date,
    JobCardExtractionError,
)
from .api_client import fetch_job_details, get_apply_url, JobDetailsFetchError

logger = logging.getLogger(__name__)

# The key ``api_client.parse_job_details`` writes ``postDateInGMT`` into. Named
# because ``_detail_posted_date`` keys the whole list-vs-detail decision on its
# PRESENCE, not on its truthiness — see there.
_DETAIL_POSTED_KEY = "posted_on"

# Loud-truncation slack. ``scrape_query`` reads Apple's own advertised total
# page count once (``get_total_pages``) and, if the walk ends more than this
# many pages short of it, logs an ERROR. The slack absorbs the board
# legitimately drifting by a page or two during a ~20-minute walk; a real
# pagination break (stop after page 1 of ~226) overshoots it by two orders of
# magnitude. See docs/incidents/2026-08-28-apple-pagination-single-page.md.
_TRUNCATION_PAGE_SLACK = 2


def _detail_posted_date(job_data: Dict[str, Any], job_id: str) -> Optional[str]:
    """Apple's detail-mode ``postDateInGMT``, but only if it is really a date.

    The list half of this pair has been normalised and logged since
    ``parse_card_posted_date`` shipped; the detail half was passed through raw —
    never validated, never logged. That is the exact failure that function's own
    docstring describes, just on the other feed: the raw string stores fine in
    ``posted_on`` (a TIMESTAMPTZ Postgres will read generously) while the shared
    ``effective_posted_date`` rejects it, so the date lands in diagnostics and
    silently does NOT land in ``first_seen_at`` — the key users are sorted by.
    Prod is ISO today (9,949 of 9,990 rows carry a real ``postDateInGMT``), so
    nothing is broken; nothing would have reported it if that changed.

    Validated against the SHARED parser, not dateutil, because the shared parser
    is precisely what ``effective_posted_date`` will run next: agreeing with it
    is the whole point, and agreeing with anything else re-opens the gap.

    **Presence, not truthiness, decides which feed we are on.** ``x or y`` read
    an empty detail value as "no detail feed" and fell through to the card, so a
    board that started emitting ``""`` for every job was indistinguishable from
    a plain list-mode row: no warning anywhere, every date NULL, and
    ``first_seen_at`` quietly back to "posted today" board-wide. The three cases
    are now separate and only one of them is silent.

    Returns ``None`` for every failure — the caller still falls back to the
    card's date, which is the behaviour the old ``or`` chain had and is worth
    keeping (a detail fetch that failed still leaves a usable card date).
    """
    if _DETAIL_POSTED_KEY not in job_data:
        # LIST MODE, or a detail fetch that raised and yielded
        # ``{**job_card, "_detail_fetch_failed": True}``. There is no detail
        # value to judge, which is not the same thing as a detail value that
        # came back empty. Silent: this is the normal shape of a list run.
        return None

    raw = job_data[_DETAIL_POSTED_KEY]
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        # DETAIL MODE, and the payload carried no date. INFO, not WARNING: one
        # dateless posting is Apple's data rather than a fault, and a board-wide
        # format change shows up here as volume (~10k rows a run) either way.
        logger.info(
            "apple: job %s came back from the detail API with no posted date", job_id
        )
        return None

    parsed = parse_posted_date(raw)
    if parsed is None:
        logger.warning(
            "apple: could not parse detail posted date %r for job %s; storing NULL",
            raw,
            job_id,
        )
        return None
    # Hand back Apple's own string when it is one, so the stored value stays
    # exactly what the board published (the rule the Microsoft normalizer
    # documents). A non-string that parses — an epoch, if Apple ever switches —
    # cannot go into a TIMESTAMPTZ as-is, so that gets the parsed ISO instead.
    return raw if isinstance(raw, str) else parsed.isoformat()


class AppleJobsScraper(BaseScraper):
    """Main scraper class for Apple Careers (extends BaseScraper)"""

    SOURCE_ID = SourceId.APPLE

    def __init__(self, headless: bool = True, detail_scrape: bool = False):
        super().__init__(headless, detail_scrape)

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

        # Loud-truncation cross-check (see _TRUNCATION_PAGE_SLACK). Apple's own
        # advertised page count, read once on page 1; the number of pages we
        # actually collected from; and whether we stopped because we hit the
        # caller's max_jobs cap (a deliberate short walk, not a truncation).
        expected_total_pages: Optional[int] = None
        pages_scraped = 0
        stopped_for_max_jobs = False

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

                if not job_cards:
                    logger.info("No more jobs found")
                    break

                logger.info(f"Found {len(job_cards)} jobs on page {page_num}")

                # Read Apple's advertised total-page count once, on page 1, as a
                # board-size oracle for the post-loop truncation check.
                if page_num == 1:
                    expected_total_pages = await get_total_pages(page)
                    if expected_total_pages is not None:
                        logger.info(
                            f"Apple board advertises {expected_total_pages} result pages"
                        )

                pages_scraped += 1

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
                    stopped_for_max_jobs = True
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

        # LOUD TRUNCATION CHECK. If Apple told us the board is N pages and we
        # walked far fewer — and we did not deliberately stop for max_jobs — the
        # pagination walk was truncated. This is the signal that was missing on
        # 2026-08-28: a stop-after-page-1 produced a clean-looking 17-job result
        # that the safety guard blocked silently for 3.5 days. An ERROR here is
        # greppable (Railway @level:error) and distinct from a genuine one-page
        # board. It does NOT raise: the incremental guard remains the backstop
        # that prevents mass closure; this only makes the failure visible.
        if (
            expected_total_pages is not None
            and not stopped_for_max_jobs
            and expected_total_pages - pages_scraped > _TRUNCATION_PAGE_SLACK
        ):
            logger.error(
                "SCRAPER TRUNCATION (apple): walked %d of %d advertised pages "
                "(%d jobs collected). A large board that stops early is the "
                "2026-08-28 single-page failure signature — verify "
                "check_has_next_page against Apple's live pagination markup.",
                pages_scraped,
                expected_total_pages,
                len(all_jobs),
            )

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

        # Get posted date. Detail mode (api_client) supplies `posted_on` from
        # `postDateInGMT`; list mode (parser) supplies `posted_date` scraped off
        # the card. Reading only `posted_on` silently dropped every list-mode
        # date. Same shape as the Microsoft scraper.
        #
        # BOTH halves are validated, and both say so when they fail. They are
        # validated DIFFERENTLY because the two feeds are different: the card is
        # human ("Jan 15, 2026") and needs `parse_card_posted_date`'s dateutil
        # normalisation, while `postDateInGMT` is already ISO and only needs
        # checking against the shared parser. What must NOT differ is whether a
        # present-but-unreadable value is allowed through — half-validating is
        # worse than none, because a string the TIMESTAMPTZ accepts and the
        # shared parser rejects reaches diagnostics and silently misses
        # `first_seen_at`, the key users are actually sorted by. See
        # `_detail_posted_date`, which also explains why the old `or` chain
        # could not tell an empty detail value from a list-mode row.
        posted_on = _detail_posted_date(job_data, job_id)
        if posted_on is None:
            posted_on = parse_card_posted_date(job_data.get("posted_date"))

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
            # THE EFFECTIVE POSTED DATE, not literally "when we first saw it"
            # (POSTED-DATE-PLAN.md §2, D9/D10). Same rule BatchWriter.add_job
            # applies on the way to the DB — kept in step here so the model a
            # caller inspects says the same thing as the row that gets written.
            #
            # Both feeds arrive VALIDATED: detail mode's ``postDateInGMT`` is
            # checked against this same shared parser by ``_detail_posted_date``,
            # list mode's ``posted_date`` is normalised to YYYY-MM-DD by
            # ``parser.parse_card_posted_date``. That is load-bearing on both
            # sides — a value the TIMESTAMPTZ ``posted_on`` accepts but the
            # shared parser rejects would land the date in diagnostics and not
            # in the sort key. Whichever half fails, it fails LOUDLY.
            first_seen_at=effective_posted_date(posted_on, created_at),
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
