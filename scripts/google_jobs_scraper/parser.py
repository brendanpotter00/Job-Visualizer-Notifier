"""
HTML and accessibility tree parsing functions for extracting job data
"""

import logging
import re
from typing import Optional, List, Dict, Any
from playwright.async_api import Page

logger = logging.getLogger(__name__)


async def extract_job_cards_from_list(page: Page) -> List[Dict[str, Any]]:
    """
    Extract job information from the list page using a simpler, more robust approach
    """
    jobs = []

    try:
        # Wait for the job list container - be more lenient
        await page.wait_for_selector('h3', timeout=15000)
        logger.info("Page loaded, searching for job listings...")

        # Get all h3 headings (these contain job titles)
        headings = await page.query_selector_all('h3')
        logger.info(f"Found {len(headings)} h3 elements on page")

        for i, heading in enumerate(headings):
            try:
                # Get the text content
                title_text = await heading.inner_text()

                # Skip if it's not a job title (too short or contains certain keywords)
                if not title_text or len(title_text) < 5:
                    continue

                # Find the link within the same listitem container
                # The link is a sibling descendant in the "Learn more" section, not a parent
                href = await heading.evaluate("""
                    element => {
                        const listItem = element.closest('li');
                        if (!listItem) return null;
                        const link = listItem.querySelector('a[href*="jobs/results/"]');
                        return link ? link.href : null;
                    }
                """)

                # Only process if it's a jobs/results link
                if href and '/jobs/results/' in href:
                    logger.debug(f"Found job {i+1}: {title_text[:50]}...")

                    # Try to get location and other info from the same container
                    container = await heading.evaluate_handle('el => el.closest("li") || el.parentElement')

                    # Extract all text content from container
                    container_text = await container.inner_text() if container else ""

                    # Parse location from container text (usually has "USA" or state abbreviations)
                    location = None
                    lines = container_text.split('\n')
                    for line in lines:
                        if any(marker in line for marker in ['USA', ', CA', ', NY', ', TX', 'United States']):
                            location = line.strip()
                            break

                    job_data = {
                        'title': title_text.strip(),
                        'location': location,
                        'job_url': href,
                        'minimum_qualifications': [],  # Will be populated if detail_scrape is enabled
                        'experience_level': None,  # Will try to extract from container
                    }

                    jobs.append(job_data)

            except Exception as e:
                logger.debug(f"Error processing heading {i}: {e}")
                continue

        logger.info(f"Successfully extracted {len(jobs)} job listings")

    except Exception as e:
        logger.error(f"Error extracting job cards: {e}")
        # Try to get page content for debugging
        try:
            content = await page.content()
            logger.debug(f"Page content length: {len(content)}")
            # Save to file for inspection
            with open('scripts/output/debug_page.html', 'w') as f:
                f.write(content)
            logger.info("Saved page content to scripts/output/debug_page.html for inspection")
        except Exception:
            pass

    return jobs


async def extract_job_details(page: Page, job_url: str) -> Dict[str, Any]:
    """
    Navigate to job detail page and extract full information
    """
    try:
        # Navigate to job detail page
        await page.goto(job_url, wait_until="networkidle", timeout=30000)

        # Wait for job title h2 to load (p1N2lc class is specific to job title on detail page)
        await page.wait_for_selector("h2.p1N2lc", timeout=10000)

        details = {
            "title": await extract_job_title(page),
            "company": await extract_company(page),
            "location": await extract_job_location(page),
            "experience_level": await extract_experience_level(page),
            "minimum_qualifications": await extract_qualifications(
                page, "Minimum qualifications"
            ),
            "preferred_qualifications": await extract_qualifications(
                page, "Preferred qualifications"
            ),
            "about_the_job": await extract_about_section(page),
            "responsibilities": await extract_responsibilities(page),
            "apply_url": await extract_apply_url(page),
        }

        # Extract salary from about section if available
        if details["about_the_job"]:
            details["salary_range"] = extract_salary_from_text(details["about_the_job"])

        # Check if remote eligible
        details["is_remote_eligible"] = check_remote_eligible(details)

        return details

    except Exception as e:
        logger.error(f"Error extracting job details from {job_url}: {e}")
        return {}


async def extract_job_title(page: Page) -> Optional[str]:
    """Extract job title from detail page (h2 with p1N2lc class)"""
    try:
        # Use specific selector for job title h2 (p1N2lc class is unique to detail page)
        title_elem = await page.query_selector("h2.p1N2lc")
        if title_elem:
            return await title_elem.inner_text()
    except Exception as e:
        logger.warning(f"Error extracting title: {e}")
    return None


async def extract_company(page: Page) -> str:
    """Extract company name (usually Google or YouTube)"""
    try:
        # Look for company indicator
        company_elem = await page.query_selector('[class*="corporate_fare"] + *')
        if company_elem:
            company = await company_elem.inner_text()
            return company.strip().lower()
    except Exception:
        pass
    return "google"


async def extract_job_location(page: Page) -> Optional[str]:
    """Extract location from detail page"""
    try:
        # Location is in span.r0wTof elements, wrapped in span.pwO9Dc
        location_container = await page.query_selector('span.pwO9Dc')
        if location_container:
            # Get all location spans and join them
            location_spans = await location_container.query_selector_all('span.r0wTof')
            locations = []
            for span in location_spans:
                text = await span.inner_text()
                # Clean up the text (remove leading semicolons from additional locations)
                text = text.strip().lstrip(';').strip()
                if text:
                    locations.append(text)
            return '; '.join(locations) if locations else None
    except Exception as e:
        logger.warning(f"Error extracting location: {e}")
    return None


async def extract_experience_level(page: Page) -> Optional[str]:
    """Extract experience level from detail page"""
    try:
        img_elem = await page.query_selector('img[alt*="Learn more about experience"]')
        if img_elem:
            alt_text = await img_elem.get_attribute("alt")
            if alt_text:
                return alt_text.split(",")[0].strip()
    except Exception as e:
        logger.warning(f"Error extracting experience level: {e}")
    return None


async def extract_qualifications(page: Page, section_title: str) -> List[str]:
    """Extract qualifications list (minimum or preferred)"""
    qualifications = []
    try:
        # Find the heading with the section title
        headings = await page.query_selector_all("h3, h4")
        for heading in headings:
            text = await heading.inner_text()
            if section_title.lower() in text.lower():
                # Get the next sibling ul
                parent = await heading.evaluate_handle("el => el.parentElement")
                ul_elem = await parent.query_selector("ul")
                if ul_elem:
                    items = await ul_elem.query_selector_all("li")
                    for item in items:
                        qual_text = await item.inner_text()
                        qualifications.append(qual_text.strip())
                break
    except Exception as e:
        logger.warning(f"Error extracting {section_title}: {e}")

    return qualifications


async def extract_about_section(page: Page) -> Optional[str]:
    """Extract 'About the job' section text"""
    try:
        headings = await page.query_selector_all("h3")
        for heading in headings:
            text = await heading.inner_text()
            if "about the job" in text.lower():
                # Get all paragraphs in the same parent container
                parent = await heading.evaluate_handle("el => el.parentElement")
                paragraphs = await parent.query_selector_all("p")

                about_texts = []
                for p in paragraphs:
                    p_text = await p.inner_text()
                    about_texts.append(p_text.strip())

                return "\n\n".join(about_texts) if about_texts else None
    except Exception as e:
        logger.warning(f"Error extracting about section: {e}")

    return None


async def extract_responsibilities(page: Page) -> List[str]:
    """Extract responsibilities list"""
    responsibilities = []
    try:
        headings = await page.query_selector_all("h3")
        for heading in headings:
            text = await heading.inner_text()
            if "responsibilit" in text.lower():
                parent = await heading.evaluate_handle("el => el.parentElement")
                ul_elem = await parent.query_selector("ul")
                if ul_elem:
                    items = await ul_elem.query_selector_all("li")
                    for item in items:
                        resp_text = await item.inner_text()
                        responsibilities.append(resp_text.strip())
                break
    except Exception as e:
        logger.warning(f"Error extracting responsibilities: {e}")

    return responsibilities


async def extract_apply_url(page: Page) -> Optional[str]:
    """Extract apply URL"""
    try:
        apply_link = await page.query_selector('a[href*="/apply?jobId"], a[href*="apply"]')
        if apply_link:
            href = await apply_link.get_attribute("href")
            if href:
                if href.startswith("http"):
                    return href
                else:
                    return f"https://www.google.com/about/careers/applications/{href.lstrip('/')}"
    except Exception as e:
        logger.warning(f"Error extracting apply URL: {e}")

    return None


def extract_salary_from_text(text: str) -> Optional[str]:
    """
    Extract salary range from text
    Format: "$185,000-$283,000 + bonus + equity + benefits"
    """
    try:
        # Look for pattern like $XXX,XXX-$XXX,XXX
        pattern = r"\$[\d,]+-\$[\d,]+(?:\s*\+\s*[\w\s]+)*"
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    except Exception as e:
        logger.warning(f"Error extracting salary: {e}")

    return None


def check_remote_eligible(job_details: Dict[str, Any]) -> bool:
    """Check if job mentions remote eligibility"""
    text_to_check = ""

    if job_details.get("location"):
        text_to_check += job_details["location"].lower()

    if job_details.get("about_the_job"):
        text_to_check += " " + job_details["about_the_job"].lower()

    return any(
        keyword in text_to_check
        for keyword in ["remote", "work from home", "telecommute", "distributed"]
    )


async def check_for_next_page(page: Page) -> bool:
    """Check if there's a next page available"""
    try:
        # Look for next page link more broadly
        next_button = await page.query_selector('a[aria-label*="next"], a:has-text("next")')
        return next_button is not None
    except Exception:
        return False
