"""The enricher-cutover sandbox (PLAN.md §2): one throwaway "machine" per case.

A ``Sandbox`` is a directory holding everything the cutover and the watcher can
touch, built from scratch:

* a fake ``HOME`` with ``Library/LaunchAgents/com.bp.job-enricher.plist`` (the
  real plist's shape, sandbox paths) and ``Library/Logs``;
* the OLD PROD at ``$HOME/developer/personal/app`` — a git repo whose tree is
  ``fixtures/fake_enricher`` (or, for CO-REAL, the prod tag's real tree), with a
  ``uv sync``-made ``.venv``, an initialised ``data/enricher.db``, an
  ``.env.local`` holding a CANARY secret, ``.checkout-role=prod`` and an
  untracked log; ``origin`` = a local bare "job-enricher" remote;
* the OLD DEV at ``$HOME/developer/personal/job-enricher`` — a clone of that
  remote with one unported local branch;
* a local bare repo standing in for GitHub JVN: a commit whose ``src/enricher``
  IS the old prod's tree (tagged ``enricher-prod-*`` unless a case says not to)
  and, when "merged", a ``main`` on top that adds ``src/enricher/scripts/
  {cutover,lib}`` copied from the scripts under test;
* PATH stubs: ``launchctl`` (fires the plist's program like launchd), ``gh``,
  and ``send.sh`` at the default ``~/.claude/skills/message-brendan/`` path.

Every knob the cutover has defaults from ``$HOME``; the sandbox sets HOME and
leaves the path knobs UNSET, so the defaults themselves are under test. It sets
only what must never default to the real machine: ``JVN_REMOTE_URL`` (a local
path), ``LAUNCHCTL``/``GH_BIN`` (the stubs), ``UV_BIN`` (real uv, OFFLINE), and
the scaled budgets. ``GIT_ALLOW_PROTOCOL=file`` makes git refuse any network
transport, and every proxy variable points at a dead loopback port.
"""

from __future__ import annotations

import hashlib
import json
import os
import plistlib
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterable

SECTION_DIR = Path(__file__).resolve().parent
REPO_ROOT = SECTION_DIR.parents[1]
FIXTURES = SECTION_DIR / "fixtures"
FAKE_TREE = FIXTURES / "fake_enricher"
STUBS = FIXTURES / "stubs"

ENRICHER_LABEL = "com.bp.job-enricher"
WATCHER_LABEL = "com.bp.jvn-enricher-cutover"
WRAPPER_REL = "scripts/enrich_tick_wrapper.sh"
CANARY = "CANARY-e2e-cutover-7f3a9c-not-a-real-key"
OLD_REPO_SLUG = "brendanpotter00/job-enricher"
FAKE_TAG = "enricher-prod-fake0001"
REAL_HOME = Path(os.path.expanduser("~")).resolve()

#: Budgets scaled from hours to seconds (PLAN.md §4.2 knobs).
BUDGETS = {
    "CUTOVER_PARK_BUDGET_S": "30",
    "CUTOVER_FIRST_TICK_START_S": "20",
    "CUTOVER_FIRST_TICK_CLOSE_S": "30",
    "CUTOVER_FIRST_TICK_HARD_CAP_S": "60",
    "CUTOVER_POLL_S": "0.3",
    "CUTOVER_LOCK_POLL_S": "0.1",
    "CUTOVER_WRAPPER_EXIT_S": "15",
    "CUTOVER_ROLLBACK_PARK_BUDGET_S": "15",
    "CUTOVER_PROGRESS_WINDOW_S": "10",
    "CUTOVER_DEFER_ALERT_AFTER": "24",
    "CUTOVER_NET_TIMEOUT_S": "60",
    "CUTOVER_UV_TIMEOUT_S": "300",
    "CUTOVER_HEALTH_TIMEOUT_S": "120",
    "CUTOVER_WATCHER_NET_TIMEOUT_S": "60",
}

#: Default per-checkout behaviour of the fake enricher (fake_enricher/job_enricher/cli.py).
DEFAULT_CONTROL = {
    "OLD_START": "1", "OLD_TICK_S": "1", "OLD_STATUS": "ok",
    "NEW_START": "1", "NEW_TICK_S": "1", "NEW_STATUS": "ok",
}


class SandboxError(AssertionError):
    pass


# --------------------------------------------------------------------------- host tools
def _which(name: str) -> str:
    p = shutil.which(name)
    if not p:
        raise SandboxError(f"`{name}` is not on PATH; the enricher-cutover section needs it")
    return p


class Host:
    """The real tools the sandbox borrows (resolved once, from the REAL env)."""

    def __init__(self) -> None:
        self.uv = _which("uv")
        self.git = _which("git")
        env = dict(os.environ, UV_PYTHON_DOWNLOADS="never")
        self.uv_cache = self._out([self.uv, "cache", "dir"], env)
        self.uv_python_dir = self._out([self.uv, "python", "dir"], env)
        # uv-MANAGED only: prod's venv is built on one, and its `bin/` has the
        # `python3` that cutover.sh and the cutover look for (a Homebrew keg's
        # versioned bin/ does not). CI installs it before the section runs.
        self.py312 = self._out([self.uv, "python", "find", "--managed-python", "3.12"], env,
                               missing="no uv-managed Python 3.12: run `uv python install 3.12`")
        self.python = sys.executable

    @staticmethod
    def _out(cmd: list[str], env: dict[str, str], missing: str = "") -> str:
        cp = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=60)
        if cp.returncode != 0 or not cp.stdout.strip():
            raise SandboxError(missing or f"{' '.join(cmd)} failed: {cp.stderr.strip()}")
        return cp.stdout.strip().splitlines()[-1]


# --------------------------------------------------------------------------- small helpers
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tree_manifest(root: Path, *, skip: Callable[[Path], bool] = lambda p: False) -> dict[str, str]:
    """``{relpath: sha256 | 'link:<target>' | 'dir'}`` for every entry under ``root``."""
    out: dict[str, str] = {}
    if not root.exists():
        return out
    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        for name in sorted(dirnames):
            p = d / name
            if not skip(p):
                out[str(p.relative_to(root)) + "/"] = "dir"
        dirnames[:] = [n for n in dirnames if not skip(d / n)]
        for name in sorted(filenames):
            p = d / name
            if skip(p):
                continue
            rel = str(p.relative_to(root))
            if p.is_symlink():
                out[rel] = "link:" + os.readlink(p)
            else:
                try:
                    out[rel] = sha256_bytes(p.read_bytes())
                except OSError as exc:
                    out[rel] = f"unreadable:{exc.errno}"
    return out


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def wait_for(pred: Callable[[], Any], timeout: float, what: str, poll: float = 0.1) -> Any:
    end = time.time() + timeout
    while True:
        val = pred()
        if val:
            return val
        if time.time() >= end:
            raise SandboxError(f"timed out after {timeout:.0f}s waiting for {what}")
        time.sleep(poll)


def processes() -> list[tuple[int, int, str]]:
    out = subprocess.run(["/bin/ps", "-axww", "-o", "pid=,pgid=,command="], capture_output=True,
                         text=True, timeout=30).stdout
    rows = []
    for line in out.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            rows.append((int(parts[0]), int(parts[1]), parts[2]))
    return rows


def copy_scripts_under_test(dest: Path) -> Path:
    """``dest/src/enricher/scripts/{cutover,lib}`` from ``$E2E_CUTOVER_SRC`` (a
    directory holding ``cutover/`` and ``lib/`` — used to prove the cases bite)
    or from this working tree. Returns ``dest``."""
    src = Path(os.environ.get("E2E_CUTOVER_SRC") or REPO_ROOT / "src" / "enricher" / "scripts")
    for sub in ("cutover", "lib"):
        if not (src / sub).is_dir():
            raise SandboxError(f"scripts under test: {src / sub} is missing")
        shutil.copytree(src / sub, dest / "src" / "enricher" / "scripts" / sub,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return dest


# --------------------------------------------------------------------------- the sandbox
class Sandbox:
    def __init__(self, root: Path, host: Host, scripts_src: Path, *,
                 real_tag: str | None = None, interval_s: float = 1.0) -> None:
        self.root = root.resolve()
        if self.root == REAL_HOME or self.root.is_relative_to(REAL_HOME / "developer"):
            raise SandboxError(f"refusing a sandbox inside the real developer tree: {self.root}")
        self.host = host
        self.scripts_src = scripts_src
        self.real_tag = real_tag
        self.interval_s = interval_s
        self.home = self.root / "home"
        self.bin = self.root / "bin"
        self.tmp = self.root / "tmp"
        self.launchd = self.root / "launchd"
        self.logs = self.root / "logs"
        self.remotes = self.root / "remotes"
        self.tree = self.root / "tree"
        personal = self.home / "developer" / "personal"
        self.old = personal / "app"
        self.new = personal / "enricher-prod"
        self.new_enricher = self.new / "src" / "enricher"
        self.old_dev = personal / "job-enricher"
        self.state_dir = self.home / "Library" / "Application Support" / "jvn-enricher-cutover"
        self.plist = self.home / "Library" / "LaunchAgents" / f"{ENRICHER_LABEL}.plist"
        self.watcher_plist = self.home / "Library" / "LaunchAgents" / f"{WATCHER_LABEL}.plist"
        self.send_sh = self.home / ".claude" / "skills" / "message-brendan" / "send.sh"
        self.je_remote = self.remotes / "job-enricher.git"
        self.jvn_remote = self.remotes / "Job-Visualizer-Notifier.git"
        self.control = self.root / "control.env"
        self.events_path = self.root / "events.jsonl"
        self.stop_file = self.root / "STOP"
        self.send_log = self.logs / "send.log"
        self.gh_log = self.logs / "gh.log"
        self.runs: list[dict[str, Any]] = []
        self.env: dict[str, str] = {}
        self.plist_orig: bytes = b""

    # ---------------------------------------------------------------- environment
    def base_env(self) -> dict[str, str]:
        user = os.environ.get("USER") or "e2e"
        dead = "http://127.0.0.1:9"
        env = {
            "HOME": str(self.home),
            "USER": user,
            "LOGNAME": user,
            "SHELL": "/bin/zsh",
            "TMPDIR": str(self.tmp) + "/",
            "LANG": "C",
            "PATH": ":".join([str(self.bin), str(Path(self.host.uv).parent),
                              str(Path(self.host.git).parent), "/usr/bin", "/bin",
                              "/usr/sbin", "/sbin"]),
            # uv: the real binary, cache and interpreters — and never the network.
            "UV_BIN": self.host.uv,
            "UV_CACHE_DIR": self.host.uv_cache,
            "UV_PYTHON_INSTALL_DIR": self.host.uv_python_dir,
            "UV_OFFLINE": "1",
            "UV_PYTHON_DOWNLOADS": "never",
            "UV_NO_PROGRESS": "1",
            # git: no system/global config, local transports only.
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_ALLOW_PROTOCOL": "file",
            "GIT_AUTHOR_NAME": "e2e", "GIT_AUTHOR_EMAIL": "e2e@example.invalid",
            "GIT_COMMITTER_NAME": "e2e", "GIT_COMMITTER_EMAIL": "e2e@example.invalid",
            "http_proxy": dead, "https_proxy": dead, "HTTP_PROXY": dead, "HTTPS_PROXY": dead,
            "ALL_PROXY": dead, "all_proxy": dead, "NO_PROXY": "", "no_proxy": "",
            # the knobs that must never default to the real machine
            "JVN_REMOTE_URL": str(self.jvn_remote),
            "LAUNCHCTL": str(self.bin / "launchctl"),
            "GH_BIN": str(self.bin / "gh"),
            "CUTOVER_OLD_REPO_SLUG": OLD_REPO_SLUG,
            **BUDGETS,
            # the stubs and the fake enricher
            "FAKE_LAUNCHD_DIR": str(self.launchd),
            "FAKE_INTERVAL_S": str(self.interval_s),
            "FAKE_UNLOAD_KILLS": "1",
            "FAKE_CONTROL": str(self.control),
            "FAKE_EVENTS": str(self.events_path),
            "FAKE_STOP_FILE": str(self.stop_file),
            "FAKE_NEW_ENRICHER": str(self.new_enricher),
            "FAKE_OLD_PROD": str(self.old),
            "FAKE_SEND_LOG": str(self.send_log),
            "FAKE_GH_LOG": str(self.gh_log),
            "FAKE_REAL_GIT": self.host.git,
        }
        return env

    def check_isolation(self) -> None:
        """Refuse to run anything if the env could reach the real machine."""
        e = self.env
        home = Path(e["HOME"]).resolve()
        if home == REAL_HOME or not home.is_relative_to(self.root):
            raise SandboxError(f"HOME {home} is not inside the sandbox")
        for k in ("CUTOVER_OLD_PROD", "CUTOVER_NEW_PROD", "CUTOVER_OLD_DEV", "CUTOVER_STATE_DIR",
                  "CUTOVER_ENRICHER_PLIST", "CUTOVER_SEND_SH", "CUTOVER_WATCHER_PLIST",
                  "CUTOVER_LAUNCHAGENTS_DIR"):
            if k in e and not Path(e[k]).resolve().is_relative_to(self.root):
                raise SandboxError(f"{k}={e[k]} points outside the sandbox")
        if not Path(e["JVN_REMOTE_URL"]).resolve().is_relative_to(self.root):
            raise SandboxError("JVN_REMOTE_URL is not a sandbox path")
        for k in ("LAUNCHCTL", "GH_BIN"):
            if not Path(e[k]).resolve().is_relative_to(self.root):
                raise SandboxError(f"{k} is not the sandbox stub")
        found = shutil.which("launchctl", path=e["PATH"])
        if not found or not Path(found).resolve().is_relative_to(self.root):
            raise SandboxError(f"`launchctl` on the sandbox PATH resolves to {found}, not the stub")
        if e.get("GIT_ALLOW_PROTOCOL") != "file" or e.get("UV_OFFLINE") != "1":
            raise SandboxError("the no-network guards (GIT_ALLOW_PROTOCOL=file, UV_OFFLINE=1) are off")

    # ---------------------------------------------------------------- commands
    def sh(self, cmd: list[str], *, cwd: Path | None = None, check: bool = True,
           env: dict[str, str] | None = None, timeout: float = 300,
           input: str | None = None) -> subprocess.CompletedProcess[str]:
        cp = subprocess.run([str(c) for c in cmd], cwd=None if cwd is None else str(cwd),
                            env=env or self.env, capture_output=True, text=True, timeout=timeout,
                            input=input, stdin=None if input is not None else subprocess.DEVNULL)
        if check and cp.returncode != 0:
            raise SandboxError(f"{' '.join(map(str, cmd))} -> {cp.returncode}\n"
                               f"{cp.stdout[-2000:]}\n{cp.stderr[-2000:]}")
        return cp

    def git(self, repo: Path, *args: str, check: bool = True) -> str:
        return self.sh([self.host.git, "-C", str(repo), *args], check=check).stdout

    # ---------------------------------------------------------------- build
    def build(self, *, jvn: str = "merged", tag: bool = True, jvn_tree_variant: bool = False,
              marked_cutover: bool = False, load: bool = True,
              control: dict[str, str] | None = None,
              extra_env: dict[str, str] | None = None) -> "Sandbox":
        """``jvn``: ``merged`` (main has the cutover) | ``unmerged`` (main is the
        prod commit only). ``tag``: tag the prod commit ``enricher-prod-*``.
        ``jvn_tree_variant``: JVN's commit differs from the old prod by one file
        (so no JVN ref matches). ``marked_cutover``: main's cutover.sh is the
        WT-03 marker. ``load``: load the enricher plist into the stub launchd."""
        for d in (self.home, self.bin, self.tmp, self.launchd, self.logs, self.remotes,
                  self.home / "Library" / "LaunchAgents", self.home / "Library" / "Logs",
                  self.send_sh.parent, self.old.parent):
            d.mkdir(parents=True, exist_ok=True)
        self.env = {**self.base_env(), **(extra_env or {})}
        self._install_stubs()
        self.check_isolation()
        self.set_control(**{**DEFAULT_CONTROL, **(control or {})})
        self._make_tree()
        self._make_job_enricher_remote()
        self._make_old_prod()
        self._make_old_dev()
        self._make_jvn_remote(merged=(jvn == "merged"), tag=tag, variant=jvn_tree_variant,
                              marked=marked_cutover)
        self._write_plist()
        if load:
            self.launchctl("load", str(self.plist))
        return self

    def _install_stubs(self) -> None:
        for name in ("launchctl", "git_rogue"):
            text = (STUBS / name).read_text(encoding="utf-8")
            first, _, rest = text.partition("\n")
            assert first.startswith("#!"), name
            dest = self.bin / name
            dest.write_text(f"#!{self.host.python} -I\n{rest}", encoding="utf-8")
            dest.chmod(0o755)
        for name in ("gh", "plutil_crash"):
            shutil.copy2(STUBS / name, self.bin / name)
            (self.bin / name).chmod(0o755)
        shutil.copy2(STUBS / "send.sh", self.send_sh)
        self.send_sh.chmod(0o755)

    def _make_tree(self) -> None:
        if self.real_tag:
            self.tree.mkdir(parents=True)
            archive = subprocess.run(
                [self.host.git, "-C", str(REPO_ROOT), "archive", f"{self.real_tag}:src/enricher"],
                capture_output=True, timeout=120)
            if archive.returncode != 0:
                raise SandboxError(f"git archive {self.real_tag}:src/enricher failed: "
                                   f"{archive.stderr.decode(errors='replace')}")
            subprocess.run(["/usr/bin/tar", "-x", "-C", str(self.tree)], input=archive.stdout,
                           check=True, timeout=120)
        else:
            shutil.copytree(FAKE_TREE, self.tree, symlinks=True,
                            ignore=shutil.ignore_patterns("__pycache__", ".venv", "data"))
            # The real job-enricher repo has a CLAUDE.md beside its README (the
            # cutover's banner edits both). Generated here so the JVN repo does
            # not carry a CLAUDE.md under e2e/.
            (self.tree / "CLAUDE.md").write_text(
                "# fake job-enricher (e2e fixture)\n\nNot a real enricher; see README.md.\n",
                encoding="utf-8")

    def _make_job_enricher_remote(self) -> None:
        self.sh([self.host.git, "init", "--quiet", "--bare", "-b", "main", str(self.je_remote)])

    def _make_old_prod(self) -> None:
        shutil.copytree(self.tree, self.old, symlinks=True)
        g = lambda *a: self.git(self.old, *a)  # noqa: E731
        self.sh([self.host.git, "init", "--quiet", "-b", "main", str(self.old)])
        g("add", "-A")
        g("commit", "--quiet", "-m", "prod: the code the live worker runs")
        g("remote", "add", "origin", str(self.je_remote))
        g("push", "--quiet", "origin", "HEAD:main")
        g("fetch", "--quiet", "origin")
        g("branch", "--quiet", "--set-upstream-to=origin/main", "main")
        self.old_tree = g("rev-parse", "HEAD^{tree}").strip()
        if self.real_tag:
            want = self.sh([self.host.git, "-C", str(REPO_ROOT), "rev-parse",
                            f"{self.real_tag}:src/enricher"]).stdout.strip()
            if want != self.old_tree:
                raise SandboxError(f"the archived {self.real_tag} tree hashes to {self.old_tree}, "
                                   f"not {want}: the extraction changed the tree")
        self.sh([self.host.uv, "sync", "--frozen", "--quiet", "--python", self.host.py312],
                cwd=self.old, timeout=600)
        init = ["init"] if self.real_tag else ["init", "--seed-ticks", "3"]
        self.sh([self.host.uv, "run", "--frozen", "python", "-m", "job_enricher.cli", *init],
                cwd=self.old, timeout=300)
        env_local = self.old / ".env.local"
        env_local.write_text(
            "JVN_BASE_URL=http://127.0.0.1:9\n"
            f"INTERNAL_API_KEY={CANARY}\n"
            "OLLAMA_BASE_URL=http://127.0.0.1:9\n", encoding="utf-8")
        env_local.chmod(0o600)
        (self.old / ".checkout-role").write_text("prod\n", encoding="utf-8")
        (self.old / "data" / "classify-run-t1.log").write_text("an untracked tick log\n")
        self.old_head = g("rev-parse", "HEAD").strip()

    def _make_old_dev(self) -> None:
        self.sh([self.host.git, "clone", "--quiet", str(self.je_remote), str(self.old_dev)])
        (self.old_dev / ".checkout-role").write_text("dev\n", encoding="utf-8")
        g = lambda *a: self.git(self.old_dev, *a)  # noqa: E731
        g("checkout", "--quiet", "-b", "feat/unported")
        (self.old_dev / "unported.txt").write_text("work that never reached origin\n")
        g("add", "unported.txt")
        g("commit", "--quiet", "-m", "wip: unported")
        g("checkout", "--quiet", "main")

    def _make_jvn_remote(self, *, merged: bool, tag: bool, variant: bool, marked: bool) -> None:
        work = self.remotes / "jvn-work"
        self.sh([self.host.git, "init", "--quiet", "-b", "main", str(work)])
        shutil.copytree(self.tree, work / "src" / "enricher", symlinks=True)
        (work / "README.md").write_text("# fake Job-Visualizer-Notifier (e2e remote)\n")
        if variant:
            p = work / "src" / "enricher" / "README.md"
            p.write_text(p.read_text() + "\nJVN's copy differs from prod by this line.\n")
        g = lambda *a: self.git(work, *a)  # noqa: E731
        g("add", "-A")
        g("commit", "--quiet", "-m", "enricher: import (the code prod runs)")
        self.jvn_prod_commit = g("rev-parse", "HEAD").strip()
        self.jvn_tag = (self.real_tag or FAKE_TAG) if tag else None
        if self.jvn_tag:
            g("tag", self.jvn_tag)
        g("tag", "release-unrelated")  # a non-matching tag the lookup must ignore
        if merged:
            dst = work / "src" / "enricher" / "scripts"
            for sub in ("cutover", "lib"):
                shutil.copytree(self.scripts_src / "src" / "enricher" / "scripts" / sub, dst / sub,
                                dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            if marked:
                shutil.copy2(STUBS / "marked_cutover.sh", dst / "cutover" / "cutover.sh")
            g("add", "-A")
            g("commit", "--quiet", "-m", "enricher: add the cutover (the merged PR)")
        self.jvn_main = g("rev-parse", "HEAD").strip()
        self.sh([self.host.git, "init", "--quiet", "--bare", "-b", "main", str(self.jvn_remote)])
        g("push", "--quiet", str(self.jvn_remote), "main", "--tags")

    def _write_plist(self) -> None:
        d = {
            "Label": ENRICHER_LABEL,
            "ProgramArguments": [str(self.old / WRAPPER_REL)],
            "WorkingDirectory": str(self.old),
            "StartInterval": 60,
            "RunAtLoad": False,
            "StandardOutPath": str(self.home / "Library" / "Logs" / "job-enricher.log"),
            "StandardErrorPath": str(self.home / "Library" / "Logs" / "job-enricher.err"),
            "EnvironmentVariables": {
                "PATH": f"{Path(self.host.uv).parent}:/usr/bin:/bin:/usr/sbin:/sbin"},
        }
        self.plist_orig = plistlib.dumps(d, fmt=plistlib.FMT_XML)
        self.plist.write_bytes(self.plist_orig)
        self.plist.chmod(0o644)

    # ---------------------------------------------------------------- control + stubs
    def set_control(self, **kv: str) -> None:
        cur: dict[str, str] = {}
        if self.control.exists():
            for line in self.control.read_text().splitlines():
                if "=" in line:
                    k, _, v = line.partition("=")
                    cur[k.strip()] = v.strip()
        cur.update({k: str(v) for k, v in kv.items()})
        tmp = self.control.with_name(".control.tmp")
        tmp.write_text("".join(f"{k}={v}\n" for k, v in sorted(cur.items())))
        os.replace(tmp, self.control)

    def launchctl(self, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return self.sh([str(self.bin / "launchctl"), *args], check=False, env=env)

    def launchd_state(self) -> dict[str, Any]:
        try:
            return json.loads((self.launchd / "state.json").read_text())
        except (OSError, ValueError):
            return {}

    def loaded_program(self, label: str = ENRICHER_LABEL) -> str | None:
        info = self.launchd_state().get(label)
        return info["args"][0] if info else None

    def calls(self) -> list[dict[str, Any]]:
        return read_jsonl(self.launchd / "calls.jsonl")

    def jobs(self) -> list[dict[str, Any]]:
        return read_jsonl(self.launchd / "jobs.jsonl")

    def events(self) -> list[dict[str, Any]]:
        return read_jsonl(self.events_path)

    def texts(self) -> list[str]:
        if not self.send_log.exists():
            return []
        return [ln for ln in self.send_log.read_text().splitlines() if ln.strip()]

    def gh_calls(self) -> list[str]:
        if not self.gh_log.exists():
            return []
        return [ln for ln in self.gh_log.read_text().splitlines() if ln.strip()]

    # ---------------------------------------------------------------- the code under test
    def cutover_sh(self) -> Path:
        return self.scripts_src / "src" / "enricher" / "scripts" / "cutover" / "cutover.sh"

    def run_cutover(self, *args: str, env_extra: dict[str, str] | None = None,
                    timeout: float = 300, label: str = "") -> subprocess.CompletedProcess[str]:
        env = {**self.env, **(env_extra or {})}
        t0 = time.time()
        cp = subprocess.run(["/bin/sh", str(self.cutover_sh()), *args], env=env,
                            capture_output=True, text=True, timeout=timeout,
                            stdin=subprocess.DEVNULL, cwd=str(self.tmp))
        self.runs.append({"what": f"cutover.sh {' '.join(args)}", "label": label,
                          "rc": cp.returncode, "seconds": round(time.time() - t0, 1),
                          "stdout": cp.stdout, "stderr": cp.stderr})
        return cp

    def install_watcher_copy(self) -> Path:
        """What install_watcher.sh does to the script: a copy in the state dir."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        dest = self.state_dir / "watcher.sh"
        shutil.copy2(self.scripts_src / "src" / "enricher" / "scripts" / "cutover" / "watcher.sh",
                     dest)
        dest.chmod(0o755)
        return dest

    def run_watcher(self, *, env_extra: dict[str, str] | None = None, timeout: float = 300,
                    label: str = "", background: bool = False):
        watcher = self.state_dir / "watcher.sh"
        if not watcher.exists():
            self.install_watcher_copy()
        env = {**self.env, **(env_extra or {})}
        cmd = ["/bin/bash", str(watcher)]  # what the plist runs (macOS bash 3.2)
        if background:
            return subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, stdin=subprocess.DEVNULL, cwd=str(self.tmp))
        t0 = time.time()
        cp = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout,
                            stdin=subprocess.DEVNULL, cwd=str(self.tmp))
        self.runs.append({"what": "watcher.sh", "label": label, "rc": cp.returncode,
                          "seconds": round(time.time() - t0, 1), "stdout": cp.stdout,
                          "stderr": cp.stderr})
        return cp

    def output(self, n: int = 60) -> str:
        """The last run's output tail, for assertion messages."""
        if not self.runs:
            return "(nothing ran)"
        r = self.runs[-1]
        lines = (r["stdout"] + r["stderr"]).splitlines()
        return f"--- {r['what']} rc={r['rc']}\n" + "\n".join(lines[-n:])

    def all_output(self) -> str:
        return "\n".join(r["stdout"] + r["stderr"] for r in self.runs)

    def lifecycle_calls(self, label: str = ENRICHER_LABEL) -> list[dict[str, Any]]:
        """load/unload/remove calls for ``label`` (list/print are reads)."""
        return [c for c in self.calls()
                if c["argv"] and c["argv"][0] in ("load", "unload", "remove")
                and c.get("label") == label]

    def history(self, needle: str) -> int:
        return sum(1 for h in self.state().get("history", []) if needle in h.get("event", ""))

    def state(self) -> dict[str, Any]:
        try:
            return json.loads((self.state_dir / "state.json").read_text())
        except (OSError, ValueError):
            return {}

    def cutover_log(self) -> str:
        p = self.state_dir / "cutover.log"
        return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""

    # ---------------------------------------------------------------- databases
    def ticks(self, checkout: Path) -> list[dict[str, Any]]:
        db = checkout / "data" / "enricher.db"
        if not db.exists():
            return []
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute(
                "SELECT id, status, claimed, classified, sent FROM ticks ORDER BY id")]
        finally:
            conn.close()

    def lock_text(self, checkout: Path) -> str | None:
        try:
            return (checkout / "data" / ".tick.lock").read_text()
        except OSError:
            return None

    # ---------------------------------------------------------------- shared assertions
    def assert_old_prod_as_found(self, *, expect_loaded: bool = True) -> None:
        """Pre-swap failure contract: everything back exactly as found."""
        assert self.plist.read_bytes() == self.plist_orig, "the enricher plist changed"
        assert (self.old / ".checkout-role").read_text() == "prod\n", \
            f"old prod role is {(self.old / '.checkout-role').read_text()!r}"
        assert self.git(self.old, "rev-parse", "HEAD").strip() == self.old_head
        assert self.git(self.old, "status", "--porcelain", "--untracked-files=no").strip() == "", \
            "old prod has tracked changes"
        if expect_loaded:
            assert self.loaded_program() == str(self.old / WRAPPER_REL), \
                f"launchd runs {self.loaded_program()!r}, not the old prod"
        st = self.state()
        ours = set(st.get("our_lock_payloads", []))
        lock = self.lock_text(self.old)
        assert lock is None or lock not in ours, f"the cutover's lock was left behind: {lock!r}"

    # ---------------------------------------------------------------- teardown
    def kill_everything(self) -> list[int]:
        """Stop every process this sandbox started: fire loops, jobs (by process
        group), the rogue writer, and anything whose command line names it."""
        try:
            self.stop_file.write_text("stop\n")
        except OSError:
            pass
        me = os.getpid()
        pgids: set[int] = set()
        for rec in self.jobs():
            if rec.get("event") == "start" and rec.get("pid"):
                pgids.add(int(rec["pid"]))
        for info in self.launchd_state().values():
            if info.get("loop_pid"):
                pgids.add(int(info["loop_pid"]))
        root = str(self.root)
        victims = [pid for pid, _pg, cmd in processes() if root in cmd and pid != me]
        for pg in pgids:
            try:
                os.killpg(pg, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        for pid in victims:
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        return sorted(set(victims))

    def leftover_processes(self) -> list[str]:
        root = str(self.root)
        return [f"{pid} {cmd}" for pid, _pg, cmd in processes() if root in cmd and pid != os.getpid()]

    def collect(self, dest: Path) -> None:
        """Copy the evidence into the case's artifact dir — never .env.local."""
        dest.mkdir(parents=True, exist_ok=True)
        pick: Iterable[tuple[Path, str]] = [
            (self.state_dir / "state.json", "state.json"),
            (self.state_dir / "cutover.log", "cutover.log"),
            (self.launchd / "calls.jsonl", "launchctl-calls.jsonl"),
            (self.launchd / "jobs.jsonl", "launchd-jobs.jsonl"),
            (self.events_path, "fake-enricher-events.jsonl"),
            (self.send_log, "texts.log"),
            (self.gh_log, "gh.log"),
            (self.control, "control.env"),
            (self.home / "Library" / "Logs" / "job-enricher.log", "job-enricher.log"),
            (self.home / "Library" / "Logs" / "job-enricher.err", "job-enricher.err"),
            (self.home / "Library" / "Logs" / "jvn-enricher-cutover.log", "watcher-launchd.log"),
        ]
        for src, name in pick:
            if src.is_file():
                shutil.copy2(src, dest / name)
        for checkout, tag in ((self.old, "old-prod"), (self.new_enricher, "new-prod")):
            db = checkout / "data" / "enricher.db"
            if db.is_file():
                try:
                    s = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
                    d = sqlite3.connect(str(dest / f"{tag}-enricher.db"))
                    s.backup(d)
                    d.close()
                    s.close()
                except sqlite3.Error:
                    pass
        with open(dest / "runs.txt", "w", encoding="utf-8") as fh:
            for i, r in enumerate(self.runs, 1):
                fh.write(f"===== run {i}: {r['what']} {r['label']} -> rc={r['rc']} "
                         f"({r['seconds']}s)\n--- stdout\n{r['stdout']}\n--- stderr\n{r['stderr']}\n")
