"""Project-wide constants shared between scripts/ and src/backend/.

Keeping these in one place avoids drift between scrapers, query helpers,
tests, and the migration test contract.
"""

from __future__ import annotations

import re
import uuid
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
# Every custom company gets its OWN ``source_id`` namespace: ``custom:<id>``,
# never a single shared ``custom`` bucket.
#
# Why per-company matters: ``job_listings``' PK is ``(source_id, id)`` and every
# destructive lifecycle helper is scoped ``WHERE source_id = %s AND id IN (...)``.
# With a per-company source_id, the DATABASE itself enforces cross-company
# isolation — a mis-scoped id list handed to ``mark_jobs_closed`` /
# ``increment_consecutive_misses`` can only ever touch the ONE company that owns
# that source_id, never a different user's company. That is precisely the
# 2026-03-29 class of mass-mutation bug, walled off at the schema level.
#
# The enrichment claim (routers/internal_enrichment.py) leans on both halves:
# the PREFIX separates the custom slice from the published one, and the
# per-company namespace is what its round-robin partitions on.
CUSTOM_SOURCE_PREFIX: Final[str] = "custom:"

# ``companies.id`` shape for a custom company: ``u-<10 base36 chars>``. Satisfies
# the frontend company-id contract ``^[a-z0-9][a-z0-9.\-]*$``, cannot collide
# with a compile-time ``COMPANY_IDS`` member or a ``public/logos/*`` filename
# (none start ``u-<base36>``), and carries ~52 bits of entropy (36**10).
_CUSTOM_COMPANY_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9.\-]*$")
_BASE36_ALPHABET: Final[str] = "0123456789abcdefghijklmnopqrstuvwxyz"
_CUSTOM_ID_RANDOM_LEN: Final[int] = 10


def custom(company_id: str) -> str:
    """Return the ``custom:<company_id>`` source_id for a custom company.

    Validates ``company_id`` against the company-id shape and raises
    ``ValueError`` on anything else — an unvalidated id would be interpolated
    into ``WHERE source_id = %s`` and (via the per-company isolation above) is
    the one value that decides which rows a destructive helper can reach.
    """
    if not isinstance(company_id, str) or not _CUSTOM_COMPANY_ID_RE.fullmatch(
        company_id
    ):
        raise ValueError(
            f"invalid custom company id {company_id!r}: must match "
            f"{_CUSTOM_COMPANY_ID_RE.pattern}"
        )
    return CUSTOM_SOURCE_PREFIX + company_id


def _to_base36(n: int) -> str:
    if n == 0:
        return "0"
    digits: list[str] = []
    while n:
        n, rem = divmod(n, 36)
        digits.append(_BASE36_ALPHABET[rem])
    return "".join(reversed(digits))


def new_custom_company_id() -> str:
    """Mint a fresh ``u-<10 base36 chars>`` id for a new custom company.

    Base36 of a uuid4 is all ``[0-9a-z]``, so slicing the low 10 characters
    yields a value that always satisfies ``_CUSTOM_COMPANY_ID_RE``. Uniqueness is
    enforced by the ``companies`` primary key at insert time; a collision at
    36**10 is astronomically unlikely and the caller retries.
    """
    body = _to_base36(uuid.uuid4().int).rjust(_CUSTOM_ID_RANDOM_LEN, "0")
    return "u-" + body[-_CUSTOM_ID_RANDOM_LEN:]
