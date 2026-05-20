"""Pure Gem Job Board API client + transformer.

Two functions, both queue-agnostic:

- ``fetch_jobs(board_token, http)``: GETs Gem's public Job Board API
  and returns the raw list of job posts. No DB, no transformation.
- ``transform_to_job_listings(company_id, raw_jobs)``: maps each raw
  Gem job dict to a :class:`scripts.shared.models.JobListing`
  ready for ``upsert_jobs_batch``.

Gem's API differs from Ashby/Greenhouse in one key way: the response
is a **flat array of jobs**, not an envelope object with a ``jobs``
key. We surface a clean ``ValueError`` if the response is not a list.

The id stored on ``JobListing`` is the raw Gem job id as a string
(observed numeric in the live API, e.g. ``"4123456"``). Gem ids are
unique within a board; cross-source uniqueness across Greenhouse /
Ashby / Gem is enforced by the composite ``(source_id, id)`` primary
key on ``job_listings``. Gem rows use ``source_id = 'gem_api'``.

Output shape note: the ``details`` JSONB column is populated with keys
the existing frontend ``backendScraperTransformer.ts`` reads
(``experience_level``, ``is_remote_eligible``). Gem's public API
doesn't expose an experience level structurally, so we always emit
``experience_level`` as ``None``. ``is_remote_eligible`` is derived
from ``raw.location_type == "remote"`` (Gem's enum value).

Employment type normalization mirrors what the now-deleted frontend
``gemTransformer.ts`` did: Gem returns snake_case enum values
(``full_time``, ``part_time``, ``contract``, ``intern``,
``temporary``); we map them to display casing (``Full-time``,
``Part-time``, ``Contract``, ``Internship``, ``Temporary``) so the
frontend ``backendScraperTransformer.ts`` doesn't need a per-source
re-mapping. Unrecognized values pass through unchanged.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from scripts.shared.constants import SourceId
from scripts.shared.models import JobListing
from scripts.shared.utils import get_iso_timestamp

logger = logging.getLogger(__name__)

GEM_BASE_URL = "https://api.gem.com/job_board/v0"
DEFAULT_TIMEOUT_SECONDS = 30.0
SOURCE_ID = SourceId.GEM


# Mirrors the now-deleted frontend gemTransformer.ts::normalizeEmploymentType.
# Map kept narrow on purpose: any unrecognized value passes through unchanged
# rather than silently becoming None, so unexpected Gem enum additions are
# visible to downstream consumers (the frontend, /api/jobs, etc).
_EMPLOYMENT_TYPE_MAP = {
    "full_time": "Full-time",
    "part_time": "Part-time",
    "contract": "Contract",
    "intern": "Internship",
    "temporary": "Temporary",
}


def _normalize_employment_type(value: Any) -> Optional[str]:
    """Map Gem's snake_case employment_type to display casing.

    ``None`` -> ``None``. Empty string -> ``None`` (Gem occasionally
    returns empty rather than null). Unknown values pass through
    unchanged so we surface schema drift instead of silently nulling.
    """
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        # Defensive: Gem could ship a non-string here someday. Coerce so
        # the JSONB payload stays JSON-clean, but don't pretend we know
        # what it means.
        return str(value)
    return _EMPLOYMENT_TYPE_MAP.get(value, value)


async def fetch_jobs(board_token: str, http: httpx.AsyncClient) -> list[dict]:
    """Fetch all open jobs for a Gem board.

    GETs ``{GEM_BASE_URL}/{board_token}/job_posts/``. Gem returns a
    plain JSON array; we coerce-fail on any other shape.

    Raises ``httpx.HTTPStatusError`` on non-2xx and ``ValueError`` if
    the response JSON is not a list. The caller (Unit 4) treats both as
    a failed run and lets Procrastinate retry.

    The timeout is enforced **per call** so a long-lived shared
    ``httpx.AsyncClient`` (preferred at the caller layer) keeps its
    default timeout for other use. 30s is the PLAN-mandated value.
    """
    url = f"{GEM_BASE_URL}/{board_token}/job_posts/"
    logger.info("Fetching Gem jobs for board %s", board_token)
    response = await http.get(url, timeout=DEFAULT_TIMEOUT_SECONDS)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError(
            f"Gem response for {board_token!r} is not a list: "
            f"got {type(payload).__name__}"
        )
    logger.info("Gem returned %d jobs for %s", len(payload), board_token)
    return payload


def transform_to_job_listings(
    company_id: str,
    raw_jobs: list[dict],
) -> list[JobListing]:
    """Map a list of Gem job dicts to ``JobListing`` rows.

    See module docstring for the id format and ``details`` shape
    contracts.
    """
    now = get_iso_timestamp()
    return [_transform_one(company_id, raw, now) for raw in raw_jobs]


def _transform_one(
    company_id: str,
    raw: dict[str, Any],
    now: str,
) -> JobListing:
    """Transform a single Gem job dict to a ``JobListing``."""
    raw_id = raw.get("id")
    if raw_id is None:
        raise ValueError(f"Gem job missing 'id': {raw!r}")
    # Cast defensively in case Gem ever returns a non-string id. The
    # composite ``(source_id, id)`` PK on ``job_listings`` is what
    # actually enforces cross-source uniqueness (see module docstring).
    job_id = str(raw_id)

    title = raw.get("title") or ""
    job_url = raw.get("absolute_url") or ""

    offices = raw.get("offices") or []
    # Mirror the frontend transformer: prefer offices[0].name, fall
    # back to location.name. Gem responses observed in production
    # always populate one or the other.
    primary_office_name: Optional[str] = None
    if offices and isinstance(offices[0], dict):
        primary_office_name = offices[0].get("name")
    location = primary_office_name
    if location is None:
        raw_location = raw.get("location")
        if isinstance(raw_location, dict):
            location = raw_location.get("name")

    secondary_offices = [
        o.get("name")
        for o in offices[1:]
        if isinstance(o, dict) and o.get("name")
    ]

    departments = raw.get("departments") or []
    department_name: Optional[str] = None
    if departments and isinstance(departments[0], dict):
        department_name = departments[0].get("name")

    # ``first_published_at`` is the canonical "posted on" anchor for
    # Gem boards. It can be null for very-new postings; fall back to
    # ``created_at`` so we always have a usable timestamp.
    raw_posted = raw.get("first_published_at") or raw.get("created_at")
    posted_on = _normalize_iso8601(raw_posted) if raw_posted else None
    if raw_posted and posted_on is None:
        # Per feedback_correctness_over_dont_crash: don't pass through
        # a corrupt timestamp string. Surface as a clean missing value
        # (None) and log so the data quality issue is visible in
        # stderr (Railway @level:error).
        logger.error(
            "Gem data quality issue: job %s for company %s had "
            "unparseable posted_on=%r; storing as NULL",
            raw_id,
            company_id,
            raw_posted,
        )

    details = {
        "department": department_name,
        "office": primary_office_name,
        "secondary_offices": secondary_offices,
        "employment_type": _normalize_employment_type(raw.get("employment_type")),
        "is_remote_eligible": bool(raw.get("location_type") == "remote"),
        "published_at": raw.get("first_published_at") or raw.get("created_at"),
        "content_html": raw.get("content"),
        "experience_level": None,
    }

    return JobListing(
        id=job_id,
        title=title,
        company=company_id,
        location=location,
        url=job_url,
        source_id=SOURCE_ID,
        details=details,
        posted_on=posted_on,
        created_at=now,
        first_seen_at=now,
        last_seen_at=now,
        consecutive_misses=0,
        details_scraped=True,
        status="OPEN",
        has_matched=False,
        ai_metadata={},
        closed_on=None,
    )


def _normalize_iso8601(value: str) -> Optional[str]:
    """Parse an ISO 8601 string and re-emit as UTC ISO 8601.

    Returns ``None`` if parsing fails. The caller logs and stores
    ``None`` so a corrupt source string never silently makes it into
    ``job_listings`` (per feedback_correctness_over_dont_crash). The
    row itself is preserved.

    Duplicated from ``ashby_client._normalize_iso8601`` because the two
    clients don't share a module. Both implementations are intentionally
    identical; future schema-drift fixes should be applied to both.
    """
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None
