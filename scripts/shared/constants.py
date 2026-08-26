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
    # ``_scraper`` suffix marks a custom web scraper (no vendor ATS behind it).
    AMAZON: Final[str] = "amazon_scraper"
    TIKTOK: Final[str] = "tiktok_scraper"
    GREENHOUSE: Final[str] = "greenhouse_api"
    ASHBY: Final[str] = "ashby_api"
    LEVER: Final[str] = "lever_api"
    GEM: Final[str] = "gem_api"
    # ``_api`` suffix mirrors Greenhouse + Ashby + Lever + Gem (frozen contract).
    EIGHTFOLD: Final[str] = "eightfold_api"
    WORKDAY: Final[str] = "workday_api"


# --- Custom company sources (E7) ---------------------------------------------
# Every custom (user-added) company gets its OWN ``source_id`` namespace:
# ``custom:<company_id>``, never a single shared ``custom`` bucket.
#
# Why per-company matters: ``job_listings``' PK is ``(source_id, id)`` and every
# destructive lifecycle helper is scoped ``WHERE source_id = %s AND id IN (...)``.
# With a per-company source_id the DATABASE itself enforces cross-company
# isolation — a mis-scoped id list can only ever touch the ONE company that owns
# that source_id, never a different user's company.
#
# The enrichment claim (routers/internal_enrichment.py) leans on both halves:
# the PREFIX separates the custom slice from the published one, and the
# per-company namespace is what its round-robin partitions on.
CUSTOM_SOURCE_PREFIX: Final[str] = "custom:"
