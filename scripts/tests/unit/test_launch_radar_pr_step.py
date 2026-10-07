"""pr_step.py: the PR step's only entry point. Every value is validated, git runs with
hooks off, pushes go only to refs/heads/radar/add-<slug>, and only the add-company
files can be committed. Uses throwaway git repos in tmp_path; gh is stubbed."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from launch_radar import pr_step
from launch_radar.pr_step import StepError

SCAFFOLD = "import sys\nprint('scaffolded', sys.argv[1:])\n"
HEAD = "print('abc123')\n"


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """origin (bare) with a main branch, and ROOT = a clone of it."""
    seed = tmp_path / "seed"
    seed.mkdir()
    git("init", "-q", "-b", "main", cwd=seed)
    git("config", "user.email", "t@example.com", cwd=seed)
    git("config", "user.name", "T", cwd=seed)
    scripts = seed / ".claude/skills/add-company/scripts"
    scripts.mkdir(parents=True)
    (scripts / "scaffold_migration.py").write_text(SCAFFOLD)
    (scripts / "current_head.py").write_text(HEAD)
    cfg = seed / "src/frontend/src/config"
    cfg.mkdir(parents=True)
    (cfg / "companies.ts").write_text("export const C = [];\n")
    (cfg / "changelog.ts").write_text("export const L = [];\n")
    git("add", "-A", cwd=seed)
    git("commit", "-q", "-m", "init", cwd=seed)
    origin = tmp_path / "origin.git"
    git("clone", "-q", "--bare", str(seed), str(origin), cwd=tmp_path)
    root = tmp_path / "root"
    git("clone", "-q", str(origin), str(root), cwd=tmp_path)
    git("config", "user.email", "t@example.com", cwd=root)
    git("config", "user.name", "T", cwd=root)
    monkeypatch.setattr(pr_step, "ROOT", root)
    monkeypatch.setattr(pr_step, "WORKTREES", root / ".claude" / "worktrees")
    return root, origin


# ---- validation ---------------------------------------------------------------------
@pytest.mark.parametrize("card_id", ["0", "-1", "1;rm", "abc", "12 3", "", "1/../2"])
def test_card_id_is_refused(card_id):
    with pytest.raises(StepError):
        pr_step.card_dir(card_id)


@pytest.mark.parametrize("slug", ["Ghost", "-x", "a/b", "a b", "../x", "x" * 50, "a;b", ""])
def test_bad_slug_is_refused(repo, slug):
    with pytest.raises(StepError, match="slug"):
        pr_step.cmd_worktree("1", slug)


@pytest.mark.parametrize("title", [
    "feat(companies): add Ghost AI (Ashby)",
    "feat(companies): add O'Reilly & Co. (Greenhouse)",
])
def test_good_titles(title):
    assert pr_step.TITLE.match(title)


@pytest.mark.parametrize("title", [
    "feat(companies): add Ghost AI (Workday)",
    "feat(companies): add $(whoami) (Ashby)",
    "feat(companies): add Ghost AI (Ashby)\nmalicious",
    "fix: something else",
])
def test_bad_titles(title):
    assert not pr_step.TITLE.match(title)


@pytest.mark.parametrize("url", [
    "http://example.com/logo.svg",
    "https://user:pw@example.com/logo.svg",
    "file:///etc/passwd",
    "https://127.0.0.1/logo.svg",
    "https://localhost/logo.svg",
    "https://10.0.0.1/logo.svg",
    "https://169.254.169.254/latest/meta-data",
    "https://exa mple.com/x",
])
def test_logo_urls_must_be_public_https(url):
    with pytest.raises(StepError):
        pr_step.check_logo_url(url)


def test_staged_problems_allow_only_the_add_company_files():
    def rec(mode: str, status: str, path: str) -> str:
        return f":100644 {mode} aaaa bbbb {status}\0{path}\0"

    ok = (rec("100644", "M", "src/frontend/src/config/companies.ts")
          + rec("100644", "M", "src/frontend/src/config/changelog.ts")
          + rec("100644", "A", "src/backend/alembic/versions/2026_10_07_ab12_seed_ghost-ai_company.py")
          + rec("100644", "A", "src/frontend/public/logos/icons/ghost-ai.png")
          + rec("100644", "A", "src/frontend/public/logos/wordmarks/ghost-ai.png"))
    assert pr_step.staged_problems(ok) == []
    bad = (rec("100644", "A", ".github/workflows/x.yml")
           + rec("100644", "M", "src/frontend/src/__tests__/config/companyLogoAssets.test.ts")
           + rec("120000", "A", "src/frontend/public/logos/icons/evil.png")
           + rec("100755", "A", "src/backend/alembic/versions/x_seed_y_company.py")
           + rec("000000", "D", "src/frontend/src/config/changelog.ts")
           + rec("100644", "A", "src/frontend/src/config/companies.ts"))
    problems = pr_step.staged_problems(bad)
    assert len(problems) == 6, problems


# ---- worktree, integrity, publish -------------------------------------------------------
def test_worktree_creates_a_radar_branch_and_avoids_a_taken_name(repo):
    root, origin = repo
    out = pr_step.cmd_worktree("7", "ghost-ai")
    assert out == {"worktree": ".claude/worktrees/radar-7", "branch": "radar/add-ghost-ai"}
    assert (root / ".claude/worktrees/radar-7/src/frontend/src/config/companies.ts").exists()
    git("push", "-q", "origin", "radar/add-ghost-ai", cwd=root)
    assert pr_step.cmd_worktree("8", "ghost-ai")["branch"] == "radar/add-ghost-ai-2"
    with pytest.raises(StepError, match="already exists"):
        pr_step.cmd_worktree("7", "ghost-ai")


def test_a_rewritten_git_pointer_is_refused(repo, tmp_path):
    pr_step.cmd_worktree("7", "ghost-ai")
    dot_git = repo[0] / ".claude/worktrees/radar-7/.git"
    evil = tmp_path / "evil-gitdir"
    evil.mkdir()
    dot_git.write_text(f"gitdir: {evil}\n")
    with pytest.raises(StepError, match="does not point at"):
        pr_step.cmd_status("7")


def test_edited_scaffold_script_is_not_run(repo):
    pr_step.cmd_worktree("7", "ghost-ai")
    assert "scaffolded" in pr_step.cmd_scaffold("7", "ghost-ai", "Ghost AI", "ashby", "ghost")["output"]
    script = repo[0] / ".claude/worktrees/radar-7/.claude/skills/add-company/scripts/scaffold_migration.py"
    script.write_text("import os; os.system('touch /tmp/pwned')\n")
    with pytest.raises(StepError, match="differs from origin/main"):
        pr_step.cmd_scaffold("7", "ghost-ai", "Ghost AI", "ashby", "ghost")
    with pytest.raises(StepError, match="differs from origin/main"):
        pr_step.cmd_check_head("7")


@pytest.mark.parametrize("bad", [
    {"ats": "workday"}, {"token": "a/b"}, {"display_name": "Ghost$(id)"}, {"display_name": "x" * 61},
])
def test_scaffold_refuses_bad_values(repo, bad):
    pr_step.cmd_worktree("7", "ghost-ai")
    args = {"card_id": "7", "slug": "ghost-ai", "display_name": "Ghost AI", "ats": "ashby", "token": "ghost"}
    args.update(bad)
    with pytest.raises(StepError):
        pr_step.cmd_scaffold(**args)


def _stub_gh(monkeypatch):
    real = pr_step.run
    calls = []

    def run(argv, cwd=None, check=True):
        if argv[0] == "gh":
            calls.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, "https://github.com/x/y/pull/9\n", "")
        return real(argv, cwd=cwd, check=check)

    monkeypatch.setattr(pr_step, "run", run)
    return calls


def test_publish_pushes_only_the_radar_branch(repo, monkeypatch):
    root, origin = repo
    calls = _stub_gh(monkeypatch)
    pr_step.cmd_worktree("7", "ghost-ai")
    wt = root / ".claude/worktrees/radar-7"
    (wt / "src/frontend/src/config/companies.ts").write_text("export const C = ['ghost-ai'];\n")
    body = root / ".claude/worktrees/radar-7-logo/pr-body.md"
    body.parent.mkdir(parents=True)
    body.write_text("Found by Launch Radar card 7.\n")
    out = pr_step.cmd_publish("7", "feat(companies): add Ghost AI (Ashby)", str(body), draft=True)
    assert out == {"pr_url": "https://github.com/x/y/pull/9", "branch": "radar/add-ghost-ai"}
    heads = git("ls-remote", "--heads", str(origin), cwd=root)
    assert "refs/heads/radar/add-ghost-ai" in heads
    assert git("rev-parse", "main", cwd=origin) == git("rev-parse", "origin/main", cwd=root)  # main untouched
    (gh,) = calls
    assert gh[:3] == ["gh", "pr", "create"] and "--draft" in gh
    assert gh[gh.index("--head") + 1] == "radar/add-ghost-ai" and gh[gh.index("--base") + 1] == "main"


def test_publish_refuses_a_workflow_file(repo, monkeypatch):
    root, origin = repo
    calls = _stub_gh(monkeypatch)
    pr_step.cmd_worktree("7", "ghost-ai")
    wt = root / ".claude/worktrees/radar-7"
    (wt / ".github/workflows").mkdir(parents=True)
    (wt / ".github/workflows/steal.yml").write_text("on: pull_request\n")
    body = root / ".claude/worktrees/radar-7-logo/pr-body.md"
    body.parent.mkdir(parents=True)
    body.write_text("x\n")
    with pytest.raises(StepError, match=r"\.github/workflows/steal\.yml"):
        pr_step.cmd_publish("7", "feat(companies): add Ghost AI (Ashby)", str(body), draft=False)
    assert "radar/add-ghost-ai" not in git("ls-remote", "--heads", str(origin), cwd=root)
    assert calls == []


@pytest.mark.parametrize("where", ["home", "git", "outside"])
def test_publish_refuses_a_body_file_outside_the_radar_dirs(repo, monkeypatch, tmp_path, where):
    root, _ = repo
    _stub_gh(monkeypatch)
    pr_step.cmd_worktree("7", "ghost-ai")
    if where == "home":
        body = tmp_path / "id_rsa"
    elif where == "git":
        body = root / ".git" / "config"
    else:
        body = root / "README-not-there.md"
    body.parent.mkdir(parents=True, exist_ok=True)
    body.write_text("secret\n")
    with pytest.raises(StepError, match="body file"):
        pr_step.cmd_publish("7", "feat(companies): add Ghost AI (Ashby)", str(body), draft=False)


def test_cleanup_removes_the_worktree_and_logo_dir(repo):
    root, _ = repo
    pr_step.cmd_worktree("7", "ghost-ai")
    (root / ".claude/worktrees/radar-7-logo/raw").mkdir(parents=True)
    out = pr_step.cmd_cleanup("7")
    assert out["removed"] == ["radar-7", "radar-7-logo"]
    assert not (root / ".claude/worktrees/radar-7").exists()


def test_cli_prints_a_refusal_and_exits_1(capsys):
    assert pr_step.main(["worktree", "--card-id", "1;rm -rf /", "--slug", "x"]) == 1
    assert "refused card id" in capsys.readouterr().err
