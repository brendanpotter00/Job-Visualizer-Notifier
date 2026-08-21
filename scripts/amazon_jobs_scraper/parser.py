"""
Pure helpers for Amazon job data.

Amazon's careers site is served entirely from a JSON endpoint, so — unlike the
Google and Apple packages — there is no HTML list/detail page to parse here.
What remains are the URL helpers every scraper package exposes, kept in
``parser.py`` so the package shape stays uniform across scrapers.
"""

import logging
import re
from typing import Optional

from .config import BASE_URL

logger = logging.getLogger(__name__)

# Canonical job paths look like /en/jobs/10496449/software-development-engineer
_JOB_ID_RE = re.compile(r"/jobs/(\d+)")


class JobCardExtractionError(Exception):
    """Raised when job cards cannot be extracted from a page.

    Defined for symmetry with the Apple/Microsoft parser surface. Amazon is
    JSON-only, so nothing in this package raises it today.
    """
    pass


def extract_job_id_from_url(url: str) -> Optional[str]:
    """Pull the numeric requisition id out of an Amazon job URL.

    Used as the fallback id source in ``transform_to_job_model`` when a card
    somehow arrives without one.
    """
    if not url:
        return None
    match = _JOB_ID_RE.search(url)
    return match.group(1) if match else None


def build_job_url(job_path: str) -> str:
    """Join a relative Amazon ``job_path`` onto the site origin."""
    if not job_path:
        return BASE_URL
    if job_path.startswith("http://") or job_path.startswith("https://"):
        return job_path
    return f"{BASE_URL}{job_path}"
