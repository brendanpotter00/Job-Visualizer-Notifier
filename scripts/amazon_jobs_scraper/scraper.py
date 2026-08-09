"""
Core scraping logic for Amazon Jobs.

Amazon exposes a public JSON search endpoint whose list rows already contain
the full description, so this scraper is API-only and performs **no** per-job
detail fetch — see ``scrape_job_details_streaming``.
"""

import asyncio
import logging
import random
import re
import sys
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional
from urllib.parse import quote_plus

from playwright.async_api import Page

# Add shared module to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.base_scraper import BaseScraper
from shared.constants import SourceId
from shared.models import JobListing
from shared.utils import get_iso_timestamp

from .config import (
    BASE_URL,
    COUNTRY,
    EXCLUDE_TITLE_KEYWORDS,
    INCLUDE_TITLE_KEYWORDS,
    JOBS_PER_PAGE,
    MAX_CONSECUTIVE_ERRORS,
    MAX_PAGES,
    PAGE_LOAD_TIMEOUT,
    REQUEST_DELAY_MAX,
    REQUEST_DELAY_MIN,
    SEARCH_QUERIES,
    SESSION_ESTABLISH_DELAY,
    SESSION_PATH,
)
from .api_client import fetch_search_results
from .parser import extract_job_id_from_url

logger = logging.getLogger(__name__)

# Word-boundary matcher for the exclude list. Substring matching here would
# drop real jobs — "HR" matches "T-h-r-eat Intelligence". See config.py.
_EXCLUDE_RE = re.compile(
    r"(?<![a-z])(?:%s)(?![a-z])"
    % "|".join(re.escape(kw.lower()) for kw in EXCLUDE_TITLE_KEYWORDS)
)

_INCLUDE_KEYWORDS_LOWER = [kw.lower() for kw in INCLUDE_TITLE_KEYWORDS]

# Experience-level heuristics, most specific first. Amazon returns null for
# is_intern / university_job / is_manager on every row observed live
# (803/803 on 2026-08-09), so the title is the only usable signal.
_EXPERIENCE_PATTERNS = [
    (re.compile(r"\bintern(ship)?\b", re.I), "Intern"),
    (re.compile(r"\b(university|new grad(uate)?|recent graduate)\b", re.I), "Entry"),
    (re.compile(r"\b(principal|distinguished|staff|director)\b", re.I), "Principal"),
    (re.compile(r"\b(sr\.?|senior|iii)\b", re.I), "Senior"),
    (re.compile(r"\bii\b", re.I), "Mid"),
    (re.compile(r"\bi\b", re.I), "Entry"),
]

_REMOTE_RE = re.compile(r"\b(remote|virtual|work from home|telecommute)\b", re.I)

# amazon.jobs polls analytics endpoints continuously, so the base class's
# wait_until="networkidle" always burns its full 30s timeout before falling
# back. Verified live 2026-08-09. Going straight to domcontentloaded saves
# ~30s per run and is sufficient — we only need *an* amazon.jobs origin for
# the same-origin fetch, not a fully settled page.
_AMAZON_GOTO_WAIT_UNTIL = "domcontentloaded"


class AmazonJobsScraper(BaseScraper):
    """Scraper for amazon.jobs (extends BaseScraper)"""

    SOURCE_ID = SourceId.AMAZON

    def __init__(self, headless: bool = True, detail_scrape: bool = False):
        super().__init__(headless, detail_scrape)

    async def _random_delay(self):
        """Override to use Amazon-specific delay configuration"""
        delay = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
        logger.debug(f"Waiting {delay:.2f} seconds before next request")
        await asyncio.sleep(delay)

    async def navigate_to_page(self, page: Page, url: str, timeout: int = 30000):
        """Amazon-specific navigation: skip networkidle waiting.

        See ``_AMAZON_GOTO_WAIT_UNTIL``. Mirrors the base class's single-retry
        resilience so a transient blip doesn't leave the page on about:blank —
        which would make every subsequent in-page fetch fail CORS.
        """
        try:
            await page.goto(url, wait_until=_AMAZON_GOTO_WAIT_UNTIL, timeout=timeout)
        except Exception as exc:
            logger.warning(f"Error navigating to {url}: {exc}, retrying...")
            await page.goto(url, wait_until=_AMAZON_GOTO_WAIT_UNTIL, timeout=timeout)

    # ---- BaseScraper abstract methods -----------------------------------

    def get_company_name(self) -> str:
        """Return company identifier"""
        return "amazon"

    def build_search_url(self, search_query: str, page_num: int) -> str:
        """Build the human-facing Amazon search URL.

        This is the page a human opens when debugging; the scraper itself hits
        the JSON endpoint via ``api_client.build_search_api_url``.
        """
        offset = (page_num - 1) * JOBS_PER_PAGE
        return (
            f"{BASE_URL}/en/search"
            f"?base_query={quote_plus(search_query)}"
            f"&country={COUNTRY}"
            f"&offset={offset}"
        )

    async def extract_job_cards(self, page: Page) -> List[Dict[str, Any]]:
        """Extract job cards for the first page of results.

        Pagination calls ``fetch_search_results`` directly; this exists to
        satisfy the BaseScraper contract and to give the API path a single
        named entry point.
        """
        result = await fetch_search_results(page, SEARCH_QUERIES[0], 0)
        return result.get("jobs", [])

    async def extract_job_details(self, page: Page, job_url: str) -> Dict[str, Any]:
        """Unused — Amazon's list payload already carries the description.

        ``scrape_job_details_streaming`` is a pass-through and never calls
        this. Implemented only to satisfy BaseScraper's ABC. Returns an empty
        dict so that if a future refactor ever routes through the base-class
        streaming path, ``{**card, **{}}`` degrades to the card unchanged
        rather than raising.
        """
        return {}

    def get_search_queries(self) -> List[str]:
        """Return search queries for Amazon"""
        return SEARCH_QUERIES

    def filter_job(self, job_title: str) -> bool:
        """Filter by title keywords.

        EXCLUDE uses word boundaries, INCLUDE uses plain substrings. The
        asymmetry is deliberate: Amazon has already narrowed by relevance
        server-side, so a loose INCLUDE costs nothing, whereas a loose EXCLUDE
        silently discards real listings.
        """
        if not job_title:
            return False
        title_lower = job_title.lower()
        if _EXCLUDE_RE.search(title_lower):
            return False
        return any(kw in title_lower for kw in _INCLUDE_KEYWORDS_LOWER)

    # ---- Session + pagination -------------------------------------------

    async def _establish_session(self, page: Page) -> None:
        """Navigate to amazon.jobs before issuing in-page fetches.

        Load-bearing, not a nicety: search.json sends no
        Access-Control-Allow-Origin header, so a fetch() issued from any other
        origin (including about:blank) is blocked by CORS.
        """
        await self.navigate_to_page(page, f"{BASE_URL}{SESSION_PATH}", PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(SESSION_ESTABLISH_DELAY)

    async def scrape_query(
        self, search_query: str, max_jobs: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Scrape all pages for one search query.

        Stop conditions (all evaluated against the *pre-filter* row count, so a
        page whose titles were all filtered out is never mistaken for the end
        of the results):
          1. the page returned zero rows
          2. the page returned fewer than JOBS_PER_PAGE rows
          3. offset + JOBS_PER_PAGE >= the reported total (`hits`)
        """
        logger.info(f"Scraping Amazon jobs for query: '{search_query}'")
        all_jobs: List[Dict[str, Any]] = []
        seen_ids: set = set()
        consecutive_errors = 0
        natural_stop = False
        offset = 0

        page = await self.context.new_page()

        try:
            await self._establish_session(page)

            # A `while` loop, not `for page_idx in range(...)`: on error we must
            # retry the SAME offset, and `continue` inside a for-loop would
            # advance it. Skipping a page silently drops 100 jobs (~8% of the
            # board), which can itself trip the partial-scrape safety guard.
            # page_idx only advances after a successful fetch, so retries do not
            # consume the page budget; consecutive_errors bounds the retries.
            page_idx = 0
            while page_idx < MAX_PAGES:
                offset = page_idx * JOBS_PER_PAGE

                try:
                    result = await fetch_search_results(page, search_query, offset)
                    consecutive_errors = 0
                except Exception as exc:
                    consecutive_errors += 1
                    logger.warning(
                        "Error fetching Amazon offset=%d (%d/%d): %s",
                        offset, consecutive_errors, MAX_CONSECUTIVE_ERRORS, exc,
                    )
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        logger.error(
                            "Too many consecutive errors, stopping. Collected %d jobs.",
                            len(all_jobs),
                        )
                        break
                    await self._random_delay()
                    continue

                page_idx += 1
                raw_count = result["raw_count"]
                if raw_count == 0:
                    logger.info("No more jobs returned at offset=%d", offset)
                    natural_stop = True
                    break

                new_this_page = 0
                for card in result["jobs"]:
                    job_id = card.get("id")
                    if not job_id or job_id in seen_ids:
                        continue
                    seen_ids.add(job_id)
                    new_this_page += 1
                    if self.filter_job(card.get("title", "")):
                        all_jobs.append(card)

                logger.info(
                    "offset=%d: %d rows, %d new, %d kept (total %d)",
                    offset, raw_count, new_this_page, len(all_jobs), len(all_jobs),
                )

                if max_jobs and len(all_jobs) >= max_jobs:
                    logger.info(f"Reached max jobs limit: {max_jobs}")
                    return all_jobs[:max_jobs]

                if raw_count < JOBS_PER_PAGE:
                    logger.info("Short page at offset=%d — end of results", offset)
                    natural_stop = True
                    break

                hits = result.get("hits")
                if isinstance(hits, int) and offset + JOBS_PER_PAGE >= hits:
                    logger.info("Reached reported total (hits=%d)", hits)
                    natural_stop = True
                    break

                await self._random_delay()

            if not natural_stop:
                logger.warning(
                    "amazon: hit MAX_PAGES=%d cap at offset=%d (%d jobs collected); "
                    "results may be truncated",
                    MAX_PAGES, offset, len(all_jobs),
                )
        finally:
            await page.close()

        logger.info(
            f"Completed Amazon scrape for '{search_query}': {len(all_jobs)} jobs collected"
        )
        return all_jobs

    # ---- Details (pass-through) -----------------------------------------

    async def scrape_job_details_streaming(
        self,
        job_cards: List[Dict[str, Any]],
    ) -> AsyncIterator[Dict[str, Any]]:
        """Yield cards unchanged — Amazon's list payload is already complete.

        Overriding is mandatory, not an optimisation. The BaseScraper
        implementation opens a page and calls ``extract_job_details`` once per
        job with a 2-5s delay between each: for a ~1,300 job board that is
        45-110 minutes of pure waiting for zero additional data, well past
        SCRAPER_TIMEOUT_MINUTES.
        """
        for job_card in job_cards:
            yield job_card

    async def scrape_job_details_batch(
        self, job_cards: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Batch form of the pass-through streaming path."""
        return [job async for job in self.scrape_job_details_streaming(job_cards)]

    # ---- Transformation --------------------------------------------------

    def derive_experience_level(
        self, title: str, job_data: Dict[str, Any]
    ) -> Optional[str]:
        """Best-effort seniority label from the job title.

        Amazon's structured flags (is_intern / university_job / is_manager) are
        null on every row observed live, so they are checked first only for
        forward-compatibility.
        """
        if job_data.get("is_intern"):
            return "Intern"
        if job_data.get("university_job"):
            return "Entry"
        for pattern, level in _EXPERIENCE_PATTERNS:
            if pattern.search(title or ""):
                return level
        return None

    def derive_is_remote_eligible(self, title: str, description: Optional[str]) -> bool:
        """Amazon exposes no remote flag; the title is the only signal."""
        return bool(_REMOTE_RE.search(title or ""))

    def transform_to_job_model(self, job_data: Dict[str, Any]) -> JobListing:
        """Transform a scraped card into the JobListing database model."""
        job_url = job_data.get("job_url", "")
        job_id = job_data.get("id") or extract_job_id_from_url(job_url) or "unknown"
        created_at = get_iso_timestamp()
        title = job_data.get("title", "")
        description = job_data.get("description")

        details = {
            # Read by the backend enrichment monitor via details->>'description'
            "description": description,
            # Denormalised into real columns by shared/database.py
            "experience_level": self.derive_experience_level(title, job_data),
            "is_remote_eligible": self.derive_is_remote_eligible(title, description),
            "department": job_data.get("department"),
            "team": job_data.get("team"),
            "job_family": job_data.get("job_family"),
            "business_category": job_data.get("business_category"),
            "employment_type": job_data.get("job_schedule_type"),
            "city": job_data.get("city"),
            "state": job_data.get("state"),
            "country_code": job_data.get("country_code"),
            "apply_url": job_data.get("apply_url"),
            "raw": job_data,
        }

        return JobListing(
            id=job_id,
            title=title,
            company="amazon",
            location=job_data.get("location"),
            url=job_url,
            source_id=SourceId.AMAZON,
            details=details,
            # Already normalised to YYYY-MM-DD by api_client.parse_posted_date
            posted_on=job_data.get("posted_date"),
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
        """Remove duplicates by requisition id and transform to JobListing."""
        seen_ids = set()
        unique_jobs = []

        for job_data in jobs:
            job_id = job_data.get("id", "")
            if job_id and job_id not in seen_ids:
                seen_ids.add(job_id)
                unique_jobs.append(self.transform_to_job_model(job_data))

        logger.info(
            f"Deduplicated: {len(jobs)} jobs -> {len(unique_jobs)} unique jobs"
        )
        return unique_jobs
