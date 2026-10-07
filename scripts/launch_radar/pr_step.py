#!/usr/bin/env python3
"""Launch Radar PR step: the ONLY way the headless session touches git, gh, pip,
the logo scripts or the network outside WebFetch (SKILL.md §2).

Why this exists. The headless session reads attacker-controlled text (Monitor
events, company sites, job boards). Generic allowlist entries such as
``Bash(curl -sSfL:*)``, ``Bash(<venv>/python:*)``, ``Bash(git push -u origin radar/:*)``
or ``Bash(gh pr create:*)`` each hand a prompt injection a free shell, a way to
upload a file (``curl -T``, ``gh pr create --body-file ~/.ssh/id_rsa``) or a push
to ``main`` (``radar/x:main``). So the session gets exactly one entry point,
``Bash(scripts/launch_radar/pr_step.py:*)``, and every subcommand here:

* validates every value it is given (card id, slug, ATS, token, display name,
  title, https URL) against a fixed pattern before it is used;
* runs fixed argv lists (never a shell), git with hooks and fsmonitor disabled;
* only runs scripts the session cannot have edited: either the copies in THIS
  checkout (the session may write only under ``.claude/worktrees/radar-*``), or
  copies inside the temp worktree after checking they are byte-identical to
  ``origin/main``;
* pushes with an explicit ``refs/heads/radar/add-<slug>`` refspec and commits
  only the files the add-company procedure is allowed to touch (no workflows,
  no tests, no symlinks).

This file lives in the main checkout, which the session cannot write. Stdlib
only, Python 3.9+ (it runs under whatever ``python3`` is first on PATH).

  pr_step.py worktree      --card-id N --slug S
  pr_step.py status        --card-id N
  pr_step.py scaffold      --card-id N --slug S --display-name NAME --ats A --board-token T
  pr_step.py check-head    --card-id N
  pr_step.py logo-setup
  pr_step.py logo-fetch    --card-id N --name symbol|wordmark --url https://...
  pr_step.py logo-normalize --card-id N --name symbol|wordmark [--remove-white]
  pr_step.py logo-tile     --card-id N --slug S --variant icon|wordmark|lockup --bg '#RRGGBB' --knockout white|black|none
  pr_step.py publish       --card-id N --title T --body-file PATH [--draft]
  pr_step.py cleanup       --card-id N
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Optional, Sequence

ROOT = Path(__file__).resolve().parents[2]
REPO = "brendanpotter00/Job-Visualizer-Notifier"
WORKTREES = ROOT / ".claude" / "worktrees"

CARD_ID = re.compile(r"^[1-9][0-9]{0,9}$")
SLUG = re.compile(r"^[a-z0-9][a-z0-9.-]{0,40}$")
BRANCH = re.compile(r"^radar/add-[a-z0-9][a-z0-9.-]{0,40}$")
TOKEN = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
DISPLAY_NAME = re.compile(r"^[A-Za-z0-9 .&'-]{1,60}$")
ATS_NAMES = {"greenhouse": "Greenhouse", "ashby": "Ashby", "lever": "Lever"}
TITLE = re.compile(r"^feat\(companies\): add [A-Za-z0-9 .&'-]{1,60} \((Greenhouse|Ashby|Lever)\)$")
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
LOGO_NAMES = ("symbol", "wordmark")
LOGO_EXTS = {"image/svg+xml": "svg", "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp",
             "image/x-icon": "ico", "image/vnd.microsoft.icon": "ico"}
MAX_LOGO_BYTES = 5 * 1024 * 1024
MAX_BODY_BYTES = 20_000

# Scripts that are run from INSIDE the worktree (they find the repo root from their
# own path) and must therefore match origin/main exactly.
PINNED_WT_DIRS = (".claude/skills/add-company/scripts",)
# Scripts run from THIS checkout (they take explicit paths).
LOGO_SCRIPTS = ROOT / ".claude" / "skills" / "fetch-company-logo" / "scripts"

# What an add-company PR may change. Anything else staged -> refuse to commit.
ALLOWED_MODIFIED = frozenset({
    "src/frontend/src/config/companies.ts",
    "src/frontend/src/config/changelog.ts",
    "src/backend/api/data/company_profiles.json",
})
ALLOWED_ADDED = (
    re.compile(r"^src/backend/alembic/versions/[A-Za-z0-9_]+_seed_[a-z0-9_.-]+_company\.py$"),
    re.compile(r"^src/frontend/public/logos/(icons|wordmarks|lockups)/[a-z0-9][a-z0-9.-]{0,40}\.png$"),
)

# Every git call: no hooks, no fsmonitor command, no pager, no prompts.
GIT = ("git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "core.pager=cat")

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class StepError(Exception):
    """A refused value or a failed step. The message is safe to print."""


def _run(argv: Sequence[str], cwd: Optional[Path] = None, check: bool = True) -> "subprocess.CompletedProcess[str]":
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_TERMINAL_PROMPT"] = "0"
    proc = subprocess.run(list(argv), cwd=str(cwd) if cwd else None, env=env, text=True,
                          capture_output=True, timeout=600)
    if check and proc.returncode != 0:
        raise StepError(f"{argv[0]} {' '.join(argv[1:3])}... failed ({proc.returncode}): "
                        f"{(proc.stderr or proc.stdout).strip()[-800:]}")
    return proc


run: Runner = _run


# ---- validation ---------------------------------------------------------------------
def _match(pattern: "re.Pattern[str]", value: str, what: str) -> str:
    if not isinstance(value, str) or not pattern.match(value):
        raise StepError(f"refused {what}: {value!r}")
    return value


def card_dir(card_id: str) -> Path:
    return WORKTREES / f"radar-{_match(CARD_ID, card_id, 'card id')}"


def logo_dir(card_id: str) -> Path:
    return WORKTREES / f"radar-{_match(CARD_ID, card_id, 'card id')}-logo"


def git_common_dir() -> Path:
    out = run([*GIT, "-C", str(ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"]).stdout.strip()
    return Path(out).resolve()


def existing_worktree(card_id: str) -> Path:
    """The temp worktree, after checking its ``.git`` pointer was not rewritten.

    The session may write files under ``.claude/worktrees/radar-*``, which includes
    the worktree's ``.git`` file; a rewritten pointer could aim git at a config the
    session wrote (fsmonitor, hooks). It must point at our own
    ``<common>/worktrees/radar-<id>``.
    """
    wt = card_dir(card_id)
    dot_git = wt / ".git"
    if not dot_git.is_file() or dot_git.is_symlink():
        raise StepError(f"no radar worktree for card {card_id}")
    expected = git_common_dir() / "worktrees" / wt.name
    text = dot_git.read_text().strip()
    if not text.startswith("gitdir: ") or Path(text[len("gitdir: "):]).resolve() != expected:
        raise StepError(f"{wt.name}/.git does not point at {expected}; refusing to run git there")
    return wt


def assert_pinned(wt: Path) -> None:
    """The worktree's copies of the scripts we run must equal origin/main's."""
    for d in PINNED_WT_DIRS:
        changed = run([*GIT, "-C", str(wt), "status", "--porcelain", "--untracked-files=all", "--", d]).stdout
        diff = run([*GIT, "-C", str(wt), "diff", "--name-only", "origin/main", "--", d]).stdout
        if changed.strip() or diff.strip():
            raise StepError(f"{d} in the worktree differs from origin/main; refusing to run it")


# ---- subcommands ----------------------------------------------------------------------
def cmd_worktree(card_id: str, slug: str) -> dict:
    wt = card_dir(card_id)
    _match(SLUG, slug, "slug")
    if wt.exists():
        raise StepError(f"{wt.name} already exists; run cleanup first")
    run([*GIT, "-C", str(ROOT), "fetch", "origin", "main"])
    branch = f"radar/add-{slug}"
    taken = run([*GIT, "-C", str(ROOT), "ls-remote", "--heads", "origin", f"refs/heads/{branch}"]).stdout.strip() \
        or run([*GIT, "-C", str(ROOT), "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
               check=False).returncode == 0
    if taken:
        branch = f"{branch}-2"
    _match(BRANCH, branch, "branch")
    run([*GIT, "-C", str(ROOT), "worktree", "add", "-b", branch, str(wt), "origin/main"])
    return {"worktree": str(wt.relative_to(ROOT)), "branch": branch}


def cmd_status(card_id: str) -> dict:
    wt = existing_worktree(card_id)
    return {"status": run([*GIT, "-C", str(wt), "status", "--short", "--untracked-files=all"]).stdout}


def cmd_scaffold(card_id: str, slug: str, display_name: str, ats: str, token: str) -> dict:
    wt = existing_worktree(card_id)
    _match(SLUG, slug, "slug")
    _match(DISPLAY_NAME, display_name, "display name")
    _match(TOKEN, token, "board token")
    if ats not in ATS_NAMES:
        raise StepError(f"refused ats: {ats!r} (greenhouse, ashby or lever only)")
    assert_pinned(wt)
    script = wt / ".claude/skills/add-company/scripts/scaffold_migration.py"
    out = run([sys.executable, "-I", str(script), "--id", slug, "--display-name", display_name,
               "--ats", ats, "--board-token", token], cwd=wt).stdout
    return {"output": out.strip()}


def cmd_check_head(card_id: str) -> dict:
    wt = existing_worktree(card_id)
    assert_pinned(wt)
    proc = run([sys.executable, "-I", str(wt / ".claude/skills/add-company/scripts/current_head.py")],
               cwd=wt, check=False)
    return {"exit": proc.returncode, "output": (proc.stdout + proc.stderr).strip()}


def logo_venv() -> Path:
    state = Path(os.environ.get("LAUNCH_RADAR_STATE_DIR")
                 or "~/Library/Application Support/jvn-launch-radar").expanduser()
    return state / "logo-venv"


def cmd_logo_setup() -> dict:
    venv = logo_venv()
    py = venv / "bin" / "python"
    if not py.exists():
        run([sys.executable, "-m", "venv", str(venv)])
    run([str(py), "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
         "-r", str(LOGO_SCRIPTS / "requirements.txt")])
    return {"venv": str(venv)}


def _public_host(host: str) -> None:
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise StepError(f"cannot resolve {host}: {e}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise StepError(f"refused {host}: resolves to a non-public address")


def check_logo_url(url: str) -> str:
    p = urllib.parse.urlsplit(url)
    if p.scheme != "https" or not p.hostname or p.username or p.password or any(c.isspace() for c in url):
        raise StepError(f"refused url {url!r}: https URLs without credentials only")
    if len(url) > 2000:
        raise StepError("refused url: too long")
    _public_host(p.hostname)
    return url


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        check_logo_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def cmd_logo_fetch(card_id: str, name: str, url: str) -> dict:
    existing_worktree(card_id)
    if name not in LOGO_NAMES:
        raise StepError(f"refused name {name!r}")
    check_logo_url(url)
    opener = urllib.request.build_opener(_HttpsOnlyRedirects())
    req = urllib.request.Request(url, headers={"User-Agent": "jvn-launch-radar-logo/1"})
    try:
        with opener.open(req, timeout=30) as resp:
            ctype = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
            data = resp.read(MAX_LOGO_BYTES + 1)
    except urllib.error.URLError as e:
        raise StepError(f"download failed: {e}") from e
    if len(data) > MAX_LOGO_BYTES:
        raise StepError("refused: larger than 5 MB")
    ext = LOGO_EXTS.get(ctype)
    if ext is None:
        raise StepError(f"refused content-type {ctype!r}; expected an image")
    raw = logo_dir(card_id) / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    for old in raw.glob(f"{name}.*"):
        old.unlink()
    out = raw / f"{name}.{ext}"
    out.write_bytes(data)
    return {"saved": str(out.relative_to(ROOT)), "bytes": len(data)}


def _logo_python() -> Path:
    py = logo_venv() / "bin" / "python"
    if not py.exists():
        raise StepError("logo venv missing; run logo-setup first")
    return py


def cmd_logo_normalize(card_id: str, name: str, remove_white: bool) -> dict:
    existing_worktree(card_id)
    if name not in LOGO_NAMES:
        raise StepError(f"refused name {name!r}")
    raws = sorted((logo_dir(card_id) / "raw").glob(f"{name}.*"))
    if not raws:
        raise StepError(f"no raw {name}; run logo-fetch first")
    master = logo_dir(card_id) / "masters" / f"{name}.png"
    master.parent.mkdir(parents=True, exist_ok=True)
    argv = [str(_logo_python()), "-I", str(LOGO_SCRIPTS / "normalize.py"), str(raws[0]), str(master)]
    if remove_white:
        argv.append("--remove-white")
    run(argv)
    return {"master": str(master.relative_to(ROOT))}


def cmd_logo_tile(card_id: str, slug: str, variant: str, bg: str, knockout: str) -> dict:
    wt = existing_worktree(card_id)
    _match(SLUG, slug, "slug")
    _match(HEX, bg, "background colour")
    if knockout not in ("white", "black", "none"):
        raise StepError(f"refused knockout {knockout!r}")
    masters = logo_dir(card_id) / "masters"
    py = str(_logo_python())
    logos = wt / "src/frontend/public/logos"
    if variant == "icon":
        out = logos / "icons" / f"{slug}.png"
        argv = [py, "-I", str(LOGO_SCRIPTS / "tile.py"), str(masters / "symbol.png"), str(out), "--bg", bg,
                "--knockout", knockout, "--shape", "square", "--size", "128"]
    elif variant == "wordmark":
        out = logos / "wordmarks" / f"{slug}.png"
        argv = [py, "-I", str(LOGO_SCRIPTS / "tile.py"), str(masters / "wordmark.png"), str(out), "--bg", bg,
                "--knockout", knockout, "--shape", "banner", "--size", "128"]
    elif variant == "lockup":
        out = logos / "lockups" / f"{slug}.png"
        argv = [py, "-I", str(LOGO_SCRIPTS / "compose_lockup.py"), str(masters / "symbol.png"),
                str(masters / "wordmark.png"), str(out), "--bg", bg, "--knockout", knockout, "--height", "128"]
    else:
        raise StepError(f"refused variant {variant!r}")
    out.parent.mkdir(parents=True, exist_ok=True)
    run(argv)
    return {"wrote": str(out.relative_to(ROOT))}


def staged_problems(raw_diff: str) -> list[str]:
    """Paths in ``git diff --cached --raw -z`` output an add-company PR may not touch."""
    problems: list[str] = []
    fields = raw_diff.split("\0")
    i = 0
    while i < len(fields) - 1:
        meta = fields[i]
        if not meta.startswith(":"):
            i += 1
            continue
        parts = meta[1:].split()
        new_mode, status = parts[1], parts[4]
        path = fields[i + 1]
        i += 2
        if status[0] in "RC":  # renames/copies carry a second path
            problems.append(f"{status[0]} {path} -> {fields[i]}")
            i += 1
            continue
        if new_mode not in ("100644", "000000"):
            problems.append(f"mode {new_mode} on {path}")
        elif status == "M" and path in ALLOWED_MODIFIED:
            continue
        elif status == "A" and any(p.match(path) for p in ALLOWED_ADDED):
            continue
        else:
            problems.append(f"{status} {path}")
    return problems


def _body_file(path: str) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    p = p.resolve()
    try:
        rel = p.relative_to(WORKTREES.resolve())
    except ValueError:
        raise StepError("refused body file: must be under .claude/worktrees/") from None
    if not rel.parts or not re.match(r"^radar-[0-9]+(-logo)?$", rel.parts[0]) or ".git" in rel.parts:
        raise StepError("refused body file: must be in a radar worktree")
    if not p.is_file() or p.stat().st_size > MAX_BODY_BYTES:
        raise StepError("refused body file: missing or larger than 20 kB")
    return p


def cmd_publish(card_id: str, title: str, body_file: str, draft: bool) -> dict:
    wt = existing_worktree(card_id)
    _match(TITLE, title, "PR title")
    body = _body_file(body_file)
    branch = run([*GIT, "-C", str(wt), "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    _match(BRANCH, branch, "branch")
    run([*GIT, "-C", str(wt), "add", "-A"])
    problems = staged_problems(run([*GIT, "-C", str(wt), "diff", "--cached", "--raw", "-z", "--no-renames"]).stdout)
    if problems:
        raise StepError("refused to commit paths outside the add-company set: " + "; ".join(problems[:20]))
    run([*GIT, "-C", str(wt), "commit", "--no-verify", "-m", title])
    run([*GIT, "-C", str(wt), "push", "--no-verify", "-u", "origin", f"HEAD:refs/heads/{branch}"])
    argv = ["gh", "pr", "create", "--repo", REPO, "--base", "main", "--head", branch, "--title", title,
            "--body-file", str(body), "--label", "launch-radar"]
    if draft:
        argv.append("--draft")
    url = run(argv, cwd=wt).stdout.strip().splitlines()[-1]
    return {"pr_url": url, "branch": branch}


def cmd_cleanup(card_id: str) -> dict:
    wt = card_dir(card_id)
    removed = []
    if (wt / ".git").exists():
        existing_worktree(card_id)
        run([*GIT, "-C", str(ROOT), "worktree", "remove", "--force", str(wt)])
        removed.append(wt.name)
    ld = logo_dir(card_id)
    if ld.exists():
        import shutil

        shutil.rmtree(ld)
        removed.append(ld.name)
    run([*GIT, "-C", str(ROOT), "worktree", "prune"], check=False)
    return {"removed": removed}


# ---- CLI ---------------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pr_step.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def card(sp: argparse.ArgumentParser) -> argparse.ArgumentParser:
        sp.add_argument("--card-id", required=True)
        return sp

    s = card(sub.add_parser("worktree"))
    s.add_argument("--slug", required=True)
    card(sub.add_parser("status"))
    s = card(sub.add_parser("scaffold"))
    s.add_argument("--slug", required=True)
    s.add_argument("--display-name", required=True)
    s.add_argument("--ats", required=True)
    s.add_argument("--board-token", required=True)
    card(sub.add_parser("check-head"))
    sub.add_parser("logo-setup")
    s = card(sub.add_parser("logo-fetch"))
    s.add_argument("--name", required=True)
    s.add_argument("--url", required=True)
    s = card(sub.add_parser("logo-normalize"))
    s.add_argument("--name", required=True)
    s.add_argument("--remove-white", action="store_true")
    s = card(sub.add_parser("logo-tile"))
    s.add_argument("--slug", required=True)
    s.add_argument("--variant", required=True)
    s.add_argument("--bg", required=True)
    s.add_argument("--knockout", required=True)
    s = card(sub.add_parser("publish"))
    s.add_argument("--title", required=True)
    s.add_argument("--body-file", required=True)
    s.add_argument("--draft", action="store_true")
    card(sub.add_parser("cleanup"))
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    a = build_parser().parse_args(argv)
    try:
        if a.cmd == "worktree":
            out = cmd_worktree(a.card_id, a.slug)
        elif a.cmd == "status":
            out = cmd_status(a.card_id)
        elif a.cmd == "scaffold":
            out = cmd_scaffold(a.card_id, a.slug, a.display_name, a.ats, a.board_token)
        elif a.cmd == "check-head":
            out = cmd_check_head(a.card_id)
            print(json.dumps(out, indent=2))
            return 0 if out["exit"] == 0 else 1
        elif a.cmd == "logo-setup":
            out = cmd_logo_setup()
        elif a.cmd == "logo-fetch":
            out = cmd_logo_fetch(a.card_id, a.name, a.url)
        elif a.cmd == "logo-normalize":
            out = cmd_logo_normalize(a.card_id, a.name, a.remove_white)
        elif a.cmd == "logo-tile":
            out = cmd_logo_tile(a.card_id, a.slug, a.variant, a.bg, a.knockout)
        elif a.cmd == "publish":
            out = cmd_publish(a.card_id, a.title, a.body_file, a.draft)
        elif a.cmd == "cleanup":
            out = cmd_cleanup(a.card_id)
        else:  # pragma: no cover - argparse rejects unknown commands
            raise StepError(f"unknown command {a.cmd}")
    except StepError as e:
        print(f"pr_step {a.cmd}: {e}", file=sys.stderr)
        return 1
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
