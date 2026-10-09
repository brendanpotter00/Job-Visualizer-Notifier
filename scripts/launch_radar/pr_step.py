#!/usr/bin/env python3
"""Launch Radar PR step: the ONLY way the headless session touches git, gh, the logo
scripts or the network outside the scout's web tools (saved-pr/PLAN.md §4.3, §4.6).

Why this exists. The headless session reads attacker-controlled text (card fields
from web research, the scout's reply, logo bytes, job-board APIs, and GitHub PRs
from anyone: the repo is public). Generic allowlist entries such as
``Bash(git push:*)`` or ``Bash(gh pr create:*)`` each hand a prompt injection a free
shell, an upload channel or a push to ``main``. So the session gets one entry point,
``Bash(scripts/launch_radar/pr_step.py:*)``, and:

* it passes only ``--card-id`` (plus, for logos, argparse choices and a ``#RRGGBB``
  colour). Every other value comes from files this program or ``radar.sh`` wrote
  (``.launch-radar-pr/claims``, ``work``) or from the scout reply, which is parsed
  and refused whole on any violation (``parse_scout``). The slug, display name and
  enum member are derived here (``verify-board``), never supplied;
* every value is checked against a fixed pattern before it is used; untrusted text
  only reaches templated, quoted TS/JSON strings, never a command line;
* fixed argv lists, never a shell; every git call runs with hooks, fsmonitor and the
  pager off, ``GIT_*`` stripped and prompts disabled;
* scripts run either from THIS checkout (the session cannot write it) or from the
  temp worktree after ``assert_pinned`` proves them equal to ``origin/main``;
* the branch is ``radar/card-<id>`` and every push is
  ``HEAD:refs/heads/radar/card-<id>`` with a lease on that same ref;
* only the add-company files can be committed (``staged_problems``);
* a PR on that branch counts only when it passes the trust check
  (``trusted_prs``: same repo, the owner's head, authored by the gh login, with the
  ``Launch-Radar-Card: <id>`` line). Fork PRs and other authors are ignored.

Commands (each prints one JSON line; errors are ``{"error", "report_reason"}``, exit
1; exit 3 means "stop for this card, report what was printed"):

  pr_step.py worktree       --card-id N   stale worktree out, trust check, lease, new worktree
  pr_step.py verify-board   --card-id N   live board, tracked check, slug/name/enum -> board.json
  pr_step.py compose        --card-id N   seed migration + companies.ts, changelog.ts, profiles
  pr_step.py logo-fetch     --card-id N --name symbol|wordmark
  pr_step.py logo-normalize --card-id N --name symbol|wordmark [--remove-white]
  pr_step.py logo-tile      --card-id N --variant icon|wordmark|lockup --bg '#RRGGBB' --knockout white|black|none
  pr_step.py check-head     --card-id N
  pr_step.py publish        --card-id N [--draft] [--dry-run]
  pr_step.py cleanup        --card-id N
  pr_step.py refresh        --card-id N   (radar.sh pr-refresh only) rebuild a PR behind main

Every output carries ``time_left_s`` (to the wrapper's 90-minute kill, only when
``LAUNCH_RADAR_RUN_ID`` matches the wrapper's ``session_started_at``) and
``skip_optional`` (true under 15 minutes: skip logos, publish a draft).

This file lives in the main checkout, which the session cannot write. Stdlib only;
it must run on Python 3.8+ (``/usr/bin/env python3`` on the server).
"""

from __future__ import annotations

import argparse
import datetime as dt
import http.client
import ipaddress
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import traceback
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

ROOT = Path(__file__).resolve().parents[2]
REPO = "brendanpotter00/Job-Visualizer-Notifier"
REPO_OWNER = "brendanpotter00"
PR_DIR_NAME = ".launch-radar-pr"
DEFAULT_STATE_DIR = "~/Library/Application Support/jvn-launch-radar"
# Logo scripts run from THIS checkout (they take explicit paths).
LOGO_SCRIPTS = ROOT / ".claude" / "skills" / "fetch-company-logo" / "scripts"

# Paths inside a worktree.
ADD_COMPANY_SCRIPTS = ".claude/skills/add-company/scripts"
COMPANIES_TS = "src/frontend/src/config/companies.ts"
CHANGELOG_TS = "src/frontend/src/config/changelog.ts"
PROFILES_JSON = "src/backend/api/data/company_profiles.json"
VERSIONS_DIR = "src/backend/alembic/versions"
LOGOS_DIR = "src/frontend/public/logos"
LOGO_VARIANT_DIRS = ("icons", "wordmarks", "lockups")
# Scripts run from INSIDE the worktree (they find the repo root from their own path)
# must match origin/main exactly.
PINNED_WT_DIRS = (ADD_COMPANY_SCRIPTS,)

# ---- patterns (always fullmatch) ---------------------------------------------------------
CARD_ID = re.compile(r"[1-9][0-9]{0,9}")
SLUG = re.compile(r"[a-z][a-z0-9-]{0,40}")
BRANCH = re.compile(r"radar/card-[1-9][0-9]{0,9}")
TOKEN = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,99}")
# No quote of any kind: the pinned scaffold puts the name in a single-quoted Python
# string, so an apostrophe would break the migration.
DISPLAY_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 .&-]{0,59}")
ENUM_MEMBER = re.compile(r"[A-Z][A-Za-z0-9]{0,63}")
DOMAIN = re.compile(r"(?=.{4,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+")
TITLE = re.compile(r"feat\(companies\): add [A-Za-z0-9][A-Za-z0-9 .&-]{0,59} \((Greenhouse|Ashby|Lever|Gem)\)")
HEX = re.compile(r"#[0-9A-Fa-f]{6}")
SHA = re.compile(r"[0-9a-f]{40}")
GH_LOGIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}")
REVISION = re.compile(r"[0-9A-Za-z_]{4,64}")
RUN_ID = re.compile(r"[0-9]{1,12}-[0-9]{1,10}")
# SEAM: the DB CHECK ck_launch_radar_pr_requests_pr_url, models.py, pr_queue.py, format.ts.
PR_URL_RE = re.compile(r"https://github\.com/brendanpotter00/Job-Visualizer-Notifier/pull/([0-9]+)")

ATS_NAMES = {"greenhouse": "Greenhouse", "ashby": "Ashby", "lever": "Lever", "gem": "Gem"}
UNSUPPORTED_ATS = ("workday", "eightfold")
# Fixed public API hosts: a token is the only variable part, and it is path-quoted.
BOARD_APIS = {
    "greenhouse": ("boards-api.greenhouse.io", "/v1/boards/{t}/jobs"),
    "ashby": ("api.ashbyhq.com", "/posting-api/job-board/{t}"),
    "lever": ("api.lever.co", "/v0/postings/{t}?mode=json"),
    "gem": ("api.gem.com", "/job_board/v0/{t}/job_posts/"),
}
PUBLIC_BOARDS = {
    "greenhouse": "https://job-boards.greenhouse.io/{t}",
    "ashby": "https://jobs.ashbyhq.com/{t}",
    "lever": "https://jobs.lever.co/{t}",
    "gem": "https://jobs.gem.com/{t}",
}
_T = r"([A-Za-z0-9_.-]+)"
BOARD_URL_PATTERNS = {
    "greenhouse": (re.compile(r"https?://(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?" + _T),
                   re.compile(r"https?://boards-api\.greenhouse\.io/v1/boards/" + _T)),
    "ashby": (re.compile(r"https?://(?:jobs|careers)\.ashbyhq\.com/" + _T),
              re.compile(r"https?://api\.ashbyhq\.com/posting-api/job-board/" + _T)),
    "lever": (re.compile(r"https?://jobs(?:\.eu)?\.lever\.co/" + _T),
              re.compile(r"https?://api(?:\.eu)?\.lever\.co/v0/postings/" + _T)),
    "gem": (re.compile(r"https?://jobs\.gem\.com/" + _T),
            re.compile(r"https?://api\.gem\.com/job_board/v0/" + _T)),
}
SEED_PAIR = re.compile(r"""['"]ats['"]\s*:\s*['"]([a-z]+)['"]\s*,\s*['"]board_token['"]\s*:\s*['"]([^'"]+)['"]""")
MAX_CANDIDATES = 8
MAX_BOARD_BYTES = 30 * 1024 * 1024
BOARD_TIMEOUT_S = 20

# ---- the scout reply (launch-radar-scout/v1) ------------------------------------------------
SCOUT_SCHEMA = "launch-radar-scout/v1"
SCOUT_KEYS = frozenset({"schema", "card_id", "boards", "logo", "summary", "milestone"})
MAX_SCOUT_BOARDS = 5
MAX_URL_CHARS = 500
MAX_LOGO_QUERY_CHARS = 200
TEXT_MIN, TEXT_MAX = 20, 240
TEXT_FORBIDDEN = frozenset("`$\\<>{}")
SECRET_SHAPES = (
    re.compile(r"(?<![A-Za-z0-9])sk-"),
    re.compile(r"gh[pos]_"),
    re.compile(r"github_pat_"),
    re.compile(r"xox"),
    re.compile(r"AKIA"),
    re.compile(r"postgres(?:ql)?://", re.I),
    re.compile(r"-----BEGIN"),
)
SECRET_RUN = re.compile(r"[A-Za-z0-9+/=_-]{32,}")

# ---- logos ------------------------------------------------------------------------------------
LOGO_NAMES = ("symbol", "wordmark")
LOGO_EXTS = {"image/svg+xml": "svg", "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp",
             "image/x-icon": "ico", "image/vnd.microsoft.icon": "ico"}
MAX_LOGO_BYTES = 5 * 1024 * 1024
MAX_LOGO_REDIRECTS = 5
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
# normalize.py turns Pillow's decompression-bomb guard off, so a tiny, highly compressible
# file that claims a huge canvas would make it allocate GBs. Raster logos are measured from
# their headers here, before any decoder sees them, and refused above this pixel count.
MAX_LOGO_PIXELS = 40_000_000
USER_AGENT = "jvn-launch-radar-pr/1"

# ---- time (§4.4) -----------------------------------------------------------------------------
KILL_AFTER_S = 5400  # wrapper.sh: the 90-minute hard limit
SKIP_OPTIONAL_UNDER_S = 900
SESSION_FILE = "session_started_at"

# What an add-company PR may change. Anything else staged -> refuse to commit.
ALLOWED_MODIFIED = frozenset({COMPANIES_TS, CHANGELOG_TS, PROFILES_JSON})
REQUIRED_MODIFIED = (COMPANIES_TS, CHANGELOG_TS)
MAX_JSON_BYTES = 256 * 1024

# Every git call: no hooks, no fsmonitor command, no pager, no prompts.
GIT = ("git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "core.pager=cat")

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class StepError(Exception):
    """A refused value or a failed step. The message is safe to print; ``reason`` is
    the PrReason the skill reports (``env_error`` refunds the attempt)."""

    def __init__(self, message: str, reason: str = "step_refused") -> None:
        super().__init__(message)
        self.reason = reason


class Stop(Exception):
    """Not an error: this card stops here (already tracked, no board, an existing PR).
    The payload is printed and the exit code is 3."""

    def __init__(self, payload: Dict[str, Any]) -> None:
        super().__init__(json.dumps(payload))
        self.payload = payload


def _describe(argv: Sequence[str]) -> str:
    """``git push``, ``gh pr create``: what failed, without paths or values."""
    args = list(argv)
    if args[:1] == ["git"]:
        rest, it = [], iter(args[1:])
        for a in it:
            if a in ("-c", "-C"):
                next(it, None)
                continue
            rest.append(a)
        return "git " + " ".join(rest[:2])
    return " ".join([Path(args[0]).name, *args[1:3]])


def _default_reason(argv: Sequence[str]) -> str:
    return {"git": "git_error", "gh": "gh_error"}.get(argv[0], "step_refused")


def _run(argv: Sequence[str], cwd: Optional[Path] = None, check: bool = True,
         reason: Optional[str] = None) -> "subprocess.CompletedProcess[str]":
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_TERMINAL_PROMPT="0", GH_PROMPT_DISABLED="1", GH_NO_UPDATE_NOTIFIER="1")
    try:
        proc = subprocess.run(list(argv), cwd=str(cwd) if cwd else None, env=env, text=True,
                              capture_output=True, timeout=600, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise StepError(f"{_describe(argv)} timed out", "timeout") from None
    except OSError as e:
        raise StepError(f"cannot run {_describe(argv)}: {e.strerror}", reason or "env_error") from None
    if check and proc.returncode != 0:
        raise StepError(f"{_describe(argv)} failed ({proc.returncode}): "
                        f"{(proc.stderr or proc.stdout).strip()[-800:]}", reason or _default_reason(argv))
    return proc


run: Runner = _run
clock: Callable[[], float] = time.time


def git(repo: Path, *args: str, check: bool = True,
        reason: Optional[str] = None) -> "subprocess.CompletedProcess[str]":
    return run([*GIT, "-C", str(repo), *args], check=check, reason=reason)


# ---- validation, paths, files -----------------------------------------------------------
def _match(pattern: "re.Pattern[str]", value: Any, what: str, reason: str = "step_refused") -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise StepError(f"refused {what}: {value!r}"[:300], reason)
    return value


def token_ok(token: Any) -> bool:
    return isinstance(token, str) and bool(TOKEN.fullmatch(token)) and ".." not in token


def worktrees_dir() -> Path:
    return ROOT / ".claude" / "worktrees"


def pr_dir() -> Path:
    return ROOT / PR_DIR_NAME


def card_dir(card_id: str) -> Path:
    return worktrees_dir() / f"radar-{_match(CARD_ID, card_id, 'card id')}"


def work_dir(card_id: str) -> Path:
    return pr_dir() / "work" / _match(CARD_ID, card_id, "card id")


def branch_for(card_id: str) -> str:
    return _match(BRANCH, f"radar/card-{card_id}", "branch")


def claim_path(card_id: str) -> Path:
    return pr_dir() / "claims" / f"{card_id}.json"


def scout_path(card_id: str) -> Path:
    return pr_dir() / "scout" / f"{card_id}.json"


def board_path(card_id: str) -> Path:
    return work_dir(card_id) / "board.json"


def published_path(card_id: str) -> Path:
    return pr_dir() / "published" / f"{card_id}.json"


def state_dir() -> Path:
    return Path(os.environ.get("LAUNCH_RADAR_STATE_DIR") or DEFAULT_STATE_DIR).expanduser()


def _no_symlinks_below_root(path: Path) -> None:
    p = path
    while p != ROOT and ROOT in p.parents:
        if p.is_symlink():
            raise StepError(f"refused: {p.relative_to(ROOT)} is a symlink")
        p = p.parent


def read_json(path: Path, what: str) -> Any:
    if path.is_symlink() or not path.is_file():
        raise StepError(f"no {what} ({path.relative_to(ROOT) if ROOT in path.parents else path.name})")
    if path.stat().st_size > MAX_JSON_BYTES:
        raise StepError(f"refused {what}: larger than {MAX_JSON_BYTES} bytes")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise StepError(f"unreadable {what}: {type(e).__name__}") from None


def write_text(path: Path, text: str) -> None:
    _no_symlinks_below_root(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, str(path))
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_json(path: Path, data: Any) -> None:
    write_text(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def remove_path(path: Path) -> bool:
    """Remove a file, a symlink or a tree (never follows a symlink)."""
    if path.is_symlink() or path.is_file():
        path.unlink()
        return True
    if path.is_dir():
        shutil.rmtree(str(path))
        return True
    return False


_TS = re.compile(r"(\d{4}-\d\d-\d\d)[T ](\d\d:\d\d:\d\d)(\.\d+)?(Z|[+-]\d\d:\d\d)?")


def parse_ts(value: Any) -> Optional[dt.datetime]:
    """An ISO-8601 timestamp as an aware datetime (``Z`` and any fraction width
    accepted on Python 3.8), or None."""
    if not isinstance(value, str):
        return None
    m = _TS.fullmatch(value.strip())
    if not m:
        return None
    frac = (m.group(3) or ".0")[1:7].ljust(6, "0")
    tz = m.group(4) or "+00:00"
    try:
        return dt.datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}.{frac}{'+00:00' if tz == 'Z' else tz}")
    except ValueError:
        return None


# ---- the clock (§4.4) ----------------------------------------------------------------------
def time_left_s() -> Optional[int]:
    """Seconds to the 90-minute kill, or None when the clock does not apply (no
    ``LAUNCH_RADAR_RUN_ID``, no file, or a file from another run)."""
    run_id = os.environ.get("LAUNCH_RADAR_RUN_ID") or ""
    if not RUN_ID.fullmatch(run_id):
        return None
    try:
        parts = (state_dir() / SESSION_FILE).read_text().split()
    except OSError:
        return None
    if len(parts) != 2 or parts[1] != run_id or not parts[0].isdigit():
        return None
    return max(0, int(KILL_AFTER_S - max(0.0, clock() - int(parts[0]))))


def time_fields() -> Dict[str, Any]:
    left = time_left_s()
    return {"time_left_s": left, "skip_optional": left is not None and left < SKIP_OPTIONAL_UNDER_S}


# ---- git worktree integrity ---------------------------------------------------------------
def git_common_dir() -> Path:
    out = git(ROOT, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    return Path(out).resolve()


def existing_worktree(card_id: str) -> Path:
    """The temp worktree, after checking its ``.git`` pointer was not rewritten: it must
    point at our own ``<common>/worktrees/radar-<id>``, or git could be aimed at a
    config someone else wrote (fsmonitor, hooks)."""
    wt = card_dir(card_id)
    dot_git = wt / ".git"
    if wt.is_symlink() or not dot_git.is_file() or dot_git.is_symlink():
        raise StepError(f"no radar worktree for card {card_id}")
    expected = git_common_dir() / "worktrees" / wt.name
    text = dot_git.read_text().strip()
    if not text.startswith("gitdir: ") or Path(text[len("gitdir: "):]).resolve() != expected:
        raise StepError(f"{wt.name}/.git does not point at {expected}; refusing to run git there")
    return wt


def remove_worktree(card_id: str) -> bool:
    """Remove a (stale) radar worktree. The pointer is checked first: a rewritten
    ``.git`` is a tampering signal, so it is refused, not deleted."""
    wt = card_dir(card_id)
    if wt.is_symlink():
        raise StepError(f"{wt.name} is a symlink; refusing to touch it")
    removed = False
    if wt.exists():
        if (wt / ".git").exists() or (wt / ".git").is_symlink():
            existing_worktree(card_id)
        shutil.rmtree(str(wt))
        removed = True
    git(ROOT, "worktree", "prune", check=False)
    return removed


def assert_pinned(wt: Path) -> None:
    """The worktree's copies of the scripts we run must equal origin/main's."""
    for d in PINNED_WT_DIRS:
        changed = git(wt, "status", "--porcelain", "--untracked-files=all", "--", d).stdout
        diff = git(wt, "diff", "--name-only", "origin/main", "--", d).stdout
        if changed.strip() or diff.strip():
            raise StepError(f"{d} in the worktree differs from origin/main; refusing to run it")


def remote_branch_sha(branch: str) -> str:
    """The remote head of ``branch`` or ``""`` when it does not exist (a network or
    auth failure here is an ``env_error``: nothing was pushed yet)."""
    ref = f"refs/heads/{_match(BRANCH, branch, 'branch')}"
    out = git(ROOT, "ls-remote", "origin", ref, reason="env_error").stdout
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == ref:
            return _match(SHA, parts[0], "remote sha", "env_error")
    return ""


# ---- the trust check (§4.3) -------------------------------------------------------------------
def gh_login(card_id: str) -> str:
    cache = work_dir(card_id) / "gh_login"
    if cache.is_file() and not cache.is_symlink():
        login = cache.read_text().strip()
        if GH_LOGIN.fullmatch(login):
            return login
    login = run(["gh", "api", "user", "--jq", ".login"], reason="env_error").stdout.strip()
    _match(GH_LOGIN, login, "gh login", "env_error")
    write_text(cache, login + "\n")
    return login


def _login_of(value: Any) -> Optional[str]:
    return value.get("login") if isinstance(value, dict) and isinstance(value.get("login"), str) else None


def is_trusted(pr: Any, card_id: str, login: str) -> bool:
    """A PR on ``radar/card-<id>`` counts only when it is this repo's own branch
    (not a fork), the owner's, authored by the gh login, with the card marker line."""
    if not isinstance(pr, dict):
        return False
    url, number, body = pr.get("url"), pr.get("number"), pr.get("body")
    m = PR_URL_RE.fullmatch(url) if isinstance(url, str) else None
    return bool(
        m and isinstance(number, int) and not isinstance(number, bool) and int(m.group(1)) == number
        and pr.get("isCrossRepository") is False
        and _login_of(pr.get("headRepositoryOwner")) == REPO_OWNER
        and _login_of(pr.get("author")) == login
        and pr.get("headRefName") == f"radar/card-{card_id}"
        and pr.get("state") in ("OPEN", "CLOSED", "MERGED")
        and isinstance(body, str)
        and f"Launch-Radar-Card: {card_id}" in (ln.strip() for ln in body.splitlines())
    )


def trusted_prs(card_id: str) -> List[Dict[str, Any]]:
    login = gh_login(card_id)
    out = run(["gh", "pr", "list", "--repo", REPO, "--head", branch_for(card_id), "--state", "all",
               "--limit", "50", "--json",
               "number,url,state,body,closedAt,mergedAt,isCrossRepository,headRepositoryOwner,"
               "headRefName,headRefOid,author"], reason="env_error").stdout
    try:
        prs = json.loads(out)
    except ValueError:
        raise StepError("gh pr list printed no JSON", "env_error") from None
    if not isinstance(prs, list):
        raise StepError("gh pr list printed no list", "env_error")
    return [pr for pr in prs if is_trusted(pr, card_id, login)]


def pr_verdict(prs: List[Dict[str, Any]], requested_at: dt.datetime) -> Optional[Tuple[str, Dict[str, Any]]]:
    """``existing_pr`` (an open trusted PR: adopt it), ``already_tracked`` (merged) or
    ``pr_closed`` (closed after the request was queued: the owner said no); None when
    a new PR may be opened."""
    by_number = sorted(prs, key=lambda p: p["number"], reverse=True)
    for pr in by_number:
        if pr["state"] == "OPEN":
            return "existing_pr", pr
    for pr in by_number:
        if pr["state"] == "MERGED":
            return "already_tracked", pr
    for pr in by_number:
        if pr["state"] == "CLOSED":
            closed = parse_ts(pr.get("closedAt"))
            if closed is None or closed > requested_at:  # unknown counts as "after": never spam
                return "pr_closed", pr
    return None


# ---- the claim, the scout reply, board.json -------------------------------------------------
def load_claim(card_id: str) -> Dict[str, Any]:
    claim = read_json(claim_path(card_id), f"claim for card {card_id} (run radar.sh pr-next)")
    if not isinstance(claim, dict):
        raise StepError("refused claim: not an object")
    cid = claim.get("card_id")
    if isinstance(cid, bool) or cid != int(card_id):
        raise StepError("refused claim: it is for another card")
    for key in ("domain", "company", "requested_at"):
        if not isinstance(claim.get(key), str):
            raise StepError(f"refused claim: no {key}")
    if not isinstance(claim.get("ats"), (dict, type(None))):
        raise StepError("refused claim: ats is not an object")
    return claim


def claim_domain(claim: Dict[str, Any]) -> str:
    return _match(DOMAIN, claim.get("domain"), "domain", "unsafe_value")


def _secret_shaped(text: str) -> bool:
    return any(p.search(text) for p in SECRET_SHAPES)


def text_ok(value: Any, lo: int = TEXT_MIN, hi: int = TEXT_MAX) -> bool:
    """Printable, single-line text with nothing that could escape a string or carry a
    secret: none of `` ` $ \\ < > { } ``, no secret prefixes, no 32+ token-ish run."""
    return (isinstance(value, str) and lo <= len(value) <= hi and value == value.strip()
            and value.isprintable() and not (TEXT_FORBIDDEN & set(value))
            and not _secret_shaped(value) and not SECRET_RUN.search(value))


def scout_url_ok(value: Any, max_query: Optional[int] = None) -> bool:
    if not isinstance(value, str) or len(value) > MAX_URL_CHARS or not value.isprintable():
        return False
    if any(c.isspace() for c in value) or _secret_shaped(value):
        return False
    try:
        p = urllib.parse.urlsplit(value)
        port = p.port
    except ValueError:
        return False
    if p.scheme != "https" or not p.hostname or p.username or p.password or port not in (None, 443):
        return False
    return max_query is None or len(p.query) <= max_query


def parse_scout(data: Any, card_id: int) -> Dict[str, Any]:
    """The scout reply, or ValueError. Any violation refuses the whole file."""
    if not isinstance(data, dict) or set(data) != SCOUT_KEYS:
        raise ValueError("keys must be exactly " + ", ".join(sorted(SCOUT_KEYS)))
    if data["schema"] != SCOUT_SCHEMA:
        raise ValueError("wrong schema")
    if isinstance(data["card_id"], bool) or data["card_id"] != card_id:
        raise ValueError("card_id does not match the claim")
    boards = data["boards"]
    if not isinstance(boards, list) or len(boards) > MAX_SCOUT_BOARDS:
        raise ValueError(f"boards must be a list of at most {MAX_SCOUT_BOARDS}")
    pairs: List[Tuple[str, str]] = []
    for b in boards:
        if not isinstance(b, dict) or set(b) != {"ats", "token", "evidence_url"}:
            raise ValueError("a board must have exactly ats, token, evidence_url")
        if b["ats"] not in ATS_NAMES or not token_ok(b["token"]) or not scout_url_ok(b["evidence_url"]):
            raise ValueError("a board has a bad ats, token or evidence_url")
        pairs.append((b["ats"], b["token"]))
    logo = data["logo"]
    if not isinstance(logo, dict) or set(logo) != {"symbol_url", "wordmark_url"}:
        raise ValueError("logo must have exactly symbol_url, wordmark_url")
    for key in ("symbol_url", "wordmark_url"):
        if logo[key] is not None and not scout_url_ok(logo[key], MAX_LOGO_QUERY_CHARS):
            raise ValueError(f"bad logo.{key}")
    if not text_ok(data["summary"]):
        raise ValueError("bad summary")
    if data["milestone"] is not None and not text_ok(data["milestone"]):
        raise ValueError("bad milestone")
    return {"boards": pairs, "symbol_url": logo["symbol_url"], "wordmark_url": logo["wordmark_url"],
            "summary": data["summary"], "milestone": data["milestone"]}


def load_scout(card_id: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """The parsed scout reply, or (None, why). A missing or bad reply is not an error:
    the step continues without it."""
    path = scout_path(card_id)
    if not path.exists() and not path.is_symlink():
        return None, "missing"
    try:
        return parse_scout(read_json(path, "scout reply"), int(card_id)), "ok"
    except StepError as e:
        return None, str(e)
    except ValueError as e:
        return None, f"refused: {e}"


def load_board(card_id: str) -> Dict[str, Any]:
    b = read_json(board_path(card_id), f"board.json for card {card_id} (run verify-board)")
    if not isinstance(b, dict):
        raise StepError("refused board.json: not an object")
    ats = b.get("ats")
    if ats not in ATS_NAMES or not token_ok(b.get("token")):
        raise StepError("refused board.json: ats/token")
    _match(SLUG, b.get("slug"), "slug")
    _match(DISPLAY_NAME, b.get("display_name"), "display name")
    _match(ENUM_MEMBER, b.get("enum_member"), "enum member")
    if b.get("enum_member") != enum_member_for(b["slug"]):
        raise StepError("refused board.json: enum member does not match the slug")
    if b.get("board_url") != public_board_url(ats, b["token"]) or b.get("checked_url") != api_url(ats, b["token"]):
        raise StepError("refused board.json: URLs")
    n = b.get("job_count")
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise StepError("refused board.json: job_count")
    if b.get("card_id") != int(card_id):
        raise StepError("refused board.json: another card")
    return b


# ---- boards -----------------------------------------------------------------------------------
def api_url(ats: str, token: str) -> str:
    host, path = BOARD_APIS[ats]
    return f"https://{host}{path.format(t=urllib.parse.quote(token, safe=''))}"


def public_board_url(ats: str, token: str) -> str:
    return PUBLIC_BOARDS[ats].format(t=urllib.parse.quote(token, safe=""))


def boards_in_text(text: str) -> List[Tuple[str, str]]:
    """Every (ats, token) a supported board URL in ``text`` names, in order."""
    found: List[Tuple[int, str, str]] = []
    for ats, patterns in BOARD_URL_PATTERNS.items():
        for pat in patterns:
            for m in pat.finditer(text):
                if token_ok(m.group(1)):
                    found.append((m.start(), ats, m.group(1)))
    out: List[Tuple[str, str]] = []
    for _, ats, token in sorted(found):
        if (ats, token) not in out:
            out.append((ats, token))
    return out


def tracked_pairs(wt: Path) -> Set[Tuple[str, str]]:
    """Every (ats, lower-cased token) the worktree already tracks: the board URLs in
    ``companies.ts`` and the ``{'ats': …, 'board_token': …}`` literals of the seed
    migrations. Only an exact pair counts (``ai`` is not ``openai``)."""
    pairs = {(a, t.lower()) for a, t in boards_in_text((wt / COMPANIES_TS).read_text(encoding="utf-8"))}
    for path in sorted((wt / VERSIONS_DIR).glob("*.py")):
        for m in SEED_PAIR.finditer(path.read_text(encoding="utf-8")):
            pairs.add((m.group(1), m.group(2).lower()))
    return pairs


def board_candidates(claim: Dict[str, Any], scout: Optional[Dict[str, Any]]) -> List[Tuple[str, str]]:
    """The card's own ats, then ATS URLs in its board/careers URLs, then the scout's."""
    out: List[Tuple[str, str]] = []

    def add(ats: str, token: str) -> None:
        if ats in ATS_NAMES and token_ok(token) and (ats, token) not in out and len(out) < MAX_CANDIDATES:
            out.append((ats, token))

    ats = claim.get("ats") or {}
    if isinstance(ats.get("provider"), str) and isinstance(ats.get("board_token"), str):
        add(ats["provider"], ats["board_token"])
    for key in (ats.get("board_url"), claim.get("careers_url")):
        if isinstance(key, str):
            for a, t in boards_in_text(key):
                add(a, t)
    for a, t in (scout or {}).get("boards", []):
        add(a, t)
    return out


class _SameHostRedirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, host: str) -> None:
        super().__init__()
        self.host = host

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        p = urllib.parse.urlsplit(newurl)
        if p.scheme != "https" or p.hostname != self.host:
            raise urllib.error.HTTPError(newurl, code, "redirect to another host refused", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _http_get(url: str, host: str) -> Tuple[int, bytes]:
    """GET a fixed-host API URL: (status, body). Transport errors propagate."""
    opener = urllib.request.build_opener(_SameHostRedirects(host))
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with opener.open(req, timeout=BOARD_TIMEOUT_S) as resp:
            return resp.status, resp.read(MAX_BOARD_BYTES + 1)
    except urllib.error.HTTPError as e:
        return e.code, b""


http_get: Callable[[str, str], Tuple[int, bytes]] = _http_get


def count_jobs(ats: str, body: bytes) -> Optional[int]:
    if len(body) > MAX_BOARD_BYTES:
        return None
    try:
        data = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    jobs = data.get("jobs") if ats in ("greenhouse", "ashby") and isinstance(data, dict) else data
    return len(jobs) if isinstance(jobs, list) else None


def check_board(ats: str, token: str) -> Tuple[str, int, str]:
    """("ok" | "empty" | "missing" | "transient", job count, the API URL)."""
    url = api_url(ats, token)
    try:
        status, body = http_get(url, BOARD_APIS[ats][0])
    except (socket.timeout, TimeoutError):
        return "transient", 0, url
    except (OSError, urllib.error.URLError, http.client.HTTPException, ValueError):
        return "transient", 0, url
    if status == 429 or status >= 500:
        return "transient", 0, url
    if status != 200:
        return "missing", 0, url
    n = count_jobs(ats, body)
    if n is None:
        return "missing", 0, url
    return ("ok" if n > 0 else "empty"), n, url


# ---- names and slugs (D3) ----------------------------------------------------------------------
def fold_name(company: Any) -> str:
    if not isinstance(company, str):
        return ""
    ascii_text = unicodedata.normalize("NFKD", company).encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_text.split())


def enum_member_for(slug: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in slug.split("-") if part)


def slug_candidates(name: str, domain: str, card_id: str) -> List[str]:
    out: List[str] = []
    for raw in (re.sub(r"[^a-z0-9]+", "-", name.lower()), domain.replace(".", "-")):
        cand = raw.strip("-")[:41].strip("-")
        if SLUG.fullmatch(cand) and cand not in out:
            out.append(cand)
    if out:
        suffix = f"-{card_id}"
        cand = out[0][: 41 - len(suffix)].rstrip("-") + suffix
        if SLUG.fullmatch(cand) and cand not in out:
            out.append(cand)
    return out


_ENUM_LINE = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*'([^']*)',?\s*")
_COMPANY_ID = re.compile(r"createBackendScraperCompany\(\s*'([^']*)'")


def _block(lines: List[str], start_line: str, end_line: str, what: str) -> Tuple[int, int]:
    starts = [i for i, ln in enumerate(lines) if ln == start_line]
    if len(starts) != 1:
        raise StepError(f"cannot find {what} in the worktree")
    for j in range(starts[0] + 1, len(lines)):
        if lines[j] == end_line:
            return starts[0], j
    raise StepError(f"cannot find the end of {what}")


def enum_members(companies_ts: str) -> List[Tuple[str, str]]:
    lines = companies_ts.split("\n")
    s, e = _block(lines, "export const enum COMPANY_IDS {", "}", "COMPANY_IDS")
    return [(m.group(1), m.group(2)) for m in (_ENUM_LINE.fullmatch(ln) for ln in lines[s + 1:e]) if m]


def slug_taken(wt: Path, slug: str, member: str) -> Optional[str]:
    """Why ``slug`` (or its enum member) is not free in the worktree, or None."""
    companies = (wt / COMPANIES_TS).read_text(encoding="utf-8")
    if slug in set(_COMPANY_ID.findall(companies)):
        return "companies.ts id"
    members = enum_members(companies)
    if any(value == slug for _, value in members):
        return "COMPANY_IDS value"
    if any(name.lower() == member.lower() for name, _ in members):
        return "COMPANY_IDS member"
    changelog = (wt / CHANGELOG_TS).read_text(encoding="utf-8")
    if re.search(r"\bid:\s*['\"]add-" + re.escape(slug) + r"['\"]", changelog):
        return "changelog id"
    if list((wt / VERSIONS_DIR).glob(f"*_seed_{slug}_company.py")):
        return "seed migration"
    if any((wt / LOGOS_DIR / d / f"{slug}.png").exists() for d in LOGO_VARIANT_DIRS):
        return "logo file"
    try:
        profiles = json.loads((wt / PROFILES_JSON).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise StepError("company_profiles.json is unreadable in the worktree") from None
    if isinstance(profiles, dict) and slug in profiles:
        return "company_profiles.json key"
    return None


def pick_slug(wt: Path, name: str, domain: str, card_id: str) -> Optional[Tuple[str, str]]:
    for slug in slug_candidates(name, domain, card_id):
        member = enum_member_for(slug)
        if ENUM_MEMBER.fullmatch(member) and slug_taken(wt, slug, member) is None:
            return slug, member
    return None


# ---- compose (templated files, D3) ------------------------------------------------------------
def ts_str(value: str) -> str:
    """A single-quoted TS string. Every value passed here excludes ``\\`` and control
    characters (text_ok / the name, slug and URL patterns), so only ``'`` needs escaping."""
    if "\\" in value or not value.isprintable():
        raise StepError("refused a value for a TS string")
    return "'" + value.replace("'", "\\'") + "'"


def today() -> str:
    return dt.datetime.now(dt.timezone.utc).date().isoformat()


def insert_company(text: str, card_id: str, domain: str, board: Dict[str, Any]) -> str:
    lines = text.split("\n")
    _, end = _block(lines, "export const COMPANIES: Company[] = [", "];", "COMPANIES")
    block = [
        "",
        f"  // Launch Radar card {card_id} ({domain})",
        f"  createBackendScraperCompany({ts_str(board['slug'])}, {ts_str(board['display_name'])}, "
        f"{ts_str(board['board_url'])}, {{",
        f"    sourceAts: {ts_str(board['ats'])},",
        "  }),",
    ]
    lines[end:end] = block
    s, e = _block(lines, "export const enum COMPANY_IDS {", "}", "COMPANY_IDS")
    member = board["enum_member"]
    pos = e
    for i in range(s + 1, e):
        m = _ENUM_LINE.fullmatch(lines[i])
        if m and m.group(1).lower() > member.lower():
            pos = i
            break
    lines.insert(pos, f"  {member} = {ts_str(board['slug'])},")
    return "\n".join(lines)


def insert_changelog(text: str, board: Dict[str, Any], description: str, date: str) -> str:
    if "import { ROUTES } from './routes';" not in text:
        raise StepError("changelog.ts does not import ROUTES")
    lines = text.split("\n")
    anchor = [i for i, ln in enumerate(lines) if ln == "export const CHANGELOG: readonly ChangelogEntry[] = ["]
    if len(anchor) != 1:
        raise StepError("cannot find CHANGELOG in the worktree")
    name = board["display_name"]
    entry = [
        "  {",
        f"    id: {ts_str('add-' + board['slug'])},",
        f"    title: {ts_str('Added ' + name)},",
        "    description:",
        f"      {ts_str(description)},",
        "    tags: ['new-companies'],",
        f"    date: {ts_str(date)},",
        "    link: {",
        "      to: ROUTES.ACCOUNT,",
        f"      label: {ts_str('Add ' + name + ' to your company preferences')},",
        "    },",
        "  },",
    ]
    lines[anchor[0] + 1:anchor[0] + 1] = entry
    return "\n".join(lines)


def insert_profile(text: str, slug: str, blurb: str, accomplishment: Optional[str]) -> str:
    try:
        data = json.loads(text)
    except ValueError:
        raise StepError("company_profiles.json is not JSON") from None
    if not isinstance(data, dict) or json.dumps(data, indent=2, ensure_ascii=False) + "\n" != text:
        raise StepError("company_profiles.json is not in its canonical form; refusing to rewrite it")
    if slug in data:
        raise StepError(f"company_profiles.json already has {slug}")
    entry: Dict[str, str] = {"blurb": blurb}
    if accomplishment:
        entry["accomplishment"] = accomplishment
    data[slug] = entry
    return json.dumps({k: data[k] for k in sorted(data)}, indent=2, ensure_ascii=False) + "\n"


def _sentence(text: str) -> str:
    text = text[:1].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else text + "."


def describe(board: Dict[str, Any], claim: Dict[str, Any], scout: Optional[Dict[str, Any]]) -> Tuple[str, str]:
    """(changelog description, its source). The scout's summary and milestone, else the
    card's one-liner, else the bare sentence."""
    name, ats_name = board["display_name"], ATS_NAMES[board["ats"]]
    summary, milestone, source = None, None, "none"
    if scout:
        summary, milestone, source = scout["summary"], scout["milestone"], "scout"
    elif text_ok(claim.get("one_liner")):
        summary, source = claim["one_liner"], "one_liner"
    if summary:
        text = f"{name} — {summary.rstrip('.').rstrip()} — is now tracked via its {ats_name} job board."
    else:
        text = f"{name} is now tracked via its {ats_name} job board."
    if milestone:
        text += " " + _sentence(milestone)
    return text, source


def current_head(wt: Path) -> str:
    """The single Alembic head of the worktree (pinned ``current_head.py``)."""
    proc = run([sys.executable, "-I", "-B", str(wt / ADD_COMPANY_SCRIPTS / "current_head.py")], cwd=wt, check=False)
    lines = proc.stdout.strip().splitlines()
    if proc.returncode != 0 or len(lines) != 1 or not REVISION.fullmatch(lines[0].strip()):
        raise StepError(f"not exactly one Alembic head: {(proc.stdout + proc.stderr).strip()[-400:]}",
                        "multi_head")
    return lines[0].strip()


def compose_into(wt: Path, card_id: str, board: Dict[str, Any], claim: Dict[str, Any],
                 scout: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    domain = claim_domain(claim)
    slug, member = board["slug"], board["enum_member"]
    if (board["ats"], board["token"].lower()) in tracked_pairs(wt):
        raise StepError(f"{board['ats']} {board['token']} is already tracked in the worktree")
    taken = slug_taken(wt, slug, member)
    if taken:
        raise StepError(f"slug {slug} is taken in the worktree ({taken}); compose runs once per worktree")
    description, source = describe(board, claim, scout)
    files = {
        COMPANIES_TS: insert_company((wt / COMPANIES_TS).read_text(encoding="utf-8"), card_id, domain, board),
        CHANGELOG_TS: insert_changelog((wt / CHANGELOG_TS).read_text(encoding="utf-8"), board, description,
                                       today()),
    }
    if scout:
        files[PROFILES_JSON] = insert_profile((wt / PROFILES_JSON).read_text(encoding="utf-8"), slug,
                                              _sentence(scout["summary"]), scout["milestone"])
    assert_pinned(wt)
    head = current_head(wt)
    run([sys.executable, "-I", "-B", str(wt / ADD_COMPANY_SCRIPTS / "scaffold_migration.py"), "--id", slug,
         "--display-name", board["display_name"], "--ats", board["ats"], "--board-token", board["token"],
         "--down-revision", head], cwd=wt)
    migrations = sorted((wt / VERSIONS_DIR).glob(f"*_seed_{slug}_company.py"))
    if len(migrations) != 1:
        raise StepError(f"expected one new seed migration for {slug}, found {len(migrations)}")
    for rel, text in files.items():
        (wt / rel).write_text(text, encoding="utf-8")
    return {"composed": sorted(files), "migration": f"{VERSIONS_DIR}/{migrations[0].name}",
            "down_revision": head, "changelog_source": source, "profile": PROFILES_JSON in files}


# ---- staging guard -----------------------------------------------------------------------------
def _raw_entries(raw_diff: str) -> List[Tuple[str, str, str, Optional[str]]]:
    """(new mode, status, path, second path) for ``git diff --cached --raw -z``."""
    out: List[Tuple[str, str, str, Optional[str]]] = []
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
        second = None
        if status[0] in "RC":  # renames/copies carry a second path
            second = fields[i] if i < len(fields) else ""
            i += 1
        out.append((new_mode, status, path, second))
    return out


def _allowed_added(slug: str) -> Tuple["re.Pattern[str]", ...]:
    s = re.escape(slug)
    return (re.compile(rf"src/backend/alembic/versions/[0-9]{{8}}_[0-9]{{6}}_[0-9a-f]{{12}}_seed_{s}_company\.py"),
            re.compile(rf"src/frontend/public/logos/(icons|wordmarks|lockups)/{s}\.png"))


def staged_problems(raw_diff: str, slug: str) -> List[str]:
    """Everything staged that an add-company PR for ``slug`` may not contain, and
    anything it must contain but does not."""
    problems: List[str] = []
    allowed_added = _allowed_added(slug)
    seen_modified, migrations = set(), 0
    for new_mode, status, path, second in _raw_entries(raw_diff):
        if second is not None:
            problems.append(f"{status[0]} {path} -> {second}")
        elif new_mode not in ("100644", "000000"):
            problems.append(f"mode {new_mode} on {path}")
        elif status == "M" and path in ALLOWED_MODIFIED:
            seen_modified.add(path)
        elif status == "A" and any(p.fullmatch(path) for p in allowed_added):
            migrations += path.startswith(VERSIONS_DIR)
        else:
            problems.append(f"{status} {path}")
    problems += [f"missing change to {p}" for p in REQUIRED_MODIFIED if p not in seen_modified]
    if migrations != 1:
        problems.append(f"expected one seed migration, staged {migrations}")
    return problems


def staged_paths(raw_diff: str) -> List[str]:
    return sorted(path for _, _, path, _ in _raw_entries(raw_diff))


def stage_and_check(wt: Path, slug: str) -> List[str]:
    git(wt, "add", "-A")
    raw = git(wt, "diff", "--cached", "--raw", "-z", "--no-renames").stdout
    problems = staged_problems(raw, slug)
    if problems:
        raise StepError("refused to commit paths outside the add-company set: " + "; ".join(problems[:20]))
    return staged_paths(raw)


def pr_title(board: Dict[str, Any]) -> str:
    return _match(TITLE, f"feat(companies): add {board['display_name']} ({ATS_NAMES[board['ats']]})", "PR title")


def push_leased(wt: Path, branch: str, lease: str) -> None:
    """The only push: this card's own ref, explicit refspec, leased on what we last saw
    there (``""`` = must not exist)."""
    _match(BRANCH, branch, "branch")
    if lease and not SHA.fullmatch(lease):
        raise StepError("refused lease")
    git(wt, "push", "--no-verify", f"--force-with-lease=refs/heads/{branch}:{lease}", "origin",
        f"HEAD:refs/heads/{branch}", reason="git_error")


# ---- subcommands ----------------------------------------------------------------------------
def _clear_scratch(card_id: str) -> None:
    w = work_dir(card_id)
    for name in ("raw", "masters", "lease", "gh_login", "pr-body.md"):
        remove_path(w / name)


def cmd_worktree(card_id: str) -> Dict[str, Any]:
    claim = load_claim(card_id)
    requested_at = parse_ts(claim["requested_at"])
    if requested_at is None:
        raise StepError("refused claim: bad requested_at")
    branch = branch_for(card_id)
    stale = remove_worktree(card_id)
    for name in ("raw", "masters"):
        remove_path(work_dir(card_id) / name)
    verdict = pr_verdict(trusted_prs(card_id), requested_at)
    if verdict:
        kind, pr = verdict
        if kind == "existing_pr":
            board = None
            try:
                board = load_board(card_id)
            except StepError:
                pass
            commit = pr.get("headRefOid") if isinstance(pr.get("headRefOid"), str) and SHA.fullmatch(
                pr["headRefOid"]) else None
            write_json(published_path(card_id), {
                "card_id": int(card_id), "dry_run": False, "pr_url": pr["url"], "pr_number": pr["number"],
                "commit": commit, "slug": board["slug"] if board else None, "draft": None, "adopted": True})
            raise Stop({"existing_pr": pr["url"], "pr_number": pr["number"]})
        if kind == "already_tracked":
            raise Stop({"already_tracked": True, "pr_url": pr["url"]})
        raise Stop({"pr_closed": pr["url"], "report_reason": "pr_closed"})
    git(ROOT, "fetch", "--quiet", "origin", "main", reason="env_error")
    lease = remote_branch_sha(branch)
    write_text(work_dir(card_id) / "lease", lease + "\n")
    git(ROOT, "branch", "-D", branch, check=False)
    wt = card_dir(card_id)
    git(ROOT, "worktree", "add", "--no-track", "-B", branch, str(wt), "refs/remotes/origin/main")
    return {"worktree": str(wt.relative_to(ROOT)), "branch": branch, "lease": lease, "stale_removed": stale}


def cmd_verify_board(card_id: str) -> Dict[str, Any]:
    wt = existing_worktree(card_id)
    claim = load_claim(card_id)
    scout, scout_note = load_scout(card_id)
    if not isinstance(claim.get("domain"), str) or not DOMAIN.fullmatch(claim["domain"]):
        raise Stop({"failed": "unsafe_value", "report_reason": "unsafe_value", "why": "domain"})
    name = fold_name(claim.get("company"))
    if not DISPLAY_NAME.fullmatch(name):
        raise Stop({"failed": "unsafe_value", "report_reason": "unsafe_value", "why": "company name"})
    provider = (claim.get("ats") or {}).get("provider")
    candidates = board_candidates(claim, scout)
    winner: Optional[Tuple[str, str, int, str]] = None
    saw_empty, transient = False, False
    for ats, token in candidates:
        status, n, url = check_board(ats, token)
        if status == "ok":
            winner = (ats, token, n, url)
            break
        saw_empty = saw_empty or status == "empty"
        transient = transient or status == "transient"
    if winner is None:
        if transient:
            raise StepError("a board check failed on the network; retry later", "timeout")
        if scout_note != "ok":
            # The board search never really ran (scout errored or its reply was refused).
            # no_board is final, so only a search with a usable scout reply may claim it.
            raise StepError("no usable scout reply; board search incomplete", "step_refused")
        reason = "board_empty" if saw_empty else (
            "unsupported_ats" if provider in UNSUPPORTED_ATS else "board_not_found")
        raise Stop({"no_board": reason, "candidates": len(candidates), "scout": scout_note})
    ats, token, n, url = winner
    if (ats, token.lower()) in tracked_pairs(wt):
        raise Stop({"already_tracked": True, "ats": ats, "token": token})
    picked = pick_slug(wt, name, claim["domain"], card_id)
    if picked is None:
        raise Stop({"failed": "unsafe_value", "report_reason": "unsafe_value", "why": "no free slug"})
    slug, member = picked
    board = {"card_id": int(card_id), "ats": ats, "token": token, "job_count": n, "checked_url": url,
             "board_url": public_board_url(ats, token), "slug": slug, "display_name": name,
             "enum_member": member, "checked_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()}
    write_json(board_path(card_id), board)
    return {"board": board, "scout": scout_note}


def cmd_compose(card_id: str) -> Dict[str, Any]:
    wt = existing_worktree(card_id)
    board, claim = load_board(card_id), load_claim(card_id)
    scout, note = load_scout(card_id)
    out = compose_into(wt, card_id, board, claim, scout)
    out["scout"] = note
    return out


def cmd_check_head(card_id: str) -> Dict[str, Any]:
    wt = existing_worktree(card_id)
    assert_pinned(wt)
    return {"head": current_head(wt)}


# -- logos: the connection is pinned to the IP that was checked (no DNS rebinding) --
def _resolve(host: str) -> List[str]:
    return [str(info[4][0]) for info in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)]


resolve: Callable[[str], List[str]] = _resolve


def pin_host(host: str) -> str:
    """One checked IP for ``host``: every address it resolves to must be global."""
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not literal.is_global:
            raise StepError(f"refused {host}: not a public address")
        return str(literal)
    try:
        addrs = resolve(host)
    except (OSError, UnicodeError) as e:
        raise StepError(f"cannot resolve {host}: {type(e).__name__}") from None
    if not addrs:
        raise StepError(f"cannot resolve {host}")
    for a in addrs:
        try:
            ok = ipaddress.ip_address(a.split("%")[0]).is_global
        except ValueError:
            ok = False
        if not ok:
            raise StepError(f"refused {host}: resolves to a non-public address")
    return addrs[0].split("%")[0]


def check_logo_url(url: str) -> Tuple[urllib.parse.SplitResult, str]:
    """(the parsed URL, the checked IP to connect to)."""
    if not scout_url_ok(url, MAX_LOGO_QUERY_CHARS):
        raise StepError(f"refused url {url!r}"[:300] + ": https, public, no credentials, short query only")
    p = urllib.parse.urlsplit(url)
    return p, pin_host(p.hostname or "")


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS to ``host`` over a socket to the already-checked ``ip``. SNI and the
    certificate check still use the host name."""

    def __init__(self, host: str, ip: str, timeout: float = 30) -> None:
        super().__init__(host, 443, timeout=timeout, context=ssl.create_default_context())
        self.pinned_ip = ip

    def connect(self) -> None:
        sock = socket.create_connection((self.pinned_ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)  # type: ignore[attr-defined]


def _make_connection(host: str, ip: str) -> Any:
    return PinnedHTTPSConnection(host, ip)


make_connection: Callable[[str, str], Any] = _make_connection


def fetch_logo(url: str) -> Tuple[str, bytes]:
    """(content type, bytes). Every hop is re-checked and re-pinned."""
    for _ in range(MAX_LOGO_REDIRECTS + 1):
        parts, ip = check_logo_url(url)
        conn = make_connection(parts.hostname or "", ip)
        try:
            path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
            conn.request("GET", path, headers={"User-Agent": USER_AGENT, "Accept": "image/*"})
            resp = conn.getresponse()
            if resp.status in (301, 302, 303, 307, 308):
                location = resp.getheader("Location")
                if not location:
                    raise StepError("redirect without a Location")
                url = urllib.parse.urljoin(url, location)
                continue
            if resp.status != 200:
                raise StepError(f"download failed: HTTP {resp.status}")
            ctype = (resp.getheader("Content-Type") or "").split(";")[0].strip().lower()
            data = resp.read(MAX_LOGO_BYTES + 1)
            return ctype, data
        except (OSError, http.client.HTTPException, ssl.SSLError) as e:
            raise StepError(f"download failed: {type(e).__name__}") from None
        finally:
            conn.close()
    raise StepError("too many redirects")


def logo_python() -> Path:
    py = state_dir() / "logo-venv" / "bin" / "python"
    if not py.exists():
        raise StepError("logo venv missing; run scripts/launch_radar/logo_setup.sh by hand")
    return py


def _u16be(b: bytes, i: int) -> int:
    return int.from_bytes(b[i:i + 2], "big")


def _png_size(data: bytes) -> Optional[Tuple[int, int]]:
    if len(data) < 24 or not data.startswith(PNG_MAGIC) or data[12:16] != b"IHDR":
        return None
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


# SOF0-SOF15 minus DHT (C4), JPG (C8) and DAC (CC).
_JPEG_SOF = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}


def _jpeg_size(data: bytes) -> Optional[Tuple[int, int]]:
    """The largest frame declared before the first scan (a decoder may use any of them)."""
    if not data.startswith(b"\xff\xd8"):
        return None
    i, best = 2, None
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        if marker == 0xFF:  # fill byte
            i += 1
            continue
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:  # standalone markers
            i += 2
            continue
        if marker in (0xD9, 0xDA):  # EOI / SOS: no frame header after this matters
            break
        seg = _u16be(data, i + 2)
        if seg < 2:
            return None
        if marker in _JPEG_SOF:
            if i + 9 > len(data):
                return None
            h, w = _u16be(data, i + 5), _u16be(data, i + 7)
            if best is None or w * h > best[0] * best[1]:
                best = (w, h)
        i += 2 + seg
    return best


def _webp_size(data: bytes) -> Optional[Tuple[int, int]]:
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    chunk = data[12:16]
    if chunk == b"VP8 " and data[23:26] == b"\x9d\x01\x2a":
        return (int.from_bytes(data[26:28], "little") & 0x3FFF,
                int.from_bytes(data[28:30], "little") & 0x3FFF)
    if chunk == b"VP8L" and data[20] == 0x2F:
        bits = int.from_bytes(data[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if chunk == b"VP8X":
        return int.from_bytes(data[24:27], "little") + 1, int.from_bytes(data[27:30], "little") + 1
    return None


def _ico_sizes(data: bytes) -> Optional[List[Tuple[int, int]]]:
    """Every entry's size, read from the embedded PNG/BMP header, not the directory byte."""
    if len(data) < 6 or data[:4] != b"\x00\x00\x01\x00":
        return None
    count = int.from_bytes(data[4:6], "little")
    if count == 0 or 6 + 16 * count > len(data):
        return None
    sizes = []
    for n in range(count):
        entry = 6 + 16 * n
        off = int.from_bytes(data[entry + 12:entry + 16], "little")
        img = data[off:off + 32]
        if img.startswith(PNG_MAGIC):
            size = _png_size(data[off:off + 24])
            if size is None:
                return None
        elif len(img) >= 12:  # BITMAPINFOHEADER: int32 width, int32 height (x2 for the mask)
            w = int.from_bytes(img[4:8], "little", signed=True)
            h = int.from_bytes(img[8:12], "little", signed=True)
            size = (abs(w), abs(h) // 2 or abs(h))
        else:
            return None
        sizes.append(size)
    return sizes


def check_logo_dimensions(ext: str, data: bytes) -> None:
    """Refuse a raster logo whose header claims more than MAX_LOGO_PIXELS (or none we can
    read). SVG is rasterized at a fixed width by normalize.py, so it is not measured here."""
    if ext == "svg":
        return
    if ext == "png":
        found = _png_size(data)
        sizes = [found] if found else None
    elif ext == "jpg":
        found = _jpeg_size(data)
        sizes = [found] if found else None
    elif ext == "webp":
        found = _webp_size(data)
        sizes = [found] if found else None
    elif ext == "ico":
        sizes = _ico_sizes(data)
    else:
        raise StepError(f"refused {ext}: no size check for it")
    if not sizes:
        raise StepError(f"refused {ext}: could not read its pixel size from the header")
    for w, h in sizes:
        if w <= 0 or h <= 0 or w * h > MAX_LOGO_PIXELS:
            raise StepError(f"refused {ext}: {w}x{h} is over the {MAX_LOGO_PIXELS}-pixel limit")


def cmd_logo_fetch(card_id: str, name: str) -> Dict[str, Any]:
    existing_worktree(card_id)
    if name not in LOGO_NAMES:
        raise StepError(f"refused name {name!r}")
    scout, note = load_scout(card_id)
    if scout is None:
        raise StepError(f"no valid scout reply ({note})")
    url = scout[f"{name}_url"]
    if not url:
        raise StepError(f"the scout found no {name} URL")
    ctype, data = fetch_logo(url)
    if len(data) > MAX_LOGO_BYTES:
        raise StepError("refused: larger than 5 MB")
    ext = LOGO_EXTS.get(ctype)
    if ext is None:
        raise StepError(f"refused content-type {ctype!r}; expected an image")
    check_logo_dimensions(ext, data)
    raw = work_dir(card_id) / "raw"
    _no_symlinks_below_root(raw)
    raw.mkdir(parents=True, exist_ok=True, mode=0o700)
    for old in raw.glob(f"{name}.*"):
        old.unlink()
    out = raw / f"{name}.{ext}"
    out.write_bytes(data)
    return {"saved": str(out.relative_to(ROOT)), "bytes": len(data)}


def cmd_logo_normalize(card_id: str, name: str, remove_white: bool) -> Dict[str, Any]:
    existing_worktree(card_id)
    if name not in LOGO_NAMES:
        raise StepError(f"refused name {name!r}")
    raws = sorted((work_dir(card_id) / "raw").glob(f"{name}.*"))
    if not raws:
        raise StepError(f"no raw {name}; run logo-fetch first")
    master = work_dir(card_id) / "masters" / f"{name}.png"
    _no_symlinks_below_root(master)
    master.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    argv = [str(logo_python()), "-I", str(LOGO_SCRIPTS / "normalize.py"), str(raws[0]), str(master)]
    if remove_white:
        argv.append("--remove-white")
    run(argv)
    return {"master": str(master.relative_to(ROOT))}


def cmd_logo_tile(card_id: str, variant: str, bg: str, knockout: str) -> Dict[str, Any]:
    wt = existing_worktree(card_id)
    slug = load_board(card_id)["slug"]
    _match(HEX, bg, "background colour")
    if knockout not in ("white", "black", "none"):
        raise StepError(f"refused knockout {knockout!r}")
    masters = work_dir(card_id) / "masters"
    py = str(logo_python())
    logos = wt / LOGOS_DIR
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


def pr_body(card_id: str, domain: str, board: Dict[str, Any], files: List[str], draft_no_logos: bool) -> str:
    name, ats_name = board["display_name"], ATS_NAMES[board["ats"]]
    kinds = ["companies.ts", "one seed migration", "changelog.ts"]
    if PROFILES_JSON in files:
        kinds.append("company_profiles.json")
    if any(f.startswith(LOGOS_DIR) for f in files):
        kinds.append("logos")
    lines = [
        f"Adds {name} ({domain}), saved on the Launch Radar admin page (card {card_id}).",
        "",
        f"- Board: {ats_name} `{board['token']}`, {board['job_count']} open jobs "
        f"(checked live {str(board['checked_at'])[:10]}: {board['checked_url']})",
        f"- Files: {', '.join(kinds)}",
        "- One Alembic head after the migration (current_head.py)",
        "- Not run here: type-check and tests. CI runs them.",
    ]
    if draft_no_logos:
        lines.append("- Logos missing: CI's logo test fails until they are added.")
    lines += [
        "- If main moves, the nightly loop rebuilds this branch from the new main (only while nobody",
        "  else has pushed to it). After merging another radar PR, wait a night or run",
        "  `scripts/launch_radar/radar.sh pr-refresh` on the server.",
        "",
        f"Launch-Radar-Card: {card_id}",
        "",
    ]
    return "\n".join(lines)


def cmd_publish(card_id: str, draft: bool, dry_run: bool) -> Dict[str, Any]:
    wt = existing_worktree(card_id)
    board, claim = load_board(card_id), load_claim(card_id)
    domain = claim_domain(claim)
    branch = branch_for(card_id)
    head_branch = git(wt, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if head_branch != branch:
        raise StepError(f"the worktree is on {head_branch!r}, not {branch}")
    slug = board["slug"]
    assert_pinned(wt)
    current_head(wt)
    missing_logos = [d for d in ("icons", "wordmarks") if not (wt / LOGOS_DIR / d / f"{slug}.png").is_file()]
    draft = draft or bool(missing_logos)
    title = pr_title(board)
    files = stage_and_check(wt, slug)
    git(wt, "commit", "--no-verify", "--quiet", "-m", title)
    commit = _match(SHA, git(wt, "rev-parse", "HEAD").stdout.strip(), "commit")
    if dry_run:
        record = {"card_id": int(card_id), "dry_run": True, "pr_url": None, "commit": commit, "slug": slug,
                  "draft": draft, "files": files, "title": title}
        write_json(published_path(card_id), record)
        return record
    lease_file = work_dir(card_id) / "lease"
    if lease_file.is_symlink() or not lease_file.is_file():
        raise StepError("no lease recorded; run worktree first")
    push_leased(wt, branch, lease_file.read_text().strip())
    body = work_dir(card_id) / "pr-body.md"
    write_text(body, pr_body(card_id, domain, board, files, bool(missing_logos)))
    argv = ["gh", "pr", "create", "--repo", REPO, "--base", "main", "--head", branch, "--title", title,
            "--body-file", str(body), "--label", "launch-radar"]
    if draft:
        argv.append("--draft")
    out = run(argv, cwd=wt, reason="gh_error").stdout
    urls = [ln.strip() for ln in out.splitlines() if PR_URL_RE.fullmatch(ln.strip())]
    if not urls:
        raise StepError("gh pr create printed no PR URL of this repository", "gh_error")
    pr_url = urls[-1]
    m = PR_URL_RE.fullmatch(pr_url)
    record = {"card_id": int(card_id), "dry_run": False, "pr_url": pr_url,
              "pr_number": int(m.group(1)) if m else None, "commit": commit, "slug": slug, "draft": draft,
              "files": files}
    write_json(published_path(card_id), record)
    return record


def cmd_cleanup(card_id: str) -> Dict[str, Any]:
    """The worktree, its local branch and the scratch files go. ``board.json`` and the
    claim, scout and published files stay (``refresh`` needs them)."""
    removed = [card_dir(card_id).name] if remove_worktree(card_id) else []
    git(ROOT, "branch", "-D", branch_for(card_id), check=False)
    _clear_scratch(card_id)
    return {"removed": removed}


def _copy_logos(wt: Path, commit: str, slug: str) -> List[str]:
    """Carry the PR's logo PNGs over from its recorded commit (blob, 100644, ≤ 5 MB, PNG)."""
    copied = []
    for d in LOGO_VARIANT_DIRS:
        rel = f"{LOGOS_DIR}/{d}/{slug}.png"
        entry = git(wt, "ls-tree", "-z", commit, "--", rel).stdout.strip("\0")
        meta, _, path = entry.partition("\t")
        parts = meta.split()
        if path != rel or len(parts) != 3 or parts[0] != "100644" or parts[1] != "blob":
            continue
        size = git(wt, "cat-file", "-s", parts[2]).stdout.strip()
        if not size.isdigit() or int(size) > MAX_LOGO_BYTES:
            continue
        git(wt, "checkout", commit, "--", rel)
        target = wt / rel
        with open(str(target), "rb") as f:
            magic = f.read(len(PNG_MAGIC))
        if magic != PNG_MAGIC:
            git(wt, "rm", "--quiet", "--cached", "--", rel)
            target.unlink()
            continue
        copied.append(rel)
    return copied


def cmd_refresh(card_id: str) -> Dict[str, Any]:
    """§4.6: rebuild an open radar PR that fell behind main, never over someone else's push."""
    cid = int(card_id)

    def skip(why: str, **extra: Any) -> Dict[str, Any]:
        return {"card_id": cid, "refreshed": False, "why": why, **extra}

    try:
        rec = read_json(published_path(card_id), "published record")
        board, claim = load_board(card_id), load_claim(card_id)
    except StepError:
        return skip("no_record")
    if not (isinstance(rec, dict) and rec.get("card_id") == cid and rec.get("dry_run") is False
            and isinstance(rec.get("pr_url"), str) and PR_URL_RE.fullmatch(rec["pr_url"])
            and isinstance(rec.get("commit"), str) and SHA.fullmatch(rec["commit"])
            and rec.get("slug") == board["slug"]):
        return skip("no_record")
    recorded = rec["commit"]
    branch = branch_for(card_id)
    try:
        open_urls = [p["url"] for p in trusted_prs(card_id) if p["state"] == "OPEN"]
        if rec["pr_url"] not in open_urls:
            return skip("not_open")
        if remote_branch_sha(branch) != recorded:
            return skip("pushed_by_someone")
        git(ROOT, "fetch", "--quiet", "origin", "main", f"refs/heads/{branch}", reason="env_error")
        if git(ROOT, "merge-base", "--is-ancestor", "refs/remotes/origin/main", recorded,
               check=False).returncode == 0:
            return skip("up_to_date")
        remove_worktree(card_id)
        git(ROOT, "branch", "-D", branch, check=False)
        wt = card_dir(card_id)
        git(ROOT, "worktree", "add", "--no-track", "-B", branch, str(wt), "refs/remotes/origin/main")
        wt = existing_worktree(card_id)
        if (board["ats"], board["token"].lower()) in tracked_pairs(wt):
            return skip("now_tracked")
        if slug_taken(wt, board["slug"], board["enum_member"]):
            return skip("slug_taken")
        scout, _ = load_scout(card_id)
        composed = compose_into(wt, card_id, board, claim, scout)
        logos = _copy_logos(wt, recorded, board["slug"])
        current_head(wt)
        stage_and_check(wt, board["slug"])
        git(wt, "commit", "--no-verify", "--quiet", "-m", pr_title(board))
        commit = _match(SHA, git(wt, "rev-parse", "HEAD").stdout.strip(), "commit")
        push_leased(wt, branch, recorded)
        rec.update(commit=commit, refreshed_at=dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat())
        write_json(published_path(card_id), rec)
        return {"card_id": cid, "refreshed": True, "why": "rebuilt", "commit": commit,
                "down_revision": composed["down_revision"], "logos": logos}
    finally:
        remove_worktree(card_id)
        git(ROOT, "branch", "-D", branch, check=False)
        _clear_scratch(card_id)


# ---- CLI ---------------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pr_step.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def card(name: str) -> argparse.ArgumentParser:
        sp = sub.add_parser(name)
        sp.add_argument("--card-id", required=True)
        return sp

    for name in ("worktree", "verify-board", "compose", "check-head", "cleanup", "refresh"):
        card(name)
    s = card("logo-fetch")
    s.add_argument("--name", required=True, choices=LOGO_NAMES)
    s = card("logo-normalize")
    s.add_argument("--name", required=True, choices=LOGO_NAMES)
    s.add_argument("--remove-white", action="store_true")
    s = card("logo-tile")
    s.add_argument("--variant", required=True, choices=("icon", "wordmark", "lockup"))
    s.add_argument("--bg", required=True)
    s.add_argument("--knockout", required=True, choices=("white", "black", "none"))
    s = card("publish")
    s.add_argument("--draft", action="store_true")
    s.add_argument("--dry-run", action="store_true")
    return p


def emit(payload: Dict[str, Any]) -> None:
    print(json.dumps({**payload, **time_fields()}, sort_keys=True, default=str), flush=True)


def dispatch(a: argparse.Namespace) -> Dict[str, Any]:
    cid = a.card_id
    if a.cmd == "worktree":
        return cmd_worktree(cid)
    if a.cmd == "verify-board":
        return cmd_verify_board(cid)
    if a.cmd == "compose":
        return cmd_compose(cid)
    if a.cmd == "check-head":
        return cmd_check_head(cid)
    if a.cmd == "logo-fetch":
        return cmd_logo_fetch(cid, a.name)
    if a.cmd == "logo-normalize":
        return cmd_logo_normalize(cid, a.name, a.remove_white)
    if a.cmd == "logo-tile":
        return cmd_logo_tile(cid, a.variant, a.bg, a.knockout)
    if a.cmd == "publish":
        return cmd_publish(cid, a.draft, a.dry_run)
    if a.cmd == "cleanup":
        return cmd_cleanup(cid)
    if a.cmd == "refresh":
        return cmd_refresh(cid)
    raise StepError(f"unknown command {a.cmd}")  # pragma: no cover - argparse rejects it


def main(argv: Optional[Sequence[str]] = None) -> int:
    a = build_parser().parse_args(argv)
    extra: Dict[str, Any] = {}
    try:
        _match(CARD_ID, a.card_id, "card id")
        if a.cmd == "refresh":
            extra = {"card_id": int(a.card_id), "refreshed": False, "why": "error"}
        emit(dispatch(a))
        return 0
    except Stop as s:
        emit(s.payload)
        return 3
    except StepError as e:
        print(f"pr_step {a.cmd}: {e}", file=sys.stderr, flush=True)
        emit({**extra, "error": str(e), "report_reason": e.reason})
        return 1
    except Exception as e:  # noqa: BLE001 - never a traceback to the session; report and retry
        where = log_unexpected(a.cmd, getattr(a, "card_id", None))
        print(f"pr_step {a.cmd}: unexpected {type(e).__name__} (traceback in {where})", file=sys.stderr, flush=True)
        emit({**extra, "error": f"unexpected {type(e).__name__}", "report_reason": "other"})
        return 1


ERROR_LOG = "pr_step-errors.log"


def log_unexpected(cmd: str, card_id: Any) -> str:
    """Append the current traceback to ``$STATE_DIR/pr_step-errors.log`` (mode 0600) and return
    its path. The traceback can quote untrusted text, so it goes to this file for the owner,
    never to the session's stdout/stderr. Never raises: a failed write must not mask the error."""
    path = state_dir() / ERROR_LOG
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a") as f:
            stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            f.write(f"--- {stamp} pr_step {cmd} card {card_id}\n{traceback.format_exc()}\n")
    except OSError:
        return "(error log not writable)"
    return str(path)


if __name__ == "__main__":
    sys.exit(main())
