"""
HTML parsing functions for Apple Jobs search results

Apple's search page renders job listings as HTML. This module extracts
job information from the search results page.
"""

import re
import logging
from typing import List, Dict, Any, Optional
from playwright.async_api import Page

logger = logging.getLogger(__name__)


class JobCardExtractionError(Exception):
    """Raised when job card extraction fails (page structure changed, blocked, etc.)"""
    pass


async def extract_jobs_from_hydration_data(page: Page) -> tuple[List[Dict[str, Any]], int]:
    """
    Extract job listings from React Router hydration data embedded in the page.

    Apple's job site (React Router v7 SSR) embeds structured job data in
    window.__staticRouterHydrationData.  When the page is served to bots with
    an empty DOM, this data may still be present and is more reliable than
    DOM scraping.

    Returns:
        Tuple of (job_cards, total_records).
        job_cards is an empty list if hydration data is unavailable.
    """
    try:
        data = await page.evaluate("""
            () => {
                const hydration = window.__staticRouterHydrationData;
                if (!hydration?.loaderData?.search) return null;
                const search = hydration.loaderData.search;
                return {
                    totalRecords: search.totalRecords || 0,
                    searchResults: search.searchResults || [],
                };
            }
        """)

        if not data or not data.get("searchResults"):
            return [], 0

        total_records = data.get("totalRecords", 0)
        job_cards = []

        for item in data["searchResults"]:
            raw_id = item.get("id") or item.get("positionId") or ""
            # Strip PIPE- prefix that Apple adds to hydration IDs
            job_id = str(raw_id).removeprefix("PIPE-") if raw_id else ""
            if not job_id:
                continue

            title = item.get("postingTitle", item.get("title", ""))
            team = item.get("team", {})
            team_name = team.get("teamName", "") if isinstance(team, dict) else str(team)
            locations = item.get("locations", [])
            location = ", ".join(
                loc.get("name", str(loc)) if isinstance(loc, dict) else str(loc)
                for loc in locations
            ) if locations else None
            posted_date = item.get("postDateInGMT")

            job_cards.append({
                "id": job_id,
                "title": title,
                "job_url": f"https://jobs.apple.com/en-us/details/{job_id}",
                "team": team_name or None,
                "location": location,
                "posted_date": posted_date,
                "company": "apple",
            })

        logger.info(
            "Hydration data: %d jobs extracted (totalRecords=%d)",
            len(job_cards), total_records,
        )
        return job_cards, total_records

    except Exception as e:
        logger.debug("Hydration data extraction failed: %s", e)
        return [], 0


async def extract_job_cards_from_list(page: Page) -> List[Dict[str, Any]]:
    """
    Extract job listings from Apple search results page

    Args:
        page: Playwright page object

    Returns:
        List of job dictionaries with basic info

    Raises:
        JobCardExtractionError: If the job list cannot be found or parsed
    """
    # Try hydration data first — more reliable when DOM is empty due to bot detection
    hydration_cards, _total = await extract_jobs_from_hydration_data(page)
    if hydration_cards:
        logger.info("Using hydration data path (%d jobs)", len(hydration_cards))
        return hydration_cards

    # Fall back to DOM extraction
    job_cards = []
    parse_errors = 0

    try:
        # Wait for job listings to load
        await page.wait_for_selector('ul[aria-label="Job Opportunities"]', timeout=10000)

        # Get all job list items
        job_elements = await page.query_selector_all(
            'ul[aria-label="Job Opportunities"] > li'
        )

        if not job_elements:
            # No job elements found - could indicate page structure changed
            logger.warning("No job elements found in job list")
            return job_cards

        for element in job_elements:
            try:
                job_card = await _parse_job_element(element)
                if job_card:
                    job_cards.append(job_card)
            except Exception as e:
                parse_errors += 1
                logger.warning(f"Error parsing job element: {e}")
                continue

        # If all elements failed to parse, likely a systematic issue
        if parse_errors > 0 and len(job_cards) == 0:
            raise JobCardExtractionError(
                f"All {parse_errors} job elements failed to parse - page structure may have changed"
            )

    except JobCardExtractionError:
        raise
    except Exception as e:
        logger.error(f"Error extracting job cards: {e}")
        raise JobCardExtractionError(f"Failed to extract job cards: {e}") from e

    return job_cards


async def _parse_job_element(element) -> Optional[Dict[str, Any]]:
    """
    Parse a single job list item element

    Args:
        element: Playwright element handle for job list item

    Returns:
        Job dictionary or None if parsing fails
    """
    try:
        # Use JavaScript to extract all job data at once for reliability
        job_data = await element.evaluate("""
            (el) => {
                // Find the job link
                const link = el.querySelector('h3 a');
                if (!link) return null;

                const title = link.textContent.trim();
                const href = link.getAttribute('href');
                if (!href) return null;

                // Get all text in the element
                const fullText = el.textContent;

                // Extract team - it's typically right after the title in the h3 parent
                let team = null;
                const h3 = el.querySelector('h3');
                if (h3 && h3.parentElement) {
                    const siblings = h3.parentElement.children;
                    for (let i = 0; i < siblings.length; i++) {
                        const sib = siblings[i];
                        if (sib !== h3 && sib.tagName !== 'H3') {
                            const text = sib.textContent.trim();
                            // Team names don't contain dates or "Location"
                            if (text && !text.match(/[A-Z][a-z]{2}\\s+\\d{1,2},\\s+\\d{4}/) &&
                                !text.includes('Location') && !text.includes('Actions')) {
                                team = text;
                                break;
                            }
                        }
                    }
                }

                // Extract posted date using regex
                const dateMatch = fullText.match(/([A-Z][a-z]{2}\\s+\\d{1,2},\\s+\\d{4})/);
                const postedDate = dateMatch ? dateMatch[1] : null;

                // Extract location - text after "Location" label
                let location = null;
                const locationMatch = fullText.match(/Location\\s*([^\\n]+)/);
                if (locationMatch) {
                    location = locationMatch[1].trim();
                    // Remove "Actions" if it got included
                    if (location.includes('Actions')) {
                        location = location.split('Actions')[0].trim();
                    }
                }

                return {
                    title: title,
                    href: href,
                    team: team,
                    location: location,
                    postedDate: postedDate
                };
            }
        """)

        if not job_data:
            return None

        href = job_data.get("href", "")
        job_url = f"https://jobs.apple.com{href}"
        job_id = extract_job_id_from_url(href)

        if not job_id:
            return None

        return {
            "id": job_id,
            "title": job_data.get("title", ""),
            "job_url": job_url,
            "team": job_data.get("team"),
            "location": job_data.get("location"),
            "posted_date": job_data.get("postedDate"),
            "company": "apple",
        }

    except Exception as e:
        logger.warning(f"Error parsing job element: {e}")
        return None


def extract_job_id_from_url(url: str) -> Optional[str]:
    """
    Extract job ID from Apple job URL

    Example URLs:
    - /en-us/details/200640732-0836/software-qa-engineer?team=SFTWR
    - /en-us/details/114438158/us-specialist-full-time-part-time-and-part-time-temporary?team=APPST

    Returns:
        Job ID string (e.g., "200640732-0836" or "114438158")
    """
    try:
        # Pattern: /details/{job_id}/ or /details/{job_id}?
        match = re.search(r"/details/([^/\?]+)", url)
        if match:
            return match.group(1)
        return None
    except Exception as e:
        logger.warning(f"Could not extract job ID from URL {url}: {e}")
        return None


async def check_has_next_page(page: Page) -> Optional[bool]:
    """
    Check if there's a next page of results

    Args:
        page: Playwright page object

    Returns:
        True if next page button exists and is enabled
        False if no next page (button not found or disabled)
        None if check failed (caller should handle - e.g., retry or stop with warning)
    """
    try:
        next_button = await page.query_selector('button:has-text("Next Page")')
        if not next_button:
            return False

        # Check if button is disabled
        is_disabled = await next_button.get_attribute("disabled")
        return is_disabled is None

    except Exception as e:
        logger.error(f"Failed to check for next page: {e}")
        return None


