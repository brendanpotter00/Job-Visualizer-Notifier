"""Procrastinate task: one-time onboarding of a custom (non-ATS) career site.

The expensive, once-per-company path. Loads the submitted careers URL in our own
Playwright (no Browserbase), captures the JSON API calls the page makes, asks
Claude Haiku to write a ``custom_json`` recipe from them
(``services/recipe_generator``), **validates the recipe deterministically** by
replaying it, and only then creates the (unlisted) company row + enables it for
the submitter. The submission row is moved to ``succeeded`` / ``failed`` so the
frontend poller can react.

Nothing here runs on the recurring scrape — once the recipe is stored, the
company rides the normal ``custom_json`` fan-out as a plain HTTP call.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlsplit

import httpx

from scripts.shared import database as db

from ..config import settings
from ..services import company_submissions as subs
from ..services import recipe_generator
from ..services.custom_json_client import fetch_jobs as replay_recipe
from ..services.custom_json_client import transform_to_job_listings
from ..services.url_guard import BlockedURLError, validate_public_url
from .procrastinate_app import procrastinate_app

logger = logging.getLogger(__name__)

# Bounds for the capture step.
_NAV_TIMEOUT_MS = 30_000
_SETTLE_MS = 4_000
_MAX_CAPTURED = 20
_SLUG_MAX = 64


class _OnboardingFailure(Exception):
    """Carries a user-safe message to store on the failed submission."""


@procrastinate_app.task(queue="onboarding", name="onboard_custom_company")
async def onboard_custom_company(
    submission_id: str, user_id: str, url: str
) -> None:
    """Run the capture → recipe → validate → create pipeline for one submission."""
    conn = await asyncio.to_thread(
        db.get_connection,
        settings.database_url,
        application_name="task_onboard_custom",
    )
    try:
        company = await _onboard(conn, user_id, url)
        await asyncio.to_thread(
            subs.finish_submission,
            conn, submission_id, status="succeeded", company_id=company["id"],
        )
        logger.info(
            "onboarding %s succeeded: created/enabled %s", submission_id, company["id"]
        )
    except _OnboardingFailure as exc:
        await asyncio.to_thread(
            subs.finish_submission,
            conn, submission_id, status="failed", error=str(exc),
        )
        logger.info("onboarding %s failed: %s", submission_id, exc)
    except Exception:  # noqa: BLE001 - convert any unexpected error to a failed submission
        logger.exception("onboarding %s crashed", submission_id)
        try:
            await asyncio.to_thread(
                subs.finish_submission,
                conn, submission_id, status="failed",
                error="We couldn't analyze that site. Please try a different URL.",
            )
        except Exception:
            logger.exception("failed to mark submission %s failed", submission_id)
    finally:
        try:
            await asyncio.to_thread(conn.close)
        except Exception:
            logger.error("onboarding conn close failed", exc_info=True)


async def _onboard(conn: Any, user_id: str, url: str) -> dict[str, Any]:
    """Do the work; raise _OnboardingFailure with a user-safe message on failure."""
    try:
        validate_public_url(url)
    except BlockedURLError as exc:
        raise _OnboardingFailure("That URL can't be fetched.") from exc

    candidates = await _capture_json_calls(url)
    if not candidates:
        raise _OnboardingFailure(
            "We couldn't find a job data source on that page. It may not be a "
            "supported job board."
        )

    try:
        recipe = await recipe_generator.generate_recipe(url, candidates)
    except recipe_generator.MissingAnthropicKeyError as exc:
        raise _OnboardingFailure(
            "Custom-site support is temporarily unavailable."
        ) from exc
    except recipe_generator.RecipeGenerationError as exc:
        raise _OnboardingFailure(
            "We couldn't build a scraper for that site."
        ) from exc

    # Deterministic validation gate: the recipe must actually yield >=1 job.
    recipe["careers_url"] = url
    try:
        async with httpx.AsyncClient() as http:
            raw = await replay_recipe(recipe, http)
        jobs = transform_to_job_listings("__probe__", raw, recipe)
    except Exception as exc:  # noqa: BLE001 - any replay error = unusable recipe
        raise _OnboardingFailure(
            "We built a scraper for that site but it didn't return any jobs."
        ) from exc
    if not jobs:
        raise _OnboardingFailure(
            "We built a scraper for that site but it didn't return any jobs."
        )

    company_id, display_name, board_token = _identity_from_url(url)

    existing = await asyncio.to_thread(db.get_company_by_id, conn, company_id)
    if existing is not None:
        await asyncio.to_thread(
            subs.enable_company_for_user, conn, user_id, existing["id"]
        )
        return existing

    row = await asyncio.to_thread(
        _insert_custom_company,
        conn, company_id, display_name, board_token, user_id, recipe,
    )
    await asyncio.to_thread(subs.enable_company_for_user, conn, user_id, row["id"])
    return row


def _insert_custom_company(
    conn: Any,
    company_id: str,
    display_name: str,
    board_token: str,
    user_id: str,
    recipe: dict[str, Any],
) -> dict[str, Any]:
    return db.insert_user_company(
        conn,
        company_id=company_id,
        display_name=display_name,
        ats="custom_json",
        board_token=board_token,
        added_by_user_id=user_id,
        provider_config=recipe,
    )


def _identity_from_url(url: str) -> tuple[str, str, str]:
    """Derive (company_id, display_name, board_token) from a careers URL host."""
    host = (urlsplit(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    # Common careers subdomains add no identity — strip them for a cleaner slug.
    for prefix in ("careers.", "jobs.", "job.", "apply."):
        if host.startswith(prefix):
            host = host[len(prefix):]
            break
    company_id = host[:_SLUG_MAX] or "custom-site"
    # Registrable-ish label for the display name (second-to-last host label).
    labels = [p for p in host.split(".") if p]
    core = labels[-2] if len(labels) >= 2 else (labels[0] if labels else host)
    display_name = core.replace("-", " ").title() if core else host
    return company_id, display_name, host


async def _capture_json_calls(url: str) -> list[dict[str, Any]]:
    """Load the page in Playwright and capture JSON API responses.

    Returns a list of ``{method, url, sample}`` (deduped by request URL, capped).
    Any Playwright/import failure yields an empty list (the caller turns that into
    a user-safe "no data source found" failure).
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("Playwright not installed; cannot onboard custom site %s", url)
        return []

    captured: dict[str, dict[str, Any]] = {}

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                page = await browser.new_page()

                async def _on_response(response: Any) -> None:
                    if len(captured) >= _MAX_CAPTURED:
                        return
                    try:
                        ctype = response.headers.get("content-type", "")
                        if "application/json" not in ctype or not response.ok:
                            return
                        req_url = response.url
                        if req_url in captured:
                            return
                        # Only validate the host is public; we're reading a body
                        # the browser already fetched, but keep the guard honest.
                        try:
                            validate_public_url(req_url)
                        except BlockedURLError:
                            return
                        body = await response.json()
                        if _looks_like_jobs(body):
                            captured[req_url] = {
                                "method": response.request.method,
                                "url": req_url,
                                "sample": body,
                            }
                    except Exception:  # noqa: BLE001 - a single bad response never aborts capture
                        return

                page.on("response", lambda r: asyncio.ensure_future(_on_response(r)))
                await page.goto(url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT_MS)
                await page.wait_for_timeout(_SETTLE_MS)
            finally:
                await browser.close()
    except Exception:  # noqa: BLE001 - navigation/launch failure = no candidates
        logger.warning("Playwright capture failed for %s", url, exc_info=True)
        return []

    return list(captured.values())


def _looks_like_jobs(body: Any) -> bool:
    """Cheap heuristic: does this JSON plausibly contain a list of postings?

    Keeps obviously-irrelevant responses (analytics pings, config blobs) out of
    the Haiku prompt so the token budget goes to real candidates.
    """
    def _has_list(obj: Any, depth: int = 0) -> bool:
        if depth > 4:
            return False
        if isinstance(obj, list):
            return len(obj) > 0 and isinstance(obj[0], (dict, str))
        if isinstance(obj, dict):
            return any(_has_list(v, depth + 1) for v in obj.values())
        return False

    return _has_list(body)
