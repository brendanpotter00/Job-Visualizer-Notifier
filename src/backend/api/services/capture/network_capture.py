"""DISCOVERY SIDE — the agent-free parent of the network-capture subprocess (E7 capture).

:func:`capture_board` is step 1+2 of discovery ("open the careers page", "record the
network"): it SSRF-validates the pasted URL, spawns :mod:`._capture_main` out of
process, and returns the JSON XHR/fetch responses that browser saw. It is the only
place a browser is opened for a discovered board, ever — everything after this is
deterministic replay of what was recorded here.

Mirrors ``browser_fetch.runner`` exactly, because the boundary is the same one:

1. SSRF (``url_guard.validate_public_url``) on the entry URL BEFORE anything spawns —
   a blocked URL must cost zero Chromium;
2. spawn ``_capture_main`` OUT OF PROCESS, so ``playwright`` never enters this process
   (the AST import guard proves it, and the replay leaf task shares this worker);
3. validate the child's report on read — a report we cannot fully believe is a
   :class:`CaptureError`, i.e. a named-step REFUSE, never a partial capture.

**Own Chromium is the default.** Browserbase is opt-in per :data:`~api.config.settings`
(``capture_use_browserbase`` plus real credentials) because it bills per browser-hour
and buys only two things a normal careers page does not need: stealth/residential IPs
for a bot-walled board, and the hosted live-view URL the discovery-progress UI embeds.
When it IS on, this parent creates the session and passes only the resulting CDP URL to
the child on stdin — the API key itself never leaves this process.

Two rules make that opt-in safe to leave on:

* the live-view URL is handed to the caller through the ``on_live_view`` CALLBACK the
  instant the session exists — before the child spawns, before the page loads — because
  a hosted view of a session that has already ended is a dead iframe, and RETRACTED
  through ``on_live_view_closed`` the instant it stops being watchable, because the
  caller cannot work that moment out for itself (it is earlier than any step it ticks);
  and
* the session is RELEASED in a ``finally``, on the success path, the refusal path and
  the cancellation path alike. Browserbase bills per browser-hour; a session we merely
  stop using goes on charging until its own ``timeout`` expires.

RAISES :class:`CaptureError` on every failure. Discovery turns that into
``DiscoveryOutcome(ok=False, refuse_reason=…)``; nothing is ever stored from a capture
we could not complete.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol
from urllib.parse import urlsplit

import httpx

from ..url_guard import _DNS_EXECUTOR, UrlGuardError, validate_public_url
from ...config import settings

logger = logging.getLogger(__name__)

# Subprocess wall-clock cap. It MUST stay strictly BELOW the discovery task's own
# ``_TASK_TIMEOUT_S`` (240s) for the same reason ``browser_fetch`` keeps 90 < 900: if
# the task's guard fires first it CANCELS this coroutine, a ``CancelledError`` is not
# an ``asyncio.TimeoutError``, and the timeout branch below — the only place that kills
# the child — would never run. The ``finally`` in :func:`_subprocess_run` reaps on the
# cancellation path too; the ordering is what keeps the FAILURE legible as a capture
# timeout instead of a task death.
_SUBPROCESS_TIMEOUT_S = 120.0

# How long to wait for a SIGKILLed child to actually die before giving up on reaping it
# ourselves. ``tini`` is PID 1 in the container precisely so an unreaped grandchild is
# still collected (see the Dockerfile's pthread-exhaustion note).
_REAP_TIMEOUT_S = 10.0

# How much of the child's stdout to take per read. The report itself can be ~16 MB (the
# child's aggregate body ceiling), so this is a pump size, not a limit.
_READ_CHUNK_BYTES = 65_536

# The longest line we are willing to try to parse as a narration EVENT. An event is a
# couple of hundred bytes; the report is megabytes. Without this, every report would be
# JSON-parsed twice — once here and once in ``_parse_report`` — for nothing.
_MAX_EVENT_LINE_BYTES = 4_096

# How long ONE narration callback may take before we stop waiting on it. This runs
# INSIDE the loop draining the child's stdout pipe, so a progress write that hangs would
# stop us reading, fill the pipe, and block the browser mid-capture: the narration would
# have taken down the thing it narrates. Bounded, and a timeout is logged and dropped.
_EVENT_CALLBACK_TIMEOUT_S = 5.0

# Browserbase session bounds (opt-in path only).
_BROWSERBASE_API = "https://api.browserbase.com/v1/sessions"
_BROWSERBASE_TIMEOUT_S = 20.0
# The session's OWN expiry, and the only cost backstop we do not control from here: if
# this process dies between creating a session and releasing it, Browserbase stops
# billing after this many seconds and not before. Kept tight for that reason — the
# worst-case leak is 5 paid minutes, and the explicit release below normally makes the
# real figure the length of one capture.
_BROWSERBASE_SESSION_TTL_S = 300
# The release POST gets its own, tighter budget because it runs inside a ``finally``
# that may be executing under a cancellation: a slow cleanup there would turn a legible
# capture timeout into a hung discovery task, which is the one failure this whole file
# is arranged to prevent.
_BROWSERBASE_RELEASE_TIMEOUT_S = 10.0

# One line of narration off the child's stdout, already parsed. Async because the only
# real implementation writes a progress row to Postgres.
EventFn = Callable[[dict[str, Any]], Awaitable[None]]


class RunSubprocess(Protocol):
    """The child seam — :func:`_subprocess_run` or a $0 test double.

    A Protocol rather than a ``Callable`` alias because of ``on_event``, which is what
    makes the capture NARRATABLE: the child announces each recorded response as it lands
    and this callback forwards it, so a test double can drive the streaming path without
    a browser exactly the way it drives the report path.
    """

    def __call__(
        self, plan: dict[str, Any], *, on_event: EventFn | None = None
    ) -> Awaitable[dict[str, Any]]: ...


UrlValidator = Callable[[str], Any]
OpenSession = Callable[[], Awaitable["BrowserSession | None"]]
ReleaseSession = Callable[["BrowserSession"], Awaitable[None]]
# Called with the hosted live-view URL the MOMENT a session has one — see the call site
# in :func:`capture_board` for why it is a callback and not a return value.
LiveViewFn = Callable[[str], Awaitable[None]]
# Called with nothing the moment that hosted view stops being WATCHABLE — the teardown
# half of ``LiveViewFn``, fired from the same ``finally`` that hands the session back.
# It exists because "is the browser still open?" was being INFERRED by the UI from the
# checklist ("step 1 is active, so there must be a browser"), and that inference is
# false: the child closes the browser (killing the CDP socket the live view is a view
# OF) and only then does discovery score, publish and tick step 1 over. The frame went
# dead seconds before the checklist admitted it. This callback is the backend stating
# the fact instead of the frontend guessing at it.
LiveViewClosedFn = Callable[[], Awaitable[None]]
# Called with ONE display-ready record per response the browser saw, the moment it is
# seen — see :func:`capture_board` for why it is a callback and not a return value.
RequestFn = Callable[[dict[str, Any]], Awaitable[None]]
HttpClientFactory = Callable[[], httpx.AsyncClient]


class CaptureError(RuntimeError):
    """The capture could not be completed. ALWAYS a refusal, never a partial result."""


@dataclass(frozen=True)
class BrowserSession:
    """A remote CDP browser the child should attach to instead of launching one.

    ``live_view_url`` is the hosted, iframe-embeddable view of the session — the
    primitive the discovery-progress UI (PR3) renders while steps 1–2 run. It is
    carried through here rather than fetched later because the session is gone by the
    time discovery finishes.
    """

    cdp_url: str
    live_view_url: str | None = None
    session_id: str | None = None


@dataclass(frozen=True)
class CapturedResponse:
    """One JSON XHR/fetch the capture browser saw. ``body`` may be truncated."""

    url: str
    method: str
    status: int
    content_type: str
    request_headers: dict[str, str]
    post_data: str | None
    body: str
    truncated: bool
    # What the response ACTUALLY weighed, which is not ``len(body)`` once a body has
    # been dropped for being oversize. Display-only — the pre-filter reads ``body`` —
    # and it is what lets a refusal say "2.7 MB, larger than we can record in one go"
    # instead of reporting the board's biggest response as empty.
    body_bytes: int = 0


@dataclass(frozen=True)
class CaptureResult:
    """Everything one capture produced. ``final_url`` is where the browser ENDED UP —
    it is what a ``browser_fetch`` recipe stores as its ``origin_url``, so a board that
    redirected in-page still fetches from the origin its own API expects."""

    final_url: str
    page_title: str
    responses: list[CapturedResponse]
    live_view_url: str | None = None
    # THE BOARD DOCUMENT'S OWN LINKS, read off the RENDERED DOM once the observation
    # window closed. Raw material for job-link derivation and nothing else: the parent
    # matches captured job ids against these hrefs to work out the shape of a per-job
    # URL, and PROVES the result by fetching two real jobs before it can be stored.
    # ``board_scripts`` is the fallback source for a board that renders no job anchors at
    # all (Jane Street) — the parent fetches a couple of them through its SSRF-guarded
    # client and reads the ``href="…${…}…"`` literal the board builds its own links with.
    #
    # Both default to empty, so a report from a child that predates them (a rolling
    # deploy, a replayed fixture) degrades to exactly today's behaviour rather than
    # failing the capture.
    board_links: tuple[str, ...] = ()
    board_scripts: tuple[str, ...] = ()
    # SOURCE 6 — the SERVED navigation document, which the host pin already fetched and
    # used to throw away. These are the exact bytes an ``http_html`` recipe re-fetches
    # every night, which is what makes them the right evidence for that transport and
    # the wrong evidence for link derivation (BIRTH-DEFECTS-PLAN §0, mirrored).
    server_html: str = ""
    server_html_url: str = ""
    # SOURCES 2a/2b — JSON blobs embedded in a document, each with the CSS selector that
    # re-finds it and the ``scope`` that says WHICH document. ``served`` is replayable
    # (one GET + one selector); ``rendered`` exists only after hydration and no transport
    # we admit can reproduce it, so it contributes ids and never records.
    islands: tuple[dict[str, Any], ...] = ()


def _hostname(url: str) -> str:
    """Lowercased host of ``url``, or ``''``. Matches the child's own copy."""
    return (urlsplit(url).hostname or "").lower()


# Everything the child legitimately needs, and nothing else — an ALLOWLIST, not a copy
# of our environment. ``dict(os.environ)`` would hand a Chromium launched with
# ``--no-sandbox``, pointed at a URL a stranger pasted, the worker's whole production
# credential set (``DATABASE_URL``, ``INTERNAL_API_KEY``, ``ANTHROPIC_API_KEY``,
# ``BROWSERBASE_API_KEY``) inherited straight into every renderer process. The one
# secret this child may ever see is a Browserbase CDP URL, and that arrives on stdin.
_ENV_ALLOWLIST = (
    "PATH",                   # find the interpreter's own tooling
    "HOME",                   # where `playwright install` put ~/.cache/ms-playwright
    "TMPDIR", "TMP", "TEMP",  # Chromium's user-data-dir / crashpad scratch
    "LANG", "LC_ALL",         # locale-dependent text handling in the child
    "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_RUNTIME_DIR",
    "PYTHONUNBUFFERED",       # the Dockerfile sets it so stderr is line-flushed
    "SYSTEMROOT",             # Windows-only; harmless elsewhere, fatal to omit there
)


def _child_env() -> dict[str, str]:
    """The child's ENTIRE environment (see :data:`_ENV_ALLOWLIST`). ``PLAYWRIGHT_*``
    passes through by prefix because the browser-path vars an image may set are not a
    fixed list; none of them is a secret."""
    env = {key: os.environ[key] for key in _ENV_ALLOWLIST if key in os.environ}
    env.update({k: v for k, v in os.environ.items() if k.startswith("PLAYWRIGHT_")})
    return env


async def _reap(proc: Any) -> None:
    """SIGKILL the child if it is still running, then WAIT for it — on EVERY path.

    ``kill()`` without the ``wait()`` leaves a zombie holding its pid and pipes, and no
    ``kill()`` at all leaves a live headless Chromium (hundreds of MB) on the Railway
    box plus a child blocked forever writing a report into a pipe whose reader is gone.
    Swallowing a cancellation here is deliberate: the SIGKILL is already delivered,
    ``tini`` collects what we could not, and re-raising would replace the real failure
    with a bookkeeping one.
    """
    if proc.returncode is not None:
        return
    try:
        proc.kill()
    except ProcessLookupError:      # it exited between the check and the kill
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=_REAP_TIMEOUT_S)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        logger.warning("capture subprocess did not exit after SIGKILL")


async def _pump_stdout(
    stream: asyncio.StreamReader, on_event: EventFn | None
) -> bytes:
    """Read the child's stdout to EOF, dispatching each complete line as it arrives.

    Deliberately ``read(n)`` and a hand-rolled line split rather than ``readline()``:
    ``StreamReader`` carries a 64 KiB line limit and the child's report is a SINGLE line
    of up to ~16 MB, so ``readline`` would raise ``LimitOverrunError`` on every real
    capture. Raising the stream limit instead would work and would also pre-allocate the
    ceiling; this costs one ``find``.

    The whole of stdout is still returned — same bytes ``communicate`` used to hand
    back, same ``_parse_report`` reading them — because the report is the thing
    discovery actually runs on and narration must not become load-bearing for it. The
    scan cursor is what keeps that free: lines are dispatched out of the SAME buffer,
    never copied into a second one.
    """
    buf = bytearray()
    scanned = 0
    while True:
        chunk = await stream.read(_READ_CHUNK_BYTES)
        if not chunk:
            break
        buf += chunk
        while True:
            newline = buf.find(b"\n", scanned)
            if newline < 0:
                break
            line = bytes(buf[scanned:newline])
            scanned = newline + 1
            await _dispatch_event(line, on_event)
    return bytes(buf)


async def _dispatch_event(line: bytes, on_event: EventFn | None) -> None:
    """Forward ``line`` if it is a narration event. NEVER raises, never blocks for long.

    Three guards, each closing a way narration could damage the capture it narrates:
    the length check keeps us from JSON-parsing a 16 MB report line a second time, the
    ``wait_for`` bounds a progress write that hangs (we are inside the pipe drain — a
    stall here stalls the browser), and the swallow means a failed write costs a row of
    a display panel and nothing else.
    """
    if on_event is None or not line or len(line) > _MAX_EVENT_LINE_BYTES:
        return
    try:
        parsed = json.loads(line)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return  # Chromium is chatty; a line we cannot read is not an event
    if not isinstance(parsed, dict) or "event" not in parsed:
        return
    try:
        await asyncio.wait_for(on_event(parsed), timeout=_EVENT_CALLBACK_TIMEOUT_S)
    except Exception:  # noqa: BLE001 - see the docstring
        logger.warning("capture progress event dropped (continuing)", exc_info=True)


async def _subprocess_run(
    plan: dict[str, Any], *, on_event: EventFn | None = None
) -> dict[str, Any]:
    """Spawn ``_capture_main``, narrate its stdout, and return its parsed JSON report.

    The child imports ``playwright``; THIS parent never does — the boundary that keeps
    the shared replay worker agent-free. The plan (including a Browserbase CDP URL when
    one is in play) goes on **stdin**, never argv.

    ``on_event`` receives each line the child prints about a response it just recorded,
    as it is printed. It is optional and it is cosmetic: a run with no callback behaves
    exactly as this did before streaming existed.
    """
    backend_root = Path(__file__).resolve().parents[3]  # src/backend
    repo_root = backend_root.parents[1]                 # repo root (holds scripts/)
    env = _child_env()
    prior = os.environ.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(backend_root), str(repo_root), prior) if p
    )

    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "api.services.capture._capture_main",
        cwd=str(backend_root),
        env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def _feed_and_collect() -> tuple[bytes, bytes]:
        """Write the plan in, then drain BOTH pipes to EOF, narrating stdout as it goes.

        This replaced ``proc.communicate()`` for exactly one reason: ``communicate``
        returns when the process EXITS, so every line the child printed while the
        browser was open arrived 30-80 seconds late, all at once. Nothing about the
        capture changed; what changed is that the parent now sees each response as the
        child records it.

        BOTH pipes are drained CONCURRENTLY, which is the part that is not optional: a
        child blocked writing a full stderr pipe never gets to finish its report, and a
        sequential reader is how that deadlock happens. (``communicate`` did this too —
        this is keeping the property, not adding one.)

        The plan is written first rather than inside the gather because it is a few
        hundred bytes, i.e. orders of magnitude under one pipe buffer; a plan that could
        fill a pipe would have to move into the gather.
        """
        assert proc.stdin is not None and proc.stdout is not None
        assert proc.stderr is not None
        proc.stdin.write(json.dumps(plan).encode("utf-8"))
        try:
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            # The child died before reading its plan. Not our error to report: it exits
            # non-zero and the rc branch below quotes its stderr, which says why.
            pass
        proc.stdin.close()
        out, err = await asyncio.gather(
            _pump_stdout(proc.stdout, on_event), proc.stderr.read()
        )
        # Both pipes are at EOF, so this is bookkeeping rather than a wait — but it is
        # what makes ``proc.returncode`` below a real exit status instead of ``None``.
        await proc.wait()
        return out, err

    try:
        stdout, stderr = await asyncio.wait_for(
            _feed_and_collect(), timeout=_SUBPROCESS_TIMEOUT_S
        )
    except asyncio.TimeoutError as exc:
        raise CaptureError(
            f"capture subprocess timed out after {_SUBPROCESS_TIMEOUT_S}s"
        ) from exc
    finally:
        # NOT in the ``except`` — the discovery task's 240s ``wait_for`` cancels this
        # coroutine, and a ``CancelledError`` (a BaseException) skips every ``except``
        # clause here. Reaping in the ``finally`` is what makes the kill unconditional.
        await _reap(proc)
    if proc.returncode != 0:
        raise CaptureError(
            f"capture subprocess failed (rc={proc.returncode}): "
            f"{stderr.decode('utf-8', 'replace')[:500]}"
        )
    return _parse_report(stdout.decode("utf-8", "replace"))


def _parse_report(stdout: str) -> dict[str, Any]:
    """Parse the report from stdout, tolerating stray log lines (Chromium is chatty)."""
    for line in reversed([ln for ln in stdout.splitlines() if ln.strip()]):
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and "responses" in parsed and "final_url" in parsed:
            return parsed
    raise CaptureError("capture subprocess produced no JSON report on stdout")


def _browserbase_headers() -> dict[str, str]:
    """Auth for every Browserbase call. The key NEVER leaves this process — the child
    is handed a connect URL and nothing else (see :data:`_ENV_ALLOWLIST`)."""
    return {
        "X-BB-API-Key": settings.browserbase_api_key or "",
        "Content-Type": "application/json",
    }


async def _fetch_live_view(http: httpx.AsyncClient, session_id: str) -> str | None:
    """``GET /v1/sessions/{id}/debug`` -> ``debuggerFullscreenUrl``, best-effort.

    This is the ONLY thing that makes the discovery-progress iframe possible, and it is
    still best-effort: losing it costs the UI its picture, never the capture.

    Deliberately NOT ``/recording``. That endpoint is deprecated, and it is also the
    wrong primitive — an rrweb recording only exists once the session has ENDED, which
    is precisely when nobody wants to watch it. ``debuggerFullscreenUrl`` is live.
    """
    try:
        debug = await http.get(
            f"{_BROWSERBASE_API}/{session_id}/debug", headers=_browserbase_headers()
        )
        if debug.status_code != 200:
            logger.info(
                "Browserbase live view unavailable (HTTP %s); continuing without it",
                debug.status_code,
            )
            return None
        url = debug.json().get("debuggerFullscreenUrl")
    except (httpx.HTTPError, ValueError, AttributeError):
        logger.info(
            "Browserbase live-view URL unavailable; continuing without it", exc_info=True
        )
        return None
    return url if isinstance(url, str) and url else None


async def _request_release(http: httpx.AsyncClient, session_id: str) -> None:
    """Ask Browserbase to end ``session_id`` NOW. Raises; callers decide what that means."""
    response = await http.post(
        f"{_BROWSERBASE_API}/{session_id}",
        headers=_browserbase_headers(),
        json={
            "projectId": settings.browserbase_project_id,
            "status": "REQUEST_RELEASE",
        },
        timeout=_BROWSERBASE_RELEASE_TIMEOUT_S,
    )
    if response.status_code >= 400:
        raise httpx.HTTPError(
            f"release refused (HTTP {response.status_code}): "
            f"{response.text[:200]!r}"
        )


async def _release_browserbase_session(
    session: BrowserSession, *, client_factory: HttpClientFactory | None = None
) -> None:
    """Hand the session back the moment we are done with it. Runs on EVERY exit path.

    Browserbase bills per browser-HOUR, so a session we stop using but never release
    keeps billing until its own ``timeout`` expires: ~5 paid minutes for a capture that
    took 30 seconds, on every single run. The failure paths are worse, not better —
    ``_subprocess_run``'s timeout SIGKILLs the child, so nobody ever closes the CDP
    socket politely and the disconnect Browserbase would otherwise notice is the
    slowest one available.

    NEVER RAISES — and the ``except`` is deliberately as wide as ``Exception``, not the
    httpx errors alone. This is called from a ``finally``; an exception escaping here
    would REPLACE the real failure (a capture timeout, a refused report) with a
    billing-cleanup one, and the user would be told the wrong thing about their board.
    The non-httpx case is not theoretical: this runs during teardown, where opening a
    fresh client can raise ``RuntimeError('Event loop is closed')``.
    :data:`_BROWSERBASE_SESSION_TTL_S` is the backstop for the one case we cannot cover
    — a cancellation delivered while this very await is in flight, which is a
    ``BaseException`` and must keep propagating.
    """
    if not session.session_id:
        return
    if not (settings.browserbase_api_key and settings.browserbase_project_id):
        return
    open_client = client_factory or (
        lambda: httpx.AsyncClient(timeout=_BROWSERBASE_RELEASE_TIMEOUT_S)
    )
    try:
        async with open_client() as http:
            await _request_release(http, session.session_id)
        logger.info("Browserbase session %s released", session.session_id)
    except Exception:  # noqa: BLE001 — see NEVER RAISES above
        logger.warning(
            "Browserbase session %s could not be released; it will bill until its own "
            "%ss timeout expires",
            session.session_id, _BROWSERBASE_SESSION_TTL_S, exc_info=True,
        )


async def _open_browserbase_session(
    *, client_factory: HttpClientFactory | None = None
) -> BrowserSession | None:
    """Create a Browserbase session, or ``None`` when the opt-in is not fully configured.

    Returning ``None`` rather than raising is the whole point: Browserbase is an
    OPTIONAL upgrade (stealth IPs + the hosted live view), so a missing key, a 402
    ("free plan limit reached") or a Browserbase outage must degrade to our own
    Chromium, not refuse a board we could have read for free.

    ``client_factory`` is injectable because the flag is the thing that costs money and
    "returns None" cannot prove it was honoured: with the opt-in check deleted, this
    function issues a real ``POST /v1/sessions``, the 401 lands in the ``httpx.HTTPError``
    swallow below, and it returns the SAME ``None``. The only observable difference is
    whether a request was attempted — so the test asserts on that, the way the spawn
    counters elsewhere in this module do.
    """
    if not settings.capture_use_browserbase:
        return None
    if not (settings.browserbase_api_key and settings.browserbase_project_id):
        logger.warning(
            "capture_use_browserbase is on but BROWSERBASE_API_KEY/PROJECT_ID are "
            "unset; falling back to our own Chromium"
        )
        return None
    open_client = client_factory or (
        lambda: httpx.AsyncClient(timeout=_BROWSERBASE_TIMEOUT_S)
    )
    try:
        async with open_client() as http:
            created = await http.post(
                _BROWSERBASE_API,
                headers=_browserbase_headers(),
                json={
                    "projectId": settings.browserbase_project_id,
                    "timeout": _BROWSERBASE_SESSION_TTL_S,
                },
            )
            if created.status_code >= 400:
                # NAMED rather than swallowed into one generic warning. A 402 is the
                # status an owner actually hits ("free plan limit reached") and it is
                # indistinguishable from an outage in the log otherwise — the behaviour
                # is identical (fall back and read the board for free) but the human
                # ACTION differs: top up the plan, versus wait it out.
                logger.warning(
                    "Browserbase refused a session (HTTP %s: %s); falling back to our "
                    "own Chromium",
                    created.status_code,
                    created.text[:200].replace("\n", " "),
                )
                return None
            payload = created.json()
            session_id = payload.get("id")
            connect_url = payload.get("connectUrl")
            if not (isinstance(connect_url, str) and connect_url):
                # We have been BILLED for a browser we cannot drive. Releasing before
                # the fallback is the difference between a free degrade and a silent
                # 5-minute charge for a session that never opened a page.
                logger.warning(
                    "Browserbase session payload carried no connectUrl; releasing it "
                    "and falling back to our own Chromium"
                )
                if isinstance(session_id, str) and session_id:
                    await _request_release(http, session_id)
                return None
            if not (isinstance(session_id, str) and session_id):
                # Usable browser, unusable id: we can capture but can never release it
                # by name, so it will bill to its TTL. Say so out loud.
                logger.warning(
                    "Browserbase session has no id; it cannot be released early and "
                    "will bill until its %ss timeout", _BROWSERBASE_SESSION_TTL_S,
                )
                session_id = None
            # The live view is fetched HERE, inside the same short-lived client, because
            # the URL is only useful while this session is alive.
            live_view = (
                await _fetch_live_view(http, session_id) if session_id else None
            )
        return BrowserSession(
            cdp_url=connect_url, live_view_url=live_view, session_id=session_id
        )
    except (httpx.HTTPError, ValueError, KeyError):
        logger.warning(
            "Browserbase session create failed; falling back to our own Chromium",
            exc_info=True,
        )
        return None


def _string_list(raw: Any) -> tuple[str, ...]:
    """The strings in a child-reported list, or ``()``. Never raises.

    Same discipline as :func:`_responses_from_report`: a field we cannot read is one
    lost observation, and losing it degrades the job link to the board's own listing
    page — the behaviour we already ship. It is never a reason to fail a capture that
    otherwise recorded the whole board.
    """
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in raw if isinstance(item, str) and item)


_ISLAND_SCOPES = ("served", "rendered")


def _islands_from_report(raw: Any) -> tuple[dict[str, Any], ...]:
    """The child's island rows, minus anything we cannot fully believe. Never raises.

    Same discipline as :func:`_responses_from_report`: an entry we cannot read is one
    lost observation, and losing it degrades to exactly today's behaviour. An unknown
    ``scope`` is DROPPED rather than defaulted — defaulting it to ``served`` would let an
    unreplayable island become a stored recipe, which is the one thing the split exists
    to prevent.
    """
    if not isinstance(raw, list):
        return ()
    out: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        scope, selector, body = (
            entry.get("scope"), entry.get("selector"), entry.get("body")
        )
        if scope not in _ISLAND_SCOPES:
            continue
        if not isinstance(selector, str) or not selector:
            continue
        if not isinstance(body, str) or not body:
            continue
        source = entry.get("source")
        out.append({
            "scope": scope,
            "selector": selector,
            "source": source if source in ("text", "attribute") else "text",
            "attribute": str(entry.get("attribute") or ""),
            "body": body,
        })
    return tuple(out)


def _responses_from_report(report: dict[str, Any]) -> list[CapturedResponse]:
    """Turn the child's raw ``responses`` into typed rows, skipping malformed entries.

    Skipping (rather than raising) is right HERE and only here: an entry we cannot read
    is one lost observation out of dozens, and the caller's own "no candidate survived"
    check is what turns a genuinely empty capture into a named-step refusal.
    """
    raw = report.get("responses")
    if not isinstance(raw, list):
        raise CaptureError("capture report has no 'responses' list")
    out: list[CapturedResponse] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        url = entry.get("url")
        body = entry.get("body")
        status = entry.get("status")
        if not isinstance(url, str) or not isinstance(body, str):
            continue
        if not isinstance(status, int) or isinstance(status, bool):
            continue
        headers = entry.get("request_headers")
        out.append(CapturedResponse(
            url=url,
            method=str(entry.get("method") or "GET").upper(),
            status=status,
            content_type=str(entry.get("content_type") or ""),
            request_headers=(
                {str(k): str(v) for k, v in headers.items()}
                if isinstance(headers, dict) else {}
            ),
            post_data=entry.get("post_data") if isinstance(entry.get("post_data"), str) else None,
            body=body,
            truncated=bool(entry.get("truncated")),
            # Falls back to the body we DID get, so a report from a child that predates
            # the field still reports a sane size rather than zero.
            body_bytes=(
                entry["bytes"]
                if isinstance(entry.get("bytes"), int)
                and not isinstance(entry.get("bytes"), bool)
                else len(body)
            ),
        ))
    return out


async def capture_board(
    url: str,
    *,
    run_subprocess: RunSubprocess | None = None,
    validate_url: UrlValidator | None = None,
    open_session: OpenSession | None = None,
    release_session: ReleaseSession | None = None,
    on_live_view: LiveViewFn | None = None,
    on_live_view_closed: LiveViewClosedFn | None = None,
    on_request: RequestFn | None = None,
) -> CaptureResult:
    """Open ``url`` once in a browser and return everything JSON it fetched.

    RAISES :class:`CaptureError`. ``run_subprocess`` / ``validate_url`` /
    ``open_session`` / ``release_session`` are injectable so the tests run at $0 against
    a canned report, a no-op guard and no Browserbase — the same seam
    ``run_browser_fetch`` uses.

    ``on_live_view`` is a CALLBACK, not a return value, and that is the whole point: the
    hosted view is worth something only WHILE the capture is running, and this function
    does not return for another 30-120 seconds. :attr:`CaptureResult.live_view_url`
    still carries it for the terminal record; the callback is what puts it on screen in
    time to be watched.

    ``on_live_view_closed`` is the OTHER half of that, and it is not optional bookkeeping
    — it is the fix for a live view that outlived its session on screen. It fires from
    the ``finally`` below, i.e. the instant the paid browser stops being watchable, which
    is always EARLIER than any step the checklist ticks afterwards. A caller that infers
    "the browser must still be open" from "step 1 is still active" is reading a signal
    that goes stale seconds before it changes; this one is exact.

    ``on_request`` is a callback for the same reason and settles the same argument about
    a different thing: :attr:`CaptureResult.responses` carries the whole recording, but
    it carries it 30-120 seconds after the first request landed. This fires as each one
    is recorded, which is what lets the progress panel show a network log filling up
    instead of a spinner followed by a finished list.
    """
    # SSRF on the pasted URL BEFORE anything spawns (invariant #4). OFF THE LOOP:
    # ``validate_public_url`` is sync and does a blocking ``getaddrinfo`` on a host a
    # stranger chose, and we share this process with the Procrastinate worker — a
    # blackholing resolver would otherwise stall every in-flight ATS fetch.
    # ``_DNS_EXECUTOR`` rather than ``asyncio.to_thread`` for the reason stated at that
    # constant: the loop's default pool is the one every outbound connection shares.
    # The seam IS ``url_guard.validate_public_url`` (raising ``UrlGuardError``, whose
    # reason codes are an API contract); the wrap into a refusal happens HERE so an
    # injected validator takes exactly the same path as the real one. The reason code is
    # quoted verbatim because the refusal string reaches the UI.
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(
            _DNS_EXECUTOR, validate_url or validate_public_url, url
        )
    except UrlGuardError as exc:
        raise CaptureError(
            f"URL {url!r} blocked by the SSRF guard ({exc.reason}): {exc}"
        ) from exc

    session = await (open_session or _open_browserbase_session)()
    release = release_session or _release_browserbase_session
    # EVERYTHING from here on is inside the try, so there is no statement between
    # "a paid browser exists" and "the finally that gives it back".
    try:
        plan: dict[str, Any] = {
            "entry_url": url,
            # THE HOST-PIN handed to the child: exactly the host we just validated, so
            # the child can refuse the navigation redirects Chromium would otherwise
            # take on its own. Sub-resource hosts are deliberately NOT pinned (the XHRs
            # are what we are here to record); their SSRF check happens on THIS side,
            # over the surviving candidates, before one can reach the LLM or a stored
            # recipe.
            "allowed_hosts": sorted({_hostname(url)} - {""}),
        }
        if session is not None:
            plan["cdp_url"] = session.cdp_url
            if session.live_view_url and on_live_view is not None:
                # BEFORE the child spawns — i.e. before the page is even opened. This
                # used to ride back on the RESULT, which meant the URL reached the
                # progress blob only once the capture was finished and the session
                # released: a dead frame, every time. Publishing here is what makes it
                # a live view rather than a screenshot of one.
                #
                # Guarded because the callback writes to the database. Narration must
                # never be able to fail a capture we can otherwise complete — the same
                # rule ``discover._publish`` follows one layer up.
                try:
                    await on_live_view(session.live_view_url)
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "live-view publish failed for %s (continuing)", url,
                        exc_info=True,
                    )

        async def _forward(event: dict[str, Any]) -> None:
            """One child event -> one ``on_request`` call. Guarded, like every other
            narration seam here: a callback that raises must not fail a capture we can
            otherwise complete (the rule ``on_live_view`` above follows, and
            ``discover._publish`` follows one layer up)."""
            if on_request is None or event.get("event") != "response":
                return
            try:
                await on_request({
                    "method": event.get("method"),
                    "url": event.get("url"),
                    "status": event.get("status"),
                    "bytes": event.get("bytes"),
                    "truncated": bool(event.get("truncated")),
                })
            except Exception:  # noqa: BLE001
                logger.warning(
                    "capture request publish failed for %s (continuing)", url,
                    exc_info=True,
                )

        report = await (run_subprocess or _subprocess_run)(plan, on_event=_forward)
        responses = _responses_from_report(report)
        final_url = report.get("final_url")
        if not isinstance(final_url, str) or not final_url:
            raise CaptureError("capture report has no final_url")
        logger.info(
            "capture: %s -> %s captured %d JSON xhr/fetch response(s)%s",
            url, final_url, len(responses),
            " via Browserbase" if session is not None else "",
        )
        return CaptureResult(
            final_url=final_url,
            page_title=str(report.get("page_title") or ""),
            responses=responses,
            live_view_url=session.live_view_url if session is not None else None,
            board_links=_string_list(report.get("board_links")),
            board_scripts=_string_list(report.get("board_scripts")),
            server_html=(
                report["server_html"]
                if isinstance(report.get("server_html"), str) else ""
            ),
            server_html_url=(
                report["server_html_url"]
                if isinstance(report.get("server_html_url"), str) else ""
            ),
            islands=_islands_from_report(report.get("islands")),
        )
    finally:
        # NOT in an ``except``: the paths that leak money are exactly the ones that
        # skip ``except`` clauses — the discovery task's 240s ``wait_for`` cancelling
        # this coroutine, and a ``CaptureError`` raised above. Same reasoning, and the
        # same shape, as ``_subprocess_run``'s unconditional ``_reap``.
        if session is not None:
            # RETRACT THE LIVE VIEW FIRST, THEN GIVE THE BROWSER BACK. By the time
            # control reaches here the thing the iframe was watching is already gone on
            # EVERY path: the child closes the browser before it exits (so the report
            # path arrives here microseconds after the CDP socket dropped), the timeout
            # path SIGKILLed it, and the cancellation path SIGKILLed it too. The release
            # POST below is billing bookkeeping, not the moment of death — so waiting
            # for it (up to 10s, longer than two of the UI's 4s polls) would leave the
            # user staring at Browserbase's "Debugging connection was closed" panel for
            # no reason. Announcing it first is honest and it is prompt.
            #
            # Guarded, and only when there was something to retract: the callback writes
            # to the database from inside a ``finally`` that may be unwinding a
            # cancellation, and an exception escaping here would replace the real
            # failure with a narration one — the same rule ``on_live_view`` above and
            # ``discover._publish`` one layer up already follow. ``except Exception``
            # deliberately does not catch the ``CancelledError`` that put us here.
            if session.live_view_url and on_live_view_closed is not None:
                try:
                    await on_live_view_closed()
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "live-view teardown publish failed for %s (continuing)", url,
                        exc_info=True,
                    )
            await release(session)
