"""Guards for running the enricher from inside the JVN monorepo.

The `claude-code` engine runs `claude -p /enrich-tick-once` with cwd =
src/enricher, and its classifier/judge sub-agents inherit the same instruction
files. Per the Claude Code docs (memory, skills, sub-agents and settings pages):

* `CLAUDE.md` / `CLAUDE.local.md` load from the cwd AND EVERY ANCESTOR, into the
  orchestrator and into every sub-agent. An ancestor file inside JVN would be
  injected into every enrichment prompt.
* `AGENTS.md` loads only when no `CLAUDE.md` exists at or above the cwd (the
  default "claude-md-or-agents-md" mode), so src/enricher/CLAUDE.md keeps JVN's
  AGENTS.md files out.
* Project skills load from the cwd and every parent up to the repo root, and a
  ROOT skill wins over a nested one with the same name (a skill also beats a
  `.claude/commands/` file). A JVN-root `enrich-tick-once` would hijack the tick.
* Shared `.claude/settings.json` is read only from the starting directory.

Each test skips, with the reason, outside the monorepo (e.g. a bare copy of
src/enricher). CI always runs inside it. The prod ollama path never calls
`claude`; these guard the `claude-code` engine path.
"""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from pathlib import Path

import pytest

from job_enricher.store import JVN_ROOT, REPO_ROOT


def _jvn_root() -> Path:
    if not ((JVN_ROOT / "src" / "backend").is_dir() and (JVN_ROOT / "AGENTS.md").is_file()):
        pytest.skip(
            f"not inside the JVN monorepo: {JVN_ROOT} has no src/backend/ + AGENTS.md "
            "(a bare copy of src/enricher, e.g. a git-archived prod tag)"
        )
    return JVN_ROOT


def _tracked(root: Path, paths: list[str]) -> list[str]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--", *paths],
            capture_output=True, text=True, check=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.skip(f"cannot list tracked files under {root}: {exc}")
    return proc.stdout.split()


def _skill_names(skills_dir: Path) -> set[str]:
    """A skill's name is its frontmatter `name`, else its directory name."""
    names: set[str] = set()
    if not skills_dir.is_dir():
        return names
    for skill_md in skills_dir.glob("*/SKILL.md"):
        names.add(skill_md.parent.name)
        text = skill_md.read_text(encoding="utf-8")
        front = re.match(r"---\n(.*?)\n---", text, re.S)
        if front:
            m = re.search(r"^name:\s*['\"]?([^'\"\s]+)", front.group(1), re.M)
            if m:
                names.add(m.group(1))
    return names


def _command_names(commands_dir: Path) -> set[str]:
    """`commands/a.md` -> `a`; `commands/x/a.md` -> `x:a`."""
    if not commands_dir.is_dir():
        return set()
    return {
        ":".join(p.relative_to(commands_dir).with_suffix("").parts)
        for p in commands_dir.rglob("*.md")
    }


def test_no_ancestor_claude_md_is_tracked_inside_jvn():
    root = _jvn_root()
    ancestors = ["", "src/"]  # every directory between the JVN root and src/enricher
    candidates = [
        f"{d}{name}"
        for d in ancestors
        for name in ("CLAUDE.md", "CLAUDE.local.md", ".claude/CLAUDE.md")
    ]
    tracked = _tracked(root, candidates)
    assert tracked == [], (
        f"{tracked} would load into EVERY `claude -p` enrichment prompt and every "
        "classifier/judge sub-agent: Claude Code reads CLAUDE.md and CLAUDE.local.md "
        "from the cwd (src/enricher) and every ancestor. Put JVN-wide agent notes "
        "in AGENTS.md instead (src/enricher/CLAUDE.md keeps AGENTS.md out)."
    )


def test_the_enricher_keeps_its_own_claude_md():
    """Its presence is what keeps every JVN AGENTS.md out of enrichment
    prompts under Claude Code's default instruction-file mode."""
    _jvn_root()
    assert (REPO_ROOT / "CLAUDE.md").is_file()


def test_jvn_root_project_settings_carry_no_hooks_or_permissions():
    """Per the current docs this file is read only by sessions that START at
    the JVN root, so it should never reach `claude -p` in src/enricher. This is
    a tripwire in case that rule changes: a hook or permission rule here would
    then run around every unattended enrichment run."""
    root = _jvn_root()
    settings = root / ".claude" / "settings.json"
    if not settings.exists():
        return
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert "hooks" not in data, f"{settings} defines hooks"
    assert "permissions" not in data, f"{settings} defines permissions"


def test_the_enricher_sandboxed_agents_and_commands_are_still_here():
    _jvn_root()
    agents = REPO_ROOT / ".claude" / "agents"
    commands = REPO_ROOT / ".claude" / "commands"
    assert (agents / "classifier.md").is_file()
    assert (agents / "judge.md").is_file()
    assert (commands / "enrich-tick-once.md").is_file()


def test_no_jvn_root_skill_or_command_shadows_an_enricher_one():
    """A root skill beats a nested one of the same name, and a skill beats a
    command file. The wrapper runs `/enrich-tick-once` and every agent reads the
    `taxonomy` skill, so a JVN-root namesake would silently replace them."""
    root = _jvn_root()
    jvn = _skill_names(root / ".claude" / "skills") | _command_names(root / ".claude" / "commands")
    enricher = _skill_names(REPO_ROOT / ".claude" / "skills") | _command_names(
        REPO_ROOT / ".claude" / "commands"
    )
    assert "enrich-tick-once" in enricher and "taxonomy" in enricher
    clash = sorted(jvn & enricher)
    assert clash == [], f"JVN-root skills/commands shadow the enricher's: {clash}"


def test_package_relative_state_stays_inside_src_enricher():
    """DB, lock and chunk paths hang off store.REPO_ROOT, so each checkout owns
    its own data/. In the monorepo that root must be src/enricher, never the
    JVN root."""
    root = _jvn_root()
    assert REPO_ROOT == root / "src" / "enricher"
    manifest = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert manifest["project"]["name"] == "job-enricher"


@pytest.mark.parametrize(
    "repo_root, want",
    [
        ("/Users/x/JVN/src/enricher", "/Users/x/JVN"),
        ("/tmp/enricher", "/"),
        ("/enricher", "/enricher"),  # a bare copy right under / : no IndexError at import
        ("/", "/"),
    ],
)
def test_monorepo_root_never_raises(repo_root, want):
    from job_enricher.store import monorepo_root

    assert monorepo_root(Path(repo_root)) == Path(want)
