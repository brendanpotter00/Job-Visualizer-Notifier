"""Pure Greenhouse Job Board API client + transformer.

Two functions, both queue-agnostic:

- ``fetch_jobs(board_token, http)``: GETs Greenhouse's public Job Board API
  and returns the raw ``jobs`` array. No DB, no transformation.
- ``transform_to_job_listings(company_id, raw_jobs)``: maps each raw
  Greenhouse job dict to a :class:`scripts.shared.models.JobListing`
  ready for ``upsert_jobs_batch``.

The id format is ``greenhouse_{raw['id']}``. Greenhouse job IDs are
globally unique across the entire Greenhouse Job Board platform, so the
source-namespace prefix is enough to prevent collisions with other ATS
providers in ``job_listings`` (Apple, Google, Microsoft).

Output shape note: the ``details`` JSONB column is populated with keys that
the existing frontend ``backendScraperTransformer.ts`` reads
(``experience_level``, ``is_remote_eligible``). Greenhouse's public Job
Board API doesn't expose these structurally, so we always emit them as
``None`` / ``False`` - the frontend parser tolerates missing keys; we set
them to keep one consistent shape across sources.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from scripts.shared.models import JobListing
from scripts.shared.utils import get_iso_timestamp

logger = logging.getLogger(__name__)

GREENHOUSE_BASE_URL = "https://boards-api.greenhouse.io/v1/boards"
DEFAULT_TIMEOUT_SECONDS = 30.0
SOURCE_ID = "greenhouse_api"


async def fetch_jobs(board_token: str, http: httpx.AsyncClient) -> list[dict]:
    """Fetch all open jobs for a Greenhouse board.

    GETs ``{GREENHOUSE_BASE_URL}/{board_token}/jobs?content=true``. The
    ``content=true`` param asks Greenhouse to include the job body HTML in
    the response - needed by future enrichment but not by this unit.

    Raises ``httpx.HTTPStatusError`` on non-2xx and ``ValueError`` if the
    response JSON is missing the ``jobs`` key. The caller (Unit 4) treats
    both as a failed run and lets Procrastinate retry.

    The timeout is enforced **per call** so a long-lived shared
    ``httpx.AsyncClient`` (preferred at the caller layer) keeps its default
    timeout for other use. 30s is the PLAN-mandated value.
    """
    url = f"{GREENHOUSE_BASE_URL}/{board_token}/jobs"
    logger.info("Fetching Greenhouse jobs for board %s", board_token)
    response = await http.get(
        url,
        params={"content": "true"},
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or "jobs" not in payload:
        raise ValueError(
            f"Greenhouse response for {board_token!r} missing 'jobs' key: "
            f"got keys {sorted(payload) if isinstance(payload, dict) else type(payload).__name__}"
        )
    jobs = payload["jobs"]
    if not isinstance(jobs, list):
        raise ValueError(
            f"Greenhouse 'jobs' for {board_token!r} is not a list: "
            f"got {type(jobs).__name__}"
        )
    logger.info("Greenhouse returned %d jobs for %s", len(jobs), board_token)
    return jobs


def transform_to_job_listings(
    company_id: str,
    raw_jobs: list[dict],
) -> list[JobListing]:
    """Map a list of Greenhouse job dicts to ``JobListing`` rows.

    See module docstring for the id format and ``details`` shape contracts.
    """
    now = get_iso_timestamp()
    return [_transform_one(company_id, raw, now) for raw in raw_jobs]


def _transform_one(
    company_id: str,
    raw: dict[str, Any],
    now: str,
) -> JobListing:
    """Transform a single Greenhouse job dict to a ``JobListing``."""
    raw_id = raw.get("id")
    if raw_id is None:
        raise ValueError(f"Greenhouse job missing 'id': {raw!r}")
    job_id = f"greenhouse_{raw_id}"

    title = raw.get("title") or ""
    absolute_url = raw.get("absolute_url") or ""

    offices = raw.get("offices") or []
    office_name = offices[0].get("name") if offices and isinstance(offices[0], dict) else None
    top_location = raw.get("location") or {}
    location_name = office_name or (top_location.get("name") if isinstance(top_location, dict) else None)

    departments = raw.get("departments") or []
    department_name = (
        departments[0].get("name")
        if departments and isinstance(departments[0], dict)
        else None
    )

    tags: list[str] = []
    for entry in raw.get("metadata") or []:
        if not isinstance(entry, dict):
            continue
        value = entry.get("value")
        if isinstance(value, str) and value:
            tags.append(value)
        elif isinstance(value, list):
            tags.extend(v for v in value if isinstance(v, str) and v)

    posted_on_raw = raw.get("first_published") or raw.get("updated_at")
    posted_on = _normalize_iso8601(posted_on_raw) if posted_on_raw else None
    if posted_on_raw and posted_on is None:
        # Per feedback_correctness_over_dont_crash: don't pass through a corrupt
        # timestamp string. Surface as a clean missing value (None) and log so the
        # data quality issue is visible in stderr (Railway @level:error).
        # ERROR (not WARNING): the comment block above promises stderr routing,
        # and Railway derives @level from Python log level.
        logger.error(
            "Greenhouse data quality issue: job %s for company %s had "
            "unparseable posted_on=%r; storing as NULL",
            raw_id,
            company_id,
            posted_on_raw,
        )

    details = {
        "department": department_name,
        "office_locations": [
            o.get("name") for o in offices if isinstance(o, dict) and o.get("name")
        ],
        "tags": tags,
        "absolute_url": absolute_url,
        "updated_at": raw.get("updated_at"),
        "first_published": raw.get("first_published"),
        "content": raw.get("content"),
        "experience_level": None,
        "is_remote_eligible": False,
    }

    return JobListing(
        id=job_id,
        title=title,
        company=company_id,
        location=location_name,
        url=absolute_url,
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

    Returns ``None`` if parsing fails. The caller logs and stores ``None`` so
    a corrupt source string never silently makes it into ``job_listings``
    (per feedback_correctness_over_dont_crash). The row itself is preserved.
    """
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None
