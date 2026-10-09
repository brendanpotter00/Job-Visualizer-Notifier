"""``radar.py pr-*``: the add-company PR queue, loop side (saved-pr/PLAN.md §4.2, §4.4).

The backend keeps one PR request per Saved card (``launch_radar_pr_requests``). These
commands move it; ``pr_step.py`` (a separate, stdlib-only program) does the git and gh
work. Nothing here pushes, opens or merges a PR.

  pr-next              claim the oldest queued request (time check, then preflight)
  pr-check --card-id N before publish: is the card still saved? (records cancelled if not)
  pr-report --card-id N --outcome O [--reason R]
                       record the outcome; ``open`` reads the URL from
                       ``.launch-radar-pr/published/<N>.json``, never from the command line
  pr-refresh           rebuild every open radar PR that fell behind main (runs
                       ``pr_step.py refresh`` as a child with a scrubbed env)
  pr-requeue --card-id N   interactive only: put a finished request back in the queue
  pr-status [--status S]   interactive only: the queue as a table

Files (repo root, gitignored): ``.launch-radar-pr/claims/<id>.json`` (written here),
``scout/<id>.json`` (the session), ``work/<id>/`` and ``published/<id>.json``
(``pr_step.py``). A new claim clears the card's scout, published and work files left
by an earlier attempt.

The clock (§4.4). The wrapper writes ``<start_epoch> <run_id>`` to
``$STATE_DIR/session_started_at`` and starts the session with ``LAUNCH_RADAR_RUN_ID``.
The clock applies only when that env var is set AND equals the file's run id, so an
interactive run (no env var) or a leftover file from another run never refuses work.
``pr-next`` claims nothing, and ``pr-refresh`` starts no refresh, once
``START_CUTOFF_S`` (55 min) have passed; the wrapper kills the session at 90 min.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import httpx

from .backend_client import BackendClient, BackendError, PrRequestNotFound

EXIT_OK = 0
EXIT_ERROR = 1

ROOT = Path(__file__).resolve().parents[2]
REPO = "brendanpotter00/Job-Visualizer-Notifier"
PR_DIR_NAME = ".launch-radar-pr"
PR_STEP = Path("scripts") / "launch_radar" / "pr_step.py"

# SEAM: the same pattern as the DB CHECK ck_launch_radar_pr_requests_pr_url, the
# backend's LAUNCH_RADAR_PR_URL_PATTERN, pr_step.py and format.ts. Always fullmatch.
PR_URL_PATTERN = r"^https://github\.com/brendanpotter00/Job-Visualizer-Notifier/pull/[0-9]+$"
PR_URL_RE = re.compile(PR_URL_PATTERN)
CARD_ID_RE = re.compile(r"[1-9][0-9]{0,9}")
RUN_ID_RE = re.compile(r"[0-9]{1,12}-[0-9]{1,10}")

KILL_AFTER_S = 5400  # wrapper.sh TOTAL_TIMEOUT_SECS: the 90-minute hard limit
START_CUTOFF_S = 3300  # 55 min: no new claim / refresh after this (D15)
SESSION_FILE = "session_started_at"
LOGO_VENV = "logo-venv"

PR_STATUSES = ("queued", "in_progress", "open", "failed", "no_board", "already_tracked", "cancelled")
# What the session may report (``cancelled`` is recorded by pr-check itself).
REPORT_OUTCOMES = ("open", "failed", "no_board", "already_tracked")
NO_BOARD_REASONS = ("board_not_found", "board_empty", "unsupported_ats")
FAILED_REASONS = ("unsafe_value", "pr_closed", "step_refused", "multi_head", "git_error", "gh_error",
                  "timeout", "other", "env_error")
# PrReason minus ``abandoned`` (set only by the backend's stale recovery).
REPORT_REASONS = NO_BOARD_REASONS + FAILED_REASONS

# Only these reach a child process: no backend URL, internal key or Parallel key.
SCRUBBED_ENV_KEYS = ("PATH", "HOME", "LANG", "LAUNCH_RADAR_STATE_DIR", "LAUNCH_RADAR_RUN_ID")
# Every git call: no hooks, no fsmonitor command, no pager (same as pr_step.py).
GIT = ("git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "core.pager=cat")
PREFLIGHT_TIMEOUT_S = 60
REFRESH_TIMEOUT_S = 900
REFRESH_LIST_LIMIT = 500

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def _default_runner(argv: Sequence[str], *, env: Mapping[str, str], cwd: Path,
                    timeout: float) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(list(argv), env=dict(env), cwd=str(cwd), text=True, capture_output=True,
                          timeout=timeout, stdin=subprocess.DEVNULL)


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _stdout(obj: Any) -> None:
    print(json.dumps(obj, default=str), flush=True)


@dataclass
class PrEnv:
    """Everything the pr-* commands touch, so tests can swap each one."""

    backend: BackendClient
    state_dir: Path
    root: Path = ROOT
    environ: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    runner: Runner = _default_runner
    now: Callable[[], float] = time.time
    out: Callable[[Any], None] = _stdout
    err: Callable[[str], None] = _stderr

    @property
    def pr_dir(self) -> Path:
        return self.root / PR_DIR_NAME


# ---- validation and files ---------------------------------------------------------------
def valid_card_id(value: Any) -> int:
    """A card id as an int, or ValueError. Accepts an int or its decimal string."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"bad card id: {value!r}")
    text = str(value)
    if not CARD_ID_RE.fullmatch(text):
        raise ValueError(f"bad card id: {value!r}")
    return int(text)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True, default=str)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _remove(path: Path) -> None:
    """Remove a file, a symlink or a directory tree (never follows a symlink)."""
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def clear_attempt_files(env: PrEnv, card_id: int) -> None:
    """A new claim starts clean: the earlier attempt's scout reply, published record
    and work dir are removed (an ``open`` request is never claimed, so none of them
    belongs to a live PR)."""
    d = env.pr_dir
    for p in (d / "scout" / f"{card_id}.json", d / "published" / f"{card_id}.json", d / "work" / str(card_id)):
        _remove(p)


# ---- the clock (§4.4) ------------------------------------------------------------------------
def session_elapsed_s(env: PrEnv) -> float | None:
    """Seconds since the wrapper started this session, or None when the clock does not
    apply (no ``LAUNCH_RADAR_RUN_ID``, no file, or a file from another run)."""
    run_id = env.environ.get("LAUNCH_RADAR_RUN_ID") or ""
    if not RUN_ID_RE.fullmatch(run_id):
        return None
    try:
        text = (env.state_dir / SESSION_FILE).read_text()
    except OSError:
        return None
    parts = text.split()
    if len(parts) != 2 or parts[1] != run_id or not parts[0].isdigit():
        return None
    return max(0.0, env.now() - int(parts[0]))


def time_left_s(env: PrEnv) -> int | None:
    """Seconds to the wrapper's 90-minute kill, or None without the clock."""
    elapsed = session_elapsed_s(env)
    return None if elapsed is None else max(0, int(KILL_AFTER_S - elapsed))


def past_cutoff(env: PrEnv) -> bool:
    elapsed = session_elapsed_s(env)
    return elapsed is not None and elapsed >= START_CUTOFF_S


# ---- child processes ------------------------------------------------------------------------
def scrubbed_env(env: PrEnv) -> dict[str, str]:
    """The only environment a child gets (§4.2): PATH, HOME, LANG, the state dir and
    the run id. ``LAUNCH_RADAR_STATE_DIR`` is always the resolved state dir, so the
    child reads the same ``session_started_at`` as this process."""
    out = {k: env.environ[k] for k in SCRUBBED_ENV_KEYS if env.environ.get(k)}
    out["LAUNCH_RADAR_STATE_DIR"] = str(env.state_dir)
    return out


def preflight(env: PrEnv) -> str | None:
    """Fixed-argv checks that the server can open a PR; the first failing check's
    name, or None when all pass. Nothing is claimed after a failure (§4.2)."""
    child_env = {**scrubbed_env(env), "GIT_TERMINAL_PROMPT": "0", "GH_PROMPT_DISABLED": "1"}
    venv_python = env.state_dir / LOGO_VENV / "bin" / "python"

    def ok(p: "subprocess.CompletedProcess[str]") -> bool:
        return p.returncode == 0

    def push_ok(p: "subprocess.CompletedProcess[str]") -> bool:
        return p.returncode == 0 and p.stdout.strip() == "true"

    checks: list[tuple[str, list[str], Callable[["subprocess.CompletedProcess[str]"], bool]]] = [
        ("gh_auth", ["gh", "auth", "status"], ok),
        ("gh_push", ["gh", "api", f"repos/{REPO}", "--jq", ".permissions.push"], push_ok),
        ("git_remote", [*GIT, "-C", str(env.root), "ls-remote", "--exit-code", "origin", "refs/heads/main"], ok),
        ("logo_venv", [str(venv_python), "-I", "-c", "import PIL, cairosvg"], ok),
    ]
    for name, argv, passed in checks:
        if name == "logo_venv" and not venv_python.is_file():
            return name
        try:
            proc = env.runner(argv, env=child_env, cwd=env.root, timeout=PREFLIGHT_TIMEOUT_S)
        except (OSError, subprocess.SubprocessError):
            return name
        if not passed(proc):
            return name
    return None


def _preflight_or_fail(env: PrEnv) -> bool:
    failed = preflight(env)
    if failed is not None:
        env.err(json.dumps({"preflight": "failed", "check": failed}))
        return False
    return True


# ---- commands ---------------------------------------------------------------------------------
def pr_next(env: PrEnv) -> int:
    """Time check, preflight, then claim. Exit 1 on a failed preflight or a backend error."""
    if past_cutoff(env):
        env.out({"claimed": False, "reason": "time", "time_left_s": time_left_s(env)})
        return EXIT_OK
    if not _preflight_or_fail(env):
        return EXIT_ERROR
    claim = env.backend.pr_next()
    if claim is None:
        env.out({"claimed": False, "reason": "empty", "time_left_s": time_left_s(env)})
        return EXIT_OK
    try:
        card_id = valid_card_id(claim.get("card_id") if isinstance(claim, dict) else None)
    except ValueError as e:
        env.err(f"pr-next: the backend returned a malformed claim ({e})")
        return EXIT_ERROR
    clear_attempt_files(env, card_id)
    _write_json(env.pr_dir / "claims" / f"{card_id}.json", claim)
    env.out({"claimed": True, **claim, "time_left_s": time_left_s(env)})
    return EXIT_OK


def pr_check(env: PrEnv, card_id: int) -> int:
    """Before publish: proceed only while the request is ``in_progress`` and the card is
    still saved. An unsaved card's request is recorded ``cancelled`` (D17). A deleted
    card is not an error."""
    for _ in range(2):  # a second look only after a 409 race on the cancel
        try:
            row = env.backend.pr_get(card_id)
        except PrRequestNotFound:
            env.out({"proceed": False, "why": "deleted"})
            return EXIT_OK
        status, card_status = row.get("status"), row.get("card_status")
        if status != "in_progress":
            env.out({"proceed": False, "why": "not_in_progress", "status": status})
            return EXIT_OK
        if card_status == "saved":
            env.out({"proceed": True})
            return EXIT_OK
        try:
            env.backend.pr_result(card_id, "cancelled")
        except PrRequestNotFound:
            env.out({"proceed": False, "why": "deleted"})
            return EXIT_OK
        except BackendError as e:
            if e.status == 409:  # re-saved (or changed) between the read and the cancel
                continue
            raise
        env.out({"proceed": False, "why": "unsaved"})
        return EXIT_OK
    env.err(f"pr-check: card {card_id} kept changing; not proceeding")
    env.out({"proceed": False, "why": "conflict"})
    return EXIT_OK


def published_pr_url(env: PrEnv, card_id: int) -> str:
    """The PR URL ``pr_step.py`` recorded for this card, or ValueError. The file must say
    it is this card's, not a dry run, and hold this repository's PR URL."""
    path = env.pr_dir / "published" / f"{card_id}.json"
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"no published record for card {card_id}")
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        raise ValueError(f"unreadable published record for card {card_id}") from e
    if not isinstance(data, dict):
        raise ValueError("published record is not an object")
    cid = data.get("card_id")
    if isinstance(cid, bool) or cid != card_id:
        raise ValueError("published record is for another card")
    if data.get("dry_run") is not False:
        raise ValueError("published record is a dry run")
    url = data.get("pr_url")
    if not isinstance(url, str) or not PR_URL_RE.fullmatch(url):
        raise ValueError("published record has no valid pr_url")
    return url


def reason_problem(outcome: str, reason: str | None) -> str | None:
    """The backend's outcome/reason rule (models.LaunchRadarPrResult), checked first so a
    bad pair never reaches it."""
    if outcome == "failed":
        allowed: tuple[str, ...] = FAILED_REASONS
    elif outcome == "no_board":
        allowed = NO_BOARD_REASONS
    else:
        allowed = ()
    if allowed and reason is None:
        return f"--outcome {outcome} needs --reason"
    if reason is not None and reason not in allowed:
        return f"--reason {reason} is not allowed with --outcome {outcome}"
    return None


def pr_report(env: PrEnv, card_id: int, outcome: str, reason: str | None) -> int:
    problem = reason_problem(outcome, reason)
    if problem:
        env.err(f"pr-report: {problem}")
        return EXIT_ERROR
    pr_url = None
    if outcome == "open":
        try:
            pr_url = published_pr_url(env, card_id)
        except ValueError as e:
            env.err(f"pr-report: {e}")
            return EXIT_ERROR
    try:
        row = env.backend.pr_result(card_id, outcome, pr_url=pr_url, reason=reason)
    except PrRequestNotFound:
        # The owner deleted the card mid-run: harmless (D11), not an error.
        env.out({"card_deleted": True, "pr_url": pr_url})
        return EXIT_OK
    env.out(row)
    return EXIT_OK


def _child_result(card_id: int, proc: "subprocess.CompletedProcess[str]") -> dict[str, Any]:
    last = next((ln for ln in reversed((proc.stdout or "").splitlines()) if ln.strip()), "")
    try:
        data = json.loads(last)
    except ValueError:
        data = None
    if proc.returncode != 0:
        out: dict[str, Any] = {"card_id": card_id, "refreshed": False, "why": "error"}
        if isinstance(data, dict) and data.get("report_reason") in FAILED_REASONS:
            out["report_reason"] = data["report_reason"]
        return out
    if not isinstance(data, dict) or data.get("card_id") != card_id or not isinstance(data.get("refreshed"), bool):
        return {"card_id": card_id, "refreshed": False, "why": "bad_output"}
    why = data.get("why")
    return {"card_id": card_id, "refreshed": data["refreshed"],
            "why": why if isinstance(why, str) and re.fullmatch(r"[a-z_]{1,40}", why) else None}


def pr_refresh(env: PrEnv) -> int:
    """§4.6: rebuild every open radar PR that fell behind main. Each card runs
    ``pr_step.py refresh --card-id N`` (fixed argv, scrubbed env). A failed refresh is
    reported in the summary, not as an error: exit 1 only on a failed preflight or a
    backend error."""
    summary: dict[str, Any] = {"open": 0, "refreshed": 0, "results": [], "stopped": None}
    if past_cutoff(env):
        summary.update(stopped="time", time_left_s=time_left_s(env))
        env.out(summary)
        return EXIT_OK
    if not _preflight_or_fail(env):
        return EXIT_ERROR
    rows = env.backend.pr_requests(statuses=("open",), limit=REFRESH_LIST_LIMIT)
    ids: list[int] = []
    for row in rows:  # oldest first (the backend orders by requested_at)
        try:
            ids.append(valid_card_id(row.get("card_id")))
        except ValueError:
            env.err(f"pr-refresh: skipping a malformed row: {row.get('card_id')!r}")
    summary["open"] = len(ids)
    child_env = scrubbed_env(env)
    pr_step = env.root / PR_STEP
    for card_id in ids:
        if past_cutoff(env):
            summary["stopped"] = "time"
            break
        argv = [sys.executable, "-I", str(pr_step), "refresh", "--card-id", str(card_id)]
        try:
            proc = env.runner(argv, env=child_env, cwd=env.root, timeout=REFRESH_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            result: dict[str, Any] = {"card_id": card_id, "refreshed": False, "why": "timeout"}
        except (OSError, subprocess.SubprocessError) as e:
            env.err(f"pr-refresh: card {card_id}: {type(e).__name__}")
            result = {"card_id": card_id, "refreshed": False, "why": "error"}
        else:
            result = _child_result(card_id, proc)
            if proc.returncode != 0 and proc.stderr:
                env.err(f"pr-refresh: card {card_id}: {proc.stderr.strip()[-300:]}")
        summary["results"].append(result)
        summary["refreshed"] += 1 if result["refreshed"] else 0
    summary["time_left_s"] = time_left_s(env)
    env.out(summary)
    return EXIT_OK


def pr_requeue(env: PrEnv, card_id: int) -> int:
    try:
        row = env.backend.pr_requeue(card_id)
    except PrRequestNotFound:
        env.err(f"pr-requeue: no PR request for card {card_id} (or the card is deleted)")
        return EXIT_ERROR
    except BackendError as e:
        if e.status != 409:
            raise
        env.err(f"pr-requeue: refused: {e.detail}")
        return EXIT_ERROR
    env.out(row)
    return EXIT_OK


_PRINTABLE = re.compile(r"[^\x20-\x7e -￿]")
_STATUS_COLUMNS = ("card_id", "status", "attempts", "pr", "last_reason", "requested_at", "retry_after",
                   "domain", "company")


def _cell(value: Any, width: int = 40) -> str:
    text = "-" if value is None or value == "" else str(value)
    text = _PRINTABLE.sub("?", text)  # card text came from the web: no terminal escapes
    return text if len(text) <= width else text[: width - 1] + "…"


def pr_status(env: PrEnv, statuses: Sequence[str]) -> int:
    rows = env.backend.pr_requests(statuses=statuses, limit=REFRESH_LIST_LIMIT)
    table = [list(_STATUS_COLUMNS)]
    for r in rows:
        pr = r.get("pr_url") if r.get("pr_url") else None
        table.append([_cell(r.get("card_id")), _cell(r.get("status")), _cell(r.get("attempts")), _cell(pr, 70),
                      _cell(r.get("last_reason")), _cell(r.get("requested_at"), 25),
                      _cell(r.get("retry_after"), 25), _cell(r.get("domain")), _cell(r.get("company"))])
    widths = [max(len(row[i]) for row in table) for i in range(len(_STATUS_COLUMNS))]
    for row in table:
        print("  ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip(), flush=True)
    print(f"{len(rows)} request(s)", flush=True)
    return EXIT_OK


def dispatch(cmd: str, args: Any, env: PrEnv) -> int:
    """Run one pr-* command. A backend or transport error is exit 1."""
    try:
        if cmd == "pr-next":
            return pr_next(env)
        if cmd == "pr-check":
            return pr_check(env, args.card_id)
        if cmd == "pr-report":
            return pr_report(env, args.card_id, args.outcome, args.reason)
        if cmd == "pr-refresh":
            return pr_refresh(env)
        if cmd == "pr-requeue":
            return pr_requeue(env, args.card_id)
        if cmd == "pr-status":
            return pr_status(env, args.status or ())
    except BackendError as e:
        env.err(f"{cmd}: backend error: {e}")
        return EXIT_ERROR
    except httpx.HTTPError as e:
        env.err(f"{cmd}: backend unreachable: {type(e).__name__}")
        return EXIT_ERROR
    raise AssertionError(f"unhandled command {cmd}")
