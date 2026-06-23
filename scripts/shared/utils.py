"""
Shared utility functions for scrapers
"""

import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# Keywords matched as whole words instead of substrings, to avoid false friends.
# "intern" must not match "internet" / "international" / "internal"; the pattern
# still accepts the real forms "intern", "interns", "internship", "internships".
_WHOLE_WORD_KEYWORD_PATTERNS = {
    "intern": re.compile(r"\bintern(?:ship)?s?\b", re.IGNORECASE),
}


def title_matches_keyword(keyword: str, title: str) -> bool:
    """Return True if ``keyword`` matches ``title`` (case-insensitive).

    Most keywords match as plain substrings (e.g. "software", "ML", "iOS"), which
    is what the scraper title filters rely on. Keywords listed in
    ``_WHOLE_WORD_KEYWORD_PATTERNS`` instead match only as whole words so they do
    not over-match longer words that merely contain them — e.g. "intern" matches
    "Software Engineering Intern" / "...Internship" but not "Internet" /
    "International" / "Internal".
    """
    pattern = _WHOLE_WORD_KEYWORD_PATTERNS.get(keyword.lower())
    if pattern is not None:
        return pattern.search(title) is not None
    return keyword.lower() in title.lower()


def get_iso_timestamp() -> str:
    """Get current timestamp in ISO 8601 format (UTC) with microsecond precision"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
