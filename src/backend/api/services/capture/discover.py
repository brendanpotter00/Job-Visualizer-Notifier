"""DISCOVERY ORCHESTRATOR — capture the board's API ONCE, prove it replays, then store.

This is the engine that replaced the Stagehand DOM agent. The pivot in one sentence:
instead of paying an LLM to re-read a rendered careers page every 24 hours, we open the
page in a browser **once**, record its network traffic, have Haiku pick the jobs request
and map its fields **once**, synthesize a deterministic recipe, and — the part that
makes it safe — **prove that recipe replays from our production environment before we
promise to track anything**. Runtime never calls an LLM again.

The seven steps, in order, each named because the REFUSE reason is rendered to the user
("we found the feed, but couldn't confirm the results match"):

1. :data:`_STEP_ENTRY` — SSRF-validate the pasted URL (invariant #4, entry half).
2. :data:`_STEP_CAPTURE` — one browser session; record every JSON XHR/fetch.
3. :data:`_STEP_FILTER` — deterministic pre-filter to job-shaped arrays, then
   SSRF-validate every surviving endpoint (invariant #4, discovered-endpoint half).
4. :data:`_STEP_SELECT` — ONE Haiku call: which request, and how its fields map.
5. :data:`_STEP_SYNTHESIZE` — assemble a recipe and run it through
   ``recipe_schema.validate_recipe`` (validate-on-write, invariant #5).
6. :data:`_STEP_ACCEPT` — replay it FROM THE PRODUCTION PATH and check it against the
   capture.
7. accept (store) or **REFUSE** (store nothing).

**The acceptance gate is the whole point** (plan DECISION D5). Tier 1a (``http_json``
through ``guarded_sync_client`` + ``run_recipe``) is tried first because it costs $0 a
night; tier 1b (``browser_fetch`` in a fresh Chromium) only when 1a's replay fails,
which is what an origin-checked/cookie-gated board looks like from our server (TikTok
400s from httpx and 200s from its own origin). Replaying from HERE — not from the
capture browser — is what catches IP/geo gating and a missing header BEFORE we promise
tracking. Beyond what ``run_recipe`` already enforces (2xx, parses, in-band error keys,
non-empty, ``expected_min_jobs``, the oracle), acceptance adds the one check only
discovery can make: the replayed ids must **overlap the ids the capture browser saw**.
A recipe that returns a hundred rows of something else passes every structural check
and is still the wrong feed.

**A board with no capturable API is REFUSED.** There is no DOM tier to fall back to, by
design (the owner's deterministic-only principle): every runtime path either works or it
does not, decided once, here. Refusing is how we never wrong-track.

NEVER RAISES. Every failure — including an unexpected one — becomes
``DiscoveryOutcome(ok=False, refuse_reason=…)``, because the caller is a ``retry=1``
Procrastinate task whose provisional ``discovering`` row is only cleared by a returned
outcome: an escaping exception wedges that row at "Setting up…" forever.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit, urlunsplit

from ..discovery.models import DiscoveryOutcome
from ..guarded_client import guarded_sync_client
from ..harvest_meta import HarvestEvidence
from ..harvest_verification import HarvestGateError, run_gate
from ..recipe_rows import recipe_rows_to_job_listings
from ..recipe_runner import RecipeExecutionError, map_records, run_recipe
from ..recipe_schema import RECIPE_VERSION, RecipeError, dig, validate_recipe
from ..url_guard import _DNS_EXECUTOR, UrlGuardError, validate_public_url
from .network_capture import CaptureError, CaptureResult, capture_board
from .request_selector import (
    Candidate,
    RequestSelection,
    RequestSelectionError,
    SelectorKeyMissingError,
    prefilter_candidates,
    select_request,
)

logger = logging.getLogger(__name__)

# The named steps. These strings are the user-visible half of a refusal, so they are
# phrased as what we were DOING, not as an internal module name.
_STEP_ENTRY = "checking the careers URL"
_STEP_CAPTURE = "opening the careers page"
_STEP_FILTER = "finding the jobs feed"
_STEP_SELECT = "reading the jobs feed"
_STEP_SYNTHESIZE = "writing the replay recipe"
_STEP_ACCEPT = "verifying we can read it"

# Placeholder company id for the acceptance replay only — the real id is minted by the
# service when the outcome is persisted.
_PROBE_COMPANY_ID = "discovery-probe"

# The STORED floor is permissive on purpose (a board must have >= 1 job to be worth
# tracking, and nothing more is knowable today). Guarding the nightly run against a
# shrink is the completeness gate's job — its delta band and 3-run VERIFIED streak —
# not a number frozen at discovery, which would turn every seasonal dip into a FAILED
# run. The ACCEPTANCE floor below is the strict one, because there we have a capture to
# compare against.
_STORED_EXPECTED_MIN_JOBS = 1

# At acceptance, the replay must return at least half of what the capture browser saw
# on its one page. Not equality: a live board legitimately moves between the capture and
# the replay seconds later, and a 50% floor separates "same feed" from "we are reading
# something else".
_ACCEPTANCE_MIN_RATIO = 0.5

# ...and at least this fraction of the capture's ids must reappear in the replay. THE
# match-the-capture check (D5). It is what stops a structurally-perfect recipe pointed
# at the wrong array from being stored.
_MIN_ID_OVERLAP_RATIO = 0.5

# The stored page budget. Ten pages of whatever the board's own page size is covers the
# ordinary board; a bigger one simply lands UNVERIFIED every night (it cannot prove it
# saw the whole board) which shows its jobs and never closes one. Deliberately below
# ``browser_fetch.runner._MAX_PAGES_CEILING`` (25) so the tier's own ceiling is never
# the thing that decides.
_MAX_PAGES = 10

# How many candidates the acceptance ladder is allowed to work through. Each round costs
# one Haiku call and up to two replays (one of them a Chromium launch), and the whole
# discovery task is bounded at 240s — so this is a real budget, not a formality.
_MAX_SELECTION_ROUNDS = 2

# Keys whose captured value being FALSY marks them as a success sentinel — TikTok's
# ``code: 0``, Amazon's ``error: null``. ``recipe_runner._check_inband_error`` fires on
# TRUTHINESS, so pinning exactly these keys turns a board's own in-band error channel
# into a FAILED run instead of a silently empty harvest. A key whose captured value is
# already truthy (``message: "ok"``) is NOT pinned — it would fail every single run.
_INBAND_ERROR_KEY_CANDIDATES = ("error", "errors", "code", "status", "success")

# Where a board publishes its own total. Searched deterministically (never asked of the
# LLM) because a hallucinated oracle path is a nightly FAILED run, and because this is
# the difference between a board that can ever be VERIFIED and one that is UNVERIFIED
# forever.
_TOTAL_KEY_HINTS = (
    "total", "hits", "count", "numfound", "num_found", "resultcount", "result_count",
    "totalcount", "total_count", "totaljobs", "total_jobs", "totalresults",
)
_MAX_TOTAL_SEARCH_DEPTH = 4

# Request headers never carried into a stored recipe. The exact names are per-connection
# junk or things the runner supplies itself; the SUBSTRING list is the important one — a
# captured session token replays fine TODAY (so acceptance would pass) and starts
# failing the moment it expires, which is a board that looks trackable and silently is
# not. Such a board belongs on the browser_fetch tier, where the browser re-earns its
# credentials same-origin every night, or refused.
_HEADER_DROP_EXACT = frozenset({
    "cookie", "set-cookie", "host", "content-length", "connection", "accept-encoding",
    "authorization", "proxy-authorization", "user-agent", "te", "upgrade", "expect",
})
_HEADER_DROP_SUBSTRINGS = ("token", "auth", "session", "csrf", "xsrf", "signature", "secret")
_HEADER_DROP_PREFIXES = ("sec-", ":")

CaptureFn = Callable[[str], Awaitable[CaptureResult]]
SelectFn = Callable[[list[Candidate]], Awaitable[RequestSelection]]
ReplayFn = Callable[[dict[str, Any]], Awaitable[tuple[list[dict], HarvestEvidence]]]
UrlValidator = Callable[[str], Any]


class _Refusal(Exception):
    """Internal control flow: a named-step refusal. Never escapes :func:`discover`."""

    def __init__(self, step: str, detail: str) -> None:
        super().__init__(f"{step}: {detail}")
        self.step = step
        self.detail = detail


# --------------------------------------------------------------------------
# step 5 — recipe synthesis (pure)
# --------------------------------------------------------------------------

def _origin_of(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def _clean_headers(headers: dict[str, str]) -> dict[str, str]:
    """The captured request headers that are safe and useful to replay verbatim.

    Keeps the static, non-secret ones a board genuinely requires — TikTok's
    ``website-path: tiktok`` is exactly this case, and dropping it would make an
    otherwise-deterministic board unreadable. See :data:`_HEADER_DROP_SUBSTRINGS` for
    why the credential-shaped ones are dropped rather than stored.
    """
    out: dict[str, str] = {}
    for raw_name, value in headers.items():
        name = str(raw_name).lower()
        if name in _HEADER_DROP_EXACT:
            continue
        if name.startswith(_HEADER_DROP_PREFIXES):
            continue
        if any(sub in name for sub in _HEADER_DROP_SUBSTRINGS):
            continue
        out[name] = str(value)
    return out


def _post_body(candidate: Candidate) -> dict[str, Any]:
    """The captured POST body as an object, or raise a refusal.

    ``recipe_schema`` requires ``fetch.body`` to be an object because that is what the
    pagination merge writes into. A form-encoded or non-object body is a board this
    vocabulary cannot express, and saying so here is better than storing a recipe whose
    paging silently does nothing.
    """
    try:
        parsed = json.loads(candidate.post_data or "", strict=False)
    except Exception as exc:  # noqa: BLE001
        raise _Refusal(
            _STEP_SYNTHESIZE,
            f"the jobs request POSTs a non-JSON body we cannot replay: {exc}",
        ) from exc
    if not isinstance(parsed, dict):
        raise _Refusal(
            _STEP_SYNTHESIZE,
            "the jobs request POSTs a JSON body that is not an object; "
            "the recipe vocabulary cannot express it",
        )
    return parsed


def _inband_error_keys(payload: Any) -> list[str]:
    """Top-level keys whose CAPTURED value is falsy — the board's success sentinels."""
    if not isinstance(payload, dict):
        return []
    return [k for k in _INBAND_ERROR_KEY_CANDIDATES if k in payload and not payload[k]]


def _find_total_path(payload: Any, records_path: str, record_count: int) -> str | None:
    """The dotted path to the board's own declared total, or ``None``.

    Deterministic breadth-first search over total-ish keys holding an int at least as
    big as the page we captured. Anything inside the records array is skipped: a per-job
    ``count`` is not a board total, and mistaking one for an oracle would make every run
    FAIL its exact-match comparison.
    """
    if not isinstance(payload, dict):
        return None
    frontier: list[tuple[Any, str, int]] = [(payload, "", 0)]
    while frontier:
        node, path, depth = frontier.pop(0)
        if depth > _MAX_TOTAL_SEARCH_DEPTH or not isinstance(node, dict):
            continue
        for key, value in node.items():
            child_path = f"{path}.{key}" if path else str(key)
            if child_path == records_path:
                continue
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and value >= record_count
                and any(hint in str(key).lower() for hint in _TOTAL_KEY_HINTS)
            ):
                return child_path
            if isinstance(value, dict):
                frontier.append((value, child_path, depth + 1))
    return None


def synthesize_recipe(
    candidate: Candidate,
    selection: RequestSelection,
    *,
    transport: str,
    origin_url: str,
) -> dict[str, Any]:
    """Assemble a validated replay recipe from one candidate + the model's mapping.

    Everything here except the field map and the paging hint is DERIVED from the bytes
    we captured, not asked of the model: the oracle, the in-band error keys, the headers
    and the body all come from the real request/response. That is deliberate — those are
    the parts where a plausible hallucination costs a nightly FAILED run rather than a
    refusal we would see immediately.

    RAISES :class:`_Refusal` (never a bare ``RecipeError``) so the caller's reason names
    the step the user is shown.
    """
    fetch: dict[str, Any] = {
        "op": "fetch",
        "method": candidate.method,
        "url": candidate.url,
        "headers": _clean_headers(candidate.request_headers),
    }
    if candidate.method == "POST":
        fetch["body"] = _post_body(candidate)

    steps: list[dict[str, Any]] = [fetch]

    total_path = _find_total_path(
        candidate.payload, selection.records_path, candidate.record_count
    )
    # Paginate only when the board says there is more than the page we captured. A
    # pagination step on a board we already read whole would spend a round-trip a night
    # to fetch an empty second page; no pagination on a board that HAS more is honest
    # (we harvest page one and the gate never calls that complete, so it never closes).
    declared_total = dig(candidate.payload, total_path) if total_path else None
    if selection.pagination is not None and isinstance(declared_total, int) and (
        declared_total > candidate.record_count
    ):
        op = "paginate_offset" if selection.pagination.style == "offset" else "paginate_page"
        steps.append({
            "op": op,
            "param": selection.pagination.param,
            # The OBSERVED page size, not the model's guess: the captured response IS
            # page one, so its record count is the board's real page size. A page_size
            # that disagrees with reality terminates the sweep one page early ("short
            # page") and reports a partial board as a complete one.
            "page_size": candidate.record_count,
            "max_pages": _MAX_PAGES,
        })

    steps.append({
        "op": "extract_json_path",
        "records_path": selection.records_path,
        "fields": dict(selection.field_map),
    })
    error_keys = _inband_error_keys(candidate.payload)
    if error_keys:
        steps.append({"op": "assert_no_inband_error", "error_keys": error_keys})
    steps.append({"op": "dedupe_key", "field": "id"})
    steps.append({"op": "assert_unique", "field": "id"})

    oracle: dict[str, Any] = (
        {"kind": "declared_probed", "total_path": total_path}
        if total_path else {"kind": "self_consistent"}
    )

    script: dict[str, Any] = {
        "script_version": RECIPE_VERSION,
        "transport": transport,
        "expected_min_jobs": _STORED_EXPECTED_MIN_JOBS,
        # Resolves leading-slash hrefs the board returns relative (Amazon's ``job_path``)
        # against the origin the capture actually landed on.
        "base_url": _origin_of(origin_url),
        "steps": steps,
        "oracle": oracle,
        # Stamped BEFORE the validation below, never after. ``validate_recipe`` runs
        # again on every nightly READ, so a key added post-validation would store a
        # recipe that passes once here and then fails every replay forever.
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "discovered_by": f"capture/{transport}",
    }
    if transport == "browser_fetch":
        script["origin_url"] = origin_url

    try:
        validate_recipe(script, transport=transport, oracle_kind=oracle["kind"])
    except RecipeError as exc:
        raise _Refusal(_STEP_SYNTHESIZE, f"the recipe we assembled is invalid: {exc}") from exc
    return script


# --------------------------------------------------------------------------
# step 6 — the acceptance gate
# --------------------------------------------------------------------------

async def _default_replay_http(script: dict[str, Any]) -> tuple[list[dict], HarvestEvidence]:
    """Tier 1a acceptance: the EXACT production replay path — ``run_recipe`` over the
    SSRF-guarded sync client, in a thread so the blocking DNS/sockets never stall the
    worker's loop."""
    def _run() -> tuple[list[dict], HarvestEvidence]:
        http = guarded_sync_client()
        try:
            return run_recipe(
                script, http,
                transport=script["transport"], oracle_kind=script["oracle"]["kind"],
            )
        finally:
            http.close()

    return await asyncio.to_thread(_run)


async def _default_replay_browser(script: dict[str, Any]) -> tuple[list[dict], HarvestEvidence]:
    """Tier 1b acceptance: the EXACT production replay path for ``browser_fetch`` — a
    FRESH local Chromium via the same subprocess the nightly harvest uses. Imported
    lazily so this module's import graph never even references the browser_fetch parent
    until a board actually needs the tier."""
    from ..browser_fetch.runner import run_browser_fetch

    return await run_browser_fetch(
        script, transport=script["transport"], oracle_kind=script["oracle"]["kind"]
    )


def _capture_ids(candidate: Candidate, selection: RequestSelection, base_url: str) -> set[str]:
    """The ids the CAPTURE BROWSER saw, mapped with the same field map the recipe uses.

    Same ``map_records`` the replay goes through, on purpose: comparing ids derived two
    different ways would compare the mappers, not the feeds.
    """
    rows = map_records(candidate.records, dict(selection.field_map), base_url)
    return {row["id"] for row in rows}


def _assert_matches_capture(
    rows: list[dict], candidate: Candidate, selection: RequestSelection, base_url: str
) -> None:
    """THE match-the-capture assertion (D5). Raises :class:`_Refusal` on a mismatch."""
    expected = _capture_ids(candidate, selection, base_url)
    if not expected:
        raise _Refusal(
            _STEP_ACCEPT,
            "the captured response yielded no usable job ids to compare against",
        )
    floor = max(1, int(len(expected) * _ACCEPTANCE_MIN_RATIO))
    if len(rows) < floor:
        raise _Refusal(
            _STEP_ACCEPT,
            f"the replay returned {len(rows)} job(s) but the browser saw "
            f"{len(expected)} — too few to believe it is the same feed",
        )
    replayed = {str(row["id"]) for row in rows}
    overlap = len(expected & replayed)
    if overlap < max(1, int(len(expected) * _MIN_ID_OVERLAP_RATIO)):
        raise _Refusal(
            _STEP_ACCEPT,
            f"only {overlap} of the {len(expected)} job(s) the browser saw came back "
            "from the replay — we are not reading the same list",
        )


async def _try_acceptance(
    script: dict[str, Any],
    candidate: Candidate,
    selection: RequestSelection,
    *,
    replay: ReplayFn,
) -> list[dict]:
    """Replay ``script`` from the production path and assert it read the right board.

    ``run_recipe`` / ``run_browser_fetch`` already enforce 2xx, JSON, the in-band error
    keys, a resolving records path, non-empty, the ``expected_min_jobs`` floor and the
    oracle — the RAISES-never-empty ladder, reused rather than reimplemented. On top of
    that this runs the SAME structural gate the nightly harvest runs (so a board that
    could never pass the gate is refused now rather than discovered and then broken every
    night), and finally the match-the-capture check.
    """
    rows, evidence = await replay(script)
    jobs = recipe_rows_to_job_listings(_PROBE_COMPANY_ID, rows)
    gate = run_gate(jobs, evidence, oracle_kind=script["oracle"]["kind"])
    if gate.is_zero or not gate.jobs:
        raise HarvestGateError("the replay produced no usable job rows")
    _assert_matches_capture(rows, candidate, selection, script.get("base_url", ""))
    return rows


# --------------------------------------------------------------------------
# the orchestrator
# --------------------------------------------------------------------------

async def _public_candidates(
    candidates: list[Candidate], validate: UrlValidator
) -> list[Candidate]:
    """Drop every candidate whose endpoint fails the SSRF guard (invariant #4, the
    discovered-endpoint half).

    Ordering matters: the shape pre-filter runs FIRST so this pays for DNS only on the
    handful of job-shaped survivors, and it runs BEFORE the LLM sees anything so a page
    that XHRs an internal address can never get that address into a prompt, let alone
    into a stored recipe.
    """
    loop = asyncio.get_running_loop()
    kept: list[Candidate] = []
    for candidate in candidates:
        try:
            await loop.run_in_executor(_DNS_EXECUTOR, validate, candidate.url)
        except UrlGuardError as exc:
            logger.info("discovery dropped non-public endpoint %s: %s", candidate.url, exc)
            continue
        kept.append(candidate)
    # Re-index so ``chosen_request_index`` still means "position in the list you saw".
    return [replace(candidate, index=i) for i, candidate in enumerate(kept)]


async def discover(
    url: str,
    *,
    capture: CaptureFn | None = None,
    select: SelectFn | None = None,
    replay_http: ReplayFn | None = None,
    replay_browser: ReplayFn | None = None,
    validate_url: UrlValidator | None = None,
) -> DiscoveryOutcome:
    """Run one capture discovery for ``url``. NEVER raises — a failure is a REFUSE.

    Every collaborator is an injectable keyword-only seam defaulting to the real thing,
    so the unit tests exercise the whole ladder at $0 with no browser, no LLM and no
    network — the same discipline ``run_browser_fetch`` and the retired browser-agent
    discover used.
    """
    # The URL seam is ``url_guard.validate_public_url`` itself — raising
    # ``UrlGuardError``, whose reason codes are an API contract. The step naming is done
    # HERE rather than inside a wrapper so an injected validator (tests) takes exactly
    # the same paths as the real one.
    check_url = validate_url or validate_public_url
    do_capture = capture or capture_board
    do_select = select or select_request
    run_http = replay_http or _default_replay_http
    run_browser = replay_browser or _default_replay_browser

    attempts = 0
    try:
        # STEP 1 — SSRF on the pasted URL, off the loop (blocking getaddrinfo on a host
        # a stranger chose; see network_capture for the whole argument).
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(_DNS_EXECUTOR, check_url, url)
        except UrlGuardError as exc:
            raise _Refusal(
                _STEP_ENTRY, f"blocked by our safety check ({exc.reason}): {exc}"
            ) from exc

        # STEP 2 — one browser session, ever.
        try:
            captured = await do_capture(url)
        except CaptureError as exc:
            raise _Refusal(_STEP_CAPTURE, str(exc)) from exc

        # The origin a browser_fetch recipe navigates to, and the base for relative
        # hrefs. Falls back to the pasted URL when the capture ended somewhere we may
        # not store (validate_recipe requires https).
        origin_url = (
            captured.final_url
            if captured.final_url.startswith("https://") else url
        )

        # STEP 3 — deterministic pre-filter, then the endpoint SSRF half.
        candidates = prefilter_candidates(captured.responses)
        if not candidates:
            # Two genuinely different boards, and the user's next action differs, so the
            # copy does too: a page that fetched NO JSON at all is server-rendered or
            # bot-walled (measured: metacareers.com captures zero XHRs), while a page
            # that fetched plenty and none of it was jobs usually means the jobs live
            # behind a filter/search the capture never triggered.
            raise _Refusal(
                _STEP_FILTER,
                "this page loaded its jobs without any JSON request we could record — "
                "it renders them on the server or blocks automated browsers"
                if not captured.responses else
                f"none of the {len(captured.responses)} JSON request(s) this page made "
                "returned a list of job postings",
            )
        candidates = await _public_candidates(candidates, check_url)
        if not candidates:
            raise _Refusal(
                _STEP_FILTER,
                "the only job-shaped requests this page made point at addresses we "
                "refuse to fetch",
            )

        # STEPS 4-6 — ask, synthesize, prove. Each round burns ONE Haiku call and at
        # most two replays; a failed candidate is removed and the next round asks again
        # over what is left, which is how "try the next candidate" stays a real
        # fallback instead of reusing a field map that belonged to a different feed.
        # The step + detail of the most recent failure. Carried as a PAIR because the
        # final refusal must name the step that actually failed: "writing the replay
        # recipe" and "verifying we can read it" are different problems with different
        # next actions for the user, and collapsing both into the last step would tell
        # them the wrong one.
        last_step = _STEP_ACCEPT
        last_error: str | None = None
        for round_number in range(1, _MAX_SELECTION_ROUNDS + 1):
            if not candidates:
                break
            attempts = round_number
            try:
                selection = await do_select(candidates)
            except SelectorKeyMissingError as exc:
                # Not the board's fault and not retryable: refuse WITHOUT counting an
                # attempt, exactly as the location cascade degrades on a missing key.
                logger.warning("discovery cannot run: %s", exc)
                return DiscoveryOutcome(
                    ok=False,
                    refuse_reason=f"{_STEP_SELECT}: discovery is not configured on this deployment",
                    attempts=0,
                )
            except RequestSelectionError as exc:
                # A rejected answer costs this ROUND, not the whole discovery: the model
                # is being asked to read a truncated sample, and a second ask over the
                # same candidates is cheap next to refusing a board we can read. It is
                # bounded by _MAX_SELECTION_ROUNDS like every other round.
                last_step, last_error = _STEP_SELECT, str(exc)
                logger.info("discovery selection rejected for %s: %s", url, exc)
                continue

            candidate = candidates[selection.chosen_request_index]
            for transport, replay in (("http_json", run_http), ("browser_fetch", run_browser)):
                try:
                    script = synthesize_recipe(
                        candidate, selection, transport=transport, origin_url=origin_url
                    )
                    rows = await _try_acceptance(
                        script, candidate, selection, replay=replay
                    )
                except _Refusal as exc:
                    last_step, last_error = exc.step, exc.detail
                    logger.info(
                        "discovery %s rejected for %s on %s: %s",
                        transport, url, candidate.url, exc.detail,
                    )
                    continue
                except (
                    RecipeExecutionError, RecipeError, HarvestGateError, ValueError
                ) as exc:
                    last_step = _STEP_ACCEPT
                    last_error = f"{type(exc).__name__}: {exc}"
                    logger.info(
                        "discovery %s replay failed for %s on %s: %s",
                        transport, url, candidate.url, last_error,
                    )
                    continue

                logger.info(
                    "capture discovery ACCEPTED %s: %s %s -> %d jobs "
                    "(transport=%s oracle=%s round=%d)",
                    url, candidate.method, candidate.url, len(rows),
                    transport, script["oracle"]["kind"], round_number,
                )
                return DiscoveryOutcome(
                    ok=True,
                    script=script,
                    transport=transport,
                    oracle_kind=script["oracle"]["kind"],
                    attempts=round_number,
                    cost_note=(
                        f"1 browser capture + {round_number} Haiku selection(s); "
                        f"replays as {transport}"
                    ),
                )
            # This candidate cannot be replayed either way — drop it and ask again.
            candidates = [
                replace(c, index=i)
                for i, c in enumerate(c for c in candidates if c.index != candidate.index)
            ]

        raise _Refusal(
            last_step,
            last_error or "we could not replay any of this board's requests",
        )

    except _Refusal as exc:
        logger.warning("capture discovery REFUSED %s — %s", url, exc)
        return DiscoveryOutcome(ok=False, refuse_reason=str(exc), attempts=attempts)
    except Exception as exc:  # noqa: BLE001
        # BROAD ON PURPOSE. The caller is a retry=1 task whose provisional
        # ``discovering`` row is cleared only by an outcome being RETURNED; an escaping
        # exception leaves that row stuck at "Setting up…" with no way out but Remove +
        # re-add. A loud refusal carrying the exception type is strictly better than a
        # wedged row, and the log line below keeps the stack.
        logger.exception("capture discovery crashed for %s", url)
        return DiscoveryOutcome(
            ok=False,
            refuse_reason=f"{_STEP_ACCEPT}: discovery failed unexpectedly "
                          f"({type(exc).__name__})",
            attempts=attempts,
        )
