"""pytest fixtures for the add-companies API tier (PLAN.md §5, §8, §10).

Assumes the stack is already up (`e2e/shared/stack/stack_up.sh`, or `run.sh`
driving it) at :8201 / jobscraper_e2e. Does NOT start or stop the stack —
that is `run.sh`'s job, so a developer can also point pytest at an
already-running stack for a fast fix loop (`--case AC-06`-style iteration).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Iterator

import httpx
import pytest

_HERE = Path(__file__).resolve()
_ADD_COMPANIES_DIR = _HERE.parents[1]
_REPO_ROOT = _HERE.parents[3]

# `add-companies` is not a valid dotted package name (hyphen), so boards.py is
# imported as a plain top-level module via sys.path rather than a relative
# import — same trick pytest itself uses for test files with no __init__.py.
if str(_ADD_COMPANIES_DIR) not in sys.path:
    sys.path.insert(0, str(_ADD_COMPANIES_DIR))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
# AC-06a imports production code directly (api.services.published_board_match)
# to exercise the real matcher hermetically — same import root e2e_app.py uses.
_BACKEND_ROOT = _REPO_ROOT / "src" / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import boards  # noqa: E402

from e2e.shared.auth.mint import OTHER_USER, PRIMARY_USER, mint_token  # noqa: E402
from e2e.shared.db import assertions as db  # noqa: E402
from e2e.shared.db import reset_user  # noqa: E402

BASE_URL = "http://127.0.0.1:8201"
DB_DSN = "postgresql://postgres:postgres@localhost:5432/jobscraper_e2e"

ARTIFACTS_DIR = Path(
    os.environ.get(
        "E2E_ARTIFACTS_DIR",
        str(_ADD_COMPANIES_DIR / "artifacts" / f"local-{int(time.time())}"),
    )
)
CASES_DIR = ARTIFACTS_DIR / "cases"


def _sanitize(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "live: touches a real board and/or spends an LLM call — excluded by "
        "run.sh --fast (PLAN.md §7). A test is 'live' if it WAITS on an async "
        "harvest/discovery completion, regardless of whether that wait itself "
        "costs an LLM call (AC-03's Cisco harvest has no LLM but still isn't "
        "a ~2-minute-total item) — see CASES.md for the exact split PLAN.md's "
        "own '--fast: everything except AC-03/04/05/06' sentence leaves "
        "ambiguous against its separate ~60s/~90s runtime table.",
    )


@pytest.fixture(scope="session", autouse=True)
def _verify_stack_and_flags() -> None:
    """Fail fast, with a clear message, if the stack isn't the e2e one."""
    resp = httpx.get(f"{BASE_URL}/health", timeout=10.0)
    resp.raise_for_status()
    assert resp.text == "OK", f"unexpected /health body: {resp.text!r}"
    conn = db.connect(DB_DSN)
    try:
        pass  # db.connect() itself asserts the database name.
    finally:
        conn.close()


@pytest.fixture(scope="session")
def primary_token() -> str:
    return mint_token(PRIMARY_USER)


@pytest.fixture(scope="session")
def other_token() -> str:
    return mint_token(OTHER_USER)


@pytest.fixture()
def http(primary_token: str) -> Iterator[httpx.Client]:
    client = httpx.Client(
        base_url=BASE_URL,
        headers={"Authorization": f"Bearer {primary_token}"},
        timeout=60.0,
    )
    try:
        yield client
    finally:
        client.close()


@pytest.fixture()
def other_http(other_token: str) -> Iterator[httpx.Client]:
    client = httpx.Client(
        base_url=BASE_URL,
        headers={"Authorization": f"Bearer {other_token}"},
        timeout=60.0,
    )
    try:
        yield client
    finally:
        client.close()


@pytest.fixture()
def anon_http() -> Iterator[httpx.Client]:
    client = httpx.Client(base_url=BASE_URL, timeout=30.0)
    try:
        yield client
    finally:
        client.close()


@pytest.fixture()
def db_conn(request: pytest.FixtureRequest) -> Iterator[Any]:
    conn = db.connect(DB_DSN)
    try:
        yield conn
    finally:
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        conn.close()


@pytest.fixture(autouse=True)
def _clean_owned_companies_before_and_after(
    primary_token: str, other_token: str
) -> Iterator[None]:
    """Every test starts AND ends with zero companies owned by either test
    user (PLAN.md §8: "re-runnable back-to-back with no manual reset" —
    applied at test granularity too, not just run granularity)."""
    reset_user.sweep(BASE_URL, primary_token)
    reset_user.sweep(BASE_URL, other_token)
    yield
    reset_user.sweep(BASE_URL, primary_token)
    reset_user.sweep(BASE_URL, other_token)


@pytest.fixture()
def case_dir(request: pytest.FixtureRequest) -> Path:
    """Per-test artifact directory (PLAN.md §10) — `cases/<TestName>/`."""
    d = CASES_DIR / _sanitize(request.node.name)
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo) -> Iterator[None]:
    """On failure, drop a step.txt naming what failed, in words (PLAN.md §10:
    "Name the step, not the assertion.") — best-effort: the exception message
    IS usually already a step description, since assertions in this suite are
    written with an explanatory message."""
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or not report.failed:
        return
    d = CASES_DIR / _sanitize(item.name)
    d.mkdir(parents=True, exist_ok=True)
    (d / "step.txt").write_text(str(report.longrepr), encoding="utf-8")


def dump_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


_BLOCKED_BOARDS = {
    b.strip() for b in os.environ.get("E2E_BLOCKED_BOARDS", "").split(",") if b.strip()
}


def require_reachable(board: "boards.Board") -> None:
    """Demote to BLOCKED (skipped, not failed) if `preflight.py` (run by
    run.sh before any case runs) found this board unreachable — PLAN.md §6's
    three-state contract: "a third-party outage must not read as our
    regression." A no-op when run standalone (no E2E_BLOCKED_BOARDS set)."""
    if board.label in _BLOCKED_BOARDS:
        pytest.skip(f"BLOCKED: {board.label} ({board.url}) failed the preflight reachability probe")


def find_company(http: httpx.Client, company_id: str) -> dict[str, Any] | None:
    resp = http.get("/api/users/companies")
    resp.raise_for_status()
    for c in resp.json()["companies"]:
        if c["id"] == company_id:
            return c
    return None


def poll_until(
    http: httpx.Client,
    company_id: str,
    predicate: "Any",
    *,
    timeout_s: float = 240.0,
    interval_s: float = 3.0,
    what: str = "condition",
) -> dict[str, Any]:
    """Poll `GET /api/users/companies` until `predicate(row)` is truthy.

    240s matches `_TASK_TIMEOUT_S` in `discover_custom_company.py` — the
    discovery task's own wall-clock cap (PLAN.md §7 risk register: "budget
    240s per discovery"). Raises AssertionError naming the step, not just the
    assertion (PLAN.md §10), on timeout.
    """
    deadline = time.monotonic() + timeout_s
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        row = find_company(http, company_id)
        if row is not None:
            last = row
            if predicate(row):
                return row
        time.sleep(interval_s)
    raise AssertionError(
        f'company {company_id} did not reach "{what}" within {timeout_s}s; '
        f"last observed row: {last}"
    )


__all__ = [
    "BASE_URL",
    "DB_DSN",
    "boards",
    "db",
    "dump_json",
    "find_company",
    "poll_until",
    "reset_user",
]
