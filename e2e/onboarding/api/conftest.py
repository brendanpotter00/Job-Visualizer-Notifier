"""pytest fixtures for the onboarding API tier (OB-01..OB-09).

Assumes `e2e/onboarding/run.sh` has the stack up on :8205 against
`jobscraper_e2e_onboarding` and has seeded it. Does not start or stop anything,
so a `--keep-up` stack takes `pytest e2e/onboarding/api -k ob04` directly.

EVERY CASE SIGNS IN AS A BRAND-NEW IDENTITY (PLAN.md §4), minted through
`shared/auth/mint.py` — a real RS256 token the real `get_current_user` checks
(signature, audience, issuer, expiry, the `email` claim). "First sign-in" means
NO `users` row exists for it, and the `identity` factory asserts exactly that
before handing the identity out. Each identity is purged when its test ends.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator

import httpx
import pytest

_HERE = Path(__file__).resolve()
_SECTION_DIR = _HERE.parents[1]
_REPO_ROOT = _HERE.parents[3]
for _p in (str(_REPO_ROOT), str(_REPO_ROOT / "src" / "backend")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from e2e.onboarding import fixtures, identities  # noqa: E402
from e2e.onboarding.identities import Identity  # noqa: E402
from e2e.shared.auth.mint import mint_token  # noqa: E402
from e2e.shared.db import assertions as db  # noqa: E402

BASE_URL = os.environ.get("E2E_BACKEND_URL", "http://127.0.0.1:8205")
DB_DSN = identities.DEFAULT_DSN

USERS = "/api/users"
VISIT = "/api/users/visit"
ONBOARDING = "/api/users/onboarding"
SAVED_FILTERS = "/api/users/saved-filters"
KEYWORD_LISTS = "/api/users/saved-filters/keyword-lists"

ARTIFACTS_DIR = Path(
    os.environ.get("E2E_ARTIFACTS_DIR", str(_SECTION_DIR / "artifacts" / f"local-{int(time.time())}"))
)
CASES_DIR = ARTIFACTS_DIR / "cases"


def _sanitize(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name)


@pytest.fixture(scope="session", autouse=True)
def _verify_stack() -> None:
    """Fail fast, in words, when this is not the onboarding stack."""
    resp = httpx.get(f"{BASE_URL}/health", timeout=10.0)
    resp.raise_for_status()
    conn = db.connect(DB_DSN)  # asserts the database name (E2E_EXPECTED_DB)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'users' AND column_name = 'onboarding_completed_at'"
            )
            assert cur.fetchone(), (
                "users.onboarding_completed_at does not exist in jobscraper_e2e_onboarding — "
                "the clone is behind migration ef0f7d8c8e11. Re-run with --refresh-db."
            )
            cur.execute("SELECT onboarding_completed_at FROM users WHERE auth0_id = %s",
                        (fixtures.PREEXISTING.sub,))
            row = cur.fetchone()
            assert row and row["onboarding_completed_at"] is not None, (
                "the pre-existing stamped account is not seeded — run `python -m "
                "e2e.onboarding.seed` (run.sh does it before this tier)"
            )
    finally:
        conn.close()


@pytest.fixture()
def conn() -> Iterator[Any]:
    """Autocommit, so every read sees what the backend just committed."""
    c = db.connect(DB_DSN)
    c.autocommit = True
    try:
        yield c
    finally:
        c.close()


@dataclass
class Session:
    """One signed-in identity: its token and an HTTP client that sends it."""

    ident: Identity
    token: str

    @property
    def sub(self) -> str:
        return self.ident.sub

    @property
    def email(self) -> str:
        return self.ident.email

    def client(self) -> httpx.Client:
        return httpx.Client(
            base_url=BASE_URL, timeout=30.0, headers={"Authorization": f"Bearer {self.token}"}
        )

    def get(self, path: str) -> httpx.Response:
        with self.client() as c:
            return c.get(path)

    def post(self, path: str, body: Any = None) -> httpx.Response:
        with self.client() as c:
            return c.post(path, json=body)

    def put(self, path: str, body: Any) -> httpx.Response:
        with self.client() as c:
            return c.put(path, json=body)


def sign_in(ident: Identity) -> Session:
    token = mint_token({"sub": ident.sub, "email": ident.email, "given_name": "E2E", "family_name": "Onboarding"})
    return Session(ident=ident, token=token)


@pytest.fixture()
def identity(conn: Any) -> Iterator[Callable[[str], Session]]:
    """`identity("OB-03")` -> a brand-new signed-in identity with NO users row.

    The no-row precondition is asserted, not assumed: a reused sub or email
    would make "first sign-in" a lie and every case built on it vacuous.
    """
    made: list[str] = []

    def make(case: str) -> Session:
        ident = identities.new_identity(case)
        assert identities.user_rows(conn, ident) == [], (
            f"a users row already exists for the brand-new identity {ident} — "
            "'first sign-in' would be a lie"
        )
        made.append(ident.sub)
        return sign_in(ident)

    yield make
    identities.purge(conn, made)


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


# --- Helpers -----------------------------------------------------------------


def ok_json(resp: httpx.Response, what: str) -> dict[str, Any]:
    assert resp.status_code == 200, f"{what}: answered {resp.status_code}, not 200: {resp.text[:400]}"
    return resp.json()


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def db_now(conn: Any) -> datetime:
    with conn.cursor() as cur:
        cur.execute("SELECT now() AS t")
        return cur.fetchone()["t"]


def saved_lists(row: dict[str, Any]) -> dict[str, list[str]]:
    """The four onboarding columns of a `user_saved_filters` DB row."""
    return {k: row[k] for k in ("category", "subcategory", "level", "locations")}


def api_lists(body: dict[str, Any]) -> dict[str, list[str]]:
    """The four onboarding fields of a SavedFiltersResponse body."""
    return {k: body[k] for k in ("category", "subcategory", "level", "locations")}


def dump_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


__all__ = [
    "BASE_URL",
    "DB_DSN",
    "KEYWORD_LISTS",
    "ONBOARDING",
    "SAVED_FILTERS",
    "USERS",
    "VISIT",
    "Session",
    "api_lists",
    "db_now",
    "dump_json",
    "fixtures",
    "identities",
    "ok_json",
    "parse_ts",
    "saved_lists",
    "sign_in",
]
