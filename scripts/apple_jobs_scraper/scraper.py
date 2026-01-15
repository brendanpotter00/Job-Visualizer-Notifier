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

# Add shared module to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.base_scraper import BaseScraper
from shared.models import JobListing
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
)
from .api_client import fetch_job_details, get_apply_url

logger = logging.getLogger(__name__)


class AppleJobsScraper(BaseScraper):
    """Main scraper class for Apple Careers (extends BaseScraper)"""

    def __init__(self, headless: bool = True, detail_scrape: bool = False):
        super().__init__(headless, detail_scrape)

    async def _random_delay(self):
        """Override to use Apple-specific delay configuration"""
        delay = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
        logger.debug(f"Waiting {delay:.2f} seconds before next request")
        await asyncio.sleep(delay)

    # ========== Abstract Method Implementations ==========

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

    # ========== Apple-Specific Methods ==========

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

        page = await self.context.new_page()

        try:
            while page_num <= MAX_PAGES:
                logger.info(f"Scraping page {page_num}")

                # Build URL with page number
                url = self.build_search_url("", page_num)

                # Navigate to page
                await self.navigate_to_page(page, url, PAGE_LOAD_TIMEOUT)

                # Wait a bit for dynamic content to load
                await asyncio.sleep(1)

                # Extract job cards from list page
                job_cards = await self.extract_job_cards(page)

                if not job_cards:
                    logger.info("No more jobs found")
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
                except Exception as e:
                    logger.error(f"Error fetching details for {job_id}: {e}")
                    yield job_card

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
            source_id="apple_scraper",
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
