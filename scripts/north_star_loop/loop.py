#!/usr/bin/env python3
r"""State store for the north-star improvement loop (stdlib only, Python 3.9+).

One SQLite file holds every proposal and every step taken on it, so the agent
that builds an idea reads the full brief the proposing agent wrote, not a
one-line summary. Lifecycle:

    proposed -> approved -> building -> pr_open -> shipped -> measured
             \-> rejected | expired           \-> closed  (PR closed unmerged)
                            building -> blocked (build failed twice)
                            building -> paused  (a no-mistakes gate asks Brendan;
                                                 he sets pr_open, or approved to rebuild)

`next` prints the one action the scheduled run should take. `sync` does the
token-free bookkeeping first (merge detection via `gh`, expiry). See
.claude/skills/north-star-loop/SKILL.md for the procedure that drives it.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_DB = Path.home() / "Library/Application Support/jvn-north-star-loop/loop.db"
PROPOSE_EVERY_DAYS = 7  # at most one new idea a week
EXPIRE_DAYS = 7  # an unanswered idea expires so the next one can go out
# Signups in the week after ship need 31 days to mature (USER-METRICS.md),
# the same "week + 38 days" rule as metrics.north_star_weekly.mature.
READOUT_DAYS = 38
MAX_BUILD_ATTEMPTS = 2
OPEN = ("proposed", "approved", "building", "paused", "pr_open")
STATUSES = (*OPEN, "shipped", "measured", "rejected", "expired", "closed", "blocked")
SETTABLE = {"status", "pr_url", "branch", "clickup_id", "plan_path", "result", "readout_at"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS proposals (
  id INTEGER PRIMARY KEY,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'proposed',
  title TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'improvement',
  metric TEXT NOT NULL,
  expected TEXT NOT NULL,
  risk TEXT NOT NULL,
  sms TEXT NOT NULL,
  brief TEXT NOT NULL,
  decision_note TEXT,
  decided_at TEXT,
  build_attempts INTEGER NOT NULL DEFAULT 0,
  branch TEXT,
  pr_url TEXT,
  clickup_id TEXT,
  plan_path TEXT,
  shipped_at TEXT,
  readout_at TEXT,
  result TEXT
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  at TEXT NOT NULL,
  proposal_id INTEGER,
  kind TEXT NOT NULL,
  detail TEXT NOT NULL
);
"""


def now() -> datetime:
    fake = os.environ.get("JVN_LOOP_NOW")  # tests only
    return datetime.fromisoformat(fake) if fake else datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    path = Path(os.environ.get("JVN_LOOP_DB", DEFAULT_DB))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def log_event(db, pid, kind: str, detail: str) -> None:
    db.execute(
        "INSERT INTO events (at, proposal_id, kind, detail) VALUES (?, ?, ?, ?)",
        (iso(now()), pid, kind, detail),
    )


def update(db, pid: int, **fields) -> None:
    fields["updated_at"] = iso(now())
    cols = ", ".join(f"{k} = ?" for k in fields)
    db.execute(f"UPDATE proposals SET {cols} WHERE id = ?", (*fields.values(), pid))


def get(db, pid: int):
    row = db.execute("SELECT * FROM proposals WHERE id = ?", (pid,)).fetchone()
    if row is None:
        sys.exit(f"no proposal {pid}")
    return row


def cmd_add(db, a) -> None:
    if db.execute(
        f"SELECT 1 FROM proposals WHERE status IN ({','.join('?' * len(OPEN))})", OPEN
    ).fetchone():
        sys.exit("refused: an idea is already open; one at a time")
    brief = Path(a.brief_file).read_text()
    t = iso(now())
    cur = db.execute(
        "INSERT INTO proposals (created_at, updated_at, title, kind, metric, expected,"
        " risk, sms, brief) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (t, t, a.title, a.kind, a.metric, a.expected, a.risk, a.sms, brief),
    )
    pid = cur.lastrowid
    # The text names the id ("NS-{N} ...", "yes {N}") before the id exists.
    db.execute("UPDATE proposals SET sms = ? WHERE id = ?", (a.sms.replace("{N}", str(pid)), pid))
    log_event(db, pid, "proposed", a.title)
    print(pid)


def cmd_decide(db, a) -> None:
    row = get(db, a.id)
    if row["status"] != "proposed":
        sys.exit(f"NS-{a.id} is {row['status']}, not waiting on a decision")
    status = "approved" if a.answer == "yes" else "rejected"
    note = " ".join(a.note) or None
    update(db, a.id, status=status, decided_at=iso(now()), decision_note=note)
    log_event(db, a.id, "decision", f"{status}" + (f": {note}" if note else ""))
    print(f"NS-{a.id} {status}")


def cmd_set(db, a) -> None:
    get(db, a.id)
    fields = {}
    for pair in a.pairs:
        key, _, value = pair.partition("=")
        if key not in SETTABLE:
            sys.exit(f"cannot set {key}; allowed: {', '.join(sorted(SETTABLE))}")
        fields[key] = value
    status = fields.get("status")
    if status is not None and status not in STATUSES:
        sys.exit(f"unknown status {status}; allowed: {', '.join(STATUSES)}")
    if status == "pr_open" and not (fields.get("pr_url") or get(db, a.id)["pr_url"]):
        sys.exit("status=pr_open needs pr_url=<url>")
    if status == "approved":
        fields["build_attempts"] = 0
    elif status == "building":
        fields["build_attempts"] = get(db, a.id)["build_attempts"] + 1
    update(db, a.id, **fields)
    log_event(db, a.id, "set", json.dumps(fields))


def cmd_log(db, a) -> None:
    get(db, a.id)  # no orphan events
    log_event(db, a.id, a.kind, " ".join(a.detail))


def cmd_show(db, a) -> None:
    row = dict(get(db, a.id))
    brief = row.pop("brief")
    for k, v in row.items():
        if v is not None:
            print(f"{k}: {v}")
    print("\n--- brief ---\n" + brief + "\n--- events ---")
    for e in db.execute(
        "SELECT at, kind, detail FROM events WHERE proposal_id = ? ORDER BY id", (a.id,)
    ):
        print(f"{e['at']}  {e['kind']:<9} {e['detail']}")


def cmd_list(db, a) -> None:
    for r in db.execute("SELECT id, status, kind, metric, title FROM proposals ORDER BY id"):
        print(f"NS-{r['id']}  {r['status']:<9} {r['kind']:<11} {r['metric']:<12} {r['title']}")


def gh_pr_state(url: str):
    gh = os.environ.get("JVN_LOOP_GH", "gh")
    out = subprocess.run(
        [gh, "pr", "view", url, "--json", "state,mergedAt"],
        capture_output=True, text=True, timeout=60,
    )
    if out.returncode != 0:
        return None
    return json.loads(out.stdout)


def cmd_sync(db, a) -> None:
    t = now()
    for r in db.execute("SELECT * FROM proposals WHERE status = 'proposed'").fetchall():
        if datetime.fromisoformat(r["created_at"]) <= t - timedelta(days=EXPIRE_DAYS):
            update(db, r["id"], status="expired")
            log_event(db, r["id"], "expired", f"no reply in {EXPIRE_DAYS} days")
    for r in db.execute("SELECT * FROM proposals WHERE status = 'pr_open'").fetchall():
        pr = gh_pr_state(r["pr_url"]) if r["pr_url"] else None
        if pr is None:
            log_event(db, r["id"], "warn", "could not read PR state")
        elif pr["state"] == "MERGED":
            shipped = datetime.fromisoformat(pr["mergedAt"].replace("Z", "+00:00"))
            update(db, r["id"], status="shipped", shipped_at=iso(shipped),
                   readout_at=iso(shipped + timedelta(days=READOUT_DAYS)))
            log_event(db, r["id"], "shipped", r["pr_url"])
        elif pr["state"] == "CLOSED":
            update(db, r["id"], status="closed")
            log_event(db, r["id"], "closed", "PR closed without merge")
    for r in db.execute("SELECT * FROM proposals WHERE status = 'building'").fetchall():
        if r["build_attempts"] >= MAX_BUILD_ATTEMPTS:
            update(db, r["id"], status="blocked")
            log_event(db, r["id"], "mistake", f"build did not finish in {MAX_BUILD_ATTEMPTS} attempts")


def next_action(db) -> str:
    """The one thing the scheduled run should do now. Token-free."""
    t = iso(now())
    r = db.execute(
        "SELECT id FROM proposals WHERE status IN ('approved', 'building') ORDER BY id"
    ).fetchone()
    if r:
        return f"build {r['id']}"
    r = db.execute(
        "SELECT id FROM proposals WHERE status = 'shipped' AND readout_at <= ? ORDER BY id", (t,)
    ).fetchone()
    if r:
        return f"readout {r['id']}"
    if db.execute(
        f"SELECT 1 FROM proposals WHERE status IN ({','.join('?' * len(OPEN))})", OPEN
    ).fetchone():
        return "none"
    last = db.execute("SELECT max(created_at) AS c FROM proposals").fetchone()["c"]
    if last is None or datetime.fromisoformat(last) <= now() - timedelta(days=PROPOSE_EVERY_DAYS):
        return "propose"
    return "none"


def cmd_next(db, a) -> None:
    print(next_action(db))


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="loop.py", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("add", help="record a new idea (refused if one is open)")
    s.add_argument("--title", required=True)
    s.add_argument("--kind", choices=["improvement", "feature"], default="improvement")
    s.add_argument("--metric", required=True)
    s.add_argument("--expected", required=True)
    s.add_argument("--risk", choices=["low", "medium", "high"], required=True)
    s.add_argument("--sms", required=True, help="the text to send; {N} becomes the new id")
    s.add_argument("--brief-file", required=True, help="markdown file with the full brief")
    s = sub.add_parser("decide", help="Brendan's answer to an idea")
    s.add_argument("id", type=int)
    s.add_argument("answer", choices=["yes", "no"])
    s.add_argument("note", nargs="*")
    s = sub.add_parser("set", help=f"set fields: {', '.join(sorted(SETTABLE))}")
    s.add_argument("id", type=int)
    s.add_argument("pairs", nargs="+", metavar="key=value")
    s = sub.add_parser("log", help="append an event (decision, mistake, note, step)")
    s.add_argument("id", type=int)
    s.add_argument("kind")
    s.add_argument("detail", nargs="+")
    sub.add_parser("show", help="full brief + every event").add_argument("id", type=int)
    sub.add_parser("list")
    sub.add_parser("sync", help="expire stale ideas, detect merged PRs")
    sub.add_parser("next", help="print the action to take: propose | build N | readout N | none")
    a = p.parse_args(argv)
    db = connect()
    with db:
        globals()[f"cmd_{a.cmd}"](db, a)


if __name__ == "__main__":
    main()
