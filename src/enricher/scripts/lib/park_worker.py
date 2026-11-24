#!/usr/bin/env python3
"""Park the enricher's launchd worker BETWEEN ticks, never in the middle of one.

Shared by ``scripts/cutover/cutover.py`` (imported) and ``scripts/deploy.sh``
(run as a CLI). Standard library only, Python >= 3.11, so it runs under any
interpreter, including a bare ``python3 -I``.

WHY A LOCK CLAIM, NOT ``launchctl unload``. The worker is a 60 s
``StartInterval`` job whose ticks run 1-3 h back to back, so the idle gap
between two ticks is about a minute. ``launchctl unload`` SIGTERMs a running
job (the label's ``exit timeout`` is 5 s), so unloading at a random moment
kills a tick. Instead we wait for the gap and take the enricher's OWN
single-flight lock (``data/.tick.lock``, ``"<pid>|<iso>"``) with
``O_CREAT|O_EXCL``. From then on every launchd fire exits 75 ("lock held")
within seconds, and only THEN is it safe to unload.

Lock states this module understands (see ``classify_holder``):

* ``live``     the recorded pid is alive -> a tick is running; wait.
* ``starting`` the pid is dead but a wrapper process for this checkout is
               running -> ``tick-acquire`` just wrote it and the wrapper is
               about to rewrite it with its own pid; wait.
* ``orphan``   the pid is dead and no wrapper runs, or the file predates the
               current boot -> nobody can hold it; reclaim it with the same
               rename-then-``O_EXCL`` dance ``job_enricher/lock.py`` uses.

Every wait is a WALL-CLOCK deadline polled in short steps (``WallClock`` /
``Deadline``), never one long ``sleep``: Darwin's sleep and monotonic clock
stall while the laptop sleeps, and the time the laptop spent asleep is
credited back to every live deadline so a night's sleep never reads as a
wedged tick.

CLI (exit 0 = done, 10 = budget exhausted / not ours, 2 = usage)::

    park_worker.py claim     --lock L --wrapper W --budget-s N --owner-pid P [--poll-s S]
    park_worker.py wait-idle --wrapper W --budget-s N
    park_worker.py release   --lock L --owner-pid P
"""

from __future__ import annotations

import argparse
import errno
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

EXIT_OK = 0
EXIT_BUDGET = 10
EXIT_USAGE = 2

PS_BIN = "/bin/ps"
SYSCTL_BIN = "/usr/sbin/sysctl"

#: How the wrapper spells every stage it runs — ``uv run python -m
#: job_enricher.cli <stage>`` — in both the ``uv`` process and its interpreter.
STAGE_NEEDLE = "job_enricher.cli"

Log = Callable[[str], None]


def _default_log(msg: str) -> None:
    print(f"[park] {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} {msg}", flush=True)


# --------------------------------------------------------------------------- clocks
class WallClock:
    """Wall-clock time with sleep-gap credit.

    ``observe()`` compares the wall clock with the monotonic clock since the
    previous observation. On Darwin ``time.monotonic()`` is
    ``mach_absolute_time()``, which does not advance while the machine sleeps,
    so ``wall_delta - mono_delta`` is the time spent asleep. When two
    observations are more than ``max(60, 6 * poll_s)`` wall seconds apart and
    most of that was not process time, the gap is added to ``credit``; every
    ``Deadline`` built on this clock moves out by the credit it has seen.
    A slow subprocess between two observations is NOT credited (its time shows
    on both clocks)."""

    def __init__(
        self,
        poll_s: float = 1.0,
        *,
        wall: Callable[[], float] = time.time,
        mono: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        log: Log | None = None,
    ) -> None:
        self.poll_s = float(poll_s)
        self.gap_threshold_s = max(60.0, 6.0 * self.poll_s)
        self._wall = wall
        self._mono = mono
        self._sleep = sleep
        self._log = log
        self.credit = 0.0
        self._last_wall = wall()
        self._last_mono = mono()

    def now(self) -> float:
        return self._wall()

    def observe(self) -> float:
        """Record one observation; return the sleep credit it added (s)."""
        w, m = self._wall(), self._mono()
        dw, dm = w - self._last_wall, m - self._last_mono
        self._last_wall, self._last_mono = w, m
        if dw <= self.gap_threshold_s:
            return 0.0
        slept = dw - max(0.0, dm)
        if slept <= 0:
            return 0.0
        self.credit += slept
        if self._log:
            self._log(f"clock: {dw:.0f}s passed between polls, {slept:.0f}s of it asleep — "
                      "crediting it to every live deadline")
        return slept

    def sleep(self, seconds: float | None = None) -> None:
        self._sleep(self.poll_s if seconds is None else seconds)
        self.observe()


class Deadline:
    """``budget_s`` seconds of AWAKE wall time from creation (see WallClock)."""

    def __init__(self, clock: WallClock, budget_s: float) -> None:
        self.clock = clock
        self.budget_s = float(budget_s)
        self.start = clock.now()
        self._credit0 = clock.credit

    def remaining(self) -> float:
        self.clock.observe()
        credit = self.clock.credit - self._credit0
        return self.start + self.budget_s + credit - self.clock.now()

    def expired(self) -> bool:
        return self.remaining() <= 0

    def extend(self, seconds: float) -> None:
        self.budget_s += float(seconds)


# --------------------------------------------------------------------------- processes
def pid_alive(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OverflowError:
        return False
    return True


def list_processes(ps_bin: str = PS_BIN) -> list[tuple[int, int, str]]:
    """``[(pid, ppid, command), ...]`` for every process. Never logged."""
    try:
        out = subprocess.run(
            [ps_bin, "-axww", "-o", "pid=,ppid=,command="],
            capture_output=True, text=True, timeout=30, check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    procs: list[tuple[int, int, str]] = []
    for line in out.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        try:
            procs.append((int(parts[0]), int(parts[1]), parts[2]))
        except ValueError:
            continue
    return procs


def _is_orphan_watchdog(pid: int, ppid: int, rows: list[tuple[int, int, str]]) -> bool:
    """The wrapper's watchdog is a subshell, ``( sleep $TIMEOUT; kill ... ) &``,
    so it carries the wrapper's command line. When a wrapper dies mid-tick (a
    SIGTERM from ``launchctl unload``), that subshell is re-parented to pid 1
    and lingers for up to 3 h with a lone ``sleep`` child. It does no work and
    holds nothing, so it must not read as "a wrapper is running". A live
    launchd job also has ppid 1, but its children are ``uv``/python/subshells,
    never only ``sleep``."""
    if ppid != 1:
        return False
    kids = [cmd for _p, pp, cmd in rows if pp == pid]
    return bool(kids) and all(Path(k.split()[0]).name == "sleep" for k in kids if k.split())


def wrapper_pids(
    wrapper_path: str | Path,
    *,
    procs: list[tuple[int, int, str]] | None = None,
    exclude: Iterable[int] = (),
) -> list[int]:
    """Pids whose command line names this checkout's wrapper script (the
    wrapper itself and its in-process subshells), minus orphaned watchdog
    subshells (see ``_is_orphan_watchdog``)."""
    needle = str(wrapper_path)
    skip = {os.getpid(), *exclude}
    rows = list_processes() if procs is None else procs
    return sorted(
        pid for pid, ppid, cmd in rows
        if needle in cmd and pid not in skip and not _is_orphan_watchdog(pid, ppid, rows)
    )


def stage_pids(
    wrapper_path: str | Path,
    *,
    procs: list[tuple[int, int, str]] | None = None,
) -> list[int]:
    """Pids of the enricher STAGES this checkout's wrapper is running: every
    ``uv run python -m job_enricher.cli <stage>`` that DESCENDS from a
    ``wrapper_pids`` process, and the interpreter each of those spawns.

    Descent, never the checkout's path in the command line: ``uv run`` spawns
    whatever the venv's ``sys.executable`` resolves to, and for a venv built on
    a macOS framework Python that is the framework's own ``bin/python3``, far
    outside the checkout — a path match then finds no stage at all."""
    rows = list_processes() if procs is None else procs
    parent = {pid: ppid for pid, ppid, _cmd in rows}
    roots = set(wrapper_pids(wrapper_path, procs=rows))
    out: list[int] = []
    for pid, ppid, cmd in rows:
        if STAGE_NEEDLE not in cmd:
            continue
        seen = {pid}
        cur = ppid
        while cur > 1 and cur not in seen:
            if cur in roots:
                out.append(pid)
                break
            seen.add(cur)
            cur = parent.get(cur, 0)
    return sorted(out)


def boot_epoch(sysctl_bin: str = SYSCTL_BIN) -> float | None:
    """Wall-clock time of the current boot (``kern.boottime``), or None."""
    try:
        out = subprocess.run(
            [sysctl_bin, "-n", "kern.boottime"],
            capture_output=True, text=True, timeout=5, check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"sec\s*=\s*(\d+)", out)
    return float(m.group(1)) if m else None


# --------------------------------------------------------------------------- the lock
@dataclass(frozen=True)
class LockInfo:
    raw: str
    pid: int | None
    mtime: float


def make_payload(pid: int) -> str:
    """The enricher's own lock format: ``"<pid>|<iso>"``."""
    return f"{pid}|{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}"


def payload_pid(raw: str) -> int | None:
    pid_s = raw.strip().partition("|")[0]
    try:
        return int(pid_s)
    except ValueError:
        return None


def read_lock(lock_path: str | Path) -> LockInfo | None:
    p = Path(lock_path)
    try:
        raw = p.read_text(encoding="utf-8", errors="replace")
        mtime = p.stat().st_mtime
    except FileNotFoundError:
        return None
    return LockInfo(raw=raw, pid=payload_pid(raw), mtime=mtime)


def try_create(lock_path: str | Path, payload: str) -> bool:
    """Atomic ``O_CREAT|O_EXCL`` create. True when we created it."""
    p = Path(lock_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except OSError as exc:
        if exc.errno == errno.EEXIST:
            return False
        raise
    try:
        os.write(fd, payload.encode("utf-8"))
    finally:
        os.close(fd)
    return True


def classify_holder(info: LockInfo, *, wrapper_running: bool, boot: float | None) -> str:
    """``live`` | ``starting`` | ``orphan`` (see the module docstring)."""
    if boot is not None and info.mtime < boot:
        return "orphan"  # written before this boot: its writer cannot be alive
    if pid_alive(info.pid):
        return "live"
    if wrapper_running:
        return "starting"
    return "orphan"


def reclaim(lock_path: str | Path, expect_raw: str, payload: str, log: Log = _default_log) -> bool:
    """Replace a lock whose content is ``expect_raw`` with ``payload``.

    rename(2) of one source succeeds for exactly one caller, so two reclaimers
    can never both win. If what we renamed is not what we judged (someone
    replaced the lock between our read and our rename), put it back and give
    up this round."""
    p = Path(lock_path)
    steal = p.with_name(f"{p.name}.steal.{os.getpid()}")
    try:
        os.rename(p, steal)
    except FileNotFoundError:
        return try_create(p, payload)
    try:
        got = steal.read_text(encoding="utf-8", errors="replace")
    except OSError:
        got = None
    if got != expect_raw:
        try:
            os.link(steal, p)  # fails with EEXIST if a new lock appeared meanwhile
        except OSError:
            log("lock changed under us and a new lock already exists — leaving it")
        finally:
            try:
                steal.unlink()
            except FileNotFoundError:
                pass
        return False
    try:
        steal.unlink()
    except FileNotFoundError:
        pass
    return try_create(p, payload)


@dataclass
class ClaimResult:
    claimed: bool
    payload: str
    waited_s: float = 0.0
    reclaimed: str | None = None   # "orphan" | "own" when we took over a file
    holder_pid: int | None = None  # last holder seen while waiting
    reason: str = ""
    notes: list[str] = field(default_factory=list)


def claim(
    lock_path: str | Path,
    wrapper_path: str | Path,
    budget_s: float,
    payload: str,
    *,
    poll_s: float = 1.0,
    known_payloads: Iterable[str] = (),
    clock: WallClock | None = None,
    log: Log = _default_log,
    processes: Callable[[], list[tuple[int, int, str]]] = list_processes,
    boot: Callable[[], float | None] = boot_epoch,
) -> ClaimResult:
    """Wait (<= ``budget_s`` awake seconds) until no tick runs, then hold the
    lock with ``payload``. ``known_payloads`` are payloads an earlier run of
    the caller wrote (its pid is gone): such a lock is ours to take back."""
    clock = clock or WallClock(poll_s, log=log)
    deadline = Deadline(clock, budget_s)
    known = {k for k in known_payloads if k}
    boot_ts = boot()
    t0 = clock.now()
    last_state: str | None = None
    holder: int | None = None
    while True:
        if try_create(lock_path, payload):
            return ClaimResult(True, payload, clock.now() - t0, None, holder, "created")
        info = read_lock(lock_path)
        if info is None:
            continue  # vanished between our create and our read: try again now
        if info.raw == payload:
            return ClaimResult(True, payload, clock.now() - t0, None, holder, "already ours")
        if (info.raw in known and not pid_alive(info.pid)) or info.pid == os.getpid():
            if reclaim(lock_path, info.raw, payload, log):
                log(f"took back our own earlier lock (pid={info.pid})")
                return ClaimResult(True, payload, clock.now() - t0, "own", info.pid, "own lock")
            continue
        running = bool(wrapper_pids(wrapper_path, procs=processes()))
        state = classify_holder(info, wrapper_running=running, boot=boot_ts)
        holder = info.pid
        if state == "orphan":
            if reclaim(lock_path, info.raw, payload, log):
                log(f"reclaimed an orphaned lock (pid={info.pid} dead, no wrapper running)")
                return ClaimResult(True, payload, clock.now() - t0, "orphan", info.pid, "orphan")
            continue
        if state != last_state:
            log(f"lock held ({state}, pid={info.pid}); waiting for the tick to end "
                f"(budget {deadline.remaining():.0f}s)")
            last_state = state
        if deadline.expired():
            return ClaimResult(False, payload, clock.now() - t0, None, holder,
                               f"budget exhausted; lock still {state} (pid={info.pid})")
        clock.sleep(poll_s)


def release(lock_path: str | Path, *, payload: str | None = None, owner_pid: int | None = None) -> bool:
    """Remove the lock only when it is ours: its content equals ``payload``, or
    its pid equals ``owner_pid``. Returns True when a file was removed."""
    info = read_lock(lock_path)
    if info is None:
        return False
    ours = (payload is not None and info.raw == payload) or (
        owner_pid is not None and info.pid == owner_pid
    )
    if not ours:
        return False
    try:
        Path(lock_path).unlink()
    except FileNotFoundError:
        return False
    return True


def wait_idle(
    wrapper_path: str | Path,
    budget_s: float,
    *,
    poll_s: float = 1.0,
    clock: WallClock | None = None,
    processes: Callable[[], list[tuple[int, int, str]]] = list_processes,
) -> bool:
    """True once no process runs this checkout's wrapper (<= ``budget_s``)."""
    clock = clock or WallClock(poll_s)
    deadline = Deadline(clock, budget_s)
    while True:
        if not wrapper_pids(wrapper_path, procs=processes()):
            return True
        if deadline.expired():
            return False
        clock.sleep(poll_s)


# --------------------------------------------------------------------------- CLI
def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="park_worker.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("claim", help="wait for the gap between ticks, then hold the lock")
    c.add_argument("--lock", required=True)
    c.add_argument("--wrapper", required=True)
    c.add_argument("--budget-s", type=float, required=True)
    c.add_argument("--owner-pid", type=int, required=True,
                   help="a pid that stays alive while the lock is held (deploy.sh passes $$)")
    c.add_argument("--poll-s", type=float, default=1.0)
    w = sub.add_parser("wait-idle", help="wait until no wrapper process runs")
    w.add_argument("--wrapper", required=True)
    w.add_argument("--budget-s", type=float, required=True)
    w.add_argument("--poll-s", type=float, default=1.0)
    r = sub.add_parser("release", help="remove the lock only if --owner-pid holds it")
    r.add_argument("--lock", required=True)
    r.add_argument("--owner-pid", type=int, required=True)
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return EXIT_USAGE if exc.code else EXIT_OK

    if args.cmd == "claim":
        res = claim(args.lock, args.wrapper, args.budget_s, make_payload(args.owner_pid),
                    poll_s=args.poll_s)
        if res.claimed:
            _default_log(f"claimed {args.lock} for pid {args.owner_pid} after {res.waited_s:.0f}s"
                         + (f" (reclaimed {res.reclaimed} lock)" if res.reclaimed else ""))
            return EXIT_OK
        _default_log(f"NOT claimed: {res.reason}")
        return EXIT_BUDGET
    if args.cmd == "wait-idle":
        ok = wait_idle(args.wrapper, args.budget_s, poll_s=args.poll_s)
        _default_log("no wrapper running" if ok else "a wrapper is still running")
        return EXIT_OK if ok else EXIT_BUDGET
    if args.cmd == "release":
        removed = release(args.lock, owner_pid=args.owner_pid)
        _default_log("released our lock" if removed else "lock not ours (or absent); left alone")
        return EXIT_OK
    return EXIT_USAGE  # pragma: no cover


if __name__ == "__main__":
    sys.exit(_main())
