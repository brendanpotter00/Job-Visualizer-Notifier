"""pytest fixtures for the subcategories API tier (PLAN.md §3, §5).

Assumes the stack is already up (`e2e/subcategories/run.sh`, or `stack_up.sh`
driven by hand with this section's env exported) at :8203 /
`jobscraper_e2e_subcategories`. Does NOT start or stop the stack — so a
developer can point pytest at an already-running stack for a fast fix loop
(`--keep-up`, then `pytest e2e/subcategories/api -k sc04`).

EVERY REQUEST HERE IS ANONYMOUS, and that is a finding rather than a
shortcut: `/api/jobs/search`, `/api/jobs/facets` and `/api/jobs/settings` are
all public read paths. The UI tier signs in only because a signed-out Recent
page caps the list at 12 cards. No token is minted on this tier at all.
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
_SECTION_DIR = _HERE.parents[1]
_REPO_ROOT = _HERE.parents[3]

# `fixtures.py` and `seed.py` are imported as plain top-level modules via
# sys.path — the same trick `add-companies/api/conftest.py` uses for
# `boards.py`, kept identical so the two sections read the same way.
for _p in (str(_SECTION_DIR), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
_BACKEND_ROOT = _REPO_ROOT / "src" / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import fixtures  # noqa: E402
import seed  # noqa: E402

from e2e.shared.db import assertions as db  # noqa: E402

BASE_URL = os.environ.get("E2E_BACKEND_URL", "http://127.0.0.1:8203")
DB_DSN = seed.DEFAULT_DSN

SEARCH = "/api/jobs/search"
FACETS = "/api/jobs/facets"
SETTINGS = "/api/jobs/settings"

ARTIFACTS_DIR = Path(
    os.environ.get(
        "E2E_ARTIFACTS_DIR",
        str(_SECTION_DIR / "artifacts" / f"local-{int(time.time())}"),
    )
)
CASES_DIR = ARTIFACTS_DIR / "cases"


def _sanitize(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name)


@pytest.fixture(scope="session", autouse=True)
def _verify_stack() -> None:
    """Fail fast, in words, if this is not the section's own stack.

    Three separate things get checked because three separate mistakes have the
    same symptom (a pile of case failures that look like product regressions):
    the wrong PORT, the wrong DATABASE, and a database that never got the
    taxonomy seed.
    """
    resp = httpx.get(f"{BASE_URL}/health", timeout=10.0)
    resp.raise_for_status()
    assert resp.text == "OK", f"unexpected /health body from {BASE_URL}: {resp.text!r}"
    # db.connect() asserts the database name itself (E2E_EXPECTED_DB).
    db.connect(DB_DSN).close()
    seed.assert_taxonomy_seeded(DB_DSN)


@pytest.fixture()
def http() -> Iterator[httpx.Client]:
    """An ANONYMOUS client. No Authorization header, on purpose — see module doc."""
    client = httpx.Client(base_url=BASE_URL, timeout=30.0)
    try:
        yield client
    finally:
        client.close()


@pytest.fixture()
def db_conn() -> Iterator[Any]:
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
def _reseed_around_every_test() -> Iterator[None]:
    """Every test starts from the exact same eleven rows, with the reveal flag
    ON (PLAN.md §5 — "re-runnable back to back with no manual reset", applied
    at TEST granularity, not just run granularity).

    SC-05 turns the flag off inside its own test; this fixture is what puts it
    back, so the order pytest happens to pick cannot change any other case's
    answer. Without it SC-05 would be an order-dependent landmine — green
    alone, and the cause of a mystery failure in whatever ran after it.
    """
    seed.reseed(DB_DSN, reveal=True)
    yield


@pytest.fixture()
def case_dir(request: pytest.FixtureRequest) -> Path:
    """Per-test artifact directory — `cases/<TestName>/`."""
    d = CASES_DIR / _sanitize(request.node.name)
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo) -> Iterator[None]:
    """On failure, drop a `step.txt` naming what failed, in words (PLAN.md §10:
    "Name the step, not the assertion")."""
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or not report.failed:
        return
    d = CASES_DIR / _sanitize(item.name)
    d.mkdir(parents=True, exist_ok=True)
    (d / "step.txt").write_text(str(report.longrepr), encoding="utf-8")


# --- Query helpers ---------------------------------------------------------
#
# Written once here rather than per test file, because getting them SLIGHTLY
# different per case is how a suite ends up asserting subtly different things
# under identical-looking names.


def search(client: httpx.Client, **params: Any) -> dict[str, Any]:
    """`GET /api/jobs/search` with repeatable params, raising on non-2xx.

    A list value is sent as REPEATED keys (`?subcategory=a&subcategory=b`),
    which is the wire form the endpoint declares and the form the Vercel proxy
    re-emits. Comma-joining instead would send one bogus slug that matches
    nothing — with a 200 — which is exactly the defect
    `api/jobs.ts`'s "append, never set" note exists for.
    """
    query: list[tuple[str, str]] = []
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            query.extend((key, str(v)) for v in value)
        else:
            query.append((key, str(value)))
    resp = client.get(SEARCH, params=query)
    assert resp.status_code == 200, (
        f"GET {SEARCH}?{query} answered {resp.status_code}, not 200: {resp.text[:400]}"
    )
    return resp.json()


def result_keys(body: dict[str, Any]) -> set[str]:
    """The fixture keys a search answered with.

    The fixture `key` IS the `job_listings.id`, so this reads the response's
    own ids and needs no lookup table. Anything the section did not seed would
    show up here verbatim and fail the set comparison loudly, which is the
    point — a schema-only database should contain nothing else.
    """
    return {job["id"] for job in body["jobs"]}


def by_id(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {job["id"]: job for job in body["jobs"]}


def dump_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


__all__ = [
    "BASE_URL",
    "DB_DSN",
    "FACETS",
    "SEARCH",
    "SETTINGS",
    "by_id",
    "db",
    "dump_json",
    "fixtures",
    "result_keys",
    "search",
    "seed",
]
