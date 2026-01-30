"""
Core scraping logic for TikTok Jobs using Playwright browser automation

This scraper uses HTML parsing for search results and job detail pages.
"""

import logging
import asyncio
import random
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, AsyncIterator
from urllib.parse import quote
from playwright.async_api import Page

# Add shared module to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.base_scraper import BaseScraper
from shared.models import JobListing
from shared.utils import get_iso_timestamp

from .config import (
    BASE_URL,
    SEARCH_PATH,
    SEARCH_QUERIES,
    JOBS_PER_PAGE,
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
    extract_total_jobs_count,
    check_has_next_page,
    extract_job_details_from_page,
    get_apply_url,
    get_job_detail_url,
    JobCardExtractionError,
)

logger = logging.getLogger(__name__)


class TikTokJobsScraper(BaseScraper):
    """Main scraper class for TikTok Careers (extends BaseScraper)"""

    def __init__(self, headless: bool = True, detail_scrape: bool = False):
        super().__init__(headless, detail_scrape)

    async def _random_delay(self):
        """Override to use TikTok-specific delay configuration"""
        delay = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
        logger.debug(f"Waiting {delay:.2f} seconds before next request")
        await asyncio.sleep(delay)

    def get_company_name(self) -> str:
        """Return company identifier"""
        return "tiktok"

    def build_search_url(self, search_query: str, page_num: int) -> str:
        """
        Build TikTok Careers search URL

        Args:
            search_query: Search term (e.g., "software engineer")
            page_num: Page number (1-indexed)

        Returns:
            Full URL string with offset parameter
        """
        offset = (page_num - 1) * JOBS_PER_PAGE
        encoded_query = quote(search_query)

        url = f"{BASE_URL}{SEARCH_PATH}?keyword={encoded_query}&limit={JOBS_PER_PAGE}"

        if offset > 0:
            url += f"&offset={offset}"

        return url

    async def extract_job_cards(self, page: Page) -> List[Dict[str, Any]]:
        """Extract job listings from TikTok search results page"""
        job_cards = await extract_job_cards_from_list(page)
        # Ensure 'id' field is set (required by incremental.py)
        for job in job_cards:
            if "id" not in job:
                job["id"] = extract_job_id_from_url(job.get("job_url", "")) or "unknown"
        return job_cards

    async def extract_job_details(self, page: Page, job_url: str) -> Dict[str, Any]:
        """
        Extract detailed information from job detail page

        Args:
            page: Playwright page object
            job_url: URL of the job detail page

        Returns:
            Dictionary with detailed job info
        """
        try:
            await self.navigate_to_page(page, job_url, PAGE_LOAD_TIMEOUT)
            await asyncio.sleep(1)  # Wait for dynamic content

            details = await extract_job_details_from_page(page)
            return details

        except Exception as e:
            logger.error(f"Error fetching job details from {job_url}: {e}")
            return {}

    def get_search_queries(self) -> List[str]:
        """Return search queries for TikTok"""
        return SEARCH_QUERIES

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
        Scrape jobs for a search query with pagination

        Args:
            search_query: Search term (e.g., "software engineer")
            max_jobs: Maximum number of jobs to collect

        Returns:
            List of job dictionaries
        """
        logger.info(f"Scraping TikTok jobs for query: '{search_query}'")
        all_jobs = []
        page_num = 1
        consecutive_errors = 0
        max_consecutive_errors = 3
        total_count = None

        # Pagination safeguards for max_jobs
        total_jobs_seen = 0
        pages_without_matches = 0
        max_pages_without_matches = 5  # Stop after 5 consecutive empty pages

        page = await self.context.new_page()

        try:
            while page_num <= MAX_PAGES:
                logger.info(f"Scraping page {page_num}")

                # Build URL with page number
                url = self.build_search_url(search_query, page_num)

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
                    # Try next page
                    page_num += 1
                    await self._random_delay()
                    continue

                # Wait a bit for dynamic content to load
                await asyncio.sleep(2)

                # Get total count on first page
                if page_num == 1:
                    total_count = await extract_total_jobs_count(page)
                    if total_count:
                        logger.info(f"Total jobs available: {total_count}")

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

                # Track total raw jobs seen for max_jobs safeguard
                total_jobs_seen += len(job_cards)

                # Filter jobs by title keywords
                filtered_jobs = [
                    job
                    for job in job_cards
                    if self.filter_job(job.get("title", ""))
                ]

                logger.info(
                    f"After filtering: {len(filtered_jobs)} software/data jobs"
                )

                # Track consecutive pages without matches for early termination
                if len(filtered_jobs) == 0:
                    pages_without_matches += 1
                    if pages_without_matches >= max_pages_without_matches:
                        logger.warning(
                            f"Stopping: {max_pages_without_matches} consecutive pages "
                            f"with no matching jobs (total raw: {total_jobs_seen}, "
                            f"collected: {len(all_jobs)})"
                        )
                        break
                else:
                    pages_without_matches = 0  # Reset counter when we find matches

                all_jobs.extend(filtered_jobs)

                # Stop if max_jobs set and we've seen way more raw jobs than requested
                # (10x multiplier accounts for filtering removing most jobs)
                if max_jobs and total_jobs_seen >= max_jobs * 10:
                    logger.warning(
                        f"Stopping: Seen {total_jobs_seen} raw jobs but only "
                        f"{len(all_jobs)} passed filter (max_jobs={max_jobs})"
                    )
                    break

                # Check if we've hit max_jobs limit
                if max_jobs and len(all_jobs) >= max_jobs:
                    logger.info(f"Reached max jobs limit: {max_jobs}")
                    all_jobs = all_jobs[:max_jobs]
                    break

                # Check for next page
                current_offset = (page_num - 1) * JOBS_PER_PAGE
                has_next = await check_has_next_page(page, current_offset, total_count)
                if not has_next:
                    logger.info("No next page available")
                    break

                page_num += 1

                # Rate limiting delay
                await self._random_delay()

        finally:
            await page.close()

        logger.info(f"Completed TikTok scrape: {len(all_jobs)} jobs collected")
        return all_jobs

    async def scrape_job_details_batch(
        self, job_cards: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Scrape detailed information for a batch of jobs

        Args:
            job_cards: List of job dictionaries from search results

        Returns:
            List of enriched job dictionaries with full details
        """
        return [job async for job in self._fetch_job_details(job_cards)]

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

        try:
            for i, job_card in enumerate(job_cards, 1):
                job_url = job_card.get("job_url")
                if not job_url:
                    logger.warning(f"Job {i}/{total}: No URL, skipping")
                    yield job_card
                    continue

                logger.info(
                    f"Fetching details {i}/{total}: {job_card.get('title', 'Unknown')}"
                )

                try:
                    details = await self.extract_job_details(page, job_url)
                    yield {**job_card, **details}
                except Exception as e:
                    # Unexpected error - log and yield original card with failure flag
                    logger.error(f"Unexpected error fetching details for {job_url}: {e}")
                    yield {**job_card, "_detail_fetch_failed": True}

                await self._random_delay()
        finally:
            await page.close()

    def transform_to_job_model(self, job_data: Dict[str, Any]) -> JobListing:
        """Transform scraped data to JobListing model (database schema)"""
        job_url = job_data.get("job_url", "")
        job_id = job_data.get("id") or extract_job_id_from_url(job_url) or "unknown"

        created_at = get_iso_timestamp()

        # Build details JSONB with all extended job information
        details = {
            "minimum_qualifications": job_data.get("minimum_qualifications", []),
            "preferred_qualifications": job_data.get("preferred_qualifications", []),
            "responsibilities": job_data.get("responsibilities"),
            "about": job_data.get("about"),
            "why_join": job_data.get("why_join"),
            "salary_range": job_data.get("salary_range"),
            "job_code": job_data.get("job_code"),
            "category": job_data.get("category"),
            "employment_type": job_data.get("employment_type"),
            "apply_url": get_apply_url(job_id),
            "raw": job_data,  # Original scraped data for debugging
        }

        job = JobListing(
            id=job_id,
            title=job_data.get("title", ""),
            company="tiktok",
            location=job_data.get("location"),
            url=job_url or get_job_detail_url(job_id),
            source_id="tiktok_scraper",
            details=details,
            posted_on=job_data.get("posted_on"),
            created_at=created_at,
            closed_on=None,
            status="OPEN",
            has_matched=False,
            ai_metadata={},
            # Incremental tracking fields (will be set by caller if using DB mode)
            first_seen_at=created_at,
            last_seen_at=created_at,
            consecutive_misses=0,
            details_scraped=self.detail_scrape,
        )
        return job

    def deduplicate_jobs(self, jobs: List[Dict[str, Any]]) -> List[JobListing]:
        """
        Remove duplicates and transform to JobListing models

        Args:
            jobs: List of raw job dictionaries

        Returns:
            List of unique JobListing models
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
        TikTok-specific streaming implementation.

        Args:
            job_cards: List of job card dicts from search results

        Yields:
            Enriched job dictionaries with details merged in
        """
        async for job in self._fetch_job_details(job_cards):
            yield job
