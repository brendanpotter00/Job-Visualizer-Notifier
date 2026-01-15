"""
API client for Apple Jobs details endpoint

Apple provides a JSON API for job details that returns structured data
including qualifications, responsibilities, salary, and more.
"""

import re
import logging
from typing import Dict, Any, Optional, List
from playwright.async_api import Page

from .config import BASE_URL, API_BASE

logger = logging.getLogger(__name__)


async def fetch_job_details(page: Page, job_id: str) -> Dict[str, Any]:
    """
    Fetch job details from Apple's API

    Args:
        page: Playwright page object (used for making authenticated requests)
        job_id: Apple job ID (e.g., "200640732-0836")

    Returns:
        Dictionary with job details from API response
    """
    api_url = f"{BASE_URL}{API_BASE}/jobDetails/{job_id}?locale=en-us"

    try:
        # Use page.evaluate to fetch from the same origin (avoids CORS)
        response = await page.evaluate(
            """
            async (url) => {
                const response = await fetch(url);
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }
                return await response.json();
            }
            """,
            api_url,
        )

        if response and "res" in response:
            return _parse_api_response(response["res"])
        else:
            logger.warning(f"Unexpected API response format for job {job_id}")
            return {}

    except Exception as e:
        logger.error(f"Error fetching job details for {job_id}: {e}")
        return {}


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
