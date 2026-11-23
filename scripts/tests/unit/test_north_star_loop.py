"""Lifecycle tests for scripts/north_star_loop/loop.py, driven through its CLI.

Oracle: the lifecycle in scripts/north_star_loop/README.md and SKILL.md:
one idea open at a time, an unanswered idea expires after 7 days, a merged
PR is read out 38 days later (USER-METRICS.md: a signup week is mature at
week + 38 days), and a build that fails twice is blocked.
"""
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

LOOP = Path(__file__).resolve().parents[2] / "north_star_loop" / "loop.py"
T0 = "2026-12-01T09:00:00+00:00"


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

    def add(now=T0, check=True):
        return run(
            "add", "--title", "Default Recent to 24h", "--metric", "7d return",
            "--expected", "23% -> 25%", "--risk", "low", "--sms", "NS-1 idea",
            "--brief-file", str(brief), now=now, check=check,
        )

    run.add = add
    return run


def fake_gh(tmp_path, payload):
    script = tmp_path / "gh"
    script.write_text(f"#!/bin/sh\necho '{json.dumps(payload)}'\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def next_action(loop, now=T0):
    return loop("next", now=now).stdout.strip()


def test_first_run_proposes_and_an_open_idea_blocks_the_next(loop):
    assert next_action(loop) == "propose"
    assert loop.add().stdout.strip() == "1"
    assert next_action(loop) == "none"
    second = loop.add(check=False)
    assert second.returncode != 0 and "one at a time" in second.stderr


def test_yes_starts_a_build_and_no_waits_a_week(loop):
    loop.add()
    loop("decide", "1", "yes")
    assert next_action(loop) == "build 1"

    loop("set", "1", "status=closed")
    loop.add(now="2026-12-09T09:00:00+00:00")
    loop("decide", "2", "no", "not", "now", now="2026-12-09T10:00:00+00:00")
    assert "rejected: not now" in loop("show", "2").stdout
    assert next_action(loop, now="2026-12-12T09:00:00+00:00") == "none"
    assert next_action(loop, now="2026-12-16T09:00:00+00:00") == "propose"


def test_unanswered_idea_expires_after_seven_days(loop):
    loop.add()
    loop("sync", now="2026-12-07T09:00:00+00:00")
    assert "status: proposed" in loop("show", "1").stdout
    loop("sync", now="2026-12-08T09:00:00+00:00")
    assert "status: expired" in loop("show", "1").stdout
    assert next_action(loop, now="2026-12-08T09:00:00+00:00") == "propose"


def test_merged_pr_is_read_out_38_days_after_merge(loop, tmp_path):
    loop.add()
    loop("decide", "1", "yes")
    loop("set", "1", "status=pr_open", "pr_url=https://github.com/x/y/pull/9")
    gh = fake_gh(tmp_path, {"state": "MERGED", "mergedAt": "2026-12-02T10:00:00Z"})
    loop("sync", now="2026-12-03T09:00:00+00:00", gh=gh)

    shown = loop("show", "1").stdout
    assert "status: shipped" in shown
    assert "readout_at: 2027-01-09T10:00:00+00:00" in shown
    assert next_action(loop, now="2027-01-09T09:59:00+00:00") == "propose"
    assert next_action(loop, now="2027-01-09T10:00:00+00:00") == "readout 1"


def test_closed_pr_frees_the_slot(loop, tmp_path):
    loop.add()
    loop("set", "1", "status=pr_open", "pr_url=https://github.com/x/y/pull/9")
    gh = fake_gh(tmp_path, {"state": "CLOSED", "mergedAt": None})
    loop("sync", gh=gh)
    assert "status: closed" in loop("show", "1").stdout


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
    assert next_action(loop, now="2026-12-08T09:00:00+00:00") == "propose"


def test_text_gets_its_own_id_and_log_needs_a_real_idea(loop, tmp_path):
    brief = tmp_path / "brief.md"
    out = loop(
        "add", "--title", "t", "--metric", "7d return", "--expected", "26% -> 28%",
        "--risk", "low", "--sms", 'NS-{N} idea\nReply "yes {N}"', "--brief-file", str(brief),
    )
    assert out.stdout.strip() == "1"
    shown = loop("show", "1").stdout
    assert 'NS-1 idea\nReply "yes 1"' in shown
    orphan = loop("log", "99", "note", "x", check=False)
    assert orphan.returncode != 0 and "no proposal 99" in orphan.stderr


def test_only_known_fields_can_be_set(loop):
    loop.add()
    out = loop("set", "1", "brief=overwritten", check=False)
    assert out.returncode != 0 and "cannot set brief" in out.stderr


def test_paused_idea_holds_the_slot_and_is_not_rebuilt(loop):
    loop.add()
    loop("decide", "1", "yes")
    loop("set", "1", "status=building")
    loop("set", "1", "status=paused")
    later = "2026-12-09T09:00:00+00:00"
    for _ in range(3):
        loop("sync", now=later)
        assert next_action(loop, now=later) == "none"
    assert "status: paused" in loop("show", "1").stdout
    assert loop.add(now=later, check=False).returncode != 0

    loop("set", "1", "status=pr_open", "pr_url=https://github.com/x/y/pull/9")
    assert "status: pr_open" in loop("show", "1").stdout


def test_rebuild_after_pause_gets_its_own_two_attempts(loop):
    loop.add()
    loop("decide", "1", "yes")
    loop("set", "1", "status=building")
    loop("set", "1", "status=paused")
    loop("set", "1", "status=approved")
    loop("set", "1", "status=building")
    loop("sync")
    assert "status: building" in loop("show", "1").stdout
    assert next_action(loop) == "build 1"


def test_set_rejects_unknown_status_and_pr_open_without_url(loop):
    loop.add()
    typo = loop("set", "1", "status=pr-open", check=False)
    assert typo.returncode != 0 and "unknown status pr-open" in typo.stderr
    no_url = loop("set", "1", "status=pr_open", check=False)
    assert no_url.returncode != 0 and "needs pr_url" in no_url.stderr
    assert "status: proposed" in loop("show", "1").stdout
    assert next_action(loop, now="2026-12-09T09:00:00+00:00") == "none"
