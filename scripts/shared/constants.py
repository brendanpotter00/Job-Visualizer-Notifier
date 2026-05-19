"""Project-wide constants shared between scripts/ and src/backend/.

Keeping these in one place avoids drift between scrapers, query helpers,
tests, and the migration test contract.
"""

from __future__ import annotations

from typing import Final


class SourceId:
    """``job_listings.source_id`` values, namespaced by data origin."""

    GOOGLE: Final[str] = "google_scraper"
    APPLE: Final[str] = "apple_scraper"
    MICROSOFT: Final[str] = "microsoft_scraper"
    GREENHOUSE: Final[str] = "greenhouse_api"
    ASHBY: Final[str] = "ashby_api"
    GEM: Final[str] = "gem_api"
