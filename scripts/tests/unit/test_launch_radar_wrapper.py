"""Guard: the launchd wrapper must never skip permissions, and its allowlist must stay narrow.

The radar reads web text and has the backend's internal key in reach (through
radar.sh). A bare ``Bash`` or ``Bash(*)`` in the allowlist, or the skip flag,
would let a prompt injection run anything. This test reads the files as text.
"""

import os
import re
import shlex
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
LR = ROOT / "scripts" / "launch_radar"
WRAPPER = LR / "wrapper.sh"


def _allowlist_block() -> str:
    text = WRAPPER.read_text()
    m = re.search(r"# ALLOWED_TOOLS-BEGIN.*?\n(.*?)# ALLOWED_TOOLS-END", text, re.S)
    assert m, "ALLOWED_TOOLS block missing from wrapper.sh"
    return m.group(1)


def _allowed_tools() -> list[str]:
    tokens = shlex.split(_allowlist_block().replace("\\\n", " "))
    start = tokens.index("--allowedTools") + 1
    end = tokens.index("--disallowedTools")
    return tokens[start:end]


def _code_lines(path: Path) -> list[str]:
    return [ln for ln in path.read_text().splitlines() if not ln.lstrip().startswith(("#", "<!--"))]


def test_no_skip_permissions_flag_anywhere():
    flag = "--dangerously-skip-permissions"
    for path in (WRAPPER, LR / "radar.sh", LR / "install_launch_agent.sh"):
        assert not any(flag in ln for ln in _code_lines(path)), path
    # The docs may only mention the flag to forbid it.
    for path in (ROOT / ".claude" / "commands" / "launch-radar-once.md",
                 ROOT / ".claude" / "skills" / "launch-radar" / "SKILL.md", LR / "README.md"):
        for ln in path.read_text().splitlines():
            if flag in ln:
                assert re.search(r"\b(never|not|no)\b", ln, re.I), f"{path}: {ln}"


# Every Bash entry the headless session may run. Exact radar.sh commands pin the
# per-run limits (3 companies, $1.00).
EXPECTED_BASH = {
    "Bash(scripts/launch_radar/radar.sh monitors-ensure)",
    "Bash(scripts/launch_radar/radar.sh run --max-companies 3 --budget 1.00)",
    "Bash(scripts/launch_radar/radar.sh run --max-companies 0 --budget 1.00)",
    "Bash(scripts/launch_radar/radar.sh grade-export --ungraded --dir .launch-radar-grades)",
    "Bash(scripts/launch_radar/radar.sh grade-apply --dir .launch-radar-grades)",
    "Bash(scripts/launch_radar/radar.sh heartbeat:*)",
}

# The run's only write: a grader's JSON reply, which grade-apply validates. Agent is for
# the one-subagent-per-card graders (they inherit this allowlist).
EXPECTED_OTHER = {"Read(./**)", "Edit(./.launch-radar-grades/grades/**)", "Agent"}


def test_wrapper_invokes_claude_with_an_allowlist():
    block = _allowlist_block()
    assert '"$CLAUDE_BIN" -p /launch-radar-once' in block
    # The host's user/local settings (a default mode such as auto, allow rules) must not
    # widen the list: unlisted tools are denied and only the tracked project settings load.
    tokens = shlex.split(block.replace("\\\n", " "))
    assert tokens[tokens.index("--permission-mode") + 1] == "dontAsk"
    assert tokens[tokens.index("--setting-sources") + 1] == "project"
    tools = _allowed_tools()
    # The run drives the loop, posts cards and grades their Talent: no web tools (the
    # loop does its own research through radar.sh), and writes only the graders' replies.
    assert set(tools) == EXPECTED_OTHER | EXPECTED_BASH
    assert not any(t.startswith(("WebSearch", "WebFetch", "Write(")) for t in tools)
    for t in tools:
        assert t != "Bash", "bare Bash is not allowed"
        assert not re.fullmatch(r"Bash\(\s*\*?\s*\)", t), f"wildcard Bash: {t}"
        assert not t.startswith("Bash(*"), f"wildcard Bash: {t}"
        if t.startswith(("Read", "Glob", "Grep")):
            assert t.endswith("(./**)"), f"file reads must stay in the checkout: {t}"
        if t.startswith("Edit("):
            assert t == "Edit(./.launch-radar-grades/grades/**)", f"writes must stay in the grades dir: {t}"


@pytest.mark.parametrize("tool", ["git", "gh", "curl", "wget", "python", "python3", "pip", "npm", "npx", "cd",
                                  "/tmp/", "sh ", "bash", "node", "uv "])
def test_no_generic_code_or_upload_entry(tool):
    """Each of these can run arbitrary code or send a local file somewhere."""
    for t in _allowed_tools():
        if t.startswith("Bash("):
            assert not t[len("Bash("):].startswith(tool), f"{t} hands the session a free {tool}"


@pytest.mark.parametrize("path", [ROOT / ".claude" / "skills" / "launch-radar" / "SKILL.md",
                                  ROOT / ".claude" / "commands" / "launch-radar-once.md"])
def test_skill_runs_only_radar_sh(path):
    """The add-company PR step was removed (it opened PRs on its own). The skill and its
    headless command may point at no loop entry point but radar.sh (plus the runbook and
    the wrapper), and never at a temporary worktree or the add-company skill."""
    text = path.read_text()
    assert set(re.findall(r"scripts/launch_radar/[\w.]+", text)) <= {
        "scripts/launch_radar/radar.sh", "scripts/launch_radar/README.md", "scripts/launch_radar/wrapper.sh"}
    assert ".claude/worktrees" not in text and "add-company" not in text


def test_secrets_are_denied_and_not_handled_by_the_wrapper():
    block = _allowlist_block()
    disallowed = shlex.split(block.replace("\\\n", " "))
    disallowed = disallowed[disallowed.index("--disallowedTools") + 1:]
    assert "Read(~/.config/jvn-launch-radar/**)" in disallowed
    for denied in ("Read(~/.ssh/**)", "Read(~/.zshrc)", "Read(./**/.env)", "Read(./**/.env.*)",
                   # in-checkout files that can hold credentials (IDE run configs, MCP config, git remotes)
                   "Read(./.git/**)", "Read(./.idea/**)", "Read(./.vscode/**)", "Read(./.mcp.json)",
                   "Read(./.claude/settings*.json)", "Read(./.playwright-mcp/**)"):
        assert denied in disallowed, denied
    assert "Bash(env:*)" in disallowed and "Bash(printenv:*)" in disallowed
    code = "\n".join(_code_lines(WRAPPER))
    assert "jvn-launch-radar/env" not in code
    assert not re.search(r"^\s*(export|\.|source)\s", code, re.M), "the wrapper must not source or export anything"
    assert "PARALLEL_API_KEY" not in code and "INTERNAL_API_KEY" not in code


def test_wrapper_takes_paths_from_the_plist_environment():
    text = WRAPPER.read_text()
    assert ': "${CLAUDE_BIN:?' in text and ': "${PROJECT_DIR:?' in text
    assert "/Users/" not in text
    plist = (LR / "com.bp.jvn-launch-radar.plist.template").read_text()
    for key in ("PROJECT_DIR", "CLAUDE_BIN", "PATH"):
        assert f"<key>{key}</key>" in plist
    assert "__PROJECT_DIR__/scripts/launch_radar/wrapper.sh" in plist
    assert "<key>Hour</key>\n        <integer>19</integer>" in plist  # 7pm local


def test_skill_quotes_the_same_allowlist():
    skill = (ROOT / ".claude" / "skills" / "launch-radar" / "SKILL.md").read_text()
    block = _allowlist_block()
    m = re.search(r"```sh\n(.*?)```", skill, re.S)
    assert m, "SKILL.md §0 has no allowlist block"
    quoted = shlex.split(m.group(1).replace("\\\n", " "))
    expected = shlex.split(block.replace("\\\n", " "))
    expected = expected[expected.index('$CLAUDE_BIN'):]
    assert quoted == expected, "SKILL.md §0 must quote wrapper.sh's ALLOWED_TOOLS block verbatim"


@pytest.mark.parametrize("name", ["wrapper.sh", "radar.sh", "install_launch_agent.sh"])
def test_scripts_parse_and_launcher_is_executable(name):
    subprocess.run(["sh", "-n", str(LR / name)], check=True)
    if name == "radar.sh":
        assert os.stat(LR / name).st_mode & stat.S_IXUSR


def test_radar_sh_finds_uv_on_path():
    code = "\n".join(_code_lines(LR / "radar.sh"))
    assert "/opt/homebrew/bin/uv" not in code
    assert 'command -v uv' in code


def test_wrapper_fails_fast_without_plist_env(tmp_path):
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    r = subprocess.run(["sh", str(WRAPPER)], env=env, capture_output=True, text=True)
    assert r.returncode != 0
    assert "CLAUDE_BIN must be set" in r.stderr


def _fake_claude(tmp_path, note_status):
    """A stand-in for claude that appends one heartbeat line and exits 0."""
    state = tmp_path / "Library" / "Application Support" / "jvn-launch-radar"
    script = tmp_path / "fake-claude"
    script.write_text(
        "#!/bin/sh\n"
        f'mkdir -p "{state}"\n'
        f'echo "2026-10-07T07:00:00Z status={note_status} run exit 0, note says status=error" >> "{state}/heartbeat.log"\n'
        "exit 0\n"
    )
    script.chmod(0o755)
    return script


@pytest.mark.parametrize("beat,expected", [("ok", 0), ("error", 98)])
def test_wrapper_surfaces_a_recorded_error(tmp_path, beat, expected):
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin", "CLAUDE_BIN": str(_fake_claude(tmp_path, beat)),
           "PROJECT_DIR": str(tmp_path), "JVN_RADAR_TIMEOUT_SECS": "60"}
    r = subprocess.run(["sh", str(WRAPPER)], env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == expected, r.stderr
    if expected:
        assert "launch-radar reported status=error" in r.stderr
    else:
        assert "status=error" not in r.stderr  # the note's text alone must not trip it
