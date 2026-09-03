"""
Core scraping logic for Meta Careers (metacareers.com).

Meta has no standard ATS. Its listings page
(https://www.metacareers.com/jobsearch) is a client-side SPA that hydrates from
a **single GraphQL POST returning the ENTIRE ~890-job catalogue in one shot** —
no pagination, no keyword search. We scrape it with Playwright by attaching a
response handler, navigating once, sniffing every GraphQL POST response, and
mining whichever payload actually carries the job arrays (by SHAPE, not by the
operation/container name — see ``parser``).

**First cut is LIST-ONLY.** ``extract_job_details`` is inert and
``scrape_job_details_streaming`` is a pass-through; ``posted_on`` is ``None`` for
every Meta job (the list query carries no date, same as TikTok).

**An empty or short capture RAISES ``MetaCaptureError`` — it never returns
``[]`` or a partial list.** See ``parser`` for why (the 2026-03-29 mass-closure
class of bug).
"""

import asyncio
import logging
import re
import sys
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from playwright.async_api import Page

# Add shared module to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.base_scraper import BaseScraper
from shared.constants import SourceId
from shared.models import JobListing
from shared.posted_date import effective_posted_date
from shared.utils import get_iso_timestamp

from .config import (
    BODY_READ_TIMEOUT_S,
    DRAIN_MAX_S,
    DRAIN_STABLE_S,
    EXCLUDE_TITLE_KEYWORDS,
    GRAPHQL_URL_SUBSTRING,
    INCLUDE_TITLE_KEYWORDS,
    LIST_URL,
    LOCATION_FILTER,
    NEW_PAGE_TIMEOUT_S,
    PAGE_TIMEOUT_MS,
    POLL_INTERVAL_S,
    RESPONSE_WAIT_S,
)
from .parser import (
    MetaCaptureError,
    _decode_graphql_payload,
    _finalize_capture,
    _SettlePoll,
)

logger = logging.getLogger(__name__)

# Word-boundary matcher for the exclude list. Substring matching here would drop
# real jobs — "HR" matches "T-h-r-eat". See config.py.
_EXCLUDE_RE = re.compile(
    r"(?<![a-z])(?:%s)(?![a-z])"
    % "|".join(re.escape(kw.lower()) for kw in EXCLUDE_TITLE_KEYWORDS)
)

_INCLUDE_KEYWORDS_LOWER = [kw.lower() for kw in INCLUDE_TITLE_KEYWORDS]

# Meta has no keyword search — one page load yields the whole catalogue — so the
# single sentinel query drives exactly one scrape_query call. scrape_query
# ignores the query text.
_SENTINEL_QUERY = "all"


class MetaJobsScraper(BaseScraper):
    """Scraper for metacareers.com (extends BaseScraper)."""

    SOURCE_ID = SourceId.META

    def __init__(self, headless: bool = True, detail_scrape: bool = False):
        super().__init__(headless, detail_scrape)

    # ---- BaseScraper abstract methods -----------------------------------

    def get_company_name(self) -> str:
        """Return company identifier."""
        return "meta"

    def build_search_url(self, search_query: str, page_num: int) -> str:
        """The human-facing listings URL a person opens when debugging.

        Args are ignored — Meta has no keyword search and no pagination; the
        real capture lives in ``scrape_query``.
        """
        return LIST_URL

    async def extract_job_cards(self, page: Page) -> List[Dict[str, Any]]:
        """Thin ABC-satisfier.

        The real capture lives in ``scrape_query`` (which owns the response
        handler + settle poll), so nothing on the run path calls this —
        ``scrape_all_queries`` calls ``scrape_query`` directly. Returns ``[]``
        rather than driving a second, half-instrumented navigation.
        """
        return []

    async def extract_job_details(self, page: Page, job_url: str) -> Dict[str, Any]:
        """Unused — list-only first cut.

        ``scrape_job_details_streaming`` is a pass-through and never calls this.
        Implemented only to satisfy BaseScraper's ABC; returns an empty dict and
        touches nothing on the page.
        """
        return {}

    def get_search_queries(self) -> List[str]:
        """A single sentinel — Meta has no keyword search."""
        return [_SENTINEL_QUERY]

    def filter_job(self, job_title: str) -> bool:
        """Filter by title keywords.

        EXCLUDE uses word boundaries, INCLUDE uses plain substrings — a loose
        EXCLUDE silently discards real listings, whereas a loose INCLUDE only
        lets through an extra role.
        """
        if not job_title:
            return False
        title_lower = job_title.lower()
        if _EXCLUDE_RE.search(title_lower):
            return False
        return any(kw in title_lower for kw in _INCLUDE_KEYWORDS_LOWER)

    def filter_location(self, location: Optional[str]) -> bool:
        """Keep only jobs in the configured country (client-side substring)."""
        if not LOCATION_FILTER:
            return True
        if not location:
            return False
        return LOCATION_FILTER.lower() in location.lower()

    # ---- The GraphQL-sniff capture --------------------------------------

    async def scrape_query(
        self, search_query: str, max_jobs: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Capture Meta's whole catalogue from one GraphQL response.

        Ignores ``search_query`` (Meta has no keyword search). Attaches a
        response handler BEFORE navigating, navigates once, settle-polls until a
        non-empty job array lands and drains, then hands the capture to the pure
        ``_finalize_capture`` (reduce → dedupe → completeness guard). The
        completeness guard runs on the FULL parsed set BEFORE the US/title
        filter, because Meta's ``job_count`` counts the whole returned catalogue.

        Honours ``max_jobs`` by slicing the kept (post-filter) list.

        Raises:
            MetaCaptureError: on an empty or truncated capture — never returns
            ``[]`` or a partial list (would mass-close the board; see parser).
        """
        from playwright.async_api import Error as PlaywrightError

        logger.info("Scraping Meta jobs (single-shot GraphQL capture)")

        captured: List[Dict[str, Any]] = []
        graphql_seen = 0
        nav_error: Optional[BaseException] = None

        # Bound new_page: Playwright's page RPCs take no timeout argument, so a
        # hung driver would block the subprocess indefinitely otherwise.
        try:
            page = await asyncio.wait_for(
                self.context.new_page(), timeout=NEW_PAGE_TIMEOUT_S
            )
        except (TimeoutError, asyncio.TimeoutError) as exc:
            raise MetaCaptureError(
                f"Meta scrape could not open a browser page within "
                f"{NEW_PAGE_TIMEOUT_S:g}s"
            ) from exc

        try:
            async def on_response(resp: Any) -> None:
                """Capture every GraphQL POST payload; select by shape later.

                Runs fire-and-forget inside Playwright's event loop, so it must
                never raise — an escaping exception is invisible to the caller.
                """
                nonlocal graphql_seen
                try:
                    if GRAPHQL_URL_SUBSTRING not in resp.url:
                        return
                    if resp.request.method != "POST":
                        return
                    graphql_seen += 1
                    body = await asyncio.wait_for(
                        resp.text(), timeout=BODY_READ_TIMEOUT_S
                    )
                except (TimeoutError, asyncio.TimeoutError):
                    logger.warning(
                        "Meta GraphQL response body read exceeded %.0fs — "
                        "dropping that capture.",
                        BODY_READ_TIMEOUT_S,
                    )
                    return
                except Exception as exc:  # noqa: BLE001 — handler must not raise
                    # Reading a body races page/context teardown, which raises a
                    # Playwright Error rather than anything more specific.
                    logger.debug("Meta response handler ignored %r", exc)
                    return
                payload = _decode_graphql_payload(body)
                if payload is not None:
                    captured.append(payload)

            page.on("response", on_response)

            try:
                await page.goto(
                    LIST_URL, wait_until="networkidle", timeout=PAGE_TIMEOUT_MS
                )
            except PlaywrightError as exc:
                # networkidle times out on slow CDNs even when the GraphQL
                # response already landed, so we don't give up here — remember
                # the error and only surface it if the capture came up empty.
                nav_error = exc

            # Belt-and-braces: networkidle can fire before the results body is
            # decoded. The settle poll waits for a NON-EMPTY job array (an empty
            # strip resolving first must not tear the context down mid-read),
            # then drains briefly. Total iterations bounded by both budgets.
            poll = _SettlePoll(
                wait_polls=int(RESPONSE_WAIT_S / POLL_INTERVAL_S),
                drain_polls=int(DRAIN_MAX_S / POLL_INTERVAL_S),
                stable_polls=int(DRAIN_STABLE_S / POLL_INTERVAL_S),
            )
            while not poll.should_stop(captured):
                await asyncio.sleep(POLL_INTERVAL_S)
        finally:
            await page.close()

        # Pure from here — reduce → dedupe → completeness guard → raise-or-return.
        cards = _finalize_capture(
            captured, graphql_seen=graphql_seen, nav_error=nav_error
        )

        # Client-side US + title filter, applied AFTER the completeness guard so
        # a legitimately narrow kept count never false-trips it.
        kept: List[Dict[str, Any]] = []
        seen_ids: set = set()
        for card in cards:
            job_id = card.get("id")
            if not job_id or job_id in seen_ids:
                continue
            seen_ids.add(job_id)
            if not self.filter_location(card.get("location")):
                continue
            if not self.filter_job(card.get("title", "")):
                continue
            kept.append(card)

        logger.info(
            "Meta scrape: %d parsed, %d kept after US/title filter",
            len(cards),
            len(kept),
        )

        if max_jobs and len(kept) >= max_jobs:
            return kept[:max_jobs]
        return kept

    # ---- Details (pass-through) -----------------------------------------

    async def scrape_job_details_streaming(
        self,
        job_cards: List[Dict[str, Any]],
    ) -> AsyncIterator[Dict[str, Any]]:
        """Yield cards unchanged — list-only first cut.

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

    def transform_to_job_model(self, job_data: Dict[str, Any]) -> JobListing:
        """Transform a scraped card into the JobListing database model."""
        job_url = job_data.get("job_url", "")
        job_id = job_data.get("id") or "unknown"
        created_at = get_iso_timestamp()
        title = job_data.get("title", "")
        location = job_data.get("location")

        details = {
            # list-only ⇒ no description scraped; read by the enrichment monitor
            # via details->>'description'.
            "description": None,
            "department": job_data.get("department"),
            "apply_url": job_url,
            "raw": job_data.get("raw"),
        }

        return JobListing(
            id=job_id,
            title=title,
            company="meta",
            location=location,
            url=job_url,
            source_id=SourceId.META,
            details=details,
            # Meta's list query carries no posted/created date at all. Leaving
            # this None is deliberate: first_seen_at is the only honest signal.
            posted_on=None,
            created_at=created_at,
            closed_on=None,
            status="OPEN",
            has_matched=False,
            ai_metadata={},
            # THE EFFECTIVE POSTED DATE — which for Meta is always first sight,
            # because ``posted_on`` above is always None. Routed through the
            # shared helper anyway so this scraper STATES the rule rather than
            # coinciding with it: the day Meta's list payload grows a date
            # field, one line changes, not two.
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
