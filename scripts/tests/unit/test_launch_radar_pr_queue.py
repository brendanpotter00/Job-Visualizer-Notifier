"""``radar.py pr-*`` (pr_queue.py): the add-company PR queue, loop side (saved-pr/PLAN.md §4.2, §4.4).

No network and no child process: the backend is ``FakeBackend`` and every subprocess
goes through the ``PrEnv.runner`` seam."""

import json
import re
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from launch_radar import pr_queue
from launch_radar.backend_client import BackendClient
from launch_radar.pr_queue import PrEnv
from tests.unit.launch_radar_fakes import FakeBackend

URL = "https://github.com/brendanpotter00/Job-Visualizer-Notifier/pull/412"
RUN_ID = "1760000000-4242"
START = 1_760_000_000


class Runner:
    """Records every child call; ``fail`` names the preflight check to fail."""

    def __init__(self, fail: str | None = None, refresh=None) -> None:
        self.calls: list[dict] = []
        self.fail = fail
        self.refresh = refresh or (lambda card_id: (0, json.dumps({"card_id": card_id, "refreshed": True,
                                                                   "why": "rebuilt"}), ""))

    def __call__(self, argv, *, env, cwd, timeout):
        argv = list(argv)
        self.calls.append({"argv": argv, "env": dict(env), "cwd": cwd, "timeout": timeout})
        check = {"auth": "gh_auth", "api": "gh_push", "ls-remote": "git_remote", "-I": "logo_venv"}
        if argv[-3:-1] == ["refresh", "--card-id"]:
            rc, out, err = self.refresh(int(argv[-1]))
            return subprocess.CompletedProcess(argv, rc, out, err)
        name = next(v for k, v in check.items() if k in argv)
        if name == self.fail:
            return subprocess.CompletedProcess(argv, 1, "false\n" if name == "gh_push" else "", "nope")
        return subprocess.CompletedProcess(argv, 0, "true\n" if name == "gh_push" else "", "")

    def preflight_names(self):
        return [c["argv"][:3] for c in self.calls]


class Captured:
    def __init__(self) -> None:
        self.out: list = []
        self.err: list[str] = []


@pytest.fixture
def fb():
    return FakeBackend()


def make_env(tmp_path, fb, *, runner=None, environ=None, now=None, venv=True):
    state = tmp_path / "state"
    root = tmp_path / "repo"
    state.mkdir(exist_ok=True)
    root.mkdir(exist_ok=True)
    if venv:
        py = state / "logo-venv" / "bin" / "python"
        py.parent.mkdir(parents=True, exist_ok=True)
        py.write_text("#!/bin/sh\n")
    cap = Captured()
    env = PrEnv(backend=BackendClient("http://backend.test", "k", transport=fb.transport()), state_dir=state,
                root=root, environ=environ if environ is not None else {"PATH": "/usr/bin", "HOME": "/home/x"},
                runner=runner or Runner(), now=now or (lambda: START + 60), out=cap.out.append,
                err=cap.err.append)
    return env, cap


def write_session(env, run_id=RUN_ID, start=START):
    (env.state_dir / "session_started_at").write_text(f"{start} {run_id}\n")


def published(env, cid, **fields):
    data = {"card_id": cid, "dry_run": False, "pr_url": URL, "commit": "a" * 40, "slug": "acme", "draft": False}
    data.update(fields)
    p = env.pr_dir / "published" / f"{cid}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data))
    return p


# ---- the clock (§4.4) -------------------------------------------------------------------------------
def test_clock_applies_only_with_the_matching_run_id(tmp_path, fb):
    env, _ = make_env(tmp_path, fb, environ={"LAUNCH_RADAR_RUN_ID": RUN_ID}, now=lambda: START + 3300)
    assert pr_queue.session_elapsed_s(env) is None  # no file
    write_session(env)
    assert pr_queue.session_elapsed_s(env) == 3300 and pr_queue.past_cutoff(env)
    assert pr_queue.time_left_s(env) == 2100
    write_session(env, run_id="1760000000-9999")  # a file from another run
    assert pr_queue.session_elapsed_s(env) is None and not pr_queue.past_cutoff(env)
    assert pr_queue.time_left_s(env) is None


def test_clock_never_applies_without_the_env_var(tmp_path, fb):
    env, _ = make_env(tmp_path, fb, environ={}, now=lambda: START + 99_999)
    write_session(env)
    assert pr_queue.session_elapsed_s(env) is None and not pr_queue.past_cutoff(env)


@pytest.mark.parametrize("text", ["", "abc 1760000000-4242", f"{START}", f"{START} {RUN_ID} extra", "-5 x"])
def test_clock_ignores_a_malformed_file(tmp_path, fb, text):
    env, _ = make_env(tmp_path, fb, environ={"LAUNCH_RADAR_RUN_ID": RUN_ID}, now=lambda: START + 9999)
    (env.state_dir / "session_started_at").write_text(text)
    assert pr_queue.session_elapsed_s(env) is None


def test_time_left_never_negative(tmp_path, fb):
    env, _ = make_env(tmp_path, fb, environ={"LAUNCH_RADAR_RUN_ID": RUN_ID}, now=lambda: START + 6000)
    write_session(env)
    assert pr_queue.time_left_s(env) == 0


# ---- pr-next ------------------------------------------------------------------------------------------
def test_pr_next_claims_writes_the_claim_and_clears_the_last_attempt(tmp_path, fb):
    cid = fb.add_card("acme.ai", company="Acme")
    fb.add_pr_request(cid)
    env, cap = make_env(tmp_path, fb, environ={"LAUNCH_RADAR_RUN_ID": RUN_ID, "PATH": "/bin"})
    write_session(env)
    stale = [env.pr_dir / "scout" / f"{cid}.json", env.pr_dir / "published" / f"{cid}.json",
             env.pr_dir / "work" / str(cid) / "board.json"]
    for p in stale:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}")
    other = env.pr_dir / "scout" / "99.json"
    other.write_text("{}")

    assert pr_queue.pr_next(env) == 0
    out = cap.out[-1]
    assert out["claimed"] is True and out["card_id"] == cid and out["company"] == "Acme"
    assert out["ats"]["provider"] == "ashby" and out["time_left_s"] == 5340
    claim = json.loads((env.pr_dir / "claims" / f"{cid}.json").read_text())
    assert claim["card_id"] == cid and claim["domain"] == "acme.ai" and "time_left_s" not in claim
    assert not any(p.exists() for p in stale) and not (env.pr_dir / "work" / str(cid)).exists()
    assert other.exists()  # only this card's files
    assert fb.pr_requests[cid]["status"] == "in_progress"


def test_pr_next_empty_queue(tmp_path, fb):
    env, cap = make_env(tmp_path, fb)
    assert pr_queue.pr_next(env) == 0
    assert cap.out == [{"claimed": False, "reason": "empty", "time_left_s": None}]


def test_pr_next_after_the_cutoff_claims_nothing_and_calls_nothing(tmp_path, fb):
    cid = fb.add_card("acme.ai")
    fb.add_pr_request(cid)
    runner = Runner()
    env, cap = make_env(tmp_path, fb, runner=runner, environ={"LAUNCH_RADAR_RUN_ID": RUN_ID},
                        now=lambda: START + 3300)
    write_session(env)
    assert pr_queue.pr_next(env) == 0
    assert cap.out == [{"claimed": False, "reason": "time", "time_left_s": 2100}]
    assert fb.requests == [] and runner.calls == []
    assert fb.pr_requests[cid]["status"] == "queued"


def test_pr_next_just_before_the_cutoff_still_claims(tmp_path, fb):
    cid = fb.add_card("acme.ai")
    fb.add_pr_request(cid)
    env, cap = make_env(tmp_path, fb, environ={"LAUNCH_RADAR_RUN_ID": RUN_ID}, now=lambda: START + 3299)
    write_session(env)
    assert pr_queue.pr_next(env) == 0 and cap.out[-1]["claimed"] is True


def test_pr_next_interactive_run_is_never_refused_by_a_nightly_file(tmp_path, fb):
    cid = fb.add_card("acme.ai")
    fb.add_pr_request(cid)
    env, cap = make_env(tmp_path, fb, environ={}, now=lambda: START + 99_999)
    write_session(env)
    assert pr_queue.pr_next(env) == 0 and cap.out[-1]["claimed"] is True
    assert cap.out[-1]["time_left_s"] is None


@pytest.mark.parametrize("check", ["gh_auth", "gh_push", "git_remote", "logo_venv"])
def test_each_preflight_failure_claims_nothing_and_exits_1(tmp_path, fb, check):
    cid = fb.add_card("acme.ai")
    fb.add_pr_request(cid)
    env, cap = make_env(tmp_path, fb, runner=Runner(fail=check))
    assert pr_queue.pr_next(env) == 1
    assert json.loads(cap.err[-1]) == {"preflight": "failed", "check": check}
    assert cap.out == [] and fb.requests == []
    assert fb.pr_requests[cid]["status"] == "queued" and not (env.pr_dir / "claims").exists()


def test_preflight_without_a_logo_venv_fails_without_running_it(tmp_path, fb):
    runner = Runner()
    env, cap = make_env(tmp_path, fb, runner=runner, venv=False)
    assert pr_queue.pr_next(env) == 1
    assert json.loads(cap.err[-1]) == {"preflight": "failed", "check": "logo_venv"}
    assert len(runner.calls) == 3  # gh auth, gh api, ls-remote; never the missing python


@pytest.mark.parametrize("exc", [FileNotFoundError("gh"), subprocess.TimeoutExpired(["gh"], 60)])
def test_preflight_a_missing_tool_or_a_hang_is_a_failure(tmp_path, fb, exc):
    def runner(argv, **kw):
        raise exc

    env, cap = make_env(tmp_path, fb, runner=runner)
    assert pr_queue.pr_next(env) == 1
    assert json.loads(cap.err[-1])["check"] == "gh_auth"


def test_preflight_argv_and_env_are_fixed_and_scrubbed(tmp_path, fb):
    runner = Runner()
    secrets = {"INTERNAL_API_KEY": "s3cret", "PARALLEL_API_KEY": "p4r", "BACKEND_URL": "https://b",
               "GIT_DIR": "/evil", "GH_TOKEN": "t", "PYTHONPATH": "/evil"}
    env, _ = make_env(tmp_path, fb, runner=runner,
                      environ={"PATH": "/bin", "HOME": "/h", "LANG": "C", "LAUNCH_RADAR_RUN_ID": RUN_ID, **secrets})
    assert pr_queue.preflight(env) is None
    venv_py = str(env.state_dir / "logo-venv" / "bin" / "python")
    assert [c["argv"] for c in runner.calls] == [
        ["gh", "auth", "status"],
        ["gh", "api", "repos/brendanpotter00/Job-Visualizer-Notifier", "--jq", ".permissions.push"],
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "core.pager=cat",
         "-C", str(env.root), "ls-remote", "--exit-code", "origin", "refs/heads/main"],
        [venv_py, "-I", "-c", "import PIL, cairosvg"],
    ]
    for c in runner.calls:
        assert c["env"] == {"PATH": "/bin", "HOME": "/h", "LANG": "C", "LAUNCH_RADAR_RUN_ID": RUN_ID,
                            "LAUNCH_RADAR_STATE_DIR": str(env.state_dir), "GIT_TERMINAL_PROMPT": "0",
                            "GH_PROMPT_DISABLED": "1"}
        assert c["cwd"] == env.root


def test_gh_push_must_print_exactly_true(tmp_path, fb):
    def runner(argv, **kw):
        out = "false\n" if "api" in argv else ""
        return subprocess.CompletedProcess(argv, 0, out, "")

    env, _ = make_env(tmp_path, fb, runner=runner)
    assert pr_queue.preflight(env) == "gh_push"


def test_pr_next_backend_error_exits_1(tmp_path, fb):
    env, cap = make_env(tmp_path, fb)
    env.backend = BackendClient("http://backend.test", "k", transport=httpx.MockTransport(
        lambda r: httpx.Response(500, json={"detail": "boom"})))
    assert pr_queue.dispatch("pr-next", None, env) == 1
    assert "backend error" in cap.err[-1] and cap.out == []


def test_pr_next_refuses_a_malformed_claim(tmp_path, fb):
    env, cap = make_env(tmp_path, fb)
    env.backend = BackendClient("http://backend.test", "k", transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"card_id": "../../etc"})))
    assert pr_queue.pr_next(env) == 1
    assert not (env.pr_dir / "claims").exists()


# ---- pr-check -------------------------------------------------------------------------------------
def test_pr_check_proceeds_while_saved_and_in_progress(tmp_path, fb):
    cid = fb.add_card("acme.ai")
    fb.add_pr_request(cid, "in_progress", attempts=1)
    env, cap = make_env(tmp_path, fb)
    assert pr_queue.pr_check(env, cid) == 0
    assert cap.out == [{"proceed": True}]
    assert fb.pr_requests[cid]["status"] == "in_progress"


@pytest.mark.parametrize("card_status", ["new", "archived"])
def test_pr_check_records_cancelled_when_the_card_was_unsaved(tmp_path, fb, card_status):
    cid = fb.add_card("acme.ai", status=card_status)
    fb.add_pr_request(cid, "in_progress", attempts=1)
    env, cap = make_env(tmp_path, fb)
    assert pr_queue.pr_check(env, cid) == 0
    assert cap.out == [{"proceed": False, "why": "unsaved"}]
    assert fb.pr_requests[cid]["status"] == "cancelled"
    assert ("backend", "pr_result", (cid, "cancelled", None)) in fb.journal


def test_pr_check_deleted_card_is_not_an_error(tmp_path, fb):
    cid = fb.add_card("acme.ai", status="deleted")
    fb.add_pr_request(cid, "in_progress")
    env, cap = make_env(tmp_path, fb)
    assert pr_queue.pr_check(env, cid) == 0
    assert cap.out == [{"proceed": False, "why": "deleted"}]
    assert pr_queue.pr_check(env, 777) == 0 and cap.out[-1] == {"proceed": False, "why": "deleted"}


def test_pr_check_a_request_no_longer_in_progress_does_not_proceed(tmp_path, fb):
    cid = fb.add_card("acme.ai")
    fb.add_pr_request(cid, "queued", attempts=1)  # recovered as stale by another claim
    env, cap = make_env(tmp_path, fb)
    assert pr_queue.pr_check(env, cid) == 0
    assert cap.out == [{"proceed": False, "why": "not_in_progress", "status": "queued"}]


def test_pr_check_resaved_between_read_and_cancel_proceeds(tmp_path, fb):
    cid = fb.add_card("acme.ai", status="new")
    fb.add_pr_request(cid, "in_progress", attempts=1)
    env, cap = make_env(tmp_path, fb)
    real = env.backend.pr_result

    def resave_first(card_id, outcome, **kw):
        fb.card_by_id(card_id)[1]["status"] = "saved"  # the owner saved it again
        return real(card_id, outcome, **kw)

    env.backend.pr_result = resave_first
    assert pr_queue.pr_check(env, cid) == 0
    assert cap.out == [{"proceed": True}]


def test_pr_check_backend_error_exits_1(tmp_path, fb):
    env, cap = make_env(tmp_path, fb)
    env.backend = BackendClient("http://backend.test", "k",
                                transport=httpx.MockTransport(lambda r: httpx.Response(503, json={})))
    assert pr_queue.dispatch("pr-check", type("A", (), {"card_id": 3})(), env) == 1


def test_pr_check_transport_error_exits_1(tmp_path, fb):
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    env, cap = make_env(tmp_path, fb)
    env.backend = BackendClient("http://backend.test", "k", transport=httpx.MockTransport(refuse))
    assert pr_queue.dispatch("pr-check", type("A", (), {"card_id": 3})(), env) == 1
    assert "unreachable" in cap.err[-1]


# ---- pr-report ------------------------------------------------------------------------------------
def test_pr_report_open_reads_the_url_from_the_published_file(tmp_path, fb):
    cid = fb.add_card("acme.ai")
    fb.add_pr_request(cid, "in_progress", attempts=1)
    env, cap = make_env(tmp_path, fb)
    published(env, cid)
    assert pr_queue.pr_report(env, cid, "open", None) == 0
    assert fb.pr_requests[cid]["pr_url"] == URL and fb.pr_requests[cid]["pr_number"] == 412
    assert cap.out[-1]["status"] == "open"
    body = json.loads(fb.requests[-1].content)
    assert body == {"outcome": "open", "pr_url": URL, "reason": None}


@pytest.mark.parametrize("fields", [
    {"card_id": 99},
    {"card_id": "1"},
    {"card_id": True},
    {"dry_run": True},
    {"dry_run": None},
    {"pr_url": None},
    {"pr_url": "https://github.com/someone/fork/pull/1"},
    {"pr_url": URL + "\n"},
    {"pr_url": URL + "/files"},
    {"pr_url": "http://github.com/brendanpotter00/Job-Visualizer-Notifier/pull/1"},
])
def test_pr_report_open_refuses_a_bad_published_record_without_calling_the_backend(tmp_path, fb, fields):
    cid = fb.add_card("acme.ai")
    fb.add_pr_request(cid, "in_progress")
    env, cap = make_env(tmp_path, fb)
    published(env, cid, **fields)
    assert pr_queue.pr_report(env, cid, "open", None) == 1
    assert fb.requests == [] and cap.out == []


def test_pr_report_open_with_no_or_garbled_file(tmp_path, fb):
    env, cap = make_env(tmp_path, fb)
    assert pr_queue.pr_report(env, 5, "open", None) == 1
    p = published(env, 5)
    p.write_text("not json")
    assert pr_queue.pr_report(env, 5, "open", None) == 1
    p.write_text("[]")
    assert pr_queue.pr_report(env, 5, "open", None) == 1
    p.unlink()
    target = tmp_path / "elsewhere.json"
    target.write_text(json.dumps({"card_id": 5, "dry_run": False, "pr_url": URL}))
    p.symlink_to(target)
    assert pr_queue.pr_report(env, 5, "open", None) == 1
    assert fb.requests == []


def test_pr_report_404_is_card_deleted_and_exits_0(tmp_path, fb):
    cid = fb.add_card("acme.ai", status="deleted")
    fb.add_pr_request(cid, "in_progress")
    env, cap = make_env(tmp_path, fb)
    published(env, cid)
    assert pr_queue.pr_report(env, cid, "open", None) == 0
    assert cap.out == [{"card_deleted": True, "pr_url": URL}]
    assert pr_queue.pr_report(env, 4242, "failed", "git_error") == 0
    assert cap.out[-1] == {"card_deleted": True, "pr_url": None}


@pytest.mark.parametrize("outcome,reason,status", [
    ("failed", "gh_error", "queued"),
    ("failed", "unsafe_value", "failed"),
    ("failed", "env_error", "queued"),
    ("no_board", "unsupported_ats", "no_board"),
    ("already_tracked", None, "already_tracked"),
])
def test_pr_report_other_outcomes(tmp_path, fb, outcome, reason, status):
    cid = fb.add_card("acme.ai")
    fb.add_pr_request(cid, "in_progress", attempts=1)
    env, cap = make_env(tmp_path, fb)
    assert pr_queue.pr_report(env, cid, outcome, reason) == 0
    assert fb.pr_requests[cid]["status"] == status and cap.out[-1]["status"] == status
    assert json.loads(fb.requests[-1].content) == {"outcome": outcome, "pr_url": None, "reason": reason}


@pytest.mark.parametrize("outcome,reason", [
    ("failed", None), ("no_board", None), ("open", "gh_error"), ("already_tracked", "board_empty"),
    ("failed", "board_empty"), ("no_board", "gh_error"),
])
def test_pr_report_bad_outcome_reason_pair_is_refused_locally(tmp_path, fb, outcome, reason):
    env, cap = make_env(tmp_path, fb)
    published(env, 5)
    assert pr_queue.pr_report(env, 5, outcome, reason) == 1
    assert fb.requests == []


def test_pr_report_409_is_an_error(tmp_path, fb):
    cid = fb.add_card("acme.ai")
    fb.add_pr_request(cid, "queued")
    env, cap = make_env(tmp_path, fb)
    assert pr_queue.dispatch("pr-report", type("A", (), {"card_id": cid, "outcome": "failed",
                                                          "reason": "other"})(), env) == 1
    assert "409" in cap.err[-1]


# ---- pr-refresh -----------------------------------------------------------------------------------
def _open_cards(fb, n):
    ids = []
    for i in range(n):
        cid = fb.add_card(f"c{i}.ai")
        fb.add_pr_request(cid, "open", pr_url=f"{URL[:-3]}{100 + i}", pr_number=100 + i)
        ids.append(cid)
    return ids


def test_pr_refresh_runs_each_open_card_with_fixed_argv_and_a_scrubbed_env(tmp_path, fb):
    ids = _open_cards(fb, 2)
    queued = fb.add_card("q.ai")
    fb.add_pr_request(queued, "queued")
    runner = Runner()
    environ = {"PATH": "/bin", "HOME": "/h", "LANG": "en_US.UTF-8", "LAUNCH_RADAR_RUN_ID": RUN_ID,
               "LAUNCH_RADAR_STATE_DIR": "/somewhere/else", "INTERNAL_API_KEY": "s3cret",
               "PARALLEL_API_KEY": "p", "BACKEND_URL": "https://b", "GIT_DIR": "/evil", "PYTHONPATH": "/evil"}
    env, cap = make_env(tmp_path, fb, runner=runner, environ=environ)
    assert pr_queue.pr_refresh(env) == 0
    children = [c for c in runner.calls if "refresh" in c["argv"]]
    pr_step = str(env.root / "scripts" / "launch_radar" / "pr_step.py")
    assert [c["argv"] for c in children] == [[sys.executable, "-I", pr_step, "refresh", "--card-id", str(i)]
                                             for i in ids]
    for c in children:
        assert c["env"] == {"PATH": "/bin", "HOME": "/h", "LANG": "en_US.UTF-8", "LAUNCH_RADAR_RUN_ID": RUN_ID,
                            "LAUNCH_RADAR_STATE_DIR": str(env.state_dir)}
        assert c["cwd"] == env.root
    assert len(runner.calls) == 4 + 2  # preflight, then one child per open card
    assert cap.out[-1] == {"open": 2, "refreshed": 2, "failed": 0, "attention": [], "stopped": None,
                           "time_left_s": None,
                           "results": [{"card_id": i, "refreshed": True, "why": "rebuilt"} for i in ids]}
    q = [r for r in fb.requests if r.url.path.endswith("/pr-requests")]
    assert q and q[0].url.params.get_list("status") == ["open"]


def test_pr_refresh_failed_preflight_exits_1_and_lists_nothing(tmp_path, fb):
    _open_cards(fb, 1)
    runner = Runner(fail="git_remote")
    env, cap = make_env(tmp_path, fb, runner=runner)
    assert pr_queue.pr_refresh(env) == 1
    assert fb.requests == [] and json.loads(cap.err[-1])["check"] == "git_remote"
    assert not any("refresh" in c["argv"] for c in runner.calls)


def test_pr_refresh_stops_starting_at_the_cutoff(tmp_path, fb):
    ids = _open_cards(fb, 3)
    clock = {"t": START + 3000}

    def refresh(card_id):
        clock["t"] += 200  # each refresh takes 200 s
        return 0, json.dumps({"card_id": card_id, "refreshed": True, "why": "rebuilt"}), ""

    env, cap = make_env(tmp_path, fb, runner=Runner(refresh=refresh), environ={"LAUNCH_RADAR_RUN_ID": RUN_ID},
                        now=lambda: clock["t"])
    write_session(env)
    assert pr_queue.pr_refresh(env) == 0
    out = cap.out[-1]
    assert [r["card_id"] for r in out["results"]] == ids[:2] and out["stopped"] == "time"
    assert out["time_left_s"] == 5400 - 3400


def test_pr_refresh_after_the_cutoff_does_nothing(tmp_path, fb):
    _open_cards(fb, 1)
    runner = Runner()
    env, cap = make_env(tmp_path, fb, runner=runner, environ={"LAUNCH_RADAR_RUN_ID": RUN_ID},
                        now=lambda: START + 4000)
    write_session(env)
    assert pr_queue.pr_refresh(env) == 0
    assert cap.out[-1]["stopped"] == "time" and runner.calls == [] and fb.requests == []


def test_pr_refresh_a_failing_child_is_reported_not_an_error(tmp_path, fb):
    ids = _open_cards(fb, 4)
    outcomes = {
        ids[0]: (1, json.dumps({"error": "push refused", "report_reason": "git_error"}), "fatal: x"),
        ids[1]: (0, "garbage", ""),
        ids[2]: (0, json.dumps({"card_id": ids[2], "refreshed": False, "why": "pushed_by_someone"}), ""),
        ids[3]: (0, json.dumps({"card_id": 999, "refreshed": True}), ""),
    }
    env, cap = make_env(tmp_path, fb, runner=Runner(refresh=lambda cid: outcomes[cid]))
    assert pr_queue.pr_refresh(env) == 0
    assert cap.out[-1]["results"] == [
        {"card_id": ids[0], "refreshed": False, "why": "error", "report_reason": "git_error"},
        {"card_id": ids[1], "refreshed": False, "why": "bad_output"},
        {"card_id": ids[2], "refreshed": False, "why": "pushed_by_someone"},
        {"card_id": ids[3], "refreshed": False, "why": "bad_output"},
    ]
    assert cap.out[-1]["refreshed"] == 0
    assert cap.out[-1]["failed"] == 3 and cap.out[-1]["attention"] == [ids[2]]


@pytest.mark.parametrize("why, failed, attention", [
    ("pushed_by_someone", 0, True), ("slug_taken", 0, True), ("now_tracked", 0, True), ("no_record", 0, True),
    ("not_open", 0, False), ("up_to_date", 0, False),
])
def test_pr_refresh_skips_that_leave_a_pr_stale_are_flagged(tmp_path, fb, why, failed, attention):
    ids = _open_cards(fb, 1)
    out = json.dumps({"card_id": ids[0], "refreshed": False, "why": why})
    env, cap = make_env(tmp_path, fb, runner=Runner(refresh=lambda cid: (0, out, "")))
    assert pr_queue.pr_refresh(env) == 0
    assert cap.out[-1]["failed"] == failed
    assert cap.out[-1]["attention"] == (ids if attention else [])


def test_pr_refresh_child_timeout(tmp_path, fb):
    ids = _open_cards(fb, 1)

    def runner(argv, **kw):
        if "refresh" in argv:
            raise subprocess.TimeoutExpired(argv, 900)
        return subprocess.CompletedProcess(argv, 0, "true\n", "")

    env, cap = make_env(tmp_path, fb, runner=runner)
    assert pr_queue.pr_refresh(env) == 0
    assert cap.out[-1]["results"] == [{"card_id": ids[0], "refreshed": False, "why": "timeout"}]
    assert cap.out[-1]["failed"] == 1


def test_pr_refresh_with_nothing_open(tmp_path, fb):
    env, cap = make_env(tmp_path, fb)
    assert pr_queue.pr_refresh(env) == 0
    assert cap.out[-1] == {"open": 0, "refreshed": 0, "failed": 0, "attention": [], "results": [], "stopped": None,
                           "time_left_s": None}


# ---- pr-requeue and pr-status -------------------------------------------------------------------------
def test_pr_requeue(tmp_path, fb):
    cid = fb.add_card("acme.ai")
    fb.add_pr_request(cid, "failed", attempts=3, last_reason="gh_error")
    env, cap = make_env(tmp_path, fb)
    assert pr_queue.pr_requeue(env, cid) == 0
    assert fb.pr_requests[cid]["status"] == "queued" and fb.pr_requests[cid]["attempts"] == 0
    assert pr_queue.pr_requeue(env, cid) == 1  # already queued: 409
    assert "refused" in cap.err[-1]
    assert pr_queue.pr_requeue(env, 999) == 1
    assert "no PR request" in cap.err[-1]


def test_pr_status_prints_a_table_without_terminal_escapes(tmp_path, fb, capsys):
    cid = fb.add_card("acme.ai", company="Acme\x1b[31m Evil")
    fb.add_pr_request(cid, "open", pr_url=URL, pr_number=412)
    other = fb.add_card("b.ai")
    fb.add_pr_request(other, "queued")
    env, _ = make_env(tmp_path, fb)
    assert pr_queue.pr_status(env, ["open"]) == 0
    text = capsys.readouterr().out
    assert "card_id" in text and URL in text and "\x1b" not in text and "Acme?[31m Evil" in text
    assert "b.ai" not in text and "1 request(s)" in text


def test_valid_card_id():
    assert pr_queue.valid_card_id("12") == 12 and pr_queue.valid_card_id(7) == 7
    for bad in ("0", "012", "-1", "1a", "", "12345678901", True, 1.5, None, "../1"):
        with pytest.raises(ValueError):
            pr_queue.valid_card_id(bad)


def test_pr_url_pattern_is_the_backends():
    """SEAM: the loop accepts exactly the backend's (and the DB CHECK's) PR URL pattern."""
    models = Path(__file__).resolve().parents[3] / "src" / "backend" / "api" / "models.py"
    text = models.read_text()
    assert f'r"{pr_queue.PR_URL_PATTERN}"' in text


def test_pr_url_pattern_copies_agree():
    """SEAM (CONTRACT §9): pr_step.py and the admin page's format.ts accept exactly the URLs
    the loop's (= the backend's) pattern accepts, as full matches."""
    from launch_radar import pr_step

    fmt = Path(__file__).resolve().parents[3] / "src" / "frontend" / "src" / "pages" / "AdminLaunchRadarPage" / "format.ts"
    m = re.search(r"const PR_URL_RE = /\^(.+)\$/;", fmt.read_text())
    assert m, "format.ts: PR_URL_RE literal not found"
    ts_re = re.compile(m.group(1).replace(r"\/", "/"), re.ASCII)
    base = "https://github.com/brendanpotter00/Job-Visualizer-Notifier/pull/"
    good = [base + "1", base + "412", base + "2147483647"]
    bad = [base, base + "12/files", base + "12#x", base + "12?a=1", base + "12\n", base + "x1",
           "http://github.com/brendanpotter00/Job-Visualizer-Notifier/pull/1",
           "https://github.com/someone/Job-Visualizer-Notifier/pull/1",
           "https://github.com/brendanpotter00/other/pull/1",
           "https://github.com.evil.io/brendanpotter00/Job-Visualizer-Notifier/pull/1",
           "javascript:alert(1)"]
    for url in good + bad:
        want = bool(pr_queue.PR_URL_RE.fullmatch(url))
        assert want == (url in good), url
        assert bool(pr_step.PR_URL_RE.fullmatch(url)) == want, f"pr_step.py: {url!r}"
        assert bool(ts_re.fullmatch(url)) == want, f"format.ts: {url!r}"
