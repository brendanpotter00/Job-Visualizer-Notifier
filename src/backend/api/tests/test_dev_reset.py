"""The LOCAL-DEVELOPMENT-ONLY custom-company reset — and, mostly, its guards.

The DELETE is a handful of statements delegated to an existing purge. The reason
this file is long is that the guards are the feature: a "delete every user-added
company" route reachable in production would be catastrophic and unrecoverable, so
each layer is pinned separately and — crucially — the localhost guard is pinned
WITH THE FLAG ON, because that is the only ordering that proves the two are
independent rather than one gate wearing two names.

Layer 3 (never reachable through a Vercel proxy) lives in
``test_proxy_path_allowlists.py``, next to the allowlists it is about.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg2 import sql

from api.auth.dependencies import get_current_user
from api.config import settings
from api.dependencies import get_db
from api.routers import dev_reset as dev_reset_router
from api.services import dev_reset as svc
from api.services.user_service import get_or_create_user
from scripts.shared.constants import custom

REPO_ROOT = Path(__file__).resolve().parents[4]
BACKEND_DIR = Path(__file__).resolve().parents[2]
DEV_RESET_PATH = "/api/users/dev-reset"

LOCAL_DB_URL = "postgresql://postgres:postgres@localhost:5432/jobscraper"


# --- Guard 1: the flag decides whether the route EXISTS -----------------------
#
# Asserted in a subprocess, not with importlib.reload, because ``api.main`` is
# imported by conftest and re-executing it in-process re-runs _configure_logging()
# and rebinds the app other fixtures already hold. A child process makes the answer
# unambiguous and leaves this one untouched.


def _main_app_with_flag(value: str) -> dict:
    """Import ``api.main`` with ``DEV_RESET_ENABLED=<value>`` and report back.

    Returns the app's route paths plus the real HTTP status of a GET at the dev
    reset path — a route table and the 404 it produces, from the same process.
    """
    env = dict(os.environ)
    env["DEV_RESET_ENABLED"] = value
    # The internal-key middleware 401s everything when a key is configured, which
    # would mask the 404-vs-not distinction this function exists to measure. Local
    # dev runs with it unset; so does this child.
    env.pop("INTERNAL_API_KEY", None)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(REPO_ROOT), *(p for p in sys.path if p)]
    )
    # ``app.routes`` holds opaque _IncludedRouter wrappers in this FastAPI version,
    # so the route table is read from the OpenAPI schema — a public, stable view of
    # exactly the paths the app will answer.
    code = (
        "import json;"
        "from fastapi.testclient import TestClient;"
        "import api.main as m;"
        "r = TestClient(m.app).get(%r);"
        "print('RESULT ' + json.dumps({'status': r.status_code,"
        " 'paths': sorted(m.app.openapi()['paths'])}))" % DEV_RESET_PATH
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, f"child failed:\n{proc.stdout}\n{proc.stderr}"
    payload = [
        line for line in proc.stdout.splitlines() if line.startswith("RESULT ")
    ]
    assert payload, f"child printed no result:\n{proc.stdout}\n{proc.stderr}"
    return json.loads(payload[-1][len("RESULT "):])


def test_the_route_is_not_registered_at_all_with_the_flag_off() -> None:
    """OFF must 404, not 403.

    A 403 would confirm to an anonymous prober that a "delete every company this
    user added" endpoint lives at this path and is merely refusing today. Skipping
    ``include_router`` means the path is indistinguishable from one that was never
    written.
    """
    result = _main_app_with_flag("false")
    assert DEV_RESET_PATH not in result["paths"]
    assert result["status"] == 404


def test_the_route_is_registered_with_the_flag_on() -> None:
    """ON registers it — and it still refuses an unauthenticated caller."""
    result = _main_app_with_flag("true")
    assert DEV_RESET_PATH in result["paths"]
    assert result["status"] != 404


# --- Guard 2: the database location, parsed and fail-closed -------------------


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://postgres:postgres@localhost:5432/jobscraper",
        "postgres://u:p@127.0.0.1:5432/db",
        # The whole 127.0.0.0/8 block is loopback, not just the .1.
        "postgresql://u:p@127.0.0.2/db",
        "postgresql://u:p@[::1]:5432/db",
        "postgresql+psycopg2://u:p@localhost/db",
        "postgresql://u:p@LOCALHOST/db",
    ],
)
def test_loopback_urls_are_accepted(url: str) -> None:
    assert svc.assert_local_database(url)


@pytest.mark.parametrize(
    "url",
    [
        # The ordinary wrong answer.
        "postgresql://u:p@db.railway.internal:5432/railway",
        # Userinfo ends at the LAST '@' — the real host is evil.example. This is
        # the case a substring check for 'localhost' gets exactly backwards.
        "postgresql://localhost@evil.example/db",
        # 'localhost' present, but in the query string, not the authority.
        "postgresql://u:p@prod.example/db?options=--search_path%3Dlocalhost",
        # Not the same host, however much it reads like it.
        "postgresql://u:p@localhost.evil.example/db",
        "postgresql://u:p@db-localhost.prod.internal/db",
        "postgresql://u:p@10.0.0.5/db",
        # A Unix-socket DSN is local in practice but not PROVABLY so from the
        # string, and this guard's contract is proof.
        "postgresql:///jobscraper",
        # Unparseable / not a Postgres URL at all: fail closed, every time.
        "",
        "not a url at all",
        "mysql://u:p@localhost/db",
        "postgresql://u:p@localhost:notaport/db",
        "postgresql://u:p@[::1/db",
    ],
)
def test_non_loopback_or_unparseable_urls_are_refused(url: str) -> None:
    with pytest.raises(svc.NonLocalDatabaseError):
        svc.assert_local_database(url)


# --- Test app: the router registered, i.e. the flag already ON ----------------


@pytest.fixture
def app_with_router(db_conn):
    """A FastAPI app that includes the dev-reset router — the flag-ON world.

    Everything below runs in that world on purpose. A guard only tested with the
    feature switched off is a guard that has never run.
    """
    app = FastAPI()
    app.include_router(dev_reset_router.router, prefix=DEV_RESET_PATH)

    def override_get_db():
        yield db_conn

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "auth0|owner", "email": "owner@example.com",
        "given_name": "A", "family_name": "B", "picture": None,
    }
    return app


@pytest.fixture
def client_on(app_with_router):
    return TestClient(app_with_router)


@pytest.fixture(autouse=True)
def local_database_url(monkeypatch):
    """Pin the URL the guard reads.

    ``Settings`` loads ``.env.local``, so without this the guard would be judging a
    developer-specific string and the delete tests would pass or fail on which
    database happened to be configured.
    """
    monkeypatch.setattr(settings, "database_url", LOCAL_DB_URL)


@pytest.fixture(autouse=True)
def clean_job_sidecars(db_conn):
    """Truncate the sidecars conftest's ``_clear_tables`` does not.

    ``job_tags`` / ``job_enrichment`` / ``job_locations`` are keyed on
    ``job_listing_id`` with no FK (they cannot reference ``job_listings``' composite
    PK), so a TRUNCATE ... CASCADE of the parent leaves them behind. This file
    reuses fixed ids across tests, so leftovers would make the counts lie.
    """
    yield
    cur = db_conn.cursor()
    for table in ("job_locations", "job_tags", "job_enrichment", "locations"):
        cur.execute(sql.SQL("DELETE FROM {}").format(sql.Identifier(table)))
    db_conn.commit()


# --- Seeding -----------------------------------------------------------------


def _login(app, sub: str, email: str) -> None:
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": sub, "email": email,
        "given_name": "A", "family_name": "B", "picture": None,
    }


def _user_id(db_conn, email: str) -> str:
    row = get_or_create_user(
        db_conn, auth0_id=f"auth0|{email}", email=email,
        given_name="A", family_name="B", picture_url=None,
    )
    return str(row["id"])


def _count(db_conn, table: str, where: str = "", params: tuple = ()) -> int:
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL("SELECT count(*) AS n FROM {} " + where).format(sql.Identifier(table)),
        params,
    )
    return int(cur.fetchone()["n"])


def _seed_custom_company(db_conn, company_id: str, owner_user_id: str) -> None:
    """One private board, owned, with a recipe, a harvest, a run and two jobs.

    Deliberately populates EVERY table the purge is responsible for, so a reset that
    silently skipped one would leave a row this file can count.
    """
    source_id = custom(company_id)
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO companies (id, display_name, ats, board_token, enabled, "
        "visibility, health_state) VALUES (%s, %s, 'discovered', %s, TRUE, 'user', "
        "'unverified')",
        (company_id, company_id, f"https://example.test/{company_id}/careers"),
    )
    cur.execute(
        "INSERT INTO user_companies (user_id, company_id, canonical_source_key) "
        "VALUES (%s, %s, %s)",
        (owner_user_id, company_id, f"discovered:{company_id}"),
    )
    cur.execute(
        "INSERT INTO company_add_attempts (user_id, submitted_url, outcome, "
        "company_id) VALUES (%s, %s, 'added', %s)",
        (owner_user_id, f"https://example.test/{company_id}/careers", company_id),
    )
    cur.execute(
        "INSERT INTO company_scripts (company_id, script, script_version, "
        "transport, oracle_kind) VALUES (%s, '{}'::jsonb, 1, 'ats_client', 'none')",
        (company_id,),
    )
    cur.execute(
        "INSERT INTO company_harvests (company_id, run_id, started_at, verdict, "
        "oracle_kind) VALUES (%s, %s, now(), 'UNVERIFIED', 'none')",
        (company_id, f"run-{company_id}"),
    )
    cur.execute(
        "INSERT INTO scrape_runs (run_id, company, started_at, mode) "
        "VALUES (%s, %s, now(), 'incremental')",
        (f"run-{company_id}", company_id),
    )
    cur.execute(
        "INSERT INTO locations (canonical_name, kind, remote_scope) "
        "VALUES (%s, 'remote', %s) RETURNING id",
        (f"Remote {company_id}", f"Remote {company_id}"),
    )
    location_id = int(cur.fetchone()["id"])
    for n in (1, 2):
        job_id = f"{company_id}-j{n}"
        cur.execute(
            "INSERT INTO job_listings (id, title, company, url, source_id, "
            "created_at, first_seen_at, status) VALUES (%s, 'Eng', %s, %s, %s, "
            "now(), now(), 'OPEN')",
            (job_id, company_id, f"https://example.test/{job_id}", source_id),
        )
        cur.execute(
            "INSERT INTO job_locations (job_listing_id, normalized_location_id, "
            "is_primary) VALUES (%s, %s, TRUE)",
            (job_id, location_id),
        )
        cur.execute(
            "INSERT INTO job_tags (source_id, job_listing_id, tag) "
            "VALUES (%s, %s, 'go')",
            (source_id, job_id),
        )
        cur.execute(
            "INSERT INTO job_enrichment (source_id, job_listing_id) VALUES (%s, %s)",
            (source_id, job_id),
        )
    db_conn.commit()


def _seed_published_company(db_conn, company_id: str, job_ids: tuple[str, ...]) -> None:
    """A ``visibility='public'`` company and its jobs — the fleet that must survive."""
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO companies (id, display_name, ats, board_token, enabled, "
        "visibility) VALUES (%s, %s, 'greenhouse', %s, TRUE, 'public')",
        (company_id, company_id, company_id),
    )
    for job_id in job_ids:
        cur.execute(
            "INSERT INTO job_listings (id, title, company, url, source_id, "
            "created_at, first_seen_at, status) VALUES (%s, 'Eng', %s, %s, "
            "'greenhouse_api', now(), now(), 'OPEN')",
            (job_id, company_id, f"https://example.test/{job_id}"),
        )
    db_conn.commit()


def _published_snapshot(db_conn) -> dict[str, int]:
    """Everything a reset must leave EXACTLY as it found it."""
    return {
        "companies": _count(db_conn, "companies", "WHERE visibility <> 'user'"),
        "jobs": _count(
            db_conn, "job_listings", "WHERE source_id NOT LIKE 'custom:%%'"
        ),
        "freshness": _count(
            db_conn, "job_freshness", "WHERE source_id NOT LIKE 'custom:%%'"
        ),
    }


# --- Guard 2, with the router registered: the ordering that proves it ---------


@pytest.mark.parametrize(
    "url", ["postgresql://u:p@db.railway.internal:5432/railway", "not a url at all"]
)
def test_a_non_local_database_is_refused_even_with_the_flag_on(
    client_on, db_conn, monkeypatch, url: str
) -> None:
    """THE IMPORTANT ONE. The router is registered — the flag is on — and the reset
    still refuses, having deleted nothing, because the database is not local."""
    owner = _user_id(db_conn, "owner@example.com")
    _seed_custom_company(db_conn, "u-devreset1", owner)
    monkeypatch.setattr(settings, "database_url", url)

    assert client_on.get(DEV_RESET_PATH).status_code == 403
    response = client_on.post(DEV_RESET_PATH)
    assert response.status_code == 403

    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 1
    assert _count(db_conn, "user_companies") == 1
    assert _count(db_conn, "company_add_attempts") == 1
    assert _count(db_conn, "job_listings", "WHERE source_id = %s",
                  (custom("u-devreset1"),)) == 2


def test_status_reports_the_loopback_host(client_on) -> None:
    body = client_on.get(DEV_RESET_PATH).json()
    assert body == {"enabled": True, "database_host": "localhost"}


# --- The reset itself ---------------------------------------------------------


def test_it_clears_the_callers_custom_companies_and_their_jobs(
    client_on, db_conn
) -> None:
    owner = _user_id(db_conn, "owner@example.com")
    _seed_custom_company(db_conn, "u-devreset1", owner)
    _seed_published_company(db_conn, "pub-co", ("pub-1", "pub-2"))
    before = _published_snapshot(db_conn)

    body = client_on.post(DEV_RESET_PATH).json()

    assert body["scope"] == "mine"
    assert body["company_ids"] == ["u-devreset1"]
    assert body["deleted"] == {
        "companies": 1,
        "user_companies": 1,
        "company_add_attempts": 1,
        "company_scripts": 1,
        "company_harvests": 1,
        "scrape_runs": 1,
        "job_listings": 2,
        "job_freshness": 2,
        "job_locations": 2,
        "job_tags": 2,
        "job_enrichment": 2,
    }

    # Every custom-company table is empty…
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 0
    assert _count(db_conn, "user_companies") == 0
    assert _count(db_conn, "company_scripts") == 0
    assert _count(db_conn, "company_harvests") == 0
    assert _count(db_conn, "scrape_runs") == 0
    assert _count(db_conn, "job_listings", "WHERE source_id LIKE 'custom:%%'") == 0
    assert _count(db_conn, "job_freshness", "WHERE source_id LIKE 'custom:%%'") == 0
    assert _count(db_conn, "job_tags") == 0
    assert _count(db_conn, "job_enrichment") == 0
    assert _count(db_conn, "job_locations") == 0

    # …and the published fleet is bit-for-bit what it was.
    assert _published_snapshot(db_conn) == before
    assert before == {"companies": 1, "jobs": 2, "freshness": 2}
    assert body["published_companies_kept"] == 1
    assert body["published_jobs_kept"] == 2


def test_it_clears_the_add_audit_so_the_monthly_quota_resets(
    client_on, db_conn
) -> None:
    """The audit is what ``services/add_quota`` counts the 20/month cap off, so a
    reset that kept it would give the boards back but not the budget to re-add
    them — and the next test run would hit the cap instead of the add path."""
    owner = _user_id(db_conn, "owner@example.com")
    _seed_custom_company(db_conn, "u-devreset1", owner)
    assert _count(db_conn, "company_add_attempts", "WHERE user_id = %s", (owner,)) == 1

    client_on.post(DEV_RESET_PATH)

    assert _count(db_conn, "company_add_attempts", "WHERE user_id = %s", (owner,)) == 0


def test_scope_mine_leaves_another_users_custom_company_alone(
    client_on, app_with_router, db_conn
) -> None:
    owner = _user_id(db_conn, "owner@example.com")
    other = _user_id(db_conn, "other@example.com")
    _seed_custom_company(db_conn, "u-devreset1", owner)
    _seed_custom_company(db_conn, "u-devreset2", other)

    body = client_on.post(DEV_RESET_PATH).json()

    assert body["company_ids"] == ["u-devreset1"]
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 1
    assert _count(db_conn, "user_companies", "WHERE user_id = %s", (other,)) == 1
    assert _count(db_conn, "company_add_attempts", "WHERE user_id = %s", (other,)) == 1
    assert _count(db_conn, "job_listings", "WHERE source_id = %s",
                  (custom("u-devreset2"),)) == 2


def test_scope_all_clears_every_users_custom_companies(client_on, db_conn) -> None:
    owner = _user_id(db_conn, "owner@example.com")
    other = _user_id(db_conn, "other@example.com")
    _seed_custom_company(db_conn, "u-devreset1", owner)
    _seed_custom_company(db_conn, "u-devreset2", other)
    _seed_published_company(db_conn, "pub-co", ("pub-1",))
    before = _published_snapshot(db_conn)

    body = client_on.post(f"{DEV_RESET_PATH}?scope=all").json()

    assert body["scope"] == "all"
    assert body["company_ids"] == ["u-devreset1", "u-devreset2"]
    assert body["deleted"]["companies"] == 2
    assert body["deleted"]["job_listings"] == 4
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 0
    assert _count(db_conn, "user_companies") == 0
    assert _count(db_conn, "company_add_attempts") == 0
    assert _published_snapshot(db_conn) == before


def test_an_unknown_scope_is_refused_before_anything_is_deleted(
    client_on, db_conn
) -> None:
    owner = _user_id(db_conn, "owner@example.com")
    _seed_custom_company(db_conn, "u-devreset1", owner)

    assert client_on.post(f"{DEV_RESET_PATH}?scope=everything").status_code == 422

    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 1


def test_resetting_twice_is_a_no_op_the_second_time(client_on, db_conn) -> None:
    """The state the owner actually wants: 'as if it was never added', repeatably."""
    owner = _user_id(db_conn, "owner@example.com")
    _seed_custom_company(db_conn, "u-devreset1", owner)

    client_on.post(DEV_RESET_PATH)
    body = client_on.post(DEV_RESET_PATH).json()

    assert body["company_ids"] == []
    assert set(body["deleted"].values()) == {0}


def test_an_ownership_row_whose_company_is_gone_is_still_cleared(
    client_on, db_conn
) -> None:
    """An orphaned link is invisible to the UI and blocks a re-add through
    ``uq_user_companies_source_key``, so a reset that missed it would leave the
    flow exactly as un-retestable as before."""
    owner = _user_id(db_conn, "owner@example.com")
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO user_companies (user_id, company_id, canonical_source_key) "
        "VALUES (%s, 'u-ghost', 'discovered:u-ghost')",
        (owner,),
    )
    db_conn.commit()

    body = client_on.post(DEV_RESET_PATH).json()

    assert body["deleted"]["user_companies"] == 1
    assert _count(db_conn, "user_companies") == 0


def test_commit_false_reports_real_counts_and_can_be_rolled_back(db_conn) -> None:
    """The CLI's dry run, pinned.

    A dry run is only worth having if the numbers it prints came from the
    statements that would actually run, so ``commit=False`` executes every DELETE
    and just leaves the transaction open. The property that matters is the one
    asserted last: after the caller's ROLLBACK, every row is still there.
    """
    owner = _user_id(db_conn, "owner@example.com")
    _seed_custom_company(db_conn, "u-devreset1", owner)

    outcome = svc.reset_custom_companies(db_conn, user_id=owner, commit=False)

    assert outcome.deleted["companies"] == 1
    assert outcome.deleted["job_listings"] == 2
    # Visible inside the open transaction …
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 0

    db_conn.rollback()

    # … and undone by the rollback the CLI issues.
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 1
    assert _count(db_conn, "user_companies") == 1
    assert _count(db_conn, "job_listings", "WHERE source_id LIKE 'custom:%%'") == 2


def test_a_public_company_is_unreachable_even_if_a_link_points_at_it(
    client_on, db_conn
) -> None:
    """Defence in depth, made concrete: a contrived ``user_companies`` row aimed at
    a PUBLISHED company must cost that company nothing. Every delete is scoped to
    ``visibility='user'``, so the target selection never returns it."""
    owner = _user_id(db_conn, "owner@example.com")
    _seed_published_company(db_conn, "pub-co", ("pub-1", "pub-2"))
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO user_companies (user_id, company_id, canonical_source_key) "
        "VALUES (%s, 'pub-co', 'greenhouse:pub-co')",
        (owner,),
    )
    db_conn.commit()
    before = _published_snapshot(db_conn)

    body = client_on.post(DEV_RESET_PATH).json()

    assert body["company_ids"] == []
    assert _published_snapshot(db_conn) == before
    assert _count(db_conn, "companies", "WHERE id = 'pub-co'") == 1
