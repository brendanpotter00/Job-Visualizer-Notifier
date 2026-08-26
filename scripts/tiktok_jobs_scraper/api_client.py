"""
API client for TikTok's public careers search endpoint.

TikTok serves job search over a JSON POST endpoint::

    POST https://api.lifeattiktok.com/api/v1/public/supplier/search/job/posts
    headers: content-type: application/json
             website-path: tiktok
    body:    {"limit": 100, "offset": N, "keyword": "software engineer",
              "recruitment_id_list": [], "job_category_id_list": [],
              "subject_id_list": [], "location_code_list": []}

The list response embeds plain-text ``description`` and ``requirement`` blocks
(no HTML), so this scraper never performs a per-job detail fetch.

All requests run *inside* the browser via ``page.evaluate`` (the repo has no
HTTP client dependency). Because the endpoint returns no
``Access-Control-Allow-Origin`` header, the page must already be on the
lifeattiktok.com origin — see ``TikTokJobsScraper._establish_session``.

Two gotchas, both verified live on 2026-08-09:

* Omitting the ``website-path`` header returns **HTTP 400** from the edge.
* The endpoint answers **HTTP 200 with a non-zero ``code``** on payload-level
  errors. Those must raise rather than return partial results — swallowing one
  would let the incremental lifecycle close the whole company over time.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from playwright.async_api import Page

from .config import (
    API_BASE_URL,
    JOBS_PER_PAGE,
    JOB_URL_PREFIX,
    SEARCH_PATH,
    WEBSITE_PATH,
)

logger = logging.getLogger(__name__)

# Bound the in-browser fetch, same double-bound as Apple/Microsoft/Amazon.
_FETCH_BROWSER_TIMEOUT_MS = 15_000
_FETCH_OUTER_TIMEOUT_S = 20.0

_JSON_HEADERS = {
    "content-type": "application/json",
    # REQUIRED — the edge answers HTTP 400 without it.
    "website-path": WEBSITE_PATH,
}

# JS payload that runs inside the page context.
#
# Unlike the GET-based scrapers this issues a POST with a JSON body, so the
# body is passed in and serialised here rather than encoded into the URL.
# Uses r.json() directly: TikTok's payloads are clean (no control bytes
# observed across 716 live jobs), unlike Amazon's.
_FETCH_JS = """
async ({url, timeoutMs, headers, body}) => {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
        const r = await fetch(url, {
            method: 'POST',
            headers,
            body: JSON.stringify(body),
            signal: ctrl.signal,
            credentials: 'same-origin',
        });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return await r.json();
    } finally {
        clearTimeout(t);
    }
}
"""


class JobSearchError(Exception):
    """Raised when the job search API fails"""
    pass


class JobDetailsFetchError(Exception):
    """Raised when fetching job details fails.

    Defined for symmetry with the other scrapers' api_client surface. TikTok's
    list payload already carries the description, so nothing raises it today.
    """
    pass


def build_search_body(query: str, offset: int = 0) -> Dict[str, Any]:
    """Build the POST body for one page of results.

    Every filter list is sent empty. ``location_code_list`` in particular is
    left empty on purpose — it takes *city* codes, and passing a country code
    silently returns zero results (see config.LOCATION_FILTER).
    """
    return {
        "limit": JOBS_PER_PAGE,
        "offset": offset,
        "keyword": query,
        "recruitment_id_list": [],
        "job_category_id_list": [],
        "subject_id_list": [],
        "location_code_list": [],
    }


def get_search_url() -> str:
    """Full URL of the search endpoint."""
    return f"{API_BASE_URL}{SEARCH_PATH}"


def flatten_location(city_info: Any) -> Optional[str]:
    """Walk ``city_info -> parent -> parent`` into "City, State, Country".

    ``city_info`` is a three-level chain (city / state-region / country). Any
    level can be missing or carry a null ``en_name`` (``name`` is almost always
    null, so ``en_name`` is the field to read).
    """
    if not isinstance(city_info, dict):
        return None
    parts: List[str] = []
    node: Any = city_info
    while isinstance(node, dict):
        name = node.get("en_name")
        if isinstance(name, str) and name.strip():
            parts.append(name.strip())
        node = node.get("parent")
    return ", ".join(parts) if parts else None


def format_department(job_category: Any) -> Optional[str]:
    """Render ``job_category`` as "Parent / Child" when nested, else "Child"."""
    if not isinstance(job_category, dict):
        return None
    name = job_category.get("en_name")
    if not isinstance(name, str) or not name.strip():
        return None
    parent = job_category.get("parent")
    if isinstance(parent, dict):
        parent_name = parent.get("en_name")
        if isinstance(parent_name, str) and parent_name.strip():
            return f"{parent_name.strip()} / {name.strip()}"
    return name.strip()


def combine_description(job: Dict[str, Any]) -> Optional[str]:
    """Join the plain-text ``description`` and ``requirement`` blocks.

    No HTML stripping — TikTok returns plain text with newline separators.
    """
    parts: List[str] = []
    for field in ("description", "requirement"):
        value = job.get(field)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return "\n\n".join(parts) if parts else None


def get_job_url(job_id: str) -> str:
    """Build the canonical public job URL."""
    return f"{JOB_URL_PREFIX}/{job_id}"


def _parse_job_from_search(job: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Convert one raw API row into a standardised job card.

    Returns None when the row is unusable (no id, or no title); the caller
    counts those so a schema change surfaces in the logs.
    """
    if not isinstance(job, dict):
        return None

    job_id = str(job.get("id") or "")
    if not job_id:
        return None

    title = job.get("title")
    if not title:
        return None

    recruit_type = job.get("recruit_type")
    recruit_name = (
        recruit_type.get("en_name") if isinstance(recruit_type, dict) else None
    )

    return {
        "id": job_id,
        "title": title,
        "job_url": get_job_url(job_id),
        "location": flatten_location(job.get("city_info")),
        # TikTok's payload carries NO posted/created/published date anywhere.
        "posted_date": None,
        "department": format_department(job.get("job_category")),
        "description": combine_description(job),
        "job_code": job.get("code"),
        "recruit_type": recruit_name,
        "job_subject": job.get("job_subject"),
        "vacancies": job.get("vacancies"),
        "company": "tiktok",
    }


def _parse_search_response(data: Any) -> Dict[str, Any]:
    """Parse a search response envelope into cards plus pagination metadata.

    ``raw_count`` is the number of rows returned *before* filtering.
    Pagination decisions must use it rather than ``len(jobs)``: a page whose
    rows were all filtered out is not a short page, and conflating the two
    truncates the scrape.

    Raises on a non-zero envelope ``code``. TikTok returns HTTP 200 with
    ``{"code": 1001, "data": null, ...}`` for payload-level errors; returning
    partial results there would let the consecutive-misses lifecycle close the
    entire company during a sustained upstream outage.
    """
    if not isinstance(data, dict):
        raise JobSearchError(f"Unexpected search payload type: {type(data)!r}")

    code = data.get("code")
    if code != 0:
        raise JobSearchError(
            f"tiktok: api error code={code!r} message={data.get('message')!r}"
        )

    payload = data.get("data") or {}
    raw_jobs = payload.get("job_post_list") or []
    if not isinstance(raw_jobs, list):
        raw_jobs = []

    cards: List[Dict[str, Any]] = []
    skipped_missing_id = 0
    skipped_missing_title = 0

    for row in raw_jobs:
        card = _parse_job_from_search(row)
        if card is not None:
            cards.append(card)
        elif isinstance(row, dict) and not str(row.get("id") or ""):
            skipped_missing_id += 1
        else:
            skipped_missing_title += 1

    if skipped_missing_id:
        logger.warning("tiktok: skipped %d job(s) missing id", skipped_missing_id)
    if skipped_missing_title:
        logger.warning("tiktok: skipped %d job(s) missing title", skipped_missing_title)

    total = payload.get("count")
    return {
        "jobs": cards,
        "raw_count": len(raw_jobs),
        "total": total if isinstance(total, int) else None,
        "skipped_missing_id": skipped_missing_id,
        "skipped_missing_title": skipped_missing_title,
    }


async def fetch_search_results(
    page: Page,
    query: str,
    offset: int = 0,
) -> Dict[str, Any]:
    """Fetch one page of TikTok search results.

    Args:
        page: Playwright page, already on the lifeattiktok.com origin (CORS).
        query: free-text keyword (e.g. "software engineer").
        offset: pagination offset in steps of ``JOBS_PER_PAGE``.

    Returns:
        The dict produced by ``_parse_search_response``.

    Raises:
        JobSearchError: on timeout, HTTP failure, or a non-zero envelope code.
    """
    try:
        response = await asyncio.wait_for(
            page.evaluate(
                _FETCH_JS,
                {
                    "url": get_search_url(),
                    "timeoutMs": _FETCH_BROWSER_TIMEOUT_MS,
                    "headers": _JSON_HEADERS,
                    "body": build_search_body(query, offset),
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
    except JobSearchError:
        raise
    except Exception as exc:
        logger.error("Error fetching TikTok search results (offset=%d): %s", offset, exc)
        raise JobSearchError(f"Failed to fetch search results: {exc}") from exc

    return _parse_search_response(response)
