"""Pure Greenhouse Job Board API client + transformer.

Two functions, both queue-agnostic:

- ``fetch_jobs(board_token, http)``: GETs Greenhouse's public Job Board API
  and returns the raw ``jobs`` array. No DB, no transformation.
- ``transform_to_job_listings(company_id, raw_jobs)``: maps each raw
  Greenhouse job dict to a :class:`scripts.shared.models.JobListing`
  ready for ``upsert_jobs_batch``.

The id format is the raw Greenhouse job id as a string (e.g. ``"7546284"``).
Cross-source uniqueness lives in the database schema via the composite
``(source_id, id)`` primary key on ``job_listings`` — Greenhouse rows
use ``source_id = 'greenhouse_api'``. Greenhouse guarantees that raw ids
are globally unique across the entire Greenhouse Job Board platform.

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

from scripts.shared.constants import SourceId
from scripts.shared.models import JobListing
from scripts.shared.utils import get_iso_timestamp

from .harvest_meta import HarvestEvidence
from .job_details import has_description
from .posted_date import effective_posted_date

logger = logging.getLogger(__name__)

GREENHOUSE_BASE_URL = "https://boards-api.greenhouse.io/v1/boards"
DEFAULT_TIMEOUT_SECONDS = 30.0
SOURCE_ID = SourceId.GREENHOUSE


async def fetch_jobs_with_meta(
    board_token: str, http: httpx.AsyncClient
) -> tuple[list[dict], HarvestEvidence]:
    """Fetch a Greenhouse board AND the completeness evidence around it (E7).

    Same single GET as :func:`fetch_jobs` (``?content=true``) but ALSO captures
    ``payload["meta"]["total"]`` — Greenhouse's own trusted, independent count,
    which the public path discards. That total is the ``declared_probed`` oracle:
    the gate verifies iff ``len(deduped) == meta.total`` exactly.

    ``meta.total`` missing or non-int → ``declared_total=None`` (defensive; never
    raises on a missing total — an absent trusted total simply means the zero /
    count checks fall back to "cannot prove", never a crash). Greenhouse is a
    single GET so this is always ``HarvestEvidence.single_shot`` (no cap, no
    pagination to advance).
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

    meta = payload.get("meta")
    raw_total = meta.get("total") if isinstance(meta, dict) else None
    declared_total = raw_total if isinstance(raw_total, int) and raw_total >= 0 else None

    logger.info(
        "Greenhouse returned %d jobs for %s (meta.total=%r)",
        len(jobs), board_token, declared_total,
    )
    return jobs, HarvestEvidence.single_shot(declared_total=declared_total)


async def fetch_jobs(board_token: str, http: httpx.AsyncClient) -> list[dict]:
    """Fetch all open jobs for a Greenhouse board.

    Thin delegator over :func:`fetch_jobs_with_meta` that discards the evidence,
    so the six PUBLIC ATS crons keep byte-identical behavior (same GET, same
    return type). Only the custom path reads the meta.

    Raises ``httpx.HTTPStatusError`` on non-2xx and ``ValueError`` if the
    response JSON is missing the ``jobs`` key. The caller treats both as a failed
    run and lets Procrastinate retry.
    """
    jobs, _ = await fetch_jobs_with_meta(board_token, http)
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
    job_id = str(raw_id)

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

    # Which field the date came from, recorded alongside it. Greenhouse omits
    # `first_published` on some boards and we silently fall back to
    # `updated_at`, which moves whenever anyone edits the posting — so "this
    # row's date is a real publish date" and "this row's date is a last-touched
    # date" were indistinguishable after the fact. `posted_on_field` names the
    # field that supplied the raw value (even if it then failed to parse).
    if raw.get("first_published"):
        posted_on_raw = raw["first_published"]
        posted_on_field: Optional[str] = "first_published"
    elif raw.get("updated_at"):
        posted_on_raw = raw["updated_at"]
        posted_on_field = "updated_at"
    else:
        posted_on_raw = None
        posted_on_field = None
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
        "posted_on_field": posted_on_field,
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
        # THE EFFECTIVE POSTED DATE (POSTED-DATE-PLAN.md §2, D9/D10): Greenhouse's
        # ``first_published`` (or its ``updated_at`` fallback — ``details
        # .posted_on_field`` records which), first sight otherwise.
        #
        # Safe with no first-run predicate because ``first_seen_at`` is absent
        # from ``_UPSERT_ON_CONFLICT`` (scripts/shared/database.py) — this line
        # only ever decides an INSERT and can never rewrite an existing row.
        first_seen_at=effective_posted_date(posted_on, now),
        last_seen_at=now,
        consecutive_misses=0,
        # Truthful, not hard-coded True: this claims we HAVE the job's detail
        # content. See ``job_details.has_description`` for what that means and
        # which rows were lying.
        details_scraped=has_description(details),
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
