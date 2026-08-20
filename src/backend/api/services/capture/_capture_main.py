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
# one request that did. 2 MB clears a realistic full jobs page (~500 KB for ~120
# postings with descriptions, measured) with headroom.
_MAX_BODY_BYTES = 2_000_000
# ...and the aggregate across every body, so raising the per-body cap cannot raise the
# worst case. One 2 MB jobs feed is fine; forty of them is a container.
_MAX_TOTAL_BODY_BYTES = 16_000_000
_SCROLL_PASSES = 2            # cheap lazy-load trigger; never an autonomous agent
_SCROLL_PAUSE_MS = 1_200
_DRAIN_TIMEOUT_S = 10.0       # how long in-flight body reads get before we close

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

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


async def _install_host_pin(context: Any, allowed_hosts: set[str]) -> None:
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


async def _record(response: Any, captured: list[dict[str, Any]], limits: dict[str, int]) -> None:
    """Record one response IFF it is a JSON XHR/fetch. Never raises out.

    Every failure mode here is a response we simply do not carry (a body already
    discarded by Chromium, a redirect with no body, a stream that errored). Losing one
    is not a discovery failure — the pre-filter downstream decides whether what we DID
    capture contains a jobs feed, and an empty capture becomes a named-step refusal
    rather than a crash.
    """
    try:
        if len(captured) >= limits["max_responses"]:
            return
        request = response.request
        if request.resource_type not in ("xhr", "fetch"):
            return
        content_type = str((response.headers or {}).get("content-type", ""))
        if "json" not in content_type.lower():
            return
        body = await response.text()
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
    except Exception:  # noqa: BLE001 - see the docstring; a lost response is not fatal
        return


async def _settle(page: Any, settle_ms: int) -> None:
    """Wait for first paint, then scroll a couple of screens to trigger lazy loads.

    Deterministic and cheap ON PURPOSE — this is the whole of "step 1" and it must not
    become an agent. A board whose jobs feed only fires after a click/filter is a board
    we refuse, not one we go hunting through.
    """
    await page.wait_for_timeout(settle_ms)
    for _ in range(_SCROLL_PASSES):
        try:
            await page.evaluate("() => window.scrollBy(0, window.innerHeight * 2)")
        except Exception:  # noqa: BLE001 - a page that refuses to scroll is still capturable
            break
        await page.wait_for_timeout(_SCROLL_PAUSE_MS)


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
            await _install_host_pin(context, allowed_hosts)
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
        finally:
            await browser.close()

    return {
        "final_url": final_url,
        "page_title": page_title,
        "responses": captured,
        "responses_total": len(captured),
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
