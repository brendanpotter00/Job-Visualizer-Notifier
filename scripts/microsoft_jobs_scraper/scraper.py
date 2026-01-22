"""
Core scraping logic for Microsoft Jobs using Playwright browser automation

This scraper uses a hybrid approach:
- JSON API for search results (primary method)
- HTML parsing as fallback
- JSON API for job details
"""

import logging
import asyncio
import random
import sys
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional
from playwright.async_api import Page

# Add shared module to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.base_scraper import BaseScraper
from shared.models import JobListing
from shared.utils import get_iso_timestamp

from .config import (
    BASE_URL,
    DOMAIN,
    LOCATION_FILTER,
    MAX_PAGES,
    JOBS_PER_PAGE,
    PAGE_LOAD_TIMEOUT,
    REQUEST_DELAY_MIN,
    REQUEST_DELAY_MAX,
    SESSION_ESTABLISH_DELAY,
    SEARCH_QUERIES,
    INCLUDE_TITLE_KEYWORDS,
    EXCLUDE_TITLE_KEYWORDS,
)
from .parser import (
    extract_job_cards_from_list,
    extract_position_id_from_url,
    check_has_next_page,
    JobCardExtractionError,
)
from .api_client import (
    fetch_search_results,
    fetch_job_details,
    get_apply_url,
    JobSearchError,
    JobDetailsFetchError,
)

logger = logging.getLogger(__name__)


class MicrosoftJobsScraper(BaseScraper):
    """Main scraper class for Microsoft Careers (extends BaseScraper)"""

    def __init__(self, headless: bool = True, detail_scrape: bool = False):
        super().__init__(headless, detail_scrape)

    async def _random_delay(self):
        """Override to use Microsoft-specific delay configuration"""
        delay = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
        logger.debug(f"Waiting {delay:.2f} seconds before next request")
        await asyncio.sleep(delay)

    def get_company_name(self) -> str:
        """Return company identifier"""
        return "microsoft"

    def build_search_url(self, search_query: str, page_num: int) -> str:
        """
        Build Microsoft Careers search URL

        Args:
            search_query: Search keyword (e.g., "software engineer")
            page_num: Page number (1-indexed)

        Returns:
            Full URL string
        """
        start = (page_num - 1) * JOBS_PER_PAGE
        url = (
            f"{BASE_URL}/careers"
            f"?query={search_query}"
            f"&location={LOCATION_FILTER}"
            f"&start={start}"
            f"&domain={DOMAIN}"
        )
        return url

    async def extract_job_cards(self, page: Page) -> List[Dict[str, Any]]:
        """
        Extract job listings from Microsoft search results page

        Primarily uses API, falls back to HTML parsing if needed.
        """
        # Ensure 'id' field is set (required by incremental.py)
        job_cards = await extract_job_cards_from_list(page)
        for job in job_cards:
            if "id" not in job:
                job["id"] = extract_position_id_from_url(job.get("job_url", "")) or "unknown"
        return job_cards

    async def extract_job_details(self, page: Page, job_url: str) -> Dict[str, Any]:
        """
        Extract detailed information using Microsoft's API

        Args:
            page: Playwright page object
            job_url: Job URL (used to extract position ID)

        Returns:
            Dictionary with detailed job info
        """
        position_id = extract_position_id_from_url(job_url)
        if not position_id:
            logger.warning(f"Could not extract position ID from URL: {job_url}")
            return {}

        return await fetch_job_details(page, position_id)

    def get_search_queries(self) -> List[str]:
        """Return search queries for Microsoft"""
        return SEARCH_QUERIES

    def filter_job(self, job_title: str) -> bool:
        """Filter job by title keywords using include/exclude keyword lists"""
        title_lower = job_title.lower()

        # Check for exclusion keywords first
        if any(kw.lower() in title_lower for kw in EXCLUDE_TITLE_KEYWORDS):
            return False

        # Check for inclusion keywords
        return any(kw.lower() in title_lower for kw in INCLUDE_TITLE_KEYWORDS)

    async def _fetch_page_jobs(
        self, page: Page, search_query: str, page_num: int
    ) -> tuple[List[Dict[str, Any]], bool, str]:
        """
        Fetch jobs for a single page, trying API first then HTML fallback.

        Returns:
            Tuple of (job_cards, has_more, source)
        """
        start = (page_num - 1) * JOBS_PER_PAGE

        try:
            result = await fetch_search_results(page, search_query, start, LOCATION_FILTER)
            return result.get("jobs", []), result.get("has_more", False), "API"
        except JobSearchError as e:
            logger.warning(f"API failed, using HTML fallback: {e}")
            url = self.build_search_url(search_query, page_num)
            await self.navigate_to_page(page, url, PAGE_LOAD_TIMEOUT)
            await asyncio.sleep(1)
            job_cards = await self.extract_job_cards(page)
            has_more = await check_has_next_page(page) or False
            return job_cards, has_more, "HTML"

    async def scrape_query(
        self, search_query: str, max_jobs: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Scrape jobs for a specific search query with pagination.

        Args:
            search_query: Search keyword (e.g., "software engineer")
            max_jobs: Maximum number of jobs to collect

        Returns:
            List of job dictionaries
        """
        logger.info(f"Scraping Microsoft jobs for query: '{search_query}'")
        all_jobs: List[Dict[str, Any]] = []
        page_num = 1
        consecutive_errors = 0

        page = await self.context.new_page()

        try:
            await self._establish_session(page)

            while page_num <= MAX_PAGES:
                logger.info(f"Scraping page {page_num}")

                try:
                    job_cards, has_more, source = await self._fetch_page_jobs(
                        page, search_query, page_num
                    )
                    consecutive_errors = 0
                except Exception as e:
                    consecutive_errors += 1
                    logger.warning(f"Error on page {page_num} ({consecutive_errors}/3): {e}")
                    if consecutive_errors >= 3:
                        logger.error(f"Too many errors, stopping. Collected {len(all_jobs)} jobs.")
                        break
                    page_num += 1
                    await self._random_delay()
                    continue

                if not job_cards:
                    logger.info(f"No more jobs found from {source}")
                    break

                logger.info(f"Found {len(job_cards)} jobs from {source} on page {page_num}")

                # Filter and collect jobs
                filtered_jobs = [j for j in job_cards if self.filter_job(j.get("title", ""))]
                logger.info(f"After filtering: {len(filtered_jobs)} software/data jobs")
                all_jobs.extend(filtered_jobs)

                if max_jobs and len(all_jobs) >= max_jobs:
                    logger.info(f"Reached max jobs limit: {max_jobs}")
                    return all_jobs[:max_jobs]

                if not has_more:
                    logger.info("No more pages available")
                    break

                page_num += 1
                await self._random_delay()

        finally:
            await page.close()

        logger.info(f"Completed Microsoft scrape for '{search_query}': {len(all_jobs)} jobs collected")
        return all_jobs

    async def _establish_session(self, page: Page) -> None:
        """Navigate to Microsoft careers site to establish session for API calls"""
        await self.navigate_to_page(
            page,
            f"{BASE_URL}/careers?domain={DOMAIN}",
            PAGE_LOAD_TIMEOUT
        )
        # Wait for page to fully load
        await asyncio.sleep(SESSION_ESTABLISH_DELAY)

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
        return [job async for job in self.scrape_job_details_streaming(job_cards)]

    def _normalize_posted_date(self, posted_on: Any) -> Optional[str]:
        """Convert posted date to ISO string format."""
        if posted_on is None:
            return None
        if isinstance(posted_on, (int, float)):
            from datetime import datetime, timezone
            return datetime.fromtimestamp(posted_on, tz=timezone.utc).isoformat()
        return str(posted_on)

    def transform_to_job_model(self, job_data: Dict[str, Any]) -> JobListing:
        """Transform scraped data to JobListing model (database schema)."""
        job_url = job_data.get("job_url", "")
        position_id = job_data.get("id") or extract_position_id_from_url(job_url) or "unknown"
        created_at = get_iso_timestamp()
        posted_on = self._normalize_posted_date(
            job_data.get("posted_on") or job_data.get("posted_date")
        )

        details = {
            "minimum_qualifications": job_data.get("minimum_qualifications", []),
            "preferred_qualifications": job_data.get("preferred_qualifications", []),
            "description": job_data.get("description"),
            "responsibilities": job_data.get("responsibilities"),
            "salary_range": job_data.get("salary_range"),
            "work_site": job_data.get("work_site"),
            "travel": job_data.get("travel"),
            "profession": job_data.get("profession"),
            "discipline": job_data.get("discipline"),
            "role_type": job_data.get("role_type"),
            "employment_type": job_data.get("employment_type"),
            "job_number": job_data.get("job_number"),
            "apply_url": get_apply_url(position_id),
            "raw": job_data,
        }

        return JobListing(
            id=position_id,
            title=job_data.get("title", ""),
            company="microsoft",
            location=job_data.get("location"),
            url=job_url,
            source_id="microsoft_scraper",
            details=details,
            posted_on=posted_on,
            created_at=created_at,
            closed_on=None,
            status="OPEN",
            has_matched=False,
            ai_metadata={},
            first_seen_at=created_at,
            last_seen_at=created_at,
            consecutive_misses=0,
            details_scraped=False,
        )

    def deduplicate_jobs(self, jobs: List[Dict[str, Any]]) -> List[JobListing]:
        """
        Remove duplicates and transform to JobListing models

        Deduplicates by position ID to ensure unique entries.
        """
        seen_ids = set()
        unique_jobs = []

        for job_data in jobs:
            position_id = job_data.get("id", "")
            if position_id and position_id not in seen_ids:
                seen_ids.add(position_id)
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
        Microsoft-specific streaming implementation using JSON API.

        Overrides base class to use API-based detail fetching (position_id)
        instead of page navigation (job_url).

        Args:
            job_cards: List of job card dicts from search results

        Yields:
            Enriched job dictionaries with details merged in
        """
        page = await self.context.new_page()
        total = len(job_cards)

        try:
            await self._establish_session(page)

            for i, job_card in enumerate(job_cards, 1):
                position_id = job_card.get("id")
                if not position_id:
                    logger.warning(f"Job {i}/{total}: No ID, skipping")
                    yield job_card
                    continue

                logger.info(
                    f"Fetching details {i}/{total}: {job_card.get('title', 'Unknown')}"
                )

                try:
                    details = await fetch_job_details(page, position_id)
                    yield {**job_card, **details}
                except JobDetailsFetchError as e:
                    logger.error(f"Detail fetch failed for {position_id}: {e}")
                    yield {**job_card, "_detail_fetch_failed": True}
                except Exception as e:
                    logger.error(f"Unexpected error fetching details for {position_id}: {e}")
                    yield {**job_card, "_detail_fetch_failed": True}

                await self._random_delay()
        finally:
            await page.close()
