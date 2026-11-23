"""EN-04 — the single-flight tick lock, through the real wrapper.

launchd fires the wrapper every 60 s and a tick lasts hours, so almost every
fire in prod lands on a held lock. The contract (``lock.py`` + the wrapper):

* a fire during a running tick prints ``lock held; skipping this fire``, exits
  **0** (exit 75 is tick-acquire's, the wrapper swallows it) and leaves the
  lock byte-for-byte and mtime untouched;
* a lock whose holder is DEAD is only reclaimed once it ages past the 3 h
  backstop — a fresh dead-holder lock still blocks;
* a lock whose mtime PREDATES THE CURRENT BOOT is reclaimed immediately, even
  when its pid is alive (that pid is post-reboot reuse, not the holder) — the
  2026-08-07 power-loss fix.

The lock file format is the enricher's own: ``"<pid>|<iso>"``.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from datetime import datetime, timezone

import pytest

import fixtures
from conftest import seed

#: Far above macOS's PID_MAX (99998): `kill(pid, 0)` answers ESRCH, so this pid
#: is dead by construction and can never be reused into a live one mid-test.
DEAD_PID = 4194304
BACKSTOP_S = 3 * 3600


def _boot_epoch() -> float:
    out = subprocess.run(["/usr/sbin/sysctl", "-n", "kern.boottime"], capture_output=True,
                         text=True, check=True).stdout
    m = re.search(r"sec\s*=\s*(\d+)", out)
    assert m, out
    return float(m.group(1))


def _plant_lock(sandbox, pid: int, mtime: float) -> str:
    sandbox.data_dir.mkdir(parents=True, exist_ok=True)
    content = f"{pid}|{datetime.now(timezone.utc).isoformat()}"
    sandbox.lock_path.write_text(content, encoding="utf-8")
    os.utime(sandbox.lock_path, (mtime, mtime))
    return content


def _lock_state(sandbox) -> tuple[str, float] | None:
    if not sandbox.lock_path.exists():
        return None
    return sandbox.lock_path.read_text(encoding="utf-8"), sandbox.lock_path.stat().st_mtime


@pytest.mark.fast
def test_en04_a_fire_during_a_running_tick_skips_and_leaves_the_lock_alone(sandbox, stub, step):
    step("seeding one row and slowing the stub's classify answer to 6 s")
    seed.reseed(fixtures.EN04)
    stub.mode("slow", stage="classify", slow_s=6.0)

    with sandbox.background(label="tick-A") as (proc, log_a):
        step("waiting until fire A owns the lock (the wrapper rewrites it with its own pid)")
        deadline = time.monotonic() + 60
        held = None
        while time.monotonic() < deadline and proc.poll() is None:
            state = _lock_state(sandbox)
            if state and state[0].split("|", 1)[0] == str(proc.pid):
                held = state
                break
            time.sleep(0.1)
        assert held is not None, f"fire A never took the lock — see {log_a}"

        step("firing B while A runs")
        b = sandbox.fire(label="tick-B")
        assert b.rc == 0, f"a skipped fire must exit 0, got {b.rc} — see {b.log_path}"
        b.expect("[wrapper] lock held; skipping this fire", "fire B did not skip")
        b.expect(f"another tick in progress: pid={proc.pid}", "fire B did not see A as the holder")
        assert proc.poll() is None, "fire B disturbed fire A"
        assert _lock_state(sandbox) == held, "fire B touched A's lock (content or mtime)"

        step("letting A finish")
        rc = proc.wait(timeout=180)
    assert rc == 0, f"fire A exited {rc} — see {log_a}"
    assert not sandbox.lock_path.exists(), "the lock outlived the tick"
    ticks = sandbox.ticks()
    assert len(ticks) == 1 and ticks[0]["status"] == "ok", f"B must not open a tick: {ticks}"


@pytest.mark.fast
def test_en04_a_dead_holder_blocks_until_the_backstop_then_is_reclaimed(sandbox, step):
    seed.reseed(())
    step("planting a FRESH lock held by a dead pid")
    _plant_lock(sandbox, DEAD_PID, time.time())
    before = _lock_state(sandbox)
    run = sandbox.fire(label="fresh-dead-holder")
    assert run.rc == 0
    run.expect("[wrapper] lock held; skipping this fire", "a fresh dead-holder lock must still block")
    run.expect("waiting until file ages past 3h", "the backstop reason was not reported")
    assert _lock_state(sandbox) == before, "a skipped fire touched the lock"
    assert sandbox.ticks() == [], "no tick may open behind a held lock"

    step("ageing the same lock past the 3 h backstop")
    aged = time.time() - BACKSTOP_S - 600
    os.utime(sandbox.lock_path, (aged, aged))
    run = sandbox.fire(label="aged-dead-holder")
    assert run.rc == 0, f"see {run.log_path}"
    run.expect("tick-acquire: acquired tick_id=1", "the aged dead-holder lock was not reclaimed")
    if aged > _boot_epoch():
        # Only when the machine has been up longer than the backstop can the
        # AGE rule be told apart from the boot rule below.
        run.expect("reclaimed stale lock", "reclaimed, but not by the age rule")
        run.refute("predates current boot", "the boot rule fired for a post-boot lock")
    run.expect("tick-end: closed tick_id=1 status=ok", "the reclaimed tick did not close ok")
    assert not sandbox.lock_path.exists(), "the reclaimed lock outlived the tick"


@pytest.mark.fast
def test_en04_a_lock_from_before_this_boot_is_reclaimed_even_with_a_live_pid(sandbox, step):
    seed.reseed(())
    live_pid = os.getpid()  # this pytest process: alive for the whole case
    step("planting a lock with a LIVE pid and a fresh mtime — must block")
    _plant_lock(sandbox, live_pid, time.time())
    run = sandbox.fire(label="live-holder-fresh")
    assert run.rc == 0
    run.expect(f"another tick in progress: pid={live_pid}", "a live holder's fresh lock must block")
    assert sandbox.ticks() == []

    step("moving the same lock's mtime to before the current boot — must reclaim")
    pre_boot = _boot_epoch() - 120
    os.utime(sandbox.lock_path, (pre_boot, pre_boot))
    run = sandbox.fire(label="live-holder-pre-boot")
    assert run.rc == 0, f"see {run.log_path}"
    run.expect("predates current boot", "the boot rule did not fire")
    run.expect("tick-acquire: acquired tick_id=1", "the pre-boot lock was not reclaimed")
    run.expect("tick-end: closed tick_id=1 status=ok", "the reclaimed tick did not close ok")
    assert not sandbox.lock_path.exists()
