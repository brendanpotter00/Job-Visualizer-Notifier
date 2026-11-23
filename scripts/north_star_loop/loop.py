#!/usr/bin/env python3
r"""State store for the north-star improvement loop (stdlib only, Python 3.9+).

One SQLite file holds every proposal and every step taken on it, so the agent
that builds an idea reads the full brief the proposing agent wrote, not a
one-line summary.

Each weekly propose run records up to 3 SMALL ideas (status `proposed`, the
loop may build them once Brendan picks them) and at most 1 BIG initiative
(status `flagged`: shown to Brendan, never built by the loop), all named in
one text. Small-idea lifecycle:

    proposed -> approved -> building -> pr_open -> shipped -> measured
             \-> rejected | expired           \-> closed  (PR closed unmerged)
                            building -> blocked (build failed twice, or the
                                                 skill found the problem no longer holds,
                                                 the idea mis-scoped, or a STRATEGY.md conflict)
                            building -> paused  (a no-mistakes gate asks Brendan: he
                                                 sets pr_open, or approved to rebuild)
    flagged  -> rejected (Brendan says why not; otherwise it stays flagged as a record)

At most 3 small ideas are in flight (approved through pr_open) at once.

`next` prints the one action the scheduled run should take (`text` when this
week's batch was saved but its text was never recorded as sent). `sync` does the
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

STATE_DIR = Path(
    os.environ.get("JVN_LOOP_STATE_DIR")
    or Path.home() / "Library/Application Support/jvn-north-star-loop"
)
PROPOSE_EVERY_DAYS = 7  # one batch a week
EXPIRE_DAYS = 7  # an unpicked idea expires so the next batch can go out
BATCH_SIZE = 3  # small ideas per weekly text
MAX_IN_FLIGHT = 3  # small ideas approved but not yet merged or closed
# Signups in the week after ship need 31 days to mature (USER-METRICS.md),
# the same "week + 38 days" rule as metrics.north_star_weekly.mature.
READOUT_DAYS = 38
MAX_BUILD_ATTEMPTS = 2
# Fires are 4h apart and a batch is stamped minutes into one, so "a week ago"
# leaves half a fire of slack to keep each batch on the same weekly slot.
SLACK = timedelta(hours=1)
IN_FLIGHT = ("approved", "building", "paused", "pr_open")
STATUSES = ("proposed", *IN_FLIGHT, "flagged", "shipped", "measured", "rejected",
            "expired", "closed", "blocked")
SETTABLE = {"status", "pr_url", "branch", "clickup_id", "plan_path", "result", "readout_at"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS proposals (
  id INTEGER PRIMARY KEY,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'proposed',
  scope TEXT NOT NULL DEFAULT 'small',
  title TEXT NOT NULL,
  metric TEXT NOT NULL,
  expected TEXT NOT NULL,
  risk TEXT NOT NULL,
  sms TEXT NOT NULL DEFAULT '',
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
    path = Path(os.environ.get("JVN_LOOP_DB") or STATE_DIR / "loop.db")
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    if "scope" not in {c[1] for c in db.execute("PRAGMA table_info(proposals)")}:
        db.execute("ALTER TABLE proposals ADD COLUMN scope TEXT NOT NULL DEFAULT 'small'")
    return db


def days_ago(days: int) -> datetime:
    return now() - timedelta(days=days) + SLACK


def count(db, where: str, *params) -> int:
    return db.execute(f"SELECT count(*) FROM proposals WHERE {where}", params).fetchone()[0]


def in_flight(db) -> int:
    marks = ",".join("?" * len(IN_FLIGHT))
    return count(db, f"scope = 'small' AND status IN ({marks})", *IN_FLIGHT)


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
    t = iso(now())
    if a.scope == "small":
        if count(db, "scope = 'small' AND status = 'proposed'") >= BATCH_SIZE:
            sys.exit(f"refused: this week's batch already has {BATCH_SIZE} small ideas")
        status = "proposed"
    else:
        if count(db, "scope = 'big' AND created_at > ?", iso(days_ago(PROPOSE_EVERY_DAYS))):
            sys.exit("refused: one big initiative a week")
        status = "flagged"
    brief = Path(a.brief_file).read_text()
    cur = db.execute(
        "INSERT INTO proposals (created_at, updated_at, status, scope, title, metric,"
        " expected, risk, sms, brief) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', ?)",
        (t, t, status, a.scope, a.title, a.metric, a.expected, a.risk, brief),
    )
    log_event(db, cur.lastrowid, status, a.title)
    print(cur.lastrowid)


def cmd_texted(db, a) -> None:
    """Record the one weekly text on every idea it names."""
    for pid in a.ids:
        get(db, pid)
        update(db, pid, sms=a.message)
        log_event(db, pid, "texted", "named in the text sent to Brendan")


def cmd_decide(db, a) -> None:
    row = get(db, a.id)
    if row["scope"] == "big":
        if a.answer == "yes":
            sys.exit(f"NS-{a.id} is a big initiative: the loop never builds it. "
                     f"Build it yourself, or reply \"no {a.id} <why>\" to record why not.")
        if row["status"] != "flagged":
            sys.exit(f"NS-{a.id} is {row['status']}, not waiting on a decision")
    elif row["status"] != "proposed":
        sys.exit(f"NS-{a.id} is {row['status']}, not waiting on a decision")
    elif a.answer == "yes" and in_flight(db) >= MAX_IN_FLIGHT:
        sys.exit(f"refused: {MAX_IN_FLIGHT} ideas are already in flight; NS-{a.id} stays proposed")
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
    for r in db.execute("SELECT id, status, scope, metric, title FROM proposals ORDER BY id"):
        print(f"NS-{r['id']}  {r['status']:<9} {r['scope']:<5} {r['metric']:<12} {r['title']}")


def gh_pr_state(url: str):
    gh = os.environ.get("JVN_LOOP_GH", "gh")
    try:
        out = subprocess.run(
            [gh, "pr", "view", url, "--json", "state,mergedAt"],
            capture_output=True, text=True, timeout=60,
        )
        if out.returncode != 0:
            return None
        return json.loads(out.stdout)
    except (subprocess.TimeoutExpired, ValueError):
        return None


def cmd_sync(db, a) -> None:
    for r in db.execute("SELECT * FROM proposals WHERE status = 'proposed'").fetchall():
        if datetime.fromisoformat(r["created_at"]) <= days_ago(EXPIRE_DAYS):
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
    if count(db, "sms = '' AND status IN ('proposed', 'flagged') AND created_at > ?",
             iso(days_ago(EXPIRE_DAYS))):
        return "text"  # this week's batch was saved but its text never went out
    if count(db, "status = 'proposed'") or in_flight(db) >= MAX_IN_FLIGHT:
        return "none"  # waiting on the weekly answer, or every slot is taken
    last = db.execute("SELECT max(created_at) AS c FROM proposals").fetchone()["c"]
    if last is None or datetime.fromisoformat(last) <= days_ago(PROPOSE_EVERY_DAYS):
        return "propose"
    return "none"


def cmd_next(db, a) -> None:
    print(next_action(db))


def render_log(db) -> str:
    """Every idea, newest first, as markdown: the readable twin of loop.db."""
    out = [
        "# North-star loop state",
        "",
        "Generated by `scripts/north_star_loop/loop.py dump` from the local loop.db on the server laptop.",
        "",
    ]
    rows = db.execute("SELECT * FROM proposals ORDER BY id DESC").fetchall()
    if not rows:
        out.append("No ideas yet.")
    for r in rows:
        out += [f"## NS-{r['id']} · {r['title']}", "",
                f"**Status:** {r['status']} · **Scope:** {r['scope']}", ""]
        for k in ("created_at", "metric", "expected", "risk", "decided_at",
                  "decision_note", "branch", "pr_url", "clickup_id", "plan_path",
                  "shipped_at", "readout_at", "result"):
            if r[k] not in (None, ""):
                out.append(f"- {k}: {r[k]}")
        if r["sms"]:
            out += ["", "### Text sent", "", "```", r["sms"], "```"]
        out += ["", "### Brief", "",
                r["brief"].strip(), "", "### Events", ""]
        for e in db.execute(
            "SELECT at, kind, detail FROM events WHERE proposal_id = ? ORDER BY id", (r["id"],)
        ):
            out.append(f"- `{e['at']}` **{e['kind']}** {e['detail']}")
        out.append("")
    return "\n".join(out) + "\n"


def cmd_dump(db, a) -> None:
    sys.stdout.write(render_log(db))


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="loop.py", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("add", help=f"record an idea: up to {BATCH_SIZE} small + 1 big a week")
    s.add_argument("--scope", choices=["small", "big"], required=True,
                   help="small: the loop may build it once picked; big: shown, never built")
    s.add_argument("--title", required=True)
    s.add_argument("--metric", required=True)
    s.add_argument("--expected", required=True)
    s.add_argument("--risk", choices=["low", "medium", "high"], required=True)
    s.add_argument("--brief-file", required=True, help="markdown file with the full brief")
    s = sub.add_parser("texted", help="record the weekly text on every idea it names")
    s.add_argument("message")
    s.add_argument("ids", type=int, nargs="+")
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
    sub.add_parser("next", help="print the action to take: propose | text | build N | readout N | none")
    sub.add_parser("dump", help="print every idea as markdown: briefs, texts, events")
    a = p.parse_args(argv)
    db = connect()
    with db:
        globals()[f"cmd_{a.cmd}"](db, a)


if __name__ == "__main__":
    main()
