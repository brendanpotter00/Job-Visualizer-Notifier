"""
Pure helpers for TikTok job data.

lifeattiktok.com is a single-page app backed entirely by a JSON API, so —
unlike the Google and Apple packages — there is no HTML list/detail page to
parse. What remains are the URL helpers every scraper package exposes, kept in
``parser.py`` so the package shape stays uniform across scrapers.
"""

import logging
import re
from typing import Optional

from .config import JOB_URL_PREFIX

logger = logging.getLogger(__name__)

# Public job URLs look like https://lifeattiktok.com/search/7613184212766607621
_JOB_ID_RE = re.compile(r"/search/(\d+)")


class JobCardExtractionError(Exception):
    """Raised when job cards cannot be extracted from a page.

    Defined for symmetry with the Apple/Microsoft parser surface. TikTok is
    JSON-only, so nothing in this package raises it today.
    """
    pass


def extract_job_id_from_url(url: str) -> Optional[str]:
    """Pull the numeric job id out of a TikTok job URL.

    Used as the fallback id source in ``transform_to_job_model`` when a card
    somehow arrives without one.
    """
    if not url:
        return None
    match = _JOB_ID_RE.search(url)
    return match.group(1) if match else None


def build_job_url(job_id: str) -> str:
    """Build the canonical public job URL from a job id."""
    if not job_id:
        return JOB_URL_PREFIX
    return f"{JOB_URL_PREFIX}/{job_id}"
