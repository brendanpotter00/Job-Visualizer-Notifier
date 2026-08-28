"""Private custom-company endpoints — ``/api/users/companies`` (E7 Phase 1).

Mounted UNDER ``/api/users`` so the existing ``api/users.ts`` Vercel proxy (which
forwards the Authorization header) reaches these without a new proxy. Every
route requires a Bearer token (``get_current_user``) and is gated by the
``custom_company_sources_enabled`` flag — 503 when off, so the whole feature
ships dark and rolls back by flipping the flag.

The load-bearing invariant: ``visibility='user'`` jobs are served ONLY by
``GET /api/users/companies/{id}/jobs``, which 403s any caller that does not own
the company. The public ``/api/jobs`` never serves them.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from urllib.parse import urlparse

import httpx
import psycopg2
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from fastapi.responses import JSONResponse
from psycopg2.extensions import connection as Connection

from scripts.shared.constants import custom

from ..auth.claims import TokenClaims
from ..auth.dependencies import get_current_user
from ..auth.jwt import get_normalized_subject
from ..config import settings
from ..dependencies import get_db
from ..models import (
    AddUserCompanyRequest,
    AlreadyPublicResponse,
    DiscoveryProgressResponse,
    JobListingResponse,
    PublicMatchResponse,
    UserCompanyListResponse,
    UserCompanyResponse,
)
from ..pagination import (
    MAX_CURSOR_LENGTH,
    MAX_TIMESTAMP_LENGTH,
    InvalidCursorError,
    JobCursor,
    decode_job_cursor,
    encode_job_cursor,
    parse_utc_timestamp,
)
# Imported, NOT redeclared: ``main.py`` wires exactly this constant into
# ``CORSMiddleware(expose_headers=...)``. A second copy of the string here would
# let the two drift and the header would silently stop reaching the browser.
from ..routers.jobs import NEXT_CURSOR_HEADER
from ..services import custom_companies_service as svc
from ..services.ats_discovery import discover_ats, probe_candidate
from ..services.discovery.progress import read_progress
from ..services.published_board_match import read_suggestion
from ..services.database import get_owned_custom_jobs, get_user_company_jobs
from ..services.user_service import get_or_create_user, get_user_by_email

logger = logging.getLogger(__name__)

router = APIRouter()

# Same aggregate outbound budget the resolve endpoint uses: one add can fan out
# to ~36 third-party requests (discovery ladder) plus a probe, so the monotonic
# deadline is threaded into every guarded hop and the outer wait_for is the
# backstop for anything the deadline doesn't cover.
_RESOLVE_BUDGET_S = 25.0
_RESOLVE_GRACE_S = 2.0
_RESOLVE_CLIENT_TIMEOUT_S = 30.0

# Wall-clock cap on the first-harvest ENQUEUE (not the harvest — that runs on the
# worker). It is two local statements, an INSERT on the broker and an UPDATE on
# ``companies``, so this bound is never reached in practice; it exists because the user
# is synchronously waiting on this response and a sick broker connection must cost them
# a bounded pause and today's 15-minute-tick behaviour, not an open-ended hang.
_FIRST_HARVEST_ENQUEUE_BUDGET_S = 5.0


def _http_client() -> httpx.AsyncClient:
    """The client discovery + probe share for one add. Module-level so tests can
    swap in an ``httpx.MockTransport`` without monkeypatching httpx itself.
    ``follow_redirects=False`` — the discovery path follows every redirect
    manually so each hop is re-validated by ``url_guard`` before its request."""
    return httpx.AsyncClient(
        follow_redirects=False, timeout=_RESOLVE_CLIENT_TIMEOUT_S
    )


def _require_flag() -> None:
    if not settings.custom_company_sources_enabled:
        raise HTTPException(
            status_code=503, detail="Custom company sources are not enabled"
        )


def _to_response(row: dict) -> UserCompanyResponse:
    # The discovery checklist rides on the SAME row the list already returns, so the
    # existing 'still settling' poll surfaces it with no second channel (DECISION D2).
    # ``read_progress`` is total: an ATS company's provider_config has no 'discovery'
    # key and yields None, and a blob written by an older deployment is trimmed rather
    # than raised on — this is the one endpoint the My-Companies page cannot live
    # without, so it must never 500 over a display-only field.
    progress = read_progress(row.get("provider_config"))
    # Same column, same poll, same total-reader contract (E7 unit 10): a row with no
    # suggestion — every ATS company, and nearly every discovered one — yields None and
    # renders exactly what it rendered before this shipped.
    public_match = read_suggestion(row.get("provider_config"))
    return UserCompanyResponse(
        id=row["id"],
        display_name=row["display_name"],
        ats=row["ats"],
        board_token=row["board_token"],
        source_id=row.get("source_id") or custom(row["id"]),
        health_state=row.get("health_state"),
        open_job_count=int(row.get("open_job_count") or 0),
        last_success_at=row.get("last_success_at"),
        tracking_started_at=row.get("tracking_started_at"),
        discovery=(
            DiscoveryProgressResponse.model_validate(progress)
            if progress is not None
            else None
        ),
        public_match=(
            PublicMatchResponse.model_validate(public_match)
            if public_match is not None
            else None
        ),
    )


def _reject(status: int, reason: str, detail: str, final_url: str | None = None) -> JSONResponse:
    body: dict[str, object] = {"reason": reason, "detail": detail}
    if final_url is not None:
        body["finalUrl"] = final_url
    return JSONResponse(status_code=status, content=body)


# Hosts that carry no company identity — the label has to come from the label BEFORE
# these, or a board on `jobs.acme.co.uk` would be named "Co".
_HOST_NOISE_PREFIXES = ("www", "jobs", "careers", "boards", "apply", "talent", "life")
# Second-level labels that are part of the suffix, not the name (`acme.co.uk`).
_HOST_SUFFIX_LABELS = ("co", "com", "net", "org", "ac", "gov", "edu")


def _discovery_display_name(final_url: str) -> str:
    """A human label for a discovered company, derived from its final URL's host.

    The host is what we have — a discovered board has no name field to read. But the
    RAW host is what the user then sees on every job card and in their companies list,
    and `www.janestreet.com` reads like a URL someone forgot to clean up rather than a
    company. So we take the registrable label and title-case it: `Jane Street`.

    Deliberately conservative about WHICH label: stripping only a leading `www.` names
    `jobs.acme.com` as "Jobs". We drop every leading noise label, then walk back from
    the TLD past compound suffixes (`.co.uk`) so `careers.acme.co.uk` is "Acme", not
    "Co". A host that is nothing but noise (or an IP, or empty) falls back to the raw
    host — a slightly ugly name is much better than a confidently wrong one.

    Hyphens and underscores become spaces so `jane-street.com` reads the same as
    `janestreet.com`. We do NOT try to split a run-together label into words: there is
    no reliable way to tell `janestreet` from `mongodb`, and "Mongo Db" is worse than
    "Janestreet". The user can rename it; we just must not invent.
    """
    host = urlparse(final_url).netloc.split("@")[-1].split(":")[0].strip().lower()
    if not host:
        return final_url

    labels = [label for label in host.split(".") if label]
    # An IPv4 literal has no registrable name to find — keep it verbatim.
    if len(labels) < 2 or all(label.isdigit() for label in labels):
        return host

    # Drop the TLD, then any compound-suffix label sitting in front of it.
    labels = labels[:-1]
    if len(labels) > 1 and labels[-1] in _HOST_SUFFIX_LABELS:
        labels = labels[:-1]
    # Then drop leading noise, but never the last label — that IS the name.
    while len(labels) > 1 and labels[0] in _HOST_NOISE_PREFIXES:
        labels = labels[1:]

    name = labels[-1].replace("-", " ").replace("_", " ").strip()
    if not name or name in _HOST_NOISE_PREFIXES:
        return host
    return " ".join(word.capitalize() for word in name.split())


async def _defer_discovery(
    *, user_id: str, submitted_url: str, normalized_url: str, display_name: str
) -> None:
    """Enqueue the one-time ``discover_custom_company`` task on its own queue.

    Module-level + lazily importing the task (which pulls in the discovery
    package) so the router's import graph stays light and tests can monkeypatch this
    seam without opening a live worker. The queueing lock is keyed PER USER
    (``discover:{user_id}:{url}``): a single user's double-submit collapses to one
    run, but two DIFFERENT users adding the SAME non-ATS URL each get their own
    discovery (a URL-only lock made user B's defer raise AlreadyEnqueued → a 500 and
    a wedged ``discovering`` row).

    The lock STRING comes from :func:`svc.discovery_queueing_lock`, not from an
    f-string here, because two other places now have to name the same job: the
    removal path cancels it, and the wedged-row reconciler asks whether it is still
    alive. An f-string that drifted from theirs would silently cancel nothing and
    reap a live run.
    """
    from ..tasks.discover_custom_company import discover_custom_company

    await discover_custom_company.configure(
        queueing_lock=svc.discovery_queueing_lock(user_id, normalized_url),
    ).defer_async(
        user_id=user_id,
        submitted_url=submitted_url,
        normalized_url=normalized_url,
        display_name=display_name,
    )


async def _start_first_harvest(conn: Connection, company_id: str) -> None:
    """Read the freshly-added ATS board NOW instead of at the next claim tick.

    THE BUG THIS FIXES: an ATS add commits a row with ``next_run_at = now()`` and then
    waits for the ``*/15 * * * *`` claim tick, so for up to fifteen minutes the user
    stares at their new company saying "Successfully tracking · 0 open jobs · Not yet
    checked" right under a preview that just told them we found 1,200 jobs on it.
    Discovery already fixed this for discovered boards; this is the same fix for the
    fast path, through the SAME helper — one enqueue path, one queueing lock, one idea
    of what "already scheduled" means.

    THREE PROPERTIES THIS SEAM OWNS, all about the fact that ``POST
    /api/users/companies`` is a request the user is sitting in front of:

    * **It never fails the add.** The company is created and committed before we get
      here. ``start_first_harvest`` already swallows broker and database trouble, so the
      blanket ``except`` is for the genuinely unforeseen (an import error, a connector
      that raises something new); degrading to "the tick runs it within 15 minutes" is
      the old behaviour and always better than a 500 on a company that IS added.
    * **It cannot hang the response.** ``wait_for`` bounds a sick broker to
      ``_FIRST_HARVEST_ENQUEUE_BUDGET_S``. ``CancelledError`` is BaseException and
      deliberately NOT caught — a disconnected client should still unwind.
    * **It is lazy-imported**, like ``_defer_discovery`` above: the task package pulls in
      the worker's import graph, which the request path has no reason to carry, and the
      indirection is also the seam tests patch instead of opening a live broker.
    """
    from ..tasks.claim_custom_companies import start_first_harvest

    try:
        await asyncio.wait_for(
            # transport='ats_client' is the literal transport ``add_custom_company``
            # writes to company_scripts. It matters: the helper skips a
            # ``browser_fetch`` enqueue while discovery is off, and an ATS board must
            # never inherit that gate — discovery had no part in creating it.
            start_first_harvest(
                conn, company_id=company_id, transport="ats_client"
            ),
            timeout=_FIRST_HARVEST_ENQUEUE_BUDGET_S,
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "Could not start the first harvest for %s; the claim tick will pick it up "
            "within 15 minutes", company_id, exc_info=True,
        )


@router.post("", response_model=UserCompanyResponse)
async def add_company(
    payload: AddUserCompanyRequest,
    response: Response,
    conn: Connection = Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
) -> UserCompanyResponse | JSONResponse:
    """Resolve a pasted careers URL, probe it, and create a private company.

    Requires ``job_count > 0``. Idempotent per ``UNIQUE(user_id,
    canonical_source_key)`` — re-adding the same board returns the existing
    company (200) instead of erroring. A non-ATS / unresolvable URL writes a
    ``company_add_attempts`` row with ``outcome='unsupported'`` and returns 422
    (Phase 3 will handle these); a resolvable board that probes 0 jobs or errors
    returns 422 with ``outcome='empty'`` / ``'probe_failed'``.

    A URL that is a company we ALREADY PUBLISH creates nothing and returns 200 with
    an ``AlreadyPublicResponse`` (``outcome='already_public'``) naming that public
    company. THREE checks answer that, in ascending order of cost and descending
    order of certainty, because a published company can be recognised three ways:

    * the ``(ats, board_token)`` the resolver named — the six ATS providers;
    * the careers HOST, for the five ``ats='script'`` boards (Amazon, Apple,
      Google, Microsoft, TikTok) that no URL can ever spell as an ATS pair; and
    * the company NAME inside the registrable domain — ``lifeatspotify.com``.

    The first two are exact and terminal: they answer ``match_kind='board'`` and
    the UI offers no way past them, because a resolved board token and a declared
    host leave no reading where the user meant somebody else. The third is a guess
    (``match_kind='name'``) and keeps a way out, because its failure mode is a false
    positive and a guess with no way out would block a legitimate different company.

    See each block for what it does and does not catch. ``trackAnyway: true`` on the
    request skips all three and adds the private copy anyway — still honoured on
    every rung, so a replayed request or an old client never 500s.
    """
    _require_flag()

    auth0_id = get_normalized_subject(user)
    email = user.get("email")
    if not auth0_id:
        raise HTTPException(status_code=401, detail="Token missing required 'sub' claim")
    if not email:
        raise HTTPException(status_code=401, detail="Token missing required 'email' claim")
    try:
        user_row = get_or_create_user(
            conn,
            auth0_id=auth0_id,
            email=email,
            given_name=user.get("given_name"),
            family_name=user.get("family_name"),
            picture_url=user.get("picture"),
        )
    except psycopg2.Error:
        logger.exception("Failed to get/create user for custom-company add")
        raise HTTPException(status_code=500, detail="Failed to load user profile")
    user_id = user_row["id"]

    deadline = time.monotonic() + _RESOLVE_BUDGET_S
    async with _http_client() as http:
        try:
            result = await asyncio.wait_for(
                discover_ats(payload.url, http, deadline=deadline),
                timeout=_RESOLVE_BUDGET_S + _RESOLVE_GRACE_S,
            )
        except asyncio.TimeoutError:
            svc.record_add_attempt(
                conn, user_id=user_id, submitted_url=payload.url,
                normalized_url=None, outcome="unsupported",
                error_detail="deadline_exceeded",
            )
            return _reject(422, "deadline_exceeded", "Resolving the URL timed out.")

        if result.candidate is None:
            # Whether the caller ALREADY owns a private row for this URL. Hoisted out
            # of the discovery gate below because BOTH no-candidate dedupe rungs (the
            # careers-host match and the company-name match) need the same answer, for
            # the same reason unit 9's dedupe sits after its own idempotent branch:
            # somebody who once sent ``trackAnyway`` — today via the name match's "This
            # isn't the same company" correction — owns a real private row, and a re-add
            # of that URL has to keep resolving to THEIR row rather than being sent back
            # to the public page.
            owned = (
                svc.find_owned_company_by_source_key(
                    conn, user_id, svc.discovered_source_key(result.final_url)
                )
                if result.final_url
                else None
            )

            # ── The careers-host match: the ats='script' half of the dedupe ──────
            # Amazon, Apple, Google, Microsoft and TikTok are published to everybody
            # with ``ats='script'`` — a sentinel the ATS resolver never emits and no
            # URL ever spells — so unit 9's ``(ats, board_token)`` check above cannot
            # see them and their careers URLs land HERE, one line from spending a
            # Claude call and a headless Chromium session on a private duplicate of a
            # board we have published for years. That is the bug the owner hit with
            # ``jobs.careers.microsoft.com`` and ``www.amazon.jobs``.
            #
            # BEFORE the discovery gate, not inside it, and before the placeholder
            # insert: on a hit we create NOTHING and enqueue NOTHING. It is also
            # before the gate because the answer does not depend on it — "we already
            # publish this board" is true and useful whether or not discovery is on,
            # and with the flag off the alternative is a 422 that reads as "this
            # board is unsupported" about a board on our own front page.
            #
            # Both URLs are checked: what the user pasted AND what the resolver's
            # redirect-following settled on. They differ in both directions —
            # ``careers.tiktok.com`` 302s to ``lifeattiktok.com``, and a company page
            # that redirects into one of these boards is only recognisable as the
            # final URL.
            if owned is None and not payload.track_anyway:
                published = svc.find_public_company_for_careers_url(
                    conn, payload.url, result.final_url
                )
                if published is not None:
                    svc.record_add_attempt(
                        conn, user_id=user_id, submitted_url=payload.url,
                        normalized_url=result.final_url, outcome="already_public",
                        # ``script`` is what the public row's ``ats`` actually is, so
                        # the audit says which half of the dedupe answered without a
                        # new outcome value that every existing query would miss.
                        resolved_ats="script", company_id=published["id"],
                    )
                    # 200 and the SAME body shape unit 9 returns, so the frontend
                    # renders the same notice. Nothing failed and there is nothing to
                    # fix — the company they asked for is already there.
                    #
                    # ``match_kind`` defaults to ``'board'``, which is the whole
                    # difference from the rung below: a declared careers host is exact
                    # evidence, so the UI renders this TERMINALLY with no way past it. A
                    # private duplicate of a board we publish re-scrapes the same feed
                    # for a chart whose history starts today, with the full history one
                    # click away in this notice. ``trackAnyway`` is still honoured on the
                    # wire — only the button is gone.
                    return JSONResponse(
                        status_code=200,
                        content=AlreadyPublicResponse(
                            detail=(
                                "That URL is the same job board as our public "
                                f"{published['display_name']} page, so there is nothing "
                                "to set up — its hiring trend is already there."
                            ),
                            company_id=str(published["id"]),
                            display_name=str(published["display_name"]),
                            final_url=result.final_url or payload.url,
                        ).model_dump(by_alias=True),
                    )

                # ── The company-name match: the third rung, and the only GUESS ──
                # ``lifeatspotify.com`` is neither an ATS board nor a declared careers
                # host, so both checks above say nothing about it and it used to spend
                # a headless Chromium session and a Claude call before unit 10's
                # job-title overlap could say "this looks like Spotify". The string
                # ``spotify`` was in the domain the whole time.
                #
                # It sits HERE — after the two exact rungs, before the discovery gate
                # and before the placeholder insert — because that ordering is the
                # entire point of the unit: on a hit we create NOTHING and enqueue
                # NOTHING. Before the gate for the same reason the careers-host match
                # is: "we probably already publish this" is a useful answer whether or
                # not discovery is switched on, and with the flag off the alternative
                # is a 422 that reads as "this board is unsupported".
                #
                # AFTER the two exact rungs, and it must stay after them. Their ``None``
                # answers are deliberate (``learn.microsoft.com`` is not Microsoft's job
                # board), and this rung is not allowed to overrule an exact check — the
                # five companies with a declared host table are excluded from the name
                # index for exactly that reason. See ``company_name_match``.
                #
                # ``match_kind='name'`` is not decoration. It is what lets the frontend
                # word this as a likelihood and keep the escape hatch, while the two
                # rungs above are terminal. A guess with no way out would hard-block
                # somebody from adding a company that merely shares a string with ours.
                published = svc.find_public_company_by_name(
                    conn, payload.url, result.final_url
                )
                if published is not None:
                    svc.record_add_attempt(
                        conn, user_id=user_id, submitted_url=payload.url,
                        normalized_url=result.final_url, outcome="already_public",
                        # A distinct marker rather than the matched company's real ``ats``:
                        # the audit's job here is to say WHICH rung answered, and this is
                        # the only one whose hits are worth reviewing for false positives.
                        resolved_ats="name_guess", company_id=published["id"],
                    )
                    return JSONResponse(
                        status_code=200,
                        content=AlreadyPublicResponse(
                            # Hedged on purpose, and every clause is doing work. "looks
                            # like" because we matched a name, not a board; "we matched
                            # the name in the web address" because a user who is about to
                            # be told they are covered deserves to know what that claim
                            # rests on; and the last sentence exists so the escape hatch
                            # reads as correcting us rather than opting into a duplicate.
                            detail=(
                                f"That web address looks like {published['display_name']}, "
                                "which we already publish — we matched the name in the web "
                                "address, not the board itself. If that's right, its hiring "
                                "trend is already there."
                            ),
                            company_id=str(published["id"]),
                            display_name=str(published["display_name"]),
                            final_url=result.final_url or payload.url,
                            match_kind="name",
                        ).model_dump(by_alias=True),
                    )

            # Non-ATS URL → one-time capture discovery, gated on the SINGLE
            # ``custom_company_discovery_enabled`` flag (the parent flag is already
            # asserted by ``_require_flag``). With it off this stays 422 'unsupported'
            # — no provisional row, no enqueue, no browser, no LLM spend, no
            # discovered-endpoint SSRF surface. It is one flag rather than the retired
            # pair because two gates made "discovery is off" read to the user as "this
            # board is unsupported", with nothing distinguishing the two.
            if settings.custom_company_discovery_enabled and result.final_url:
                normalized_url = result.final_url
                existing = owned
                if existing is not None:
                    # Idempotent re-add of an already-discovered (or refused) board:
                    # resolve to the existing row instead of re-spending on discovery.
                    svc.record_add_attempt(
                        conn, user_id=user_id, submitted_url=payload.url,
                        normalized_url=normalized_url, outcome="discovery_pending",
                        resolved_ats="discovered", company_id=existing["id"],
                    )
                    existing["source_id"] = custom(existing["id"])
                    existing["open_job_count"] = svc.count_open_jobs(
                        conn, existing["id"]
                    )
                    response.status_code = 200
                    return _to_response(existing)

                # Insert a PROVISIONAL 'discovering' companies row so the list shows
                # the board as "Setting up…" immediately (§7 — the fix for the "list
                # stays idle until a hard refresh" bug). This also records the
                # discovery_pending attempt. The discovery task flips it to tracked or
                # refused; nothing is scraped in the meantime (enabled=false).
                try:
                    placeholder = svc.add_discovering_placeholder(
                        conn, user_id=user_id, submitted_url=payload.url,
                        normalized_url=normalized_url,
                        display_name=_discovery_display_name(normalized_url),
                    )
                except (psycopg2.Error, RuntimeError):
                    logger.exception(
                        "Failed to create discovering placeholder for %s", normalized_url
                    )
                    raise HTTPException(
                        status_code=500, detail="Failed to start discovery"
                    )
                try:
                    await _defer_discovery(
                        user_id=user_id,
                        submitted_url=payload.url,
                        normalized_url=normalized_url,
                        display_name=_discovery_display_name(normalized_url),
                    )
                except Exception:
                    logger.exception(
                        "Failed to enqueue discovery for %s", normalized_url
                    )
                    raise HTTPException(
                        status_code=500, detail="Failed to start discovery"
                    )
                # Hand back the placeholder's id. Without it the caller can only find
                # the board it just added by diffing the list, so the "one-time setup"
                # notice could never point at the row now narrating its own progress.
                # Purely additive: ``isDiscoveryPending`` discriminates on ``status``.
                # Hand-cased keys — this is a raw dict, not a Pydantic model, so no
                # ``to_camel`` generator runs over it.
                return JSONResponse(
                    status_code=202,
                    content={
                        "status": "discovery_pending",
                        "detail": (
                            "One-time setup — we're figuring out how to read this "
                            "board; jobs appear after the first scan."
                        ),
                        "finalUrl": normalized_url,
                        "id": placeholder["id"],
                        "sourceId": placeholder.get("source_id")
                        or custom(placeholder["id"]),
                    },
                )

            svc.record_add_attempt(
                conn, user_id=user_id, submitted_url=payload.url,
                normalized_url=result.final_url, outcome="unsupported",
                error_detail=result.reason or "no_ats_detected",
            )
            return _reject(
                422, result.reason or "no_ats_detected",
                "No supported ATS board was found behind this URL.",
                final_url=result.final_url,
            )

        candidate = result.candidate
        source_key = svc.canonical_source_key(candidate.ats, candidate.board_token)

        # Idempotent re-add: resolve to the caller's existing company, skip the
        # probe + create, but still record the attempt for the audit trail.
        existing = svc.find_owned_company_by_source_key(conn, user_id, source_key)
        if existing is not None:
            svc.record_add_attempt(
                conn, user_id=user_id, submitted_url=payload.url,
                normalized_url=result.final_url, outcome="added",
                resolved_ats=candidate.ats, board_token=candidate.board_token,
                company_id=existing["id"],
            )
            existing["source_id"] = custom(existing["id"])
            existing["open_job_count"] = svc.count_open_jobs(conn, existing["id"])
            response.status_code = 200
            return _to_response(existing)

        # ── The P2 dedupe: a board we ALREADY PUBLISH is not a board to copy ──
        # One SELECT against the ~130 public rows. On a hit we create NOTHING and
        # hand back the public company to link to; the audit still gets its row.
        #
        # AFTER the idempotent branch above on purpose. Someone who used
        # ``trackAnyway`` once owns a real private row, and a re-add of that URL has
        # to keep resolving to THEIR row — otherwise the endpoint stops being
        # idempotent for exactly the users who opted in.
        #
        # BEFORE the probe, so a board we are not going to add costs no outbound
        # request.
        #
        # THE HONEST LIMIT, because the copy must not overstate it: this catches a
        # pasted Greenhouse / Ashby / Lever / Gem / Workday / Eightfold URL — the
        # thing the resolver can name. The five ``ats='script'`` boards (Amazon,
        # Apple, Google, Microsoft, TikTok) are caught by the careers-host match on
        # the no-candidate path above, which keys on the host instead.
        #
        # A company's own careers site fronting a board we publish is caught by
        # neither: ``lifeatspotify.com`` resolves to no ATS at all (52 KB of its HTML
        # names none of the hosts the sniffer knows) and is not a declared careers
        # host. That is the third rung's case — the company-name match on the
        # no-candidate path above, which reads ``spotify`` out of the domain. What
        # remains uncaught after all three is a careers site whose domain does not
        # name the company at all; only the job SET links those, which is what
        # ``published_board_match`` (unit 10) suggests after the first harvest.
        if not payload.track_anyway:
            published = svc.find_public_company_for_candidate(
                conn,
                ats=candidate.ats,
                board_token=candidate.board_token,
                provider_config=dict(candidate.provider_config),
            )
            if published is not None:
                svc.record_add_attempt(
                    conn, user_id=user_id, submitted_url=payload.url,
                    normalized_url=result.final_url, outcome="already_public",
                    resolved_ats=candidate.ats, board_token=candidate.board_token,
                    # The PUBLIC company's id. The column records what the attempt
                    # resolved to, and that is what it resolved to.
                    company_id=published["id"],
                )
                # 200, not a 4xx. Nothing failed and there is nothing for the user
                # to fix — they asked for a company and it is already there. A
                # rejection status would render this as an alarm, which is the one
                # thing this answer is not.
                return JSONResponse(
                    status_code=200,
                    content=AlreadyPublicResponse(
                        detail=(
                            "That URL is the same job board as our public "
                            f"{published['display_name']} page, so there is nothing "
                            "to set up — its hiring trend is already there."
                        ),
                        company_id=str(published["id"]),
                        display_name=str(published["display_name"]),
                        final_url=result.final_url or payload.url,
                    ).model_dump(by_alias=True),
                )

        # New board — probe it. probe_candidate never raises; a failure is data.
        probe = await probe_candidate(candidate, http, deadline=deadline)

    if not probe.ok:
        svc.record_add_attempt(
            conn, user_id=user_id, submitted_url=payload.url,
            normalized_url=result.final_url, outcome="probe_failed",
            error_detail=probe.error, resolved_ats=candidate.ats,
            board_token=candidate.board_token,
        )
        return _reject(422, "probe_failed", probe.error or "The board could not be probed.")

    if probe.job_count <= 0:
        svc.record_add_attempt(
            conn, user_id=user_id, submitted_url=payload.url,
            normalized_url=result.final_url, outcome="empty",
            error_detail="board resolved but has 0 open jobs",
            resolved_ats=candidate.ats, board_token=candidate.board_token,
        )
        return _reject(422, "empty", "This board resolved but currently has no open jobs.")

    try:
        created = svc.add_custom_company(
            conn,
            user_id=user_id,
            ats=candidate.ats,
            board_token=candidate.board_token,
            provider_config=dict(candidate.provider_config),
            display_name=candidate.board_token,
            submitted_url=payload.url,
            normalized_url=result.final_url,
        )
    except psycopg2.Error:
        logger.exception("Failed to create custom company for user=%s", user_id)
        raise HTTPException(status_code=500, detail="Failed to add company")

    # ONLY on a row this call actually inserted. A re-add returns 200 from the
    # idempotent branch far above and never reaches here; the one path that does is
    # ``add_custom_company``'s UNIQUE race backstop, where a concurrent add created the
    # company — and started its harvest — microseconds ago. Harvesting on every add of
    # an existing board would turn this endpoint into a manual scrape button.
    if created.get("created"):
        await _start_first_harvest(conn, str(created["id"]))

    response.status_code = 201
    return _to_response(created)


@router.get("", response_model=UserCompanyListResponse)
async def list_companies(
    conn: Connection = Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
) -> UserCompanyListResponse:
    """The caller's private companies with health, open-job count, last success."""
    _require_flag()
    email = user.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Token missing required 'email' claim")
    row = get_user_by_email(conn, email)
    if row is None:
        return UserCompanyListResponse(companies=[])
    try:
        companies = svc.list_owned_companies(conn, row["id"])
    except psycopg2.Error:
        conn.rollback()
        logger.exception("Failed to list custom companies for user=%s", row["id"])
        raise HTTPException(status_code=500, detail="Failed to load companies")
    return UserCompanyListResponse(companies=[_to_response(c) for c in companies])


@router.get("/jobs", response_model=list[JobListingResponse])
async def get_all_owned_jobs(
    response: Response,
    conn: Connection = Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
    status: str | None = Query(default=None, pattern=r"^(OPEN|CLOSED)$"),
    limit: int = Query(default=1000, ge=1, le=5000),
    since: str | None = Query(
        default=None,
        max_length=MAX_TIMESTAMP_LENGTH,
        description=(
            "Recency lower bound, INCLUSIVE — same contract as `GET /api/jobs`. "
            "Presence switches this endpoint into keyset-paging mode."
        ),
    ),
    cursor: str | None = Query(
        default=None,
        max_length=MAX_CURSOR_LENGTH,
        description="Opaque token echoed back from a previous `X-Next-Cursor`.",
    ),
) -> list[JobListingResponse]:
    """The caller's OWN custom-company jobs, across every board they own.

    This is what puts a user's private boards on the Recent Jobs feed. The public
    ``GET /api/jobs`` still excludes ``visibility='user'`` UNCONDITIONALLY — that
    guard is not relaxed and must not be, because a viewer-scoped version of it
    would turn an unconditional leak into a conditional one. Instead the feed
    makes a SECOND, authenticated request here and merges the two pages; an
    anonymous caller cannot make this request at all (401), and a signed-in
    non-owner gets only their own boards because the company set is derived from
    ``user_companies``, never from the request.

    Declared BEFORE the ``/{company_id}`` routes: FastAPI matches in declaration
    order, and a future ``GET /{company_id}`` would otherwise swallow ``/jobs``
    and answer this with a 404-shaped "company not found".

    Same ``since``/``cursor``/``X-Next-Cursor`` contract as ``GET /api/jobs`` so
    the frontend's existing keyset walk drives both halves of the feed with one
    implementation. ``limit`` is capped lower (5000) than the public endpoint's
    50000: one user's private boards are a handful, not the whole corpus.
    """
    _require_flag()
    email = user.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Token missing required 'email' claim")

    parsed_cursor: JobCursor | None = None
    if cursor is not None:
        try:
            parsed_cursor = decode_job_cursor(cursor)
        except InvalidCursorError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid 'cursor': {exc}")
    parsed_since: datetime | None = None
    if since is not None:
        try:
            parsed_since = parse_utc_timestamp(since, field="'since'")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid 'since': {exc}")

    row = get_user_by_email(conn, email)
    if row is None:
        # Signed in but no users row yet — they cannot own anything. Empty, not an
        # error: the feed always issues this request, and a 404 here would make
        # every brand-new user's Recent page render an error banner.
        return []
    source_ids = svc.list_owned_source_ids(conn, row["id"])
    jobs = get_owned_custom_jobs(
        conn, source_ids, status=status, since=parsed_since,
        cursor=parsed_cursor, limit=limit,
    )

    # Mint the next token only in keyset mode off a FULL page — byte-identical
    # rule to ``GET /api/jobs``. Its ABSENCE is the only end-of-walk signal, so a
    # short page must not carry one.
    if (parsed_since is not None or parsed_cursor is not None) and len(jobs) == limit:
        tail = jobs[-1]
        response.headers[NEXT_CURSOR_HEADER] = encode_job_cursor(
            tail["first_seen_at"], tail["source_id"], tail["id"]
        )
    return [JobListingResponse(**job) for job in jobs]


@router.delete("/{company_id}", status_code=204)
async def delete_company(
    company_id: str = Path(max_length=64),
    conn: Connection = Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
) -> Response:
    """Remove the caller's ownership and, if that was the last owner, PURGE the
    company: its ``companies`` row, its ``company_scripts`` recipe, every job in
    its ``custom:<id>`` namespace (plus the freshness/location/tag/enrichment rows
    hanging off them), its harvests and its scrape runs — one transaction. Only
    the append-only ``company_add_attempts`` audit survives. "Remove" means gone,
    not hidden: a disabled-but-present row was invisible to the user and
    unreachable by a re-add, so it could only ever accumulate."""
    _require_flag()
    email = user.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Token missing required 'email' claim")
    row = get_user_by_email(conn, email)
    if row is None:
        raise HTTPException(status_code=404, detail="Company not found")
    try:
        outcome = svc.remove_owned_company(conn, row["id"], company_id)
    except psycopg2.Error:
        logger.exception("Failed to delete custom company %s for user=%s", company_id, row["id"])
        raise HTTPException(status_code=500, detail="Failed to remove company")
    if outcome == "not_owner":
        raise HTTPException(status_code=404, detail="Company not found")
    return Response(status_code=204)


@router.get("/{company_id}/jobs", response_model=list[JobListingResponse])
async def get_company_jobs(
    company_id: str = Path(max_length=64),
    conn: Connection = Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
) -> list[JobListingResponse]:
    """Owner-scoped jobs for a private company. 403 if the caller is not an owner.

    This is the ONLY path that serves ``visibility='user'`` jobs.
    """
    _require_flag()
    email = user.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Token missing required 'email' claim")
    row = get_user_by_email(conn, email)
    if row is None:
        raise HTTPException(status_code=403, detail="Not an owner of this company")
    if svc.get_company_if_owner(conn, row["id"], company_id) is None:
        raise HTTPException(status_code=403, detail="Not an owner of this company")
    jobs = get_user_company_jobs(conn, company_id, custom(company_id))
    return [JobListingResponse(**job) for job in jobs]
