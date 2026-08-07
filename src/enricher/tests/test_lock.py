import os
import subprocess
import sys
import time
from pathlib import Path

from job_enricher import lock as lk


def test_acquire_and_contention(tmp_path):
    p = tmp_path / ".tick.lock"
    ok, reason = lk.try_acquire(p)
    assert ok and reason is None
    ok2, reason2 = lk.try_acquire(p)  # our own live pid holds it
    assert not ok2 and "in progress" in reason2
    lk.release(p)
    ok3, _ = lk.try_acquire(p)
    assert ok3
    lk.release(p)


def test_release_idempotent(tmp_path):
    p = tmp_path / ".tick.lock"
    lk.release(p)  # no file — safe
    lk.release(p)


def test_stale_dead_holder_not_taken_until_aged(tmp_path):
    p = tmp_path / ".tick.lock"
    p.write_text("999999|2020-01-01T00:00:00+00:00")  # dead pid, but fresh mtime
    ok, reason = lk.try_acquire(p, stale_after_hours=3)
    assert not ok and "holder is gone" in reason


def test_stale_dead_holder_reclaimed_when_aged(tmp_path):
    """E8: an aged, dead holder is reclaimed atomically and the new lock is
    owned by the reclaiming process."""
    p = tmp_path / ".tick.lock"
    p.write_text("999999|2020-01-01T00:00:00+00:00")  # dead pid
    old = time.time() - 4 * 3600                        # aged past the 3h backstop
    os.utime(p, (old, old))
    ok, reason = lk.try_acquire(p, stale_after_hours=3)
    assert ok and reason is None
    pid, _ = lk._read_lock(p)
    assert pid == os.getpid()  # we own the reclaimed lock now
    lk.release(p)


def test_release_refuses_live_foreign_owner(tmp_path):
    """E8/E15: release() must not delete a lock held by another *live* process
    (a genuinely concurrent tick)."""
    p = tmp_path / ".tick.lock"
    # our parent pid is alive but is not us
    ppid = os.getppid()
    assert ppid != os.getpid() and lk._pid_alive(ppid)  # live + foreign
    p.write_text(f"{ppid}|2020-01-01T00:00:00+00:00")
    lk.release(p)
    assert p.exists()  # left intact — a live foreign process still holds it


def test_release_removes_dead_foreign_owner_lock(tmp_path):
    """E15: tick-acquire and tick-end are SEPARATE processes, so tick-end's
    release() sees the (by-then dead) pid tick-acquire wrote — a different pid
    from our own. That lock MUST be released; otherwise the orphaned-but-fresh
    lock looks live to the next tick-acquire and starves every tick for ~3h."""
    p = tmp_path / ".tick.lock"
    # spawn a trivial subprocess and reap it, so its pid is reliably dead and
    # is not our own — exactly tick-end's situation vs tick-acquire's pid
    proc = subprocess.Popen([sys.executable, "-c", ""])
    proc.wait()
    dead_pid = proc.pid
    assert dead_pid != os.getpid() and not lk._pid_alive(dead_pid)
    p.write_text(f"{dead_pid}|2020-01-01T00:00:00+00:00")
    lk.release(p)
    assert not p.exists()  # dead holder -> released across processes


def test_release_removes_own_lock(tmp_path):
    p = tmp_path / ".tick.lock"
    ok, _ = lk.try_acquire(p)
    assert ok
    lk.release(p)
    assert not p.exists()  # we owned it, so it is gone


def test_release_with_owner_pid_releases_delegated_live_lock(tmp_path):
    """Wrapper topology: the lock records the WRAPPER's pid (live for the whole
    tick); tick-end is a different process but knows the delegated owner via
    ENRICH_LOCK_OWNER_PID and may release it."""
    p = tmp_path / ".tick.lock"
    ppid = os.getppid()  # live + foreign, standing in for the wrapper
    assert ppid != os.getpid() and lk._pid_alive(ppid)
    p.write_text(f"{ppid}|2026-01-01T00:00:00+00:00")
    lk.release(p, owner_pid=ppid)
    assert not p.exists()  # delegated owner honored


def test_release_with_wrong_owner_pid_still_refuses_live_foreign(tmp_path):
    """A stray owner hint must not unlock someone ELSE's live lock."""
    p = tmp_path / ".tick.lock"
    ppid = os.getppid()
    p.write_text(f"{ppid}|2026-01-01T00:00:00+00:00")
    lk.release(p, owner_pid=ppid + 12345)
    assert p.exists()  # live holder != owner hint -> left intact


def test_cross_process_release_via_owner_env(tmp_path):
    """Cross-process E15/E8 check: a SEPARATE python process (like the real
    tick-end child) releases a lock held by a live foreign pid only when the
    delegated owner pid matches."""
    p = tmp_path / ".tick.lock"
    owner = os.getpid()  # we play the wrapper: alive for the whole test
    p.write_text(f"{owner}|2026-01-01T00:00:00+00:00")
    code = (
        "import sys; sys.path.insert(0, sys.argv[3]);"
        "from pathlib import Path;"
        "from job_enricher import lock as lk;"
        "lk.release(Path(sys.argv[1]), owner_pid=int(sys.argv[2]))"
    )
    src = str(Path(lk.__file__).resolve().parents[1])
    # without the owner hint: refused (live foreign holder)
    subprocess.run([sys.executable, "-c", code.replace(", owner_pid=int(sys.argv[2])", ""),
                    str(p), "0", src], check=True)
    assert p.exists()
    # with the owner hint: released
    subprocess.run([sys.executable, "-c", code, str(p), str(owner), src], check=True)
    assert not p.exists()


def test_preboot_dead_lock_reclaimed_immediately(tmp_path, monkeypatch):
    """Power-loss recovery: a lock written before the current boot cannot have
    a live holder, so the FIRST post-reboot fire reclaims it instead of waiting
    out the age backstop (2026-08-07 outage: every 60s fire skipped for hours
    behind a reboot-orphaned lock)."""
    p = tmp_path / ".tick.lock"
    p.write_text("999999|2020-01-01T00:00:00+00:00")  # dead pid, FRESH mtime
    monkeypatch.setattr(lk, "_boot_epoch", lambda: time.time() + 60)  # booted "after" the write
    ok, reason = lk.try_acquire(p, stale_after_hours=3)
    assert ok and reason is None
    pid, _ = lk._read_lock(p)
    assert pid == os.getpid()
    lk.release(p)


def test_preboot_rule_overrides_pid_reuse(tmp_path, monkeypatch):
    """A pre-boot lock whose recorded pid is ALIVE is post-reboot pid reuse by
    a foreign process — still an orphan, still reclaimed. Without the boot rule
    this lock was never recoverable (a live pid blocks regardless of age)."""
    p = tmp_path / ".tick.lock"
    ppid = os.getppid()  # live + foreign
    assert lk._pid_alive(ppid)
    p.write_text(f"{ppid}|2020-01-01T00:00:00+00:00")
    monkeypatch.setattr(lk, "_boot_epoch", lambda: time.time() + 60)
    ok, reason = lk.try_acquire(p, stale_after_hours=3)
    assert ok and reason is None
    lk.release(p)


def test_same_boot_young_dead_lock_still_waits(tmp_path, monkeypatch):
    """Within the same boot the age backstop still governs: a young dead-holder
    lock is a just-crashed tick, not a reboot orphan — wait it out."""
    p = tmp_path / ".tick.lock"
    p.write_text("999999|2020-01-01T00:00:00+00:00")
    monkeypatch.setattr(lk, "_boot_epoch", lambda: time.time() - 3600)  # booted 1h ago; lock is younger
    ok, reason = lk.try_acquire(p, stale_after_hours=3)
    assert not ok and "holder is gone" in reason


def test_boot_epoch_unavailable_falls_back_to_age_rule(tmp_path, monkeypatch):
    """No boot time (non-mac / sysctl failure) -> exactly the old behavior."""
    monkeypatch.setattr(lk, "_boot_epoch", lambda: None)
    p = tmp_path / ".tick.lock"
    p.write_text("999999|2020-01-01T00:00:00+00:00")
    ok, reason = lk.try_acquire(p, stale_after_hours=3)
    assert not ok and "holder is gone" in reason


def test_boot_epoch_parses_on_this_platform():
    """On macOS the sysctl must parse to a sane epoch; elsewhere None is fine."""
    b = lk._boot_epoch()
    if sys.platform == "darwin":
        assert b is not None and 0 < b <= time.time()
    else:
        assert b is None or 0 < b <= time.time()
