"""
HTML parsing functions for Apple Jobs search results

Apple's search page renders job listings as HTML. This module extracts
job information from the search results page.
"""

import re
import logging
from typing import List, Dict, Any, Optional

import dateutil.parser
from playwright.async_api import Page

logger = logging.getLogger(__name__)


def parse_card_posted_date(value: Optional[str]) -> Optional[str]:
    """Normalise a list-card posted date ("Jan 15, 2026") to ``YYYY-MM-DD``.

    Normalising HERE, at the one place that produces the odd format, rather than
    teaching the shared parser to read human dates. Precedent:
    ``amazon_jobs_scraper.api_client.parse_posted_date`` does exactly this for
    Amazon's "August  8, 2026". The shared ``shared/posted_date.py`` stays strict
    on purpose — widening it to accept human formats would hand every future
    caller a genuine ambiguity (``03/04/2026`` is two different days depending on
    locale), and its strictness is what makes it trustworthy in the write path.

    Half-normalising is worse than not doing it. Before this existed the raw
    string still stored fine (``posted_on`` is a TIMESTAMPTZ and Postgres reads
    "Jan 15, 2026") while ``effective_posted_date`` rejected it, so the card's
    date reached ``posted_on`` and silently did NOT reach ``first_seen_at`` — a
    date visible in diagnostics but absent from the sort key users actually see.

    Called from ``scraper.transform_to_job_model``, not from the card extractor
    below, so it sits on the one boundary that derives both of those fields.

    There is no locale ambiguity to inherit: the card regex above is
    ``[A-Z][a-z]{2}\\s+\\d{1,2},\\s+\\d{4}``, so this only ever sees an English
    three-letter month with an unambiguous day and a four-digit year.

    Date-only in, date-only out: Apple's card carries no time and no timezone,
    and ``posted_on`` being a TIMESTAMPTZ means Postgres will read this as UTC
    midnight. That is the honest encoding of a date-only source, the same call
    the Amazon client documents at length.

    A parse failure warns and returns None rather than passing through a string
    that would then mean one thing to the column and another to the sort key.
    """
    if not value:
        return None
    try:
        parsed = dateutil.parser.parse(value)
    except (ValueError, TypeError, OverflowError):
        logger.warning("apple: could not parse card posted date %r", value)
        return None
    return parsed.date().isoformat()


class JobCardExtractionError(Exception):
    """Raised when job card extraction fails (page structure changed, blocked, etc.)"""
    pass


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
            # Raw, as scraped. Normalised by ``parse_card_posted_date`` at the
            # one boundary that matters — ``scraper.transform_to_job_model``,
            # which derives BOTH ``posted_on`` and ``first_seen_at`` from it.
            # Normalising here instead would leave that boundary reachable with
            # a raw string by any other caller, which is exactly how the two
            # ended up disagreeing.
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
    Check if there's a next page of results.

    Select by the ACCESSIBLE NAME, not by text content. Apple's "Next" control
    is an icon-only chevron ``<button class="icon icon-chevronend">`` whose
    visible text is empty (``textContent === ""``); its label lives only in
    ``aria-label="Next Page"``. The old probe ``button:has-text("Next Page")``
    matches on text content, so it found NOTHING on every page, returned False,
    and ``scrape_query`` stopped after page 1 — collecting ~17 of ~3,350 jobs on
    every run. That silent single-paging ran for 3.5 days
    (2026-08-28 → 2026-08-31) before it was caught, because the guard blocked
    the empty result rather than alarming on it. Full write-up:
    ``docs/incidents/2026-08-28-apple-pagination-single-page.md``.

    Honour BOTH of Apple's disabled encodings. On the last page Apple sets the
    Next button ``disabled`` AND ``aria-disabled="true"``; the ``disabled``
    attribute is present as an EMPTY STRING (``disabled=""``), so test for its
    presence (``is None``), never its truthiness.

    Args:
        page: Playwright page object

    Returns:
        True if next page button exists and is enabled
        False if no next page (button not found or disabled)
        None if check failed (caller should handle - e.g., retry or stop with warning)
    """
    try:
        next_button = await page.query_selector('button[aria-label="Next Page"]')
        if not next_button:
            return False

        # Present-but-disabled is the last page. `disabled` arrives as "" (an
        # empty string, which is falsy) when set, so `is None` is the only
        # correct presence test; `aria-disabled` is the redundant a11y encoding.
        disabled = await next_button.get_attribute("disabled")
        aria_disabled = await next_button.get_attribute("aria-disabled")
        return disabled is None and aria_disabled != "true"

    except Exception as e:
        logger.error(f"Failed to check for next page: {e}")
        return None


async def get_total_pages(page: Page) -> Optional[int]:
    """Apple publishes its own result-page count; read it as a board-size oracle.

    The pagination control renders the total number of result pages in
    ``.rc-pagination-total-pages`` (``data-autom="paginationTotalPages"``) — e.g.
    ``226`` for the US board. ``scrape_query`` reads it once on page 1 and, when
    the walk terminates far short of it, logs a LOUD truncation error. That is
    what turns "``check_has_next_page`` said stop after page 1" from something
    indistinguishable from a genuine one-page board into an alarming signal — the
    exact indistinguishability that let the 2026-08-28 break run for 3.5 days.

    Returns None when the element is absent or unparseable. The caller treats
    None as "board size unknown — cannot assert truncation", never as zero, so a
    future markup change here degrades to "no cross-check", not to a false alarm.
    """
    try:
        el = await page.query_selector(".rc-pagination-total-pages")
        if el is None:
            return None
        text = await el.text_content()
        if not isinstance(text, str):
            return None
        raw = text.replace(",", "").strip()
        return int(raw) if raw.isdigit() else None
    except Exception as e:
        logger.warning(f"Could not read Apple total-pages count: {e}")
        return None


