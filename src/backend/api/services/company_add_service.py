"""Orchestration for the add-company-by-URL flow (Tier 1, synchronous).

Ties together SSRF validation, deterministic ATS detection, dedup, the company
row insert, and additive per-user enablement. The async Tier-2 path (custom
sites needing a Playwright capture + Haiku recipe) is handled by
``tasks/onboard_custom_company.py``; this service decides which path a URL takes
and performs the whole Tier-1 path in-request.

Dedup is by scrape target, not per user: two users adding the same board share
one ``companies`` row (see the migration/plan for why physical duplication would
corrupt ``job_listings``). "Private" = the row is ``listed = false`` (never in
the public directory) and only visible to users who have enabled it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from scripts.shared import database as db

from . import company_submissions as subs
from .ats_detector import detect_ats
from .url_guard import BlockedURLError, validate_public_url

logger = logging.getLogger(__name__)


@dataclass
class AddOutcome:
    """Result of the synchronous add attempt.

    ``status`` is one of:
    * ``added`` — a new company row was created + enabled (``company`` set).
    * ``already_tracked`` — the board already existed; just enabled (``company`` set).
    * ``needs_onboarding`` — no known ATS; caller must create a submission and
      defer the Tier-2 onboarding task (``company`` is None).
    """

    status: str
    company: Optional[dict[str, Any]] = None


def company_to_dto(row: dict[str, Any]) -> dict[str, Any]:
    """Map a ``companies`` row to the frontend CompanyDTO (snake_case keys;
    the Pydantic response model applies camelCase aliases)."""
    provider_config = row.get("provider_config") or {}
    return {
        "id": row["id"],
        "name": row.get("display_name") or row["id"],
        "jobs_url": provider_config.get("careers_url"),
        "source_ats": row.get("ats"),
    }


async def try_add_by_url(
    conn: Any, user_id: str, url: str, http: httpx.AsyncClient
) -> AddOutcome:
    """Attempt the synchronous (Tier-1) add. Raises BlockedURLError for bad URLs.

    Returns an :class:`AddOutcome`. For ``needs_onboarding`` the caller owns
    creating the submission row + deferring the onboarding task (keeps the
    Procrastinate dependency at the router edge and this service unit-testable
    without a queue).
    """
    validate_public_url(url)  # 422 upstream on failure

    detection = await detect_ats(url, http)
    if detection is None:
        return AddOutcome(status="needs_onboarding")

    # Dedup: same board (ats, board_token) or same derived id already present?
    existing = db.find_company_by_ats_token(
        conn, detection.ats, detection.board_token
    ) or db.get_company_by_id(conn, detection.company_id)
    if existing is not None:
        subs.enable_company_for_user(conn, user_id, existing["id"])
        return AddOutcome(status="already_tracked", company=existing)

    provider_config = dict(detection.provider_config)
    provider_config["careers_url"] = url  # so the UI can link back to the board
    row = db.insert_user_company(
        conn,
        company_id=detection.company_id,
        display_name=detection.display_name,
        ats=detection.ats,
        board_token=detection.board_token,
        added_by_user_id=user_id,
        provider_config=provider_config,
    )
    subs.enable_company_for_user(conn, user_id, row["id"])
    logger.info(
        "user %s added company %s (ats=%s, %d jobs on probe)",
        user_id, row["id"], detection.ats, detection.job_count,
    )
    return AddOutcome(status="added", company=row)


def list_user_custom_companies(conn: Any, user_id: str) -> list[dict[str, Any]]:
    """Return the user's tracked *unlisted* companies as CompanyDTO dicts.

    These are the runtime-added companies not present in the frontend's static
    ``COMPANIES`` (curated ones already ship in the bundle). The jobs UI merges
    this list with the static one.
    """
    cursor = conn.cursor()
    cursor.execute(
        "SELECT c.id, c.display_name, c.ats, c.provider_config "
        "FROM user_enabled_companies e "
        "JOIN companies c ON c.id = e.company_id "
        "WHERE e.user_id = %s AND c.listed = false AND c.enabled = true "
        "ORDER BY lower(c.display_name), c.id",
        (user_id,),
    )
    return [company_to_dto(dict(row)) for row in cursor.fetchall()]


def company_exists(conn: Any, company_id: str) -> bool:
    """True if a company row with this id exists (used to validate enablement)."""
    return db.get_company_by_id(conn, company_id) is not None


# Re-export for callers that want to catch the SSRF error type without importing
# url_guard directly.
__all__ = [
    "AddOutcome",
    "BlockedURLError",
    "company_to_dto",
    "try_add_by_url",
    "list_user_custom_companies",
    "company_exists",
]
