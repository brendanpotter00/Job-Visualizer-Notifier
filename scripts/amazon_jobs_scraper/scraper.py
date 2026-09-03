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
from shared.posted_date import effective_posted_date
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
from .api_client import JobSearchError, fetch_search_results
from .parser import extract_job_id_from_url

logger = logging.getLogger(__name__)

# Word-boundary matcher for the exclude list. Substring matching here would
# drop real jobs — "HR" matches "T-h-r-eat Intelligence". See config.py.
#
# The empty-list guard is load-bearing. With no keywords the alternation
# degenerates to `(?:)`, which matches the empty string at every non-letter
# boundary — so emptying the list to "disable excludes" would instead reject
# almost the entire board (verified: "Software Development Engineer, EC2"
# fails). An empty list must mean "exclude nothing".
_NEVER_MATCHES = r"(?!)"
_EXCLUDE_RE = re.compile(
    (
        r"(?<![a-z])(?:%s)(?![a-z])"
        % "|".join(re.escape(kw.lower()) for kw in EXCLUDE_TITLE_KEYWORDS)
    )
    if EXCLUDE_TITLE_KEYWORDS
    else _NEVER_MATCHES
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
    # The `&` lookahead keeps "I&T" (Integration & Test) from reading as a
    # roman-numeral level: "Software I&T Engineer, Amazon Leo" is not entry-level.
    (re.compile(r"\bi\b(?!\s*&)", re.I), "Entry"),
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

        EXCLUDE is matched only against the **role segment** — everything before
        the first comma. Amazon's title convention is "<Role>, <Team/Org>", and
        matching the whole string lets an org name veto a real engineering req:
        the live title "Principal Engineer, Amazon | Multiple Locations, USA,
        Global Specialty Recruiting Team" was dropped because its *team* name
        contains "Recruiting". INCLUDE still reads the full title, since a
        keyword anywhere in it is evidence for keeping the job.
        """
        if not job_title:
            return False
        title_lower = job_title.lower()
        role_segment = title_lower.split(",", 1)[0]
        if _EXCLUDE_RE.search(role_segment):
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

        Clean stop conditions (all evaluated against the *pre-filter* row count,
        so a page whose titles were all filtered out is never mistaken for the
        end of the results):
          1. the page returned zero rows
          2. the page returned fewer than JOBS_PER_PAGE rows
          3. offset + JOBS_PER_PAGE >= the reported total (`hits`)

        Any other exit — consecutive fetch failures, an error envelope on an
        HTTP 200, or exhausting the page budget — raises ``JobSearchError``
        rather than returning a short list. Returning an incomplete board to the
        incremental lifecycle gets the missing jobs CLOSED; see the comment at
        the raise sites.

        Raises:
            JobSearchError: the scrape ended incomplete.
        """
        logger.info(f"Scraping Amazon jobs for query: '{search_query}'")
        all_jobs: List[Dict[str, Any]] = []
        seen_ids: set = set()
        consecutive_errors = 0
        stop_reason: Optional[str] = None
        last_error: Optional[str] = None
        offset = 0
        filtered_out = 0
        skipped_missing_id = 0
        skipped_missing_title = 0

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
                    last_error = f"{type(exc).__name__}: {exc}"
                    logger.warning(
                        "Error fetching Amazon offset=%d (%d/%d): %s",
                        offset, consecutive_errors, MAX_CONSECUTIVE_ERRORS, exc,
                    )
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        stop_reason = "consecutive_errors"
                        break
                    await self._random_delay()
                    continue

                page_idx += 1

                # An HTTP 200 can still carry an error envelope
                # ({"error": "...", "jobs": null}) — e.g. "Cannot return more
                # than 10000 results at once", or rate limiting. Without this
                # check it becomes raw_count == 0, which reads as a clean end of
                # results and silently truncates the run. The error is parsed and
                # returned by the client; the bug was never reading it here.
                api_error = result.get("error")
                if api_error:
                    stop_reason = "api_error"
                    last_error = str(api_error)
                    break

                skipped_missing_id += result.get("skipped_missing_id", 0) or 0
                skipped_missing_title += result.get("skipped_missing_title", 0) or 0

                raw_count = result["raw_count"]
                if raw_count == 0:
                    logger.info("No more jobs returned at offset=%d", offset)
                    stop_reason = "empty_page"
                    break

                new_this_page = 0
                kept_this_page = 0
                for card in result["jobs"]:
                    job_id = card.get("id")
                    if not job_id or job_id in seen_ids:
                        continue
                    seen_ids.add(job_id)
                    new_this_page += 1
                    if self.filter_job(card.get("title", "")):
                        all_jobs.append(card)
                        kept_this_page += 1
                    else:
                        filtered_out += 1

                logger.info(
                    "offset=%d: %d rows, %d new, %d kept (total %d)",
                    offset, raw_count, new_this_page, kept_this_page, len(all_jobs),
                )

                if max_jobs and len(all_jobs) >= max_jobs:
                    logger.info(f"Reached max jobs limit: {max_jobs}")
                    return all_jobs[:max_jobs]

                if raw_count < JOBS_PER_PAGE:
                    logger.info("Short page at offset=%d — end of results", offset)
                    stop_reason = "short_page"
                    break

                hits = result.get("hits")
                if isinstance(hits, int) and offset + JOBS_PER_PAGE >= hits:
                    logger.info("Reached reported total (hits=%d)", hits)
                    stop_reason = "reached_total"
                    break

                await self._random_delay()
            else:
                # `while` exhausted without break — the page budget ran out.
                stop_reason = "page_cap"
        finally:
            await page.close()

        if skipped_missing_id or skipped_missing_title:
            logger.warning(
                "amazon: dropped %d row(s) with no id_icims and %d with no title "
                "across the run — a field rename upstream looks exactly like this",
                skipped_missing_id, skipped_missing_title,
            )

        # A run that ended for any reason other than a clean end-of-results is
        # INCOMPLETE, and an incomplete list handed to the incremental lifecycle
        # is indistinguishable from "these jobs are gone" — it closes them.
        # The partial_scrape guard cannot be relied on to catch this: it trips
        # below ~85%, while losing one Amazon page is only ~8% of the board, so
        # a single-page truncation lands squarely in its blind spot and reaches
        # close-detection. Raising instead means run_incremental_scrape records
        # the failure and re-raises without running the destructive phases.
        # See docs/incidents/2026-03-29-mass-job-closure.md.
        if stop_reason == "consecutive_errors":
            raise JobSearchError(
                f"Amazon scrape aborted after {MAX_CONSECUTIVE_ERRORS} consecutive "
                f"fetch failures at offset={offset}; {len(all_jobs)} jobs had been "
                f"collected and are being discarded rather than reported as "
                f"complete. Last error: {last_error}"
            )
        if stop_reason == "api_error":
            raise JobSearchError(
                f"Amazon search.json returned an error envelope at offset={offset} "
                f"after {len(all_jobs)} jobs: {last_error}"
            )
        if stop_reason == "page_cap":
            raise JobSearchError(
                f"Amazon scrape hit the MAX_PAGES={MAX_PAGES} cap at offset={offset} "
                f"with {len(all_jobs)} jobs collected — the board is larger than the "
                f"page budget. Raise MAX_PAGES; do not ship a truncated run."
            )

        logger.info(
            "Completed Amazon scrape for '%s': %d jobs collected (%d filtered out by "
            "title, stop=%s)",
            search_query, len(all_jobs), filtered_out, stop_reason,
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
        """Transform a scraped card into the JobListing database model.

        Raises:
            ValueError: the card carries no usable id.
        """
        job_url = job_data.get("job_url", "")
        job_id = job_data.get("id") or extract_job_id_from_url(job_url)
        if not job_id:
            # Never fabricate an id. `job_listings` is keyed on the composite PK
            # (source_id, id), so two id-less cards sharing a placeholder collapse
            # into one row that flip-flops between two different real jobs — and
            # publishes that garbage to users. BatchWriter.add_job isolates a
            # raising transform: the row is counted and skipped, the run survives.
            raise ValueError(
                f"Amazon card has no id_icims and no id recoverable from its URL "
                f"({job_url!r}); refusing to fabricate one"
            )
        created_at = get_iso_timestamp()
        title = job_data.get("title", "")
        description = job_data.get("description")
        # Already normalised to YYYY-MM-DD by api_client.parse_posted_date.
        posted_on = job_data.get("posted_date")

        details = {
            # Read by the backend enrichment monitor via details->>'description'
            "description": description,
            # Denormalised into real columns by shared/database.py
            "experience_level": self.derive_experience_level(title, job_data),
            "is_remote_eligible": self.derive_is_remote_eligible(title, description),
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
            posted_on=posted_on,
            created_at=created_at,
            closed_on=None,
            status="OPEN",
            has_matched=False,
            ai_metadata={},
            # THE EFFECTIVE POSTED DATE, not literally "when we first saw it"
            # (POSTED-DATE-PLAN.md §2, D9/D10). Same rule BatchWriter.add_job
            # applies on the way to the DB — kept in step here so the model a
            # caller inspects says the same thing as the row that gets written.
            first_seen_at=effective_posted_date(posted_on, created_at),
            last_seen_at=created_at,
            consecutive_misses=0,
            details_scraped=False,
        )

    def deduplicate_jobs(self, jobs: List[Dict[str, Any]]) -> List[JobListing]:
        """Remove duplicates by requisition id and transform to JobListing."""
        seen_ids = set()
        unique_jobs = []
        duplicates = 0
        missing_id = 0

        for job_data in jobs:
            job_id = job_data.get("id", "")
            if not job_id:
                # Counted separately from duplicates: a run of these means the
                # id field was renamed upstream, which is a very different
                # problem from the sort=recent page overlap.
                missing_id += 1
                continue
            if job_id in seen_ids:
                duplicates += 1
                continue
            seen_ids.add(job_id)
            unique_jobs.append(self.transform_to_job_model(job_data))

        logger.info(
            "Deduplicated: %d jobs -> %d unique (%d cross-page duplicates, "
            "%d dropped for missing id)",
            len(jobs), len(unique_jobs), duplicates, missing_id,
        )
        if missing_id:
            logger.warning(
                "amazon: %d card(s) had no id and were dropped before transform",
                missing_id,
            )
        return unique_jobs
