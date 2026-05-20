"""Pure Lever Postings API client + transformer.

Two functions, both queue-agnostic:

- ``fetch_jobs(board_token, http)``: GETs Lever's public Postings API
  and returns the raw top-level array. No DB, no transformation.
- ``transform_to_job_listings(company_id, raw_jobs)``: maps each raw
  Lever job dict to a :class:`scripts.shared.models.JobListing`
  ready for ``upsert_jobs_batch``.

The id stored on ``JobListing`` is the raw Lever job id as a string. Lever ids
are observed to be UUID-shaped (e.g. ``"4e1c7a5a-5b0a-4e6f-9a7c-1ad3c4f7b6e9"``)
but the actual cross-source uniqueness guarantee lives in the ``job_listings``
schema via the composite ``(source_id, id)`` primary key. Lever rows use
``source_id = 'lever_api'``, so even if a raw id ever collides with a
different source's raw id, the composite PK keeps them distinct.

Output shape note: the ``details`` JSONB column is populated with keys that
the existing frontend ``backendScraperTransformer.ts`` reads
(``experience_level``, ``is_remote_eligible``, ``tags``). Lever's public
Postings API doesn't expose an experience level structurally, so we always
emit ``experience_level`` as ``None``. ``is_remote_eligible`` is the boolean
``raw["workplaceType"] == "remote"`` (Lever returns ``"remote" | "onsite" |
"unspecified"``; missing / unspecified both map to ``False``).

Lever returns a top-level JSON ARRAY (not a ``{"jobs": [...]}`` wrapper) —
``fetch_jobs`` validates the root type and raises ``ValueError`` if Lever ever
changes that contract (so we don't silently treat a wrapping dict as a list).
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

LEVER_BASE_URL = "https://api.lever.co/v0/postings"
DEFAULT_TIMEOUT_SECONDS = 30.0
SOURCE_ID = SourceId.LEVER


async def fetch_jobs(board_token: str, http: httpx.AsyncClient) -> list[dict]:
    """Fetch all open postings for a Lever board.

    GETs ``{LEVER_BASE_URL}/{board_token}?mode=json``. Lever returns a flat
    JSON array as the response root (unlike Ashby's ``{"jobs": [...]}`` or
    Greenhouse's ``{"jobs": [...], "meta": ...}`` envelopes).

    Raises ``httpx.HTTPStatusError`` on non-2xx and ``ValueError`` if the
    response root is not a list. The caller (Unit 4) treats both as a failed
    run and lets Procrastinate retry.

    The timeout is enforced **per call** so a long-lived shared
    ``httpx.AsyncClient`` (preferred at the caller layer) keeps its default
    timeout for other use. 30s is the PLAN-mandated value.
    """
    url = f"{LEVER_BASE_URL}/{board_token}"
    logger.info("Fetching Lever postings for board %s", board_token)
    response = await http.get(
        url,
        params={"mode": "json"},
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError(
            f"Lever response for {board_token!r} is not a list: "
            f"got {type(payload).__name__}"
        )
    logger.info("Lever returned %d postings for %s", len(payload), board_token)
    return payload


def transform_to_job_listings(
    company_id: str,
    raw_jobs: list[dict],
) -> list[JobListing]:
    """Map a list of Lever posting dicts to ``JobListing`` rows.

    See module docstring for the id format and ``details`` shape contracts.
    """
    now = get_iso_timestamp()
    return [_transform_one(company_id, raw, now) for raw in raw_jobs]


def _transform_one(
    company_id: str,
    raw: dict[str, Any],
    now: str,
) -> JobListing:
    """Transform a single Lever posting dict to a ``JobListing``."""
    raw_id = raw.get("id")
    if raw_id is None:
        raise ValueError(f"Lever posting missing 'id': {raw!r}")
    # Lever ids have historically been UUID-shaped strings, but cast
    # defensively in case a future response ever ships a non-string id.
    # The composite ``(source_id, id)`` PK on ``job_listings`` is what
    # actually enforces cross-source uniqueness (see module docstring).
    job_id = str(raw_id)

    # Lever names the title field "text" (not "title"). Defensive default
    # to empty string mirrors the Ashby/Greenhouse transformers.
    title = raw.get("text") or ""
    job_url = raw.get("hostedUrl") or ""

    cats = raw.get("categories") or {}
    if not isinstance(cats, dict):
        # Lever has historically always returned categories as an object,
        # but coerce to {} so a future schema drift doesn't crash the whole
        # batch. Mirrors the .get("offices") or [] pattern in gem_client.
        cats = {}

    location = cats.get("location")

    created_at_ms = raw.get("createdAt")
    posted_on = _ms_to_iso8601(created_at_ms)
    if created_at_ms is not None and posted_on is None:
        # Per feedback_correctness_over_dont_crash: don't pass through a
        # corrupt timestamp. Surface as a clean missing value (None) and log
        # so the data quality issue is visible in stderr (Railway @level:error).
        # ERROR (not WARNING): Railway derives @level from Python log level.
        logger.error(
            "Lever data quality issue: posting %s for company %s had "
            "unparseable createdAt=%r; storing posted_on as NULL",
            raw_id,
            company_id,
            created_at_ms,
        )

    details = {
        "department": cats.get("department"),
        "team": cats.get("team"),
        # Lever's postings endpoint doesn't expose secondary location lists;
        # populate the key with an empty list so the JSONB shape stays
        # stable across all three providers.
        "secondary_locations": [],
        "employment_type": cats.get("commitment"),
        "is_remote_eligible": raw.get("workplaceType") == "remote",
        # Lever's postings endpoint doesn't expose compensation tier
        # summaries (only the v1 /opportunities endpoint does, behind auth).
        # Emit None so the JSONB shape stays parallel to Ashby/Greenhouse.
        "compensation_summary": None,
        "published_at": posted_on,
        # Lever's postings endpoint exposes both `description` (HTML) and
        # `descriptionPlain` (text). The Ashby/Greenhouse JSONB key is
        # `description_html`; we prefer the HTML form. If only the plain
        # form is present, fall back so the field is non-empty.
        "description_html": raw.get("description") or raw.get("descriptionPlain"),
        "experience_level": None,
        "tags": _sanitize_tags(raw.get("tags") or []),
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


def _ms_to_iso8601(value: Any) -> Optional[str]:
    """Convert an epoch-milliseconds value to an ISO 8601 UTC string.

    Returns ``None`` for ``None``, non-numeric types, or values that overflow
    Python's ``datetime`` range. The caller logs and stores ``None`` so a
    corrupt source value never silently lands in ``job_listings``
    (per feedback_correctness_over_dont_crash). The row itself is preserved.
    """
    if value is None:
        return None
    # Lever's createdAt is documented as Unix milliseconds (integer).
    # Defensively accept both int and float — boolean is a subclass of int
    # in Python, so explicitly reject bools to avoid silent coercion.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        # OverflowError: epoch too far in past/future for the platform's
        # time_t range. OSError: same condition on some platforms. ValueError:
        # negative epoch on Windows. All three map to "we can't parse this"
        # rather than crashing the whole batch.
        return None


def _sanitize_tags(raw_tags: Any) -> list[str]:
    """Flatten Lever's ``(string | string[] | null)[]`` tag shape to ``list[str]``.

    Mirrors the frontend ``sanitizeTags`` helper in ``src/frontend/src/lib/tags.ts``:
    nested arrays are flattened one level, non-string entries are dropped,
    and empty strings are dropped. Insertion order is preserved.

    Frontend does NOT deduplicate, so neither do we — same downstream display
    semantics as before the migration.
    """
    if not isinstance(raw_tags, list):
        return []
    out: list[str] = []
    for tag in raw_tags:
        if isinstance(tag, list):
            for t in tag:
                if isinstance(t, str) and t:
                    out.append(t)
        elif isinstance(tag, str) and tag:
            out.append(tag)
        # Non-string non-list (None, int, dict, bool, etc.) — drop.
    return out
