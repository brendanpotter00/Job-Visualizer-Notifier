"""
HTML parsing functions for TikTok Jobs search results

TikTok's search page (lifeattiktok.com) renders job listings as HTML.
This module extracts job information from the search results page.
"""

import re
import logging
from typing import List, Dict, Any, Optional
from playwright.async_api import Page

from .config import BASE_URL, JOBS_PER_PAGE

logger = logging.getLogger(__name__)


class JobCardExtractionError(Exception):
    """Raised when job card extraction fails (page structure changed, blocked, etc.)"""
    pass


async def extract_job_cards_from_list(page: Page) -> List[Dict[str, Any]]:
    """
    Extract job listings from TikTok search results page

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
        # Wait for job listings to load - look for job card links
        await page.wait_for_selector('a[href*="/search/"]', timeout=15000)

        # Extract job data using JavaScript - more reliable than DOM traversal
        job_data_list = await page.evaluate("""
            () => {
                const jobs = [];
                // Find all job card links that match /search/{job_id} pattern
                const jobLinks = document.querySelectorAll('a[href*="/search/"]');

                for (const link of jobLinks) {
                    const href = link.getAttribute('href');
                    // Filter to only job detail links (e.g., /search/7579201004205164805)
                    const jobIdMatch = href && href.match(/\\/search\\/(\\d+)$/);
                    if (!jobIdMatch) continue;

                    const jobId = jobIdMatch[1];

                    // Find the job card container (parent elements)
                    let container = link;
                    // Walk up to find a container with multiple text elements
                    for (let i = 0; i < 5; i++) {
                        if (container.parentElement) {
                            container = container.parentElement;
                        }
                    }

                    // IMPROVED: Try multiple strategies to find the title
                    let title = '';
                    let location = '';
                    let category = '';
                    let employmentType = '';

                    // Strategy 1: Look for title directly in the link element
                    // The job link usually contains a heading or strong text with the title
                    const linkHeadings = link.querySelectorAll('h1, h2, h3, h4, h5, h6, strong, b');
                    for (const h of linkHeadings) {
                        const text = h.textContent?.trim();
                        if (text && text.length > 5) {
                            title = text;
                            break;
                        }
                    }

                    // Strategy 2: Use the link's direct text content (common pattern)
                    if (!title) {
                        // Get only direct text, not nested elements
                        const linkText = link.textContent?.trim();
                        if (linkText && linkText.length > 5 && linkText.length < 150) {
                            // Split by common delimiters and take the first substantial part
                            const parts = linkText.split(/[\\n\\r|·]+/);
                            for (const part of parts) {
                                const cleaned = part.trim();
                                if (cleaned.length > 5 &&
                                    !cleaned.includes('Apply') &&
                                    !cleaned.match(/^(Regular|Intern|Full-time|Part-time|Contract)$/i)) {
                                    title = cleaned;
                                    break;
                                }
                            }
                        }
                    }

                    // Extract other fields from the card container
                    const textElements = container.querySelectorAll('span, div, p');
                    const texts = [];
                    for (const el of textElements) {
                        const text = el.textContent?.trim();
                        if (text && text.length > 0 && text.length < 200) {
                            texts.push(text);
                        }
                    }

                    // Strategy 3: Fall back to text-based heuristics (original approach)
                    // But with better filtering for job-title-like patterns
                    if (!title) {
                        for (const text of texts) {
                            // Look for text that looks like a job title
                            const isJobTitle = (
                                text.length > 5 &&
                                text.length < 150 &&
                                !text.includes('Apply') &&
                                !text.includes('Location') &&
                                !text.match(/^(Regular|Intern|Full-time|Part-time|Contract)$/i) &&
                                !text.match(/^(Technology|Engineering|Data|Product)$/i) &&
                                // Job titles often contain these patterns
                                (text.match(/engineer/i) ||
                                 text.match(/developer/i) ||
                                 text.match(/scientist/i) ||
                                 text.match(/architect/i) ||
                                 text.match(/analyst/i) ||
                                 text.match(/manager/i) ||
                                 text.match(/lead/i) ||
                                 text.match(/specialist/i) ||
                                 text.match(/director/i) ||
                                 // Or just take first reasonable text that's long enough
                                 text.length > 20)
                            );
                            if (isJobTitle) {
                                title = text;
                                break;
                            }
                        }
                    }

                    // Extract location, category, employment type from remaining texts
                    for (const text of texts) {
                        if (!location && (
                            text.includes('San') ||
                            text.includes('New York') ||
                            text.includes('Seattle') ||
                            text.includes('Los Angeles') ||
                            text.includes('Austin') ||
                            text.includes('Mountain View') ||
                            text.includes('USA') ||
                            text.includes('Remote') ||
                            text.includes('Singapore') ||
                            text.includes('London') ||
                            text.includes('Beijing') ||
                            text.includes('Shanghai')
                        )) {
                            location = text;
                        } else if (!category && (
                            text === 'Technology' ||
                            text === 'Engineering' ||
                            text === 'Data' ||
                            text === 'Product'
                        )) {
                            category = text;
                        } else if (!employmentType && (
                            text === 'Regular' ||
                            text === 'Intern' ||
                            text === 'Full-time' ||
                            text === 'Part-time' ||
                            text === 'Contract'
                        )) {
                            employmentType = text;
                        }
                    }

                    if (title && jobId) {
                        jobs.push({
                            id: jobId,
                            title: title,
                            location: location || null,
                            category: category || null,
                            employment_type: employmentType || null,
                            href: href,
                            _debug_texts: texts.slice(0, 5)  // Keep first 5 texts for debugging
                        });
                    }
                }

                // Deduplicate by job ID
                const seen = new Set();
                return jobs.filter(job => {
                    if (seen.has(job.id)) return false;
                    seen.add(job.id);
                    return true;
                });
            }
        """)

        if not job_data_list:
            logger.warning("No job elements found in job list")
            return job_cards

        for job_data in job_data_list:
            try:
                job_card = _transform_job_data(job_data)
                if job_card:
                    job_cards.append(job_card)
            except Exception as e:
                parse_errors += 1
                logger.warning(f"Error transforming job data: {e}")
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


def _transform_job_data(job_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Transform raw job data to standard format

    Args:
        job_data: Raw job data from JavaScript extraction

    Returns:
        Standardized job dictionary or None if invalid
    """
    job_id = job_data.get("id")
    if not job_id:
        return None

    href = job_data.get("href", "")
    job_url = f"{BASE_URL}{href}" if href.startswith("/") else href

    title = job_data.get("title", "")

    # Debug logging for title extraction troubleshooting
    debug_texts = job_data.get("_debug_texts", [])
    if debug_texts:
        logger.debug(
            f"Job {job_id}: extracted title='{title}', "
            f"first_texts={debug_texts[:3]}"
        )

    return {
        "id": job_id,
        "title": title,
        "job_url": job_url,
        "location": job_data.get("location"),
        "category": job_data.get("category"),
        "employment_type": job_data.get("employment_type"),
        "company": "tiktok",
    }


def extract_job_id_from_url(url: str) -> Optional[str]:
    """
    Extract job ID from TikTok job URL

    Example URLs:
    - https://lifeattiktok.com/search/7579201004205164805
    - /search/7579201004205164805

    Returns:
        Job ID string (e.g., "7579201004205164805")
    """
    try:
        match = re.search(r"/search/(\d+)", url)
        if match:
            return match.group(1)
        return None
    except Exception as e:
        logger.warning(f"Could not extract job ID from URL {url}: {e}")
        return None


async def extract_total_jobs_count(page: Page) -> Optional[int]:
    """
    Extract total job count from the search results heading

    Args:
        page: Playwright page object

    Returns:
        Total number of jobs, or None if not found
    """
    try:
        # Look for heading like "880 open roles."
        count_text = await page.evaluate("""
            () => {
                const headings = document.querySelectorAll('h1, h2');
                for (const h of headings) {
                    const text = h.textContent || '';
                    const match = text.match(/(\\d+)\\s*open\\s*roles?/i);
                    if (match) {
                        return parseInt(match[1], 10);
                    }
                }
                return null;
            }
        """)
        return count_text
    except Exception as e:
        logger.warning(f"Could not extract total jobs count: {e}")
        return None


async def check_has_next_page(
    page: Page, current_offset: int, total_count: Optional[int]
) -> bool:
    """
    Check if there's a next page of results

    Args:
        page: Playwright page object
        current_offset: Current pagination offset
        total_count: Total number of jobs (if known)

    Returns:
        True if there are more pages, False otherwise
    """
    try:
        # If we know total count, check if we've seen all jobs
        if total_count is not None:
            next_offset = current_offset + JOBS_PER_PAGE
            return next_offset < total_count

        # Otherwise, check if "Load More" or pagination exists
        has_more = await page.evaluate("""
            () => {
                // Look for load more button
                const loadMore = document.querySelector('button:has-text("Load More")');
                if (loadMore && !loadMore.disabled) return true;

                // Look for next page link
                const nextLink = document.querySelector('a[href*="offset="]');
                if (nextLink) return true;

                return false;
            }
        """)
        return has_more

    except Exception as e:
        logger.warning(f"Error checking for next page: {e}")
        return False


async def extract_job_details_from_page(page: Page) -> Dict[str, Any]:
    """
    Extract detailed job information from a job detail page

    Args:
        page: Playwright page object on a job detail page

    Returns:
        Dictionary with job details
    """
    try:
        details = await page.evaluate("""
            () => {
                const result = {
                    responsibilities: '',
                    minimum_qualifications: [],
                    preferred_qualifications: [],
                    salary_range: null,
                    job_code: null,
                    about: '',
                    why_join: '',
                };

                // Get all text content
                const allText = document.body.innerText || '';

                // Extract job code (e.g., "A16898B")
                const codeMatch = allText.match(/Job Code[:\\s]*([A-Z]\\d+[A-Z]?)/i);
                if (codeMatch) {
                    result.job_code = codeMatch[1];
                }

                // Extract salary range
                const salaryMatch = allText.match(/\\$(\\d{1,3},?\\d{3})\\s*-\\s*\\$(\\d{1,3},?\\d{3})/);
                if (salaryMatch) {
                    result.salary_range = salaryMatch[0];
                }

                // Look for sections by heading
                const sections = document.querySelectorAll('section, div');
                for (const section of sections) {
                    const headings = section.querySelectorAll('h2, h3, h4');
                    for (const h of headings) {
                        const heading = (h.textContent || '').toLowerCase();
                        const content = section.textContent || '';

                        if (heading.includes('responsibilities') || heading.includes('what you')) {
                            result.responsibilities = content.substring(0, 2000);
                        } else if (heading.includes('minimum') || heading.includes('qualifications')) {
                            // Split by bullet points or newlines
                            const items = content.split(/[\\n•\\-]+/).filter(s => s.trim().length > 10);
                            result.minimum_qualifications = items.slice(0, 10);
                        } else if (heading.includes('preferred')) {
                            const items = content.split(/[\\n•\\-]+/).filter(s => s.trim().length > 10);
                            result.preferred_qualifications = items.slice(0, 10);
                        } else if (heading.includes('about')) {
                            result.about = content.substring(0, 1000);
                        } else if (heading.includes('why join')) {
                            result.why_join = content.substring(0, 1000);
                        }
                    }
                }

                return result;
            }
        """)
        return details

    except Exception as e:
        logger.error(f"Error extracting job details: {e}")
        return {}


def parse_salary_range(text: str) -> Optional[str]:
    """
    Extract salary range from text

    Args:
        text: Text that may contain salary information

    Returns:
        Salary range string (e.g., "$118657 - $259200") or None
    """
    if not text:
        return None

    # Match patterns like "$118657 - $259200" or "$118,657 - $259,200"
    match = re.search(r"\$[\d,]+\s*-\s*\$[\d,]+", text)
    if match:
        return match.group(0)
    return None


def parse_qualifications(text: Optional[str]) -> List[str]:
    """
    Parse qualifications text into a list

    Args:
        text: Qualifications text with bullet points or newlines

    Returns:
        List of individual qualification strings
    """
    if not text:
        return []

    # Split by common delimiters
    lines = re.split(r"[\n•\-]+", text)
    # Filter and clean
    return [line.strip() for line in lines if line.strip() and len(line.strip()) > 10]


def get_apply_url(job_id: str) -> str:
    """
    Build application URL for a TikTok job

    Args:
        job_id: TikTok job ID

    Returns:
        Application URL
    """
    return f"https://careers.tiktok.com/resume/{job_id}/apply"


def get_job_detail_url(job_id: str) -> str:
    """
    Build job detail URL

    Args:
        job_id: TikTok job ID

    Returns:
        Job detail page URL
    """
    return f"{BASE_URL}/search/{job_id}"
