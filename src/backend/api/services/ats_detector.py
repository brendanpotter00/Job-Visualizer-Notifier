"""Deterministic ATS detection for a user-submitted careers URL.

Given a URL, work out whether it belongs to an ATS we already scrape
(Greenhouse / Ashby / Lever / Gem / Workday), extract the board identifier, and
**confirm by probing the live ATS API** before we commit a company row. No LLM,
no browser — just URL parsing + one HTTP probe reusing the existing per-ATS
clients (``services/*_client.py``).

Two matching strategies:

1. **URL shape** — the host/path uniquely identifies the ATS and its board token
   (``boards.greenhouse.io/<token>``, ``jobs.lever.co/<token>``,
   ``<sub>.<hostslug>.myworkdayjobs.com/<lang>/<career_site_slug>``, …).
2. **HTML marker** — when the URL is a company's own careers domain, fetch the
   page (through the SSRF guard) and look for an embedded supported board.

A match is returned only if the probe returns a valid (possibly empty) job list;
a 404 / malformed response means "no such board" and is treated as no match.

Returns a :class:`Detection` on success, or ``None`` when nothing matched (the
caller then falls through to the Tier-2 custom-site recipe flow).

Eightfold is intentionally **not** auto-detected here: its API needs a
``domain`` param that isn't derivable from the URL, and non-``*.eightfold.ai``
vanity hosts require a code allowlist edit (see ``eightfold_client.py``). Such
URLs fall through to Tier 2 or a clear "unsupported" message.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlsplit

import httpx

from . import (
    ashby_client,
    gem_client,
    greenhouse_client,
    lever_client,
    workday_client,
)
from . import url_guard

logger = logging.getLogger(__name__)

# A board token / slug we're willing to store as companies.id. Mirrors the
# frontend ENABLED_COMPANY_ID_PATTERN (interior dots allowed, e.g. happyrobot.ai).
_SLUG_RE = re.compile(r"^[a-zA-Z0-9_-]+(\.[a-zA-Z0-9_-]+)*$")


@dataclass
class Detection:
    """A confirmed ATS match ready to become a ``companies`` row."""

    ats: str  # 'greenhouse' | 'ashby' | 'lever' | 'gem' | 'workday'
    company_id: str  # slug → companies.id
    display_name: str
    board_token: str
    provider_config: dict[str, Any] = field(default_factory=dict)
    job_count: int = 0


def _slugify_token(token: str) -> Optional[str]:
    """Return a lowercased id slug for ``token`` or None if it can't be one."""
    candidate = token.strip().lower()
    if candidate and _SLUG_RE.match(candidate) and len(candidate) <= 64:
        return candidate
    return None


def _display_name_from(token: str) -> str:
    """Best-effort human name from a board token (``fireworksai`` → ``Fireworksai``)."""
    cleaned = re.sub(r"[-_]+", " ", token.strip()).strip()
    return cleaned.title() if cleaned else token


def _first_path_segment(path: str) -> Optional[str]:
    segments = [seg for seg in path.split("/") if seg]
    return segments[0] if segments else None


# --- Per-ATS candidate extraction from a URL (no network) --------------------


def _candidate_from_url(url: str) -> Optional[tuple[str, str, dict[str, Any]]]:
    """Return ``(ats, board_token, provider_config)`` from URL shape, or None."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    path = parts.path or ""

    # Greenhouse: boards.greenhouse.io/<token>, job-boards.greenhouse.io/<token>,
    # boards.eu.greenhouse.io/<token>
    if host.endswith("greenhouse.io"):
        token = _first_path_segment(path)
        if token and token not in ("embed",):
            return ("greenhouse", token, {})

    # Ashby: jobs.ashbyhq.com/<token> or api.ashbyhq.com/posting-api/job-board/<token>
    if host == "jobs.ashbyhq.com":
        token = _first_path_segment(path)
        if token:
            return ("ashby", token, {})
    if host == "api.ashbyhq.com" and "/posting-api/job-board/" in path:
        token = path.split("/posting-api/job-board/", 1)[1].split("/", 1)[0]
        if token:
            return ("ashby", token, {})

    # Lever: jobs.lever.co/<token>
    if host == "jobs.lever.co":
        token = _first_path_segment(path)
        if token:
            return ("lever", token, {})

    # Gem: jobs.gem.com/<token> (public board host)
    if host == "jobs.gem.com":
        token = _first_path_segment(path)
        if token:
            return ("gem", token, {})

    # Workday: <sub>.<hostslug>.myworkdayjobs.com/<maybe-lang>/<career_site_slug>
    if host.endswith(".myworkdayjobs.com"):
        cfg = _workday_config_from(parts)
        if cfg is not None:
            return ("workday", cfg["tenant_slug"], cfg)

    return None


def _workday_config_from(parts: Any) -> Optional[dict[str, Any]]:
    """Derive Workday ``provider_config`` from a myworkdayjobs URL.

    ``https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite`` →
    ``{base_url: 'https://nvidia.wd5.myworkdayjobs.com', tenant_slug: 'nvidia',
       career_site_slug: 'NVIDIAExternalCareerSite'}``.

    The tenant slug can legitimately differ from the host label (e.g. Slack's is
    ``salesforce``); we use the host's first label as the best URL-derivable
    guess and rely on the probe to confirm — a wrong guess simply fails to
    detect (falls through) rather than creating a broken row.
    """
    host = (parts.hostname or "").lower()
    labels = host.split(".")
    if len(labels) < 3:
        return None
    tenant_slug = labels[0]
    segments = [seg for seg in (parts.path or "").split("/") if seg]
    # Drop a leading locale segment like 'en-US' / 'en'.
    if segments and re.fullmatch(r"[a-z]{2}(-[A-Za-z]{2})?", segments[0]):
        segments = segments[1:]
    if not segments:
        return None
    career_site_slug = segments[0]
    base_url = f"{parts.scheme}://{parts.hostname}"
    return {
        "base_url": base_url,
        "tenant_slug": tenant_slug,
        "career_site_slug": career_site_slug,
    }


# --- HTML-marker fallback ----------------------------------------------------

# Company careers pages frequently embed a supported ATS board. These patterns
# pull the board token out of the embedded markup / script src.
_HTML_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("greenhouse", re.compile(r"boards\.greenhouse\.io/embed/job_board\?for=([a-zA-Z0-9_-]+)")),
    ("greenhouse", re.compile(r"(?:job-)?boards(?:\.eu)?\.greenhouse\.io/([a-zA-Z0-9_-]+)")),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([a-zA-Z0-9_-]+)")),
    ("lever", re.compile(r"jobs\.lever\.co/([a-zA-Z0-9_-]+)")),
    ("gem", re.compile(r"jobs\.gem\.com/([a-zA-Z0-9_-]+)")),
)


async def _candidate_from_html(
    url: str, http: httpx.AsyncClient
) -> Optional[tuple[str, str, dict[str, Any]]]:
    """Fetch the page (SSRF-guarded) and extract an embedded board, or None."""
    try:
        response = await url_guard.safe_get(http, url)
    except (url_guard.BlockedURLError, httpx.HTTPError) as exc:
        logger.info("HTML marker fetch failed for %s: %s", url, exc)
        return None
    if response.status_code >= 400:
        return None
    html = response.text
    for ats, pattern in _HTML_MARKERS:
        match = pattern.search(html)
        if match:
            token = match.group(1)
            if token and token != "embed":
                return (ats, token, {})
    return None


# --- Probing (confirm the board exists) --------------------------------------


async def _probe(
    ats: str,
    board_token: str,
    provider_config: dict[str, Any],
    http: httpx.AsyncClient,
) -> Optional[int]:
    """Hit the ATS API. Return job count on success, None if the board is invalid.

    A non-2xx (``HTTPStatusError``) or malformed body (``ValueError``) means the
    board doesn't exist / isn't what we think → None. A valid empty board
    returns 0 (still a real board — accepted). Workday's host is user-derived, so
    that probe goes through the SSRF guard inside ``workday_client`` — here we
    additionally pre-validate the base_url.
    """
    try:
        if ats == "greenhouse":
            jobs = await greenhouse_client.fetch_jobs(board_token, http)
        elif ats == "ashby":
            jobs = await ashby_client.fetch_jobs(board_token, http)
        elif ats == "lever":
            jobs = await lever_client.fetch_jobs(board_token, http)
        elif ats == "gem":
            jobs = await gem_client.fetch_jobs(board_token, http)
        elif ats == "workday":
            url_guard.validate_public_url(provider_config["base_url"])
            jobs = await workday_client.fetch_jobs(provider_config, http)
        else:  # pragma: no cover - guarded by callers
            return None
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.info("Probe rejected %s board %r: %s", ats, board_token, exc)
        return None
    return len(jobs)


async def detect_ats(url: str, http: httpx.AsyncClient) -> Optional[Detection]:
    """Detect + confirm the ATS for ``url``. Return a :class:`Detection` or None.

    Order: URL-shape candidate first (cheap, no page fetch); if that misses, the
    HTML-marker fallback (one guarded page fetch). Either way the candidate is
    confirmed by an API probe before returning.
    """
    candidate = _candidate_from_url(url)
    if candidate is None:
        candidate = await _candidate_from_html(url, http)
    if candidate is None:
        return None

    ats, board_token, provider_config = candidate
    company_id = _slugify_token(
        provider_config.get("tenant_slug", board_token)
        if ats == "workday"
        else board_token
    )
    if company_id is None:
        logger.info("Detected %s but token %r is not a valid slug", ats, board_token)
        return None

    job_count = await _probe(ats, board_token, provider_config, http)
    if job_count is None:
        return None

    return Detection(
        ats=ats,
        company_id=company_id,
        display_name=_display_name_from(
            provider_config.get("tenant_slug", board_token)
            if ats == "workday"
            else board_token
        ),
        board_token=board_token,
        provider_config=provider_config,
        job_count=job_count,
    )
