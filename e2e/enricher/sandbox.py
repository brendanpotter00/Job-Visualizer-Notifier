"""Build, guard and collect the throwaway enricher checkout this section runs.

WHY A SANDBOX COPY, NOT ``src/enricher`` ITSELF. Every durable path the
enricher has is PACKAGE-RELATIVE (``store.REPO_ROOT = parents[2]``): the
SQLite DB, the tick lock and the chunk directory live wherever the package
source lives. Running the dev tree would create ``src/enricher/data/`` in the
owner's checkout. So the gate copies the tree somewhere else, syncs its own
venv, writes its own ``.env.local`` and PROVES the isolation before any case
runs: ``REPO_ROOT`` printed by the sandbox's own interpreter must equal the
sandbox directory, or the run refuses.

WHERE. Under ``$TMPDIR/jvn-e2e-<repo hash>/enricher-sandbox/<run id>/`` —
outside the repo, so ``vercel dev``'s whole-repo watcher never sees a venv
appear and vanish. ``run.sh`` copies the sandbox's ``data/`` into the run's
artifacts on the way out, then removes the sandbox (``--keep-up`` keeps it).

WHAT. The working tree by default (so uncommitted edits are what gets tested),
or ``git archive <ref>:src/enricher`` with ``--enricher-ref`` — notably
``enricher-prod-eeff1c9``, the exact code the cutover will put in prod.

Subcommands::

    sandbox.py build   --root DIR [--ref REF] --env-file env.enricher --out sandbox.json
    sandbox.py guard   --root DIR
    sandbox.py collect --root DIR --to ARTIFACTS_SUBDIR

``tick_env()`` is the ONE definition of the environment every enricher process
in this section runs under; ``api/conftest.py`` imports it.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_HERE = Path(__file__).resolve()
REPO_ROOT = _HERE.parents[2]
DEV_ENRICHER = REPO_ROOT / "src" / "enricher"

#: The wrapper hardcodes this path (``UV_BIN=/opt/homebrew/bin/uv``); the gate
#: uses the same binary so "the sandbox synced" and "the wrapper ran" agree.
UV_BIN = "/opt/homebrew/bin/uv"
#: The prod plist's EnvironmentVariables.PATH, verbatim.
LAUNCHD_PATH = "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
STUB_PORT = 8215
BACKEND_PORT = 8207
REAL_OLLAMA_PORT = 11434
LOOPBACK = ("127.0.0.1", "localhost")

#: Checkouts the sandbox may never live in, and never be confused with.
FORBIDDEN_ROOTS = tuple(
    Path.home() / "developer" / "personal" / name
    for name in ("app", "enricher-prod", "job-enricher")
)

#: Never copied from the working tree. `.env.local`/`.env` above all: the dev
#: checkout's may hold a real key, and the sandbox writes its own test values.
RSYNC_EXCLUDES = (
    ".venv", "data", ".env", ".env.local", ".checkout-role", "CLAUDE.local.md",
    "__pycache__", "*.pyc", ".pytest_cache", ".coverage", ".idea",
    "dashboard/node_modules", "dashboard/dist",
)


def tick_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """The environment an enricher process gets here — launchd's, plus three
    e2e-only locks.

    launchd hands a job HOME/USER/LOGNAME/SHELL/TMPDIR plus the plist's PATH and
    NOTHING from anybody's shell, so the enricher's config comes from
    ``.env.local`` alone, exactly as in prod. Building the env from scratch (not
    from ``os.environ``) also means an ``OLLAMA_BASE_URL``/``JVN_BASE_URL``/
    ``INTERNAL_API_KEY`` exported in the shell that ran the gate can never leak
    into a tick.

    The e2e-only additions, none of which changes what the wrapper does:

    * ``UV_OFFLINE=1`` — ``uv run`` may not reach the network mid-tick.
    * every proxy variable points at ``127.0.0.1:9`` (discard; nothing listens)
      with ``NO_PROXY`` = loopback, so any non-loopback HTTP the enricher tried
      would fail fast instead of leaving the machine.
    * ``ENRICH_TICK_TIMEOUT_SECS=600`` — each tick leaves its watchdog's
      ``sleep`` behind as an orphan when it finishes (pre-existing, harmless);
      ten minutes instead of three hours keeps a gate run from leaving dozens.
      No case runs anywhere near it.
    """
    env = {
        "HOME": os.environ["HOME"],
        "USER": os.environ.get("USER", ""),
        "LOGNAME": os.environ.get("LOGNAME", os.environ.get("USER", "")),
        "SHELL": "/bin/sh",
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
        "PATH": LAUNCHD_PATH,
        "UV_OFFLINE": "1",
        "ENRICH_TICK_TIMEOUT_SECS": "600",
    }
    dead_proxy = "http://127.0.0.1:9"
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        env[key] = dead_proxy
        env[key.lower()] = dead_proxy
    env["NO_PROXY"] = env["no_proxy"] = "127.0.0.1,localhost"
    if extra:
        for key, value in extra.items():
            if key in ("JVN_BASE_URL", "OLLAMA_BASE_URL"):
                assert_loopback(key, value)
            env[key] = value
    return env


def assert_loopback(name: str, url: str, *, port: int | None = None) -> None:
    parsed = urlparse(url)
    if parsed.hostname not in LOOPBACK:
        raise SystemExit(f"sandbox: {name}={url!r} is not loopback — refusing")
    if parsed.port == REAL_OLLAMA_PORT:
        raise SystemExit(f"sandbox: {name}={url!r} is the REAL ollama (:11434) — refusing")
    if port is not None and parsed.port != port:
        raise SystemExit(f"sandbox: {name}={url!r} must be on :{port}")


def _refuse_forbidden(path: Path) -> None:
    resolved = path.resolve()
    for root in FORBIDDEN_ROOTS + (DEV_ENRICHER,):
        root = root.resolve() if root.exists() else root
        if resolved == root or root in resolved.parents:
            raise SystemExit(f"sandbox: {resolved} is inside {root} — refusing to build there")


def _run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None,
         check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise SystemExit(
            f"sandbox: {' '.join(cmd)} exited {proc.returncode}\n{proc.stdout}\n{proc.stderr}"
        )
    return proc


def cli(sandbox: Path, *args: str, extra_env: dict[str, str] | None = None,
        check: bool = True) -> subprocess.CompletedProcess[str]:
    """``uv run python -m job_enricher.cli <args>`` inside the sandbox, under
    :func:`tick_env` — the same command shape the wrapper uses."""
    return _run([UV_BIN, "run", "python", "-m", "job_enricher.cli", *args],
                cwd=sandbox, env=tick_env(extra_env), check=check)


def _parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


def build(root: Path, ref: str | None, env_file: Path, out: Path) -> dict[str, Any]:
    _refuse_forbidden(root)
    sandbox = root / "enricher"
    if sandbox.exists() and any(sandbox.iterdir()):
        raise SystemExit(f"sandbox: {sandbox} already exists and is not empty")
    sandbox.mkdir(parents=True, exist_ok=True)

    if ref:
        commit = _run(["git", "-C", str(REPO_ROOT), "rev-parse", f"{ref}^{{commit}}"]).stdout.strip()
        tree = _run(["git", "-C", str(REPO_ROOT), "rev-parse", f"{ref}:src/enricher"]).stdout.strip()
        archive = subprocess.Popen(
            ["git", "-C", str(REPO_ROOT), "archive", f"{ref}:src/enricher"],
            stdout=subprocess.PIPE,
        )
        untar = subprocess.run(["tar", "-x", "-C", str(sandbox)], stdin=archive.stdout)
        archive.stdout.close()  # type: ignore[union-attr]
        if archive.wait() != 0 or untar.returncode != 0:
            raise SystemExit(f"sandbox: git archive {ref}:src/enricher failed")
        source = f"ref {ref} @ {commit[:12]} (src/enricher tree {tree[:12]})"
        dirty = False
    else:
        commit = _run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"]).stdout.strip()
        tree = None
        excludes = [arg for pat in RSYNC_EXCLUDES for arg in ("--exclude", pat)]
        _run(["rsync", "-a", *excludes, f"{DEV_ENRICHER}/", f"{sandbox}/"])
        dirty = bool(_run(["git", "-C", str(REPO_ROOT), "status", "--porcelain", "--",
                           "src/enricher"]).stdout.strip())
        source = f"working tree @ HEAD {commit[:12]}{' + uncommitted changes' if dirty else ''}"

    # Network is allowed for THIS step only (a cold uv cache downloads wheels);
    # every tick afterwards runs with UV_OFFLINE=1.
    sync_env = {k: v for k, v in tick_env().items() if k != "UV_OFFLINE"}
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        sync_env.pop(key, None)
    _run([UV_BIN, "sync", "--frozen", "--python", "3.12"], cwd=sandbox, env=sync_env)

    values = _parse_env_file(env_file)
    key = values.get("INTERNAL_API_KEY", "")
    if not key or "not-a-secret" not in key:
        raise SystemExit(f"sandbox: {env_file} must carry the TEST INTERNAL_API_KEY")
    (sandbox / ".env.local").write_text(
        "# Written by e2e/enricher/sandbox.py. TEST VALUES ONLY.\n"
        f"JVN_BASE_URL=http://127.0.0.1:{BACKEND_PORT}\n"
        f"INTERNAL_API_KEY={key}\n"
        f"OLLAMA_BASE_URL=http://127.0.0.1:{STUB_PORT}\n",
        encoding="utf-8",
    )
    (sandbox / ".checkout-role").write_text("e2e-sandbox\n", encoding="utf-8")

    cli(sandbox, "--help")  # the CLI must at least import under tick_env
    repo_root = _run(
        [UV_BIN, "run", "python", "-c",
         "from job_enricher.store import REPO_ROOT; print(REPO_ROOT)"],
        cwd=sandbox, env=tick_env(),
    ).stdout.strip().splitlines()[-1]
    if Path(repo_root).resolve() != sandbox.resolve():
        raise SystemExit(
            f"sandbox: ISOLATION FAILED — job_enricher.store.REPO_ROOT is {repo_root}, not "
            f"{sandbox}. The enricher would write its DB/lock somewhere else. Refusing."
        )
    v7 = cli(sandbox, "subcategory-push", "--help", check=False).returncode == 0
    # The FDE correction's scoped form (`reenrich --title-regex`); older refs lack it.
    scoped_reenrich = "--title-regex" in cli(sandbox, "reenrich", "--help", check=False).stdout
    info = {
        "root": str(root.resolve()),
        "dir": str(sandbox.resolve()),
        "ref": ref,
        "source": source,
        "commit": commit,
        "enricher_tree": tree,
        "dirty": dirty,
        "repo_root": repo_root,
        "v7": v7,
        "scoped_reenrich": scoped_reenrich,
        "taxonomy_version": cli(sandbox, "taxonomy-version").stdout.strip().splitlines()[-1],
        "uv": _run([UV_BIN, "--version"]).stdout.strip(),
    }
    out.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    return info


def guard(root: Path) -> None:
    """The boot guards, run before any case (PLAN.md §3.1)."""
    sandbox = root / "enricher"
    _refuse_forbidden(sandbox)
    values = _parse_env_file(sandbox / ".env.local")
    assert_loopback("OLLAMA_BASE_URL", values.get("OLLAMA_BASE_URL", ""), port=STUB_PORT)
    assert_loopback("JVN_BASE_URL", values.get("JVN_BASE_URL", ""), port=BACKEND_PORT)
    if "not-a-secret" not in values.get("INTERNAL_API_KEY", ""):
        raise SystemExit("sandbox: .env.local INTERNAL_API_KEY is not the committed test value")
    # `cli init` first, as the README's first-time setup does: `cli health` does
    # not create data/, and on a never-initialised checkout it fails with
    # "unable to open database file".
    cli(sandbox, "init")
    health = json.loads(cli(sandbox, "health").stdout)
    engines = (health.get("classify_engine"), health.get("judge_engine"))
    if engines != ("ollama", "ollama"):
        raise SystemExit(
            f"sandbox: cli health reports classify/judge engines {engines}, not ollama/ollama. "
            f"Any other engine could reach `claude -p`; refusing."
        )
    print(f"sandbox: guards OK — engines {engines}, stub :{STUB_PORT}, backend :{BACKEND_PORT}")


def collect(root: Path, to: Path) -> None:
    """Copy every data dir the run produced (the live one and each case's
    archived one) into the artifacts. Small: a few hundred KB of SQLite."""
    to.mkdir(parents=True, exist_ok=True)
    sources = [root / "enricher" / "data"]
    archive = root / "data-archive"
    if archive.is_dir():
        sources.extend(sorted(p for p in archive.iterdir() if p.is_dir()))
    for src in sources:
        if src.is_dir():
            dest = to / ("final" if src.name == "data" else src.name)
            shutil.copytree(src, dest, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("chunks"))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="enricher e2e sandbox")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--root", required=True, type=Path)
    b.add_argument("--ref", default=None)
    b.add_argument("--env-file", required=True, type=Path)
    b.add_argument("--out", required=True, type=Path)
    g = sub.add_parser("guard")
    g.add_argument("--root", required=True, type=Path)
    c = sub.add_parser("collect")
    c.add_argument("--root", required=True, type=Path)
    c.add_argument("--to", required=True, type=Path)
    args = p.parse_args(argv)
    if args.cmd == "build":
        info = build(args.root, args.ref, args.env_file, args.out)
        print(f"sandbox: built {info['dir']} from {info['source']} (v7={info['v7']}, "
              f"scoped_reenrich={info['scoped_reenrich']})")
    elif args.cmd == "guard":
        guard(args.root)
    else:
        collect(args.root, args.to)
    return 0


if __name__ == "__main__":
    sys.exit(main())
