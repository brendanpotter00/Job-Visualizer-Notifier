"""Fake ``job_enricher.cli`` — an e2e FIXTURE for the enricher-cutover section.

It is not an enricher. It honours exactly the contract the cutover relies on
(``e2e/enricher-cutover/PLAN.md`` §2), with package-relative state like the real
one: ``data/`` sits next to this package's parent directory.

Commands::

    init [--seed-ticks N]   schema (WAL, user_version 3) + meta + N closed ticks
    health                  one JSON object, with volatile keys (now, *_at, *_age_s)
    should-start            exit 1 when the control file says this checkout idles
    tick-acquire            O_EXCL lock with lock.py's rules; exit 75 while held
    work --tick-id N        "runs" the tick: sleeps <ROLE>_TICK_S, writing progress rows
    tick-end --tick-id N    closes the tick <ROLE>_STATUS and releases the lock

Per-checkout behaviour comes from ``$FAKE_CONTROL`` (``KEY=VALUE`` lines). The
role is ``NEW`` when this checkout is ``$FAKE_NEW_ENRICHER``, else ``OLD``:

    <ROLE>_START=1|0       0 = every fire exits before tick-acquire (no tick ever starts)
    <ROLE>_TICK_S=1        how long a tick runs (re-read while it runs: lower it to unwedge)
    <ROLE>_STATUS=ok|error how the tick closes
    <ROLE>_CLAIMED / _CLASSIFIED / _SENT   the tick's counters (default 2 each)

Every lifecycle step appends one JSON line to ``$FAKE_EVENTS`` (when set).
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA = REPO_ROOT / "data"
DB = DATA / "enricher.db"
LOCK = DATA / ".tick.lock"
STALE_S = 3 * 3600  # lock.py's 3 h backstop

SCHEMA = """
CREATE TABLE IF NOT EXISTS ticks (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at  TEXT NOT NULL,
  ended_at    TEXT,
  status      TEXT NOT NULL DEFAULT 'running',
  claimed     INTEGER NOT NULL DEFAULT 0,
  classified  INTEGER NOT NULL DEFAULT 0,
  sent        INTEGER NOT NULL DEFAULT 0,
  notes       TEXT
);
CREATE TABLE IF NOT EXISTS stage_timings (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  tick_id     INTEGER NOT NULL,
  stage       TEXT NOT NULL,
  started_at  TEXT NOT NULL,
  ended_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
  key         TEXT PRIMARY KEY,
  value       TEXT,
  updated_at  TEXT
);
CREATE TABLE IF NOT EXISTS enrichments (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id      TEXT NOT NULL,
  category    TEXT,
  tick_id     INTEGER,
  sent        INTEGER NOT NULL DEFAULT 0
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def role() -> str:
    new = os.environ.get("FAKE_NEW_ENRICHER", "")
    if new and os.path.realpath(new) == os.path.realpath(REPO_ROOT):
        return "NEW"
    return "OLD"


def control() -> dict[str, str]:
    path = os.environ.get("FAKE_CONTROL", "")
    out: dict[str, str] = {}
    try:
        text = Path(path).read_text(encoding="utf-8") if path else ""
    except OSError:
        text = ""
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


def knob(name: str, default: str) -> str:
    return control().get(f"{role()}_{name}", default)


def event(ev: str, **extra: object) -> None:
    path = os.environ.get("FAKE_EVENTS")
    if not path:
        return
    rec = {"t": time.time(), "ev": ev, "role": role(), "dir": str(REPO_ROOT),
           "pid": os.getpid(), "owner": os.environ.get("ENRICH_LOCK_OWNER_PID"), **extra}
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, (json.dumps(rec) + "\n").encode())
    finally:
        os.close(fd)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB), timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


# --------------------------------------------------------------------------- lock
def _pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _boot_epoch() -> float | None:
    try:
        out = subprocess.run(["/usr/sbin/sysctl", "-n", "kern.boottime"], capture_output=True,
                             text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"sec\s*=\s*(\d+)", out)
    return float(m.group(1)) if m else None


def _create_lock() -> bool:
    DATA.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except OSError as exc:
        if exc.errno == errno.EEXIST:
            return False
        raise
    try:
        os.write(fd, f"{os.getpid()}|{now_iso()}".encode())
    finally:
        os.close(fd)
    return True


def _lock_pid() -> int | None:
    try:
        return int(LOCK.read_text().strip().partition("|")[0])
    except (OSError, ValueError):
        return None


def try_acquire() -> tuple[bool, str]:
    """lock.py's rules: a live holder blocks; a dead holder blocks until the
    file is 3 h old; a lock written before this boot is reclaimed at once."""
    if _create_lock():
        return True, ""
    try:
        mtime = LOCK.stat().st_mtime
    except FileNotFoundError:
        return (True, "") if _create_lock() else (False, "lock contention")
    pid = _lock_pid()
    boot = _boot_epoch()
    if not (boot is not None and mtime < boot):
        if _pid_alive(pid):
            return False, f"another tick in progress: pid={pid}"
        if time.time() - mtime < STALE_S:
            return False, f"lock held but holder is gone (pid={pid}); waiting until it ages past 3h"
    steal = LOCK.with_name(f"{LOCK.name}.steal.{os.getpid()}")
    try:
        os.rename(LOCK, steal)
    except FileNotFoundError:
        return (True, "") if _create_lock() else (False, "lock contention")
    steal.unlink(missing_ok=True)
    return (True, "") if _create_lock() else (False, "lock contention")


def release_lock() -> None:
    """lock.py's release: never remove a lock a live, different process holds,
    unless it is the wrapper that delegated it (ENRICH_LOCK_OWNER_PID)."""
    pid = _lock_pid()
    owner = os.environ.get("ENRICH_LOCK_OWNER_PID")
    owner_pid = int(owner) if owner and owner.isdigit() else None
    if pid is not None and pid != os.getpid() and pid != owner_pid and _pid_alive(pid):
        print(f"tick-end: lock held by live pid={pid}; not releasing", file=sys.stderr)
        return
    LOCK.unlink(missing_ok=True)


# --------------------------------------------------------------------------- commands
def cmd_init(args: argparse.Namespace) -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        conn.execute("PRAGMA user_version=3")
        for key, value in (("classify:engine", "ollama"), ("judge:engine", "ollama"),
                           ("classify:model", "qwen3:32b")):
            conn.execute("INSERT OR IGNORE INTO meta (key, value, updated_at) VALUES (?, ?, ?)",
                         (key, value, now_iso()))
        for i in range(args.seed_ticks):
            cur = conn.execute(
                "INSERT INTO ticks (started_at, ended_at, status, claimed, classified, sent) "
                "VALUES (?, ?, 'ok', 2, 2, 2)", (now_iso(), now_iso()))
            for j in range(2):
                conn.execute("INSERT INTO enrichments (job_id, category, tick_id, sent) "
                             "VALUES (?, 'software_engineering', ?, 1)",
                             (f"seed-{i}-{j}", cur.lastrowid))
    conn.close()
    print("init: schema ready")
    return 0


def _env_configured() -> bool:
    """Whether .env.local names JVN — never its values."""
    try:
        text = (REPO_ROOT / ".env.local").read_text(encoding="utf-8")
    except OSError:
        return False
    keys = {ln.partition("=")[0].strip() for ln in text.splitlines()
            if "=" in ln and ln.partition("=")[2].strip()}
    return {"JVN_BASE_URL", "INTERNAL_API_KEY"} <= keys


def cmd_health(args: argparse.Namespace) -> int:
    if not DB.exists():
        print("health: unable to open database file", file=sys.stderr)
        return 1
    conn = connect()
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        counts = {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
        last = conn.execute("SELECT id, status, started_at, ended_at FROM ticks "
                            "ORDER BY id DESC LIMIT 1").fetchone()
        meta = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()
    age = None
    if last and last["started_at"]:
        age = round(time.time() - datetime.fromisoformat(
            last["started_at"].replace("Z", "+00:00")).timestamp())
    print(json.dumps({
        "user_version": version,
        "counts": counts,
        "last_tick": dict(last) if last else None,
        "classify_engine": meta.get("classify:engine"),
        "judge_engine": meta.get("judge:engine"),
        "classify_model": meta.get("classify:model"),
        "jvn_configured": _env_configured(),
        "now": now_iso(),
        "last_tick_age_s": age,
    }, sort_keys=True))
    return 0


def cmd_should_start(args: argparse.Namespace) -> int:
    return 0 if knob("START", "1") == "1" else 1


def cmd_tick_acquire(args: argparse.Namespace) -> int:
    ok, why = try_acquire()
    if not ok:
        print(f"tick-acquire: skipped — {why}")
        event("skip", reason=why)
        return 75
    try:
        with connect() as conn:
            cur = conn.execute("INSERT INTO ticks (started_at, status) VALUES (?, 'running')",
                               (now_iso(),))
            tick_id = cur.lastrowid
            conn.execute("INSERT OR REPLACE INTO meta (key, value, updated_at) "
                         "VALUES ('current_tick_id', ?, ?)", (str(tick_id), now_iso()))
        conn.close()
    except Exception:
        LOCK.unlink(missing_ok=True)
        raise
    print(f"tick-acquire: acquired tick_id={tick_id}")
    event("acquire", tick=tick_id)
    return 0


def cmd_work(args: argparse.Namespace) -> int:
    """Run for <ROLE>_TICK_S seconds (re-read every poll), writing a progress
    row about every half second, like a real tick's stage timings."""
    started = time.time()
    stop = os.environ.get("FAKE_STOP_FILE")
    last_row = 0.0
    while True:
        if stop and os.path.exists(stop):
            return 1
        if time.time() - started >= float(knob("TICK_S", "1")):
            break
        if time.time() - last_row >= 0.5:
            with connect() as conn:
                conn.execute("INSERT INTO stage_timings (tick_id, stage, started_at, ended_at) "
                             "VALUES (?, 'classify', ?, ?)", (args.tick_id, now_iso(), now_iso()))
            conn.close()
            last_row = time.time()
        time.sleep(0.1)
    return 0


def cmd_tick_end(args: argparse.Namespace) -> int:
    status = args.status or knob("STATUS", "ok")
    claimed = int(knob("CLAIMED", "2"))
    classified = int(knob("CLASSIFIED", "2"))
    sent = int(knob("SENT", "2"))
    with connect() as conn:
        cur = conn.execute("SELECT value FROM meta WHERE key='current_tick_id'").fetchone()
        if cur is None or int(cur[0]) != args.tick_id:
            print(f"tick-end: REFUSED — current_tick_id={cur[0] if cur else None}, "
                  f"expected {args.tick_id}")
            return 1
        conn.execute("UPDATE ticks SET status=?, ended_at=?, claimed=?, classified=?, sent=? "
                     "WHERE id=?", (status, now_iso(), claimed, classified, sent, args.tick_id))
        for j in range(classified):
            conn.execute("INSERT INTO enrichments (job_id, category, tick_id, sent) "
                         "VALUES (?, 'software_engineering', ?, ?)",
                         (f"t{args.tick_id}-{j}", args.tick_id, 1 if j < sent else 0))
        conn.execute("DELETE FROM meta WHERE key='current_tick_id'")
    conn.close()
    release_lock()
    print(f"tick-end: closed tick_id={args.tick_id} status={status}")
    event("end", tick=args.tick_id, status=status)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="job_enricher.cli (fake)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init")
    p.add_argument("--seed-ticks", type=int, default=0)
    p.set_defaults(func=cmd_init)
    sub.add_parser("health").set_defaults(func=cmd_health)
    sub.add_parser("should-start").set_defaults(func=cmd_should_start)
    sub.add_parser("tick-acquire").set_defaults(func=cmd_tick_acquire)
    p = sub.add_parser("work")
    p.add_argument("--tick-id", type=int, required=True)
    p.set_defaults(func=cmd_work)
    p = sub.add_parser("tick-end")
    p.add_argument("--tick-id", type=int, required=True)
    p.add_argument("--status", default=None, choices=["ok", "error"])
    p.set_defaults(func=cmd_tick_end)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
