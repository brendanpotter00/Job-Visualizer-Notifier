"""SUBPROCESS ENTRY — the ONLY module on the replay side that imports ``playwright``.

Navigates OUR OWN headless Chromium to a board's ``origin_url`` and re-issues the
board's captured jobs request with ``fetch()`` from inside that page, so the request
carries the origin, the cookies and whatever same-origin check the board applies.
That is the whole trick: TikTok's ``search/job/posts`` is a deterministic public POST
that 400s from plain ``httpx`` and 200s from its own origin. No LLM, no DOM parsing,
no agent — the same recipe, issued from a different place.

It is spawned by :func:`api.services.browser_fetch.runner.run_browser_fetch` via
``asyncio.create_subprocess_exec`` and is NEVER imported in-process, so ``playwright``
never lands in the shared Procrastinate worker's ``sys.modules`` and the replay path's
``assert_no_agent_imports`` guard stays satisfied. That subprocess boundary is the
reason this file exists at all; the AST import guard proves nothing reaches it.

THE CHILD IS DUMB (plan DECISION D3). It returns RAW response bodies::

    {pages: [{status, text, headers}], pages_fetched, terminated_cleanly, cap_hit}

It does NOT map fields, dedupe, judge completeness or build evidence — the agent-free
parent does all of that with the SAME ``recipe_runner`` machinery the httpx tier uses.
The ONE judgement it makes is when to stop paginating, which needs a record COUNT at
``records_path``; that is a pure JSON dig, reimplemented locally below.

**No credentials are passed to this process.** Unlike the Browserbase/Stagehand child,
this one drives a local Chromium: there is no API key to leak, and it must stay that
way — if this ever needs a secret, pass it through the child ENV, never argv.

Duplicate-don't-import rule (same discipline as ``browser_agent/_stagehand_main``):
this file's first-party import surface is ZERO. ``_dig`` and the query merge are
re-implemented rather than imported so the child can never drag the worker's service
graph — and therefore the forbidden-import closure — behind Playwright.
"""

from __future__ import annotations

import json
import sys
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

# The ONLY playwright import in the backend's replay path, and it is in a child process.
from playwright.sync_api import sync_playwright

# Hard ceilings the child enforces on ITSELF, independent of the plan it is handed.
# The parent re-asserts the page bound on read; these keep a malformed plan from
# pinning a Railway container regardless.
_MAX_PAGES_CEILING = 25
_DEFAULT_NAV_TIMEOUT_MS = 45_000
_DEFAULT_SETTLE_MS = 2_500
_DEFAULT_FETCH_TIMEOUT_MS = 30_000

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# The in-page request. ``credentials: 'same-origin'`` is load-bearing — an
# origin-gated board is exactly the case this tier exists for, and a cross-origin
# fetch without the page's cookies would 400 the same way plain httpx does.
# Response headers come back lowercased by the Headers iterator; the parent's
# ``header`` oracle lowercases both sides, so that is fine. NOTE they are readable
# only for a same-origin response or one the board CORS-exposes — a header oracle on
# a cross-origin endpoint will legitimately find nothing and FAIL loudly.
_FETCH_JS = """
async ({url, method, headers, body, timeoutMs}) => {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    // redirect:'error' is the HOST-PIN for this request. Chromium follows a 302
    // itself, and context.route() is NOT re-entered for a redirect hop (measured),
    // so 'follow' would let a board launder our fetch onto an internal address and
    // hand us its body as if it were jobs. 'error' rejects instead -> the child
    // exits non-zero -> the parent raises -> FAILED run -> nothing closes.
    const init = {method: method, headers: headers, credentials: 'same-origin',
                  redirect: 'error', signal: controller.signal};
    if (method === 'POST') { init.body = JSON.stringify(body); }
    const r = await fetch(url, init);
    const text = await r.text();
    return {status: r.status, text: text,
            headers: Object.fromEntries(r.headers.entries())};
  } finally {
    clearTimeout(timer);
  }
}
"""


def _dig(payload: Any, path: str) -> Any:
    """``recipe_schema.dig``, re-implemented locally (see the duplicate-don't-import
    rule above). Returns ``None`` instead of raising — the child only uses it to
    count records for its stop condition; the PARENT is what turns an unresolvable
    ``records_path`` into a FAILED run."""
    if not path:
        return payload
    current = payload
    for segment in path.split("."):
        if isinstance(current, list):
            try:
                index = int(segment)
            except ValueError:
                return None
            if index >= len(current):
                return None
            current = current[index]
        elif isinstance(current, dict):
            if segment not in current:
                return None
            current = current[segment]
        else:
            return None
    return current


def _count_records(text: str, records_path: str) -> int | None:
    """How many records this page carried, or ``None`` when that cannot be known
    (non-JSON body / path missing / not a list). ``None`` STOPS the loop: the parent
    will raise on the same page, and paging on into an unparseable board would just
    burn browser time before the same failure."""
    try:
        payload = json.loads(text, strict=False)
    except Exception:  # noqa: BLE001 - the parent raises with the real diagnosis
        return None
    records = _dig(payload, records_path)
    return len(records) if isinstance(records, list) else None


def _merge_query(url: str, params: dict[str, Any]) -> str:
    """MERGE ``params`` into the URL's EXISTING query, replacing only those keys.

    Mirrors ``httpx.URL.copy_merge_params``, which ``recipe_runner._request`` uses for
    exactly the reason spelled out there: replacing the whole query string would drop
    every captured filter and silently turn a scoped board into the global one. The
    two transports must page identically or the same recipe means two different things.
    """
    parts = urlsplit(url)
    existing = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                if k not in params]
    existing.extend((k, str(v)) for k, v in params.items())
    return urlunsplit(parts._replace(query=urlencode(existing)))


def _hostname(url: str) -> str:
    """Lowercased host of ``url``, or ``''``. Mirrors ``runner._hostname``."""
    return (urlsplit(url).hostname or "").lower()


def _redirect_target_host(response: Any) -> str:
    """Lowercased host of a 3xx ``Location``, or ``''`` for a non-redirect."""
    if not (300 <= int(response.status) < 400):
        return ""
    location = response.headers.get("location") or ""
    if not location:
        return ""
    return _hostname(urljoin(response.url, location))


def _install_host_pin(context: Any, allowed_hosts: set[str]) -> None:
    """Pin NAVIGATIONS to the hosts the parent SSRF-validated.

    The parent validates ``origin_url`` and the fetch URL before we are spawned, and
    that is where its guarantee stops: Chromium then follows redirects ITSELF, from
    inside the Railway container, with no re-validation. A board that 302s its
    careers page to ``http://169.254.169.254/…`` gets that request issued from inside
    our network.

    The obvious fix does NOT work, and this is measured, not assumed: a plain
    ``context.route`` handler that inspects ``request.url`` is **never re-entered for
    a redirect hop** — the handler sees only the first request, Chromium follows the
    302 internally, and the internal host is reached anyway. What does work is asking
    PLAYWRIGHT to make the request first: ``route.fetch(max_redirects=0)`` returns the
    3xx itself, so we can read ``Location`` and abort BEFORE Chromium ever takes the
    hop. We then ``continue_()`` rather than ``fulfill()`` — see the note at the call.

    Scope is deliberately NARROW — navigations only:

    * a navigation is the one request whose redirect we must own, and it carries no
      board signing, so performing it through Playwright cannot break the tier; and
    * every other request (the board's own CDN images, fonts, scripts) is passed
      straight through with ``continue_()``, because routing those through Playwright
      would change the first-paint settle this tier depends on for no security gain —
      the recipe does not read them.

    The recipe's OWN fetch is pinned separately and more strongly, by
    ``redirect: 'error'`` in :data:`_FETCH_JS` — that one must keep running inside the
    page to stay origin-signed, so it is the request, not the router, that refuses.
    """
    def _handler(route: Any, request: Any) -> None:
        # FAIL CLOSED, and say why. An exception escaping a route handler does not
        # merely skip the pin — playwright never resolves the route, the request
        # hangs, and the run dies with an opaque error. Aborting on an unexpected
        # fault keeps the invariant while making the cause greppable in stderr,
        # which the parent already surfaces in its RecipeExecutionError.
        try:
            if not request.is_navigation_request():
                route.continue_()
                return
            if _hostname(request.url) not in allowed_hosts:
                print(f"host-pin: aborted navigation {request.url}", file=sys.stderr)
                route.abort()
                return
            # INSPECT-ONLY, and never ``fulfill``. Fulfilling the document from an
            # APIResponse makes every sub-resource of that document fail with
            # ``net::ERR_FAILED`` (measured: the board's own CDN image stops
            # loading), which would break exactly the client-rendered boards this
            # tier exists to read. So we use ``route.fetch`` purely to LOOK at the
            # redirect, then hand the request back to Chromium untouched. The cost
            # is that a clean navigation is fetched twice — an idempotent GET on a
            # careers page, which is cheap next to the Chromium launch it precedes.
            response = route.fetch(max_redirects=0)
            target = _redirect_target_host(response)
            if target and target not in allowed_hosts:
                print(
                    f"host-pin: aborted redirect {request.url} -> {target}",
                    file=sys.stderr,
                )
                route.abort()
                return
            route.continue_()
        except Exception as exc:                       # noqa: BLE001 - see above
            print(f"host-pin: FAULT on {request.url}: {exc!r}", file=sys.stderr)
            try:
                route.abort()
            except Exception:                          # already resolved
                pass

    context.route("**/*", _handler)


def _effective_max_pages(plan: dict[str, Any]) -> int:
    pagination = plan.get("pagination")
    if not isinstance(pagination, dict):
        return 1
    declared = pagination.get("max_pages")
    if not isinstance(declared, int) or isinstance(declared, bool) or declared < 1:
        return 1
    return min(declared, _MAX_PAGES_CEILING)


def _fetch_page(page: Any, plan: dict[str, Any], params: dict[str, Any] | None) -> dict[str, Any]:
    """One in-page ``fetch``. GET merges the cursor into the query, POST into the body
    — the same split ``recipe_runner._request`` makes."""
    method = plan.get("method", "GET")
    url = plan["url"]
    body = dict(plan.get("body") or {})
    if params:
        if method == "POST":
            body.update(params)
        else:
            url = _merge_query(url, params)
    result = page.evaluate(
        _FETCH_JS,
        {
            "url": url,
            "method": method,
            "headers": dict(plan.get("headers") or {}),
            "body": body,
            "timeoutMs": int(plan.get("fetch_timeout_ms") or _DEFAULT_FETCH_TIMEOUT_MS),
        },
    )
    return {
        "status": int(result.get("status") or 0),
        "text": str(result.get("text") or ""),
        "headers": {str(k): str(v) for k, v in (result.get("headers") or {}).items()},
    }


def _sweep(page: Any, plan: dict[str, Any]) -> dict[str, Any]:
    """Run the (optionally paginated) capture and return the raw report.

    The loop is a deliberate transcription of ``recipe_runner._sweep_offset_page``:
    window-cap check BEFORE the request, a short page is the clean terminus, and
    running the page budget out with a still-full page is NOT clean (the parent turns
    that into ``terminated_cleanly=False`` → UNVERIFIED → nothing closes).
    """
    pagination = plan.get("pagination")
    records_path = plan.get("records_path", "")
    if not isinstance(pagination, dict):
        response = _fetch_page(page, plan, None)
        return {"pages": [response], "pages_fetched": 1,
                "terminated_cleanly": True, "cap_hit": False}

    style = pagination["style"]                  # "offset" | "page"
    param = pagination["param"]
    page_size = int(pagination["page_size"])
    max_pages = _effective_max_pages(plan)
    window_cap = pagination.get("window_cap")
    cursor = 0 if style == "offset" else int(pagination.get("start_page", 1))

    pages: list[dict[str, Any]] = []
    cap_hit = False
    ended_short = False
    while len(pages) < max_pages:
        if style == "offset" and window_cap is not None and cursor + page_size > int(window_cap):
            cap_hit = True
            break
        response = _fetch_page(page, plan, {param: cursor})
        pages.append(response)
        if not (200 <= response["status"] < 300):
            break                                # the parent RAISES on this page
        count = _count_records(response["text"], records_path)
        if count is None:
            break                                # unreadable → the parent RAISES
        if count < page_size:
            ended_short = True
            break
        cursor += page_size if style == "offset" else 1

    return {"pages": pages, "pages_fetched": len(pages),
            "terminated_cleanly": ended_short, "cap_hit": cap_hit}


def run_capture(plan: dict[str, Any]) -> dict[str, Any]:
    """Launch Chromium, land on ``origin_url``, run the sweep, return the report."""
    origin_url = plan["origin_url"]
    nav_timeout_ms = int(plan.get("nav_timeout_ms") or _DEFAULT_NAV_TIMEOUT_MS)
    settle_ms = int(plan.get("settle_ms") or _DEFAULT_SETTLE_MS)
    # Defence in depth against a plan that lost the key: an EMPTY allowlist pins
    # everything shut rather than opening everything up, so a bug here is a FAILED
    # run, never a silently unpinned browser.
    allowed_hosts = {str(h).lower() for h in plan.get("allowed_hosts") or []}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            # Same args the repo's other Playwright scrapers use: --no-sandbox is
            # required inside the Railway container, and the automation flag keeps a
            # bot-sniffing board from serving us a different page than a human sees.
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        try:
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
                user_agent=_USER_AGENT,
            )
            # BEFORE the first navigation — a pin installed after ``goto`` would
            # miss the one hop that matters.
            _install_host_pin(context, allowed_hosts)
            page = context.new_page()
            page.goto(origin_url, wait_until="domcontentloaded", timeout=nav_timeout_ms)
            # Settle on-origin before fetching: a client-rendered careers SPA sets the
            # cookies / storage its own API calls depend on during first paint, and
            # firing the capture too early gets the same 400 plain httpx would.
            page.wait_for_timeout(settle_ms)
            return _sweep(page, plan)
        finally:
            browser.close()


def main() -> None:
    raw = sys.stdin.read()
    try:
        plan = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"invalid plan JSON on stdin: {exc}", file=sys.stderr)
        sys.exit(2)
    try:
        report = run_capture(plan)
    except Exception as exc:  # noqa: BLE001 - surface as rc!=0; the parent RAISES → FAILED
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
    # The report is the SOLE stdout payload; the parent parses the last JSON line
    # (Playwright/Chromium may print stray lines of its own).
    sys.stdout.write("\n" + json.dumps(report) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
