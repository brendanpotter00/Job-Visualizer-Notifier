"""Guard: the launchd wrapper must never skip permissions, and its allowlist must stay narrow.

The radar reads web text, has the backend's internal key in reach (through
radar.sh) and opens add-company PRs for Saved cards (through pr_step.py). A bare
``Bash`` or ``Bash(*)`` in the allowlist, a generic git/gh entry, or the skip flag
would let a prompt injection run anything, push anywhere or merge. This test reads
the files as text (and runs the wrapper against a fake claude).
"""

import ast
import os
import re
import shlex
import stat
import subprocess
import time
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


SKILL = ROOT / ".claude" / "skills" / "launch-radar" / "SKILL.md"
COMMAND = ROOT / ".claude" / "commands" / "launch-radar-once.md"
SCOUT = ROOT / ".claude" / "agents" / "launch-radar-scout.md"


def test_no_skip_permissions_flag_anywhere():
    flag = "--dangerously-skip-permissions"
    for path in (WRAPPER, LR / "radar.sh", LR / "install_launch_agent.sh", LR / "pr_step.py", LR / "logo_setup.sh"):
        assert not any(flag in ln for ln in _code_lines(path)), path
    # The docs may only mention the flag to forbid it.
    for path in (ROOT / ".claude" / "commands" / "launch-radar-once.md",
                 ROOT / ".claude" / "skills" / "launch-radar" / "SKILL.md", LR / "README.md"):
        for ln in path.read_text().splitlines():
            if flag in ln:
                assert re.search(r"\b(never|not|no)\b", ln, re.I), f"{path}: {ln}"


# Every Bash entry the headless session may run. Exact radar.sh commands pin the
# per-run limits (3 companies, $1.00); pr-next and pr-refresh take no arguments; the
# prefix entries (pr-check, pr-report, pr_step.py) validate every argument themselves.
EXPECTED_BASH = {
    "Bash(scripts/launch_radar/radar.sh monitors-ensure)",
    "Bash(scripts/launch_radar/radar.sh run --max-companies 3 --budget 1.00)",
    "Bash(scripts/launch_radar/radar.sh run --max-companies 0 --budget 1.00)",
    "Bash(scripts/launch_radar/radar.sh grade-export --ungraded --dir .launch-radar-grades)",
    "Bash(scripts/launch_radar/radar.sh grade-apply --dir .launch-radar-grades)",
    "Bash(scripts/launch_radar/radar.sh pr-next)",
    "Bash(scripts/launch_radar/radar.sh pr-refresh)",
    "Bash(scripts/launch_radar/radar.sh pr-check:*)",
    "Bash(scripts/launch_radar/radar.sh pr-report:*)",
    "Bash(scripts/launch_radar/pr_step.py:*)",
    "Bash(scripts/launch_radar/radar.sh heartbeat:*)",
}

# The run's only writes: a grader's JSON reply (grade-apply validates it) and a scout's
# JSON reply (pr_step.py's parse_scout refuses it whole on any violation). Agent is
# scoped to the grader (tool: Read) and the scout (tools: WebSearch, WebFetch); the web
# tools are on the list for the scout (see the tests below).
EXPECTED_EDIT = {"Edit(./.launch-radar-grades/grades/**)", "Edit(./.launch-radar-pr/scout/**)"}
EXPECTED_OTHER = {"Read(./**)", "Agent(launch-radar-grader)", "Agent(launch-radar-scout)", "WebSearch",
                  "WebFetch"} | EXPECTED_EDIT


def test_the_grader_agent_can_only_read():
    """A grader reads untrusted card text, so it must not get the run's Bash commands."""
    text = (ROOT / ".claude" / "agents" / "launch-radar-grader.md").read_text()
    front = text.split("---")[1]
    assert re.search(r"^name: launch-radar-grader$", front, re.M)
    assert re.search(r"^tools: Read$", front, re.M)


def test_the_scout_agent_has_only_web_tools():
    """The scout reads web pages, so it gets the web tools and nothing else: no Bash, no
    Read, no Write. Its reply is saved verbatim by the main session and parsed by pr_step."""
    front = SCOUT.read_text().split("---")[1]
    assert re.search(r"^name: launch-radar-scout$", front, re.M)
    assert re.search(r"^tools: WebSearch, WebFetch$", front, re.M)
    assert len(re.findall(r"^tools:", front, re.M)) == 1


def test_wrapper_invokes_claude_with_an_allowlist():
    block = _allowlist_block()
    assert '"$CLAUDE_BIN" -p /launch-radar-once' in block
    # The host's user/local settings (a default mode such as auto, allow rules) must not
    # widen the list: unlisted tools are denied and only the tracked project settings load.
    tokens = shlex.split(block.replace("\\\n", " "))
    assert tokens[tokens.index("--permission-mode") + 1] == "dontAsk"
    assert tokens[tokens.index("--setting-sources") + 1] == "project"
    tools = _allowed_tools()
    assert set(tools) == EXPECTED_OTHER | EXPECTED_BASH
    assert len(tools) == len(set(tools))
    # Web tools exist only for the scout: they are on the list only with its Agent entry.
    assert "WebSearch" in tools and "WebFetch" in tools and "Agent(launch-radar-scout)" in tools
    assert "Agent" not in tools, "a bare Agent hands any subagent the run's Bash commands"
    assert [t for t in tools if t.startswith("Agent")] == ["Agent(launch-radar-grader)", "Agent(launch-radar-scout)"]
    # Writes stay in the two reply dirs: never Write(...), never the PR worktrees.
    assert {t for t in tools if t.startswith("Edit(")} == EXPECTED_EDIT
    assert not any(t.startswith("Write(") for t in tools)
    assert not any(".claude/worktrees" in t for t in tools if t.startswith(("Edit(", "Write(")))
    for t in tools:
        assert t != "Bash", "bare Bash is not allowed"
        assert not re.fullmatch(r"Bash\(\s*\*?\s*\)", t), f"wildcard Bash: {t}"
        assert not t.startswith("Bash(*"), f"wildcard Bash: {t}"
        if t.startswith(("Read", "Glob", "Grep")):
            assert t.endswith("(./**)"), f"file reads must stay in the checkout: {t}"


def test_the_session_gets_the_run_id_and_nothing_else():
    """claude starts as exactly `env LAUNCH_RADAR_RUN_ID="$RUN_ID" "$CLAUDE_BIN" -p ...`: the
    run id (not a secret) is the only variable the wrapper adds to the session's env."""
    block = _allowlist_block()
    assert 'env LAUNCH_RADAR_RUN_ID="$RUN_ID" "$CLAUDE_BIN" -p /launch-radar-once' in block
    tokens = shlex.split(block.replace("\\\n", " "))
    assert tokens[:tokens.index("$CLAUDE_BIN")] == [
        "run_bounded", "launch-radar", "$TOTAL_TIMEOUT_SECS", "env", "LAUNCH_RADAR_RUN_ID=$RUN_ID"]


@pytest.mark.parametrize("tool", ["git", "gh", "curl", "wget", "python", "python3", "pip", "npm", "npx", "cd",
                                  "/tmp/", "sh ", "bash", "node", "uv "])
def test_no_generic_code_or_upload_entry(tool):
    """Each of these can run arbitrary code or send a local file somewhere."""
    for t in _allowed_tools():
        if t.startswith("Bash("):
            assert not t[len("Bash("):].startswith(tool), f"{t} hands the session a free {tool}"


def _inline_code_spans(text: str) -> list[str]:
    """The `code` spans of a markdown file, outside fenced blocks."""
    prose = re.sub(r"```.*?```", "", text, flags=re.S)
    return re.findall(r"`([^`\n]+)`", prose)


@pytest.mark.parametrize("path", [SKILL, COMMAND])
def test_skill_runs_only_radar_sh_and_pr_step(path):
    """The skill and its headless command point at no loop entry point but radar.sh and
    pr_step.py (plus the runbook and the wrapper). They never tell the session to run git,
    gh, curl or python itself, never run pr_step.py refresh (radar.sh pr-refresh does, with a
    scrubbed env), and never hand the add-company procedure to the Skill tool."""
    text = path.read_text()
    assert set(re.findall(r"scripts/launch_radar/[\w.]+", text)) <= {
        "scripts/launch_radar/radar.sh", "scripts/launch_radar/pr_step.py", "scripts/launch_radar/README.md",
        "scripts/launch_radar/wrapper.sh"}
    assert not re.search(r"pr_step\.py\s+refresh", text)
    for span in _inline_code_spans(text):
        # A bare name in "there is no `curl` entry" is prose; a name with arguments is a command.
        assert not re.match(r"(git|gh|curl|python[0-9.]*)\s+\S", span), f"{path.name}: `{span}`"
    for line in text.splitlines():
        if "add-company" in line:
            assert "Skill" not in line, f"{path.name}: {line}"


def test_skill_has_the_pr_step_in_order():
    """§3 (refresh, then the per-card loop) runs after grading and before the heartbeat,
    and the loop checks the card is still saved before it publishes."""
    text = SKILL.read_text()
    order = [text.index(h) for h in ("## §1 Run the loop", "## §2 Grade", "## §3 Add-company PRs for Saved cards",
                                     "## §4 Heartbeat (FINAL step)")]
    assert order == sorted(order)
    s3 = text[order[2]:order[3]]
    steps = [s3.index(s) for s in (
        "radar.sh pr-refresh", "radar.sh pr-next", "launch-radar-scout", "pr_step.py worktree --card-id N",
        "pr_step.py verify-board --card-id N", "pr_step.py compose --card-id N", "pr_step.py logo-fetch",
        "pr_step.py check-head --card-id N", "radar.sh pr-check --card-id N", "pr_step.py publish --card-id N",
        "pr_step.py cleanup --card-id N")]
    assert steps == sorted(steps)
    assert "skip_optional" in s3 and "report_reason" in s3
    assert "Never call WebSearch or WebFetch yourself" in text


def test_pushing_and_pr_creation_only_through_pr_step():
    """pr_step.py is the only way to git and gh: an explicit refspec to its own ref, every
    push leased on that ref, hooks and fsmonitor off, and no merge of any kind."""
    path = LR / "pr_step.py"
    text = path.read_text()
    assert os.stat(path).st_mode & stat.S_IXUSR
    assert 'f"HEAD:refs/heads/{branch}"' in text  # explicit refspec: never radar/x:main
    assert "core.hooksPath=/dev/null" in text and "core.fsmonitor=false" in text
    tree = ast.parse(text)
    literals = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    for banned in ("merge", "--auto", "--admin", "--force", "-f"):
        assert banned not in literals, f"pr_step.py has the argv word {banned!r}"
    forces = [s for s in literals if "--force" in s]
    assert forces == ["--force-with-lease=refs/heads/"], forces  # the only force: a lease on its own ref
    assert not any(s.startswith(("+HEAD", "+refs")) for s in literals), "a + refspec forces a push"
    # Every gh call is one of the three it needs.
    gh_calls = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.List) and node.elts and isinstance(node.elts[0], ast.Constant) \
                and node.elts[0].value == "gh":
            gh_calls.add(tuple(e.value for e in node.elts[1:3] if isinstance(e, ast.Constant)))
    assert gh_calls == {("api", "user"), ("pr", "list"), ("pr", "create")}, gh_calls


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
    skill = SKILL.read_text()
    block = _allowlist_block()
    m = re.search(r"```sh\n(.*?)```", skill, re.S)
    assert m, "SKILL.md §0 has no allowlist block"
    quoted = shlex.split(m.group(1).replace("\\\n", " "))
    expected = shlex.split(block.replace("\\\n", " "))
    expected = expected[expected.index('$CLAUDE_BIN'):]
    assert quoted == expected, "SKILL.md §0 must quote wrapper.sh's ALLOWED_TOOLS block verbatim"


@pytest.mark.parametrize("name", ["wrapper.sh", "radar.sh", "install_launch_agent.sh", "logo_setup.sh"])
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


STATE_REL = Path("Library") / "Application Support" / "jvn-launch-radar"


def _fake_claude(tmp_path, note_status, exit_code=0):
    """A stand-in for claude: it records its LAUNCH_RADAR_RUN_ID and the wrapper's
    session_started_at, appends one heartbeat line (exit 0 only) and exits."""
    state = tmp_path / STATE_REL
    script = tmp_path / "fake-claude"
    beat = (f'echo "2026-10-07T07:00:00Z status={note_status} run exit 0, note says status=error" '
            f'>> "{state}/heartbeat.log"\n') if exit_code == 0 else ""
    script.write_text(
        "#!/bin/sh\n"
        f'mkdir -p "{state}"\n'
        f'printf "%s\\n" "$LAUNCH_RADAR_RUN_ID" > "{tmp_path}/seen_run_id"\n'
        f'cp "{state}/session_started_at" "{tmp_path}/seen_session" 2>/dev/null || true\n'
        + beat +
        f"exit {exit_code}\n"
    )
    script.chmod(0o755)
    return script


def _run_wrapper(tmp_path, claude):
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin", "CLAUDE_BIN": str(claude),
           "PROJECT_DIR": str(tmp_path), "JVN_RADAR_TIMEOUT_SECS": "60"}
    return subprocess.run(["sh", str(WRAPPER)], env=env, capture_output=True, text=True, timeout=120)


@pytest.mark.parametrize("beat,expected", [("ok", 0), ("error", 98)])
def test_wrapper_surfaces_a_recorded_error(tmp_path, beat, expected):
    r = _run_wrapper(tmp_path, _fake_claude(tmp_path, beat))
    assert r.returncode == expected, r.stderr
    if expected:
        assert "launch-radar reported status=error" in r.stderr
    else:
        assert "status=error" not in r.stderr  # the note's text alone must not trip it


def test_wrapper_gives_the_session_its_clock_and_removes_it(tmp_path):
    """§4.4: "<start_epoch> <run_id>" is written before claude starts, the session's
    LAUNCH_RADAR_RUN_ID is that run id, and the file is gone once the wrapper exits (so a
    later interactive run never inherits this run's clock)."""
    before = int(time.time())
    r = _run_wrapper(tmp_path, _fake_claude(tmp_path, "ok"))
    assert r.returncode == 0, r.stderr
    run_id = (tmp_path / "seen_run_id").read_text().strip()
    assert re.fullmatch(r"[0-9]{1,12}-[0-9]{1,10}", run_id), run_id  # pr_queue / pr_step RUN_ID
    start, seen_id = (tmp_path / "seen_session").read_text().split()
    assert seen_id == run_id and run_id.startswith(f"{start}-")
    assert before - 5 <= int(start) <= int(time.time())
    assert not (tmp_path / STATE_REL / "session_started_at").exists()


@pytest.mark.parametrize("code", [1, 3])
def test_a_failed_session_leaves_an_error_heartbeat(tmp_path, code):
    """D11: a killed or failed session never wrote its heartbeat, so the wrapper writes
    the error line itself (and still removes the clock file)."""
    r = _run_wrapper(tmp_path, _fake_claude(tmp_path, "ok", exit_code=code))
    assert r.returncode == code, r.stderr
    last = (tmp_path / STATE_REL / "heartbeat.log").read_text().splitlines()[-1]
    assert re.fullmatch(rf"\d{{4}}-\d\d-\d\dT\d\d:\d\d:\d\dZ status=error wrapper: session exit {code}", last), last
    assert not (tmp_path / STATE_REL / "session_started_at").exists()


def test_a_session_without_a_heartbeat_leaves_an_error_heartbeat(tmp_path):
    state = tmp_path / STATE_REL
    claude = tmp_path / "fake-claude"
    claude.write_text(f'#!/bin/sh\nmkdir -p "{state}"\nexit 0\n')
    claude.chmod(0o755)
    r = _run_wrapper(tmp_path, claude)
    assert r.returncode == 97, r.stderr
    last = (state / "heartbeat.log").read_text().splitlines()[-1]
    assert last.split()[1:] == ["status=error", "wrapper:", "session", "exit", "0", "without", "a", "heartbeat"]
