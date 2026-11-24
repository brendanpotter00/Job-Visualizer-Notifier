"""Wall-clock deadlines with sleep-gap credit (PLAN §4.3), in scripts/lib/park_worker.py.

On Darwin `time.monotonic()` (mach_absolute_time) stops while the laptop
sleeps, so wall - monotonic is the time asleep. That time is credited to every
live deadline: a night's sleep must not read as a wedged tick, and a slow
subprocess (time on both clocks) must not be credited.
"""

from __future__ import annotations

import pytest

from test_park_worker import FakeTime, pw


def make(poll_s: float = 5.0):
    ft = FakeTime()
    logs: list[str] = []
    clock = pw.WallClock(poll_s, wall=lambda: ft.wall, mono=lambda: ft.mono, sleep=ft.sleep,
                         log=logs.append)
    return ft, clock, logs


def test_threshold_is_max_of_60s_and_six_polls():
    assert make(5)[1].gap_threshold_s == 60
    assert make(1)[1].gap_threshold_s == 60
    assert make(30)[1].gap_threshold_s == 180


def test_normal_polls_earn_no_credit():
    ft, clock, _ = make(5)
    dl = pw.Deadline(clock, 100)
    for _ in range(10):
        clock.sleep()
    assert clock.credit == 0
    assert dl.remaining() == pytest.approx(50)


def test_a_night_asleep_is_credited_to_every_live_deadline():
    ft, clock, logs = make(5)
    park = pw.Deadline(clock, 14400)
    verify = pw.Deadline(clock, 900)
    clock.sleep()                      # one normal poll
    ft.wall += 8 * 3600                # lid closed for 8 h: wall moves, monotonic does not
    ft.mono += 2
    clock.sleep()
    assert clock.credit == pytest.approx(8 * 3600 - 2 + 0, abs=1)
    assert not verify.expired()        # would have expired 7 h ago without the credit
    assert verify.remaining() == pytest.approx(900 - 5 - 5 - 2, abs=1)
    assert park.remaining() == pytest.approx(14400 - 12, abs=1)
    assert any("asleep" in m for m in logs)


def test_a_slow_subprocess_is_not_mistaken_for_sleep():
    ft, clock, _ = make(5)
    dl = pw.Deadline(clock, 100)
    ft.wall += 90                      # e.g. an integrity_check: time passes on BOTH clocks
    ft.mono += 90
    clock.observe()
    assert clock.credit == 0
    assert dl.remaining() == pytest.approx(10)


def test_a_gap_below_the_threshold_is_not_credited():
    ft, clock, _ = make(5)
    ft.wall += 55
    ft.mono += 1
    clock.observe()
    assert clock.credit == 0


def test_a_deadline_created_after_the_sleep_gets_no_credit_for_it():
    ft, clock, _ = make(5)
    ft.wall += 3600
    clock.observe()
    later = pw.Deadline(clock, 60)
    assert later.remaining() == pytest.approx(60)


def test_deadline_expires_and_extends():
    ft, clock, _ = make(1)
    dl = pw.Deadline(clock, 10)
    for _ in range(10):
        clock.sleep()
    assert dl.expired()
    dl.extend(5)
    assert not dl.expired() and dl.remaining() == pytest.approx(5)


def test_claim_budget_counts_awake_time_only(tmp_path):
    """A live tick holds the lock; the laptop sleeps 6 h mid-wait. With a 1 h
    budget the claim must still be waiting (not exhausted) right after wake."""
    import os
    import subprocess

    holder = subprocess.Popen(["sleep", "60"])
    try:
        lock = tmp_path / ".tick.lock"
        lock.write_text(f"{holder.pid}|x")
        ft = FakeTime()
        slept = {"done": False}

        def sleep(s: float) -> None:
            ft.sleep(s)
            if not slept["done"] and ft.wall - 1_000_000 > 600:
                ft.wall += 6 * 3600     # asleep; monotonic stalls
                slept["done"] = True

        clock = pw.WallClock(1.0, wall=lambda: ft.wall, mono=lambda: ft.mono, sleep=sleep)
        res = pw.claim(lock, "/x/scripts/enrich_tick_wrapper.sh", 3600, pw.make_payload(os.getpid()),
                       clock=clock, processes=lambda: [], boot=lambda: None, log=lambda m: None)
        assert not res.claimed
        assert res.waited_s == pytest.approx(3600 + 6 * 3600, abs=5)
        assert clock.credit == pytest.approx(6 * 3600, abs=2)
    finally:
        holder.kill()
        holder.wait()
