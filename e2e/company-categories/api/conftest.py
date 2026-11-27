"""pytest fixtures for the company-categories API tier.

Assumes the stack is up (`e2e/company-categories/run.sh`, or `--keep-up`) on
:8208 / `jobscraper_e2e_company_categories`. Does not start or stop it.

Every request is ANONYMOUS: `/api/jobs/search` and `/api/jobs/facets` are
public read paths. Only the UI tier signs in.
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
for _p in (str(_SECTION_DIR), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fixtures  # noqa: E402
import seed  # noqa: E402

from e2e.shared.db import assertions as db  # noqa: E402

BASE_URL = os.environ.get("E2E_BACKEND_URL", "http://127.0.0.1:8208")
DB_DSN = seed.DEFAULT_DSN

SEARCH = "/api/jobs/search"
FACETS = "/api/jobs/facets"

ARTIFACTS_DIR = Path(
    os.environ.get("E2E_ARTIFACTS_DIR", str(_SECTION_DIR / "artifacts" / f"local-{int(time.time())}"))
)
CASES_DIR = ARTIFACTS_DIR / "cases"


def _sanitize(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name)


@pytest.fixture(scope="session", autouse=True)
def _verify_stack() -> None:
    """Fail fast, in words, on the wrong port, the wrong database, or a backend
    whose boot seed did not write the membership tables."""
    resp = httpx.get(f"{BASE_URL}/health", timeout=10.0)
    resp.raise_for_status()
    assert resp.text == "OK", f"unexpected /health body from {BASE_URL}: {resp.text!r}"
    db.connect(DB_DSN).close()
    seed.assert_membership_seeded(DB_DSN)


@pytest.fixture(autouse=True)
def _reseed_around_every_test() -> Iterator[None]:
    seed.reseed(DB_DSN)
    yield


@pytest.fixture()
def http() -> Iterator[httpx.Client]:
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


@pytest.fixture()
def case_dir(request: pytest.FixtureRequest) -> Path:
    d = CASES_DIR / _sanitize(request.node.name)
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo) -> Iterator[None]:
    """On failure, `cases/<test>/step.txt` names the failing step in words."""
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or not report.failed:
        return
    d = CASES_DIR / _sanitize(item.name)
    d.mkdir(parents=True, exist_ok=True)
    (d / "step.txt").write_text(str(report.longrepr), encoding="utf-8")


def _query(params: dict[str, Any]) -> list[tuple[str, str]]:
    """Lists go out as REPEATED keys, the wire form the endpoint declares and
    the Vercel proxy re-emits. A comma join would be one bogus slug."""
    query: list[tuple[str, str]] = []
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            query.extend((key, str(v)) for v in value)
        else:
            query.append((key, str(value)))
    return query


def search_raw(client: httpx.Client, **params: Any) -> httpx.Response:
    return client.get(SEARCH, params=_query(params))


def search(client: httpx.Client, **params: Any) -> dict[str, Any]:
    """`GET /api/jobs/search`, raising on non-2xx."""
    resp = search_raw(client, **params)
    assert resp.status_code == 200, (
        f"GET {SEARCH}?{_query(params)} answered {resp.status_code}, not 200: {resp.text[:400]}"
    )
    return resp.json()


def result_keys(body: dict[str, Any]) -> set[str]:
    """The fixture `key` IS the `job_listings.id`."""
    return {job["id"] for job in body["jobs"]}


def dump_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


__all__ = [
    "BASE_URL",
    "DB_DSN",
    "FACETS",
    "SEARCH",
    "db",
    "dump_json",
    "fixtures",
    "result_keys",
    "search",
    "search_raw",
    "seed",
]
