"""
HTML parsing functions for Microsoft Jobs search results

This module provides fallback HTML parsing for cases where the JSON API
is unavailable or returns incomplete data. Microsoft's Eightfold-powered
career site renders job cards as HTML with structured data.
"""

import re
import logging
from typing import List, Dict, Any, Optional
from playwright.async_api import Page

from .config import BASE_URL

logger = logging.getLogger(__name__)


class JobCardExtractionError(Exception):
    """Raised when job card extraction fails (page structure changed, blocked, etc.)"""
    pass


# Job card selectors to try (Eightfold uses various patterns)
JOB_CARD_SELECTORS = [
    '[data-testid="job-card"]',
    '.job-card',
    '.position-card',
    '[role="listitem"]',
    '.search-result-item',
]


async def _find_job_selector(page: Page) -> Optional[str]:
    """Find the first matching job card selector on the page."""
    from playwright.async_api import TimeoutError as PlaywrightTimeout

    for selector in JOB_CARD_SELECTORS:
        try:
            await page.wait_for_selector(selector, timeout=5000)
            return selector
        except PlaywrightTimeout:
            logger.debug(f"Selector not found within timeout: {selector}")
            continue
        except Exception as e:
            logger.warning(f"Unexpected error checking selector '{selector}': {e}")
            continue
    return None


async def extract_job_cards_from_list(page: Page) -> List[Dict[str, Any]]:
    """
    Extract job listings from Microsoft search results page via HTML.

    This is a fallback method when the JSON API is unavailable.

    Args:
        page: Playwright page object

    Returns:
        List of job dictionaries with basic info

    Raises:
        JobCardExtractionError: If the job list cannot be found or parsed
    """
    try:
        selector = await _find_job_selector(page)
        if not selector:
            logger.warning("No standard job card selector found")
            return []

        job_elements = await page.query_selector_all(selector)
        if not job_elements:
            logger.warning("No job elements found in job list")
            return []

        job_cards = []
        parse_errors = 0

        for element in job_elements:
            try:
                job_card = await _parse_job_element(element)
                if job_card:
                    job_cards.append(job_card)
                else:
                    parse_errors += 1
                    logger.debug(f"Job element {parse_errors} failed to parse (returned None)")
            except Exception as e:
                parse_errors += 1
                logger.warning(f"Error parsing job element: {e}")

        if parse_errors > 0 and not job_cards:
            raise JobCardExtractionError(
                f"All {parse_errors} job elements failed to parse - page structure may have changed"
            )

        return job_cards

    except JobCardExtractionError:
        raise
    except Exception as e:
        logger.error(f"Error extracting job cards: {e}")
        raise JobCardExtractionError(f"Failed to extract job cards: {e}") from e


async def _parse_job_element(element) -> Optional[Dict[str, Any]]:
    """
    Parse a single job card element

    Args:
        element: Playwright element handle for job card

    Returns:
        Job dictionary or None if parsing fails
    """
    try:
        job_data = await element.evaluate("""
            (el) => {
                // Try to find job link with various selectors
                let link = el.querySelector('a[href*="position"]');
                if (!link) link = el.querySelector('a[data-testid="job-title"]');
                if (!link) link = el.querySelector('a.job-title');
                if (!link) link = el.querySelector('h3 a, h2 a, h4 a');
                if (!link) link = el.querySelector('a');

                if (!link) return null;

                const title = link.textContent ? link.textContent.trim() : null;
                const href = link.getAttribute('href');
                if (!href) return null;

                // Extract position ID from URL
                let positionId = null;
                const posMatch = href.match(/position_id=([^&]+)/);
                if (posMatch) {
                    positionId = posMatch[1];
                } else {
                    // Try other patterns
                    const altMatch = href.match(/positions?\\/([\\d]+)/);
                    if (altMatch) positionId = altMatch[1];
                }

                // Get location
                let location = null;
                const locationEl = el.querySelector('[data-testid="job-location"], .job-location, .location');
                if (locationEl) {
                    location = locationEl.textContent ? locationEl.textContent.trim() : null;
                }

                // Get posted date
                let postedDate = null;
                const dateEl = el.querySelector('[data-testid="job-date"], .job-date, .posted-date');
                if (dateEl) {
                    postedDate = dateEl.textContent ? dateEl.textContent.trim() : null;
                }

                // Get job number
                let jobNumber = null;
                const jobNumEl = el.querySelector('[data-testid="job-number"], .job-number, .requisition-id');
                if (jobNumEl) {
                    jobNumber = jobNumEl.textContent ? jobNumEl.textContent.trim() : null;
                }

                return {
                    title: title,
                    href: href,
                    positionId: positionId,
                    location: location,
                    postedDate: postedDate,
                    jobNumber: jobNumber
                };
            }
        """)

        if not job_data or not job_data.get("positionId"):
            return None

        position_id = job_data.get("positionId")
        job_url = job_data.get("href", "")

        # Make URL absolute if relative
        if job_url and not job_url.startswith("http"):
            job_url = f"{BASE_URL}{job_url}"

        # Fallback job URL
        if not job_url:
            job_url = f"{BASE_URL}/careers/apply?pid={position_id}"

        return {
            "id": position_id,
            "job_number": job_data.get("jobNumber"),
            "title": job_data.get("title", ""),
            "job_url": job_url,
            "location": job_data.get("location"),
            "posted_date": job_data.get("postedDate"),
            "company": "microsoft",
        }

    except Exception as e:
        logger.warning(f"Error parsing job element: {e}")
        return None


def extract_position_id_from_url(url: str) -> Optional[str]:
    """
    Extract position ID from Microsoft job URL

    Example URLs:
    - https://apply.careers.microsoft.com/careers?position_id=1970393556642428&domain=microsoft.com
    - /careers?position_id=1970393556642428
    - /positions/1970393556642428

    Returns:
        Position ID string (e.g., "1970393556642428")
    """
    if not url:
        return None

    try:
        # Pattern 1: position_id parameter
        match = re.search(r"position_id=([^&]+)", url)
        if match:
            return match.group(1)

        # Pattern 2: /positions/ID or /position/ID
        match = re.search(r"/positions?/(\d+)", url)
        if match:
            return match.group(1)

        return None
    except Exception as e:
        logger.warning(f"Could not extract position ID from URL {url}: {e}")
        return None


NEXT_PAGE_SELECTORS = [
    'button[aria-label="Next page"]',
    'button:has-text("Next")',
    '[data-testid="next-page"]',
    '.pagination-next',
    'a[rel="next"]',
]


async def _is_button_enabled(button) -> bool:
    """Check if a button element is enabled (not disabled)."""
    is_disabled = await button.get_attribute("disabled")
    aria_disabled = await button.get_attribute("aria-disabled")
    return is_disabled is None and aria_disabled != "true"


async def check_has_next_page(page: Page) -> Optional[bool]:
    """
    Check if there's a next page of results.

    Args:
        page: Playwright page object

    Returns:
        True if next page exists and is enabled, False if no next page, None if check failed
    """
    try:
        # Check standard next page buttons
        for selector in NEXT_PAGE_SELECTORS:
            button = await page.query_selector(selector)
            if button:
                return await _is_button_enabled(button)

        # Check for "Load More" pattern
        load_more = await page.query_selector('button:has-text("Load More"), button:has-text("Show More")')
        if load_more:
            is_disabled = await load_more.get_attribute("disabled")
            return is_disabled is None

        return False

    except Exception as e:
        logger.error(f"Failed to check for next page: {e}")
        return None
