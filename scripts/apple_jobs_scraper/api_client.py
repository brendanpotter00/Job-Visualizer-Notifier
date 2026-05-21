"""
API client for Apple Jobs details endpoint

Apple provides a JSON API for job details that returns structured data
including qualifications, responsibilities, salary, and more.
"""

import asyncio
import re
import logging
from typing import Dict, Any, Optional, List
from playwright.async_api import Error as PlaywrightError, Page

from shared.constants import SourceId
from shared.source_registry import VerifierResult, register_verifier

from .config import BASE_URL, API_BASE

logger = logging.getLogger(__name__)

# Bound the in-browser fetch. Without these, a stalled response from Apple
# (rate limiting, edge holding the connection) hangs page.evaluate forever
# and the whole scraper subprocess sits idle until SCRAPER_TIMEOUT_MINUTES.
# See docs/implementations/appleScraperHangFix/PLAN.md.
_FETCH_BROWSER_TIMEOUT_MS = 15_000
_FETCH_OUTER_TIMEOUT_S = 20.0

# JS payload that runs inside the page context. AbortController + setTimeout
# bound the in-page fetch so a never-arriving response surfaces as an error
# instead of a hang. The Python-side asyncio.wait_for below is the
# belt-and-suspenders if the JS abort somehow doesn't propagate.
_FETCH_JS = """
async ({url, timeoutMs}) => {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
        const r = await fetch(url, { signal: ctrl.signal });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return await r.json();
    } finally {
        clearTimeout(t);
    }
}
"""


class JobDetailsFetchError(Exception):
    """Raised when fetching job details fails (network, API, or parsing error)"""
    pass


async def fetch_job_details(page: Page, job_id: str) -> Dict[str, Any]:
    """
    Fetch job details from Apple's API

    Args:
        page: Playwright page object (used for making authenticated requests)
        job_id: Apple job ID (e.g., "200640732-0836")

    Returns:
        Dictionary with job details from API response

    Raises:
        JobDetailsFetchError: If the API request fails or returns unexpected format
    """
    api_url = f"{BASE_URL}{API_BASE}/jobDetails/{job_id}?locale=en-us"

    try:
        response = await asyncio.wait_for(
            page.evaluate(
                _FETCH_JS,
                {"url": api_url, "timeoutMs": _FETCH_BROWSER_TIMEOUT_MS},
            ),
            timeout=_FETCH_OUTER_TIMEOUT_S,
        )

        if response and "res" in response:
            return _parse_api_response(response["res"])
        else:
            logger.warning(f"Unexpected API response format for job {job_id}")
            return {}

    except asyncio.TimeoutError as e:
        logger.error(
            "Detail fetch outer timeout for job %s after %.0fs",
            job_id, _FETCH_OUTER_TIMEOUT_S,
        )
        raise JobDetailsFetchError(
            f"Detail fetch timed out for job {job_id} after {_FETCH_OUTER_TIMEOUT_S}s"
        ) from e
    except Exception as e:
        logger.error(f"Error fetching job details for {job_id}: {e}")
        raise JobDetailsFetchError(f"Failed to fetch details for job {job_id}: {e}") from e


def _parse_api_response(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse API response into standardized job details format

    Args:
        data: Raw API response data (the "res" object)

    Returns:
        Standardized job details dictionary
    """
    # Parse qualifications from newline-separated text
    min_quals = parse_qualifications(data.get("minimumQualifications", ""))
    pref_quals = parse_qualifications(data.get("preferredQualifications", ""))

    # Extract salary from postingPostLocationData
    salary_range = extract_salary(data)

    # Format location from locations array
    location = format_location(data.get("locations", []))

    # Check remote eligibility
    is_remote = data.get("homeOffice", False)

    # Get posting date
    posted_on = data.get("postDateInGMT")

    return {
        "title": data.get("postingTitle", ""),
        "job_id": data.get("jobNumber", ""),
        "position_id": data.get("positionId", ""),
        "description": data.get("description", ""),
        "job_summary": data.get("jobSummary", ""),
        "responsibilities": data.get("responsibilities", ""),
        "minimum_qualifications": min_quals,
        "preferred_qualifications": pref_quals,
        "team_names": data.get("teamNames", []),
        "location": location,
        "locations": data.get("locations", []),
        "salary_range": salary_range,
        "is_remote_eligible": is_remote,
        "posted_on": posted_on,
        "job_type": data.get("jobType", ""),
        "employment_type": data.get("employmentType", ""),
        "raw_api_response": data,  # Keep raw data for debugging
    }


def parse_qualifications(text: Optional[str]) -> List[str]:
    """
    Parse newline-separated qualifications text into a list

    Apple's API returns qualifications as a single string with newlines.
    Example: "Bachelor's degree\\n5+ years experience\\nStrong Python skills"

    Args:
        text: Newline-separated qualifications string, or None

    Returns:
        List of individual qualification strings
    """
    if not text:
        return []

    # Split by newlines and filter empty lines
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    return lines


def extract_salary(data: Dict[str, Any]) -> Optional[str]:
    """
    Extract salary range from API response

    Salary is typically in postingPostLocationData with key like "Base Pay Range"

    Args:
        data: Raw API response data

    Returns:
        Salary range string (e.g., "$141,800 - $258,600") or None
    """
    salary_keys = ["Base Pay Range", "basePay", "salary", "payRange"]

    # Check postingPostLocationData first, then top level
    search_locations = [data.get("postingPostLocationData", {}), data]
    for location in search_locations:
        for key in salary_keys:
            if key in location:
                return str(location[key])

    # Try to find salary in description or summary text
    description = data.get("description") or ""
    summary = data.get("jobSummary") or ""
    combined_text = f"{description} {summary}"

    match = re.search(r"\$[\d,]+(?:\s*-\s*\$[\d,]+)?(?:/(?:year|hr|hour))?", combined_text)
    return match.group(0) if match else None


def format_location(locations: Optional[List[Dict[str, Any]]]) -> str:
    """
    Format location from locations array into readable string

    Args:
        locations: List of location dictionaries from API, or None

    Returns:
        Formatted location string (e.g., "Cupertino, California, United States")
    """
    if not locations:
        return ""

    # Use the first (primary) location
    loc = locations[0]

    parts = []
    if loc.get("city"):
        parts.append(loc["city"])
    if loc.get("stateProvince"):
        parts.append(loc["stateProvince"])
    if loc.get("countryName"):
        parts.append(loc["countryName"])

    return ", ".join(parts)


def get_apply_url(job_id: str) -> str:
    """
    Build application URL for a job

    Args:
        job_id: Apple job ID

    Returns:
        Application URL
    """
    return f"{BASE_URL}/app/en-us/apply/{job_id}"


# -----------------------------------------------------------------------------
# URL verifier — close-gate signal for the Apple scraper
# -----------------------------------------------------------------------------
#
# Apple's ``/api/role/jobDetails/{id}?locale=en-us`` endpoint returns a
# populated ``res`` object for active jobs and either 404s or returns an
# empty/error response for closed jobs. We can use it as ground truth at
# close-decision time to filter the false-close set produced by HTML
# pagination drift in ``scraper.scrape_query``.
#
# Critical constraint: the API REQUIRES a Playwright browser context to
# respond — a plain httpx request gets redirected to ``apple.com/pagenotfound``
# (verified 2026-05-21). So the verifier must run via ``page.evaluate``
# inside the same browser context the scraper uses. The scraper sets the
# page reference via ``set_apple_verifier_page(page)`` once at startup;
# the verifier reads that module-level reference at call time.
# -----------------------------------------------------------------------------

_VERIFIER_PAGE: Optional[Page] = None


def set_apple_verifier_page(page: Optional[Page]) -> None:
    """Install (or clear) the Playwright page the Apple verifier uses.

    The Apple scraper calls this with its own dedicated verify page when
    starting and again with ``None`` on shutdown. While ``None``, the
    verifier returns ``"unknown"`` so the close path treats Apple sources
    as unverifiable (close-on-threshold) — preserving today's behavior for
    JSON-mode runs without a browser.
    """
    global _VERIFIER_PAGE
    _VERIFIER_PAGE = page


_JOB_ID_FROM_URL = re.compile(r"/details/([^/?#]+)")


def _extract_apple_job_id_from_url(url: str) -> Optional[str]:
    """Pull the ``200555687-0836``-style id out of a jobs.apple.com URL.

    Mirrors ``parser.extract_job_id_from_url`` — duplicated here to avoid a
    circular import between ``api_client`` (verifier) and ``parser``.
    """
    if not url:
        return None
    match = _JOB_ID_FROM_URL.search(url)
    return match.group(1) if match else None


async def verify_url_alive(
    url: str, source_id: str, job_id: str
) -> VerifierResult:
    """Verify a candidate-close Apple job is actually gone upstream.

    Returns:
    - ``"alive"`` if Apple's detail API returns a populated ``res`` object.
    - ``"dead"`` if Apple's detail API returns no ``res`` / empty payload
      (closed or removed).
    - ``"unknown"`` if no verifier page is installed, the in-page fetch
      raises, or the URL doesn't parse.
    """
    if _VERIFIER_PAGE is None:
        return "unknown"

    # Use the ID parsed from the URL — Apple's API expects the
    # ``{positionId}-{teamSuffix}`` form that appears in the URL path, which
    # may differ from the bare positionId stored in the row when the suffix
    # has been remapped.
    parsed_id = _extract_apple_job_id_from_url(url) or job_id
    api_url = f"{BASE_URL}{API_BASE}/jobDetails/{parsed_id}?locale=en-us"

    try:
        response = await asyncio.wait_for(
            _VERIFIER_PAGE.evaluate(
                _FETCH_JS,
                {"url": api_url, "timeoutMs": _FETCH_BROWSER_TIMEOUT_MS},
            ),
            timeout=_FETCH_OUTER_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "apple verify_url_alive: outer timeout for %s — returning unknown",
            parsed_id,
        )
        return "unknown"
    except (PlaywrightError, OSError):
        # Transient verifier failure: Playwright-level error (page crashed,
        # context torn down, navigation race, JS abort) or OS-level socket
        # error from the in-page fetch. Resolves to "unknown" per the
        # ``source_registry.Verifier`` contract — implementers MUST swallow
        # transient errors themselves. Programming bugs (TypeError,
        # AttributeError) are NOT caught — they propagate to Sentry instead
        # of being silently classified as "ambient verifier ambiguity."
        logger.warning(
            "apple verify_url_alive: in-page fetch raised for %s — unknown",
            parsed_id,
            exc_info=True,
        )
        return "unknown"

    if isinstance(response, dict) and "res" in response and response["res"]:
        return "alive"
    # Apple's API returns ``{"res": null}``, ``{}``, or an error dict for
    # closed positions. Anything that's not a populated ``res`` is treated
    # as dead.
    return "dead"


register_verifier(SourceId.APPLE, verify_url_alive)
