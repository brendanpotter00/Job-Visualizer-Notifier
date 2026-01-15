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

    @abstractmethod
    def filter_job(self, job_title: str) -> bool:
        """
        Determine if a job should be included based on title

        Args:
            job_title: Job title string

        Returns:
            True if job should be included, False otherwise
        """
        pass

    # ========== Concrete Methods (shared implementation) ==========

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
