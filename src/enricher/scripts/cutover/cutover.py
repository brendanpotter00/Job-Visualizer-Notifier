#!/usr/bin/env python3
"""Move the live enricher from the retired job-enricher clone to a JVN clone.

The cutover changes WHERE prod's code comes from, never WHAT runs: the new
prod is a JVN clone checked out at the commit whose ``src/enricher`` tree is
byte-identical to the old prod's tree (today tag ``enricher-prod-eeff1c9``).

Standard library only (plus ``scripts/lib/park_worker.py``), Python >= 3.11.
``cutover.sh`` runs it under the old prod's own interpreter with ``-I``.

Modes (exit 0 done/no-op, 10 deferred, 20 failed before any swap, 30 rolled
back, 2 usage)::

    cutover.sh --preflight [--jvn-repo PATH] [--json]   read-only report
    cutover.sh --rehearse --scratch DIR [--jvn-repo PATH]
    cutover.sh --run                                     what the watcher calls; resumable
    cutover.sh --status                                  print the state file

Phases of ``--run`` (state in ``$CUTOVER_STATE_DIR/state.json``):

A prepare  (worker still running)  mirror, derive the ref, clone, ``uv sync``
B park     claim the tick lock at idle, THEN ``launchctl unload``
C copy     sqlite online backup + checks, untracked state, health equality
D swap     roles, plist rewrite (the switch point), ``launchctl load``
E verify   the first tick in the new prod closes ``ok`` and does the work
F retire   markers, bundle, README banner, archive the old repo, text

Any failure before the plist write restores the old prod exactly as found;
any failure after it rolls back (``ROLLED_BACK``, exit 30). Runbook:
``scripts/cutover/README.md``. Design: ``docs/implementations/
enricher-consolidation/PLAN.md`` §4 in the JVN repo.
"""

from __future__ import annotations

import sys

if sys.version_info < (3, 11):  # pragma: no cover - guarded before any import below
    print("[cutover] needs Python >= 3.11", file=sys.stderr)
    sys.exit(20)

import argparse
import copy
import hashlib
import json
import os
import plistlib
import re
import shutil
import signal
import sqlite3
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

_HERE = Path(__file__).resolve().parent
_LIB = _HERE.parent / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import park_worker  # noqa: E402  (scripts/lib, stdlib-only)

# --------------------------------------------------------------------------- constants
EXIT_DONE = 0
EXIT_DEFERRED = 10
EXIT_FAILED = 20
EXIT_ROLLED_BACK = 30
EXIT_USAGE = 2

ENRICHER_LABEL = "com.bp.job-enricher"
WATCHER_LABEL = "com.bp.jvn-enricher-cutover"
WRAPPER_REL = "scripts/enrich_tick_wrapper.sh"
CUTOVER_PY_IN_MAIN = "src/enricher/scripts/cutover/cutover.py"
TAG_PATTERN = "refs/tags/enricher-prod-*"
ENRICHER_SUBDIR = "src/enricher"

OWNED_MARKER = ".cutover-owned"      # the only dirs the cutover may delete carry this
SWAPPED_MARKER = ".cutover-swapped"  # replaces OWNED_MARKER once prod runs here
RETIRED_NOTE_HEADER = "# RETIRED checkout"

TERMINAL_PHASES = ("DONE", "FAILED", "ROLLED_BACK")
PRE_SWAP_PHASES = ("PENDING", "PREPARED", "PARKED", "COPIED")

#: Untracked paths that are regenerated, never copied, into the new prod.
REGENERATE_PREFIXES = (
    ".venv/", ".pytest_cache/", "data/chunks/",
    "dashboard/node_modules/", "dashboard/dist/", "dashboard/.vite/", "dashboard/coverage/",
)
REGENERATE_EXACT = frozenset({
    ".checkout-role", "data/.tick.lock", "data/.backfill.lock", "data/.subcategory-push.lock",
})
_LOCK_LEFTOVER_RE = re.compile(r"^data/\.(tick|backfill|subcategory-push)\.lock\.")
_DB_RE = re.compile(r"^data/.+\.db$")
_DB_SIDECAR_RE = re.compile(r"^data/.+\.db-(wal|shm|journal)$")

#: Health JSON keys that differ between two reads of the same data.
VOLATILE_KEY_SUFFIXES = ("_age_s", "_at")
VOLATILE_KEYS = frozenset({"now"})

#: Environment variables a subprocess must never inherit from whoever ran us.
_STRIP_ENV = (
    "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP",
    "CONDA_PREFIX", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
)


# --------------------------------------------------------------------------- errors
class Defer(Exception):
    """Transient: put everything back as found and retry on the next fire (exit 10)."""


class Refuse(Exception):
    """Terminal before any swap: put everything back as found and stop (exit 20)."""


class VerifyFailure(Exception):
    """A post-swap check failed: roll back (exit 30)."""


class PlistRewriteError(ValueError):
    pass


# --------------------------------------------------------------------------- logging
class _LogSink:
    stream = sys.stdout
    file: Path | None = None


LOG = _LogSink()


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg: str) -> None:
    line = f"[cutover {now_iso()}] {msg}"
    print(line, file=LOG.stream, flush=True)
    if LOG.file is not None:
        try:
            with open(LOG.file, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass


# --------------------------------------------------------------------------- config
def _env_float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name, "")
    try:
        return float(raw) if raw.strip() else default
    except ValueError:
        return default


@dataclass
class Config:
    home: Path
    old_prod: Path
    new_prod: Path
    old_dev: Path
    state_dir: Path
    jvn_remote_url: str
    enricher_plist: Path
    send_sh: Path
    uv_bin: str
    launchctl: str
    gh_bin: str
    git_bin: str
    plutil_bin: str
    lsof_bin: str
    launchd_domain: str
    old_repo_slug: str | None
    park_budget_s: float
    first_tick_start_s: float
    first_tick_close_s: float
    first_tick_hard_cap_s: float
    poll_s: float
    lock_poll_s: float
    wrapper_exit_s: float
    rollback_park_budget_s: float
    progress_window_s: float
    defer_alert_after: int
    net_timeout_s: float
    uv_timeout_s: float
    health_timeout_s: float

    @property
    def new_enricher(self) -> Path:
        return self.new_prod / ENRICHER_SUBDIR

    @property
    def state_file(self) -> Path:
        return self.state_dir / "state.json"

    @property
    def mirror(self) -> Path:
        return self.state_dir / "jvn.git"

    @property
    def plist_orig(self) -> Path:
        return self.state_dir / "com.bp.job-enricher.plist.orig"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Config":
        env = os.environ if env is None else env
        home = Path(env.get("HOME") or str(Path.home()))
        personal = home / "developer" / "personal"
        f = lambda name, default: _env_float(env, name, default)  # noqa: E731
        return cls(
            home=home,
            old_prod=Path(env.get("CUTOVER_OLD_PROD") or personal / "app"),
            new_prod=Path(env.get("CUTOVER_NEW_PROD") or personal / "enricher-prod"),
            old_dev=Path(env.get("CUTOVER_OLD_DEV") or personal / "job-enricher"),
            state_dir=Path(env.get("CUTOVER_STATE_DIR")
                           or home / "Library" / "Application Support" / "jvn-enricher-cutover"),
            jvn_remote_url=env.get("JVN_REMOTE_URL")
            or "https://github.com/brendanpotter00/Job-Visualizer-Notifier.git",
            enricher_plist=Path(env.get("CUTOVER_ENRICHER_PLIST")
                                or home / "Library" / "LaunchAgents" / f"{ENRICHER_LABEL}.plist"),
            send_sh=Path(env.get("CUTOVER_SEND_SH")
                         or home / ".claude" / "skills" / "message-brendan" / "send.sh"),
            uv_bin=env.get("UV_BIN") or "/opt/homebrew/bin/uv",
            launchctl=env.get("LAUNCHCTL") or "launchctl",
            gh_bin=env.get("GH_BIN") or "gh",
            git_bin=env.get("CUTOVER_GIT_BIN") or "git",
            plutil_bin=env.get("CUTOVER_PLUTIL_BIN") or "/usr/bin/plutil",
            lsof_bin=env.get("CUTOVER_LSOF_BIN") or "/usr/sbin/lsof",
            launchd_domain=env.get("CUTOVER_LAUNCHD_DOMAIN") or f"gui/{os.getuid()}",
            old_repo_slug=env.get("CUTOVER_OLD_REPO_SLUG") or None,
            park_budget_s=f("CUTOVER_PARK_BUDGET_S", 14400),
            first_tick_start_s=f("CUTOVER_FIRST_TICK_START_S", 900),
            first_tick_close_s=f("CUTOVER_FIRST_TICK_CLOSE_S", 18000),
            first_tick_hard_cap_s=f("CUTOVER_FIRST_TICK_HARD_CAP_S", 86400),
            poll_s=f("CUTOVER_POLL_S", 5),
            lock_poll_s=f("CUTOVER_LOCK_POLL_S", 1),
            wrapper_exit_s=f("CUTOVER_WRAPPER_EXIT_S", 120),
            rollback_park_budget_s=f("CUTOVER_ROLLBACK_PARK_BUDGET_S", 1800),
            progress_window_s=f("CUTOVER_PROGRESS_WINDOW_S", 1800),
            defer_alert_after=int(f("CUTOVER_DEFER_ALERT_AFTER", 24)),
            net_timeout_s=f("CUTOVER_NET_TIMEOUT_S", 600),
            uv_timeout_s=f("CUTOVER_UV_TIMEOUT_S", 1800),
            health_timeout_s=f("CUTOVER_HEALTH_TIMEOUT_S", 600),
        )


# --------------------------------------------------------------------------- subprocess
def child_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _STRIP_ENV}
    env.update({
        "GIT_TERMINAL_PROMPT": "0",          # never hang on a credential prompt
        "GIT_OPTIONAL_LOCKS": "0",           # `git status` must not rewrite the index
        "GIT_HTTP_LOW_SPEED_LIMIT": "1000",  # a stalled transfer aborts ...
        "GIT_HTTP_LOW_SPEED_TIME": "30",     # ... after 30 s below 1 KB/s
    })
    if extra:
        env.update(extra)
    return env


def run(cmd: list[str], *, cwd: Path | str | None = None, timeout: float | None = 120,
        env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run without a shell, capture text output, never raise on a non-zero exit.
    A timeout comes back as returncode 124; a missing binary as 127."""
    cmd = [str(c) for c in cmd]
    try:
        return subprocess.run(cmd, cwd=None if cwd is None else str(cwd), timeout=timeout,
                              env=dict(env) if env is not None else child_env(),
                              capture_output=True, text=True, check=False)
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return subprocess.CompletedProcess(cmd, 124, out, f"timed out after {timeout}s")
    except (FileNotFoundError, PermissionError) as exc:
        return subprocess.CompletedProcess(cmd, 127, "", str(exc))


def tail(text: str, n: int = 15) -> str:
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    return "\n".join(lines[-n:])


def git(cfg: Config, repo: Path | str, *args: str, timeout: float | None = 120,
        env_extra: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return run([cfg.git_bin, "-C", str(repo), *args], timeout=timeout, env=child_env(env_extra))


def git_ok(cfg: Config, repo: Path | str, *args: str, timeout: float | None = 120) -> str:
    cp = git(cfg, repo, *args, timeout=timeout)
    if cp.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])} failed ({cp.returncode}): {tail(cp.stderr, 5)}")
    return cp.stdout


# --------------------------------------------------------------------------- files
def sha256_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_write_bytes(path: Path, data: bytes, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    if mode is not None:
        os.chmod(tmp, mode)
    os.replace(tmp, path)


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError):
        return None


def same_path(a: Path | str, b: Path | str) -> bool:
    if os.path.normpath(str(a)) == os.path.normpath(str(b)):
        return True
    try:
        return os.path.realpath(str(a)) == os.path.realpath(str(b))
    except OSError:
        return False


# --------------------------------------------------------------------------- git: ref derivation
@dataclass
class RefMatch:
    ref: str          # the tag name, or the commit sha when found by the history walk
    commit: str
    tree: str
    source: str       # "tag" | "history"


def _batch_trees(cfg: Config, repo: Path, revs: list[str]) -> dict[str, str]:
    """``{rev: tree sha of rev:src/enricher}`` for every rev that has one."""
    if not revs:
        return {}
    query = "".join(f"{r}:{ENRICHER_SUBDIR}\n" for r in revs)
    cp = subprocess.run([cfg.git_bin, "-C", str(repo), "cat-file", "--batch-check"],
                        input=query, capture_output=True, text=True, env=child_env(),
                        timeout=300, check=False)
    out: dict[str, str] = {}
    for rev, line in zip(revs, cp.stdout.splitlines()):
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "tree":
            out[rev] = parts[0]
    return out


def derive_ref(cfg: Config, repo: Path, app_tree: str) -> RefMatch | None:
    """The JVN ref whose ``src/enricher`` tree equals ``app_tree``: every
    ``enricher-prod-*`` tag first, then every commit in ``repo``'s history.
    None means no JVN commit carries the code prod runs: refuse."""
    tags = [t for t in git_ok(cfg, repo, "for-each-ref", "--format=%(refname:short)",
                                TAG_PATTERN).split() if t]
    trees = _batch_trees(cfg, repo, sorted(tags))
    for tag in sorted(tags):
        if trees.get(tag) == app_tree:
            commit = git_ok(cfg, repo, "rev-parse", f"{tag}^{{commit}}").strip()
            return RefMatch(tag, commit, app_tree, "tag")
    commits = git_ok(cfg, repo, "rev-list", "--all", timeout=300).split()
    trees = _batch_trees(cfg, repo, commits)
    for c in commits:
        if trees.get(c) == app_tree:
            return RefMatch(c, c, app_tree, "history")
    return None


def main_has_cutover(cfg: Config, repo: Path, ref: str = "main") -> bool:
    return git(cfg, repo, "cat-file", "-e", f"{ref}:{CUTOVER_PY_IN_MAIN}").returncode == 0


def ensure_mirror(cfg: Config) -> Path:
    """Bare mirror of JVN in the state dir, refreshed (main + tags). Network
    failure is transient (Defer)."""
    m = cfg.mirror
    if not (m / "HEAD").exists():
        tmp = cfg.state_dir / f"jvn.git.tmp-{os.getpid()}"
        shutil.rmtree(tmp, ignore_errors=True)
        cp = run([cfg.git_bin, "clone", "--bare", "--quiet", cfg.jvn_remote_url, str(tmp)],
                 timeout=cfg.net_timeout_s)
        if cp.returncode != 0:
            shutil.rmtree(tmp, ignore_errors=True)
            raise Defer(f"cannot reach JVN to build the mirror ({cp.returncode}): {tail(cp.stderr, 3)}")
        os.replace(tmp, m)
    cp = git(cfg, m, "fetch", "--quiet", "--prune", "--tags", "origin",
             "+refs/heads/main:refs/heads/main", timeout=cfg.net_timeout_s)
    if cp.returncode != 0:
        raise Defer(f"cannot fetch JVN main ({cp.returncode}): {tail(cp.stderr, 3)}")
    return m


# --------------------------------------------------------------------------- plist
@dataclass
class PlistInfo:
    label: str | None
    program: str | None
    workdir: str | None
    raw: bytes


def parse_plist(data: bytes) -> PlistInfo:
    d = plistlib.loads(data)
    args = d.get("ProgramArguments") or []
    program = d.get("Program") or (args[0] if args else None)
    return PlistInfo(d.get("Label"), program, d.get("WorkingDirectory"), data)


def read_plist(path: Path) -> PlistInfo | None:
    try:
        return parse_plist(path.read_bytes())
    except (OSError, plistlib.InvalidFileException, ValueError):
        return None


_XML_UNSAFE = set("&<>\"'")


def rewrite_plist_bytes(orig: bytes, old_root: str, new_root: str) -> bytes:
    """``orig`` with the old prod root replaced by ``new_root`` in EXACTLY the
    two places a prod plist names it — ``ProgramArguments[0]``'s prefix and
    ``WorkingDirectory`` — and nothing else (same StartInterval, environment,
    log paths). Raises PlistRewriteError instead of guessing."""
    if orig.startswith(b"bplist"):
        raise PlistRewriteError("binary plist: refusing to rewrite (expected XML)")
    for root in (old_root, new_root):
        if not root.startswith("/") or _XML_UNSAFE & set(root):
            raise PlistRewriteError(f"unsupported path for a plist rewrite: {root!r}")
    old_root = old_root.rstrip("/")
    new_root = new_root.rstrip("/")
    try:
        parsed = plistlib.loads(orig)
    except Exception as exc:  # noqa: BLE001 — any parse failure is a refusal
        raise PlistRewriteError(f"plist does not parse: {exc}") from exc
    old_b = old_root.encode("utf-8")
    raw_hits = orig.count(old_b)
    bounded = re.compile(re.escape(old_b) + rb"(?=[/<])")
    hits = len(bounded.findall(orig))
    if hits != 2 or raw_hits != 2:
        raise PlistRewriteError(
            f"expected exactly 2 occurrences of the old prod path, found {hits} "
            f"(raw substring count {raw_hits})")
    args = list(parsed.get("ProgramArguments") or [])
    if parsed.get("WorkingDirectory") != old_root:
        raise PlistRewriteError("WorkingDirectory is not the old prod path")
    if not args or not str(args[0]).startswith(old_root + "/"):
        raise PlistRewriteError("ProgramArguments[0] is not under the old prod path")
    if "Program" in parsed:
        raise PlistRewriteError("plist sets Program; expected ProgramArguments only")
    new = bounded.sub(new_root.encode("utf-8"), orig)
    expected = copy.deepcopy(parsed)
    expected["WorkingDirectory"] = new_root
    expected["ProgramArguments"][0] = new_root + str(args[0])[len(old_root):]
    if plistlib.loads(new) != expected:
        raise PlistRewriteError("rewritten plist differs beyond the two path values")
    return new


def plutil_lint(cfg: Config, data: bytes) -> tuple[bool, str]:
    try:
        cp = subprocess.run([cfg.plutil_bin, "-lint", "-"], input=data, capture_output=True,
                            timeout=30, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"plutil unavailable: {exc}"
    return cp.returncode == 0, (cp.stdout + cp.stderr).decode("utf-8", "replace").strip()


def plist_where(cfg: Config, info: PlistInfo | None) -> str:
    """``old`` | ``new`` | ``other`` | ``missing`` — where launchd will run prod."""
    if info is None or info.workdir is None:
        return "missing"
    if same_path(info.workdir, cfg.old_prod):
        return "old"
    if same_path(info.workdir, cfg.new_enricher):
        return "new"
    return "other"


# --------------------------------------------------------------------------- launchd
class Launchd:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    def _ctl(self, *args: str, timeout: float = 60) -> subprocess.CompletedProcess[str]:
        return run([self.cfg.launchctl, *args], timeout=timeout)

    def labels(self) -> dict[str, str] | None:
        """``{label: pid-or-'-'}``, or None when ``launchctl list`` fails."""
        cp = self._ctl("list")
        if cp.returncode != 0:
            return None
        out: dict[str, str] = {}
        for line in cp.stdout.splitlines():
            parts = line.split("\t") if "\t" in line else line.split()
            if len(parts) >= 3 and parts[0] != "PID":
                out[parts[2].strip()] = parts[0].strip()
        return out

    def is_loaded(self, label: str = ENRICHER_LABEL) -> bool | None:
        labels = self.labels()
        return None if labels is None else label in labels

    def program(self, label: str = ENRICHER_LABEL) -> str | None:
        cp = self._ctl("print", f"{self.cfg.launchd_domain}/{label}")
        if cp.returncode != 0:
            return None
        m = re.search(r"^\s*program = (.+?)\s*$", cp.stdout, re.M)
        return m.group(1) if m else None

    def load(self, plist: Path) -> subprocess.CompletedProcess[str]:
        return self._ctl("load", str(plist))

    def unload(self, plist: Path) -> subprocess.CompletedProcess[str]:
        return self._ctl("unload", str(plist))

    def wait_loaded(self, want: bool, budget_s: float = 30, label: str = ENRICHER_LABEL) -> bool:
        clock = park_worker.WallClock(1.0)
        dl = park_worker.Deadline(clock, budget_s)
        while True:
            if self.is_loaded(label) is want:
                return True
            if dl.expired():
                return False
            clock.sleep(1.0)

    def wait_program(self, program: str, budget_s: float = 30) -> str | None:
        clock = park_worker.WallClock(1.0)
        dl = park_worker.Deadline(clock, budget_s)
        while True:
            got = self.program()
            if got is not None and same_path(got, program):
                return got
            if dl.expired():
                return got
            clock.sleep(1.0)


# --------------------------------------------------------------------------- sqlite
def ro_uri(path: Path, immutable: bool = False) -> str:
    return path.resolve().as_uri() + ("?immutable=1" if immutable else "?mode=ro")


def connect_ro(path: Path, *, allow_immutable: bool = False) -> tuple[sqlite3.Connection, str]:
    """Read-only connection (``mode=ro``); with ``allow_immutable`` fall back to
    ``immutable=1`` (no locking at all — may read a torn page; informational)."""
    try:
        conn = sqlite3.connect(ro_uri(path), uri=True, timeout=10)
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        return conn, "ro"
    except sqlite3.Error:
        if not allow_immutable:
            raise
    conn = sqlite3.connect(ro_uri(path, immutable=True), uri=True, timeout=10)
    conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
    return conn, "immutable (may be torn)"


def _qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def db_snapshot(conn: sqlite3.Connection) -> dict[str, Any]:
    """user_version, every table's row count, max(ticks.id), meta rows."""
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {_qident(t)}").fetchone()[0] for t in tables}
    max_tick = (conn.execute("SELECT COALESCE(MAX(id), 0) FROM ticks").fetchone()[0]
                if "ticks" in tables else None)
    meta = ([list(r) for r in conn.execute(
        "SELECT key, value, updated_at FROM meta ORDER BY key")] if "meta" in tables else [])
    return {
        "user_version": conn.execute("PRAGMA user_version").fetchone()[0],
        "counts": counts,
        "max_tick_id": max_tick,
        "meta": meta,
    }


def compare_snapshots(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    diffs: list[str] = []
    if a["user_version"] != b["user_version"]:
        diffs.append(f"user_version {a['user_version']} != {b['user_version']}")
    if a["counts"] != b["counts"]:
        keys = sorted(set(a["counts"]) | set(b["counts"]))
        bad = [k for k in keys if a["counts"].get(k) != b["counts"].get(k)]
        diffs.append("row counts differ in: " + ", ".join(bad))
    if a["max_tick_id"] != b["max_tick_id"]:
        diffs.append(f"max(ticks.id) {a['max_tick_id']} != {b['max_tick_id']}")
    if a["meta"] != b["meta"]:
        diffs.append("meta rows differ")
    return diffs


def online_backup(src: Path, dst: Path) -> None:
    """SQLite online backup ``src`` -> ``dst`` (never ``cp`` a database: the
    backup API reads through the journal/WAL and yields a consistent copy)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    for p in (dst, Path(f"{dst}-journal"), Path(f"{dst}-wal"), Path(f"{dst}-shm")):
        p.unlink(missing_ok=True)
    s = sqlite3.connect(ro_uri(src), uri=True, timeout=30)
    d = sqlite3.connect(str(dst))
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()


def integrity_ok(path: Path) -> tuple[bool, str]:
    conn = sqlite3.connect(str(path))
    try:
        rows = [r[0] for r in conn.execute("PRAGMA integrity_check")]
    finally:
        conn.close()
    return rows == ["ok"], "; ".join(rows[:3])


@dataclass
class Tick:
    id: int
    status: str
    claimed: int
    classified: int
    sent: int


_TICK_SQL = "SELECT id, status, claimed, classified, sent FROM ticks"


def first_tick_after(db: Path, after_id: int) -> Tick | None:
    try:
        conn, _ = connect_ro(db)
    except sqlite3.Error:
        return None
    try:
        row = conn.execute(f"{_TICK_SQL} WHERE id > ? ORDER BY id LIMIT 1", (after_id,)).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return Tick(*row) if row else None


def read_tick(db: Path, tick_id: int) -> Tick | None:
    try:
        conn, _ = connect_ro(db)
    except sqlite3.Error:
        return None
    try:
        row = conn.execute(f"{_TICK_SQL} WHERE id = ?", (tick_id,)).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return Tick(*row) if row else None


def recent_closed_ticks(db: Path, at_or_below: int, n: int = 3) -> list[Tick]:
    try:
        conn, _ = connect_ro(db)
    except sqlite3.Error:
        return []
    try:
        rows = conn.execute(
            f"{_TICK_SQL} WHERE status != 'running' AND id <= ? ORDER BY id DESC LIMIT ?",
            (at_or_below, n)).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    return [Tick(*r) for r in rows]


def judge_first_tick(tick: Tick, old_recent: list[Tick]) -> tuple[bool, str]:
    """Pass = closed ``ok`` AND it did the work: when it claimed rows it also
    classified and sent some — unless the old prod's last 3 closed ticks show
    the very same stall (then the stall predates the cutover)."""
    if tick.status != "ok":
        return False, f"first tick #{tick.id} closed status={tick.status!r}"
    if tick.claimed > 0 and (tick.classified == 0 or tick.sent == 0):
        def stalled(t: Tick) -> bool:
            return t.claimed > 0 and (t.classified == 0 or t.sent == 0)
        if len(old_recent) >= 3 and all(stalled(t) for t in old_recent[:3]):
            return True, (f"first tick #{tick.id} claimed {tick.claimed} but classified "
                          f"{tick.classified}/sent {tick.sent}; the old prod's last 3 ticks "
                          "stalled the same way, so this predates the cutover")
        return False, (f"first tick #{tick.id} claimed {tick.claimed} but classified "
                       f"{tick.classified}, sent {tick.sent}")
    return True, (f"first tick #{tick.id} ok (claimed {tick.claimed}, classified "
                  f"{tick.classified}, sent {tick.sent})")


def db_mtime(db: Path) -> float:
    times = []
    for p in (db, Path(f"{db}-wal"), Path(f"{db}-journal")):
        try:
            times.append(p.stat().st_mtime)
        except FileNotFoundError:
            pass
    return max(times) if times else 0.0


# --------------------------------------------------------------------------- untracked state
def classify_untracked(rel: str) -> str:
    """``regenerate`` | ``db`` | ``db-sidecar`` | ``copy`` for one untracked path
    (relative to the old prod root, ``/``-separated)."""
    parts = rel.rstrip("/").split("/")
    if "__pycache__" in parts or ".pytest_cache" in parts or "node_modules" in parts:
        return "regenerate"
    if rel.endswith(".pyc"):
        return "regenerate"
    if rel in REGENERATE_EXACT or rel.rstrip("/") in REGENERATE_EXACT:
        return "regenerate"
    if any(rel.startswith(p) or rel + "/" == p for p in REGENERATE_PREFIXES):
        return "regenerate"
    if _LOCK_LEFTOVER_RE.match(rel):
        return "regenerate"
    if _DB_RE.match(rel):
        return "db"
    if _DB_SIDECAR_RE.match(rel):
        return "db-sidecar"
    return "copy"


def list_untracked(cfg: Config, root: Path) -> list[str]:
    """Every untracked + ignored path under ``root`` (files, one per entry)."""
    cp = git(cfg, root, "status", "--porcelain=v1", "-z", "--ignored", "--untracked-files=all")
    if cp.returncode != 0:
        raise RuntimeError(f"git status failed in {root}: {tail(cp.stderr, 3)}")
    out: list[str] = []
    for entry in cp.stdout.split("\0"):
        if len(entry) > 3 and entry[:2] in ("??", "!!"):
            out.append(entry[3:])
    return out


def inventory(cfg: Config, root: Path) -> list[dict[str, Any]]:
    """Names, sizes and classes of the untracked state — never contents."""
    items = []
    for rel in list_untracked(cfg, root):
        cls = classify_untracked(rel)
        try:
            size = (root / rel).lstat().st_size
        except OSError:
            size = None
        items.append({"path": rel, "class": cls, "size": size})
    return items


def summarize_inventory(items: list[dict[str, Any]]) -> dict[str, Any]:
    by: dict[str, dict[str, int]] = {}
    for it in items:
        b = by.setdefault(it["class"], {"files": 0, "bytes": 0})
        b["files"] += 1
        b["bytes"] += it["size"] or 0
    return by


def copy_untracked(src_root: Path, dst_root: Path, rels: Iterable[str],
                   skip: Iterable[str] = ()) -> list[dict[str, Any]]:
    """Copy every ``copy``-class path with ``shutil.copy2`` (mode + mtime kept)
    and verify each by sha256 (symlinks: by target). Raises on any mismatch.
    Returns name/size/sha records; contents are never logged."""
    skipped = set(skip)
    copied: list[dict[str, Any]] = []
    for rel in rels:
        if classify_untracked(rel) != "copy" or rel in skipped:
            continue
        src, dst = src_root / rel, dst_root / rel
        if os.path.lexists(dst):
            raise RuntimeError(f"untracked copy: {rel} already exists in the new prod")
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():
            target = os.readlink(src)
            os.symlink(target, dst)
            if os.readlink(dst) != target:
                raise RuntimeError(f"untracked copy: symlink {rel} did not round-trip")
            copied.append({"path": rel, "size": None, "sha256": None, "symlink": True})
            continue
        if src.is_dir():
            raise RuntimeError(f"untracked copy: {rel} is a directory (expected files only)")
        shutil.copy2(src, dst, follow_symlinks=False)
        s_sha, d_sha = sha256_file(src), sha256_file(dst)
        s_mode, d_mode = src.stat().st_mode & 0o7777, dst.stat().st_mode & 0o7777
        if s_sha != d_sha or s_mode != d_mode:
            raise RuntimeError(f"untracked copy: {rel} did not arrive byte- and mode-identical")
        copied.append({"path": rel, "size": dst.stat().st_size, "sha256": d_sha})
    return copied


# --------------------------------------------------------------------------- health
def normalize_health(obj: Any) -> Any:
    """Drop keys that differ between two reads of the same data (``*_age_s``,
    ``*_at``, ``now``), recursively."""
    if isinstance(obj, dict):
        return {k: normalize_health(v) for k, v in obj.items()
                if k not in VOLATILE_KEYS and not k.endswith(VOLATILE_KEY_SUFFIXES)}
    if isinstance(obj, list):
        return [normalize_health(v) for v in obj]
    return obj


def parse_health(stdout: str) -> dict[str, Any]:
    """The last stdout line that is a JSON object (uv may print chatter)."""
    for line in reversed((stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                val = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(val, dict):
                return val
    raise ValueError("no JSON object in `cli health` output")


def health_diff(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    na, nb = normalize_health(a), normalize_health(b)
    if na == nb:
        return []
    keys = sorted(set(na) | set(nb))
    return [k for k in keys if na.get(k) != nb.get(k)]


def run_health(cfg: Config, checkout: Path, *, no_sync: bool) -> dict[str, Any]:
    cmd = [cfg.uv_bin, "run"] + (["--frozen", "--no-sync"] if no_sync else []) + [
        "python", "-m", "job_enricher.cli", "health"]
    cp = run(cmd, cwd=checkout, timeout=cfg.health_timeout_s)
    if cp.returncode != 0:
        raise RuntimeError(f"`cli health` failed in {checkout} ({cp.returncode}): "
                           f"{tail(cp.stderr, 5)}")
    return parse_health(cp.stdout)


# --------------------------------------------------------------------------- venv
def read_pyvenv_cfg(venv: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    text = read_text(venv / "pyvenv.cfg") or ""
    for line in text.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


def app_interpreter(cfg: Config) -> tuple[Path | None, str]:
    """The old prod venv's base interpreter (``home`` in pyvenv.cfg + python3)."""
    pv = read_pyvenv_cfg(cfg.old_prod / ".venv")
    home = pv.get("home")
    if not home:
        return None, "old prod .venv/pyvenv.cfg has no `home`"
    interp = Path(home) / "python3"
    if not (interp.exists() and os.access(interp, os.X_OK)):
        return None, f"interpreter {interp} (from pyvenv.cfg) is missing"
    return interp, pv.get("version_info", "?")


def freeze(cfg: Config, venv_python: Path) -> list[str]:
    cp = run([cfg.uv_bin, "pip", "list", "--format=freeze", "--python", str(venv_python)],
             timeout=300)
    if cp.returncode != 0:
        raise RuntimeError(f"uv pip list failed for {venv_python}: {tail(cp.stderr, 3)}")
    keep = []
    for line in cp.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("-e "):
            continue
        name = re.split(r"==| @ ", line, maxsplit=1)[0].strip().lower().replace("_", "-")
        if name == "job-enricher":
            continue
        keep.append(line)
    return sorted(keep)


# --------------------------------------------------------------------------- state
class State:
    """``state.json`` — written atomically (tmp + fsync + os.replace)."""

    def __init__(self, path: Path, data: dict[str, Any] | None = None, exists: bool = False):
        self.path = path
        self.data: dict[str, Any] = data or {}
        self.exists = exists

    @classmethod
    def load(cls, path: Path) -> "State":
        text = read_text(path)
        if text is None:
            return cls(path, {"phase": "PENDING", "created_at": now_iso()}, exists=False)
        return cls(path, json.loads(text), exists=True)

    @property
    def phase(self) -> str:
        return self.data.get("phase", "PENDING")

    def set_phase(self, phase: str, **extra: Any) -> None:
        self.data["phase"] = phase
        self.data.update(extra)
        self.event(f"phase -> {phase}")
        self.save()

    def event(self, msg: str) -> None:
        hist = self.data.setdefault("history", [])
        hist.append({"at": now_iso(), "event": msg})
        del hist[:-200]

    def save(self) -> None:
        self.data["updated_at"] = now_iso()
        atomic_write_bytes(self.path, (json.dumps(self.data, indent=2, sort_keys=True) + "\n")
                           .encode("utf-8"))
        self.exists = True


class SingleFlight:
    """``$STATE/cutover.lock/`` (mkdir + pid). A dead or pre-boot holder is reclaimed."""

    def __init__(self, state_dir: Path) -> None:
        self.dir = state_dir / "cutover.lock"

    def acquire(self) -> bool:
        for _ in range(2):
            try:
                self.dir.mkdir()
                (self.dir / "pid").write_text(str(os.getpid()))
                return True
            except FileExistsError:
                pid = park_worker.payload_pid(read_text(self.dir / "pid") or "")
                boot = park_worker.boot_epoch()
                try:
                    mtime = self.dir.stat().st_mtime
                except FileNotFoundError:
                    continue
                pre_boot = boot is not None and mtime < boot
                if pid is None and time.time() - mtime < 5 and not pre_boot:
                    return False  # another run is between its mkdir and its pid write
                if park_worker.pid_alive(pid) and not pre_boot:
                    return False
                shutil.rmtree(self.dir, ignore_errors=True)
        return False

    def release(self) -> None:
        if park_worker.payload_pid(read_text(self.dir / "pid") or "") == os.getpid():
            shutil.rmtree(self.dir, ignore_errors=True)


# --------------------------------------------------------------------------- notifications
def notify(cfg: Config, st: State | None, event: str, message: str) -> bool:
    """Text Brendan once per event (recorded in state). Best effort, 60 s cap.
    Callers never put secrets or ``.env.local`` content in ``message``."""
    if st is not None:
        sent = st.data.setdefault("notified", {})
        if event in sent:
            return False
    text = f"JVN enricher cutover: {message}"
    ok = False
    if os.access(cfg.send_sh, os.X_OK):
        cp = run([str(cfg.send_sh), text], timeout=60)
        ok = cp.returncode == 0
        log(f"text '{event}': {'sent' if ok else f'send.sh failed ({cp.returncode})'}")
    else:
        log(f"text '{event}': send.sh not executable at {cfg.send_sh}; not sent")
    if st is not None:
        st.data["notified"][event] = {"at": now_iso(), "sent": ok}
        st.save()
    return ok


# --------------------------------------------------------------------------- resume
def decide_resume(phase: str, where: str, new_exists: bool, new_owned: bool,
                  state_exists: bool) -> str:
    """What a ``--run`` start does, from reality first and ``phase`` second
    (PLAN §4.6). Pure, so the table is unit-tested."""
    if phase == "DONE":
        return "noop_done"
    if phase == "FAILED":
        return "noop_failed"
    if phase == "ROLLED_BACK":
        return "noop_rolled_back"
    if phase == "ROLLING_BACK":
        return "rollback"
    if where == "old":
        if not new_exists:
            return "start"
        if new_owned:
            return "redo"
        return "refuse_unowned_new"
    if where == "new":
        if not state_exists:
            return "refuse_new_without_state"
        if phase in ("SWAPPING", "SWAPPED"):
            return "continue_swap"
        if phase == "VERIFIED":
            return "retire"
        return "refuse_inconsistent"
    return "refuse_plist_elsewhere"


RESUME_EXIT = {"noop_done": EXIT_DONE, "noop_failed": EXIT_FAILED,
               "noop_rolled_back": EXIT_ROLLED_BACK}

REFUSALS = {
    "refuse_unowned_new": "the new prod path exists but was not created by the cutover "
                          f"(no {OWNED_MARKER}); move it aside and re-arm",
    "refuse_new_without_state": "the plist already points at the new prod but there is no "
                                "cutover state — a human moved it; nothing to do",
    "refuse_inconsistent": "the plist points at the new prod but the state says no swap "
                           "happened — a human changed it; stopping",
    "refuse_plist_elsewhere": "the enricher plist points neither at the old nor at the new "
                              "prod (or is unreadable); stopping",
}


# --------------------------------------------------------------------------- checks
@dataclass
class Check:
    name: str
    ok: bool
    level: str = "hard"        # hard | soft | info
    detail: str = ""
    transient: bool = False    # in --run: a failure defers instead of refusing


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)

    def add(self, *a: Any, **kw: Any) -> Check:
        c = Check(*a, **kw)
        self.checks.append(c)
        return c

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks if c.level == "hard")

    def hard_failures(self) -> list[Check]:
        return [c for c in self.checks if c.level == "hard" and not c.ok]


def free_space_at(path: Path) -> int:
    p = path
    while not p.exists() and p != p.parent:
        p = p.parent
    return shutil.disk_usage(p).free


def _local_checks(cfg: Config, launchd: Launchd, rep: Report, *, in_run: bool,
                  st: State | None = None) -> None:
    """Checks that read local state only (shared by --preflight and phase A)."""
    old = cfg.old_prod
    exists = (old / ".git").exists()
    rep.add("old_prod_exists", exists, detail=str(old))
    if not exists:
        return
    role = (read_text(old / ".checkout-role") or "").strip()
    rep.add("old_prod_role", role == "prod", detail=f".checkout-role={role!r}")
    cp = git(cfg, old, "status", "--porcelain", "--untracked-files=no")
    dirty = [ln for ln in cp.stdout.splitlines() if ln.strip()]
    rep.add("old_prod_clean", cp.returncode == 0 and not dirty,
            detail="no tracked changes" if not dirty else f"{len(dirty)} tracked change(s)")
    cp = git(cfg, old, "rev-parse", "HEAD", "HEAD^{tree}")
    head, tree = (cp.stdout.split() + ["", ""])[:2]
    rep.extras["old_prod_head"], rep.extras["app_tree"] = head, tree
    rep.add("old_prod_tree", cp.returncode == 0 and bool(tree), detail=f"HEAD {head[:12]} tree {tree}")

    db = old / "data" / "enricher.db"
    if db.exists():
        try:
            conn, mode = connect_ro(db, allow_immutable=not in_run)
            try:
                snap = db_snapshot(conn)
            finally:
                conn.close()
            size = db.stat().st_size
            rep.extras["db"] = {"path": str(db), "size": size, "read_mode": mode,
                                "user_version": snap["user_version"], "counts": snap["counts"],
                                "max_tick_id": snap["max_tick_id"]}
            rep.add("db_readable", True, detail=f"user_version={snap['user_version']} "
                    f"size={size} read={mode}")
            free = free_space_at(cfg.new_prod)
            rep.add("free_space", free >= 3 * size, detail=f"free={free} need>={3 * size}",
                    transient=True)
        except sqlite3.Error as exc:
            rep.add("db_readable", False, detail=f"{db}: {exc}", transient=True)
    else:
        rep.add("db_readable", False, detail=f"{db} missing")

    interp, version = app_interpreter(cfg)
    rep.extras["interpreter"] = str(interp) if interp else None
    rep.add("interpreter", interp is not None,
            detail=f"{interp} (venv version_info={version})" if interp else version)
    cp = run([cfg.uv_bin, "--version"], timeout=30)
    rep.add("uv", cp.returncode == 0, detail=(cp.stdout.strip() or tail(cp.stderr, 1)))

    info = read_plist(cfg.enricher_plist)
    where = plist_where(cfg, info)
    rep.extras["plist_where"] = where
    if info is None:
        rep.add("plist", False, detail=f"{cfg.enricher_plist} missing or unparseable")
    else:
        detail = f"label={info.label} workdir={info.workdir}"
        ok = info.label == ENRICHER_LABEL and where == "old"
        if ok:
            try:
                new_bytes = rewrite_plist_bytes(info.raw, str(info.workdir), str(cfg.new_enricher))
                lint_ok, lint = plutil_lint(cfg, new_bytes)
                ok = lint_ok
                detail += f"; rewrite holds exactly 2 old-prod paths; lint={'ok' if lint_ok else lint}"
            except PlistRewriteError as exc:
                ok, detail = False, f"{detail}; {exc}"
        rep.add("plist", ok, detail=detail)

    loaded = launchd.is_loaded()
    program = launchd.program() if loaded else None
    want = str(cfg.old_prod / WRAPPER_REL)
    rep.extras["launchd"] = {"loaded": loaded, "program": program}
    unloaded_by_us = bool(st and st.data.get("unloaded_by_us"))
    if loaded is None:
        rep.add("launchd", False, detail="`launchctl list` failed", transient=True)
    elif not loaded:
        rep.add("launchd", unloaded_by_us,
                detail="label not loaded" + (" (we unloaded it)" if unloaded_by_us else ""),
                transient=True)
    else:
        rep.add("launchd", program is not None and same_path(program, want),
                detail=f"loaded; program={program}", transient=True)

    new = cfg.new_prod
    if not new.exists():
        rep.add("new_prod_path", True, detail=f"{new} absent")
    else:
        owned = (new / OWNED_MARKER).exists()
        rep.add("new_prod_path", owned, detail=f"{new} exists"
                + (f" with {OWNED_MARKER} (a rerun replaces it)" if owned else
                   f" WITHOUT {OWNED_MARKER} — move it aside"))

    rep.add("send_sh", os.access(cfg.send_sh, os.X_OK), level="soft", detail=str(cfg.send_sh))


def _lock_info(cfg: Config) -> dict[str, Any]:
    li = park_worker.read_lock(cfg.old_prod / "data" / ".tick.lock")
    if li is None:
        return {"present": False}
    return {"present": True, "pid": li.pid, "pid_alive": park_worker.pid_alive(li.pid),
            "age_s": round(time.time() - li.mtime)}


def _tick_info(cfg: Config) -> dict[str, Any] | None:
    db = cfg.old_prod / "data" / "enricher.db"
    if not db.exists():
        return None
    try:
        conn, _ = connect_ro(db, allow_immutable=True)
    except sqlite3.Error:
        return None
    try:
        row = conn.execute("SELECT id, status, started_at, ended_at FROM ticks "
                           "ORDER BY id DESC LIMIT 1").fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    if not row:
        return None
    age = None
    try:
        age = round(time.time() - datetime.fromisoformat(
            str(row[2]).replace("Z", "+00:00")).timestamp())
    except ValueError:
        pass
    return {"id": row[0], "status": row[1], "started_at": row[2], "ended_at": row[3],
            "started_age_s": age}


def preflight(cfg: Config, launchd: Launchd, jvn_repo: Path | None) -> Report:
    """Strictly read-only: never writes the old prod, the plists, launchd (only
    ``list``/``print``) or the state dir; any temp dir is deleted."""
    rep = Report()
    _local_checks(cfg, launchd, rep, in_run=False)
    tmp: str | None = None
    try:
        repo: Path | None = None
        if jvn_repo is not None:
            repo = jvn_repo
            rep.extras["ref_source"] = f"local repo {jvn_repo}"
        else:
            tmp = tempfile.mkdtemp(prefix="jvn-cutover-preflight-")
            cp = run([cfg.git_bin, "clone", "--bare", "--quiet", "--filter=blob:none",
                      cfg.jvn_remote_url, f"{tmp}/jvn.git"], timeout=cfg.net_timeout_s)
            if cp.returncode == 0:
                repo = Path(tmp) / "jvn.git"
                rep.extras["ref_source"] = f"temp bare fetch of {cfg.jvn_remote_url}"
            else:
                rep.add("jvn_fetch", False, detail=tail(cp.stderr, 2), transient=True)
        tree = rep.extras.get("app_tree")
        if repo is not None and tree:
            try:
                m = derive_ref(cfg, repo, tree)
            except RuntimeError as exc:
                m = None
                rep.add("ref", False, detail=str(exc))
            else:
                rep.extras["ref"] = asdict(m) if m else None
                rep.add("ref", m is not None,
                        detail=(f"{m.ref} -> {m.commit[:12]} (by {m.source}), "
                                f"src/enricher tree {m.tree}") if m
                        else f"no JVN ref has src/enricher == {tree}: the cutover would REFUSE")
            main_ref = "refs/remotes/origin/main" if jvn_repo is not None else "main"
            merged = main_has_cutover(cfg, repo, main_ref)
            rep.add("merged", True, level="info",
                    detail=f"{main_ref} {'contains' if merged else 'does not contain yet'} "
                           f"{CUTOVER_PY_IN_MAIN}")
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    cp = run([cfg.git_bin, "ls-remote", "--heads", cfg.jvn_remote_url, "main"],
             timeout=cfg.net_timeout_s)
    rep.add("jvn_reachable", cp.returncode == 0 and "refs/heads/main" in cp.stdout,
            detail=cfg.jvn_remote_url, transient=True)
    ref = rep.extras.get("ref") or {}
    if ref.get("source") == "tag":
        cp = run([cfg.git_bin, "ls-remote", "--tags", cfg.jvn_remote_url,
                  f"refs/tags/{ref['ref']}"], timeout=cfg.net_timeout_s)
        rep.add("tag_on_remote", cp.returncode == 0 and ref["ref"] in cp.stdout, level="soft",
                detail=f"{ref['ref']} {'is' if ref['ref'] in cp.stdout else 'is NOT yet'} "
                       "on the JVN remote (the merged cutover looks tags up there)")
    old_url = git(cfg, cfg.old_prod, "remote", "get-url", "origin").stdout.strip()
    if old_url:
        cp = run([cfg.git_bin, "ls-remote", "--heads", old_url, "main"], timeout=cfg.net_timeout_s)
        rep.add("job_enricher_reachable", cp.returncode == 0, level="soft",
                detail=f"{old_url} (needed for the README banner push)")
    cp = run([cfg.gh_bin, "auth", "status"], timeout=60)  # output never printed: it names the token
    rep.add("gh_auth", cp.returncode == 0, level="soft",
            detail="gh is logged in" if cp.returncode == 0 else "gh auth status failed (archive will be skipped)")

    rep.extras["tick"] = _tick_info(cfg)
    rep.extras["lock"] = _lock_info(cfg)
    try:
        items = inventory(cfg, cfg.old_prod) if (cfg.old_prod / ".git").exists() else []
    except RuntimeError as exc:
        items = []
        rep.add("untracked_inventory", False, level="soft", detail=str(exc))
    rep.extras["untracked_summary"] = summarize_inventory(items)
    rep.extras["untracked_copy"] = [i for i in items if i["class"] in ("copy", "db")]
    rep.extras["old_dev"] = {
        "path": str(cfg.old_dev), "exists": cfg.old_dev.exists(),
        "role": (read_text(cfg.old_dev / ".checkout-role") or "").strip() or None,
    }
    st_text = read_text(cfg.state_file)
    rep.extras["state"] = json.loads(st_text).get("phase") if st_text else None
    return rep


def print_report(rep: Report, stream: Any) -> None:
    for c in rep.checks:
        tag = "ok" if c.ok else {"hard": "FAIL", "soft": "warn", "info": "info"}[c.level]
        print(f"[{tag:>4}] {c.name}: {c.detail}", file=stream)
    for key in ("ref_source", "tick", "lock", "untracked_summary", "old_dev", "state"):
        if key in rep.extras:
            print(f"[info] {key}: {json.dumps(rep.extras[key], sort_keys=True)}", file=stream)
    for it in rep.extras.get("untracked_copy", []):
        print(f"[info]   carry over: {it['path']} ({it['size']} bytes, {it['class']})", file=stream)
    print(f"preflight: {'PASS' if rep.ok else 'FAIL'}", file=stream)


# --------------------------------------------------------------------------- phase A
def make_clone(cfg: Config, src_repo: Path, dest: Path, commit: str) -> None:
    """``dest`` = a JVN clone detached at ``commit``, ``origin`` = the real JVN
    URL. The OWNED marker is written FIRST, so even a crash mid-clone leaves a
    dir the next run may delete."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.mkdir()
    (dest / OWNED_MARKER).write_text(json.dumps(
        {"created_at": now_iso(), "pid": os.getpid(), "commit": commit}) + "\n")
    steps = [
        ("-c", "init.defaultBranch=main", "init", "--quiet"),
        ("remote", "add", "origin", str(src_repo)),
        ("fetch", "--quiet", "--tags", "origin", "+refs/heads/*:refs/remotes/origin/*"),
        ("-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", commit),
        ("remote", "set-url", "origin", cfg.jvn_remote_url),
    ]
    for args in steps:
        git_ok(cfg, dest, *args, timeout=cfg.net_timeout_s)
    excl = dest / ".git" / "info" / "exclude"
    excl.parent.mkdir(parents=True, exist_ok=True)
    with open(excl, "a", encoding="utf-8") as fh:
        fh.write(f"\n# jvn-enricher-cutover markers\n/{OWNED_MARKER}\n/{SWAPPED_MARKER}\n"
                 "/.checkout-role\n")


def verify_clone(cfg: Config, dest: Path, app_tree: str) -> None:
    got = git_ok(cfg, dest, "rev-parse", f"HEAD:{ENRICHER_SUBDIR}").strip()
    if got != app_tree:
        raise Refuse(f"new prod src/enricher tree {got} != old prod tree {app_tree}")
    dirty = git_ok(cfg, dest, "status", "--porcelain").strip()
    if dirty:
        raise Refuse(f"new prod clone is not clean: {len(dirty.splitlines())} entr(ies)")


def sync_and_compare_venv(cfg: Config, interp: Path, new_enricher: Path) -> None:
    cp = run([cfg.uv_bin, "sync", "--frozen", "--python", str(interp)], cwd=new_enricher,
             timeout=cfg.uv_timeout_s)
    if cp.returncode != 0:
        raise Defer(f"uv sync --frozen failed ({cp.returncode}): {tail(cp.stderr, 8)}")
    old_v = read_pyvenv_cfg(cfg.old_prod / ".venv").get("version_info")
    new_v = read_pyvenv_cfg(new_enricher / ".venv").get("version_info")
    if not old_v or old_v != new_v:
        raise Refuse(f"new venv python {new_v} != old prod venv python {old_v}")
    old_f = freeze(cfg, cfg.old_prod / ".venv" / "bin" / "python")
    new_f = freeze(cfg, new_enricher / ".venv" / "bin" / "python")
    if old_f != new_f:
        only_old = sorted(set(old_f) - set(new_f))[:5]
        only_new = sorted(set(new_f) - set(old_f))[:5]
        raise Refuse(f"installed packages differ: old-only {only_old}, new-only {only_new}")
    log(f"venv equivalent: python {new_v}, {len(new_f)} packages identical")


def phase_a(cfg: Config, st: State, launchd: Launchd) -> None:
    log("A: prepare (the worker keeps running)")
    rep = Report()
    _local_checks(cfg, launchd, rep, in_run=True, st=st)
    for c in rep.checks:
        log(f"A: check {c.name}: {'ok' if c.ok else 'FAIL'} — {c.detail}")
    bad = rep.hard_failures()
    if bad:
        if all(c.transient for c in bad):
            raise Defer("; ".join(f"{c.name}: {c.detail}" for c in bad))
        raise Refuse("; ".join(f"{c.name}: {c.detail}" for c in bad if not c.transient))
    interp = Path(rep.extras["interpreter"])
    app_tree = rep.extras["app_tree"]

    mirror = ensure_mirror(cfg)
    if not main_has_cutover(cfg, mirror):
        raise Defer("JVN main does not contain the cutover yet (not merged)")
    m = derive_ref(cfg, mirror, app_tree)
    if m is None:
        raise Refuse(f"no JVN ref has src/enricher == the old prod tree {app_tree}")
    log(f"A: ref {m.ref} -> {m.commit[:12]} (found by {m.source})")
    st.data.update(ref=m.ref, commit=m.commit, app_tree=app_tree, ref_source=m.source,
                   old_prod_head=rep.extras.get("old_prod_head"))
    st.save()

    make_clone(cfg, mirror, cfg.new_prod, m.commit)
    verify_clone(cfg, cfg.new_prod, app_tree)
    sync_and_compare_venv(cfg, interp, cfg.new_enricher)
    st.set_phase("PREPARED")


# --------------------------------------------------------------------------- phase B
def lsof_holders(cfg: Config, path: Path) -> list[int] | None:
    """Pids holding ``path`` open; None when lsof itself is unavailable."""
    cp = run([cfg.lsof_bin, "-t", "--", str(path)], timeout=60)
    if cp.returncode == 127:
        return None
    return sorted({int(x) for x in cp.stdout.split() if x.isdigit()} - {os.getpid()})


def wait_no_holders(cfg: Config, path: Path, budget_s: float) -> list[int]:
    clock = park_worker.WallClock(cfg.lock_poll_s)
    dl = park_worker.Deadline(clock, budget_s)
    while True:
        holders = lsof_holders(cfg, path)
        if holders is None:
            log(f"lsof unavailable at {cfg.lsof_bin}; skipping the open-file check")
            return []
        if not holders or dl.expired():
            return holders
        clock.sleep(max(cfg.lock_poll_s, 1.0))


def park(cfg: Config, st: State, launchd: Launchd, checkout: Path, *, budget_s: float,
         key: str) -> park_worker.ClaimResult:
    """Claim ``checkout``'s tick lock at idle (worker still loaded). Records
    the payload in state BEFORE claiming so a later run can take it back."""
    payload = park_worker.make_payload(os.getpid())
    known = st.data.setdefault("our_lock_payloads", [])
    known.append(payload)
    del known[:-50]
    st.save()
    clock = park_worker.WallClock(cfg.lock_poll_s, log=log)
    res = park_worker.claim(checkout / "data" / ".tick.lock", checkout / WRAPPER_REL, budget_s,
                            payload, poll_s=cfg.lock_poll_s, known_payloads=known,
                            clock=clock, log=log)
    if res.claimed:
        st.data[key] = payload
        st.save()
    return res


def unload_and_quiesce(cfg: Config, st: State, launchd: Launchd, checkout: Path,
                       plist: Path) -> None:
    """With the lock held: let the finishing wrapper exit, unload, verify the
    label is gone, wait for any racing fire, and require no open DB handle."""
    wrapper = checkout / WRAPPER_REL
    if not park_worker.wait_idle(wrapper, cfg.wrapper_exit_s, poll_s=cfg.lock_poll_s):
        raise Defer(f"a wrapper for {checkout} kept running {cfg.wrapper_exit_s:.0f}s "
                    "after the lock was ours")
    if launchd.is_loaded():
        st.data["unloaded_by_us"] = True
        st.save()
        log(f"unloading {ENRICHER_LABEL} (lock held, no wrapper running)")
        launchd.unload(plist)
        if not launchd.wait_loaded(False, 30):
            raise Defer(f"{ENRICHER_LABEL} is still loaded after `launchctl unload`")
    if not park_worker.wait_idle(wrapper, cfg.wrapper_exit_s, poll_s=cfg.lock_poll_s):
        raise Defer("a wrapper is still running after the unload")
    holders = wait_no_holders(cfg, checkout / "data" / "enricher.db", cfg.wrapper_exit_s)
    if holders:
        raise Defer(f"enricher.db is still open by pid(s) {holders}")


def phase_b(cfg: Config, st: State, launchd: Launchd) -> None:
    log("B: park the old worker between ticks")
    if "launchd_loaded_at_start" not in st.data:
        st.data["launchd_loaded_at_start"] = bool(launchd.is_loaded())
        st.save()
    res = park(cfg, st, launchd, cfg.old_prod, budget_s=cfg.park_budget_s, key="old_lock_payload")
    if not res.claimed:
        notify(cfg, st, "DEFERRED:wedged",
               f"waiting: an enricher tick looks wedged ({res.reason}); will retry")
        raise Defer(f"park budget exhausted: {res.reason}")
    log(f"B: lock claimed after {res.waited_s:.0f}s"
        + (f" (reclaimed {res.reclaimed} lock)" if res.reclaimed else ""))
    unload_and_quiesce(cfg, st, launchd, cfg.old_prod, cfg.enricher_plist)
    st.set_phase("PARKED")


def restore_old_role(cfg: Config, st: State) -> None:
    orig = st.data.get("orig_old_role")
    if orig is None:
        return
    p = cfg.old_prod / ".checkout-role"
    if read_text(p) != orig:
        atomic_write_bytes(p, orig.encode("utf-8"))
        log(f"restored old prod .checkout-role to {orig.strip()!r}")


def release_our_lock(st: State, checkout: Path) -> bool:
    lock = checkout / "data" / ".tick.lock"
    li = park_worker.read_lock(lock)
    if li is None or li.raw not in st.data.get("our_lock_payloads", []):
        return False
    if li.pid != os.getpid() and park_worker.pid_alive(li.pid):
        return False
    removed = park_worker.release(lock, payload=li.raw)
    if removed:
        log(f"released our lock in {checkout}")
    return removed


def unpark_old(cfg: Config, st: State, launchd: Launchd) -> None:
    """Put the old prod back exactly as found (role, lock, launchd). Pre-swap only."""
    try:
        restore_old_role(cfg, st)
    except OSError as exc:
        log(f"unpark: could not restore .checkout-role: {exc}")
    release_our_lock(st, cfg.old_prod)
    if st.data.get("unloaded_by_us") and st.data.get("launchd_loaded_at_start", True):
        if launchd.is_loaded() is False:
            if plist_where(cfg, read_plist(cfg.enricher_plist)) != "old":
                log("unpark: the plist no longer points at the old prod; NOT loading it")
                return
            log(f"unpark: reloading {ENRICHER_LABEL}")
            launchd.load(cfg.enricher_plist)
            if not launchd.wait_loaded(True, 30):
                log(f"unpark: WARNING {ENRICHER_LABEL} did not come back")
                notify(cfg, st, "UNPARK_FAILED",
                       f"the old enricher did not reload after a deferral — run "
                       f"`launchctl load {cfg.enricher_plist}`")
                return
        st.data["unloaded_by_us"] = False
        st.save()


# --------------------------------------------------------------------------- phase C
def phase_c(cfg: Config, st: State, launchd: Launchd) -> None:
    log("C: copy state (worker parked)")
    plist_now = cfg.enricher_plist.read_bytes()
    if plist_where(cfg, parse_plist(plist_now)) != "old":
        raise Refuse("the plist stopped pointing at the old prod during the cutover")
    atomic_write_bytes(cfg.plist_orig, plist_now)
    st.data["plist_orig_sha256"] = hashlib.sha256(plist_now).hexdigest()
    if "orig_old_role" not in st.data:
        st.data["orig_old_role"] = read_text(cfg.old_prod / ".checkout-role") or "prod\n"
    st.save()

    rels = list_untracked(cfg, cfg.old_prod)
    dbs = sorted(r for r in rels if classify_untracked(r) == "db")
    if "data/enricher.db" not in dbs:
        raise Refuse("old prod has no data/enricher.db")
    copied_max = None
    for rel in dbs:
        src, dst = cfg.old_prod / rel, cfg.new_enricher / rel
        t0 = time.time()
        online_backup(src, dst)
        ok, why = integrity_ok(dst)
        if not ok:
            raise Refuse(f"integrity_check of the copied {rel}: {why}")
        s_conn, _ = connect_ro(src)
        d_conn, _ = connect_ro(dst)
        try:
            a, b = db_snapshot(s_conn), db_snapshot(d_conn)
        finally:
            s_conn.close()
            d_conn.close()
        diffs = compare_snapshots(a, b)
        if diffs:
            raise Refuse(f"copied {rel} differs: " + "; ".join(diffs))
        if rel == "data/enricher.db":
            copied_max = a["max_tick_id"]
        log(f"C: {rel} backed up and verified in {time.time() - t0:.1f}s "
            f"(user_version={a['user_version']}, {len(a['counts'])} tables, "
            f"max tick {a['max_tick_id']})")

    copied = copy_untracked(cfg.old_prod, cfg.new_enricher, rels)
    for c in copied:
        log(f"C: carried over {c['path']} ({c['size']} bytes)")
    if not any(c["path"] == ".env.local" for c in copied):
        log("C: note — the old prod has no .env.local")

    try:
        h_old = run_health(cfg, cfg.old_prod, no_sync=True)
        h_new = run_health(cfg, cfg.new_enricher, no_sync=False)
    except (RuntimeError, ValueError) as exc:
        raise Refuse(f"health: {exc}") from exc
    diff = health_diff(h_old, h_new)
    if diff:
        raise Refuse(f"`cli health` differs between old and new prod in: {', '.join(diff)}")
    log("C: `cli health` identical in both checkouts (volatile keys dropped)")
    dirty = git_ok(cfg, cfg.new_prod, "status", "--porcelain", "--untracked-files=no").strip()
    if dirty:
        raise Refuse("new prod has tracked changes after `uv run` (lockfile rewritten?)")

    st.set_phase("COPIED", copied_max_tick_id=copied_max,
                 copy_sha256=sha256_file(cfg.new_enricher / "data" / "enricher.db"),
                 old_db_sha256=sha256_file(cfg.old_prod / "data" / "enricher.db"),
                 untracked_copied=[{"path": c["path"], "size": c["size"]} for c in copied])


# --------------------------------------------------------------------------- phase D
def phase_d_switch(cfg: Config, st: State) -> None:
    """Roles, then the plist write — THE switch point. Raises Refuse/Defer only
    BEFORE ``os.replace``; once it returns, prod is the new checkout."""
    log("D: swap")
    st.set_phase("SWAPPING", swap_started_at=now_iso())
    role = st.data.get("orig_old_role") or "prod\n"
    atomic_write_bytes(cfg.new_enricher / ".checkout-role", role.encode("utf-8"))
    atomic_write_bytes(cfg.new_prod / ".checkout-role", role.encode("utf-8"))
    atomic_write_bytes(cfg.old_prod / ".checkout-role", b"retiring\n")

    orig = cfg.plist_orig.read_bytes()
    if cfg.enricher_plist.read_bytes() != orig:
        raise Refuse("the enricher plist changed since phase C")
    info = parse_plist(orig)
    try:
        new_bytes = rewrite_plist_bytes(orig, str(info.workdir), str(cfg.new_enricher))
    except PlistRewriteError as exc:
        raise Refuse(f"plist rewrite: {exc}") from exc
    lint_ok, lint = plutil_lint(cfg, new_bytes)
    if not lint_ok:
        raise Refuse(f"plutil -lint rejected the rewritten plist: {lint}")
    mode = cfg.enricher_plist.stat().st_mode & 0o7777
    atomic_write_bytes(cfg.enricher_plist, new_bytes, mode=mode)  # <- the switch
    st.data.update(swap_epoch=time.time(), swapped_at=now_iso())
    st.event("plist now points at the new prod")
    st.save()
    log(f"D: plist now points at {cfg.new_enricher}")


def finish_swap(cfg: Config, st: State, launchd: Launchd) -> None:
    """D3 + D4, idempotent (a resumed run repeats them safely)."""
    want = str(cfg.new_enricher / WRAPPER_REL)
    if launchd.is_loaded():
        prog = launchd.program()
        if prog is not None and not same_path(prog, want):
            log(f"D: launchd still runs {prog}; unloading before loading the new plist")
            launchd.unload(cfg.enricher_plist)
            launchd.wait_loaded(False, 30)
    if not launchd.is_loaded():
        cp = launchd.load(cfg.enricher_plist)
        log(f"D: launchctl load -> {cp.returncode}")
    got = launchd.wait_program(want, 30)
    if got is None or not same_path(got, want):
        raise VerifyFailure(f"launchd runs {got!r}, not {want}")
    log(f"D: launchd program = {got}")
    release_our_lock(st, cfg.old_prod)
    owned = cfg.new_prod / OWNED_MARKER
    swapped = cfg.new_prod / SWAPPED_MARKER
    if not swapped.exists():
        atomic_write_bytes(swapped, (json.dumps({"swap_epoch": st.data.get("swap_epoch"),
                                                 "swapped_at": st.data.get("swapped_at")})
                                     + "\n").encode())
    owned.unlink(missing_ok=True)
    if st.phase != "SWAPPED":
        st.set_phase("SWAPPED")


# --------------------------------------------------------------------------- phase E
def phase_e(cfg: Config, st: State, launchd: Launchd) -> None:
    log("E: verify the first tick in the new prod")
    db = cfg.new_enricher / "data" / "enricher.db"
    copied_max = int(st.data["copied_max_tick_id"] or 0)
    clock = park_worker.WallClock(cfg.poll_s, log=log)
    start_dl = park_worker.Deadline(clock, cfg.first_tick_start_s)
    tick = first_tick_after(db, copied_max)
    while tick is None:
        if start_dl.expired():
            raise VerifyFailure(f"no tick started in the new prod within "
                                f"{cfg.first_tick_start_s:.0f}s of the swap")
        clock.sleep()
        tick = first_tick_after(db, copied_max)
    if st.data.get("first_tick_id") != tick.id:
        st.data["first_tick_id"] = tick.id
        st.event(f"first tick #{tick.id} started")
        st.save()
    log(f"E: first tick #{tick.id} is {tick.status}")
    close_dl = park_worker.Deadline(clock, cfg.first_tick_close_s)
    hard_dl = park_worker.Deadline(clock, cfg.first_tick_hard_cap_s)
    while tick.status == "running":
        if close_dl.expired():
            if hard_dl.expired():
                raise VerifyFailure(f"first tick #{tick.id} still running after the "
                                    f"{cfg.first_tick_hard_cap_s:.0f}s hard cap")
            idle = time.time() - db_mtime(db)
            if idle > cfg.progress_window_s:
                raise VerifyFailure(f"first tick #{tick.id} stalled: no DB write for {idle:.0f}s")
            close_dl.extend(cfg.progress_window_s)
            log(f"E: tick #{tick.id} still progressing (last DB write {idle:.0f}s ago); "
                f"extending by {cfg.progress_window_s:.0f}s")
        clock.sleep()
        tick = read_tick(db, tick.id) or tick
    ok, why = judge_first_tick(tick, recent_closed_ticks(
        cfg.old_prod / "data" / "enricher.db", copied_max))
    log(f"E: {why}")
    if not ok:
        raise VerifyFailure(why)
    if sha256_file(cfg.old_prod / "data" / "enricher.db") != st.data.get("old_db_sha256"):
        raise VerifyFailure("the old prod DB changed after the swap — something still runs there")
    if plist_where(cfg, read_plist(cfg.enricher_plist)) != "new":
        raise VerifyFailure("the plist no longer points at the new prod")
    st.set_phase("VERIFIED", first_tick={"id": tick.id, "status": tick.status,
                                         "claimed": tick.claimed, "classified": tick.classified,
                                         "sent": tick.sent}, verified_at=now_iso())


# --------------------------------------------------------------------------- phase F
def parse_github_slug(url: str) -> str | None:
    m = re.match(r"^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
                 r"([^/]+)/([^/]+?)(?:\.git)?/?$", url.strip())
    return f"{m.group(1)}/{m.group(2)}" if m else None


def jvn_browse_url(cfg: Config) -> str:
    base = cfg.jvn_remote_url[:-4] if cfg.jvn_remote_url.endswith(".git") else cfg.jvn_remote_url
    if base.startswith("https://github.com/"):
        return f"{base}/tree/main/{ENRICHER_SUBDIR}"
    return f"{base} ({ENRICHER_SUBDIR})"


def retired_note(cfg: Config, extra: str = "") -> str:
    return (
        f"{RETIRED_NOTE_HEADER} — do not edit here\n\n"
        f"The enricher now lives in the JVN monorepo at `{ENRICHER_SUBDIR}/` "
        f"({jvn_browse_url(cfg)}).\n\n"
        f"- Prod: `{cfg.new_enricher}` (launchd `{ENRICHER_LABEL}`; deploy only with its "
        "`scripts/deploy.sh <ref>`)\n"
        f"- Dev:  `{cfg.home}/developer/personal/Job-Visualizer-Notifier/{ENRICHER_SUBDIR}`\n"
        f"- Retired here on {now_iso()} by the JVN enricher cutover. Work in JVN instead.\n"
        + (f"\n{extra}\n" if extra else "")
    )


def write_retired_markers(cfg: Config, root: Path, extra: str = "") -> None:
    atomic_write_bytes(root / ".checkout-role", b"retired\n")
    note = root / "CLAUDE.local.md"
    existing = read_text(note)
    if existing is not None and not existing.startswith(RETIRED_NOTE_HEADER):
        note.rename(root / "CLAUDE.local.md.pre-retire")
    atomic_write_bytes(note, retired_note(cfg, extra).encode("utf-8"))


def unported_branches(cfg: Config, repo: Path) -> list[tuple[str, int]]:
    out = []
    for b in git(cfg, repo, "for-each-ref", "--format=%(refname:short)", "refs/heads").stdout.split():
        cp = git(cfg, repo, "rev-list", "--count", f"origin/main..{b}")
        if cp.returncode == 0 and cp.stdout.strip().isdigit() and int(cp.stdout) > 0:
            out.append((b, int(cp.stdout)))
    return out


BANNER = (
    "> **Moved.** This repository is retired and archived. The enricher now lives in "
    "the Job-Visualizer-Notifier monorepo at `src/enricher/`: {url}\n"
    "> Do not open PRs here.\n\n"
)


def _retire_step(st: State, name: str, fn: Callable[[], str]) -> None:
    done = st.data.setdefault("retire", {})
    if str(done.get(name, "")).startswith("ok"):
        return
    try:
        done[name] = fn()
    except Exception as exc:  # noqa: BLE001 — retirement is best effort, never rolls back
        done[name] = f"error: {exc}"
    log(f"F: {name}: {done[name]}")
    st.save()


def phase_f(cfg: Config, st: State) -> int:
    log("F: retire the old checkouts and the old repo (best effort)")
    old_url = git(cfg, cfg.old_prod, "remote", "get-url", "origin").stdout.strip()

    def markers_old_prod() -> str:
        write_retired_markers(cfg, cfg.old_prod,
                              "This directory is the pre-cutover rollback artifact; leave it "
                              "alone until Brendan deletes it.")
        return "ok"

    def markers_old_dev() -> str:
        if not (cfg.old_dev / ".git").exists():
            return f"skipped: {cfg.old_dev} is not a git checkout"
        branches = unported_branches(cfg, cfg.old_dev)
        lines = ["Local branches with commits not on origin/main (port them into JVN; "
                 "this repo is archived):"]
        lines += [f"- `{b}` ({n} commit{'s' if n != 1 else ''})" for b, n in branches] or ["- none"]
        lines += ["", "Port recipe, from the JVN checkout:", "```",
                  f"git -C {cfg.old_dev} format-patch origin/main..<branch> -o /tmp/<branch>",
                  "git am --directory=src/enricher /tmp/<branch>/*.patch", "```",
                  f"A bundle of every ref: `{cfg.state_dir / 'job-enricher-all-refs.bundle'}`."]
        write_retired_markers(cfg, cfg.old_dev, "\n".join(lines))
        return f"ok ({len(branches)} unported branch(es) listed)"

    def bundle() -> str:
        src = cfg.old_dev if (cfg.old_dev / ".git").exists() else cfg.old_prod
        dest = cfg.state_dir / "job-enricher-all-refs.bundle"
        cp = git(cfg, src, "bundle", "create", str(dest), "--all", timeout=cfg.net_timeout_s)
        if cp.returncode != 0:
            return f"error: git bundle failed: {tail(cp.stderr, 2)}"
        return f"ok ({dest}, {dest.stat().st_size} bytes)"

    def banner() -> str:
        if not old_url:
            return "skipped: old prod has no origin URL"
        work = cfg.state_dir / "job-enricher-banner"
        shutil.rmtree(work, ignore_errors=True)
        cp = run([cfg.git_bin, "clone", "--quiet", "--depth", "1", "--branch", "main", old_url,
                  str(work)], timeout=cfg.net_timeout_s)
        if cp.returncode != 0:
            return f"error: clone failed: {tail(cp.stderr, 2)}"
        text = BANNER.format(url=jvn_browse_url(cfg))
        changed = []
        for name in ("README.md", "CLAUDE.md"):
            p = work / name
            body = read_text(p)
            if body is None or body.startswith("> **Moved.**"):
                continue
            p.write_text(text + body, encoding="utf-8")
            changed.append(name)
        if not changed:
            shutil.rmtree(work, ignore_errors=True)
            return "ok (banner already present)"
        ident: list[str] = []
        if git(cfg, work, "config", "user.email").returncode != 0:
            ident = ["-c", "user.name=JVN enricher cutover",
                     "-c", "user.email=jvn-enricher-cutover@localhost"]
        git_ok(cfg, work, "add", *changed)
        git_ok(cfg, work, *ident, "commit", "--quiet", "-m",
               "docs: moved to Job-Visualizer-Notifier src/enricher")
        cp = git(cfg, work, "push", "--quiet", "origin", "HEAD:main", timeout=cfg.net_timeout_s)
        shutil.rmtree(work, ignore_errors=True)
        if cp.returncode != 0:
            return f"error: push rejected: {tail(cp.stderr, 2)}"
        return f"ok (pushed {', '.join(changed)})"

    def archive() -> str:
        slug = cfg.old_repo_slug or parse_github_slug(old_url)
        if not slug:
            return f"skipped: cannot parse owner/repo from {old_url!r}"
        cp = run([cfg.gh_bin, "repo", "archive", slug, "--yes"], timeout=60)
        if cp.returncode != 0:
            return f"error: gh repo archive {slug} failed ({cp.returncode}): {tail(cp.stderr, 2)}"
        return f"ok (archived {slug})"

    _retire_step(st, "markers_old_prod", markers_old_prod)
    _retire_step(st, "markers_old_dev", markers_old_dev)
    _retire_step(st, "bundle", bundle)
    _retire_step(st, "banner", banner)
    _retire_step(st, "archive", archive)

    r = st.data.get("retire", {})
    ft = st.data.get("first_tick") or {}
    yes = lambda k: "yes" if str(r.get(k, "")).startswith("ok") else "NO"  # noqa: E731
    notify(cfg, st, "DONE",
           f"DONE. Prod now runs from {cfg.new_enricher} @ {str(st.data.get('commit'))[:7]} "
           f"({st.data.get('ref')}). First tick #{ft.get('id')} ok (claimed {ft.get('claimed')}, "
           f"sent {ft.get('sent')}). Old repo README banner: {yes('banner')}; archived: "
           f"{yes('archive')}.")
    st.set_phase("DONE", done_at=now_iso())
    log("DONE")
    return EXIT_DONE


# --------------------------------------------------------------------------- rollback
def _term_pids(pids: list[int]) -> None:
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass


def park_new_for_rollback(cfg: Config, st: State, launchd: Launchd) -> None:
    ck = cfg.new_enricher
    res = park(cfg, st, launchd, ck, budget_s=cfg.rollback_park_budget_s, key="new_lock_payload")
    if not res.claimed:
        # A wedged tick: TERM its python stage first, so the wrapper still
        # writes back and closes the tick (the sleep-socket-hang runbook order).
        kids = [pid for pid, _pp, cmd in park_worker.list_processes()
                if str(ck) in cmd and "job_enricher.cli" in cmd]
        log(f"rollback: new prod tick wedged; TERM python stage pid(s) {kids}")
        _term_pids(kids)
        res = park(cfg, st, launchd, ck, budget_s=max(cfg.wrapper_exit_s * 5, 60),
                   key="new_lock_payload")
    if not res.claimed:
        log("rollback: still wedged; unloading and TERMing the wrapper")
        launchd.unload(cfg.enricher_plist)
        launchd.wait_loaded(False, 30)
        _term_pids(park_worker.wrapper_pids(ck / WRAPPER_REL))
        if not park_worker.wait_idle(ck / WRAPPER_REL, cfg.wrapper_exit_s):
            for pid in park_worker.wrapper_pids(ck / WRAPPER_REL):
                try:
                    os.kill(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
        res = park(cfg, st, launchd, ck, budget_s=max(cfg.wrapper_exit_s, 30),
                   key="new_lock_payload")
        if not res.claimed:
            raise RuntimeError(f"cannot park the new prod: {res.reason}")
    unload_and_quiesce(cfg, st, launchd, ck, cfg.enricher_plist)


def copy_db_back(cfg: Config, st: State) -> bool:
    """The new prod did work: put its DB in the old prod (no lost enrichment)."""
    new_db = cfg.new_enricher / "data" / "enricher.db"
    old_db = cfg.old_prod / "data" / "enricher.db"
    if st.data.get("rollback_db_copied"):
        return True
    if sha256_file(new_db) == st.data.get("copy_sha256"):
        log("rollback: the new prod DB is unchanged; no copy-back needed")
        return False
    holders = wait_no_holders(cfg, old_db, cfg.wrapper_exit_s)
    if holders:
        raise RuntimeError(f"old prod DB is open by {holders}; cannot copy back")
    tmp = old_db.with_name("enricher.db.rollback-tmp")
    online_backup(new_db, tmp)
    ok, why = integrity_ok(tmp)
    if not ok:
        raise RuntimeError(f"integrity_check of the copy-back: {why}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for suffix in ("-journal", "-wal", "-shm"):
        side = Path(f"{old_db}{suffix}")
        if side.exists():
            os.replace(side, old_db.with_name(f"enricher.db.pre-rollback-{stamp}{suffix}"))
    os.replace(old_db, old_db.with_name(f"enricher.db.pre-rollback-{stamp}"))
    os.replace(tmp, old_db)
    st.data["rollback_db_copied"] = True
    st.event(f"new prod DB copied back into the old prod (old kept as pre-rollback-{stamp})")
    st.save()
    log(f"rollback: copied the new prod DB back; the stale one is enricher.db.pre-rollback-{stamp}")
    return True


def rollback(cfg: Config, st: State, launchd: Launchd, reason: str) -> int:
    if st.phase != "ROLLING_BACK":
        st.set_phase("ROLLING_BACK", rollback_reason=reason, rollback_started_at=now_iso())
    reason = st.data.get("rollback_reason", reason)
    log(f"ROLLBACK: {reason}")
    try:
        orig = cfg.plist_orig.read_bytes()
        old_wrapper = str(cfg.old_prod / WRAPPER_REL)
        already_back = (cfg.enricher_plist.exists()
                        and cfg.enricher_plist.read_bytes() == orig
                        and launchd.is_loaded()
                        and same_path(launchd.program() or "", old_wrapper))
        if not already_back:
            if cfg.new_enricher.exists():
                park_new_for_rollback(cfg, st, launchd)
            copied = copy_db_back(cfg, st) if cfg.new_enricher.exists() else False
            st.data["rollback_db_copied"] = bool(st.data.get("rollback_db_copied") or copied)
            if launchd.is_loaded():
                launchd.unload(cfg.enricher_plist)
                launchd.wait_loaded(False, 30)
            atomic_write_bytes(cfg.enricher_plist, orig)
            restore_old_role(cfg, st)
            for p in (cfg.new_enricher / ".checkout-role", cfg.new_prod / ".checkout-role"):
                if p.parent.exists():
                    atomic_write_bytes(p, b"failed-cutover\n")
            launchd.load(cfg.enricher_plist)
            got = launchd.wait_program(old_wrapper, 30)
            if got is None or not same_path(got, old_wrapper):
                raise RuntimeError(f"after restoring the plist launchd runs {got!r}")
        release_our_lock(st, cfg.old_prod)
        release_our_lock(st, cfg.new_enricher)
    except Exception as exc:  # noqa: BLE001 — never leave a half rollback silent
        log(f"ROLLBACK STUCK: {exc}")
        notify(cfg, st, "ROLLBACK_STUCK",
               f"ROLLBACK INCOMPLETE ({exc}). The watcher retries every 5 min. "
               f"Original plist: {cfg.plist_orig}")
        return EXIT_DEFERRED
    copied = "yes" if st.data.get("rollback_db_copied") else "no (unchanged)"
    notify(cfg, st, "ROLLED_BACK",
           f"ROLLED BACK to {cfg.old_prod}: {reason}. New prod DB copied back: {copied}. "
           f"{cfg.new_prod} kept for diagnosis (.checkout-role=failed-cutover). "
           "Re-arming needs a human (scripts/cutover/README.md).")
    st.set_phase("ROLLED_BACK", rolled_back_at=now_iso())
    return EXIT_ROLLED_BACK


# --------------------------------------------------------------------------- driver
@dataclass
class Reality:
    where: str
    new_exists: bool
    new_owned: bool
    new_swapped: bool


def observe(cfg: Config) -> Reality:
    info = read_plist(cfg.enricher_plist)
    return Reality(
        where=plist_where(cfg, info),
        new_exists=cfg.new_prod.exists(),
        new_owned=(cfg.new_prod / OWNED_MARKER).is_file(),
        new_swapped=(cfg.new_prod / SWAPPED_MARKER).is_file(),
    )


def delete_owned_new_prod(cfg: Config) -> None:
    p = cfg.new_prod
    if not (p / OWNED_MARKER).is_file():
        raise Refuse(f"{p} has no {OWNED_MARKER}; refusing to delete it")
    rp = p.resolve()
    for forbidden in (cfg.home, cfg.old_prod, cfg.old_dev, cfg.state_dir, Path("/")):
        try:
            fr = forbidden.resolve()
        except OSError:
            continue
        if rp == fr or fr.is_relative_to(rp):
            raise Refuse(f"refusing to delete {p}: it is or contains {forbidden}")
    log(f"removing the half-built new prod {p} (it carries {OWNED_MARKER})")
    shutil.rmtree(p)


def _record_deferral(cfg: Config, st: State, reason: str) -> None:
    st.data["deferrals"] = int(st.data.get("deferrals", 0)) + 1
    st.data["last_deferral"] = {"at": now_iso(), "reason": reason}
    st.event(f"deferred: {reason}")
    st.save()
    if st.data["deferrals"] >= cfg.defer_alert_after:
        notify(cfg, st, "DEFERRED:repeated",
               f"still waiting after {st.data['deferrals']} tries; last reason: {reason}")


def mark_new_failed(cfg: Config) -> None:
    """A refused, half-built new prod must never look like a prod checkout."""
    if not (cfg.new_prod / OWNED_MARKER).is_file():
        return
    for p in (cfg.new_enricher / ".checkout-role", cfg.new_prod / ".checkout-role"):
        if p.parent.exists():
            try:
                atomic_write_bytes(p, b"failed-cutover\n")
            except OSError:
                pass


def _fail(cfg: Config, st: State, reason: str) -> int:
    log(f"FAILED: {reason}")
    mark_new_failed(cfg)
    st.set_phase("FAILED", failed_reason=reason, failed_at=now_iso())
    notify(cfg, st, "FAILED", f"FAILED before any swap; nothing changed in prod. Reason: {reason}")
    return EXIT_FAILED


def drive(cfg: Config, st: State, launchd: Launchd) -> int:
    r = observe(cfg)
    action = decide_resume(st.phase, r.where, r.new_exists, r.new_owned, st.exists)
    log(f"start: phase={st.phase} plist->{r.where} new_prod exists={r.new_exists} "
        f"owned={r.new_owned} -> {action}")
    if action in RESUME_EXIT:
        return RESUME_EXIT[action]
    if action in REFUSALS:
        return _fail(cfg, st, REFUSALS[action])
    if action == "rollback":
        return rollback(cfg, st, launchd, st.data.get("rollback_reason", "resumed rollback"))
    if action == "retire":
        return phase_f(cfg, st)

    if action in ("start", "redo"):
        st.save()
        try:
            restore_old_role(cfg, st)
            if action == "redo":
                delete_owned_new_prod(cfg)
            if st.phase != "PENDING":
                st.set_phase("PENDING")
            phase_a(cfg, st, launchd)
            phase_b(cfg, st, launchd)
            phase_c(cfg, st, launchd)
            phase_d_switch(cfg, st)
        except (Defer, Refuse, Exception) as exc:  # noqa: BLE001
            if observe(cfg).where == "new":  # the switch happened after all
                return rollback(cfg, st, launchd, f"after the swap: {exc}")
            unpark_old(cfg, st, launchd)
            if isinstance(exc, Defer):
                log(f"DEFERRED: {exc}")
                _record_deferral(cfg, st, str(exc))
                if st.phase != "PENDING":
                    st.set_phase("PENDING")
                return EXIT_DEFERRED
            reason = str(exc) if isinstance(exc, Refuse) else f"unexpected {type(exc).__name__}: {exc}"
            return _fail(cfg, st, reason)

    try:
        finish_swap(cfg, st, launchd)
        phase_e(cfg, st, launchd)
    except Exception as exc:  # noqa: BLE001 — every post-swap failure rolls back
        reason = str(exc) if isinstance(exc, VerifyFailure) else f"{type(exc).__name__}: {exc}"
        return rollback(cfg, st, launchd, reason)
    return phase_f(cfg, st)


def run_mode(cfg: Config) -> int:
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    LOG.file = cfg.state_dir / "cutover.log"
    flight = SingleFlight(cfg.state_dir)
    if not flight.acquire():
        log("another cutover is running; deferring")
        return EXIT_DEFERRED
    try:
        st = State.load(cfg.state_file)
        return drive(cfg, st, Launchd(cfg))
    finally:
        flight.release()


# --------------------------------------------------------------------------- rehearse
def rehearse(cfg: Config, scratch: Path, jvn_repo: Path | None) -> int:
    """Phases A + C into ``scratch``: no launchd call, no write to the old prod,
    no state dir. The live DB is read with one online backup (a shared lock of
    a few seconds); ``.env.local`` is NOT copied, so the scratch checkout can
    never reach real JVN."""
    t_all = time.time()
    try:
        scratch.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log(f"--scratch {scratch}: {exc}")
        return EXIT_USAGE
    if any(scratch.iterdir()):
        log(f"--scratch {scratch} must be empty")
        return EXIT_USAGE
    report: dict[str, Any] = {"started_at": now_iso(), "steps": {}}

    def step(name: str, t0: float, **info: Any) -> None:
        report["steps"][name] = {"seconds": round(time.time() - t0, 1), **info}
        log(f"rehearse: {name} done in {time.time() - t0:.1f}s")

    rep = Report()
    _local_checks(cfg, Launchd(cfg), rep, in_run=False)
    tree = rep.extras.get("app_tree")
    interp = rep.extras.get("interpreter")
    if not tree or not interp:
        log("rehearse: old prod tree or interpreter unavailable")
        return EXIT_FAILED
    t0 = time.time()
    repo = jvn_repo
    if repo is None:
        repo = scratch / "jvn.git"
        cp = run([cfg.git_bin, "clone", "--bare", "--quiet", cfg.jvn_remote_url, str(repo)],
                 timeout=cfg.net_timeout_s)
        if cp.returncode != 0:
            log(f"rehearse: cannot fetch JVN: {tail(cp.stderr, 2)}")
            return EXIT_DEFERRED
    m = derive_ref(cfg, repo, tree)
    if m is None:
        log(f"rehearse: no JVN ref matches the old prod tree {tree}")
        return EXIT_FAILED
    step("derive_ref", t0, ref=m.ref, commit=m.commit, source=m.source)
    dest = scratch / "enricher-prod"
    t0 = time.time()
    make_clone(cfg, repo, dest, m.commit)
    try:
        verify_clone(cfg, dest, tree)
    except Refuse as exc:
        log(f"rehearse: {exc}")
        return EXIT_FAILED
    step("clone", t0)
    t0 = time.time()
    try:
        sync_and_compare_venv(cfg, Path(interp), dest / ENRICHER_SUBDIR)
    except (Defer, Refuse, RuntimeError) as exc:
        log(f"rehearse: {exc}")
        return EXIT_FAILED
    step("uv_sync_and_equivalence", t0)
    atomic_write_bytes(dest / ENRICHER_SUBDIR / ".checkout-role", b"rehearsal\n")
    rels = list_untracked(cfg, cfg.old_prod)
    for rel in sorted(r for r in rels if classify_untracked(r) == "db"):
        t0 = time.time()
        dst = dest / ENRICHER_SUBDIR / rel
        online_backup(cfg.old_prod / rel, dst)
        b1 = time.time() - t0
        ok, why = integrity_ok(dst)
        conn, _ = connect_ro(dst)
        try:
            snap = db_snapshot(conn)
        finally:
            conn.close()
        step(f"backup:{rel}", t0, backup_seconds=round(b1, 1), integrity=why,
             user_version=snap["user_version"], max_tick_id=snap["max_tick_id"],
             counts=snap["counts"])
        if not ok:
            return EXIT_FAILED
    t0 = time.time()
    copied = copy_untracked(cfg.old_prod, dest / ENRICHER_SUBDIR, rels, skip={".env.local"})
    step("untracked_copy", t0, files=[{"path": c["path"], "size": c["size"]} for c in copied],
         skipped=[".env.local"])
    t0 = time.time()
    try:
        h = run_health(cfg, dest / ENRICHER_SUBDIR, no_sync=False)
    except (RuntimeError, ValueError) as exc:
        log(f"rehearse: health failed: {exc}")
        return EXIT_FAILED
    step("health", t0, classify_engine=h.get("classify_engine"),
         judge_engine=h.get("judge_engine"), keys=sorted(normalize_health(h)))
    report["total_seconds"] = round(time.time() - t_all, 1)
    out = scratch / "rehearsal.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    log(f"rehearse: PASS in {report['total_seconds']}s; report {out}")
    return EXIT_DONE


# --------------------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="cutover.sh", description=__doc__.split("\n\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight", action="store_true", help="read-only report")
    mode.add_argument("--rehearse", action="store_true", help="A + C into --scratch")
    mode.add_argument("--run", action="store_true", help="the resumable cutover")
    mode.add_argument("--status", action="store_true", help="print the state file")
    ap.add_argument("--jvn-repo", type=Path, help="derive the ref from this local JVN repo")
    ap.add_argument("--json", action="store_true", help="--preflight: JSON on stdout")
    ap.add_argument("--scratch", type=Path, help="--rehearse: an empty directory")
    return ap


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return EXIT_USAGE if exc.code else EXIT_DONE
    cfg = Config.from_env(env)
    if args.rehearse and not args.scratch:
        print("--rehearse needs --scratch DIR", file=sys.stderr)
        return EXIT_USAGE
    if args.status:
        text = read_text(cfg.state_file)
        print(text.rstrip() if text else f"no cutover state at {cfg.state_file}")
        return EXIT_DONE
    if args.preflight:
        LOG.stream = sys.stderr if args.json else sys.stdout
        rep = preflight(cfg, Launchd(cfg), args.jvn_repo)
        if args.json:
            print(json.dumps({"ok": rep.ok, "generated_at": now_iso(),
                              "checks": [asdict(c) for c in rep.checks], **rep.extras},
                             indent=2, sort_keys=True, default=str))
            print_report(rep, sys.stderr)
        else:
            print_report(rep, sys.stdout)
        return EXIT_DONE if rep.ok else EXIT_FAILED
    if args.rehearse:
        return rehearse(cfg, args.scratch, args.jvn_repo)
    return run_mode(cfg)


if __name__ == "__main__":
    sys.exit(main())
