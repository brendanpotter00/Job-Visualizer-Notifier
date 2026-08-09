"""
API client for Amazon Jobs' public search endpoint.

Amazon serves job search over a plain JSON endpoint::

    GET https://www.amazon.jobs/en/search.json
        ?offset=0&result_limit=100&sort=recent
        &country=USA&base_query=software+engineer

The list response embeds the full HTML description plus
``basic_qualifications`` and ``preferred_qualifications``, so — unlike Google,
Apple, and Microsoft — this scraper never performs a per-job detail fetch.

All requests run *inside* the browser via ``page.evaluate`` (the repo has no
HTTP client dependency; see ``scripts/requirements.txt``). Because the endpoint
returns no ``Access-Control-Allow-Origin`` header, the page must already be on
an ``amazon.jobs`` origin before the fetch runs — see
``AmazonJobsScraper._establish_session``.
"""

import asyncio
import html
import logging
import re
from datetime import timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import dateutil.parser
from playwright.async_api import Page

from .config import BASE_URL, COUNTRY, JOBS_PER_PAGE, SEARCH_PATH, SORT

logger = logging.getLogger(__name__)

# Bound the in-browser fetch. Mirrors Apple/Microsoft — the double bound
# (in-page AbortController + Python-side asyncio.wait_for) exists because an
# unbounded page.evaluate once hung a scraper silently for 90 minutes. See
# docs/implementations/appleScraperHangFix/PLAN.md.
_FETCH_BROWSER_TIMEOUT_MS = 15_000
_FETCH_OUTER_TIMEOUT_S = 20.0

_JSON_HEADERS = {"Accept": "application/json"}

# JS payload that runs inside the page context.
#
# MUST be a raw string: the \u escapes below are for JavaScript, not Python.
#
# Deliberately NOT `r.json()`. Amazon intermittently embeds raw control bytes
# (\x01) inside description HTML. V8's JSON.parse rejects those with
# "Bad control character in string literal", exactly as Python's strict
# json.loads does (the sibling job-watcher adapter works around it with
# json.loads(..., strict=False)). Left unhandled, every page would raise,
# the consecutive-error bail would trip, and a partial scrape would falsely
# close jobs via the consecutive-misses lifecycle.
#
# The fast path parses the bytes untouched — that is 100% of pages observed on
# 2026-08-09 — and only a parse failure triggers the sanitising retry, so a
# healthy payload is never mutated.
_FETCH_JS = r"""
async ({url, timeoutMs, headers}) => {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
        const r = await fetch(url, { headers, signal: ctrl.signal, credentials: 'same-origin' });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const text = await r.text();
        try {
            return { data: JSON.parse(text), sanitized: false };
        } catch (e) {
            // Tab/LF/CR become a space rather than vanishing: deleting a real
            // newline inside a string would word-join "line one\nline two".
            // Every other C0 control byte is junk and is dropped.
            const cleaned = text
                .replace(/[\u0009\u000A\u000D]/g, ' ')
                .replace(/[\u0000-\u001F]/g, '');
            return { data: JSON.parse(cleaned), sanitized: true };
        }
    } finally {
        clearTimeout(t);
    }
}
"""

# Block-level tags become newlines; everything else is dropped.
_HTML_BLOCK_TAG_RE = re.compile(
    r"</?\s*(?:br|p|div|li|ul|ol|tr|h[1-6])\b[^<>]*?/?>", re.IGNORECASE
)
# NOTE: the leading ASCII-letter requirement is load-bearing. The looser
# `<[^>]+>` used elsewhere in this repo spans from a literal "<" in prose to
# the ">" of the next real tag, destroying text. Live Amazon job 10490591
# contains "P99 < 1 second at 40 TPS ... P99 < 100ms for profile serving<br/>";
# the loose pattern eats the whole sentence. `[^<>]` also stops a match from
# ever spanning another tag.
_HTML_TAG_RE = re.compile(r"</?[a-zA-Z][a-zA-Z0-9]*(?:\s[^<>]*?)?/?>")
_HORIZONTAL_WS_RE = re.compile(r"[ \t ]+")
_EXCESS_NEWLINES_RE = re.compile(r"\n{3,}")


class JobSearchError(Exception):
    """Raised when the job search API fails"""
    pass


class JobDetailsFetchError(Exception):
    """Raised when fetching job details fails.

    Defined for symmetry with the Apple/Microsoft api_client surface. Amazon's
    list payload already carries the description, so nothing in this package
    raises it today.
    """
    pass


def strip_html(content: Optional[str]) -> Optional[str]:
    """Convert Amazon's description HTML into readable plain text."""
    if not content:
        return None

    text = _HTML_BLOCK_TAG_RE.sub("\n", content)
    text = _HTML_TAG_RE.sub("", text)
    text = html.unescape(text)
    text = _HORIZONTAL_WS_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _EXCESS_NEWLINES_RE.sub("\n\n", text).strip()
    return text or None


def combine_description(job: Dict[str, Any]) -> Optional[str]:
    """Concatenate the three description sources Amazon returns inline."""
    parts: List[str] = []
    for field in ("description", "basic_qualifications", "preferred_qualifications"):
        stripped = strip_html(job.get(field))
        if stripped:
            parts.append(stripped)
    return "\n\n".join(parts) if parts else None


def parse_posted_date(value: Optional[str]) -> Optional[str]:
    """Normalise Amazon's ``posted_date`` into the stored ``posted_on`` shape.

    Amazon serves a date-only English string ("August  8, 2026" — note the
    double space) with no time-of-day and no timezone. We deliberately return a
    10-character ``YYYY-MM-DD`` rather than stamping UTC midnight: midnight UTC
    renders as the *previous* evening for every user west of UTC, which made
    every Amazon job appear a day early in the sibling repo.

    Forward-compat: if Amazon ever emits a tz-aware value we normalise the
    instant to UTC so the stored-timestamp convention still holds.

    A parse failure warns rather than silently flattening every row to None.
    """
    if not value:
        return None
    try:
        parsed = dateutil.parser.parse(value)
    except (ValueError, TypeError, OverflowError):
        logger.warning("amazon: could not parse posted_date %r", value)
        return None
    if parsed.tzinfo is None:
        return parsed.date().isoformat()
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def extract_location(job: Dict[str, Any]) -> Optional[str]:
    """Prefer Amazon's normalised location, falling back to the raw one."""
    return job.get("normalized_location") or job.get("location") or None


def get_job_url(job_path: str) -> str:
    """Build the canonical job URL from Amazon's relative ``job_path``."""
    if not job_path:
        return BASE_URL
    if job_path.startswith("http://") or job_path.startswith("https://"):
        return job_path
    return f"{BASE_URL}{job_path}"


def build_search_api_url(query: str, offset: int = 0) -> str:
    """Build the search.json URL.

    Owns query-string encoding — ``base_query`` contains spaces and must not be
    interpolated raw.
    """
    params = urlencode(
        {
            "offset": offset,
            "result_limit": JOBS_PER_PAGE,
            "sort": SORT,
            "country": COUNTRY,
            "base_query": query,
        }
    )
    return f"{BASE_URL}{SEARCH_PATH}?{params}"


def _parse_job_from_search(job: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Convert one raw API row into a standardised job card.

    Returns None when the row is unusable (no requisition id, or no title); the
    caller counts those so a schema change surfaces in the logs.
    """
    if not isinstance(job, dict):
        return None

    # id_icims is the numeric requisition id. `id` is a GUID — not the id we
    # key on, and not the one that appears in the canonical URL.
    job_id = str(job.get("id_icims") or "")
    if not job_id:
        return None

    title = job.get("title")
    if not title:
        return None

    return {
        "id": job_id,
        "title": title,
        "job_url": get_job_url(job.get("job_path") or ""),
        "location": extract_location(job),
        "posted_date": parse_posted_date(job.get("posted_date")),
        "department": job.get("job_category"),
        "description": combine_description(job),
        "team": (job.get("team") or {}).get("label") if isinstance(job.get("team"), dict) else None,
        "job_schedule_type": job.get("job_schedule_type"),
        "business_category": job.get("business_category"),
        "job_family": job.get("job_family"),
        "city": job.get("city"),
        "state": job.get("state"),
        "country_code": job.get("country_code"),
        "apply_url": job.get("url_next_step"),
        "is_intern": job.get("is_intern"),
        "university_job": job.get("university_job"),
        "is_manager": job.get("is_manager"),
        "company": "amazon",
    }


def _parse_search_response(data: Dict[str, Any]) -> Dict[str, Any]:
    """Parse a search.json payload into cards plus pagination metadata.

    ``raw_count`` is the number of rows Amazon returned *before* any filtering.
    Pagination decisions must use it rather than ``len(jobs)``: a page whose
    rows all failed validation is not a short page, and conflating the two
    truncates the scrape.
    """
    if not isinstance(data, dict):
        raise JobSearchError(f"Unexpected search payload type: {type(data)!r}")

    error = data.get("error")
    if error:
        # e.g. result_limit > 100 answers 200 with jobs: null and this string.
        logger.warning("amazon: search payload carried error %r", error)

    # `or []` is mandatory: Amazon answers an over-large result_limit with
    # "jobs": null, not an empty list.
    raw_jobs = data.get("jobs") or []
    if not isinstance(raw_jobs, list):
        raw_jobs = []

    cards: List[Dict[str, Any]] = []
    skipped_missing_id = 0
    skipped_missing_title = 0

    for row in raw_jobs:
        card = _parse_job_from_search(row)
        if card is not None:
            cards.append(card)
        elif isinstance(row, dict) and not str(row.get("id_icims") or ""):
            skipped_missing_id += 1
        else:
            skipped_missing_title += 1

    if skipped_missing_id:
        logger.warning("amazon: skipped %d job(s) missing id_icims", skipped_missing_id)
    if skipped_missing_title:
        logger.warning("amazon: skipped %d job(s) missing title", skipped_missing_title)

    hits = data.get("hits")
    return {
        "jobs": cards,
        "raw_count": len(raw_jobs),
        "hits": hits if isinstance(hits, int) else None,
        "error": error,
        "skipped_missing_id": skipped_missing_id,
        "skipped_missing_title": skipped_missing_title,
    }


async def fetch_search_results(
    page: Page,
    query: str,
    offset: int = 0,
) -> Dict[str, Any]:
    """Fetch one page of Amazon search results.

    Args:
        page: Playwright page, already on an amazon.jobs origin (CORS).
        query: free-text ``base_query`` (e.g. "software engineer").
        offset: pagination offset in steps of ``JOBS_PER_PAGE``.

    Returns:
        The dict produced by ``_parse_search_response``.

    Raises:
        JobSearchError: on timeout, HTTP failure, or unparseable payload.
    """
    api_url = build_search_api_url(query, offset)

    try:
        response = await asyncio.wait_for(
            page.evaluate(
                _FETCH_JS,
                {
                    "url": api_url,
                    "timeoutMs": _FETCH_BROWSER_TIMEOUT_MS,
                    "headers": _JSON_HEADERS,
                },
            ),
            timeout=_FETCH_OUTER_TIMEOUT_S,
        )
    except asyncio.TimeoutError as exc:
        logger.error(
            "Search outer timeout (offset=%d) after %.0fs", offset, _FETCH_OUTER_TIMEOUT_S
        )
        raise JobSearchError(
            f"Search timed out after {_FETCH_OUTER_TIMEOUT_S}s"
        ) from exc
    except Exception as exc:
        logger.error("Error fetching Amazon search results (offset=%d): %s", offset, exc)
        raise JobSearchError(f"Failed to fetch search results: {exc}") from exc

    payload = response.get("data") if isinstance(response, dict) else None
    if isinstance(response, dict) and response.get("sanitized"):
        # Visible on purpose: this is the control-byte failure mode recurring.
        logger.warning(
            "amazon: search payload at offset=%d needed control-character "
            "sanitising before it would parse",
            offset,
        )

    return _parse_search_response(payload if payload is not None else response)
