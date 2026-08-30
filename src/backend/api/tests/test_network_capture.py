"""E7 capture pivot — the agent-free parent of the capture subprocess. $0.

The Chromium child is FAKED (no browser, no DNS, no network). What these prove is
everything the parent alone is responsible for: the SSRF entry guard fires BEFORE a
browser can be spawned, the child is handed a host-pin and nothing else, a report we
cannot believe is a refusal rather than a partial capture, and — the one that costs
money if it regresses — Browserbase stays OFF unless it is explicitly opted into with
real credentials.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

from api.config import settings
from api.services.capture import network_capture as nc
from api.services.capture.network_capture import (
    BrowserSession,
    CaptureError,
    _child_env,
    _parse_report,
    _pump_stdout,
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


def _child(report: dict[str, Any], *, plans: list[dict] | None = None,
           events: list[dict] | None = None):
    """A canned child. ``events`` are replayed through ``on_event`` before the report,
    which is how the streaming half of the capture is exercised without a browser."""
    async def _run(
        plan: dict[str, Any], *, on_event: Any = None, **_: Any
    ) -> dict[str, Any]:
        if plans is not None:
            plans.append(plan)
        for event in events or ():
            if on_event is not None:
                await on_event(event)
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


# --- THE BROWSERBASE OPT-IN: the live view, and giving the browser back -------
#
# All $0. Every one of these fakes the HTTP and the CDP side, because the thing under
# test is precisely the code that would otherwise create a real, billed browser.


class _FakeResponse:
    """Just enough of ``httpx.Response`` for the three calls this module makes."""

    def __init__(self, status_code: int, payload: Any = None, text: str = "") -> None:
        self.status_code = status_code
        self.text = text
        self._payload = payload

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("response body is not JSON")
        return self._payload


class _FakeBrowserbase:
    """A Browserbase stand-in that RECORDS calls instead of making them.

    Recording is the assertion surface: "did we release it" and "did we ask for the
    live view at all" are both invisible in a return value — the same trick the
    session-create counter above uses to prove the opt-in was honoured.
    """

    def __init__(
        self,
        *,
        create: "_FakeResponse | None" = None,
        debug: "_FakeResponse | None" = None,
        release: "_FakeResponse | None" = None,
    ) -> None:
        self.create = create or _FakeResponse(
            201, {"id": "s1", "connectUrl": "wss://cdp/s1"}
        )
        self.debug = debug or _FakeResponse(
            200,
            {"debuggerFullscreenUrl":
             "https://www.browserbase.com/devtools-fullscreen/s1"},
        )
        self.release = release or _FakeResponse(200, {"status": "REQUEST_RELEASE"})
        self.posts: list[tuple[str, dict[str, Any]]] = []
        self.gets: list[str] = []

    def factory(self) -> "_FakeBrowserbase":
        return self

    async def __aenter__(self) -> "_FakeBrowserbase":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.posts.append((url, dict(kwargs.get("json") or {})))
        return self.create if url == nc._BROWSERBASE_API else self.release

    async def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.gets.append(url)
        return self.debug


@pytest.fixture
def browserbase_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "capture_use_browserbase", True)
    monkeypatch.setattr(settings, "browserbase_api_key", "bb-key")
    monkeypatch.setattr(settings, "browserbase_project_id", "proj")


async def test_the_live_view_url_is_fetched_from_the_debug_endpoint(
    browserbase_on: None,
) -> None:
    """``GET /v1/sessions/{id}/debug`` -> ``debuggerFullscreenUrl``, and NOT the
    deprecated ``/recording`` rrweb endpoint — which is also the wrong primitive, since
    a recording only exists once the session has ENDED and nobody wants to watch that.
    """
    fake = _FakeBrowserbase()
    session = await nc._open_browserbase_session(client_factory=fake.factory)
    assert session is not None
    assert session.session_id == "s1"
    assert session.cdp_url == "wss://cdp/s1"
    assert session.live_view_url == "https://www.browserbase.com/devtools-fullscreen/s1"
    assert fake.gets == [f"{nc._BROWSERBASE_API}/s1/debug"]
    assert not any("recording" in url for url in fake.gets)


async def test_a_402_from_browserbase_degrades_to_our_own_chromium(
    browserbase_on: None, caplog: pytest.LogCaptureFixture
) -> None:
    """The status an owner actually hits ("free plan limit reached"). It must never
    wedge a discovery: we fall back to our own Chromium and read the board for free.

    The body is REAL JSON, deliberately. A bodyless 402 would be refused by ``.json()``
    on the way past and the status check would look load-bearing while doing nothing —
    the fake has to be able to sail through a missing check for the test to guard one.

    And the assertion is on the LOG, because that is the only thing a 402 does
    differently: it degrades exactly like an outage does, but the owner's next action is
    "top up the plan", not "wait it out". A generic warning cannot tell them which.
    """
    fake = _FakeBrowserbase(
        create=_FakeResponse(
            402,
            {"message": "free plan limit reached"},
            text='{"message":"free plan limit reached"}',
        )
    )
    with caplog.at_level(logging.WARNING, logger=nc.logger.name):
        assert await nc._open_browserbase_session(client_factory=fake.factory) is None
    assert any(
        "402" in record.getMessage() and "free plan limit reached" in record.getMessage()
        for record in caplog.records
    ), f"the 402 was not named in the log: {[r.getMessage() for r in caplog.records]}"
    # We DID try — this is the degrade path, not the never-configured one.
    assert fake.posts and fake.posts[0][0] == nc._BROWSERBASE_API
    # ...and we never went looking for a live view on a session that does not exist.
    assert fake.gets == []


async def test_a_browserbase_outage_degrades_to_our_own_chromium(
    browserbase_on: None,
) -> None:
    """A transport error rather than a status code — the shape an outage actually takes."""

    class _Down(_FakeBrowserbase):
        async def post(self, url: str, **kwargs: Any) -> _FakeResponse:
            raise httpx.ConnectError("browserbase unreachable")

    assert await nc._open_browserbase_session(client_factory=_Down().factory) is None


async def test_a_session_we_cannot_drive_is_released_before_we_fall_back(
    browserbase_on: None,
) -> None:
    """A create that succeeds but carries no ``connectUrl`` has still BILLED us. Falling
    back without releasing it is a silent charge for a browser that never opened a page.
    """
    fake = _FakeBrowserbase(create=_FakeResponse(201, {"id": "s9"}))
    assert await nc._open_browserbase_session(client_factory=fake.factory) is None
    assert [call for call in fake.posts if call[0].endswith("/s9")] == [
        (f"{nc._BROWSERBASE_API}/s9", {"projectId": "proj", "status": "REQUEST_RELEASE"})
    ]


async def test_releasing_a_session_asks_browserbase_to_end_it_now(
    browserbase_on: None,
) -> None:
    """Browserbase bills per browser-hour: a session we merely stop using goes on
    charging until its own timeout expires."""
    fake = _FakeBrowserbase()
    await nc._release_browserbase_session(
        BrowserSession(cdp_url="wss://cdp/s1", session_id="s1"),
        client_factory=fake.factory,
    )
    assert fake.posts == [
        (f"{nc._BROWSERBASE_API}/s1", {"projectId": "proj", "status": "REQUEST_RELEASE"})
    ]


@pytest.mark.parametrize(
    "boom",
    [
        httpx.ConnectError("browserbase unreachable"),
        # NOT an httpx error, and not theoretical: this runs during teardown, where
        # opening a client on a loop that is already closing raises exactly this.
        RuntimeError("Event loop is closed"),
    ],
    ids=["outage", "teardown"],
)
async def test_a_failed_release_never_becomes_the_captures_failure(
    browserbase_on: None, boom: Exception
) -> None:
    """It runs in a ``finally``. An exception here would replace the real outcome with a
    billing-cleanup one, and the user would be told the wrong thing about their board."""

    class _Refuses(_FakeBrowserbase):
        async def post(self, url: str, **kwargs: Any) -> _FakeResponse:
            raise boom

    await nc._release_browserbase_session(
        BrowserSession(cdp_url="wss://cdp/s1", session_id="s1"),
        client_factory=_Refuses().factory,
    )


async def test_the_live_view_is_published_before_the_page_is_ever_opened() -> None:
    """THE ORDERING IS THE FEATURE. A hosted view handed over after the capture returns
    points at a session that has already been released — a dead iframe every time."""
    order: list[str] = []

    async def _session() -> BrowserSession:
        return BrowserSession(
            cdp_url="wss://cdp/s1",
            live_view_url="https://www.browserbase.com/devtools-fullscreen/s1",
            session_id="s1",
        )

    async def _run(plan: dict[str, Any], **_: Any) -> dict[str, Any]:
        order.append("capture")
        return _report()

    async def _published(url: str) -> None:
        order.append(f"live_view:{url}")

    async def _release(session: BrowserSession) -> None:
        order.append("release")

    result = await capture_board(
        _URL,
        run_subprocess=_run,
        validate_url=_allow_all,
        open_session=_session,
        release_session=_release,
        on_live_view=_published,
    )
    assert order == [
        "live_view:https://www.browserbase.com/devtools-fullscreen/s1",
        "capture",
        "release",
    ]
    assert result.live_view_url == "https://www.browserbase.com/devtools-fullscreen/s1"


async def test_a_live_view_publish_failure_never_fails_the_capture() -> None:
    """The callback writes to the database. Narration must not be able to refuse a board
    we can perfectly well read — the same rule ``discover._publish`` follows."""

    async def _session() -> BrowserSession:
        return BrowserSession(
            cdp_url="wss://cdp/s1", live_view_url="https://bb/live", session_id="s1"
        )

    async def _explodes(url: str) -> None:
        raise RuntimeError("progress write failed")

    async def _release(session: BrowserSession) -> None:
        return None

    result = await capture_board(
        _URL,
        run_subprocess=_child(_report()),
        validate_url=_allow_all,
        open_session=_session,
        release_session=_release,
        on_live_view=_explodes,
    )
    assert len(result.responses) == 3


async def test_the_session_is_released_when_the_capture_fails() -> None:
    """The paths that leak money are the ones that skip ``except`` clauses. A refusal
    must give the browser back exactly like a success does."""
    released: list[str | None] = []

    async def _session() -> BrowserSession:
        return BrowserSession(cdp_url="wss://cdp/s1", session_id="s1")

    async def _fails(plan: dict[str, Any], **_: Any) -> dict[str, Any]:
        raise CaptureError("capture subprocess timed out after 120.0s")

    async def _release(session: BrowserSession) -> None:
        released.append(session.session_id)

    with pytest.raises(CaptureError, match="timed out"):
        await capture_board(
            _URL,
            run_subprocess=_fails,
            validate_url=_allow_all,
            open_session=_session,
            release_session=_release,
        )
    assert released == ["s1"]


async def test_the_session_is_released_when_the_discovery_task_cancels_us() -> None:
    """The 240s task guard CANCELS this coroutine, and ``CancelledError`` is a
    BaseException that skips every ``except``. Only the ``finally`` gives the browser
    back — otherwise it bills to its own TTL on the one path that already went wrong."""
    released: list[str | None] = []

    async def _session() -> BrowserSession:
        return BrowserSession(cdp_url="wss://cdp/s1", session_id="s1")

    driving = asyncio.Event()

    async def _hangs(plan: dict[str, Any], **_: Any) -> dict[str, Any]:
        driving.set()
        await asyncio.sleep(30)
        raise AssertionError("unreachable")

    async def _release(session: BrowserSession) -> None:
        released.append(session.session_id)

    task = asyncio.ensure_future(
        capture_board(
            _URL,
            run_subprocess=_hangs,
            validate_url=_allow_all,
            open_session=_session,
            release_session=_release,
        )
    )
    # Cancel only once the paid browser is genuinely open and being driven — cancelling
    # earlier proves nothing, because there is no session to give back yet.
    await driving.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert released == ["s1"]


async def test_our_own_chromium_never_calls_browserbase_at_all() -> None:
    """The DEFAULT path. No session, so nothing to publish and nothing to release — the
    live-view plumbing cannot cost anything on a free capture."""
    releases: list[Any] = []
    views: list[str] = []

    async def _release(session: BrowserSession) -> None:
        releases.append(session)

    async def _published(url: str) -> None:
        views.append(url)

    result = await capture_board(
        _URL,
        run_subprocess=_child(_report()),
        validate_url=_allow_all,
        open_session=_no_session,
        release_session=_release,
        on_live_view=_published,
    )
    assert result.live_view_url is None
    assert releases == []
    assert views == []


# --------------------------------------------------------------------------
# THE TEARDOWN HALF — saying when the live view STOPS being one
# --------------------------------------------------------------------------
# The frontend used to infer this from the checklist ("step 1 is still active, so the
# browser must still be open") and it was wrong every time: the child closes the browser
# before it exits, and step 1 is not ticked over until discovery has scored the capture,
# published the network log and started step 2. In between, the iframe sat on a socket
# Browserbase had already closed — "Debugging connection was closed" over a blank page,
# under a spinner that said we were still opening it. These pin the fact that the moment
# is ANNOUNCED, on every path that can reach the finally.


async def _live_session() -> BrowserSession:
    return BrowserSession(
        cdp_url="wss://cdp/s1",
        live_view_url="https://www.browserbase.com/devtools-fullscreen/s1",
        session_id="s1",
    )


async def test_the_live_view_is_retracted_the_moment_the_browser_closes() -> None:
    """ORDERING AGAIN, and the other end of it. The retraction has to be announced
    before the release POST (up to 10s, i.e. two of the UI's 4s polls) and long before
    the caller ticks a step — everything the caller does after this returns happens over
    an iframe that is already dead."""
    order: list[str] = []

    async def _run(plan: dict[str, Any], **_: Any) -> dict[str, Any]:
        order.append("capture")
        return _report()

    async def _published(url: str) -> None:
        order.append(f"live_view:{url}")

    async def _closed() -> None:
        order.append("live_view_closed")

    async def _release(session: BrowserSession) -> None:
        order.append("release")

    result = await capture_board(
        _URL,
        run_subprocess=_run,
        validate_url=_allow_all,
        open_session=_live_session,
        release_session=_release,
        on_live_view=_published,
        on_live_view_closed=_closed,
    )
    assert order == [
        "live_view:https://www.browserbase.com/devtools-fullscreen/s1",
        "capture",
        "live_view_closed",
        "release",
    ]
    # The result still CARRIES the URL — it is the record of which session ran, not a
    # claim that it is still watchable. The caller must not republish it (see
    # ``discover``'s note where that copy used to be).
    assert result.live_view_url == "https://www.browserbase.com/devtools-fullscreen/s1"


async def test_the_live_view_is_retracted_when_the_capture_fails() -> None:
    """A refusal kills the browser exactly as dead as a success does. If only the happy
    path retracted, every failed discovery would keep a dead frame on the row until the
    run ended."""
    closed: list[str] = []

    async def _fails(plan: dict[str, Any], **_: Any) -> dict[str, Any]:
        raise CaptureError("capture subprocess timed out after 120.0s")

    async def _closed() -> None:
        closed.append("closed")

    async def _release(session: BrowserSession) -> None:
        return None

    with pytest.raises(CaptureError, match="timed out"):
        await capture_board(
            _URL,
            run_subprocess=_fails,
            validate_url=_allow_all,
            open_session=_live_session,
            release_session=_release,
            on_live_view_closed=_closed,
        )
    assert closed == ["closed"]


async def test_the_live_view_is_retracted_when_the_discovery_task_cancels_us() -> None:
    """The 240s task guard CANCELS us, and on THAT path the refusal carries no terminal
    checklist — the task persists ``progress=None`` and the last live snapshot is what
    the user is left looking at. So the retraction has to survive a ``CancelledError``
    unwinding through the same ``finally``, or a timed-out run keeps a dead live view on
    the row permanently."""
    closed: list[str] = []
    driving = asyncio.Event()

    async def _hangs(plan: dict[str, Any], **_: Any) -> dict[str, Any]:
        driving.set()
        await asyncio.sleep(30)
        raise AssertionError("unreachable")

    async def _closed() -> None:
        closed.append("closed")

    async def _release(session: BrowserSession) -> None:
        return None

    task = asyncio.ensure_future(
        capture_board(
            _URL,
            run_subprocess=_hangs,
            validate_url=_allow_all,
            open_session=_live_session,
            release_session=_release,
            on_live_view_closed=_closed,
        )
    )
    await driving.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed == ["closed"]


async def test_a_run_that_never_had_a_live_view_never_retracts_one() -> None:
    """Our own Chromium is the DEFAULT and has no hosted view at all; a Browserbase
    session whose ``/debug`` lookup failed has none either. Firing the retraction there
    would be a database write per run to set a key that is already null — and, worse, a
    caller could reasonably read it as "the live view you had is gone"."""
    closed: list[str] = []

    async def _closed() -> None:
        closed.append("closed")

    async def _viewless_session() -> BrowserSession:
        return BrowserSession(cdp_url="wss://cdp/s1", session_id="s1")

    async def _release(session: BrowserSession) -> None:
        return None

    for opener in (_no_session, _viewless_session):
        await capture_board(
            _URL,
            run_subprocess=_child(_report()),
            validate_url=_allow_all,
            open_session=opener,
            release_session=_release,
            on_live_view_closed=_closed,
        )
    assert closed == []


async def test_a_failed_live_view_retraction_never_becomes_the_captures_failure(
) -> None:
    """It writes to the database from inside a ``finally``. An exception escaping there
    would replace the real outcome with a narration one — and it would also skip the
    release, turning a cosmetic failure into a paid browser nobody handed back."""
    released: list[str | None] = []

    async def _explodes() -> None:
        raise RuntimeError("progress write failed")

    async def _release(session: BrowserSession) -> None:
        released.append(session.session_id)

    result = await capture_board(
        _URL,
        run_subprocess=_child(_report()),
        validate_url=_allow_all,
        open_session=_live_session,
        release_session=_release,
        on_live_view_closed=_explodes,
    )
    assert len(result.responses) == 3
    assert released == ["s1"]


# --------------------------------------------------------------------------
# STREAMING — the child narrates while the browser is still open
# --------------------------------------------------------------------------
# The capture takes 30-120 seconds and used to say nothing until it exited, so the
# progress panel had a list that appeared all at once at the end. These pin the two
# halves of the fix: the child's lines reach the caller AS THEY ARRIVE, and nothing
# about that path can cost us a capture.


async def test_recorded_responses_reach_the_caller_before_the_report_does() -> None:
    seen: list[dict[str, Any]] = []

    async def _on_request(record: dict[str, Any]) -> None:
        seen.append(record)

    await capture_board(
        _URL,
        run_subprocess=_child(_report(), events=[
            {"event": "response", "method": "GET", "url": "https://a.example/ping",
             "status": 204, "bytes": 12, "truncated": False},
            {"event": "response", "method": "POST", "url": "https://a.example/api/jobs",
             "status": 200, "bytes": 90_000, "truncated": True},
            # Not a response event — a future event type must not be forwarded as one.
            {"event": "something_else", "url": "https://a.example/x"},
        ]),
        validate_url=_allow_all,
        open_session=_no_session,
        on_request=_on_request,
    )
    assert [record["url"] for record in seen] == [
        "https://a.example/ping", "https://a.example/api/jobs"
    ]
    assert seen[1] == {
        "method": "POST", "url": "https://a.example/api/jobs", "status": 200,
        "bytes": 90_000, "truncated": True,
    }


async def test_a_publish_failure_never_fails_the_capture() -> None:
    """Same rule the live-view callback follows: narration writes to the database, and
    there is no version of "the progress write failed" that should refuse a board."""

    async def _explodes(record: dict[str, Any]) -> None:
        raise RuntimeError("progress write failed")

    result = await capture_board(
        _URL,
        run_subprocess=_child(_report(), events=[
            {"event": "response", "method": "GET", "url": "https://a.example/x",
             "status": 200, "bytes": 1, "truncated": False},
        ]),
        validate_url=_allow_all,
        open_session=_no_session,
        on_request=_explodes,
    )
    assert len(result.responses) == 3


async def test_the_stream_survives_a_report_line_bigger_than_the_reader_limit() -> None:
    """THE regression this pump exists for. ``StreamReader.readline`` carries a 64 KiB
    line limit and the child's report is ONE line of up to ~16 MB, so the obvious
    implementation raises ``LimitOverrunError`` on every real capture — while passing
    every test written against a small fixture."""
    events: list[dict[str, Any]] = []

    async def _on_event(event: dict[str, Any]) -> None:
        events.append(event)

    reader = asyncio.StreamReader(limit=64 * 1024)
    reader.feed_data(b'{"event":"response","url":"https://a.example/x"}\n')
    big = json.dumps({"final_url": _URL, "responses": [{"pad": "y" * 300_000}]})
    reader.feed_data(big.encode() + b"\n")
    reader.feed_eof()

    stdout = await _pump_stdout(reader, _on_event)
    assert [event["url"] for event in events] == ["https://a.example/x"]
    # ...and the report still comes back whole, which is what discovery actually runs on.
    assert _parse_report(stdout.decode())["final_url"] == _URL


async def test_chromium_chatter_is_not_mistaken_for_narration() -> None:
    """The child shares stdout with a browser that prints whatever it likes."""
    events: list[dict[str, Any]] = []

    async def _on_event(event: dict[str, Any]) -> None:
        events.append(event)

    reader = asyncio.StreamReader()
    reader.feed_data(b"[0824/090000.1:ERROR:bus.cc(399)] Failed to connect\n")
    reader.feed_data(b'{"not": "an event"}\n')
    reader.feed_data(b'{"event":"response","url":"https://a.example/x"}\n')
    reader.feed_eof()

    await _pump_stdout(reader, _on_event)
    assert len(events) == 1


def test_an_oversize_response_reports_what_it_actually_weighed() -> None:
    """``body`` is emptied when a response is too big to carry, so ``len(body)`` would
    report the board's biggest response as 0 bytes — the precise opposite of the
    evidence a "larger than we can record" refusal needs."""
    responses = _responses_from_report({
        "final_url": _URL,
        "responses": [
            {"url": "https://a.example/api/jobs", "method": "GET", "status": 200,
             "body": "", "truncated": True, "bytes": 2_775_685},
            # A report from a child that predates the field falls back to the body.
            {"url": "https://a.example/ok", "method": "GET", "status": 200,
             "body": "12345", "truncated": False},
        ],
    })
    assert [r.body_bytes for r in responses] == [2_775_685, 5]


# --------------------------------------------------------------------------
# the board document's own LINKS — raw material for job-link derivation
# --------------------------------------------------------------------------

def test_the_child_reads_links_off_the_RENDERED_dom_not_the_served_document() -> None:
    """WHY ``page.content()`` AND NOT THE HOST-PIN BODY, which is already fetched and
    thrown away and looks free.

    That body is what the SERVER sent, and the boards this feature exists for render
    their job list on the client. Measured 2026-08-30:
    ``atlassian.com/company/careers/all-jobs`` contains ``careers/details/`` **0 times**
    in the served document and 233 times in the DOM after the observation window; Jane
    Street's served document carries none of its 233 job ids either. A harvest that read
    the server body would find job links only on the boards that never needed help.

    Run in a SUBPROCESS for the reason the truncation test above gives: importing
    ``_capture_main`` would make ``playwright`` resident and every later
    ``assert_no_agent_imports()`` in the suite would then raise.
    """
    rendered = (
        '<a href="/company/careers">All</a>'
        "<a href='/company/careers/details/25583'>A</a>"
        '<a href="/company/careers/details/25583">dup</a>'
        '<script src="/assets/app.js"></script>'
        "<script src='https://cdn.example.com/x.js'></script>"
    )
    code = (
        "import json, sys\n"
        "from api.services.capture._capture_main import _document_links\n"
        "print(json.dumps(_document_links(json.loads(sys.argv[1]))))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, json.dumps(rendered)],
        cwd=str(_BACKEND), env=_SUBPROC_ENV,
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    links, scripts = json.loads(result.stdout.strip().splitlines()[-1])
    # Deduped, first-seen order, both quote styles.
    assert links == ["/company/careers", "/company/careers/details/25583"]
    # Every script SRC, on-host or not — the PARENT decides which it may read, because
    # only the parent knows the board's host and owns the SSRF-guarded client.
    assert scripts == ["/assets/app.js", "https://cdn.example.com/x.js"]


def test_a_child_that_reports_no_links_degrades_to_todays_behaviour() -> None:
    """A report from a child that predates the field — a rolling deploy, a replayed
    fixture — must not fail a capture that recorded the whole board. The job link then
    falls to the board's own listing page, which is what we ship today."""
    result = nc.CaptureResult(
        final_url="https://b.example/careers", page_title="", responses=[],
    )
    assert result.board_links == () and result.board_scripts == ()
    assert nc._string_list(None) == ()
    assert nc._string_list(["/a", 7, "", None, "/b"]) == ("/a", "/b")
