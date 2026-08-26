"""
Core scraping logic for TikTok Jobs (lifeattiktok.com).

TikTok exposes a public JSON search endpoint whose rows already contain the
full description, so this scraper is API-only and performs **no** per-job
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
from shared.posted_date import effective_posted_date
from shared.utils import get_iso_timestamp

from .config import (
    EXCLUDE_TITLE_KEYWORDS,
    INCLUDE_TITLE_KEYWORDS,
    JOBS_PER_PAGE,
    LOCATION_FILTER,
    MAX_CONSECUTIVE_ERRORS,
    MAX_PAGES,
    PAGE_LOAD_TIMEOUT,
    REQUEST_DELAY_MAX,
    REQUEST_DELAY_MIN,
    SEARCH_QUERIES,
    SESSION_ESTABLISH_DELAY,
    SESSION_PATH,
    SITE_URL,
)
from .api_client import JobSearchError, fetch_search_results
from .parser import extract_job_id_from_url

logger = logging.getLogger(__name__)

# Word-boundary matcher for the exclude list. Substring matching here would
# drop real jobs — "HR" matches "T-h-r-eat". See config.py.
_EXCLUDE_RE = re.compile(
    r"(?<![a-z])(?:%s)(?![a-z])"
    % "|".join(re.escape(kw.lower()) for kw in EXCLUDE_TITLE_KEYWORDS)
)

_INCLUDE_KEYWORDS_LOWER = [kw.lower() for kw in INCLUDE_TITLE_KEYWORDS]

# lifeattiktok.com is a SPA that keeps polling after load, so the base class's
# wait_until="networkidle" would burn its full timeout before falling back.
_TIKTOK_GOTO_WAIT_UNTIL = "domcontentloaded"

# Seniority heuristics, most specific first. TikTok's structured
# recruit_type.en_name distinguishes Intern from Regular (95/282 on the live
# US software set), and the title supplies the rest.
_EXPERIENCE_PATTERNS = [
    (re.compile(r"\bintern(ship)?\b", re.I), "Intern"),
    (re.compile(r"\b(graduate|new grad(uate)?|campus)\b", re.I), "Entry"),
    (re.compile(r"\b(principal|distinguished|staff|director|head of)\b", re.I), "Principal"),
    (re.compile(r"\b(sr\.?|senior|lead|tech lead)\b", re.I), "Senior"),
]

_REMOTE_RE = re.compile(r"\b(remote|virtual|work from home|telecommute)\b", re.I)


class TikTokJobsScraper(BaseScraper):
    """Scraper for lifeattiktok.com (extends BaseScraper)"""

    SOURCE_ID = SourceId.TIKTOK

    def __init__(self, headless: bool = True, detail_scrape: bool = False):
        super().__init__(headless, detail_scrape)

    async def _random_delay(self):
        """Override to use TikTok-specific delay configuration"""
        delay = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
        logger.debug(f"Waiting {delay:.2f} seconds before next request")
        await asyncio.sleep(delay)

    async def navigate_to_page(self, page: Page, url: str, timeout: int = 30000):
        """TikTok-specific navigation: skip networkidle waiting.

        Mirrors the base class's single-retry resilience so a transient blip
        doesn't leave the page on about:blank — which would make every
        subsequent in-page fetch fail CORS.
        """
        try:
            await page.goto(url, wait_until=_TIKTOK_GOTO_WAIT_UNTIL, timeout=timeout)
        except Exception as exc:
            logger.warning(f"Error navigating to {url}: {exc}, retrying...")
            await page.goto(url, wait_until=_TIKTOK_GOTO_WAIT_UNTIL, timeout=timeout)

    # ---- BaseScraper abstract methods -----------------------------------

    def get_company_name(self) -> str:
        """Return company identifier"""
        return "tiktok"

    def build_search_url(self, search_query: str, page_num: int) -> str:
        """Build the human-facing TikTok search URL.

        This is the page a human opens when debugging; the scraper itself POSTs
        to the JSON endpoint via ``api_client.fetch_search_results``.
        """
        return f"{SITE_URL}{SESSION_PATH}?keyword={quote_plus(search_query)}"

    async def extract_job_cards(self, page: Page) -> List[Dict[str, Any]]:
        """Extract job cards for the first page of results.

        Pagination calls ``fetch_search_results`` directly; this exists to
        satisfy the BaseScraper contract and give the API path a named entry.
        """
        result = await fetch_search_results(page, SEARCH_QUERIES[0], 0)
        return result.get("jobs", [])

    async def extract_job_details(self, page: Page, job_url: str) -> Dict[str, Any]:
        """Unused — TikTok's list payload already carries the description.

        ``scrape_job_details_streaming`` is a pass-through and never calls
        this. Implemented only to satisfy BaseScraper's ABC. Returns an empty
        dict so a future refactor routing through the base-class streaming path
        degrades to the card unchanged rather than raising.
        """
        return {}

    def get_search_queries(self) -> List[str]:
        """Return search queries for TikTok"""
        return SEARCH_QUERIES

    def filter_job(self, job_title: str) -> bool:
        """Filter by title keywords.

        EXCLUDE uses word boundaries, INCLUDE uses plain substrings — a loose
        EXCLUDE silently discards real listings, whereas a loose INCLUDE only
        lets through an extra role the keyword search already surfaced.
        """
        if not job_title:
            return False
        title_lower = job_title.lower()
        if _EXCLUDE_RE.search(title_lower):
            return False
        return any(kw in title_lower for kw in _INCLUDE_KEYWORDS_LOWER)

    def filter_location(self, location: Optional[str]) -> bool:
        """Keep only jobs in the configured country.

        Applied client-side: the API's ``location_code_list`` takes city codes,
        and a country code silently returns zero results (see config).
        """
        if not LOCATION_FILTER:
            return True
        if not location:
            return False
        return LOCATION_FILTER.lower() in location.lower()

    # ---- Session + pagination -------------------------------------------

    async def _establish_session(self, page: Page) -> None:
        """Navigate to lifeattiktok.com before issuing in-page fetches.

        Load-bearing, not a nicety: the search endpoint sends no
        Access-Control-Allow-Origin header, so a fetch() issued from any other
        origin (including about:blank) is blocked by CORS.
        """
        await self.navigate_to_page(page, f"{SITE_URL}{SESSION_PATH}", PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(SESSION_ESTABLISH_DELAY)

    async def scrape_query(
        self, search_query: str, max_jobs: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Scrape all pages for one search query.

        Stop conditions (all evaluated against the *pre-filter* row count, so a
        page whose rows were all filtered out is never mistaken for the end of
        the results):
          1. the page returned zero rows
          2. the page returned fewer than JOBS_PER_PAGE rows
          3. offset + JOBS_PER_PAGE >= the reported total (`count`)

        Any other exit — exhausted retries or the page budget — is INCOMPLETE
        and raises ``JobSearchError``; see the guard below the loop.

        Raises:
            JobSearchError: on exhausted retries or an exhausted page budget.
        """
        logger.info(f"Scraping TikTok jobs for query: '{search_query}'")
        all_jobs: List[Dict[str, Any]] = []
        seen_ids: set = set()
        consecutive_errors = 0
        stop_reason: Optional[str] = None
        last_error: Optional[str] = None
        offset = 0

        page = await self.context.new_page()

        try:
            await self._establish_session(page)

            # A `while` loop, not `for page_idx in range(...)`: on error we must
            # retry the SAME offset, and `continue` inside a for-loop would
            # advance it, silently dropping 100 jobs. page_idx only advances
            # after a successful fetch; consecutive_errors bounds the retries.
            page_idx = 0
            while page_idx < MAX_PAGES:
                offset = page_idx * JOBS_PER_PAGE

                try:
                    result = await fetch_search_results(page, search_query, offset)
                    consecutive_errors = 0
                except Exception as exc:
                    consecutive_errors += 1
                    last_error = f"{type(exc).__name__}: {exc}"
                    logger.warning(
                        "Error fetching TikTok offset=%d (%d/%d): %s",
                        offset, consecutive_errors, MAX_CONSECUTIVE_ERRORS, exc,
                    )
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        stop_reason = "consecutive_errors"
                        break
                    await self._random_delay()
                    continue

                page_idx += 1
                raw_count = result["raw_count"]
                if raw_count == 0:
                    logger.info("No more jobs returned at offset=%d", offset)
                    stop_reason = "empty_page"
                    break

                kept_this_page = 0
                for card in result["jobs"]:
                    job_id = card.get("id")
                    if not job_id or job_id in seen_ids:
                        continue
                    seen_ids.add(job_id)
                    if not self.filter_location(card.get("location")):
                        continue
                    if not self.filter_job(card.get("title", "")):
                        continue
                    all_jobs.append(card)
                    kept_this_page += 1

                logger.info(
                    "offset=%d: %d rows, %d kept (total %d)",
                    offset, raw_count, kept_this_page, len(all_jobs),
                )

                if max_jobs and len(all_jobs) >= max_jobs:
                    logger.info(f"Reached max jobs limit: {max_jobs}")
                    return all_jobs[:max_jobs]

                if raw_count < JOBS_PER_PAGE:
                    logger.info("Short page at offset=%d — end of results", offset)
                    stop_reason = "short_page"
                    break

                total = result.get("total")
                if isinstance(total, int) and offset + JOBS_PER_PAGE >= total:
                    logger.info("Reached reported total (count=%d)", total)
                    stop_reason = "reached_total"
                    break

                await self._random_delay()
            else:
                # `while` exhausted without break — the page budget ran out.
                stop_reason = "page_cap"
        finally:
            await page.close()

        # A run that ended for any reason other than a clean end-of-results is
        # INCOMPLETE, and an incomplete list handed to the incremental lifecycle
        # is indistinguishable from "these jobs are gone" — it closes them.
        # The partial_scrape guard cannot be relied on to catch this: it trips
        # below ~85%, while losing one TikTok page is only ~13% of the kept
        # board, so a single-page truncation lands squarely in its blind spot
        # and reaches close-detection. Raising instead means
        # run_incremental_scrape records the failure and re-raises without
        # running the destructive phases.
        # See docs/incidents/2026-03-29-mass-job-closure.md.
        if stop_reason == "consecutive_errors":
            raise JobSearchError(
                f"TikTok scrape aborted after {MAX_CONSECUTIVE_ERRORS} consecutive "
                f"fetch failures at offset={offset}; {len(all_jobs)} jobs had been "
                f"collected and are being discarded rather than reported as "
                f"complete. Last error: {last_error}"
            )
        if stop_reason == "page_cap":
            raise JobSearchError(
                f"TikTok scrape hit the MAX_PAGES={MAX_PAGES} cap at offset={offset} "
                f"with {len(all_jobs)} jobs collected — the board is larger than the "
                f"page budget. Raise MAX_PAGES; do not ship a truncated run."
            )

        logger.info(
            f"Completed TikTok scrape for '{search_query}': {len(all_jobs)} jobs collected"
        )
        return all_jobs

    # ---- Details (pass-through) -----------------------------------------

    async def scrape_job_details_streaming(
        self,
        job_cards: List[Dict[str, Any]],
    ) -> AsyncIterator[Dict[str, Any]]:
        """Yield cards unchanged — TikTok's list payload is already complete.

        Overriding is mandatory, not an optimisation. The BaseScraper
        implementation opens a page and calls ``extract_job_details`` once per
        job with a 2-5s delay between each, for zero additional data.
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
        """Best-effort seniority label.

        ``recruit_type`` is TikTok's own structured signal and is authoritative
        for interns; the title supplies the remaining gradations.
        """
        recruit_type = (job_data.get("recruit_type") or "").strip().lower()
        if recruit_type == "intern":
            return "Intern"
        for pattern, level in _EXPERIENCE_PATTERNS:
            if pattern.search(title or ""):
                return level
        return None

    def derive_is_remote_eligible(self, title: str, location: Optional[str]) -> bool:
        """TikTok exposes no remote flag; title and location are the signals."""
        haystack = f"{title or ''} {location or ''}"
        return bool(_REMOTE_RE.search(haystack))

    def transform_to_job_model(self, job_data: Dict[str, Any]) -> JobListing:
        """Transform a scraped card into the JobListing database model."""
        job_url = job_data.get("job_url", "")
        job_id = job_data.get("id") or extract_job_id_from_url(job_url) or "unknown"
        created_at = get_iso_timestamp()
        title = job_data.get("title", "")
        location = job_data.get("location")

        details = {
            # Read by the backend enrichment monitor via details->>'description'
            "description": job_data.get("description"),
            # Denormalised into real columns by shared/database.py
            "experience_level": self.derive_experience_level(title, job_data),
            "is_remote_eligible": self.derive_is_remote_eligible(title, location),
            "department": job_data.get("department"),
            "job_code": job_data.get("job_code"),
            "recruit_type": job_data.get("recruit_type"),
            "job_subject": job_data.get("job_subject"),
            "vacancies": job_data.get("vacancies"),
            "apply_url": job_url,
            "raw": job_data,
        }

        return JobListing(
            id=job_id,
            title=title,
            company="tiktok",
            location=location,
            url=job_url,
            source_id=SourceId.TIKTOK,
            details=details,
            # TikTok's payload carries no posted/created date at all. Leaving
            # this None is deliberate: first_seen_at is the only honest signal
            # for when we became aware of the role.
            posted_on=None,
            created_at=created_at,
            closed_on=None,
            status="OPEN",
            has_matched=False,
            ai_metadata={},
            # THE EFFECTIVE POSTED DATE (POSTED-DATE-PLAN.md §2, D9/D10) — which
            # for TikTok is always first sight, because ``posted_on`` above is
            # always None. Routed through the shared helper anyway so this
            # scraper states the rule rather than coinciding with it: the day
            # TikTok's payload grows a date field, one line changes, not two.
            first_seen_at=effective_posted_date(None, created_at),
            last_seen_at=created_at,
            consecutive_misses=0,
            details_scraped=False,
        )

    def deduplicate_jobs(self, jobs: List[Dict[str, Any]]) -> List[JobListing]:
        """Remove duplicates by job id and transform to JobListing."""
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
