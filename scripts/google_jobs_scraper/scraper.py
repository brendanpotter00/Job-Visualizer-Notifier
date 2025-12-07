"""
Core scraping logic using Playwright browser automation
"""

import logging
from urllib.parse import quote
from typing import List, Dict, Any, Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from .config import (
    BASE_URL,
    LOCATION_FILTER,
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


class GoogleJobsScraper:
    """Main scraper class for Google Careers"""

    def __init__(self, headless: bool = True, detail_scrape: bool = False):
        self.headless = headless
        self.detail_scrape = detail_scrape
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None

    async def __aenter__(self):
        """Async context manager entry"""
        await self.initialize_browser()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close_browser()

    async def initialize_browser(self):
        """Launch headless Chromium browser with anti-detection measures"""
        logger.info("Initializing browser...")

        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
            ],
        )

        self.context = await self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="en-US",
        )

        logger.info("Browser initialized successfully")

    async def close_browser(self):
        """Close browser and cleanup"""
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        logger.info("Browser closed")

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
                url = self._build_search_url(search_query, page_num)

                # Navigate to page
                await self._navigate_to_page(page, url)

                # Extract job cards from list page
                job_cards = await extract_job_cards_from_list(page)

                if not job_cards:
                    logger.info("No more jobs found")
                    break

                logger.info(f"Found {len(job_cards)} jobs on page {page_num}")

                # Filter jobs by title keywords
                filtered_jobs = [
                    job
                    for job in job_cards
                    if should_include_job(
                        job.get("title", ""),
                        INCLUDE_TITLE_KEYWORDS,
                        EXCLUDE_TITLE_KEYWORDS,
                    )
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
                    details = await extract_job_details(page, job_url)

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

    def _build_search_url(self, search_query: str, page_num: int) -> str:
        """Build search URL with filters and pagination"""
        url = f"{BASE_URL}?location={quote(LOCATION_FILTER)}&q={quote(search_query)}"

        if page_num > 1:
            url += f"&page={page_num}"

        return url

    async def _navigate_to_page(self, page: Page, url: str):
        """Navigate to URL with error handling"""
        try:
            await page.goto(url, wait_until="networkidle", timeout=PAGE_LOAD_TIMEOUT)
        except Exception as e:
            logger.warning(f"Error navigating to {url}: {e}, retrying...")
            # Retry once
            await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)

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

        return GoogleJob(
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
        )

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
