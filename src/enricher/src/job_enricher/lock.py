"""Single-flight lock — O_EXCL create + PID-liveness + stale backstop.

Faithful port of job-watcher/lock.py. Guarantees at most one /enrich-tick runs
at a time. Lock file lives at data/.tick.lock and holds "{pid}|{iso}". A held
lock by a live PID blocks; a dead holder is only taken over once the file ages
past the backstop (default 3h — enrichment ticks are longer than job-watcher's).

Boot rule: a lock whose mtime predates the CURRENT BOOT is reclaimed
immediately, liveness and age notwithstanding — its writer died with the
previous boot (power loss, panic), so no live process can hold it; a live
matching pid is post-reboot pid reuse. Without this, a mid-tick power loss
left every 60s fire skipping for up to the full backstop (2026-08-07 outage),
and a reused-pid orphan was never reclaimed at all.
"""

from __future__ import annotations

import errno
import logging
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from job_enricher.store import DEFAULT_DB_PATH

logger = logging.getLogger(__name__)

DEFAULT_LOCK_PATH = DEFAULT_DB_PATH.parent / ".tick.lock"
DEFAULT_STALE_HOURS = 3


def _boot_epoch() -> float | None:
    """Wall-clock time of the current boot via `sysctl -n kern.boottime`
    (macOS: `{ sec = 1754593020, usec = ... } ...`). None when unavailable or
    unparseable — callers then fall back to the age backstop alone."""
    try:
        out = subprocess.run(
            ["/usr/sbin/sysctl", "-n", "kern.boottime"],
            capture_output=True, text=True, timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"sec\s*=\s*(\d+)", out)
    return float(m.group(1)) if m else None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OverflowError:
        return False
    except PermissionError:
        return True
    return True


def _read_lock(lock_path: Path) -> tuple[int | None, str | None]:
    try:
        content = lock_path.read_text().strip()
    except FileNotFoundError:
        return None, None
    pid_str, _, ts = content.partition("|")
    try:
        pid = int(pid_str)
    except ValueError:
        return None, None
    return pid, ts or None


def _write_lock_exclusive(lock_path: Path) -> bool:
    """Atomic O_CREAT|O_EXCL create. True on success, False if it already exists."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    payload = f"{os.getpid()}|{datetime.now(timezone.utc).isoformat()}"
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except OSError as exc:
        if exc.errno == errno.EEXIST:
            return False
        raise
    try:
        os.write(fd, payload.encode("utf-8"))
    finally:
        os.close(fd)
    return True


def try_acquire(
    lock_path: Path = DEFAULT_LOCK_PATH,
    stale_after_hours: int = DEFAULT_STALE_HOURS,
) -> tuple[bool, str | None]:
    if _write_lock_exclusive(lock_path):
        return True, None

    pid, started_at = _read_lock(lock_path)
    try:
        stat = lock_path.stat()
    except FileNotFoundError:
        if _write_lock_exclusive(lock_path):
            return True, None
        return False, "another tick in progress (lock contention)"

    mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
    age = datetime.now(timezone.utc) - mtime
    stale_age = timedelta(hours=stale_after_hours)

    boot = _boot_epoch()
    pre_boot = boot is not None and stat.st_mtime < boot
    if pre_boot:
        # Written before this boot -> the writer cannot have survived it. Skip
        # the liveness check on purpose: a live matching pid is post-reboot pid
        # reuse by a foreign process, not the holder.
        logger.info(
            "lock: lock predates current boot (pid=%s started_at=%s) — "
            "reclaiming now instead of waiting out the %sh backstop",
            pid, started_at, stale_after_hours,
        )
    else:
        alive = pid is not None and _pid_alive(pid)
        if alive:
            return False, f"another tick in progress: pid={pid} started_at={started_at}"
        if age < stale_age:
            return (
                False,
                f"lock held but holder is gone (pid={pid} started_at={started_at}); "
                f"waiting until file ages past {stale_after_hours}h",
            )

    # Stale + dead holder (or pre-boot orphan): reclaim ATOMICALLY. The old code did unlink() then
    # create, which let two ticks both delete-and-recreate (a competitor could
    # remove OUR fresh lock, TOCTOU double-acquire). Instead, rename the stale
    # file to a per-PID unique path: os.rename of the SAME source succeeds for
    # exactly ONE caller (the rest get FileNotFoundError). The winner then
    # creates the real lock via O_EXCL; losers fall through and their O_EXCL
    # create races the winner's — so at most one lock file ever exists.
    steal_path = lock_path.with_name(f"{lock_path.name}.steal.{os.getpid()}")
    try:
        os.rename(lock_path, steal_path)
    except FileNotFoundError:
        # Another reclaimer already moved/removed it — just try a fresh exclusive
        # create; O_EXCL guarantees only one winner.
        if _write_lock_exclusive(lock_path):
            return True, None
        return False, "another tick in progress (lock contention)"
    try:
        os.unlink(steal_path)
    except FileNotFoundError:
        pass
    logger.info("lock: reclaimed stale lock (dead pid=%s started_at=%s)", pid, started_at)
    if _write_lock_exclusive(lock_path):
        return True, None
    return False, "another tick in progress (lock contention)"


def release(lock_path: Path = DEFAULT_LOCK_PATH, owner_pid: int | None = None) -> None:
    """Remove the lock file unless a *live, different* process holds it.

    tick-acquire and tick-end run as SEPARATE OS processes, so the PID the lock
    records (written by tick-acquire) is normally NOT this process when tick-end
    releases it (E15). We therefore unlink when the recorded PID is our own OR is
    no longer alive: a dead holder cannot be mid-tick, so reclaiming its lock is
    safe, and this is exactly tick-end seeing tick-acquire's now-exited PID. We
    refuse ONLY when the recorded PID belongs to a genuinely live, different
    process — a concurrent tick whose lock we must not delete (the E8 intent).

    ``owner_pid`` handles the headless-wrapper topology: the wrapper rewrites
    the lock with its OWN pid (which stays alive for the whole tick, so
    liveness checks become meaningful) and exports it as
    ``ENRICH_LOCK_OWNER_PID``; tick-end — a child of that wrapper but a
    different process — passes it here so the delegated owner's lock is still
    releasable even though its holder is live and foreign.

    A lock with no parseable PID is REMOVED (it can only be our own malformed
    write or leftover cruft). Safe to call multiple times."""
    pid, _ = _read_lock(lock_path)
    if (
        pid is not None
        and pid != os.getpid()
        and (owner_pid is None or pid != owner_pid)
        and _pid_alive(pid)
    ):
        logger.warning(
            "lock: refusing to release lock held by live pid=%s (we are pid=%s)",
            pid, os.getpid(),
        )
        return
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass
