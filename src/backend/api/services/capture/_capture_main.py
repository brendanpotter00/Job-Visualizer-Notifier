"""SUBPROCESS ENTRY — the ONLY module on the DISCOVERY side that imports ``playwright``.

Opens a pasted careers URL in a browser ONCE, records every JSON XHR/fetch response
it makes, and prints them as a JSON report. That single recording is the whole raw
material of discovery: the deterministic pre-filter, the one Haiku pick+map call and
the acceptance replay all read it, and nothing downstream ever opens a browser again
for that board (the point of the capture pivot — the retired Stagehand tier re-read
the rendered DOM every 24h).

It is spawned by :func:`api.services.capture.network_capture.capture_board` via
``asyncio.create_subprocess_exec`` and is NEVER imported in-process, so ``playwright``
never lands in the shared Procrastinate worker's ``sys.modules`` and the replay path's
``assert_no_agent_imports`` guard stays satisfied even though the same worker hosts the
discovery task. That subprocess boundary is the reason this file exists at all; the AST
import guard proves nothing in-process reaches it.

**Our OWN Chromium by default** (``chromium.launch()``). Browserbase is used ONLY when
the parent hands us a ``cdp_url`` — it costs money per browser-hour, and the two things
it buys (stealth/residential IPs for bot-walled boards, and the hosted live-view embed
for the progress UX) are not needed to read a normal careers page.

THE CHILD IS DUMB, exactly as ``_browser_fetch_main`` is. It returns RAW captured
responses::

    {final_url, page_title, responses: [{url, method, status, content_type,
     request_headers, post_data, body, truncated}], responses_total, dropped}

It does NOT decide which response is the jobs feed, does not map fields and does not
know what a recipe is — the agent-free parent + the selector do all of that. The one
judgement it makes is the cheap resource-type/content-type filter that keeps a 40 MB
video body out of a pipe.

**No credentials are passed in argv.** A Browserbase ``cdp_url`` carries a session
token, so it arrives on **stdin** with the rest of the plan (stdin is not visible in
``ps``) and is never printed. In the default local-Chromium mode there is no secret at
all.

Duplicate-don't-import rule (same discipline as ``_browser_fetch_main``): this file's
first-party import surface is ZERO, so the child can never drag the worker's service
graph — and therefore the forbidden-import closure — behind Playwright.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from typing import Any
from urllib.parse import urljoin, urlsplit

# The ONLY playwright import on the discovery side, and it is in a child process.
from playwright.async_api import async_playwright

# Hard ceilings the child enforces on ITSELF, independent of the plan it is handed —
# a malformed plan must not be able to pin a Railway container or fill a pipe.
_DEFAULT_NAV_TIMEOUT_MS = 45_000
_DEFAULT_SETTLE_MS = 6_000
_MAX_RESPONSES = 40           # how many JSON bodies we are willing to carry back
# Per body. A body over this is NOT carried — it is recorded with an empty body and
# ``truncated: True`` so the parent can say so. Truncating it was worse than useless:
# a JSON document cut mid-object no longer parses, so the pre-filter dropped it and
# the refusal told the user "none of these returned a list of job postings" about the
# one request that did.
#
# It used to be 2 MB, and — exactly like the 8.4s window above — that budget SILENTLY
# LOST a board. Measured on ``binance.com/en/careers/job-openings``: its jobs feed
# (``/bapi/career/jobs-lever/v0/postings/binance``, a Lever export, 14 departments,
# 279 postings) is **2,775,685 bytes**, 39% over the old cap. It was recorded empty,
# the pre-filter dropped it with the tracking pings, and discovery refused the board
# for "none of the 40 JSON request(s) this page made is a list of job postings" — our
# limit, reported as the board's fault. A/B on one page load, cap the only variable:
# 2 MB refuses, 4 MB accepts and reads the feed. The two biggest real jobs feeds
# measured across 70 boards are Binance (2.78 MB) and Atlassian (1.85 MB), so 4 MB
# clears the worst known board by ~44%.
_MAX_BODY_BYTES = 4_000_000
# ...and the aggregate across every body, so raising the per-body cap cannot raise the
# worst case. THIS is the number that protects the container and the pipe, and it does
# not move: one 4 MB jobs feed is fine; forty of them is a container.
_MAX_TOTAL_BODY_BYTES = 16_000_000
# The rest of the observation window, spent scrolling a couple of screens at a time so
# a lazy-loaded feed is triggered as well as merely waited for. Together with
# ``_DEFAULT_SETTLE_MS`` this is the WHOLE of how long we watch: 6s + 12 x 1.5s = 24s.
#
# It used to be 6s + 2 x 1.2s = 8.4s, and that budget SILENTLY LOST boards. Measured on
# ``atlassian.com/company/careers/all-jobs``: its jobs XHR
# (``/endpoint/careers/listings``, 1.85 MB, 268 postings) lands ~10.6s after ``goto``
# returns on 10 of 11 runs — so the capture carried back 14 unrelated consent/analytics
# pings, the pre-filter found no jobs in them, and discovery refused the board saying
# "none of these is a list of job postings". We blamed the board for our own clock, and
# on the 11th run (the feed arrived at 0.55s) the very same board was accepted, which is
# what a too-short window looks like from the outside: a flaky board, not a bug.
#
# Fixed rather than adaptive ON PURPOSE. There is no signal that says "the feed is still
# coming": Playwright's ``networkidle`` fires ~1.7s into that page, and the stream goes
# completely silent for ~3s before the feed lands, so every quiet-period heuristic we
# could write stops early on exactly the board that needs the wait. The only honest
# answer is to spend a generous fixed budget, and 24s leaves the subprocess's own 120s
# cap (45s nav + 24s settle + 10s drain = 79s worst case) intact.
_SCROLL_PASSES = 12           # cheap lazy-load trigger; never an autonomous agent
_SCROLL_PAUSE_MS = 1_500
_DRAIN_TIMEOUT_S = 10.0       # how long in-flight body reads get before we close

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# --------------------------------------------------------------------------
# the board document's own LINKS — the raw material of job-link derivation
# --------------------------------------------------------------------------
#
# WHY THE RENDERED DOM AND NOT THE HOST-PIN BODY. ``_install_host_pin`` already fetches
# the navigation document (``route.fetch(max_redirects=0)``) and throws it away, and
# reusing that body looks free. It is the WRONG BYTES. That response is what the SERVER
# sent, and the boards this whole feature exists for render their job list on the
# client: measured 2026-08-30, ``atlassian.com/company/careers/all-jobs`` contains
# ``careers/details/`` **0 times** in the served document and 233 times in the DOM after
# the observation window. A harvest that reads the server body finds job links on
# exactly the boards that never needed help.
#
# ``page.content()`` is ONE round-trip, taken AFTER ``_settle`` has already returned, so
# it cannot shorten the watch or delay a body read. What crosses the pipe is hrefs, not
# a document — a careers page is routinely 1-2 MB of markup and none of it but the links
# has a reader.
#
# THE CHILD STILL DECIDES NOTHING. This is the same kind of mechanical filter as the
# resource-type/content-type test in ``_record``: it extracts strings and ranks nothing.
# Which of these links (if any) is a job link is a question the agent-free parent asks,
# against the records it captured, and then PROVES by fetching two real jobs.
_HREF_RE = re.compile(r"""\bhref\s*=\s*["']([^"'>\s]{1,400})["']""", re.IGNORECASE)
_SCRIPT_SRC_RE = re.compile(
    r"""<script\b[^>]*?\bsrc\s*=\s*["']([^"'>\s]{1,400})["']""", re.IGNORECASE
)
# Bounds, and they are pipe bounds rather than taste. A board with 2,000 postings on one
# page publishes 2,000 anchors; the derivation needs a handful of records to AGREE on a
# shape, so a few hundred is already far past the point of diminishing evidence.
_MAX_BOARD_LINKS = 600
# Scripts are a fallback source consulted only when a board publishes no job anchors at
# all, and the parent FETCHES them one at a time through its SSRF-guarded client. This
# is the list it chooses from, not the list it reads.
_MAX_BOARD_SCRIPTS = 20

# --------------------------------------------------------------------------
# sources 2 and 6 — JSON islands, and the SERVED document they may live in
# --------------------------------------------------------------------------
#
# THE SPLIT THAT MATTERS, AND IT IS NOT OPTIONAL. An embedded island is a RECORD source
# only if it is in the **served** document, because ``recipe_runner.extract_embedded_island``
# replays by issuing one plain GET and running a CSS selector over the SERVER's bytes.
# An island that only exists after hydration is not replayable by any transport we admit,
# so it may contribute ids and nothing else. Both documents are already in this process's
# memory — ``_install_host_pin`` fetches the served one and throws it away, and
# ``page.content()`` is already called for the link harvest — so carrying both costs
# ZERO extra requests and zero wall clock. The cost is pipe bytes.
#
# THE CHILD STILL DECIDES NOTHING. Same class of mechanical extraction as ``_HREF_RE``
# above: find <script> blocks with a JSON-ish type or a known id, keep the blob and the
# CSS selector that would re-find it, rank nothing. Which of them (if any) holds job
# postings is the agent-free parent's question, answered against the records it captured
# and then PROVEN by an acceptance replay.
_SCRIPT_BLOCK_RE = re.compile(r"(?is)<script\b([^>]*)>(.*?)</script\s*>")
_SCRIPT_ATTR_RE = re.compile(r"""(?i)([a-zA-Z_:][-\w:.]*)\s*=\s*["']([^"']*)["']""")
# Ids whose blob is JSON by convention even when the tag carries no type.
_ISLAND_IDS = ("__next_data__", "__nuxt_data__", "__universal_data_for_rehydration__")
# Bounds. Eight islands per document is already far past the point of diminishing
# evidence (a page has one __NEXT_DATA__ and a handful of ld+json blocks), and the
# aggregate is folded into the SAME ``_MAX_TOTAL_BODY_BYTES`` accounting the XHR bodies
# spend from, so raising the per-island cap cannot raise the worst case.
_MAX_ISLANDS_PER_DOC = 8
_MAX_ISLAND_BYTES = 2_000_000
_MAX_TOTAL_ISLAND_BYTES = 6_000_000
# The served document itself, carried whole for source 6. A careers page is routinely
# 1-2 MB of markup and this is the ONE document a stored ``http_html`` recipe will fetch
# every night, so it is the right bytes to reason about — the mirror of the finding that
# it is the WRONG bytes for link derivation (BIRTH-DEFECTS-PLAN §0), and the mirror is
# the point: the replay transport decides which bytes are the right evidence.
_MAX_SERVER_HTML_BYTES = 2_000_000

# Request headers we refuse to carry back out of the browser. ``cookie`` and the
# authorization family are session secrets that must never reach a stored recipe (a
# board that needs them belongs on the browser_fetch tier, which re-earns them
# same-origin every night); the rest are per-connection junk that would be wrong to
# replay. The PARENT filters again — this copy just keeps the secret out of the pipe.
_HEADER_DENYLIST = frozenset(
    {"cookie", "set-cookie", "authorization", "proxy-authorization", "host",
     "content-length", "connection", "accept-encoding", "referer"}
)


def _hostname(url: str) -> str:
    """Lowercased host of ``url``, or ``''``. Mirrors ``network_capture._hostname``."""
    return (urlsplit(url).hostname or "").lower()


def _redirect_target_host(response: Any) -> str:
    """Lowercased host of a 3xx ``Location``, or ``''`` for a non-redirect."""
    if not (300 <= int(response.status) < 400):
        return ""
    location = response.headers.get("location") or ""
    if not location:
        return ""
    return _hostname(urljoin(response.url, location))


def _script_attrs(raw: str) -> dict[str, str]:
    return {k.lower(): v for k, v in _SCRIPT_ATTR_RE.findall(raw or "")}


def _json_islands(markup: str, scope: str, budget: dict[str, int]) -> list[dict[str, Any]]:
    """Every JSON blob embedded in ``markup``, with the selector that re-finds it.

    ``scope`` is ``"served"`` or ``"rendered"`` and is the ONLY thing the parent needs to
    know the difference between a record source and an id set.

    THE SELECTOR MUST BE UNAMBIGUOUS or the island is not carried at all, because
    ``_run_embedded_island`` replays with ``soup.select_one`` and a selector matching two
    blocks would silently read whichever one happens to come first in tomorrow's markup.
    So: ``script#id`` when the id is unique in the document, ``script[type=...]`` when
    exactly one script carries that type, and nothing otherwise.

    The blob is JSON-parsed here purely to avoid pushing two megabytes of minified
    JavaScript down the pipe. That is a filter, not a judgement — exactly like the
    resource-type test in ``_record``.
    """
    blocks: list[tuple[dict[str, str], str]] = []
    for attrs_raw, blob in _SCRIPT_BLOCK_RE.findall(markup):
        blocks.append((_script_attrs(attrs_raw), blob.strip()))

    id_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    for attrs, _ in blocks:
        if attrs.get("id"):
            id_counts[attrs["id"]] = id_counts.get(attrs["id"], 0) + 1
        if attrs.get("type"):
            type_counts[attrs["type"]] = type_counts.get(attrs["type"], 0) + 1

    out: list[dict[str, Any]] = []
    for attrs, blob in blocks:
        if len(out) >= _MAX_ISLANDS_PER_DOC:
            break
        if not blob or len(blob) > _MAX_ISLAND_BYTES:
            continue
        if budget["islands"] + len(blob) > _MAX_TOTAL_ISLAND_BYTES:
            break
        element_id = attrs.get("id") or ""
        element_type = attrs.get("type") or ""
        json_ish = "json" in element_type.lower() or element_id.lower() in _ISLAND_IDS
        if not json_ish:
            continue
        if element_id and id_counts.get(element_id) == 1:
            selector = f"script#{element_id}"
        elif element_type and type_counts.get(element_type) == 1:
            selector = f'script[type="{element_type}"]'
        else:
            continue
        try:
            json.loads(blob, strict=False)
        except Exception:  # noqa: BLE001 - a blob that is not JSON is not an island
            continue
        budget["islands"] += len(blob)
        out.append({
            "scope": scope,
            "selector": selector,
            "source": "text",
            "body": blob,
        })
    return out


async def _install_host_pin(
    context: Any, allowed_hosts: set[str], served: dict[str, str] | None = None
) -> None:
    """Pin NAVIGATIONS to the hosts the parent SSRF-validated.

    Identical in shape and in reasoning to ``_browser_fetch_main._install_host_pin``
    (read the long note there): the parent validates the entry URL and that is where
    its guarantee stops, because Chromium then follows redirects ITSELF from inside
    the Railway container with no re-validation, and a plain ``route`` handler is
    **never re-entered for a redirect hop**. Asking Playwright to make the request
    first (``route.fetch(max_redirects=0)``) is what lets us read ``Location`` and
    abort BEFORE the hop is taken.

    Scope is navigations only. Sub-resources — including the very XHRs we are here to
    record — are passed straight through, deliberately: blocking them would defeat the
    capture, and the SSRF risk they carry is closed on the PARENT side instead, where
    ``validate_public_url`` runs over every surviving candidate URL before one can be
    shown to the LLM or written into a recipe.

    The cost of pinning navigations this tightly is that a careers page which 302s to a
    DIFFERENT host is aborted and the board REFUSES at the "opening the careers page"
    step. That is the safe direction and it is rarely reached: the add-flow's
    ``discover_ats`` already followed redirects under its own guard and hands us the
    FINAL url.
    """
    async def _handler(route: Any, request: Any) -> None:
        # FAIL CLOSED, and say why: an exception escaping a route handler leaves the
        # request unresolved forever (playwright never continues it), which surfaces as
        # an opaque navigation timeout instead of a legible refusal.
        try:
            if not request.is_navigation_request():
                await route.continue_()
                return
            if _hostname(request.url) not in allowed_hosts:
                print(f"host-pin: aborted navigation {request.url}", file=sys.stderr)
                await route.abort()
                return
            # INSPECT-ONLY, never ``fulfill`` — fulfilling the document from an
            # APIResponse makes every sub-resource of that document fail, which would
            # break exactly the client-rendered boards whose XHRs we are here to read.
            response = await route.fetch(max_redirects=0)
            # SOURCE 6, for free. This body was already fetched and already thrown away;
            # it is the exact bytes an ``http_html`` recipe re-fetches every night, and
            # it is where a SERVED (i.e. replayable) JSON island lives. Only the FIRST
            # navigation document is kept — that is the page the user pasted, and the
            # one a stored recipe would name.
            if served is not None and not served.get("html"):
                try:
                    body = await response.text()
                except Exception:  # noqa: BLE001 - the pin is what matters, not the copy
                    body = ""
                if body:
                    served["html"] = body[:_MAX_SERVER_HTML_BYTES]
                    served["url"] = request.url
            target = _redirect_target_host(response)
            if target and target not in allowed_hosts:
                print(
                    f"host-pin: aborted redirect {request.url} -> {target}",
                    file=sys.stderr,
                )
                await route.abort()
                return
            await route.continue_()
        except Exception as exc:  # noqa: BLE001 - see above
            print(f"host-pin: FAULT on {request.url}: {exc!r}", file=sys.stderr)
            try:
                await route.abort()
            except Exception:  # already resolved
                pass

    await context.route("**/*", _handler)


def _safe_headers(headers: dict[str, Any] | None) -> dict[str, str]:
    """The request headers worth carrying back, minus cookies/auth/per-connection junk."""
    return {
        str(k).lower(): str(v)
        for k, v in (headers or {}).items()
        if str(k).lower() not in _HEADER_DENYLIST and not str(k).startswith(":")
    }


def _is_json_shaped(body: str) -> bool:
    """Does this body LOOK like a JSON document, judged on the bytes?

    A first-character probe rather than a parse, deliberately: this runs on every
    XHR/fetch a board makes, some of which are megabytes, and the only question that
    has to be answered here is "could the parent's pre-filter possibly want this?".
    The parent already runs the real ``json.loads`` and drops anything that fails it.
    """
    head = body.lstrip()[:1]
    return head in ("{", "[")


async def _record(response: Any, captured: list[dict[str, Any]], limits: dict[str, int]) -> None:
    """Record one response IFF it is an XHR/fetch carrying a JSON document. Never raises out.

    Every failure mode here is a response we simply do not carry (a body already
    discarded by Chromium, a redirect with no body, a stream that errored). Losing one
    is not a discovery failure — the pre-filter downstream decides whether what we DID
    capture contains a jobs feed, and an empty capture becomes a named-step refusal
    rather than a crash.

    THE APERTURE IS THE BODY, NOT THE CONTENT-TYPE HEADER — and that is a fix, not a
    style choice. The test used to be ``"json" in content-type``, which SILENTLY LOST a
    whole board: measured 2026-08-30, ``metacareers.com/jobsearch/`` answers its
    ``POST /graphql`` with **``content-type: text/html``** over 186,957 bytes of pure
    JSON carrying 877 job records and a sibling call that declares ``job_count: 877``.
    The capture recorded **zero** requests and discovery told the user the page loads
    its jobs without any JSON request we could record. A board we can read perfectly
    well, refused over a header.

    WHY A BODY PROBE AND NOT "RECORD EVERY XHR/FETCH", which is the obvious wider fix:
    :data:`_MAX_RESPONSES` is 40 and it is spent in ARRIVAL ORDER. Measured on
    ``jobs.uber.com``, one page load produced **42** ``fetch`` responses of
    ``text/x-component`` (React Server Components) at ~163 KB each — enough, on their
    own, to fill the budget and evict a jobs feed that arrived after them. Nothing
    downstream can read RSC: :func:`~api.services.capture.request_selector.prefilter_candidates`
    keeps only what ``json.loads`` accepts. So the aperture is widened to exactly what
    the pre-filter can use, which recovers Meta and cannot crowd anything out.

    The old content-type test is kept as an OR, so this is a strict widening: a
    ``application/json`` response whose body is malformed is still recorded, and still
    reported honestly, exactly as it is today.
    """
    try:
        if len(captured) >= limits["max_responses"]:
            return
        request = response.request
        if request.resource_type not in ("xhr", "fetch"):
            return
        content_type = str((response.headers or {}).get("content-type", ""))
        body = await response.text()
        if "json" not in content_type.lower() and not _is_json_shaped(body):
            return
        # ALL OR NOTHING. Half a JSON document is not "the shape" — it does not parse,
        # so the parent's pre-filter discards it exactly like a tracking ping and the
        # board's own jobs feed disappears from a refusal that then blames the board.
        # Carrying the flag with an empty body is what lets the parent say the true
        # thing ("larger than we can record") instead of the false one.
        used = sum(len(entry["body"]) for entry in captured)
        oversize = (
            len(body) > limits["max_body_bytes"]
            or used + len(body) > limits["max_total_body_bytes"]
        )
        captured.append({
            "url": request.url,
            "method": request.method,
            "status": int(response.status),
            "content_type": content_type,
            "request_headers": _safe_headers(request.headers),
            "post_data": request.post_data,
            "body": "" if oversize else body,
            "truncated": oversize,
        })
        _emit_event({
            "event": "response",
            "method": request.method,
            "url": request.url,
            "status": int(response.status),
            "bytes": len(body),
            "truncated": oversize,
        })
    except Exception:  # noqa: BLE001 - see the docstring; a lost response is not fatal
        return


def _emit_event(event: dict[str, Any]) -> None:
    """Announce one recorded response on stdout, NOW, as a single JSON line.

    THE STREAMING HALF of the discovery UX: without it the parent learns what this
    browser saw only when the process exits, which on a slow board is 30-80 seconds
    after the first request landed — so the user's "here is what we are doing" panel
    would fill in one lump at the end and narrate nothing.

    STDOUT, not stderr, because stdout is already the data channel: the parent's
    ``_parse_report`` scans it in reverse for the LAST line carrying both ``responses``
    and ``final_url``, and an event line carries neither. Putting these on stderr would
    have polluted the one thing stderr is for here — the ``rc != 0`` failure text the
    parent quotes back into a refusal.

    NEVER RAISES and never blocks the capture: a broken pipe (a parent that gave up) or
    an unserializable field must cost the narration, never the recording. The body
    itself is deliberately NOT in the event — 4 MB per response down a pipe we are
    writing from inside a response handler is how a capture becomes a stall.
    """
    try:
        sys.stdout.write(json.dumps(event) + "\n")
        sys.stdout.flush()
    except Exception:  # noqa: BLE001 - narration must never fail a capture
        return


async def _settle(page: Any, settle_ms: int) -> None:
    """Watch the page for the whole observation window, scrolling as we go.

    Deterministic and cheap ON PURPOSE — this is the whole of "step 1" and it must not
    become an agent. A board whose jobs feed only fires after a click/filter is a board
    we refuse, not one we go hunting through.

    WAITING and SCROLLING are separate concerns and the wait is the load-bearing half.
    A failed ``scrollBy`` used to ``break``, which threw away every remaining pass —
    i.e. a page that will not scroll (CSP, a navigation mid-scroll, a detached frame)
    silently got an 8.4s window cut back to 6s. That is the same failure mode as a
    too-short window: a board refused for "none of these is a list of job postings"
    when the feed was simply still in flight. Losing the scroll is survivable; losing
    the watch is not, so a scroll fault only stops SCROLLING.
    """
    await page.wait_for_timeout(settle_ms)
    scrollable = True
    for _ in range(_SCROLL_PASSES):
        if scrollable:
            try:
                await page.evaluate("() => window.scrollBy(0, window.innerHeight * 2)")
            except Exception:  # noqa: BLE001 - stop scrolling, NEVER stop watching
                scrollable = False
        await page.wait_for_timeout(_SCROLL_PAUSE_MS)


def _document_links(html: str) -> tuple[list[str], list[str]]:
    """``(hrefs, script srcs)`` from one rendered document, deduped, order preserved.

    Order is first-seen ON PURPOSE: a page's own navigation comes before its list, so a
    truncated harvest keeps the chrome and loses the tail of the postings — which is the
    harmless direction, because the derivation needs SEVERAL postings to agree and a few
    hundred is already far more than enough.
    """
    def _unique(pattern: "re.Pattern[str]", limit: int) -> list[str]:
        seen: dict[str, None] = {}
        for match in pattern.finditer(html):
            value = match.group(1).strip()
            if value and value not in seen:
                seen[value] = None
                if len(seen) >= limit:
                    break
        return list(seen)

    return _unique(_HREF_RE, _MAX_BOARD_LINKS), _unique(_SCRIPT_SRC_RE, _MAX_BOARD_SCRIPTS)


async def run_capture(plan: dict[str, Any]) -> dict[str, Any]:
    """Open ``entry_url``, record its JSON XHR/fetch traffic, return the raw report."""
    entry_url = plan["entry_url"]
    nav_timeout_ms = int(plan.get("nav_timeout_ms") or _DEFAULT_NAV_TIMEOUT_MS)
    settle_ms = int(plan.get("settle_ms") or _DEFAULT_SETTLE_MS)
    cdp_url = plan.get("cdp_url") or None
    limits = {
        "max_responses": int(plan.get("max_responses") or _MAX_RESPONSES),
        "max_body_bytes": int(plan.get("max_body_bytes") or _MAX_BODY_BYTES),
        "max_total_body_bytes": int(
            plan.get("max_total_body_bytes") or _MAX_TOTAL_BODY_BYTES
        ),
    }
    # Defence in depth against a plan that lost the key: an EMPTY allowlist pins
    # everything shut rather than opening everything up, so a bug here is a refused
    # discovery, never a silently unpinned browser.
    allowed_hosts = {str(h).lower() for h in plan.get("allowed_hosts") or []}

    captured: list[dict[str, Any]] = []
    pending: list[asyncio.Task[None]] = []
    # The served navigation document, filled in from inside the host pin.
    served: dict[str, str] = {}
    async with async_playwright() as pw:
        if cdp_url:
            # Browserbase (or any CDP endpoint the parent chose). Opt-in only.
            browser = await pw.chromium.connect_over_cdp(cdp_url)
        else:
            browser = await pw.chromium.launch(
                headless=True,
                # Same args the repo's other Playwright scrapers use: --no-sandbox is
                # required inside the Railway container, and the automation flag keeps
                # a bot-sniffing board from serving us a different page than a human.
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
        try:
            if cdp_url and browser.contexts:
                # A CDP-attached remote browser already owns its context; making a new
                # one there is both wasteful and (on Browserbase) unsupported.
                context = browser.contexts[0]
            else:
                context = await browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    locale="en-US",
                    user_agent=_USER_AGENT,
                )
            # BEFORE the first navigation — a pin installed after ``goto`` would miss
            # the one hop that matters.
            await _install_host_pin(context, allowed_hosts, served)
            page = context.pages[0] if context.pages else await context.new_page()
            page.on(
                "response",
                lambda response: pending.append(
                    asyncio.ensure_future(_record(response, captured, limits))
                ),
            )
            await page.goto(entry_url, wait_until="domcontentloaded", timeout=nav_timeout_ms)
            await _settle(page, settle_ms)
            # DRAIN before closing. ``response.text()`` is itself a round-trip to the
            # browser, so a handler still in flight when ``browser.close()`` runs loses
            # its body — and on a slow board the LAST XHR is often the jobs feed, which
            # would turn a capturable board into a "no jobs feed found" refusal.
            if pending:
                await asyncio.wait(pending, timeout=_DRAIN_TIMEOUT_S)
            final_url = page.url
            try:
                page_title = await page.title()
            except Exception:  # noqa: BLE001 - a title is nice-to-have, never load-bearing
                page_title = ""
            # THE LINKS, read once, last, and never at the cost of the recording. A page
            # that will not hand us its DOM (detached frame, navigation mid-read) simply
            # publishes no job links, which downgrades the job link to the board's own
            # listing page — the outcome we already ship today.
            island_budget = {"islands": 0}
            islands = _json_islands(served.get("html", ""), "served", island_budget)
            try:
                rendered = await page.content()
            except Exception:  # noqa: BLE001 - see above; links are never load-bearing
                rendered = ""
            board_links, board_scripts = _document_links(rendered)
            islands += _json_islands(rendered, "rendered", island_budget)
        finally:
            await browser.close()

    return {
        "final_url": final_url,
        "page_title": page_title,
        "responses": captured,
        "responses_total": len(captured),
        "board_links": board_links,
        "board_scripts": board_scripts,
        # SOURCE 6 — the bytes an ``http_html`` replay re-fetches every night, and the
        # document a SERVED island's selector is resolved against.
        "server_html": served.get("html", ""),
        "server_html_url": served.get("url", ""),
        # SOURCES 2a + 2b, told apart by ``scope`` and by nothing else.
        "islands": islands,
    }


def main() -> None:
    raw = sys.stdin.read()
    try:
        plan = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"invalid plan JSON on stdin: {exc}", file=sys.stderr)
        sys.exit(2)
    try:
        report = asyncio.run(run_capture(plan))
    except Exception as exc:  # noqa: BLE001 - surface as rc!=0; the parent REFUSES
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
    # The report is the SOLE stdout payload; the parent parses the last JSON line
    # (Playwright/Chromium may print stray lines of its own).
    sys.stdout.write("\n" + json.dumps(report) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
