"""scripts/lib/park_worker.py — park the worker BETWEEN ticks (cutover + deploy.sh).

No launchd, no network. Live lock holders are real `sleep` processes; dead
pids come from processes we spawned and reaped.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1] / "scripts" / "lib"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

import park_worker as pw  # noqa: E402

WRAPPER = "/x/prod/scripts/enrich_tick_wrapper.sh"


def _dead_pid() -> int:
    p = subprocess.Popen(["/bin/sh", "-c", "exit 0"])
    p.wait()
    return p.pid


@pytest.fixture
def live_pid():
    p = subprocess.Popen(["sleep", "60"])
    yield p.pid
    p.kill()
    p.wait()


@pytest.fixture
def lock(tmp_path) -> Path:
    return tmp_path / "data" / ".tick.lock"


class FakeTime:
    """A wall + monotonic clock that only moves when slept (no real waiting)."""

    def __init__(self) -> None:
        self.wall = 1_000_000.0
        self.mono = 50.0

    def sleep(self, s: float) -> None:
        self.wall += s
        self.mono += s

    def clock(self, poll_s: float = 1.0) -> pw.WallClock:
        return pw.WallClock(poll_s, wall=lambda: self.wall, mono=lambda: self.mono, sleep=self.sleep)


def no_procs():
    return []


def test_payload_is_the_enrichers_own_lock_format():
    p = pw.make_payload(4242)
    pid, _, ts = p.partition("|")
    assert pid == "4242" and ts.endswith("Z")
    assert pw.payload_pid(p) == 4242
    assert pw.payload_pid("garbage") is None


def test_claims_an_absent_lock_with_o_excl(lock):
    payload = pw.make_payload(os.getpid())
    res = pw.claim(lock, WRAPPER, 5, payload, processes=no_procs, boot=lambda: None, log=lambda m: None)
    assert res.claimed and res.reclaimed is None
    assert lock.read_text() == payload


def test_waits_out_a_live_tick_and_gives_up_at_the_budget(lock, live_pid):
    foreign = f"{live_pid}|2026-01-01T00:00:00Z"
    lock.parent.mkdir(parents=True)
    lock.write_text(foreign)
    ft = FakeTime()
    res = pw.claim(lock, WRAPPER, 30, pw.make_payload(os.getpid()), poll_s=1, clock=ft.clock(1),
                   processes=no_procs, boot=lambda: None, log=lambda m: None)
    assert not res.claimed
    assert "budget exhausted" in res.reason and str(live_pid) in res.reason
    assert lock.read_text() == foreign  # never touched a live tick's lock
    assert ft.wall - 1_000_000.0 >= 30


def test_claims_in_the_gap_right_after_the_tick_releases(lock, live_pid):
    lock.parent.mkdir(parents=True)
    lock.write_text(f"{live_pid}|2026-01-01T00:00:00Z")
    threading.Timer(0.3, lambda: lock.unlink()).start()  # tick-end releases the lock
    payload = pw.make_payload(os.getpid())
    res = pw.claim(lock, WRAPPER, 10, payload, poll_s=0.05, processes=no_procs,
                   boot=lambda: None, log=lambda m: None)
    assert res.claimed and lock.read_text() == payload
    assert res.holder_pid == live_pid


def test_reclaims_an_orphan_dead_pid_and_no_wrapper(lock):
    lock.parent.mkdir(parents=True)
    lock.write_text(f"{_dead_pid()}|2026-01-01T00:00:00Z")
    payload = pw.make_payload(os.getpid())
    res = pw.claim(lock, WRAPPER, 5, payload, processes=no_procs, boot=lambda: None, log=lambda m: None)
    assert res.claimed and res.reclaimed == "orphan"
    assert lock.read_text() == payload
    assert not list(lock.parent.glob(".tick.lock.steal.*"))


def test_dead_pid_while_a_wrapper_runs_is_a_tick_starting_not_an_orphan(lock):
    """tick-acquire's short-lived python wrote the lock; the wrapper is about to
    rewrite it with its own pid. Reclaiming here would steal a starting tick."""
    raw = f"{_dead_pid()}|2026-01-01T00:00:00Z"
    lock.parent.mkdir(parents=True)
    lock.write_text(raw)
    ft = FakeTime()
    procs = lambda: [(999_001, 1, f"/bin/sh {WRAPPER}"), (999_002, 999_001, "/opt/homebrew/bin/uv run")]  # noqa: E731
    res = pw.claim(lock, WRAPPER, 10, pw.make_payload(os.getpid()), clock=ft.clock(1),
                   processes=procs, boot=lambda: None, log=lambda m: None)
    assert not res.claimed
    assert "starting" in res.reason
    assert lock.read_text() == raw


def test_a_lock_written_before_this_boot_is_reclaimed_even_with_a_live_pid(lock, live_pid):
    lock.parent.mkdir(parents=True)
    lock.write_text(f"{live_pid}|2026-01-01T00:00:00Z")
    mtime = lock.stat().st_mtime
    res = pw.claim(lock, WRAPPER, 5, pw.make_payload(os.getpid()), processes=no_procs,
                   boot=lambda: mtime + 100, log=lambda m: None)
    assert res.claimed and res.reclaimed == "orphan"


def test_takes_back_its_own_lock_from_an_earlier_crashed_run(lock):
    old = f"{_dead_pid()}|2026-01-01T00:00:00Z"
    lock.parent.mkdir(parents=True)
    lock.write_text(old)
    procs = lambda: [(999_001, 1, f"/bin/sh {WRAPPER}"), (999_002, 999_001, "uv run")]  # noqa: E731
    payload = pw.make_payload(os.getpid())
    res = pw.claim(lock, WRAPPER, 5, payload, known_payloads=[old], processes=procs,
                   boot=lambda: None, log=lambda m: None)
    assert res.claimed and res.reclaimed == "own"
    assert lock.read_text() == payload


def test_reclaim_puts_back_a_lock_that_changed_under_it(lock):
    lock.parent.mkdir(parents=True)
    lock.write_text("123|new-tick")
    assert pw.reclaim(lock, "123|old-orphan", "456|ours", log=lambda m: None) is False
    assert lock.read_text() == "123|new-tick"
    assert not list(lock.parent.glob(".tick.lock.steal.*"))


def test_release_removes_only_our_lock(lock, live_pid):
    lock.parent.mkdir(parents=True)
    lock.write_text(f"{live_pid}|x")
    assert pw.release(lock, owner_pid=os.getpid()) is False
    assert pw.release(lock, payload="someone|else") is False
    assert lock.exists()
    assert pw.release(lock, owner_pid=live_pid) is True
    assert not lock.exists()
    lock.write_text("1|ours")
    assert pw.release(lock, payload="1|ours") is True
    assert pw.release(lock, payload="1|ours") is False  # absent: no error


@pytest.mark.parametrize(
    "rows, expected",
    [
        ([(10, 1, f"/bin/sh {WRAPPER}"), (11, 10, "/opt/homebrew/bin/uv run python -m x")], [10]),
        ([(10, 1, f"/bin/sh {WRAPPER}"), (11, 10, f"/bin/sh {WRAPPER}"), (12, 11, "sleep 10800")], [10, 11]),
        # orphaned watchdog subshell: re-parented to launchd, only a sleep child
        ([(20, 1, f"/bin/sh {WRAPPER}"), (21, 20, "sleep 10800")], []),
        ([(20, 1, f"/bin/sh {WRAPPER}"), (21, 20, "/bin/sleep 600")], []),
        # an orphaned STAGES subshell still does work: it counts
        ([(30, 1, f"/bin/sh {WRAPPER}"), (31, 30, "/opt/homebrew/bin/uv run python -m job_enricher.cli judge-run")], [30]),
        ([(40, 1, "/bin/sh /other/checkout/scripts/enrich_tick_wrapper.sh")], []),
    ],
)
def test_wrapper_pids(rows, expected):
    assert pw.wrapper_pids(WRAPPER, procs=rows) == expected


def test_wrapper_pids_against_the_real_process_table():
    p = subprocess.Popen(["/bin/sh", "-c", "sleep 30", "/tmp/fake-checkout/scripts/enrich_tick_wrapper.sh"])
    try:
        time.sleep(0.2)
        rows = pw.list_processes()
        assert any(pid == p.pid for pid, _pp, _c in rows)
        assert pw.wrapper_pids("/no/such/checkout/scripts/enrich_tick_wrapper.sh", procs=rows) == []
    finally:
        p.kill()
        p.wait()


@pytest.mark.parametrize(
    "rows, expected",
    [
        # prod's shape: wrapper -> stages subshell -> uv -> the venv's python
        ([(10, 1, f"/bin/sh {WRAPPER}"), (11, 10, f"/bin/sh {WRAPPER}"),
          (12, 11, "/opt/homebrew/bin/uv run python -m job_enricher.cli classify-run"),
          (13, 12, "/x/prod/.venv/bin/python3 -m job_enricher.cli classify-run")], [12, 13]),
        # a venv built on a macOS framework Python: the interpreter it spawns
        # lives OUTSIDE the checkout, so only descent can find the stage
        ([(10, 1, f"/bin/sh {WRAPPER}"),
          (11, 10, "/opt/homebrew/bin/uv run python -m job_enricher.cli work --tick-id 4"),
          (12, 11, "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 "
                   "-m job_enricher.cli work --tick-id 4")], [11, 12]),
        # another checkout's tick: never ours to signal
        ([(20, 1, "/bin/sh /other/checkout/scripts/enrich_tick_wrapper.sh"),
          (21, 20, "/other/checkout/.venv/bin/python3 -m job_enricher.cli classify-run")], []),
        # an orphaned stage (its wrapper is gone): no root to descend from
        ([(31, 1, "/x/prod/.venv/bin/python3 -m job_enricher.cli classify-run")], []),
        # the wrapper and its watchdog are not stages
        ([(10, 1, f"/bin/sh {WRAPPER}"), (11, 10, f"/bin/sh {WRAPPER}"), (12, 11, "sleep 10800")], []),
    ],
)
def test_stage_pids(rows, expected):
    assert pw.stage_pids(WRAPPER, procs=rows) == expected


def test_stage_pids_against_the_real_process_table(tmp_path):
    wrapper = tmp_path / "scripts" / "enrich_tick_wrapper.sh"
    wrapper.parent.mkdir(parents=True)
    # Like the real wrapper: a child spelled the way a stage is, waited on.
    wrapper.write_text("#!/bin/sh\n/bin/sh -c 'sleep 5; :' python -m job_enricher.cli work &\nwait\n")
    wrapper.chmod(0o755)
    p = subprocess.Popen([str(wrapper)], start_new_session=True)
    try:
        time.sleep(0.3)
        rows = pw.list_processes()
        stage = [pid for pid, ppid, cmd in rows if ppid == p.pid and "job_enricher.cli" in cmd]
        assert stage, "the fake stage did not start"
        assert pw.stage_pids(wrapper, procs=rows) == stage
        assert pw.stage_pids("/no/such/checkout/scripts/enrich_tick_wrapper.sh", procs=rows) == []
    finally:
        os.killpg(p.pid, 9)
        p.wait()


def test_classify_holder(live_pid):
    now = time.time()
    live = pw.LockInfo(f"{live_pid}|x", live_pid, now)
    dead = pw.LockInfo("1999999999|x", 1999999999, now)
    assert pw.classify_holder(live, wrapper_running=False, boot=None) == "live"
    assert pw.classify_holder(live, wrapper_running=False, boot=now + 10) == "orphan"
    assert pw.classify_holder(dead, wrapper_running=True, boot=None) == "starting"
    assert pw.classify_holder(dead, wrapper_running=False, boot=None) == "orphan"


def test_wait_idle():
    ft = FakeTime()
    rows = [(10, 1, f"/bin/sh {WRAPPER}"), (11, 10, "uv run")]
    assert pw.wait_idle(WRAPPER, 5, clock=ft.clock(1), processes=lambda: rows) is False
    assert pw.wait_idle(WRAPPER, 5, clock=ft.clock(1), processes=lambda: []) is True


def test_boot_epoch_parses_sysctl_on_macos():
    if not Path(pw.SYSCTL_BIN).exists():
        pytest.skip("no sysctl")
    boot = pw.boot_epoch()
    if sys.platform == "darwin":
        assert boot is not None and 0 < boot < time.time()


# ---------------------------------------------------------------------------- CLI
def _cli(*args: str, timeout: float = 30) -> subprocess.CompletedProcess[str]:
    """``-S`` as well as ``-I``: no site-packages at all, so any import beyond the
    stdlib fails the run. deploy.sh and cutover.py both call this file with a bare
    interpreter, and a rolled-back checkout may have no venv at all."""
    return subprocess.run([sys.executable, "-I", "-S", str(LIB / "park_worker.py"), *args],
                          capture_output=True, text=True, timeout=timeout)


def test_cli_claim_then_release(lock):
    owner = os.getpid()
    cp = _cli("claim", "--lock", str(lock), "--wrapper", WRAPPER, "--budget-s", "5",
              "--owner-pid", str(owner))
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert pw.payload_pid(lock.read_text()) == owner
    cp = _cli("release", "--lock", str(lock), "--owner-pid", str(owner))
    assert cp.returncode == 0 and not lock.exists()


def test_cli_claim_gives_up_with_exit_10_when_a_tick_never_ends(lock, live_pid):
    lock.parent.mkdir(parents=True)
    lock.write_text(f"{live_pid}|x")
    cp = _cli("claim", "--lock", str(lock), "--wrapper", WRAPPER, "--budget-s", "0.5",
              "--poll-s", "0.1", "--owner-pid", str(os.getpid()))
    assert cp.returncode == 10
    assert lock.read_text() == f"{live_pid}|x"


def test_cli_release_leaves_a_foreign_lock(lock, live_pid):
    lock.parent.mkdir(parents=True)
    lock.write_text(f"{live_pid}|x")
    assert _cli("release", "--lock", str(lock), "--owner-pid", str(os.getpid())).returncode == 0
    assert lock.exists()


def test_cli_usage_error_is_exit_2():
    assert _cli("claim").returncode == 2
    assert _cli("bogus").returncode == 2

