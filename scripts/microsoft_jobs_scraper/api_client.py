"""
API client for Microsoft Jobs Eightfold endpoints

Microsoft's career site uses Eightfold ATS which provides JSON APIs
for job search and details. This module handles all API interactions.
"""

import re
import logging
from typing import Dict, Any, Optional, List, Union
from playwright.async_api import Page

from .config import BASE_URL, API_BASE, DOMAIN, LOCATION_FILTER

logger = logging.getLogger(__name__)


class JobSearchError(Exception):
    """Raised when job search API fails"""
    pass


class JobDetailsFetchError(Exception):
    """Raised when fetching job details fails (network, API, or parsing error)"""
    pass


def _format_location(loc: Any) -> str:
    """
    Format location from various API response formats into a string.

    Handles: string, dict with city/state/country, or list of locations.
    """
    if not loc:
        return ""
    if isinstance(loc, str):
        return loc
    if isinstance(loc, list) and len(loc) > 0:
        return _format_location(loc[0])  # Use first location
    if isinstance(loc, dict):
        parts = [loc.get("city", ""), loc.get("state", ""), loc.get("country", "")]
        return ", ".join(filter(None, parts))
    return str(loc)


async def fetch_search_results(
    page: Page,
    query: str,
    start: int = 0,
    location: str = LOCATION_FILTER
) -> Dict[str, Any]:
    """
    Fetch job search results from Microsoft's Eightfold API

    Args:
        page: Playwright page object (used for making authenticated requests)
        query: Search keyword (e.g., "software engineer")
        start: Pagination offset (0, 10, 20, ...)
        location: Location filter (e.g., "United States")

    Returns:
        Dictionary with search results from API

    Raises:
        JobSearchError: If the API request fails
    """
    # Build API URL with query parameters
    api_url = (
        f"{BASE_URL}{API_BASE}/search"
        f"?domain={DOMAIN}"
        f"&query={query}"
        f"&location={location}"
        f"&start={start}"
    )

    try:
        response = await page.evaluate(
            """
            async (url) => {
                const response = await fetch(url, {
                    headers: {
                        'Accept': 'application/json',
                        'Content-Type': 'application/json'
                    }
                });
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }
                return await response.json();
            }
            """,
            api_url,
        )

        return _parse_search_response(response)

    except Exception as e:
        logger.error(f"Error fetching search results: {e}")
        raise JobSearchError(f"Failed to fetch search results: {e}") from e


def _parse_search_response(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse search API response into standardized format

    Args:
        data: Raw API response

    Returns:
        Parsed response with jobs list and pagination info
    """
    # Debug: log the response structure
    logger.debug(f"API response keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")

    # Eightfold API typically returns positions in a 'positions' or 'data' array
    # But might also be in 'results', 'jobs', or 'hits'
    positions = (
        data.get("positions") or
        data.get("data") or
        data.get("results") or
        data.get("jobs") or
        data.get("hits") or
        []
    )

    # Handle nested structure (e.g., data.positions or data.results)
    if isinstance(positions, dict):
        positions = positions.get("positions") or positions.get("results") or positions.get("jobs") or []

    logger.debug(f"Found {len(positions) if isinstance(positions, list) else 'non-list'} positions")
    if positions and len(positions) > 0:
        logger.debug(f"First position type: {type(positions[0])}")
        if isinstance(positions[0], dict):
            logger.debug(f"First position keys: {list(positions[0].keys())[:10]}")

    total_count = data.get("totalCount", data.get("total", data.get("count", len(positions) if isinstance(positions, list) else 0)))

    jobs = []
    for pos in positions:
        job = _parse_position_from_search(pos)
        if job:
            jobs.append(job)

    return {
        "jobs": jobs,
        "total_count": total_count,
        "has_more": len(positions) > 0,
    }


def _parse_position_from_search(pos: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Parse a single position from search results

    Microsoft Eightfold API returns positions with these fields:
    - id: position ID
    - displayJobId: job number (e.g., "1234567")
    - name: job title
    - locations: list of location objects with city/state/country
    - postedTs: timestamp when posted
    - department: department name

    Args:
        pos: Position data from search API

    Returns:
        Standardized job dictionary or None
    """
    try:
        # Handle string positions (shouldn't happen but be safe)
        if not isinstance(pos, dict):
            logger.warning(f"Position is not a dict: {type(pos)}")
            return None

        # Get position ID - Microsoft uses 'id' field
        position_id = str(pos.get("id", ""))
        if not position_id:
            return None

        # Get title - Microsoft uses 'name' field
        title = pos.get("name", pos.get("title", ""))

        # Get job number - Microsoft uses 'displayJobId'
        job_number = pos.get("displayJobId", pos.get("jobNumber", pos.get("requisitionId", "")))

        # Extract location (prefer 'locations' array, fallback to 'location')
        location = _format_location(pos.get("locations") or pos.get("location"))

        # Get posted date - Microsoft uses 'postedTs' (timestamp)
        posted_date = pos.get("postedTs", pos.get("postedDate", pos.get("createdTs")))

        # Get department
        department = pos.get("department", "")

        return {
            "id": position_id,
            "job_number": job_number,
            "title": title,
            "location": location,
            "posted_date": posted_date,
            "department": department,
            "job_url": f"{BASE_URL}/careers/apply?pid={position_id}",
            "company": "microsoft",
        }
    except Exception as e:
        logger.warning(f"Error parsing position: {e}")
        return None


async def fetch_job_details(page: Page, position_id: str) -> Dict[str, Any]:
    """
    Fetch job details from Microsoft's position details API

    Args:
        page: Playwright page object
        position_id: Microsoft position ID (e.g., "1970393556642428")

    Returns:
        Dictionary with detailed job information

    Raises:
        JobDetailsFetchError: If the API request fails
    """
    api_url = (
        f"{BASE_URL}{API_BASE}/position_details"
        f"?position_id={position_id}"
        f"&domain={DOMAIN}"
    )

    try:
        response = await page.evaluate(
            """
            async (url) => {
                const response = await fetch(url, {
                    headers: {
                        'Accept': 'application/json',
                        'Content-Type': 'application/json'
                    }
                });
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }
                return await response.json();
            }
            """,
            api_url,
        )

        return _parse_details_response(response, position_id)

    except Exception as e:
        logger.error(f"Error fetching job details for {position_id}: {e}")
        raise JobDetailsFetchError(f"Failed to fetch details for job {position_id}: {e}") from e


def _parse_details_response(data: Dict[str, Any], position_id: str) -> Dict[str, Any]:
    """
    Parse position details API response

    Args:
        data: Raw API response
        position_id: The position ID for reference

    Returns:
        Standardized job details dictionary
    """
    # Handle nested response structure - API wraps response in "data" or "position"
    pos = data.get("data") or data.get("position") or data

    # Extract qualifications (may be in different formats)
    min_quals = parse_qualifications(pos.get("minimumQualifications", pos.get("minQualifications", "")))
    pref_quals = parse_qualifications(pos.get("preferredQualifications", pos.get("prefQualifications", "")))

    # Extract requirements/qualifications from list format
    if not min_quals and "requirements" in pos:
        min_quals = pos.get("requirements", [])
        if isinstance(min_quals, str):
            min_quals = parse_qualifications(min_quals)

    # Extract salary information
    salary_range = extract_salary(pos)

    # Extract description and responsibilities
    description = pos.get("description", pos.get("jobDescription", ""))
    responsibilities = pos.get("responsibilities", pos.get("jobResponsibilities", ""))

    # Extract additional metadata
    work_site = pos.get("workSite", pos.get("workLocation", pos.get("remoteType", "")))
    travel = pos.get("travel", pos.get("travelPercentage", ""))
    profession = pos.get("profession", pos.get("category", pos.get("jobFamily", "")))
    discipline = pos.get("discipline", pos.get("subCategory", ""))
    role_type = pos.get("roleType", pos.get("employmentType", ""))
    employment_type = pos.get("employmentType", pos.get("jobType", ""))

    # Location handling
    location = _format_location(pos.get("location"))

    return {
        "title": pos.get("title", pos.get("name", "")),
        "position_id": position_id,
        "job_number": pos.get("jobNumber", pos.get("requisitionId", "")),
        "description": description,
        "responsibilities": responsibilities,
        "minimum_qualifications": min_quals,
        "preferred_qualifications": pref_quals,
        "location": location,
        "salary_range": salary_range,
        "work_site": work_site,
        "travel": travel,
        "profession": profession,
        "discipline": discipline,
        "role_type": role_type,
        "employment_type": employment_type,
        "posted_on": pos.get("postedDate", pos.get("datePosted")),
        "raw_api_response": data,
    }


def parse_qualifications(text: Optional[str]) -> List[str]:
    """
    Parse qualifications text into a list

    Handles newline-separated or HTML-formatted qualification lists.

    Args:
        text: Qualifications string (may contain newlines or HTML)

    Returns:
        List of individual qualification strings
    """
    if not text:
        return []

    if isinstance(text, list):
        return [str(q).strip() for q in text if str(q).strip()]

    # Remove HTML tags if present
    clean_text = re.sub(r"<[^>]+>", "\n", text)

    # Split by newlines and bullet points
    lines = re.split(r"[\n\r]+|(?:^|\n)\s*[\u2022\u2023\u25E6\u2043\u2219\-\*]\s*", clean_text)

    # Filter empty lines and clean up
    return [line.strip() for line in lines if line.strip()]


def extract_salary(data: Dict[str, Any]) -> Optional[str]:
    """
    Extract salary range from API response

    Args:
        data: Raw API response data

    Returns:
        Salary range string (e.g., "$141,800 - $258,600") or None
    """
    # Check common salary field names
    for key in ("salaryRange", "salary", "basePay"):
        if data.get(key):
            return str(data[key])

    # Check for min/max salary fields
    min_sal = data.get("minSalary") or data.get("salaryMin")
    max_sal = data.get("maxSalary") or data.get("salaryMax")

    if min_sal and max_sal:
        if isinstance(min_sal, (int, float)):
            return f"${min_sal:,} - ${max_sal:,}"
        return f"{min_sal} - {max_sal}"

    return None


def get_apply_url(position_id: str) -> str:
    """
    Build application URL for a job

    Args:
        position_id: Microsoft position ID

    Returns:
        Application URL
    """
    return f"{BASE_URL}/careers/apply?pid={position_id}"
