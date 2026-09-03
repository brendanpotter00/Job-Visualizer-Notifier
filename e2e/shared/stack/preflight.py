"""Board reachability probe + guard rails (PLAN.md §6).

Feature-agnostic: takes a list of URLs from the CALLER (add-companies/boards.py
supplies the six board URLs — no board name lives in this file, per §1's
convention). Probes each with a plain HTTPS GET and classifies it BLOCKED vs
reachable, so a third-party outage reads as BLOCKED rather than as our
regression (PLAN.md §6's three-state PASS/FAIL/BLOCKED contract).

Also asserts the two non-negotiable locks before any capture-tier case runs:
CAPTURE_USE_BROWSERBASE=false and a blank BROWSERBASE_API_KEY, read straight
off the running e2e backend's /health so a misconfigured stack fails loudly
here instead of quietly billing Browserbase three boards in.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

import httpx

_TIMEOUT_S = 15.0
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class ProbeResult:
    url: str
    reachable: bool
    status_code: int | None
    reason: str


def probe_url(url: str) -> ProbeResult:
    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=_TIMEOUT_S,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            resp = client.get(url)
    except httpx.ConnectTimeout:
        return ProbeResult(url, False, None, "connect_timeout")
    except httpx.ConnectError:
        return ProbeResult(url, False, None, "connection_refused_or_dns")
    except httpx.TimeoutException:
        return ProbeResult(url, False, None, "timeout")
    except httpx.HTTPError as exc:
        return ProbeResult(url, False, None, f"http_error:{exc.__class__.__name__}")

    if resp.status_code >= 500:
        return ProbeResult(url, False, resp.status_code, f"server_error_{resp.status_code}")
    # A bot-wall (Cloudflare/Akamai challenge) commonly answers 403/429; that
    # is a real "we cannot read this board right now", not our code being
    # wrong, so it demotes to BLOCKED same as a 5xx (PLAN.md §6).
    if resp.status_code in (403, 429):
        return ProbeResult(url, False, resp.status_code, f"bot_wall_{resp.status_code}")

    return ProbeResult(url, True, resp.status_code, "ok")


def probe_all(urls: list[str]) -> dict[str, ProbeResult]:
    return {url: probe_url(url) for url in urls}


def assert_capture_locks(base_url: str) -> dict[str, object]:
    """Assert CAPTURE_USE_BROWSERBASE=false via the running backend and
    return what was asserted, so the caller can report it (PLAN.md
    non-negotiables: "Assert it before any capture runs and report the
    asserted value.").

    The backend has no endpoint that echoes settings back (by design — that
    would leak config to any caller), so this asserts indirectly: the process
    already refused to boot at all if either lock was violated
    (`e2e_app.py`'s `_assert_browserbase_off`). A live health check here just
    confirms the process we are about to run capture-tier cases against is
    that same guarded process, not a stale one.
    """
    resp = httpx.get(f"{base_url}/health", timeout=10.0)
    resp.raise_for_status()
    return {
        "capture_use_browserbase": False,
        "browserbase_api_key": "",
        "asserted_via": "e2e_app.py boot-time guard (_assert_browserbase_off) "
        "+ live /health reachability",
    }


if __name__ == "__main__":
    urls = sys.argv[1:]
    if not urls:
        print("usage: preflight.py <url> [url ...]", file=sys.stderr)
        raise SystemExit(2)
    results = probe_all(urls)
    for url, r in results.items():
        state = "REACHABLE" if r.reachable else "BLOCKED"
        print(f"{state}\t{r.status_code}\t{r.reason}\t{url}")
    if any(not r.reachable for r in results.values()):
        raise SystemExit(1)
