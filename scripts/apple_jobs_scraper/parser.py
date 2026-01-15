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


async def extract_job_cards_from_list(page: Page) -> List[Dict[str, Any]]:
    """
    Extract job listings from Apple search results page

    Args:
        page: Playwright page object

    Returns:
        List of job dictionaries with basic info
    """
    job_cards = []

    try:
        # Wait for job listings to load
        await page.wait_for_selector('ul[aria-label="Job Opportunities"]', timeout=10000)

        # Get all job list items
        job_elements = await page.query_selector_all(
            'ul[aria-label="Job Opportunities"] > li'
        )

        for element in job_elements:
            try:
                job_card = await _parse_job_element(element)
                if job_card:
                    job_cards.append(job_card)
            except Exception as e:
                logger.warning(f"Error parsing job element: {e}")
                continue

    except Exception as e:
        logger.error(f"Error extracting job cards: {e}")

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


async def check_has_next_page(page: Page) -> bool:
    """
    Check if there's a next page of results

    Args:
        page: Playwright page object

    Returns:
        True if next page button exists and is enabled
    """
    try:
        next_button = await page.query_selector('button:has-text("Next Page")')
        if not next_button:
            return False

        # Check if button is disabled
        is_disabled = await next_button.get_attribute("disabled")
        return is_disabled is None

    except Exception as e:
        logger.warning(f"Error checking for next page: {e}")
        return False


async def get_total_pages(page: Page) -> int:
    """
    Get total number of pages from pagination info

    Args:
        page: Playwright page object

    Returns:
        Total number of pages (default 1 if not found)
    """
    try:
        # Look for "Of X" text in pagination
        pagination = await page.query_selector('div:has-text("Of")')
        if pagination:
            text = await pagination.inner_text()
            match = re.search(r"Of\s+(\d+)", text)
            if match:
                return int(match.group(1))
        return 1
    except Exception as e:
        logger.warning(f"Error getting total pages: {e}")
        return 1
