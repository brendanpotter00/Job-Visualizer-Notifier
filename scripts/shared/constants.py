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


# --- Careers hosts of the script-scraped boards (E7 unit 11) ------------------
# The five ``ats='script'`` companies — Amazon, Apple, Google, Microsoft, TikTok
# — are published to everybody, but NOTHING about them is derivable from a URL
# the way ``boards.greenhouse.io/<token>`` is. ``ats_link_resolver`` never emits
# ``script``, so the add path's ``(ats, board_token)`` dedupe
# (``custom_companies_service.find_public_company_for_candidate``) cannot see
# them: pasting ``jobs.careers.microsoft.com`` used to fall straight through to
# one-time discovery and build a private duplicate of a board we already publish.
#
# This table is the missing half of that identity, and it is DECLARED rather than
# derived because no store we own holds it. ``companies`` has no URL column;
# ``company_profiles.json`` has no URL either; each scraper's ``config.py``
# ``BASE_URL`` holds only the ONE host that scraper calls, which for three of the
# five is not the host a person would ever paste (Google's scraper reads
# ``www.google.com/about/careers/...`` while people paste ``careers.google.com``;
# Microsoft's reads ``apply.careers.microsoft.com`` while people paste
# ``jobs.careers.microsoft.com``).
#
# It lives HERE — beside ``SourceId``, in the module whose whole job is constants
# shared between ``scripts/`` and ``src/backend/`` — because adding a script
# company already means adding a ``SourceId`` member three lines up. A guard test
# (``test_careers_host_match``) fails if a ``*_scraper`` SourceId ever exists
# without an entry below, so the mapping cannot go stale in silence.
#
# **Every host is an EXACT match after normalization, never a suffix match.**
# See ``api.services.careers_host_match`` for the normalizer and for why the
# registrable domain is the wrong unit here.
#
# Verified live 2026-08-26 (status → redirect target):
#   careers.google.com          301 → www.google.com/about/careers/applications/
#   careers.tiktok.com          302 → lifeattiktok.com/
#   jobs.careers.microsoft.com  301 → apply.careers.microsoft.com/
#   careers.microsoft.com       302 → careers.microsoft.com/v2/global/en/home.html
#   amazon.jobs                 302 → amazon.jobs/en/   (bare and ``www.`` are one site)
#
# Each entry is ``(host, path_prefix)``. ``path_prefix`` is ``""`` for a host that
# IS the careers board, and a leading-slash prefix for the one case where the host
# is not: ``google.com`` is a search engine, a mail client and a maps app, and only
# ``/about/careers`` under it is a job board.
SCRIPT_COMPANY_CAREERS_HOSTS: Final[dict[str, tuple[tuple[str, str], ...]]] = {
    # ``www.amazon.jobs`` is the scraper's BASE_URL; the bare apex redirects into
    # the same site, and the normalizer strips the ``www.`` label, so one entry
    # covers both.
    "amazon": (("amazon.jobs", ""),),
    # NOT extended to ``apple.com/careers``, deliberately -- see the near-miss
    # parametrize block in ``test_careers_host_match.py``. A final review flagged
    # that URL falling through to a paid discovery, but measured behaviour says
    # leave it: ``apple.com/careers/`` 301s to ``apple.com/careers/us/`` and stops
    # there. It is Apple's careers MARKETING page, not the ``jobs.apple.com``
    # board this table names. A careers-host hit is TERMINAL with no escape
    # hatch, so a wrong match hard-blocks the user -- worse than the ~$0.03 the
    # discovery costs.
    "apple": (("jobs.apple.com", ""),),
    "google": (
        # The vanity host people actually paste. It 301s onto the path below.
        ("careers.google.com", ""),
        # The scraper's BASE_URL, and the redirect target. PATH-SCOPED on purpose:
        # ``google.com`` bare is not a job board, and answering "we already track
        # Google" for ``google.com/maps`` would be a confidently wrong link.
        ("google.com", "/about/careers"),
    ),
    "microsoft": (
        # The board the owner pasted, ...
        ("jobs.careers.microsoft.com", ""),
        # ...what it 301s to (and what the scraper reads), ...
        ("apply.careers.microsoft.com", ""),
        # ...and the vanity host in ``companies.ts``.
        ("careers.microsoft.com", ""),
        # NOT FIXED HERE, deliberately: ``https://www.microsoft.com/en-us/careers/``
        # was measured falling through to a paid discovery, but the locale sits
        # BETWEEN the host and ``/careers``, and ``_path_matches`` anchors the
        # prefix at the start of the path. A bare ``("microsoft.com", "")`` entry
        # would answer "we already track Microsoft" for microsoft.com/windows,
        # which is the confidently-wrong link this table exists to avoid.
        # Catching it needs a segment-aware match in ``careers_host_match`` --
        # a change to the matcher's contract, not a table addition.
    ),
    "tiktok": (
        ("lifeattiktok.com", ""),
        # The API origin the scraper POSTs to. Nobody pastes it, but a captured
        # request or a copied devtools URL is a real way to arrive here.
        ("api.lifeattiktok.com", ""),
        # 302s to lifeattiktok.com.
        ("careers.tiktok.com", ""),
    ),
}


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
