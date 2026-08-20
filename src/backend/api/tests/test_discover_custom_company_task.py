"""E7 — the discover_custom_company leaf task. $0 (the capture engine is mocked).

The task itself is called directly (``await discover_custom_company(...)``) so it opens
its OWN connection from ``settings.database_url``, pointed at the per-worker test
schema. ``discover`` is monkeypatched to return a canned outcome, so no browser, no LLM
and no network. Proves: an accept creates the four rows with the captured recipe
(``transport='http_json'`` or ``'browser_fetch'`` + the real stored ``oracle_kind``); a
refuse writes a DISABLED ``health_state='refused'`` row + a ``refused`` attempt carrying
the NAMED STEP and NO script; the ONE discovery flag gates the whole task; and the
create path is idempotent per (user, discovered-url).
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
    # ONE flag since the capture pivot — see test_flag_off_skips_discovery.
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)


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
    outcome = DiscoveryOutcome(
        ok=False,
        refuse_reason="verifying we can read it: only 0 of the 12 job(s) the browser saw "
                      "came back from the replay — we are not reading the same list",
        attempts=2,
    )

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
    # The NAMED STEP survives into the audit row — it is what the UI renders instead of
    # a bare "discovery failed", so losing it here loses the user's only next action.
    assert "verifying we can read it" in (attempt["error_detail"] or "")


async def test_browser_fetch_outcome_stores_that_transport(db_conn, monkeypatch) -> None:
    """A board whose API only replays inside our own Chromium stores
    ``transport='browser_fetch'`` — free text on the column, so no migration, and the
    nightly leaf task routes on exactly this value."""
    _patch_env(monkeypatch)
    user_id = _seed_user(db_conn)
    script = _recipe()
    script["transport"] = "browser_fetch"
    script["origin_url"] = "https://careers.acme.example/jobs"
    script["oracle"] = {"kind": "self_consistent"}
    outcome = DiscoveryOutcome(
        ok=True, script=script, transport="browser_fetch",
        oracle_kind="self_consistent", attempts=1,
    )

    async def _fake_discover(url):
        return outcome

    monkeypatch.setattr(task_mod, "discover", _fake_discover)
    await discover_custom_company(user_id, _SUBMITTED, _NORMALIZED, "careers.acme.example")

    company = _row(db_conn, "SELECT id FROM companies WHERE ats = 'discovered'")
    stored = _row(
        db_conn,
        "SELECT transport, oracle_kind FROM company_scripts WHERE company_id = %s",
        (company["id"],),
    )
    assert stored["transport"] == "browser_fetch"
    assert stored["oracle_kind"] == "self_consistent"


async def test_flag_off_skips_discovery(db_conn, monkeypatch) -> None:
    """ONE flag gates the task (defence in depth behind the router's identical gate).
    ``browser_agent_enabled`` is gone: two gates made "discovery is off"
    indistinguishable from "this board is unsupported"."""
    monkeypatch.setattr(settings, "database_url", os.environ["DATABASE_URL"])
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", False)
    assert not hasattr(settings, "browser_agent_enabled")
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
