"""Companies router: the public directory read, plus the ATS resolve probe.

``GET ""`` is read-only, no auth, no query params: every enabled company with
its directory content (blurb + accomplishment), alphabetically by display name.
The frontend does search / alphabetical sort / infinite-scroll reveal
client-side over this single payload (~130 short rows), mirroring the
``/api/features`` + Changelog design.

``POST /resolve`` takes a careers-page URL a signed-in user pasted and answers
"is there an ATS board behind this, and does it actually have jobs?". It
**persists nothing** — no ``companies`` row, no audit row (that arrives with
PR 3's ``company_add_attempts``). Rollback for the whole custom-sources feature
is leaving ``custom_company_sources_enabled`` off, which 503s this route, or
deleting it outright.
"""

import asyncio
import logging
import time

import httpx
import psycopg2
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from psycopg2.extensions import connection as Connection

from ..auth.claims import TokenClaims
from ..auth.dependencies import get_current_user
from ..auth.jwt import get_normalized_subject
from ..config import settings
from ..dependencies import get_db
from ..models import (
    AtsCandidateResponse,
    CompanyListResponse,
    CompanyProfileResponse,
    NameCandidateResponse,
    ProbeResultResponse,
    ResolveUrlRequest,
    ResolveUrlResponse,
    SearchCompanyRequest,
    SearchCompanyResponse,
)
from ..services.ats_discovery import (
    DiscoveryResult,
    ProbeResult,
    discover_ats,
    probe_candidate,
)
from ..services.company_name_search import (
    NameCandidate,
    NameSearchUnavailable,
    search_ats_candidates,
)
from ..services.companies_service import list_enabled_companies_with_profiles
from ..services.rate_limit import enforce_resolve_rate_limit
from ..services.url_guard import REASON_DEADLINE, UrlGuardError, normalize_public_url

logger = logging.getLogger(__name__)

router = APIRouter()

# The client's default timeout. It is NOT a backstop on a resolve call and must
# not be described as one: ``ats_discovery`` passes an explicit ``timeout=`` on
# every outbound request, and an explicit per-request timeout *overrides* the
# client default rather than being capped by it (demonstrated: client
# ``timeout=0.05`` plus a per-call ``5.0`` let a 0.4 s request succeed). It only
# governs requests that do not set their own.
_RESOLVE_CLIENT_TIMEOUT_S = 30.0

# The actual aggregate bound, and the reason one is needed. Worst case without it
# is ~36 outbound requests for a single call (L1 HEAD chain + GET retry, then 4
# sniff targets, each up to _MAX_REDIRECT_HOPS hops) at _DISCOVERY_TIMEOUT_S
# each — minutes, at a third-party host, with Vercel 504-ing the user long before
# the backend stopped working. The monotonic deadline is threaded into every
# ``guarded_get`` so the burst *stops*; the ``asyncio.wait_for`` below is the hard
# backstop for anything not covered by it (DNS in a worker thread, JSON parsing).
_RESOLVE_BUDGET_S = 25.0

# Slack between the threaded deadline and the outer cancel, so the normal path
# ends as a clean ``deadline_exceeded`` from the guard rather than a cancellation.
_RESOLVE_GRACE_S = 2.0


async def _discover_and_probe(
    url: str,
    http: httpx.AsyncClient,
    deadline: float,
) -> tuple[DiscoveryResult, ProbeResult | None]:
    """Discovery plus, on a hit, the probe — one awaitable so one bound covers both.

    ``ProbeResult`` is ``None`` exactly when discovery found no candidate.
    """
    result = await discover_ats(url, http, deadline=deadline)
    if result.candidate is None:
        return result, None
    return result, await probe_candidate(result.candidate, http, deadline=deadline)


def _http_client() -> httpx.AsyncClient:
    """The client discovery + probe share for one request.

    A module-level factory rather than an inline constructor so tests can swap
    in an ``httpx.MockTransport`` without monkeypatching httpx itself.
    ``follow_redirects=False`` is load-bearing: every redirect in the discovery
    path is followed manually by ``url_guard.guarded_get`` so each hop can be
    revalidated before its request goes out.
    """
    return httpx.AsyncClient(
        follow_redirects=False, timeout=_RESOLVE_CLIENT_TIMEOUT_S
    )


@router.get("", response_model=CompanyListResponse)
def list_companies(conn: Connection = Depends(get_db)) -> CompanyListResponse:
    try:
        rows = list_enabled_companies_with_profiles(conn)
    except psycopg2.Error:
        # Roll back so the pooled connection isn't returned in an aborted-
        # transaction state — the next get_db caller would otherwise hit
        # "current transaction is aborted" on their first statement.
        conn.rollback()
        logger.exception("Failed to list companies")
        raise HTTPException(status_code=500, detail="Failed to list companies")
    return CompanyListResponse(
        companies=[
            CompanyProfileResponse(
                id=r["id"],
                display_name=r["display_name"],
                ats=r["ats"],
                blurb=r["blurb"],
                accomplishment=r["accomplishment"],
            )
            for r in rows
        ]
    )


def _normalized_or_raw(url: str) -> str:
    """The guard's spelling of ``url``, or the input when it has none.

    Used on the paths that have no discovery result to report a ``finalUrl``
    from. Every other 422 returns a URL that has been through
    ``validate_public_url``; echoing the raw request body back on the timeout
    path alone was both inconsistent and a reflection of unvalidated input.
    ``normalize_public_url`` performs no IO, so this is safe to call after the
    budget has already been exhausted.
    """
    try:
        normalized, _ = normalize_public_url(url)
    except UrlGuardError:
        return url
    return normalized


@router.post("/resolve", response_model=ResolveUrlResponse)
async def resolve_company_url(
    payload: ResolveUrlRequest,
    user: TokenClaims = Depends(get_current_user),
) -> ResolveUrlResponse | JSONResponse:
    """Resolve a pasted careers URL to an ATS candidate and probe it.

    Writes nothing. Returns 503 when the feature flag is off, 401 without a
    Bearer token (via ``get_current_user``), 429 when one user resolves faster
    than the rate limit allows, and 422 with a stable, machine-readable
    ``reason`` when no board could be found or the URL was rejected by the SSRF
    guard. The 422 body is flat (``reason`` / ``finalUrl`` / ``hops``) rather
    than nested under ``detail`` because the frontend and PR 3's audit log both
    key off ``reason``.
    """
    if not settings.custom_company_sources_enabled:
        raise HTTPException(
            status_code=503, detail="Custom company sources are not enabled"
        )

    # Before any outbound work. One call is up to ~36 third-party requests and
    # holds a slot in url_guard's 4-thread DNS pool for as long as the remote
    # resolver stalls, so "authenticated" is not on its own a sufficient bound.
    enforce_resolve_rate_limit(get_normalized_subject(user) or "unknown")

    deadline = time.monotonic() + _RESOLVE_BUDGET_S
    async with _http_client() as http:
        try:
            result, probe = await asyncio.wait_for(
                _discover_and_probe(payload.url, http, deadline),
                timeout=_RESOLVE_BUDGET_S + _RESOLVE_GRACE_S,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Resolve budget of %.0fs exhausted for %r",
                _RESOLVE_BUDGET_S, payload.url,
            )
            return JSONResponse(
                status_code=422,
                content={
                    "reason": REASON_DEADLINE,
                    "finalUrl": _normalized_or_raw(payload.url),
                    "hops": [],
                },
            )

    if result.candidate is None or probe is None:
        logger.info(
            "Resolve miss for %r: reason=%s via=%s hops=%d",
            payload.url, result.reason, result.via, len(result.hops),
        )
        return JSONResponse(
            status_code=422,
            content={
                "reason": result.reason or "no_ats_detected",
                "finalUrl": result.final_url,
                "hops": list(result.hops),
            },
        )

    # ``runners_up`` is why a wrong embedded resolution is diagnosable at all:
    # "we picked Workday/cisco but the page also named Greenhouse/acme" is the
    # whole diagnosis. It is populated by the L2 ranker and this is the only place
    # it is recorded, so it belongs in the log line rather than being dropped.
    logger.info(
        "Resolve hit for %r: ats=%s token=%s via=%s probe_ok=%s jobs=%d "
        "runners_up=%s",
        payload.url, result.candidate.ats, result.candidate.board_token,
        result.via, probe.ok, probe.job_count,
        [f"{c.ats}/{c.board_token}" for c in result.runners_up] or None,
    )
    return ResolveUrlResponse(
        candidate=AtsCandidateResponse(
            ats=result.candidate.ats,
            board_token=result.candidate.board_token,
            provider_config=result.candidate.provider_config,
            source_url=result.candidate.source_url,
        ),
        probe=ProbeResultResponse(
            ok=probe.ok, job_count=probe.job_count, error=probe.error
        ),
        via=result.via,
        hops=list(result.hops),
        final_url=result.final_url,
    )


# Probing every candidate a search returns would multiply one user action into up
# to 25 outbound ATS calls. Only the few we are going to SHOW get probed, and the
# job count is most of what makes a wrong board obvious to a human, so it is worth
# exactly this much and no more.
_MAX_SHOWN_CANDIDATES = 5

# The whole name path, end to end, inside one user request. Deliberately tighter
# than the resolve budget: rung A is a single fast search call plus a handful of
# probes, and if that is slow the honest answer is "type a URL", not a longer wait.
_SEARCH_BUDGET_S = 20.0


async def _probe_shown(
    candidates: list[NameCandidate], http: httpx.AsyncClient, deadline: float
) -> list[NameCandidateResponse]:
    """Probe the handful of candidates we intend to show, concurrently.

    A probe that fails is kept, not dropped: "Guidehouse · board unreachable" is
    still the information that tells a user this is not their company. Only the
    ``ok``/``job_count`` fields change.
    """
    shown = candidates[:_MAX_SHOWN_CANDIDATES]
    probes = await asyncio.gather(
        *(probe_candidate(c.candidate, http, deadline=deadline) for c in shown),
        return_exceptions=True,
    )
    out: list[NameCandidateResponse] = []
    # `strict=True` states the invariant `asyncio.gather` already guarantees —
    # one result per input, in order. If that ever stops holding, a silent
    # truncation would pair a candidate with another candidate's job count,
    # which is the one number the user is being asked to judge.
    for found, probe in zip(shown, probes, strict=True):
        if isinstance(probe, BaseException):
            logger.warning(
                "Probe of %s/%s raised during name search",
                found.candidate.ats, found.candidate.board_token, exc_info=probe,
            )
            probe = ProbeResult(ok=False, job_count=0, error="probe failed")
        out.append(
            NameCandidateResponse(
                candidate=AtsCandidateResponse(
                    ats=found.candidate.ats,
                    board_token=found.candidate.board_token,
                    provider_config=found.candidate.provider_config,
                    source_url=found.candidate.source_url,
                ),
                probe=ProbeResultResponse(
                    ok=probe.ok, job_count=probe.job_count, error=probe.error
                ),
                source_url=found.source_url,
                title=found.title,
                rank=found.rank,
                # A board that resolves but has NO jobs is never something to add
                # silently, however well its token matches — an empty board is the
                # cheapest signal we have that we picked the wrong one.
                auto_addable=found.auto_addable and probe.ok and probe.job_count > 0,
            )
        )
    return out


@router.post("/search-by-name", response_model=SearchCompanyResponse)
async def search_company_by_name(
    payload: SearchCompanyRequest,
    user: TokenClaims = Depends(get_current_user),
) -> SearchCompanyResponse:
    """Find ATS boards for a typed company name. Writes nothing.

    One Browserbase Search call, then every result scored by the free pure
    ``resolve_ats_url``. This route exists ONLY for names — a pasted URL still
    goes to ``/resolve`` and enters at L0, which is exact, free and instant.

    503 (not an empty 200) when the flag is off or search is unavailable, because
    "we could not look" and "we looked and there is no board" must never reach a
    user as the same sentence. The second one is an empty ``candidates`` list.
    """
    if not settings.custom_company_sources_enabled:
        raise HTTPException(
            status_code=503, detail="Custom company sources are not enabled"
        )
    if not settings.company_name_search_enabled:
        raise HTTPException(
            status_code=503, detail="Company name search is not enabled"
        )

    # Same limiter as /resolve: one call is a paid third-party search plus up to
    # five outbound ATS probes, so it needs a bound that is not just "logged in".
    enforce_resolve_rate_limit(get_normalized_subject(user) or "unknown")

    deadline = time.monotonic() + _SEARCH_BUDGET_S
    async with _http_client() as http:
        try:
            candidates, careers_urls = await search_ats_candidates(payload.name, http)
        except NameSearchUnavailable as exc:
            logger.warning("Name search unavailable for %r: %s", payload.name, exc)
            raise HTTPException(
                status_code=503, detail="Company search is temporarily unavailable"
            ) from exc

        shown = await _probe_shown(candidates, http, deadline)

    logger.info(
        "Name search for %r: %d candidate(s), %d shown, %d auto-addable",
        payload.name, len(candidates), len(shown),
        sum(1 for c in shown if c.auto_addable),
    )
    return SearchCompanyResponse(
        query=payload.name,
        candidates=shown,
        careers_url=careers_urls[0] if careers_urls else None,
    )
