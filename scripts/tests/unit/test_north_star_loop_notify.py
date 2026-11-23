"""notify.sh: the north-star loop's texts.

It sends a text AND writes it into Boop's conversation history through Convex
`messages:send` (the call Boop's own automations use), so a reply like
"yes 1" reaches Boop with context. Exit codes are its contract (README "Texts
and replies").
"""
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "north_star_loop"
NOTIFY = ROOT / "notify.sh"


def sh(*args, cwd, env=None, check=True):
    out = subprocess.run(list(args), cwd=cwd, capture_output=True, text=True,
                         env={**os.environ, **(env or {})})
    if check:
        assert out.returncode == 0, out.stderr
    return out


def executable(path: Path, body: str) -> Path:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


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
    # Boop is told how to act on a multi-number reply like "yes 4 6"
    assert "loop.py decide <N> yes` once for each number" in payload["content"]
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
