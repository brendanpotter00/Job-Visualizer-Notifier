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

import psycopg2
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

from .conftest import _insert_admin

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
    #
    # ``raise_server_exceptions=False`` because the child never runs the lifespan, so
    # there is no connection pool, and the status route takes a connection now (it
    # verifies the LIVE database rather than trusting the URL). Without this the
    # handler's "pool not initialized" would come back as a crashed child instead of
    # the 500 it is. What this function measures is 404-vs-not — whether the route
    # was registered — and a 500 answers that as well as a 403 does.
    code = (
        "import json;"
        "from fastapi.testclient import TestClient;"
        "import api.main as m;"
        "r = TestClient(m.app, raise_server_exceptions=False).get(%r);"
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
        # What the pool ACTUALLY connects with. ``dependencies.init_pool`` runs the
        # configured URL through ``augment_db_url`` first, which appends keepalives,
        # an application_name and a statement_timeout as query parameters — so the
        # string this guard sees in anger is never the bare one above.
        "postgresql://u:p@localhost:5432/db?keepalives=1&keepalives_idle=30"
        "&application_name=fastapi_pool&options=-c%20statement_timeout%3D30000",
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
        # ── THE BYPASS, measured 2026-09-04 ────────────────────────────────────
        # libpq IGNORES the authority when the DSN carries host= / hostaddr=, and
        # ``augment_db_url`` (which every pooled connection goes through) preserves
        # query parameters. ``urlsplit().hostname`` reports "localhost" for both of
        # these while psycopg2 connects to production. A guard that reads the URL
        # grammar instead of libpq's is reading a different string than the driver.
        "postgresql://u:p@localhost:5432/db?host=prod-db.railway.internal",
        "postgresql://u:p@localhost:5432/db?hostaddr=10.0.0.5",
        # …and through the SQLAlchemy driver spelling, which parse_dsn refuses
        # outright unless the ``+driver`` suffix is stripped first. Fail-closed
        # either way, but it must fail for the right reason.
        "postgresql+psycopg2://u:p@localhost/db?host=prod-db.railway.internal",
        # A socket DIRECTORY as host= is local in practice; refused for the same
        # reason ``postgresql:///jobscraper`` is — the contract here is proof.
        "postgresql://u:p@localhost/db?host=/var/run/postgresql",
    ],
)
def test_non_loopback_or_unparseable_urls_are_refused(url: str) -> None:
    with pytest.raises(svc.NonLocalDatabaseError):
        svc.assert_local_database(url)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgresql://u:p@localhost:5432/db?host=prod-db.railway.internal",
         "host="),
        ("postgresql://u:p@localhost:5432/db?hostaddr=10.0.0.5", "hostaddr="),
    ],
)
def test_the_refusal_names_the_parameter_that_did_it(url: str, expected: str) -> None:
    """The message has to say WHICH host lost, or the reader is left staring at a
    DSN whose visible hostname is 'localhost' wondering why it was refused."""
    with pytest.raises(svc.NonLocalDatabaseError, match=expected):
        svc.assert_local_database(url)


# --- Guard 3: the live connection, not the config string ----------------------
#
# ``assert_local_database`` judges ``settings.database_url``. The DELETEs travel down
# a pooled connection built from an AUGMENTED copy of it — and, under pytest, from
# ``TEST_DATABASE_URL`` instead. These use a fake connection rather than the real one
# because the interesting answers (a remote server, a Unix socket, a query that
# errors) cannot be produced by the local database on demand.


class _FakeCursor:
    def __init__(self, row: object, error: Exception | None) -> None:
        self._row = row
        self._error = error

    def execute(self, _sql: str) -> None:
        if self._error is not None:
            raise self._error

    def fetchone(self) -> object:
        return self._row


class _FakeInfo:
    def __init__(self, host: str | None) -> None:
        self.host = host


class _FakeConnection:
    """Just enough psycopg2 connection for the guard: ``.info.host`` and a cursor."""

    def __init__(
        self,
        *,
        host: str | None,
        server_addr: object = None,
        row: object = "unset",
        error: Exception | None = None,
    ) -> None:
        self.info = _FakeInfo(host)
        self._row = ({"server_addr": server_addr} if row == "unset" else row)
        self._error = error

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._row, self._error)


@pytest.mark.parametrize(
    ("host", "server_addr", "why"),
    [
        ("localhost", "127.0.0.1", "the plain local case"),
        ("127.0.0.1", "127.0.0.1", "an IP literal, same thing"),
        ("localhost", None, "a Unix socket has no server address"),
        ("/var/run/postgresql", None, "a socket DIRECTORY never leaves the machine"),
        # MEASURED on this repo's own prescribed setup (`docker compose up -d
        # postgres`, published port): the server sits inside the container network
        # and reports 172.18.0.2 for a connection made to localhost:5432. GitHub
        # Actions' service containers are the same shape. Refusing this would refuse
        # every ordinary local setup, so `info.host` carries the weight here.
        ("localhost", "172.18.0.2", "Postgres in Docker behind a published port"),
        ("localhost", "172.18.0.2/32", "…rendered by a cursor that keeps the prefix"),
    ],
)
def test_a_local_connection_is_accepted(
    host: str, server_addr: object, why: str
) -> None:
    svc.assert_local_connection(
        _FakeConnection(host=host, server_addr=server_addr)  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    ("conn", "why"),
    [
        (
            _FakeConnection(host="prod-db.railway.internal", server_addr="10.0.0.5"),
            "the ?host= bypass, caught on the wire this time",
        ),
        (
            _FakeConnection(host="db.railway.internal", server_addr=None),
            "a remote host that answers over a socket it claims not to have",
        ),
        (
            _FakeConnection(host="localhost", server_addr="52.10.20.30"),
            "we dialled loopback and the server answered from the public internet — "
            "something is forwarding the port",
        ),
        (_FakeConnection(host=""), "a connection that will not say where it went"),
        (_FakeConnection(host=None), "…or says nothing at all"),
        (
            _FakeConnection(host="localhost", row=None),
            "no row back from inet_server_addr()",
        ),
        (
            _FakeConnection(host="localhost", server_addr="not-an-address"),
            "an address that will not parse",
        ),
        (
            _FakeConnection(host="localhost", error=psycopg2.OperationalError("boom")),
            "the query itself failed — 'we could not tell' is 'no'",
        ),
    ],
)
def test_a_connection_that_is_not_provably_local_is_refused(
    conn: object, why: str
) -> None:
    with pytest.raises(svc.NonLocalDatabaseError):
        svc.assert_local_connection(conn)  # type: ignore[arg-type]


def test_a_tuple_cursor_row_is_read_the_same_as_a_dict_row() -> None:
    """The app's pool uses RealDictCursor; the CLI and psql-shaped callers do not."""
    svc.assert_local_connection(
        _FakeConnection(host="localhost", row=("127.0.0.1",))  # type: ignore[arg-type]
    )
    with pytest.raises(svc.NonLocalDatabaseError):
        svc.assert_local_connection(
            _FakeConnection(host="localhost", row=("52.10.20.30",))  # type: ignore[arg-type]
        )


def test_the_delete_itself_refuses_a_non_local_connection() -> None:
    """The service function guards ITSELF, so a caller that skipped the router — the
    CLI, a test, a future reaper — cannot delete through a remote connection."""
    with pytest.raises(svc.NonLocalDatabaseError):
        svc.reset_custom_companies(
            _FakeConnection(host="db.railway.internal"),  # type: ignore[arg-type]
            user_id=None,
        )


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


# --- Guard 5: scope=all is everybody's data, so it needs the admin grant -------
#
# ``scope=all`` runs ``DELETE FROM user_companies`` and ``DELETE FROM
# company_add_attempts`` with NO WHERE clause. Behind ``get_current_user`` alone that
# is "any authenticated caller wipes every user's data", which is harmless on one
# laptop and is exactly what compounds a mis-set flag or a DSN that is not as local as
# it looks. ``scope=mine`` — the default, and what the button sends — needs no grant.


def test_scope_all_is_refused_for_a_non_admin_and_deletes_nothing(
    client_on, db_conn
) -> None:
    owner = _user_id(db_conn, "owner@example.com")
    other = _user_id(db_conn, "other@example.com")
    _seed_custom_company(db_conn, "u-devreset1", owner)
    _seed_custom_company(db_conn, "u-devreset2", other)

    response = client_on.post(f"{DEV_RESET_PATH}?scope=all")

    assert response.status_code == 403
    assert "admin" in response.json()["detail"].lower()
    # Not one row, not even the caller's own — the refusal is before the delete.
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 2
    assert _count(db_conn, "user_companies") == 2
    assert _count(db_conn, "company_add_attempts") == 2


def test_scope_mine_still_needs_no_admin_grant(client_on, db_conn) -> None:
    """The gate is on the scope, not on the endpoint. A developer clearing their own
    boards twenty times an evening must not need a row in ``admins`` to do it."""
    owner = _user_id(db_conn, "owner@example.com")
    _seed_custom_company(db_conn, "u-devreset1", owner)

    body = client_on.post(DEV_RESET_PATH).json()

    assert body["scope"] == "mine"
    assert body["company_ids"] == ["u-devreset1"]


def test_scope_all_clears_every_users_custom_companies(client_on, db_conn) -> None:
    owner = _user_id(db_conn, "owner@example.com")
    other = _user_id(db_conn, "other@example.com")
    _insert_admin(db_conn, owner)
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
