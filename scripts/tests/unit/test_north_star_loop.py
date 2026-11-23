"""Lifecycle tests for scripts/north_star_loop/loop.py, driven through its CLI.

Oracle: the lifecycle in scripts/north_star_loop/README.md and SKILL.md §0.5:
one weekly batch of at most 3 small ideas plus at most 1 big initiative; big
initiatives are never built; at most 3 small ideas in flight; an unpicked idea
expires after 7 days; a merged PR is read out 38 days later (USER-METRICS.md:
a signup week is mature at week + 38 days); a build that fails twice is blocked.
"""
import json
import os
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

import pytest

LOOP = Path(__file__).resolve().parents[2] / "north_star_loop" / "loop.py"
T0 = "2026-12-01T09:00:00+00:00"
WEEK_LATER = "2026-12-08T09:00:00+00:00"


@pytest.fixture
def loop(tmp_path):
    brief = tmp_path / "brief.md"
    brief.write_text("## Problem\nfull brief text\n")

    def run(*args, now=T0, gh=None, check=True):
        env = {**os.environ, "JVN_LOOP_DB": str(tmp_path / "loop.db"), "JVN_LOOP_NOW": now}
        if gh:
            env["JVN_LOOP_GH"] = gh
        out = subprocess.run(
            [sys.executable, str(LOOP), *args], capture_output=True, text=True, env=env
        )
        if check:
            assert out.returncode == 0, out.stderr
        return out

    def add(scope="small", title="Default Recent to 24h", now=T0, check=True):
        return run(
            "add", "--scope", scope, "--title", title, "--metric", "7d return",
            "--expected", "23% -> 25%", "--risk", "low", "--brief-file", str(brief),
            now=now, check=check,
        )

    run.add = add
    run.db = tmp_path / "loop.db"
    return run


def fake_gh(tmp_path, by_url):
    """A gh stand-in: `gh pr view <url> --json ...` prints by_url[url]."""
    cases = "".join(f"  '{url}') echo '{json.dumps(p)}' ;;\n" for url, p in by_url.items())
    script = tmp_path / "gh"
    script.write_text(f'#!/bin/sh\ncase "$3" in\n{cases}  *) exit 1 ;;\nesac\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def status(loop, pid):
    return next(line for line in loop("show", str(pid)).stdout.splitlines()
                if line.startswith("status: "))[len("status: "):]


def next_action(loop, now=T0):
    return loop("next", now=now).stdout.strip()


def test_a_weekly_batch_holds_three_small_ideas_and_one_big(loop):
    assert next_action(loop) == "propose"
    assert [loop.add().stdout.strip() for _ in range(3)] == ["1", "2", "3"]
    fourth = loop.add(check=False)
    assert fourth.returncode != 0 and "already has 3 small ideas" in fourth.stderr

    assert loop.add(scope="big", title="Daily digest email").stdout.strip() == "4"
    assert status(loop, 4) == "flagged"
    second_big = loop.add(scope="big", check=False)
    assert second_big.returncode != 0 and "one big initiative a week" in second_big.stderr
    loop("texted", "NS weekly", "1", "2", "3", "4")
    assert next_action(loop) == "none"  # waiting on Brendan's picks


def test_a_batch_saved_but_never_texted_is_texted_by_the_next_fire(loop):
    loop.add()
    loop.add(scope="big", title="Daily digest email")
    assert next_action(loop, now="2026-12-01T13:30:00+00:00") == "text"
    loop("texted", "NS weekly\n1) Divider\nBig (yours): Daily digest · NS-2", "1", "2")
    assert next_action(loop, now="2026-12-01T13:30:00+00:00") == "none"


def test_a_batch_stamped_minutes_into_a_fire_is_due_at_the_same_slot_next_week(loop):
    loop.add(now="2026-12-01T09:35:00+00:00")
    loop("texted", "NS weekly", "1", now="2026-12-01T09:36:00+00:00")
    loop("sync", now="2026-12-08T09:30:00+00:00")
    assert status(loop, 1) == "expired"
    assert next_action(loop, now="2026-12-08T09:30:00+00:00") == "propose"


def test_picked_small_ideas_are_built_in_order_and_a_no_keeps_his_reason(loop):
    for _ in range(3):
        loop.add()
    loop("decide", "1", "yes")
    loop("decide", "3", "yes")
    loop("decide", "2", "no", "not", "worth", "it")
    assert next_action(loop) == "build 1"
    loop("set", "1", "status=pr_open", "pr_url=https://github.com/x/y/pull/1")
    assert next_action(loop) == "build 3"
    assert "rejected: not worth it" in loop("show", "2").stdout


def test_a_big_initiative_is_never_built(loop):
    loop.add(scope="big", title="Daily digest email")
    yes = loop("decide", "1", "yes", check=False)
    assert yes.returncode != 0 and "never builds" in yes.stderr
    assert status(loop, 1) == "flagged"
    assert next_action(loop, now=WEEK_LATER) == "propose"  # nothing to build

    loop("decide", "1", "no", "needs", "the", "match", "bar", "first")
    assert status(loop, 1) == "rejected"
    assert "rejected: needs the match bar first" in loop("show", "1").stdout


def test_unpicked_idea_expires_after_seven_days_and_frees_the_next_batch(loop):
    loop.add()
    loop("sync", now="2026-12-07T09:00:00+00:00")
    assert status(loop, 1) == "proposed"
    loop("sync", now=WEEK_LATER)
    assert status(loop, 1) == "expired"
    assert next_action(loop, now=WEEK_LATER) == "propose"


def test_no_new_batch_and_no_fourth_yes_while_three_are_in_flight(loop, tmp_path):
    for _ in range(3):
        loop.add()
    for pid in ("1", "2", "3"):
        loop("decide", pid, "yes")
        loop("set", pid, "status=pr_open", f"pr_url=https://github.com/x/y/pull/{pid}")
    assert next_action(loop, now=WEEK_LATER) == "none"

    loop.add(now=WEEK_LATER)  # a small idea can still be recorded...
    late_yes = loop("decide", "4", "yes", now=WEEK_LATER, check=False)
    assert late_yes.returncode != 0 and "3 ideas are already in flight" in late_yes.stderr
    assert status(loop, 4) == "proposed"  # ...but not picked until a slot frees

    gh = fake_gh(tmp_path, {
        "https://github.com/x/y/pull/1": {"state": "MERGED", "mergedAt": "2026-12-08T10:00:00Z"},
        "https://github.com/x/y/pull/2": {"state": "OPEN", "mergedAt": None},
        "https://github.com/x/y/pull/3": {"state": "OPEN", "mergedAt": None},
    })
    loop("sync", now="2026-12-09T09:00:00+00:00", gh=gh)
    assert status(loop, 1) == "shipped"
    loop("decide", "4", "yes", now="2026-12-09T09:00:00+00:00")
    assert next_action(loop, now="2026-12-09T09:00:00+00:00") == "build 4"


def test_merged_pr_is_read_out_38_days_after_merge(loop, tmp_path):
    loop.add()
    loop("decide", "1", "yes")
    loop("set", "1", "status=pr_open", "pr_url=https://github.com/x/y/pull/9")
    gh = fake_gh(tmp_path, {"https://github.com/x/y/pull/9":
                            {"state": "MERGED", "mergedAt": "2026-12-02T10:00:00Z"}})
    loop("sync", now="2026-12-03T09:00:00+00:00", gh=gh)

    shown = loop("show", "1").stdout
    assert "status: shipped" in shown
    assert "readout_at: 2027-01-09T10:00:00+00:00" in shown
    assert next_action(loop, now="2027-01-09T09:59:00+00:00") == "propose"
    assert next_action(loop, now="2027-01-09T10:00:00+00:00") == "readout 1"


def test_closed_pr_frees_its_slot(loop, tmp_path):
    loop.add()
    loop("decide", "1", "yes")
    loop("set", "1", "status=pr_open", "pr_url=https://github.com/x/y/pull/9")
    gh = fake_gh(tmp_path, {"https://github.com/x/y/pull/9": {"state": "CLOSED", "mergedAt": None}})
    loop("sync", gh=gh)
    assert status(loop, 1) == "closed"


def test_build_that_fails_twice_is_blocked_and_logged_as_a_mistake(loop):
    loop.add()
    loop("decide", "1", "yes")
    loop("set", "1", "status=building")
    loop("sync")
    assert next_action(loop) == "build 1"  # first interrupted run gets one retry
    loop("set", "1", "status=building")
    loop("sync")
    shown = loop("show", "1").stdout
    assert "status: blocked" in shown
    assert "mistake" in shown
    assert next_action(loop, now=WEEK_LATER) == "propose"


def test_the_weekly_text_is_recorded_on_every_idea_it_names(loop):
    loop.add()
    loop.add()
    loop.add(scope="big", title="Daily digest email")
    text = 'NS weekly · 7d return 26%\n1) Divider · 3.0 · low\n2) Badge · 2.0 · low\nBig (yours): Daily digest · 3.2 · NS-3\nReply e.g. "yes 1"'
    loop("texted", text, "1", "2", "3")
    for pid in ("1", "2", "3"):
        shown = loop("show", pid).stdout
        assert f"sms: {text}" in shown and "texted" in shown
    orphan = loop("log", "99", "note", "x", check=False)
    assert orphan.returncode != 0 and "no proposal 99" in orphan.stderr


def test_only_known_fields_can_be_set(loop):
    loop.add()
    out = loop("set", "1", "brief=overwritten", check=False)
    assert out.returncode != 0 and "cannot set brief" in out.stderr


def test_paused_idea_keeps_its_slot_and_is_not_rebuilt(loop):
    loop.add()
    loop("decide", "1", "yes")
    loop("set", "1", "status=building")
    loop("set", "1", "status=paused")
    for _ in range(3):
        loop("sync", now=WEEK_LATER)
        assert next_action(loop, now=WEEK_LATER) != "build 1"
    assert status(loop, 1) == "paused"

    loop("set", "1", "status=pr_open", "pr_url=https://github.com/x/y/pull/9")
    assert status(loop, 1) == "pr_open"


def test_rebuild_after_pause_gets_its_own_two_attempts(loop):
    loop.add()
    loop("decide", "1", "yes")
    loop("set", "1", "status=building")
    loop("set", "1", "status=paused")
    loop("set", "1", "status=approved")
    loop("set", "1", "status=building")
    loop("sync")
    assert status(loop, 1) == "building"
    assert next_action(loop) == "build 1"


def test_set_rejects_unknown_status_and_pr_open_without_url(loop):
    loop.add()
    typo = loop("set", "1", "status=pr-open", check=False)
    assert typo.returncode != 0 and "unknown status pr-open" in typo.stderr
    no_url = loop("set", "1", "status=pr_open", check=False)
    assert no_url.returncode != 0 and "needs pr_url" in no_url.stderr
    assert status(loop, 1) == "proposed"


def test_sync_survives_unreadable_gh_output_and_still_expires(loop, tmp_path):
    gh = tmp_path / "gh"
    gh.write_text("#!/bin/sh\necho 'not json'\n")
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    loop.add()
    loop.add()
    loop("decide", "1", "yes")
    loop("set", "1", "status=pr_open", "pr_url=https://github.com/x/y/pull/9")
    loop("sync", now=WEEK_LATER, gh=str(gh))
    assert "could not read PR state" in loop("show", "1").stdout
    assert status(loop, 2) == "expired"


def test_dump_prints_scope_text_and_full_brief(loop, tmp_path):
    brief = tmp_path / "long-brief.md"
    brief.write_text("## Problem\n47% never come back\n\n## Risk\nrevert the PR\n")
    loop("add", "--scope", "small", "--title", "Divider for jobs since last visit",
         "--metric", "7d return", "--expected", "26% -> 28%", "--risk", "low",
         "--brief-file", str(brief))
    loop("texted", "NS weekly\n1) Divider", "1")
    out = loop("dump").stdout
    assert "NS-1 · Divider for jobs since last visit" in out
    assert "**Scope:** small" in out
    assert "NS weekly\n1) Divider" in out
    assert "47% never come back" in out and "revert the PR" in out


def test_a_db_from_before_scope_existed_still_works(loop):
    # The first dry runs wrote this schema: no scope column, sms required.
    db = sqlite3.connect(loop.db)
    db.executescript("""
        CREATE TABLE proposals (
          id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'proposed', title TEXT NOT NULL,
          kind TEXT NOT NULL DEFAULT 'improvement', metric TEXT NOT NULL,
          expected TEXT NOT NULL, risk TEXT NOT NULL, sms TEXT NOT NULL, brief TEXT NOT NULL,
          decision_note TEXT, decided_at TEXT, build_attempts INTEGER NOT NULL DEFAULT 0,
          branch TEXT, pr_url TEXT, clickup_id TEXT, plan_path TEXT, shipped_at TEXT,
          readout_at TEXT, result TEXT);
        INSERT INTO proposals (created_at, updated_at, status, title, metric, expected, risk, sms, brief)
          VALUES ('2026-11-23T14:21:14+00:00', '2026-11-23T14:21:14+00:00', 'expired',
                  'Divider', '7d return', '26% -> 28%', 'low', 'NS-1 idea', 'old brief');
    """)
    db.commit()
    db.close()
    assert "NS-1  expired   small" in loop("list").stdout
    assert loop.add(scope="big", title="Daily digest email").stdout.strip() == "2"
