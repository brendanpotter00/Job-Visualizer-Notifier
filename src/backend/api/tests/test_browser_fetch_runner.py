"""E7 Phase 3c — the browser_fetch runner. $0: the Chromium subprocess is FAKED.

The runner is the agent-free parent of the local-Chromium fetch subprocess. These
tests inject a fake ``{pages: [{status, text}]}`` report (no browser, no DNS, no
network) and prove the whole RAISES-never-empty surface of the tier:

* a clean report maps rows through the SHARED ``recipe_runner`` machinery and emits
  the right evidence (declared_total from the oracle, page_advance_ok, terminus);
* a 2-page report dedupes and reports page advance;
* a non-200 page, a non-JSON body, an in-band error code, zero rows and a count under
  ``expected_min_jobs`` each RAISE — none of them may look like "no jobs today";
* the page bound is re-asserted on READ (a child that overran is refused);
* an SSRF-blocked origin_url raises BEFORE anything spawns (proved by counting spawns);
* a subprocess timeout and a non-zero exit are RecipeExecutionError, not escapes.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from api.services.browser_fetch.runner import (
    _parse_report,
    _subprocess_run,
    build_subprocess_plan,
    run_browser_fetch,
)
from api.services.recipe_runner import RecipeExecutionError, parse_plan

pytestmark = pytest.mark.asyncio

_FIXTURES = Path(__file__).parent / "fixtures" / "recipes"
_ORIGIN = "https://lifeattiktok.com/"
_BACKEND = Path(__file__).resolve().parents[2]          # src/backend
_REPO_ROOT = _BACKEND.parents[1]
_SUBPROC_ENV = {**os.environ,
                "PYTHONPATH": os.pathsep.join([str(_REPO_ROOT), str(_BACKEND)])}


def _script(**overrides: Any) -> dict:
    """The real TikTok capture fixture, optionally tweaked per test."""
    script = json.loads((_FIXTURES / "tiktok_browser_fetch.json").read_text())
    script.update(overrides)
    return script


def _single_page_script(**overrides: Any) -> dict:
    """The same recipe with the pagination step removed (single-shot boards)."""
    script = _script(**overrides)
    script["steps"] = [s for s in script["steps"] if s["op"] != "paginate_offset"]
    return script


def _job(i: int) -> dict:
    return {
        "id": f"76754401718199606{i:02d}",
        "title": f"Software Engineer {i}",
        "city_info": {"en_name": "San Jose"},
        "job_category": {"en_name": "Engineering"},
    }


def _body(jobs: list[dict], *, count: int = 4026, code: int = 0) -> str:
    return json.dumps({"code": code, "message": "ok",
                       "data": {"job_post_list": jobs, "count": count}})


def _page(jobs: list[dict], *, status: int = 200, count: int = 4026,
          code: int = 0, headers: dict | None = None) -> dict:
    return {"status": status, "text": _body(jobs, count=count, code=code),
            "headers": headers if headers is not None else {"content-type": "application/json"}}


def _report(pages: list[dict], *, pages_fetched: int | None = None,
            terminated_cleanly: bool = True, cap_hit: bool = False) -> dict:
    return {
        "pages": pages,
        "pages_fetched": len(pages) if pages_fetched is None else pages_fetched,
        "terminated_cleanly": terminated_cleanly,
        "cap_hit": cap_hit,
    }


def _noop_validate(url: str) -> None:
    return None


def _fake_subprocess(report: dict[str, Any]):
    async def _run(subprocess_plan: dict[str, Any]) -> dict[str, Any]:
        return report
    return _run


async def _replay(report: dict, *, script: dict | None = None):
    return await run_browser_fetch(
        script or _script(),
        run_subprocess=_fake_subprocess(report),
        validate_url=_noop_validate,
    )


# --- the happy paths ---------------------------------------------------------

async def test_single_page_report_maps_rows_and_evidence() -> None:
    rows, evidence = await _replay(
        _report([_page([_job(i) for i in range(10)])]),
        script=_single_page_script(),
    )
    assert len(rows) == 10
    assert rows[0]["title"] == "Software Engineer 0"
    assert rows[0]["location"] == "San Jose"
    assert rows[0]["department"] == "Engineering"
    # The url template resolved against the record's id.
    assert rows[0]["url"] == f"https://lifeattiktok.com/search/{rows[0]['id']}"
    assert evidence.declared_total == 4026          # declared_probed oracle
    assert evidence.pages_fetched == 1
    assert evidence.page_advance_ok is None         # vacuous on one page
    assert evidence.terminated_cleanly is True
    assert evidence.cap_hit is False
    assert evidence.transport_ok is True


async def test_two_pages_dedupe_and_report_page_advance() -> None:
    """Distinct ids across pages → page_advance_ok True; a repeat across pages is
    deduped to one row (first occurrence wins)."""
    page_one = [_job(i) for i in range(10)]
    page_two = [_job(i) for i in range(9, 19)]      # job 9 repeats
    rows, evidence = await _replay(_report([_page(page_one), _page(page_two)]))
    assert len(rows) == 19                          # 20 records, one duplicate id
    assert len({r["id"] for r in rows}) == 19
    assert evidence.pages_fetched == 2
    assert evidence.page_advance_ok is False        # the repeat IS the signal


async def test_two_disjoint_pages_advance_cleanly() -> None:
    rows, evidence = await _replay(_report([
        _page([_job(i) for i in range(10)]),
        _page([_job(i) for i in range(10, 20)]),
    ]))
    assert len(rows) == 20
    assert evidence.page_advance_ok is True
    assert evidence.terminated_cleanly is True


async def test_unclean_terminus_and_cap_hit_ride_through_honestly() -> None:
    """The child's own report of how it stopped is carried to the gate verbatim —
    a budget-exhausted or capped sweep must NOT read as a proven-complete board."""
    _rows, evidence = await _replay(_report(
        [_page([_job(i) for i in range(10)]), _page([_job(i) for i in range(10, 20)])],
        terminated_cleanly=False, cap_hit=True,
    ))
    assert evidence.cap_hit is True
    assert evidence.terminated_cleanly is False


async def test_child_receives_a_dumb_plan_not_the_recipe() -> None:
    """D3: the subprocess gets only what it needs to ISSUE requests — no fields, no
    oracle, no dedupe key. Everything else stays on the agent-free side."""
    captured: dict[str, Any] = {}

    async def _capture(subprocess_plan: dict[str, Any]) -> dict[str, Any]:
        captured.update(subprocess_plan)
        return _report([_page([_job(i) for i in range(10)])])

    await run_browser_fetch(
        _script(), run_subprocess=_capture, validate_url=_noop_validate
    )
    assert captured["origin_url"] == _ORIGIN
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/search/job/posts")
    assert captured["headers"]["website-path"] == "tiktok"
    assert captured["pagination"] == {
        "style": "offset", "param": "offset", "page_size": 10,
        "max_pages": 2, "start_page": 1, "window_cap": None,
    }
    assert captured["records_path"] == "data.job_post_list"
    assert "fields" not in captured and "oracle" not in captured


def test_build_subprocess_plan_has_no_pagination_for_a_single_shot_recipe() -> None:
    script = _single_page_script()
    plan = build_subprocess_plan(script, parse_plan(script))
    assert plan["pagination"] is None


# --- RAISES-never-empty: every way a page can be unusable --------------------

async def test_non_200_page_raises() -> None:
    with pytest.raises(RecipeExecutionError, match="HTTP 403 from the in-browser fetch"):
        await _replay(
            _report([{"status": 403, "text": "forbidden", "headers": {}}]),
            script=_single_page_script(),
        )


async def test_non_json_body_raises() -> None:
    with pytest.raises(RecipeExecutionError, match="unparseable JSON"):
        await _replay(
            _report([{"status": 200, "text": "<html>bot wall</html>", "headers": {}}]),
            script=_single_page_script(),
        )


async def test_inband_error_code_raises() -> None:
    """TikTok signals failure with a non-zero ``code`` inside an HTTP 200. The
    recipe's assert_no_inband_error fires on the truthy value; ``code: 0`` (ok) does
    not — which is exactly why listing 'code' is safe for this board."""
    with pytest.raises(RecipeExecutionError, match="in-band error key 'code'"):
        await _replay(
            _report([_page([_job(i) for i in range(10)], code=40001)]),
            script=_single_page_script(),
        )


async def test_records_path_that_does_not_resolve_raises() -> None:
    body = json.dumps({"code": 0, "data": {"renamed_list": [], "count": 3}})
    with pytest.raises(RecipeExecutionError, match="records_path"):
        await _replay(
            _report([{"status": 200, "text": body, "headers": {}}]),
            script=_single_page_script(),
        )


async def test_zero_rows_raises() -> None:
    with pytest.raises(RecipeExecutionError, match="zero records"):
        await _replay(
            _report([_page([])]),
            script=_single_page_script(),
        )


async def test_below_expected_min_jobs_raises() -> None:
    with pytest.raises(RecipeExecutionError, match="below expected_min_jobs=10"):
        await _replay(
            _report([_page([_job(0), _job(1)])]),
            script=_single_page_script(),
        )


async def test_no_pages_at_all_raises() -> None:
    with pytest.raises(RecipeExecutionError, match="pages_fetched"):
        await _replay(_report([]), script=_single_page_script())


async def test_vanished_oracle_raises() -> None:
    """declared_probed whose total_path stopped resolving is a FAILED run, never a
    silently total-less one."""
    body = json.dumps({"code": 0, "data": {"job_post_list": [_job(i) for i in range(10)]}})
    with pytest.raises(RecipeExecutionError, match="declared_probed total_path"):
        await _replay(
            _report([{"status": 200, "text": body, "headers": {}}]),
            script=_single_page_script(),
        )


# --- THE BOUND, re-asserted on read ------------------------------------------

async def test_child_exceeding_max_pages_raises_in_the_parent() -> None:
    """max_pages is 2 in the fixture; a child that returned 3 pages is not the child
    we think it is, so the whole run is refused."""
    with pytest.raises(RecipeExecutionError, match="bound is 2"):
        await _replay(_report([
            _page([_job(i) for i in range(10)]),
            _page([_job(i) for i in range(10, 20)]),
            _page([_job(i) for i in range(20, 30)]),
        ]))


async def test_pages_length_must_match_pages_fetched() -> None:
    with pytest.raises(RecipeExecutionError, match="inconsistent"):
        await _replay(_report([_page([_job(0)])], pages_fetched=2))


async def test_invalid_pages_fetched_raises() -> None:
    report = _report([_page([_job(0)])])
    report["pages_fetched"] = 0
    with pytest.raises(RecipeExecutionError, match="pages_fetched=0"):
        await _replay(report)


# --- SSRF: nothing spawns for a blocked URL ----------------------------------

async def test_ssrf_blocked_origin_url_raises_before_any_spawn() -> None:
    spawned = {"count": 0}

    async def _must_not_spawn(subprocess_plan: dict[str, Any]) -> dict[str, Any]:
        spawned["count"] += 1
        return {}

    def _blocking_validator(url: str) -> None:
        raise RecipeExecutionError(
            f"browser_fetch URL {url!r} blocked by the SSRF guard "
            "(resolves_to_private_address)"
        )

    with pytest.raises(RecipeExecutionError, match="SSRF guard"):
        await run_browser_fetch(
            _script(), run_subprocess=_must_not_spawn, validate_url=_blocking_validator
        )
    assert spawned["count"] == 0


async def test_both_origin_and_fetch_url_are_guarded() -> None:
    """Invariant #4 is two URLs, not one: the origin Chromium lands on AND the
    endpoint it fetches from inside that page."""
    seen: list[str] = []

    def _record(url: str) -> None:
        seen.append(url)

    await run_browser_fetch(
        _single_page_script(),
        run_subprocess=_fake_subprocess(_report([_page([_job(i) for i in range(10)])])),
        validate_url=_record,
    )
    assert seen == [
        _ORIGIN,
        "https://api.lifeattiktok.com/api/v1/public/supplier/search/job/posts",
    ]


async def test_a_blocked_fetch_url_also_stops_the_spawn() -> None:
    spawned = {"count": 0}

    async def _must_not_spawn(subprocess_plan: dict[str, Any]) -> dict[str, Any]:
        spawned["count"] += 1
        return {}

    def _block_the_api_host(url: str) -> None:
        if url.startswith("https://api."):
            raise RecipeExecutionError(f"blocked {url} (SSRF guard: invalid_hostname)")

    with pytest.raises(RecipeExecutionError, match="SSRF guard"):
        await run_browser_fetch(
            _script(), run_subprocess=_must_not_spawn, validate_url=_block_the_api_host
        )
    assert spawned["count"] == 0


# --- wrong-transport / drifted-script guards ---------------------------------

async def test_an_http_json_script_is_refused() -> None:
    """Running a plain-HTTP board through a browser would WORK and be wrong — it
    would burn Chromium nightly for a board that needs none."""
    script = json.loads((_FIXTURES / "janestreet.json").read_text())
    with pytest.raises(RecipeExecutionError, match="only 'browser_fetch' recipes"):
        await run_browser_fetch(
            script,
            run_subprocess=_fake_subprocess(_report([_page([_job(0)])])),
            validate_url=_noop_validate,
        )


async def test_column_mismatch_is_caught_on_read() -> None:
    with pytest.raises(Exception, match="company_scripts.oracle_kind"):
        await run_browser_fetch(
            _script(),
            transport="browser_fetch",
            oracle_kind="self_consistent",       # the script says declared_probed
            run_subprocess=_fake_subprocess(_report([_page([_job(0)])])),
            validate_url=_noop_validate,
        )


# --- subprocess failure modes ------------------------------------------------

async def test_subprocess_timeout_raises(monkeypatch) -> None:
    """A hung Chromium must become a FAILED run, not a wedged worker."""
    monkeypatch.setattr(
        "api.services.browser_fetch.runner._SUBPROCESS_TIMEOUT_S", 0.05
    )

    class _HangingProc:
        # ``None`` because that is what a still-running child ACTUALLY reports —
        # the reaper keys off it to tell "hung, kill it" from "already exited,
        # killing it would be a bug" (the non-zero-exit test below asserts the
        # other side of that branch).
        returncode = None

        async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
            await asyncio.sleep(5)
            return b"", b""

        def kill(self) -> None:
            self.killed = True
            self.returncode = -9

        async def wait(self) -> int:
            return -9

    proc = _HangingProc()

    async def _fake_exec(*args: Any, **kwargs: Any) -> Any:
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    with pytest.raises(RecipeExecutionError, match="timed out"):
        await _subprocess_run({"origin_url": _ORIGIN})
    assert getattr(proc, "killed", False) is True


async def test_subprocess_non_zero_exit_raises(monkeypatch) -> None:
    class _FailingProc:
        returncode = 1

        async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
            return b"", b"TargetClosedError: browser has been closed"

        def kill(self) -> None:  # pragma: no cover - not reached
            raise AssertionError("must not kill a process that already exited")

    async def _fake_exec(*args: Any, **kwargs: Any) -> Any:
        return _FailingProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    with pytest.raises(RecipeExecutionError, match="rc=1.*TargetClosedError"):
        await _subprocess_run({"origin_url": _ORIGIN})


async def test_subprocess_stdout_without_a_report_raises(monkeypatch) -> None:
    class _ChattyProc:
        returncode = 0

        async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
            return b"[chromium] some log line\n", b""

        def kill(self) -> None:  # pragma: no cover - not reached
            raise AssertionError("must not kill a process that already exited")

    async def _fake_exec(*args: Any, **kwargs: Any) -> Any:
        return _ChattyProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    with pytest.raises(RecipeExecutionError, match="no JSON report"):
        await _subprocess_run({"origin_url": _ORIGIN})


def test_parse_report_ignores_stray_log_lines() -> None:
    """Chromium prints to stdout; the report is the LAST JSON line carrying the
    sentinel keys."""
    stdout = (
        "[chromium] DevTools listening on ws://127.0.0.1:1234\n"
        '{"unrelated": "json line"}\n'
        '{"pages": [], "pages_fetched": 1, "terminated_cleanly": true}\n'
    )
    assert _parse_report(stdout)["pages_fetched"] == 1


# --- the child's pure helpers, exercised OUT OF PROCESS ----------------------

def test_child_get_cursor_merge_preserves_the_captured_filters() -> None:
    """The GET pagination path is the one that can silently change a board's SCOPE:
    ``fetch(url + '?offset=N')`` would drop every captured filter and turn a scoped
    search into the global one. The child must MERGE like ``httpx.copy_merge_params``
    — replacing only the cursor key — exactly as ``recipe_runner._request`` does.

    Run in a SUBPROCESS on purpose: importing ``_browser_fetch_main`` would make
    ``playwright`` resident in the pytest process, and every later
    ``assert_no_agent_imports()`` in the suite would then raise. The boundary that
    protects the worker protects the test process the same way.
    """
    code = (
        "from api.services.browser_fetch._browser_fetch_main import _merge_query, _count_records\n"
        "print(_merge_query('https://b.example/api?team=eng&limit=100', {'offset': 200}))\n"
        "print(_merge_query('https://b.example/api?offset=0&team=eng', {'offset': 100}))\n"
        "print(_count_records('{\"d\": {\"jobs\": [1, 2, 3]}}', 'd.jobs'))\n"
        "print(_count_records('{\"d\": {}}', 'd.jobs'))\n"
        "print(_count_records('<html>bot wall</html>', 'd.jobs'))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(_BACKEND), env=_SUBPROC_ENV,
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    merged, replaced, counted, missing, unparseable = result.stdout.strip().splitlines()

    assert "team=eng" in merged and "limit=100" in merged and "offset=200" in merged
    # An existing cursor key is REPLACED, not appended twice (which most servers
    # resolve to the FIRST value — i.e. page 1 forever).
    assert replaced.count("offset=") == 1 and "offset=100" in replaced
    assert "team=eng" in replaced
    # The count is the child's ONLY judgement: how many records this page carried.
    assert counted == "3"
    # Unknown → stop paging and let the PARENT raise with the real diagnosis.
    assert missing == "None" and unparseable == "None"


def test_child_post_cursor_merge_matches_the_parents_exactly() -> None:
    """The POST twin of the GET merge above, and the same failure class: a cursor
    written at the TOP LEVEL of a nested body leaves the real one at its captured value
    and every page is page one (higher.gs.com: 56 pages, 1,120 rows, 20 after dedupe).

    Pinned as a PARITY test because the child re-implements the merge rather than
    importing it (this file's zero-first-party-import rule): the two copies drifting is
    the same recipe meaning two different things on two transports. TikTok — the only
    ``browser_fetch`` board in production — carries ``offset`` at the top level, and its
    case is included so byte-identity there is what fails first if this regresses.

    Run in a SUBPROCESS for the reason spelled out above: importing the child would make
    ``playwright`` resident and every later ``assert_no_agent_imports()`` would raise.
    """
    cases = [
        # (captured body, params) — nested GraphQL, flat TikTok, and a novel key.
        ({"variables": {"searchQueryInput": {"page": {"pageSize": 20, "pageNumber": 0}}},
          "operationName": "GetRoles"}, {"pageNumber": 41}),
        ({"limit": 10, "offset": 0, "keyword": ""}, {"offset": 250}),
        ({"q": "x"}, {"page": 3}),
        ({"offset": 0, "filters": {"offset": 99}}, {"offset": 5}),
    ]
    code = (
        "import json\n"
        "from api.services.browser_fetch._browser_fetch_main import _merge_body\n"
        f"for body, params in {cases!r}:\n"
        "    print(json.dumps(_merge_body(body, params), sort_keys=True))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(_BACKEND), env=_SUBPROC_ENV,
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr

    from api.services.recipe_runner import merge_body_params

    expected = [
        json.dumps(merge_body_params(body, params), sort_keys=True)
        for body, params in cases
    ]
    assert result.stdout.strip().splitlines() == expected
    # ...and the values themselves, so a parity test over two identically-broken
    # copies cannot pass.
    assert json.loads(expected[0])["variables"]["searchQueryInput"]["page"] == {
        "pageSize": 20, "pageNumber": 41,
    }
    assert json.loads(expected[1]) == {"limit": 10, "offset": 250, "keyword": ""}


def test_child_fetch_page_actually_uses_the_nested_merge() -> None:
    """The helper being right is not the same claim as the CALL SITE using it.

    ``_fetch_page`` is what hands the body to the in-page ``fetch()``, so this drives
    it with a stub page and reads the body it would have sent. Without this, a
    ``_merge_body`` that is perfectly correct and simply not called still passes.
    """
    code = (
        "import json\n"
        "from api.services.browser_fetch import _browser_fetch_main as m\n"
        "class _Page:\n"
        "    def __init__(self): self.arg = None\n"
        "    def evaluate(self, js, arg):\n"
        "        self.arg = arg\n"
        "        return {'status': 200, 'text': '{}', 'headers': {}}\n"
        "plan = {'method': 'POST', 'url': 'https://b.example/gql', 'headers': {},\n"
        "        'body': {'variables': {'page': {'pageSize': 20, 'pageNumber': 0}}}}\n"
        "p = _Page(); m._fetch_page(p, plan, {'pageNumber': 41})\n"
        "print(json.dumps(p.arg['body'], sort_keys=True))\n"
        # ...and the GET branch still merges into the query, untouched.
        "plan2 = {'method': 'GET', 'url': 'https://b.example/api?team=eng', 'headers': {},\n"
        "         'body': {}}\n"
        "p2 = _Page(); m._fetch_page(p2, plan2, {'offset': 20})\n"
        "print(p2.arg['url'])\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(_BACKEND), env=_SUBPROC_ENV,
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    body, url = result.stdout.strip().splitlines()
    assert json.loads(body) == {"variables": {"page": {"pageSize": 20, "pageNumber": 41}}}
    assert "team=eng" in url and "offset=20" in url


# --- the host-pin (redirect laundering) --------------------------------------
#
# The BROWSER-level proof lives in ``scripts/one_off/http_capture_poc/browser_fetch_pin_repro.py``
# — it stands up local board/private/CDN servers, runs the REAL child against a REAL
# Chromium, and shows the private host is never reached while the board's third-party
# sub-resource still loads. These tests pin the pure pieces that proof depends on, so a
# refactor cannot quietly remove the control without a red test.


def test_the_recipe_fetch_refuses_to_follow_redirects() -> None:
    """``redirect: 'error'`` is the pin for the request that produces our DATA.

    Chromium follows a 302 itself and ``context.route`` is NOT re-entered for the hop
    (measured), so ``redirect: 'follow'`` would let a board launder our fetch onto an
    internal address and hand us that body as if it were jobs. Losing this one word is
    a silent SSRF regression, hence a test that names it.
    """
    code = (
        "from api.services.browser_fetch._browser_fetch_main import _FETCH_JS\n"
        "print('error' if \"redirect: 'error'\" in _FETCH_JS else 'MISSING')\n"
        "print('follow' if \"redirect: 'follow'\" in _FETCH_JS else 'no-follow')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(_BACKEND), env=_SUBPROC_ENV,
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    mode, follow = result.stdout.strip().splitlines()
    assert mode == "error"
    assert follow == "no-follow"


def test_redirect_target_host_reads_the_location_hop() -> None:
    """What the navigation pin decides on: the host a 3xx would send us to.

    Relative Locations must resolve against the response URL — a board that answers
    ``Location: /internal`` is not off-host, and one that answers a bare absolute URL
    is, and confusing the two either breaks clean boards or opens the hole.
    """
    code = (
        "from api.services.browser_fetch._browser_fetch_main import _redirect_target_host\n"
        "class R:\n"
        "    def __init__(self, status, loc, url):\n"
        "        self.status, self.url = status, url\n"
        "        self.headers = {'location': loc} if loc else {}\n"
        "print(repr(_redirect_target_host(R(200, '', 'https://board.test/careers'))))\n"
        "print(repr(_redirect_target_host(R(302, 'http://169.254.169.254/latest/meta-data',"
        " 'https://board.test/careers'))))\n"
        "print(repr(_redirect_target_host(R(302, '/jobs', 'https://board.test/careers'))))\n"
        "print(repr(_redirect_target_host(R(301, 'https://BOARD.TEST/jobs',"
        " 'https://board.test/careers'))))\n"
        "print(repr(_redirect_target_host(R(302, '', 'https://board.test/careers'))))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(_BACKEND), env=_SUBPROC_ENV,
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    non_redirect, metadata, relative, cased, headerless = result.stdout.strip().splitlines()
    assert non_redirect == "''"                   # a 200 is not a hop
    assert metadata == "'169.254.169.254'"        # the case the pin exists for
    assert relative == "'board.test'"             # same-host, must stay allowed
    assert cased == "'board.test'"                # host compare is case-insensitive
    assert headerless == "''"                     # a 3xx with no Location is not a hop


async def test_the_plan_pins_exactly_the_two_validated_hosts() -> None:
    """The child can only pin what the parent hands it, and the parent must hand it
    exactly the hosts it SSRF-validated — no more (a third host would be unvalidated)
    and no fewer (a missing host pins the run shut)."""
    script = _script()
    plan = parse_plan(script)
    subprocess_plan = build_subprocess_plan(script, plan)
    assert subprocess_plan["allowed_hosts"] == ["api.lifeattiktok.com", "lifeattiktok.com"]
