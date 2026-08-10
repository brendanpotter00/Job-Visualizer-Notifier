"""E7 Phase 3b — the discover_custom_company leaf task. $0 (discovery mocked).

The task itself is called directly (``await discover_custom_company(...)``) so it
opens its OWN connection from ``settings.database_url``, pointed at the per-worker
test schema. ``discover`` is monkeypatched to return a canned outcome, so no LLM /
browser runs. Proves: an accept creates the four rows with the multi-primitive
script (``transport='http_json'`` + the real stored ``oracle_kind``); a refuse
writes a DISABLED ``health_state='refused'`` row + a ``refused`` attempt and NO
script; and the create path is idempotent per (user, discovered-url).
"""

from __future__ import annotations

import os
import uuid

import pytest
from psycopg2 import sql

import api.tasks.discover_custom_company as task_mod
from api.config import settings
from api.services import custom_companies_service as ccs
from api.services.discovery.models import DiscoveryOutcome
from api.tasks.discover_custom_company import discover_custom_company

pytestmark = pytest.mark.asyncio

_NORMALIZED = "https://careers.acme.example/jobs"
_SUBMITTED = "https://acme.example/careers"


def _recipe() -> dict:
    return {
        "script_version": 1,
        "transport": "http_json",
        "expected_min_jobs": 5,
        "steps": [
            {"op": "fetch", "method": "GET", "url": "https://careers.acme.example/api/jobs", "headers": {}},
            {"op": "extract_json_path", "records_path": "jobs",
             "fields": {"id": "id", "title": "title", "url": "url"}},
            {"op": "dedupe_key", "field": "id"},
        ],
        "oracle": {"kind": "facet_sum", "facet_path": "facets.dept",
                   "single_valued": True, "total_path": "hits"},
    }


def _seed_user(db_conn) -> str:
    user_id = uuid.uuid4().hex
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, auth0_id, email, created_at, updated_at) "
            "VALUES (%s, %s, %s, now(), now())"
        ).format(sql.Identifier("users")),
        (user_id, f"auth0|{user_id[:12]}", f"{user_id[:8]}@example.com"),
    )
    db_conn.commit()
    return user_id


def _patch_env(monkeypatch) -> None:
    monkeypatch.setattr(settings, "database_url", os.environ["DATABASE_URL"])
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    # The task now also gates on browser_agent_enabled (the real kill-switch).
    monkeypatch.setattr(settings, "browser_agent_enabled", True)


def _row(db_conn, query: str, params: tuple = ()):
    cur = db_conn.cursor()
    cur.execute(query, params)
    return cur.fetchone()


async def test_success_creates_four_rows(db_conn, monkeypatch) -> None:
    _patch_env(monkeypatch)
    user_id = _seed_user(db_conn)
    outcome = DiscoveryOutcome(
        ok=True, script=_recipe(), transport="http_json",
        oracle_kind="facet_sum", attempts=1,
    )

    async def _fake_discover(url):
        assert url == _NORMALIZED
        return outcome

    monkeypatch.setattr(task_mod, "discover", _fake_discover)

    await discover_custom_company(user_id, _SUBMITTED, _NORMALIZED, "careers.acme.example")

    company = _row(
        db_conn,
        "SELECT id, visibility, enabled, health_state, ats FROM companies "
        "WHERE ats = 'discovered'",
    )
    assert company is not None
    assert company["visibility"] == "user"
    assert company["enabled"] is True
    company_id = company["id"]

    script = _row(
        db_conn,
        "SELECT transport, oracle_kind, script_version FROM company_scripts WHERE company_id = %s",
        (company_id,),
    )
    assert script["transport"] == "http_json"
    assert script["oracle_kind"] == "facet_sum"     # the STORED real oracle
    assert script["script_version"] == 1

    assert _row(db_conn, "SELECT count(*) AS n FROM user_companies WHERE company_id = %s", (company_id,))["n"] == 1
    attempt = _row(
        db_conn,
        "SELECT outcome FROM company_add_attempts WHERE company_id = %s AND outcome = 'added'",
        (company_id,),
    )
    assert attempt is not None


async def test_refuse_writes_disabled_refused_row_and_no_script(db_conn, monkeypatch) -> None:
    _patch_env(monkeypatch)
    user_id = _seed_user(db_conn)
    outcome = DiscoveryOutcome(ok=False, refuse_reason="RecipeError: bad shape", attempts=2)

    async def _fake_discover(url):
        return outcome

    monkeypatch.setattr(task_mod, "discover", _fake_discover)

    await discover_custom_company(user_id, _SUBMITTED, _NORMALIZED, "careers.acme.example")

    company = _row(
        db_conn,
        "SELECT id, health_state, enabled FROM companies WHERE ats = 'discovered'",
    )
    assert company is not None
    assert company["health_state"] == "refused"
    assert company["enabled"] is False          # never scraped
    # No script row: even if the leaf task were reached, it would no-op.
    assert _row(
        db_conn, "SELECT count(*) AS n FROM company_scripts WHERE company_id = %s",
        (company["id"],),
    )["n"] == 0
    attempt = _row(
        db_conn,
        "SELECT outcome, error_detail FROM company_add_attempts "
        "WHERE company_id = %s AND outcome = 'refused'",
        (company["id"],),
    )
    assert attempt is not None
    assert "RecipeError" in (attempt["error_detail"] or "")


async def test_flag_off_skips_discovery(db_conn, monkeypatch) -> None:
    monkeypatch.setattr(settings, "database_url", os.environ["DATABASE_URL"])
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", False)
    user_id = _seed_user(db_conn)

    async def _boom(url):
        raise AssertionError("discovery must not run with the flag off")

    monkeypatch.setattr(task_mod, "discover", _boom)

    await discover_custom_company(user_id, _SUBMITTED, _NORMALIZED, "careers.acme.example")
    # Nothing created.
    assert _row(db_conn, "SELECT count(*) AS n FROM companies")["n"] == 0


def test_add_discovered_company_is_idempotent(db_conn) -> None:
    """The service create path resolves a re-add to the existing row instead of
    minting a second company (UNIQUE(user_id, canonical_source_key))."""
    user_id = _seed_user(db_conn)
    first = ccs.add_discovered_company(
        db_conn, user_id=user_id, submitted_url=_SUBMITTED, normalized_url=_NORMALIZED,
        display_name="careers.acme.example", script=_recipe(),
        transport="http_json", oracle_kind="facet_sum",
    )
    second = ccs.add_discovered_company(
        db_conn, user_id=user_id, submitted_url=_SUBMITTED, normalized_url=_NORMALIZED,
        display_name="careers.acme.example", script=_recipe(),
        transport="http_json", oracle_kind="facet_sum",
    )
    assert first["id"] == second["id"]
    assert _row(db_conn, "SELECT count(*) AS n FROM companies WHERE ats = 'discovered'")["n"] == 1
