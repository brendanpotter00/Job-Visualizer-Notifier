"""The north-star loop's two outputs to the outside world.

1. `loop.py publish` mirrors the state to the `loop-state` git branch so other
   agents can read it (README "State in git"): the branch holds loop.db and a
   readable LOG.md, gets a commit only when the state changed, and never
   touches main.
2. `notify.sh` sends a text AND writes it into Boop's conversation history
   through Convex `messages:send` (the call Boop's own automations use), so a
   reply like "yes 1" reaches Boop with context. Exit codes are its contract.
"""
import json
import os
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "north_star_loop"
LOOP = ROOT / "loop.py"
NOTIFY = ROOT / "notify.sh"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "loop", "GIT_AUTHOR_EMAIL": "loop@example.com",
    "GIT_COMMITTER_NAME": "loop", "GIT_COMMITTER_EMAIL": "loop@example.com",
}


def sh(*args, cwd, env=None, check=True):
    out = subprocess.run(list(args), cwd=cwd, capture_output=True, text=True,
                         env={**os.environ, **GIT_ENV, **(env or {})})
    if check:
        assert out.returncode == 0, out.stderr
    return out


def executable(path: Path, body: str) -> Path:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


@pytest.fixture
def repo(tmp_path):
    """A checkout with one commit on main and a bare origin, like the server's."""
    origin = tmp_path / "origin.git"
    sh("git", "init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    work = tmp_path / "work"
    sh("git", "clone", "-q", str(origin), str(work), cwd=tmp_path)
    (work / "README.md").write_text("app\n")
    sh("git", "add", "README.md", cwd=work)
    sh("git", "commit", "-q", "-m", "init", cwd=work)
    sh("git", "push", "-q", "origin", "HEAD:main", cwd=work)
    brief = tmp_path / "brief.md"
    brief.write_text("## Problem\n47% never come back after signup day\n")
    env = {"JVN_LOOP_STATE_DIR": str(tmp_path / "state")}

    def loop(*args, check=True):
        return sh(sys.executable, str(LOOP), *args, cwd=work, env=env, check=check)

    loop.add = lambda: loop(
        "add", "--title", "Divider for jobs posted since last visit", "--metric", "7d return",
        "--expected", "26% -> 28%", "--risk", "low", "--sms", "NS-{N} idea",
        "--brief-file", str(brief),
    )
    loop.origin, loop.work, loop.state = origin, work, tmp_path / "state"
    return loop


def branch_log(origin):
    return sh("git", "--git-dir", str(origin), "log", "--format=%s", "loop-state",
              cwd=origin).stdout.split("\n")[:-1]


def branch_file(origin, name):
    return sh("git", "--git-dir", str(origin), "show", f"loop-state:{name}", cwd=origin).stdout


def test_publish_creates_the_state_branch_with_db_and_readable_log(repo, tmp_path):
    repo.add()
    out = repo("publish")
    assert "published loop-state: NS-1 proposed" in out.stdout

    files = sh("git", "--git-dir", str(repo.origin), "ls-tree", "--name-only", "loop-state",
               cwd=tmp_path).stdout.split()
    assert sorted(files) == ["LOG.md", "loop.db"]  # only the state, none of main's files
    log = branch_file(repo.origin, "LOG.md")
    assert "## NS-1 · Divider for jobs posted since last visit" in log
    assert "47% never come back after signup day" in log  # the full brief, not a summary

    snapshot = tmp_path / "snapshot.db"
    snapshot.write_bytes(subprocess.run(
        ["git", "--git-dir", str(repo.origin), "show", "loop-state:loop.db"],
        capture_output=True, check=True).stdout)
    assert sqlite3.connect(snapshot).execute("SELECT title FROM proposals").fetchone()[0] \
        == "Divider for jobs posted since last visit"
    main_files = sh("git", "--git-dir", str(repo.origin), "ls-tree", "--name-only", "main",
                    cwd=tmp_path).stdout.split()
    assert main_files == ["README.md"]


def test_publish_commits_only_when_state_changed(repo):
    repo.add()
    repo("publish")
    assert "loop-state unchanged" in repo("publish").stdout
    repo("decide", "1", "no", "too", "big")
    repo("publish")
    assert branch_log(repo.origin) == ["loop-state: NS-1 decision", "loop-state: NS-1 proposed"]
    assert "rejected: too big" in branch_file(repo.origin, "LOG.md")


def test_publish_recovers_when_the_local_worktree_is_gone(repo):
    repo.add()
    repo("publish")
    sh("git", "worktree", "remove", "--force", str(repo.state / "loop-state"), cwd=repo.work)
    repo("decide", "1", "yes")
    repo("publish")
    assert branch_log(repo.origin) == ["loop-state: NS-1 decision", "loop-state: NS-1 proposed"]


def test_publish_is_skipped_in_a_dry_run(repo):
    repo.add()
    out = sh(sys.executable, str(LOOP), "publish", cwd=repo.work,
             env={"JVN_LOOP_STATE_DIR": str(repo.state), "JVN_LOOP_DRY_RUN": "1"})
    assert "dry run" in out.stdout
    assert sh("git", "--git-dir", str(repo.origin), "branch", "--list", "loop-state",
              cwd=repo.work).stdout == ""


@pytest.fixture
def notify(tmp_path):
    sent = tmp_path / "sent.txt"
    send = executable(tmp_path / "send.sh", f'#!/bin/sh\nprintf "%s" "$1" > "{sent}"\n')
    calls = tmp_path / "npx-calls.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    executable(bin_dir / "npx",
               f'#!/bin/sh\npwd > "{calls}"\nfor a in "$@"; do printf "%s\\n" "$a" >> "{calls}"; done\n')
    boop = tmp_path / "boop"
    boop.mkdir()
    state = tmp_path / "state"
    state.mkdir()

    def run(msg, env=None, notify_env=None):
        (state / "notify.env").write_text(
            "".join(f"{k}={v}\n" for k, v in (notify_env or {}).items()))
        full = {"JVN_LOOP_STATE_DIR": str(state), "JVN_LOOP_SEND": str(send),
                "JVN_LOOP_PROJECT_DIR": "/srv/jvn", "PATH": f"{bin_dir}:{os.environ['PATH']}",
                **(env or {})}
        return sh("sh", str(NOTIFY), msg, cwd=tmp_path, env=full, check=False)

    run.sent, run.calls, run.boop = sent, calls, boop
    return run


def test_notify_sends_and_writes_the_same_text_into_boop_history(notify):
    out = notify("NS-2 idea → 7d return\nReply \"yes 2\"",
                 notify_env={"BOOP_DIR": notify.boop, "BOOP_CONVERSATION_ID": "sms:+15550001111"})
    assert out.returncode == 0, out.stderr
    assert notify.sent.read_text() == "NS-2 idea → 7d return\nReply \"yes 2\""

    cwd, *argv = notify.calls.read_text().split("\n")[:-1]
    assert Path(cwd).resolve() == notify.boop.resolve()
    assert argv[:4] == ["--yes", "convex", "run", "messages:send"]
    payload = json.loads("\n".join(argv[4:]))
    assert payload["conversationId"] == "sms:+15550001111"
    assert payload["role"] == "assistant"
    assert "Reply \"yes 2\"" in payload["content"]
    assert "loop.py decide N yes" in payload["content"]  # Boop is told how to act on the reply
    assert "/srv/jvn" in payload["content"]


def test_notify_without_boop_config_still_sends_but_says_history_is_missing(notify):
    out = notify("NS-2 PR ready")
    assert out.returncode == 4
    assert notify.sent.read_text() == "NS-2 PR ready"
    assert "Boop has no record" in out.stderr
    assert not notify.calls.exists()


def test_notify_skips_boop_when_send_already_records_history(notify):
    out = notify("NS-2 PR ready", notify_env={"SEND_WRITES_BOOP_HISTORY": "1"})
    assert out.returncode == 0
    assert not notify.calls.exists()


def test_notify_missing_send_script_is_an_error_not_a_dry_run(notify, tmp_path):
    out = notify("NS-2 idea", env={"JVN_LOOP_SEND": str(tmp_path / "nope.sh")})
    assert out.returncode == 2
    assert not notify.sent.exists()


def test_notify_dry_run_only_prints(notify):
    out = notify("NS-2 idea", env={"JVN_LOOP_DRY_RUN": "1"})
    assert out.returncode == 0
    assert out.stdout.strip() == "[DRY-RUN TEXT] NS-2 idea"
    assert not notify.sent.exists()
