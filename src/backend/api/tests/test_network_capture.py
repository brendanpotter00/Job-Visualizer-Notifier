"""E7 capture pivot — the agent-free parent of the capture subprocess. $0.

The Chromium child is FAKED (no browser, no DNS, no network). What these prove is
everything the parent alone is responsible for: the SSRF entry guard fires BEFORE a
browser can be spawned, the child is handed a host-pin and nothing else, a report we
cannot believe is a refusal rather than a partial capture, and — the one that costs
money if it regresses — Browserbase stays OFF unless it is explicitly opted into with
real credentials.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from api.config import settings
from api.services.capture import network_capture as nc
from api.services.capture.network_capture import (
    BrowserSession,
    CaptureError,
    _child_env,
    _parse_report,
    _responses_from_report,
    capture_board,
)
from api.services.url_guard import UrlGuardError

pytestmark = pytest.mark.asyncio

_FIXTURES = Path(__file__).parent / "fixtures" / "discovery"
_URL = "https://www.amazon.jobs/en/search"
_BACKEND = Path(__file__).resolve().parents[2]          # src/backend
_REPO_ROOT = _BACKEND.parents[1]
_SUBPROC_ENV = {**os.environ,
                "PYTHONPATH": os.pathsep.join([str(_REPO_ROOT), str(_BACKEND)])}


def _report(name: str = "amazon") -> dict[str, Any]:
    return json.loads((_FIXTURES / f"{name}_capture.json").read_text())


def _child(report: dict[str, Any], *, plans: list[dict] | None = None):
    async def _run(plan: dict[str, Any]) -> dict[str, Any]:
        if plans is not None:
            plans.append(plan)
        return report
    return _run


def _allow_all(url: str) -> None:
    return None


async def _no_session() -> BrowserSession | None:
    return None


async def test_capture_returns_the_childs_json_responses() -> None:
    result = await capture_board(
        _URL, run_subprocess=_child(_report()), validate_url=_allow_all,
        open_session=_no_session,
    )
    assert result.final_url == _URL
    assert len(result.responses) == 3
    assert result.responses[2].method == "GET"
    assert result.responses[2].request_headers["cookie"] == "session=abc123"
    assert result.live_view_url is None


async def test_blocked_url_refuses_before_a_browser_is_spawned() -> None:
    """SSRF entry half (invariant #4). A blocked URL must cost ZERO Chromium — provable
    only by counting spawns, which is why the fake records its plans."""
    plans: list[dict] = []

    def _blocked(url: str) -> None:
        raise UrlGuardError("private_address", "resolves to 10.0.0.5")

    with pytest.raises(CaptureError, match="private_address"):
        await capture_board(
            "https://internal.example/careers",
            run_subprocess=_child(_report(), plans=plans),
            validate_url=_blocked,
            open_session=_no_session,
        )
    assert plans == []


async def test_the_child_is_handed_a_host_pin_and_no_credentials() -> None:
    """The child navigates a URL a stranger pasted with ``--no-sandbox``. It gets the
    entry URL, the one host we validated, and nothing else — no API key, no plan field
    it could turn into a second target."""
    plans: list[dict] = []
    await capture_board(
        _URL, run_subprocess=_child(_report(), plans=plans), validate_url=_allow_all,
        open_session=_no_session,
    )
    (plan,) = plans
    assert plan == {"entry_url": _URL, "allowed_hosts": ["www.amazon.jobs"]}


async def test_a_browserbase_session_passes_only_its_cdp_url_through() -> None:
    """When the opt-in IS on, the PARENT creates the session (so the API key stays in
    this process) and the child receives only the connect URL — on stdin, never argv,
    because argv is visible in ``ps``."""
    plans: list[dict] = []

    async def _session() -> BrowserSession:
        return BrowserSession(
            cdp_url="wss://connect.browserbase.com/?sessionId=s1",
            live_view_url="https://browserbase.com/devtools/s1",
            session_id="s1",
        )

    result = await capture_board(
        _URL, run_subprocess=_child(_report(), plans=plans), validate_url=_allow_all,
        open_session=_session,
    )
    (plan,) = plans
    assert plan["cdp_url"] == "wss://connect.browserbase.com/?sessionId=s1"
    assert not any("API" in key.upper() for key in plan)
    assert result.live_view_url == "https://browserbase.com/devtools/s1"


async def test_browserbase_is_off_unless_explicitly_opted_into(monkeypatch) -> None:
    """Browserbase bills per browser-hour and our own Chromium reads a normal careers
    page fine, so the default must be OFF — and a half-configured deployment (flag on,
    no credentials) must DEGRADE to our own browser, never refuse a readable board.

    Asserted on the MECHANISM (no session-create was attempted), not on the return
    value, because ``is None`` cannot tell the two apart: with the opt-in check deleted
    this issues a real ``POST /v1/sessions``, the 401 lands in the ``httpx.HTTPError``
    swallow, and it returns the SAME ``None`` — so the money bug ships green and the
    suite quietly makes an outbound call. Counting attempts is the same trick
    ``test_blocked_url_refuses_before_a_browser_is_spawned`` uses for spawns."""
    attempts: list[str] = []

    class _NeverCalled:
        async def __aenter__(self) -> "_NeverCalled":
            return self

        async def __aexit__(self, *exc: object) -> bool:
            return False

        async def post(self, url: str, **kwargs: object) -> None:
            attempts.append(url)
            raise AssertionError(f"Browserbase must not be contacted: POST {url}")

        async def get(self, url: str, **kwargs: object) -> None:
            attempts.append(url)
            raise AssertionError(f"Browserbase must not be contacted: GET {url}")

    monkeypatch.setattr(settings, "capture_use_browserbase", False)
    monkeypatch.setattr(settings, "browserbase_api_key", "bb-key")
    monkeypatch.setattr(settings, "browserbase_project_id", "proj")
    assert await nc._open_browserbase_session(client_factory=_NeverCalled) is None
    assert attempts == []

    monkeypatch.setattr(settings, "capture_use_browserbase", True)
    monkeypatch.setattr(settings, "browserbase_api_key", None)
    assert await nc._open_browserbase_session(client_factory=_NeverCalled) is None
    assert attempts == []


async def test_a_report_without_a_final_url_refuses() -> None:
    report = {**_report(), "final_url": ""}
    with pytest.raises(CaptureError, match="final_url"):
        await capture_board(
            _URL, run_subprocess=_child(report), validate_url=_allow_all,
            open_session=_no_session,
        )


def test_a_report_without_responses_refuses() -> None:
    with pytest.raises(CaptureError, match="responses"):
        _responses_from_report({"final_url": _URL})


def test_malformed_response_entries_are_skipped_not_fatal() -> None:
    """One unreadable observation out of dozens is not a discovery failure; "no
    candidate survived" is the check that turns a genuinely empty capture into a
    named-step refusal, and it lives one layer up."""
    responses = _responses_from_report({
        "final_url": _URL,
        "responses": [
            "not-an-object",
            {"url": None, "body": "{}", "status": 200},
            {"url": "https://x.example/a", "body": "{}", "status": "200"},
            {"url": "https://x.example/b", "body": '{"ok":1}', "status": 200},
        ],
    })
    assert [r.url for r in responses] == ["https://x.example/b"]


def test_parse_report_takes_the_last_json_line() -> None:
    """Chromium is chatty on stdout; the report is the last JSON object that looks like
    one, exactly as the browser_fetch parent does it."""
    noise = "[0820/084213.1:INFO] some chromium chatter\n"
    report = json.dumps({"final_url": _URL, "responses": []})
    assert _parse_report(noise + report + "\n")["final_url"] == _URL
    with pytest.raises(CaptureError, match="no JSON report"):
        _parse_report(noise)


def test_child_env_is_an_allowlist_not_a_copy(monkeypatch) -> None:
    """``dict(os.environ)`` would inherit the worker's whole production credential set
    into every renderer process of a browser pointed at a stranger's URL."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@host/db")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")
    monkeypatch.setenv("BROWSERBASE_API_KEY", "bb-secret")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw")

    env = _child_env()
    assert "DATABASE_URL" not in env
    assert "ANTHROPIC_API_KEY" not in env
    assert "BROWSERBASE_API_KEY" not in env
    assert env["PLAYWRIGHT_BROWSERS_PATH"] == "/opt/pw"     # passes through by prefix
    assert env.get("PATH") == os.environ["PATH"]


def test_the_child_never_carries_half_a_body() -> None:
    """An oversize body is recorded EMPTY with ``truncated=True``, never cut in half.

    Half a JSON document parses as nothing, so a truncated body was dropped by the
    pre-filter exactly like a tracking ping — and the refusal then told the user "none
    of these returned a list of job postings" about the one request that did. The flag
    is what lets the parent say the true thing instead.

    Run in a SUBPROCESS on purpose: importing ``_capture_main`` would make
    ``playwright`` resident in the pytest process, and every later
    ``assert_no_agent_imports()`` in the suite would then raise.
    """
    code = (
        "import asyncio, json\n"
        "from api.services.capture._capture_main import _record\n"
        "class R:\n"
        "    def __init__(self, n):\n"
        "        self.resource_type='xhr'; self.url='https://b.example/api'\n"
        "        self.method='GET'; self.post_data=None; self.headers={}\n"
        "        self._n=n\n"
        "class Resp:\n"
        "    def __init__(self, n):\n"
        "        self.request=R(n); self.status=200\n"
        "        self.headers={'content-type':'application/json'}; self._n=n\n"
        "    async def text(self):\n"
        "        return json.dumps({'jobs': ['x'*10] * self._n})\n"
        "limits={'max_responses':40,'max_body_bytes':1000,'max_total_body_bytes':1500}\n"
        "out=[]\n"
        "asyncio.run(_record(Resp(60), out, limits))\n"       # ~850 chars: carried whole
        "asyncio.run(_record(Resp(500), out, limits))\n"      # over the per-body cap
        "asyncio.run(_record(Resp(60), out, limits))\n"       # over the aggregate budget
        "print(json.dumps([(e['truncated'], bool(e['body'])) for e in out]))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(_BACKEND), env=_SUBPROC_ENV,
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1]) == [
        [False, True],      # under both caps — the real body
        [True, False],      # over the per-body cap — flagged, nothing carried
        [True, False],      # over the aggregate budget — same
    ]


# The fake page both window tests drive. No browser, no network: ``_settle`` only ever
# calls ``wait_for_timeout`` and ``evaluate``, so a counter for the first and a switch
# for the second is the whole seam.
_FAKE_PAGE = (
    "import asyncio\n"
    "from api.services.capture._capture_main import _DEFAULT_SETTLE_MS, _settle\n"
    "class Page:\n"
    "    def __init__(self, scrollable):\n"
    "        self.waited = 0; self._scrollable = scrollable\n"
    "    async def wait_for_timeout(self, ms):\n"
    "        self.waited += ms\n"
    "    async def evaluate(self, script):\n"
    "        if not self._scrollable:\n"
    "            raise RuntimeError('scrollBy blocked')\n"
    "def window(scrollable):\n"
    "    page = Page(scrollable)\n"
    "    asyncio.run(_settle(page, _DEFAULT_SETTLE_MS))\n"
    "    return page.waited\n"
)


def _settle_window(script: str) -> str:
    """Run ``script`` against the fake page IN A SUBPROCESS and return its last line.

    Subprocess for the same reason as ``test_the_child_never_carries_half_a_body``:
    importing ``_capture_main`` makes ``playwright`` resident in the pytest process and
    every later ``assert_no_agent_imports()`` in the suite would then raise.
    """
    result = subprocess.run(
        [sys.executable, "-c", _FAKE_PAGE + script],
        cwd=str(_BACKEND), env=_SUBPROC_ENV,
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip().splitlines()[-1]


def test_the_observation_window_outlasts_a_slow_boards_jobs_xhr() -> None:
    """We watch the page for TWENTY-PLUS seconds, not the 8.4s we used to.

    The number is not decoration. Measured on
    ``atlassian.com/company/careers/all-jobs``, the jobs XHR
    (``/endpoint/careers/listings``, 268 postings) lands ~10.6s after ``goto`` returns
    on 10 of 11 runs. Under the old 6s + 2 x 1.2s budget the capture carried back 14
    consent/analytics pings and discovery refused the board for "none of these is a
    list of job postings" — our clock, reported as the board's fault. The 11th run,
    where the same feed arrived at 0.55s, was accepted, so the symptom was a board that
    looked flaky rather than a bug that looked like one.

    Asserted as a FLOOR with real margin rather than an exact total: what has to hold
    is "comfortably past 10.6s on a container slower than the laptop that measured it",
    not any particular arithmetic of passes x pause.
    """
    assert int(_settle_window("print(window(True))")) >= 20_000


def test_a_page_that_refuses_to_scroll_still_gets_the_whole_window() -> None:
    """A scroll fault stops SCROLLING. It must never cut the watch short.

    ``_settle`` used to ``break`` out of the loop when ``scrollBy`` raised, so a page
    that will not scroll (CSP, a navigation mid-scroll, a detached frame) silently lost
    every remaining pass — the same under-capture as a too-short window, and now worth
    18 of the 24 seconds rather than 2.4 of 8.4.
    """
    assert _settle_window("print(window(True) == window(False))") == "True"


def test_the_per_body_cap_clears_the_biggest_real_jobs_feed() -> None:
    """A whole jobs feed must fit in ONE body, and 2 MB did not.

    Same failure shape as the 8.4s window, from the other ceiling. Measured on
    ``binance.com/en/careers/job-openings``: its feed
    (``/bapi/career/jobs-lever/v0/postings/binance``, a Lever export — 14 departments,
    279 postings) is **2,775,685 bytes**. Over the old 2 MB cap it was recorded EMPTY,
    the pre-filter dropped it along with the tracking pings, and discovery refused the
    board for "none of the 40 JSON request(s) this page made is a list of job
    postings". A/B on one page load with the cap as the only variable: 2 MB refuses,
    4 MB accepts and reads the feed.

    Asserted as a FLOOR with margin rather than an exact value — what has to hold is
    "a 2.78 MB feed still fits, with room for a board slightly bigger", not any
    particular constant. The AGGREGATE is asserted as a ceiling in the same breath
    because it, not the per-body cap, is what bounds the worst case: raising what one
    body may cost must never raise what forty of them may cost.

    Subprocess for the same reason as the tests above: importing ``_capture_main``
    makes ``playwright`` resident in the pytest process and every later
    ``assert_no_agent_imports()`` in the suite would then raise.
    """
    result = subprocess.run(
        [sys.executable, "-c",
         "from api.services.capture._capture_main import ("
         "_MAX_BODY_BYTES, _MAX_TOTAL_BODY_BYTES)\n"
         "print(_MAX_BODY_BYTES, _MAX_TOTAL_BODY_BYTES)\n"],
        cwd=str(_BACKEND), env=_SUBPROC_ENV,
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    per_body, aggregate = (int(v) for v in result.stdout.strip().split()[-2:])

    assert per_body >= 3_500_000, (
        "the biggest real jobs feed measured is 2,775,685 bytes (binance.com); a cap "
        "at or below it records the feed empty and refuses the board for having none"
    )
    assert aggregate <= 16_000_000, (
        "the aggregate is what bounds the worst case — raising the per-body cap must "
        "not raise it"
    )
