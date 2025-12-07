"""
Core scraping logic using Playwright browser automation
"""

import logging
import sys
from pathlib import Path
from urllib.parse import quote
from typing import List, Dict, Any, Optional
from playwright.async_api import Page

# Add shared module to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.base_scraper import BaseScraper

from .config import (
    BASE_URL,
    LOCATION_FILTER,
    SEARCH_QUERIES,
    MAX_PAGES,
    PAGE_LOAD_TIMEOUT,
    INCLUDE_TITLE_KEYWORDS,
    EXCLUDE_TITLE_KEYWORDS,
)
from .models import GoogleJob
from .utils import (
    random_delay,
    get_iso_timestamp,
    extract_job_id_from_url,
    should_include_job,
)
from .parser import (
    extract_job_cards_from_list,
    extract_job_details,
    check_for_next_page,
)

logger = logging.getLogger(__name__)


class GoogleJobsScraper(BaseScraper):
    """Main scraper class for Google Careers (extends BaseScraper)"""

    def __init__(self, headless: bool = True, detail_scrape: bool = False):
        super().__init__(headless, detail_scrape)

    # ========== Abstract Method Implementations ==========

    def get_company_name(self) -> str:
        """Return company identifier"""
        return "google"

    def build_search_url(self, search_query: str, page_num: int) -> str:
        """Build Google Careers search URL"""
        url = f"{BASE_URL}?location={quote(LOCATION_FILTER)}&q={quote(search_query)}"

        if page_num > 1:
            url += f"&page={page_num}"

        return url

    async def extract_job_cards(self, page: Page) -> List[Dict[str, Any]]:
        """Extract job listings from Google search results page"""
        return await extract_job_cards_from_list(page)

    async def extract_job_details(self, page: Page, job_url: str) -> Dict[str, Any]:
        """Extract detailed information from Google job detail page"""
        return await extract_job_details(page, job_url)

    def get_search_queries(self) -> List[str]:
        """Return Google-specific search queries"""
        return SEARCH_QUERIES

    def filter_job(self, job_title: str) -> bool:
        """Filter job by title keywords"""
        return should_include_job(job_title, INCLUDE_TITLE_KEYWORDS, EXCLUDE_TITLE_KEYWORDS)

    # ========== Google-Specific Methods ==========

    async def scrape_query(
        self, search_query: str, max_jobs: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Scrape all jobs for a given search query
        Returns list of job dictionaries
        """
        logger.info(f"Scraping query: '{search_query}'")
        all_jobs = []
        page_num = 1

        page = await self.context.new_page()

        try:
            while page_num <= MAX_PAGES:
                logger.info(
                    f"Scraping page {page_num} for query '{search_query}'"
                )

                # Build URL with filters
                url = self.build_search_url(search_query, page_num)

                # Navigate to page
                await self.navigate_to_page(page, url, PAGE_LOAD_TIMEOUT)

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
                has_next = await check_for_next_page(page)
                if not has_next:
                    logger.info("No next page available")
                    break

                page_num += 1

                # Rate limiting delay
                await random_delay()

        finally:
            await page.close()

        logger.info(
            f"Completed query '{search_query}': {len(all_jobs)} jobs collected"
        )
        return all_jobs

    async def scrape_job_details_batch(
        self, job_cards: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Scrape detailed information for a batch of jobs
        """
        enriched_jobs = []

        page = await self.context.new_page()

        try:
            for i, job_card in enumerate(job_cards, 1):
                job_url = job_card.get("job_url")
                if not job_url:
                    logger.warning(f"Job {i}/{len(job_cards)}: No URL, skipping")
                    continue

                logger.info(
                    f"Scraping details for job {i}/{len(job_cards)}: {job_card.get('title', 'Unknown')}"
                )

                try:
                    # Extract detailed information
                    details = await self.extract_job_details(page, job_url)

                    # Merge with basic info from list page
                    enriched_job = {**job_card, **details}
                    enriched_jobs.append(enriched_job)

                    # Rate limiting
                    await random_delay()

                except Exception as e:
                    logger.error(
                        f"Error scraping details for {job_url}: {e}"
                    )
                    # Keep the basic info even if details fail
                    enriched_jobs.append(job_card)

        finally:
            await page.close()

        return enriched_jobs

    def transform_to_job_model(self, job_data: Dict[str, Any]) -> GoogleJob:
        """Transform scraped data to JobListing model (database schema)"""
        job_url = job_data.get("job_url", "")
        job_id = extract_job_id_from_url(job_url) or "unknown"

        created_at = get_iso_timestamp()

        # Build details JSONB with all extended job information
        details = {
            "minimum_qualifications": job_data.get("minimum_qualifications", []),
            "preferred_qualifications": job_data.get("preferred_qualifications", []),
            "about_the_job": job_data.get("about_the_job"),
            "responsibilities": job_data.get("responsibilities", []),
            "experience_level": job_data.get("experience_level"),
            "salary_range": job_data.get("salary_range"),
            "is_remote_eligible": job_data.get("is_remote_eligible", False),
            "apply_url": job_data.get("apply_url"),
            "raw": job_data,  # Original scraped data for debugging
        }

        job = GoogleJob(
            id=job_id,
            title=job_data.get("title", ""),
            company=job_data.get("company", "google"),
            location=job_data.get("location"),
            url=job_url,
            source_id="google_scraper",
            details=details,
            posted_on=None,  # Google doesn't expose post date
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

    def deduplicate_jobs(self, jobs: List[Dict[str, Any]]) -> List[GoogleJob]:
        """
        Remove duplicates (same job from different search queries)
        and transform to GoogleJob models
        """
        seen_urls = set()
        unique_jobs = []

        for job_data in jobs:
            job_url = job_data.get("job_url", "")
            if job_url and job_url not in seen_urls:
                seen_urls.add(job_url)
                job_model = self.transform_to_job_model(job_data)
                unique_jobs.append(job_model)

        logger.info(
            f"Deduplicated: {len(jobs)} jobs -> {len(unique_jobs)} unique jobs"
        )
        return unique_jobs
