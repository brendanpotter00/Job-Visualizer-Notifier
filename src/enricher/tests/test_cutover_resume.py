"""cutover.py — resume table, first-tick verdict, state file, CLI contract.

Every `--run` start re-derives reality (where the plist points, whether the new
prod exists and carries `.cutover-owned`) before trusting `phase` (PLAN §4.6).
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from test_cutover_ref import SCRIPTS, load_cutover
from test_cutover_plist import prod_plist

co = load_cutover()
CUTOVER_PY = SCRIPTS / "cutover" / "cutover.py"


@pytest.mark.parametrize(
    "phase, where, new_exists, new_owned, state_exists, action",
    [
        # terminal: never act again
        ("DONE", "new", True, False, True, "noop_done"),
        ("FAILED", "old", True, True, True, "noop_failed"),
        ("ROLLED_BACK", "old", True, False, True, "noop_rolled_back"),
        # a rollback in progress always continues, wherever the plist points
        ("ROLLING_BACK", "new", True, False, True, "rollback"),
        ("ROLLING_BACK", "old", True, False, True, "rollback"),
        # plist -> old prod
        ("PENDING", "old", False, False, False, "start"),
        ("PENDING", "old", False, False, True, "start"),
        ("PREPARED", "old", True, True, True, "redo"),       # crashed after the clone
        ("COPIED", "old", True, True, True, "redo"),         # crashed after the copy
        ("SWAPPING", "old", True, True, True, "redo"),       # crashed before the plist write
        ("PENDING", "old", True, False, True, "refuse_unowned_new"),
        ("PENDING", "old", True, False, False, "refuse_unowned_new"),
        # plist -> new prod
        ("SWAPPING", "new", True, True, True, "continue_swap"),  # crashed right after the write
        ("SWAPPED", "new", True, False, True, "continue_swap"),  # never re-copies the DB
        ("VERIFIED", "new", True, False, True, "retire"),
        ("PENDING", "new", True, False, False, "refuse_new_without_state"),
        ("COPIED", "new", True, True, True, "refuse_inconsistent"),
        # plist anywhere else
        ("PENDING", "other", False, False, True, "refuse_plist_elsewhere"),
        ("SWAPPED", "missing", True, False, True, "refuse_plist_elsewhere"),
    ],
)
def test_resume_table(phase, where, new_exists, new_owned, state_exists, action):
    assert co.decide_resume(phase, where, new_exists, new_owned, state_exists) == action


def test_every_refusal_has_a_message():
    actions = {co.decide_resume(p, w, e, o, s)
               for p in ("PENDING", "COPIED", "SWAPPED") for w in ("old", "new", "other", "missing")
               for e in (True, False) for o in (True, False) for s in (True, False)}
    for a in actions:
        if a.startswith("refuse"):
            assert a in co.REFUSALS


T = co.Tick


@pytest.mark.parametrize(
    "tick, old, ok",
    [
        (T(10, "ok", 40, 40, 40), [], True),
        (T(10, "ok", 0, 0, 0), [], True),                       # nothing to claim: same as old prod
        (T(10, "error", 40, 40, 40), [], False),
        (T(10, "running", 40, 0, 0), [], False),
        (T(10, "ok", 40, 0, 0), [], False),                     # claimed but did no work
        (T(10, "ok", 40, 40, 0), [], False),                    # classified but sent nothing
        # ... unless the old prod's last 3 closed ticks stalled exactly the same way
        (T(10, "ok", 40, 0, 0), [T(9, "ok", 40, 0, 0), T(8, "ok", 40, 40, 0), T(7, "ok", 5, 0, 0)], True),
        (T(10, "ok", 40, 0, 0), [T(9, "ok", 40, 0, 0), T(8, "ok", 40, 40, 40), T(7, "ok", 5, 0, 0)], False),
        (T(10, "ok", 40, 0, 0), [T(9, "ok", 40, 0, 0), T(8, "ok", 40, 0, 0)], False),  # < 3 ticks
    ],
)
def test_first_tick_verdict(tick, old, ok):
    assert co.judge_first_tick(tick, old)[0] is ok


# ------------------------------------------------------------------ state file + watcher contract
WATCHER_TERMINAL = re.compile(r'^  "phase": "(DONE|FAILED|ROLLED_BACK)"', re.M)


@pytest.mark.parametrize("phase", ["DONE", "FAILED", "ROLLED_BACK"])
def test_watcher_sees_terminal_phases(tmp_path, phase):
    st = co.State.load(tmp_path / "state.json")
    st.data["failure"] = {"phase": "nested-key-must-not-confuse-the-watcher"}
    st.set_phase(phase)
    assert WATCHER_TERMINAL.search((tmp_path / "state.json").read_text())


@pytest.mark.parametrize("phase", ["PENDING", "PREPARED", "SWAPPING", "SWAPPED", "VERIFIED", "ROLLING_BACK"])
def test_watcher_keeps_going_on_live_phases(tmp_path, phase):
    st = co.State.load(tmp_path / "state.json")
    st.data["nested"] = {"phase": "DONE"}  # indented deeper: not the top-level phase
    st.set_phase(phase)
    assert not WATCHER_TERMINAL.search((tmp_path / "state.json").read_text())


def test_the_watcher_greps_the_same_pattern():
    text = (SCRIPTS / "cutover" / "watcher.sh").read_text()
    assert "'^  \"phase\": \"(DONE|FAILED|ROLLED_BACK)\"'" in text
    assert "'^  \"phase\": \"(DONE|FAILED|ROLLED_BACK)\"'" in \
        (SCRIPTS / "cutover" / "install_watcher.sh").read_text()


def test_state_is_written_atomically_and_round_trips(tmp_path):
    st = co.State.load(tmp_path / "s" / "state.json")
    assert not st.exists and st.phase == "PENDING"
    st.data["copy_sha256"] = "ab"
    st.set_phase("COPIED")
    again = co.State.load(tmp_path / "s" / "state.json")
    assert again.exists and again.phase == "COPIED" and again.data["copy_sha256"] == "ab"
    assert again.data["history"][-1]["event"] == "phase -> COPIED"
    assert not list((tmp_path / "s").glob(".state.json.tmp-*"))


def test_single_flight(tmp_path):
    a = co.SingleFlight(tmp_path)
    assert a.acquire()
    assert not co.SingleFlight(tmp_path).acquire()  # same live pid holds it
    a.release()
    assert co.SingleFlight(tmp_path).acquire()


def test_single_flight_reclaims_a_dead_holder(tmp_path):
    p = subprocess.Popen(["/bin/sh", "-c", "exit 0"])
    p.wait()
    d = tmp_path / "cutover.lock"
    d.mkdir()
    (d / "pid").write_text(str(p.pid))
    assert co.SingleFlight(tmp_path).acquire()


# ------------------------------------------------------------------ config + module contract
def test_knobs_default_from_home(tmp_path):
    cfg = co.Config.from_env({"HOME": str(tmp_path)})
    assert cfg.old_prod == tmp_path / "developer/personal/app"
    assert cfg.new_prod == tmp_path / "developer/personal/enricher-prod"
    assert cfg.new_enricher == tmp_path / "developer/personal/enricher-prod/src/enricher"
    assert cfg.old_dev == tmp_path / "developer/personal/job-enricher"
    assert cfg.state_dir == tmp_path / "Library/Application Support/jvn-enricher-cutover"
    assert cfg.enricher_plist == tmp_path / "Library/LaunchAgents/com.bp.job-enricher.plist"
    assert cfg.send_sh == tmp_path / ".claude/skills/message-brendan/send.sh"
    assert cfg.jvn_remote_url.endswith("/brendanpotter00/Job-Visualizer-Notifier.git")
    assert (cfg.park_budget_s, cfg.first_tick_start_s, cfg.first_tick_close_s,
            cfg.first_tick_hard_cap_s, cfg.poll_s) == (14400, 900, 18000, 86400, 5)


def test_knobs_override(tmp_path):
    cfg = co.Config.from_env({"HOME": str(tmp_path), "CUTOVER_PARK_BUDGET_S": "3",
                              "CUTOVER_POLL_S": "0.2", "CUTOVER_OLD_PROD": "/x/app",
                              "LAUNCHCTL": "/stub/launchctl", "CUTOVER_POLL_S_BAD": "nope"})
    assert cfg.park_budget_s == 3 and cfg.poll_s == 0.2
    assert cfg.old_prod == Path("/x/app") and cfg.launchctl == "/stub/launchctl"
    bad = co.Config.from_env({"HOME": str(tmp_path), "CUTOVER_PARK_BUDGET_S": "soon"})
    assert bad.park_budget_s == 14400


def test_cutover_is_stdlib_only_plus_park_worker():
    tree = ast.parse(CUTOVER_PY.read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert names - set(sys.stdlib_module_names) - {"__future__"} == {"park_worker"}


def test_exit_codes():
    assert (co.EXIT_DONE, co.EXIT_DEFERRED, co.EXIT_FAILED, co.EXIT_ROLLED_BACK, co.EXIT_USAGE) == \
        (0, 10, 20, 30, 2)


def _run(args: list[str], home: Path, extra: dict[str, str] | None = None):
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", **(extra or {})}
    return subprocess.run([sys.executable, "-I", str(CUTOVER_PY), *args], capture_output=True,
                          text=True, env=env, timeout=120)


def test_cli_usage(tmp_path):
    assert _run([], tmp_path).returncode == 2
    assert _run(["--run", "--status"], tmp_path).returncode == 2
    assert _run(["--rehearse"], tmp_path).returncode == 2
    cp = _run(["--status"], tmp_path)
    assert cp.returncode == 0 and "no cutover state" in cp.stdout


def test_rehearse_needs_a_usable_empty_scratch_dir(tmp_path):
    (tmp_path / "afile").write_text("x")
    assert _run(["--rehearse", "--scratch", str(tmp_path / "afile" / "sub")], tmp_path).returncode == 2
    full = tmp_path / "full"
    full.mkdir()
    (full / "x").write_text("x")
    assert _run(["--rehearse", "--scratch", str(full)], tmp_path).returncode == 2


def test_cutover_sh_refuses_without_an_interpreter(tmp_path):
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin", "UV_BIN": "/nonexistent/uv"}
    cp = subprocess.run(["/bin/sh", str(SCRIPTS / "cutover" / "cutover.sh"), "--status"],
                        capture_output=True, text=True, env=env)
    assert cp.returncode == 20 and "no Python 3.12" in cp.stderr


def _terminal_home(tmp_path: Path, phase: str) -> Path:
    home = tmp_path / "home"
    state = home / "Library/Application Support/jvn-enricher-cutover"
    state.mkdir(parents=True)
    (state / "state.json").write_text(json.dumps({"phase": phase}, indent=2) + "\n")
    return home


@pytest.mark.parametrize("phase, code", [("DONE", 0), ("FAILED", 20), ("ROLLED_BACK", 30)])
def test_run_after_a_terminal_phase_is_a_noop(tmp_path, phase, code):
    home = _terminal_home(tmp_path, phase)
    calls = tmp_path / "calls"
    stub = tmp_path / "stub"
    stub.write_text(f"#!/bin/sh\necho \"$0 $*\" >> {calls}\nexit 0\n")
    stub.chmod(0o755)
    cp = _run(["--run"], home, {"LAUNCHCTL": str(stub), "GH_BIN": str(stub),
                                "CUTOVER_SEND_SH": str(stub)})
    assert cp.returncode == code, cp.stdout + cp.stderr
    assert not calls.exists()  # no launchctl, no gh, no text


def test_a_foreign_new_prod_dir_refuses_once_and_texts_once(tmp_path):
    home = tmp_path / "home"
    old = home / "developer/personal/app"
    old.mkdir(parents=True)
    (home / "developer/personal/enricher-prod").mkdir()          # NOT made by the cutover
    la = home / "Library/LaunchAgents"
    la.mkdir(parents=True)
    (la / "com.bp.job-enricher.plist").write_bytes(prod_plist(old=str(old)))
    texts = tmp_path / "texts"
    send = tmp_path / "send.sh"
    send.write_text(f"#!/bin/sh\necho \"$*\" >> {texts}\n")
    send.chmod(0o755)
    lc = tmp_path / "launchctl"
    lc.write_text(f"#!/bin/sh\necho \"$*\" >> {tmp_path / 'lc'}\n")
    lc.chmod(0o755)
    env = {"CUTOVER_SEND_SH": str(send), "LAUNCHCTL": str(lc)}
    cp = _run(["--run"], home, env)
    assert cp.returncode == 20, cp.stdout + cp.stderr
    state = json.loads((home / "Library/Application Support/jvn-enricher-cutover/state.json").read_text())
    assert state["phase"] == "FAILED" and "not created by the cutover" in state["failed_reason"]
    assert texts.read_text().count("FAILED") == 1
    assert _run(["--run"], home, env).returncode == 20                 # terminal now
    assert texts.read_text().count("FAILED") == 1                      # no second text
    assert not (tmp_path / "lc").exists()                              # launchd never touched
    assert (home / "developer/personal/enricher-prod").exists()        # never deleted


def test_preflight_json_is_read_only_on_an_empty_home(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    lc = tmp_path / "launchctl"
    lc.write_text(f"#!/bin/sh\necho \"$*\" >> {tmp_path / 'lc'}\nexit 1\n")
    lc.chmod(0o755)
    before = sorted(str(p) for p in home.rglob("*"))
    cp = _run(["--preflight", "--json", "--jvn-repo", str(tmp_path)], home,
              {"LAUNCHCTL": str(lc), "JVN_REMOTE_URL": str(tmp_path / "nope.git")})
    assert cp.returncode == 20
    report = json.loads(cp.stdout)
    assert report["ok"] is False
    assert {c["name"] for c in report["checks"] if not c["ok"]} >= {"old_prod_exists"}
    assert sorted(str(p) for p in home.rglob("*")) == before
    calls = (tmp_path / "lc").read_text().split("\n") if (tmp_path / "lc").exists() else []
    assert all(c.split(" ")[0] in ("", "list", "print") for c in calls)
