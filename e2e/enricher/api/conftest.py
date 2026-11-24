"""pytest fixtures for the enricher section (PLAN.md §3).

Assumes ``e2e/enricher/run.sh`` already brought up: the backend on :8207 with
the internal-key middleware armed, ``stub_ollama.py`` on :8215, and a guarded
sandbox enricher (``sandbox.json`` in the run's artifacts). Starts nothing
itself except the short-lived kill-switch backend EN-08 needs, so a fix loop can
point pytest at a ``--keep-up`` stack.

What every case gets:

* ``sandbox``   — the throwaway enricher: ``fire()`` runs the REAL
  ``scripts/enrich_tick_wrapper.sh`` the way launchd does (direct exec, cwd =
  the checkout, launchd's env), ``cli()`` runs one CLI command, and readers for
  the sandbox's own SQLite DB (read-only).
* ``stub``      — the stub model's control endpoints and request log.
* ``http`` / ``db_conn`` — JVN, with the internal key / the section's database.
* ``step``      — ``step("what I am doing")``; a failing case's
  ``cases/<test>/step.txt`` names the last step in words.

Around EVERY case: the stub is reset to ``normal``, and the sandbox's ``data/``
is moved aside to ``data-archive/NN-<test>`` afterwards, so each case starts with
an empty local DB, no lock and no knobs (run.sh copies every archive into
artifacts).
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import httpx
import pytest

_HERE = Path(__file__).resolve()
_SECTION_DIR = _HERE.parents[1]
_REPO_ROOT = _HERE.parents[3]
for _p in (str(_SECTION_DIR), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fixtures  # noqa: E402
import sandbox as sandbox_mod  # noqa: E402
import seed  # noqa: E402

from e2e.shared.db import assertions as db  # noqa: E402

BASE_URL = os.environ.get("E2E_BACKEND_URL", "http://127.0.0.1:8207")
INTERNAL_KEY = os.environ.get("E2E_INTERNAL_API_KEY", "e2e-enricher-not-a-secret")
STUB_URL = os.environ.get("E2E_STUB_URL", "http://127.0.0.1:8215")
KILLSWITCH_PORT = int(os.environ.get("E2E_KILLSWITCH_PORT", "8206"))
PID_DIR = Path(os.environ.get("E2E_PID_DIR", str(_SECTION_DIR / ".pids")))
DB_DSN = seed.DEFAULT_DSN
ENV_FILE = _SECTION_DIR / "env.enricher"

ARTIFACTS_DIR = Path(
    os.environ.get("E2E_ARTIFACTS_DIR", str(_SECTION_DIR / "artifacts" / f"local-{int(time.time())}"))
)
CASES_DIR = ARTIFACTS_DIR / "cases"
SANDBOX_INFO_PATH = Path(os.environ.get("E2E_SANDBOX_INFO", str(ARTIFACTS_DIR / "sandbox.json")))


def _sanitize(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name)


# --- markers + ordering ----------------------------------------------------


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "fast: part of --fast (EN-00, EN-01, EN-04, EN-10)")
    config.addinivalue_line("markers", "slow: needs several ticks or a second backend")
    config.addinivalue_line(
        "markers", "v7: needs the v7 enricher (subcategories); deselected for a pre-v7 --enricher-ref"
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """EN-10 runs LAST: its dev-tree check is only meaningful after every other
    case has had its chance to write somewhere it should not."""
    items.sort(key=lambda it: 1 if "en10" in it.nodeid.lower() else 0)


# --- step tracking + step.txt ----------------------------------------------

_CURRENT_STEP: dict[str, str] = {}


@pytest.fixture()
def step(request: pytest.FixtureRequest):
    def _set(text: str) -> None:
        _CURRENT_STEP[request.node.nodeid] = text
        print(f"  [step] {text}")

    _set("setting up")
    return _set


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo) -> Iterator[None]:
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or not report.failed:
        return
    d = CASES_DIR / _sanitize(item.name)
    d.mkdir(parents=True, exist_ok=True)
    where = _CURRENT_STEP.get(item.nodeid, "(no step recorded)")
    (d / "step.txt").write_text(
        f"FAILED while: {where}\n\n{report.longrepr}\n", encoding="utf-8"
    )


@pytest.fixture()
def case_dir(request: pytest.FixtureRequest) -> Path:
    d = CASES_DIR / _sanitize(request.node.name)
    d.mkdir(parents=True, exist_ok=True)
    return d


# --- the stub ---------------------------------------------------------------


class Stub:
    def __init__(self, base: str) -> None:
        self.base = base

    def reset(self) -> None:
        httpx.post(f"{self.base}/__stub/reset", timeout=5.0).raise_for_status()

    def mode(self, mode: str, *, stage: str = "all", slow_s: float = 0.0) -> None:
        resp = httpx.post(
            f"{self.base}/__stub/mode",
            json={"mode": mode, "stage": stage, "slow_s": slow_s},
            timeout=5.0,
        )
        resp.raise_for_status()

    def log(self) -> dict[str, Any]:
        resp = httpx.get(f"{self.base}/__stub/requests", timeout=5.0)
        resp.raise_for_status()
        return resp.json()

    def chats(self, stage: str | None = None) -> list[dict[str, Any]]:
        reqs = [r for r in self.log()["requests"] if r.get("path") == "/api/chat"]
        if stage:
            reqs = [r for r in reqs if r.get("stage") == stage]
        return reqs

    def ids_seen(self, stage: str) -> set[str]:
        return {jid for r in self.chats(stage) for jid in r.get("job_ids") or []}


# --- the sandbox enricher ---------------------------------------------------


@dataclass
class WrapperRun:
    rc: int
    output: str
    log_path: Path

    def expect(self, needle: str, why: str) -> None:
        """Assert the run printed ``needle`` — failing with ``why`` and the log's
        path, not a screenful of repr."""
        if needle not in self.output:
            raise AssertionError(f"{why}\n  missing: {needle!r}\n  log: {self.log_path}")

    def refute(self, needle: str, why: str) -> None:
        if needle in self.output:
            raise AssertionError(f"{why}\n  present: {needle!r}\n  log: {self.log_path}")


class Sandbox:
    def __init__(self, info: dict[str, Any]) -> None:
        self.info = info
        self.dir = Path(info["dir"])
        self.root = Path(info["root"])
        self.v7 = bool(info["v7"])
        self.wrapper = self.dir / "scripts" / "enrich_tick_wrapper.sh"
        self._case_dir: Path | None = None
        self._n = 0

    # paths
    @property
    def data_dir(self) -> Path:
        return self.dir / "data"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "enricher.db"

    @property
    def lock_path(self) -> Path:
        return self.data_dir / ".tick.lock"

    def archive_data(self, label: str) -> None:
        """Move ``data/`` (DB, lock, chunks) aside to ``data-archive/<label>`` so
        the next case starts from an empty local state. run.sh copies every
        archive into the run's artifacts."""
        archive = self.root / "data-archive"
        archive.mkdir(parents=True, exist_ok=True)
        if self.data_dir.exists():
            self.data_dir.rename(archive / _sanitize(label))

    def _next_log(self, label: str) -> Path:
        self._n += 1
        base = self._case_dir or CASES_DIR
        base.mkdir(parents=True, exist_ok=True)
        return base / f"{self._n:02d}-{label}.log"

    # running things
    def fire(self, *, extra_env: dict[str, str] | None = None, timeout: float = 240.0,
             label: str = "wrapper") -> WrapperRun:
        """One launchd fire: exec the wrapper directly, cwd = the checkout."""
        log_path = self._next_log(label)
        with log_path.open("w", encoding="utf-8") as fh:
            proc = subprocess.run(
                [str(self.wrapper)], cwd=self.dir, env=sandbox_mod.tick_env(extra_env),
                stdout=fh, stderr=subprocess.STDOUT, timeout=timeout,
            )
        return WrapperRun(proc.returncode, log_path.read_text(encoding="utf-8"), log_path)

    @contextmanager
    def background(self, *, extra_env: dict[str, str] | None = None,
                   label: str = "wrapper-bg") -> Iterator[tuple[subprocess.Popen, Path]]:
        log_path = self._next_log(label)
        fh = log_path.open("w", encoding="utf-8")
        proc = subprocess.Popen(
            [str(self.wrapper)], cwd=self.dir, env=sandbox_mod.tick_env(extra_env),
            stdout=fh, stderr=subprocess.STDOUT,
        )
        try:
            yield proc, log_path
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)
            fh.close()

    def cli(self, *args: str, extra_env: dict[str, str] | None = None,
            check: bool = True) -> subprocess.CompletedProcess[str]:
        proc = sandbox_mod.cli(self.dir, *args, extra_env=extra_env, check=False)
        log_path = self._next_log("cli-" + _sanitize(args[0] if args else "cli"))
        log_path.write_text(f"$ cli {' '.join(args)}\n[rc={proc.returncode}]\n{proc.stdout}\n{proc.stderr}",
                            encoding="utf-8")
        if check and proc.returncode != 0:
            raise AssertionError(f"cli {' '.join(args)} exited {proc.returncode}: {proc.stderr[-800:]}")
        return proc

    def python(self, code: str) -> str:
        """Run ``code`` with the SANDBOX's interpreter (its own venv, its own
        package) and return stdout's last line."""
        proc = subprocess.run(
            [sandbox_mod.UV_BIN, "run", "python", "-c", code],
            cwd=self.dir, env=sandbox_mod.tick_env(), capture_output=True, text=True,
        )
        assert proc.returncode == 0, f"sandbox python failed: {proc.stderr[-800:]}"
        return proc.stdout.strip().splitlines()[-1]

    # reading the sandbox DB (read-only; it is the sandbox's, never prod's)
    def _query(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        if not self.db_path.exists():
            return []
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()

    def ticks(self) -> list[dict[str, Any]]:
        return self._query("SELECT * FROM ticks ORDER BY id")

    def enrichments(self) -> dict[str, dict[str, Any]]:
        return {r["job_listing_id"]: r for r in self._query("SELECT * FROM enrichments")}

    def inbox(self) -> dict[str, dict[str, Any]]:
        return {r["job_listing_id"]: r for r in self._query("SELECT * FROM inbox")}

    def meta(self, key: str) -> str | None:
        rows = self._query("SELECT value FROM meta WHERE key = ?", (key,))
        return rows[0]["value"] if rows else None

    def mark_all_unsent(self) -> int:
        """TEST FIXTURE, sandbox DB only: model a LOST ACK — JVN committed the
        write-back but the enricher never saw the 2xx, so its rows are still
        unsent. The one raw write this section makes to the enricher's DB,
        because no CLI command reaches this state on purpose."""
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.execute("UPDATE enrichments SET sent_at = NULL WHERE sent_at IS NOT NULL")
            conn.execute("UPDATE inbox SET status = 'enriched' WHERE status = 'sent'")
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()


def wrapper_line(output: str, prefix: str) -> str | None:
    """The LAST line of a wrapper run that starts with ``prefix`` (CLI summary
    lines like ``classify-run: engine=... chunks=N``)."""
    lines = [ln for ln in output.splitlines() if ln.startswith(prefix)]
    return lines[-1] if lines else None


def wrapper_int(output: str, prefix: str, key: str) -> int:
    line = wrapper_line(output, prefix)
    assert line is not None, f"wrapper output has no {prefix!r} line"
    m = re.search(rf"\b{re.escape(key)}=(\d+)", line)
    assert m, f"{prefix!r} line carries no {key}=: {line!r}"
    return int(m.group(1))


# --- session wiring -----------------------------------------------------------


@pytest.fixture(scope="session")
def sandbox_info() -> dict[str, Any]:
    assert SANDBOX_INFO_PATH.exists(), (
        f"{SANDBOX_INFO_PATH} is missing — run this through e2e/run.sh enricher, which "
        f"builds and guards the sandbox before any case"
    )
    return json.loads(SANDBOX_INFO_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="session", autouse=True)
def _verify_stack(sandbox_info: dict[str, Any]) -> None:
    """Fail fast, in words, if this is not the section's own stack."""
    resp = httpx.get(f"{BASE_URL}/health", timeout=10.0)
    resp.raise_for_status()
    # The middleware is ARMED: an /api/* call without the key must 401. If this
    # ever answers 200 the enricher's key is not being checked at all, and every
    # "the enricher authenticated" claim below would be vacuous.
    anon = httpx.get(f"{BASE_URL}/api/jobs/facets", timeout=10.0)
    assert anon.status_code == 401, (
        f"/api/jobs/facets without X-Internal-Key answered {anon.status_code}, not 401 — "
        f"the backend is not running with E2E_INTERNAL_API_KEY armed"
    )
    db.connect(DB_DSN).close()
    Stub(STUB_URL).log()
    sandbox_dir = Path(sandbox_info["dir"])
    assert sandbox_dir.is_dir(), f"sandbox {sandbox_dir} is gone"
    assert Path(sandbox_info["repo_root"]).resolve() == sandbox_dir.resolve()


@pytest.fixture(scope="session")
def sandbox(sandbox_info: dict[str, Any]) -> Sandbox:
    return Sandbox(sandbox_info)


@pytest.fixture(scope="session")
def stub() -> Stub:
    return Stub(STUB_URL)


_ORDINAL = {"n": 0}


@pytest.fixture(autouse=True)
def _fresh_case(request: pytest.FixtureRequest, sandbox: Sandbox, stub: Stub, case_dir: Path) -> Iterator[None]:
    _ORDINAL["n"] += 1
    n = _ORDINAL["n"]
    stub.reset()
    # Whatever is there now is NOT this case's: the boot guard's `cli init`,
    # or a `--keep-up` leftover.
    sandbox.archive_data(f"{n:02d}-before-{request.node.name}")
    sandbox._case_dir = case_dir
    sandbox._n = 0
    yield
    sandbox.archive_data(f"{n:02d}-{request.node.name}")
    # Keep the stub's view of this case beside its wrapper logs.
    try:
        (case_dir / "stub-requests.json").write_text(json.dumps(stub.log(), indent=2), encoding="utf-8")
    except httpx.HTTPError:
        pass


@pytest.fixture()
def http() -> Iterator[httpx.Client]:
    client = httpx.Client(base_url=BASE_URL, timeout=30.0, headers={"X-Internal-Key": INTERNAL_KEY})
    try:
        yield client
    finally:
        client.close()


@pytest.fixture()
def db_conn() -> Iterator[Any]:
    conn = db.connect(DB_DSN)
    conn.autocommit = True  # every read sees the latest committed write
    try:
        yield conn
    finally:
        conn.close()


def dump_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


# --- the kill-switch backend (EN-08) ------------------------------------------


def _parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


@contextmanager
def second_backend(port: int, overrides: dict[str, str], log_path: Path) -> Iterator[str]:
    """A short-lived backend on ``port`` over the SAME database, with
    ``overrides`` on top of env.enricher — the add-companies AC-09 pattern. Its
    pid goes into the section's pidfile dir so run.sh's teardown can stop it
    even if this test dies mid-way."""
    env = dict(os.environ)
    env.update(_parse_env_file(ENV_FILE))
    env["INTERNAL_API_KEY"] = INTERNAL_KEY
    env["ANTHROPIC_API_KEY"] = ""
    env["PORT"] = str(port)
    env["E2E_EXPECTED_DB"] = os.environ.get("E2E_EXPECTED_DB", "jobscraper_e2e_enricher")
    env.update(overrides)
    fh = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "e2e.shared.stack.e2e_app:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(_REPO_ROOT), env=env, stdout=fh, stderr=subprocess.STDOUT,
    )
    PID_DIR.mkdir(parents=True, exist_ok=True)
    pidfile = PID_DIR / "killswitch.pid"
    pidfile.write_text(str(proc.pid), encoding="utf-8")
    try:
        deadline = time.monotonic() + 60.0
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(f"backend on :{port} exited early — see {log_path}")
            try:
                if httpx.get(f"http://127.0.0.1:{port}/health", timeout=2.0).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        else:
            raise RuntimeError(f"backend on :{port} did not become healthy in 60s — see {log_path}")
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
        fh.close()
        pidfile.unlink(missing_ok=True)


__all__ = [
    "BASE_URL", "DB_DSN", "INTERNAL_KEY", "KILLSWITCH_PORT", "Sandbox", "Stub",
    "db", "dump_json", "fixtures", "second_backend", "seed", "wrapper_int", "wrapper_line",
]
