"""E7 — the discover_custom_company leaf task. $0 (the capture engine is mocked).

The task itself is called directly (``await discover_custom_company(...)``) so it opens
its OWN connection from ``settings.database_url``, pointed at the per-worker test
schema. ``discover`` is monkeypatched to return a canned outcome, so no browser, no LLM
and no network. Proves: an accept creates the four rows with the captured recipe
(``transport='http_json'`` or ``'browser_fetch'`` + the real stored ``oracle_kind``); a
refuse writes a DISABLED ``health_state='refused'`` row + a ``refused`` attempt carrying
the NAMED STEP and NO script; the ONE discovery flag gates the whole task; and the
create path is idempotent per (user, discovered-url).

The second half covers the DISCOVERY-PROGRESS CHECKLIST (E7 unit 3): the provisional row
is seeded already narrating step 1, live step writes land on it and are gated so a
straggler cannot reopen a settled board, an accept stores four ticks plus the job
preview, a refusal stores the NAMED STEP that failed, a timeout leaves the last live
snapshot alone, and a progress write that blows up never costs the discovery.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from psycopg2 import sql

import api.services.discovery.progress as dp
import api.tasks.claim_custom_companies as claim_mod
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

    async def _fake_discover(url, **kwargs):
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

    async def _fake_discover(url, **kwargs):
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

    async def _fake_discover(url, **kwargs):
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

    async def _boom(url, **kwargs):
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


# --- discovery-progress checklist (E7 unit 3) ---------------------------------


def _progress(db_conn, company_id: str) -> dict:
    row = _row(
        db_conn,
        "SELECT provider_config -> 'discovery' AS d FROM companies WHERE id = %s",
        (company_id,),
    )
    return row["d"]


def _placeholder(db_conn, user_id: str) -> str:
    """The provisional 'discovering' row the 202 add path creates, minted directly."""
    created = ccs.add_discovering_placeholder(
        db_conn, user_id=user_id, submitted_url=_SUBMITTED,
        normalized_url=_NORMALIZED, display_name="careers.acme.example",
    )
    return str(created["id"])


def test_the_provisional_row_is_seeded_with_step_one_already_running(db_conn) -> None:
    """Without the seed the row is a bare "Setting up…" badge until the queue picks the
    job up — the spinner the checklist replaced. It is also the escape hatch when the
    worker never runs at all: the user still sees which step we were on."""
    user_id = _seed_user(db_conn)
    company_id = _placeholder(db_conn, user_id)
    steps = {s["key"]: s for s in _progress(db_conn, company_id)["steps"]}
    assert steps["open_page"]["status"] == "active"
    assert len(steps) == 5
    # The harvest's rung is on the seeded blob from the very first render, pending —
    # the checklist tells the user up front that reading the board is a step too.
    assert steps["first_scan"]["status"] == "pending"


def test_live_progress_writes_land_on_the_provisional_row(db_conn) -> None:
    """The narration channel: the task publishes as each step lands and the EXISTING
    list poll picks it up — no second polling channel (DECISION D2)."""
    user_id = _seed_user(db_conn)
    company_id = _placeholder(db_conn, user_id)

    ledger = dp.ProgressLedger()
    ledger.finish(dp.STEP_OPEN_PAGE, "opened careers.acme.example — recorded 9 JSON request(s)")
    ledger.start(dp.STEP_FIND_FEED)
    assert ccs.record_discovery_progress(
        db_conn, user_id=user_id, normalized_url=_NORMALIZED, progress=ledger.snapshot()
    ) is True

    steps = {s["key"]: s for s in _progress(db_conn, company_id)["steps"]}
    assert steps["open_page"]["status"] == "done"
    assert "recorded 9" in steps["open_page"]["result"]
    assert steps["find_feed"]["status"] == "active"


def test_a_straggler_progress_write_cannot_reopen_a_settled_row(db_conn) -> None:
    """The live write races the terminal one. Gating on ``health_state='discovering'``
    makes a late step update a NO-OP instead of resurrecting "still working" on a board
    we already refused."""
    user_id = _seed_user(db_conn)
    company_id = _placeholder(db_conn, user_id)
    ccs.record_discovery_refusal(
        db_conn, user_id=user_id, submitted_url=_SUBMITTED, normalized_url=_NORMALIZED,
        display_name="careers.acme.example", reason="finding the jobs feed: nope",
        progress=dp.ProgressLedger().snapshot(outcome=dp.OUTCOME_REFUSED),
    )

    ledger = dp.ProgressLedger()
    ledger.start(dp.STEP_VERIFY_READ)
    assert ccs.record_discovery_progress(
        db_conn, user_id=user_id, normalized_url=_NORMALIZED, progress=ledger.snapshot()
    ) is False
    assert _progress(db_conn, company_id)["outcome"] == dp.OUTCOME_REFUSED


async def test_an_accept_stores_the_terminal_checklist_and_the_job_preview(
    db_conn, monkeypatch
) -> None:
    """Success has to be LEGIBLE: four ticks with their specific results plus a few of
    the jobs the ACCEPTANCE REPLAY actually returned (DECISION D3)."""
    _patch_env(monkeypatch)
    user_id = _seed_user(db_conn)
    _placeholder(db_conn, user_id)

    ledger = dp.ProgressLedger()
    ledger.finish(dp.STEP_OPEN_PAGE, "opened careers.acme.example — recorded 9 JSON request(s)")
    ledger.finish(dp.STEP_FIND_FEED, "found 2 candidate feed(s)")
    ledger.finish(dp.STEP_VERIFY_READ, "read 90 job(s)")
    ledger.finish(dp.STEP_READY, "reading the board's own feed directly — no browser needed")
    outcome = DiscoveryOutcome(
        ok=True, script=_recipe(), transport="http_json", oracle_kind="facet_sum",
        attempts=1,
        progress=ledger.snapshot(
            outcome=dp.OUTCOME_TRACKING,
            job_preview=[{"id": "1", "title": "Staff Engineer", "location": "Remote",
                          "url": "https://careers.acme.example/jobs/1"}],
        ),
    )

    async def _fake_discover(url, **kwargs):
        return outcome

    monkeypatch.setattr(task_mod, "discover", _fake_discover)
    await discover_custom_company(user_id, _SUBMITTED, _NORMALIZED, "careers.acme.example")

    company = _row(db_conn, "SELECT id, health_state FROM companies WHERE ats = 'discovered'")
    assert company["health_state"] == "unverified"       # tracked
    stored = _progress(db_conn, company["id"])
    assert stored["outcome"] == dp.OUTCOME_TRACKING
    terminal = {s["key"]: s for s in stored["steps"]}
    assert all(
        terminal[key]["status"] == "done"
        for key in ("open_page", "find_feed", "verify_read", "ready")
    )
    # ...and the harvest's rung is NOT ticked by discovery - the row has no jobs yet.
    assert terminal["first_scan"]["status"] != "done"
    assert stored["job_preview"] == [
        {"title": "Staff Engineer", "location": "Remote",
         "url": "https://careers.acme.example/jobs/1"}
    ]


async def test_a_refusal_stores_the_named_step_that_failed(db_conn, monkeypatch) -> None:
    """"Not trackable" with nothing else is a dead end. The failed step is what makes it
    "we found the feed, but couldn't confirm the results match" — and the audit row that
    also carries it is not readable by any endpoint, so this blob is the ONLY path from
    the refusal to the user."""
    _patch_env(monkeypatch)
    user_id = _seed_user(db_conn)
    _placeholder(db_conn, user_id)

    ledger = dp.ProgressLedger()
    ledger.finish(dp.STEP_OPEN_PAGE, "opened careers.acme.example — recorded 9 JSON request(s)")
    ledger.finish(dp.STEP_FIND_FEED, "found 2 candidate feed(s)")
    ledger.fail(dp.STEP_VERIFY_READ,
                "only 0 of the 12 job(s) the browser saw came back from the replay")
    outcome = DiscoveryOutcome(
        ok=False, refuse_reason="verifying we can read it: …", attempts=2,
        progress=ledger.snapshot(outcome=dp.OUTCOME_REFUSED),
    )

    async def _fake_discover(url, **kwargs):
        return outcome

    monkeypatch.setattr(task_mod, "discover", _fake_discover)
    await discover_custom_company(user_id, _SUBMITTED, _NORMALIZED, "careers.acme.example")

    company = _row(db_conn, "SELECT id, health_state FROM companies WHERE ats = 'discovered'")
    assert company["health_state"] == "refused"
    steps = {s["key"]: s for s in _progress(db_conn, company["id"])["steps"]}
    assert steps["find_feed"]["status"] == "done"
    assert steps["verify_read"]["status"] == "failed"
    assert "came back from the replay" in steps["verify_read"]["result"]


async def test_a_timeout_leaves_the_last_live_checklist_in_place(db_conn, monkeypatch) -> None:
    """There is no outcome to carry a terminal checklist, so the refusal must not wipe
    the narration — how far we got before the clock ran out is the useful thing."""
    _patch_env(monkeypatch)
    user_id = _seed_user(db_conn)
    company_id = _placeholder(db_conn, user_id)

    ledger = dp.ProgressLedger()
    ledger.finish(dp.STEP_OPEN_PAGE, "opened careers.acme.example — recorded 9 JSON request(s)")
    ledger.start(dp.STEP_FIND_FEED)
    ccs.record_discovery_progress(
        db_conn, user_id=user_id, normalized_url=_NORMALIZED, progress=ledger.snapshot()
    )

    async def _hang(url, **kwargs):
        raise asyncio.TimeoutError

    monkeypatch.setattr(task_mod, "discover", _hang)
    await discover_custom_company(user_id, _SUBMITTED, _NORMALIZED, "careers.acme.example")

    assert _row(db_conn, "SELECT health_state FROM companies WHERE id = %s",
                (company_id,))["health_state"] == "refused"
    steps = {s["key"]: s for s in _progress(db_conn, company_id)["steps"]}
    assert steps["open_page"]["status"] == "done"
    assert steps["find_feed"]["status"] == "active"


async def test_a_failing_progress_write_never_costs_the_discovery(db_conn, monkeypatch) -> None:
    """The narration is cosmetic; the discovery is not. A database blip while we are
    narrating must not refuse a board we can read — the exact inversion of the point.
    Drives the REAL ``emit`` callback the task builds, not a stand-in."""
    _patch_env(monkeypatch)
    user_id = _seed_user(db_conn)
    _placeholder(db_conn, user_id)

    def _explode(*args, **kwargs):
        raise RuntimeError("progress connection is down")

    monkeypatch.setattr(task_mod.ccs, "record_discovery_progress", _explode)

    async def _fake_discover(url, **kwargs):
        await kwargs["emit"](dp.ProgressLedger().snapshot())
        return DiscoveryOutcome(
            ok=True, script=_recipe(), transport="http_json",
            oracle_kind="facet_sum", attempts=1,
        )

    monkeypatch.setattr(task_mod, "discover", _fake_discover)
    await discover_custom_company(user_id, _SUBMITTED, _NORMALIZED, "careers.acme.example")

    assert _row(
        db_conn, "SELECT health_state FROM companies WHERE ats = 'discovered'"
    )["health_state"] == "unverified"


# --- the FIRST harvest: jobs without waiting for a claim tick (E7) -------------
#
# What this section pins is the whole answer to "I added a board and it shows 0 jobs".
# Discovery used to accept a board, mark it tracked with every step green, and leave the
# actual reading to the ``*/15 * * * *`` claim tick — so the user watched a finished
# checklist sit above "0 open jobs" for up to a quarter of an hour. The accept now
# enqueues the first harvest itself, and the two enqueue paths must be provably unable
# to run the same board twice.


def _accepting(monkeypatch, transport: str = "http_json") -> None:
    """Patch ``discover`` to ACCEPT with a recipe on ``transport``."""
    script = _recipe()
    script["transport"] = transport
    outcome = DiscoveryOutcome(
        ok=True, script=script, transport=transport,
        oracle_kind="facet_sum", attempts=1,
    )

    async def _fake_discover(url, **kwargs):
        return outcome

    monkeypatch.setattr(task_mod, "discover", _fake_discover)


def _record_defers(monkeypatch, result: str = "deferred") -> list[str]:
    """Capture every ``fetch_custom_company`` enqueue from BOTH paths.

    Patched on the claim module and re-patched on the discovery task's own binding,
    because the task imported the name — so a test that only patched one of the two
    would silently measure half the system.
    """
    calls: list[str] = []

    async def _defer(company_id: str) -> str:
        calls.append(company_id)
        return result

    monkeypatch.setattr(claim_mod, "defer_fetch", _defer)
    monkeypatch.setattr(task_mod, "defer_fetch", _defer)
    return calls


def _seconds_until_next_run(db_conn, company_id: str) -> float:
    db_conn.rollback()
    row = _row(
        db_conn,
        "SELECT EXTRACT(EPOCH FROM (next_run_at - now())) AS s "
        "FROM companies WHERE id = %s",
        (company_id,),
    )
    return float(row["s"])


def _discovered_id(db_conn, board_url: str) -> str:
    db_conn.rollback()
    return str(
        _row(
            db_conn,
            "SELECT id FROM companies WHERE ats = 'discovered' AND board_token = %s",
            (board_url,),
        )["id"]
    )


async def test_an_accept_enqueues_the_first_harvest_immediately(db_conn, monkeypatch) -> None:
    """THE FIX. Without this the board is tracked, green all the way down, and empty
    until the next 15-minute tick — which reads as "we looked and your board has no
    jobs" rather than "we have not read it yet"."""
    _patch_env(monkeypatch)
    user_id = _seed_user(db_conn)
    url = "https://careers.first-harvest.example/jobs"
    _accepting(monkeypatch)
    calls = _record_defers(monkeypatch)

    await discover_custom_company(user_id, _SUBMITTED, url, "first-harvest.example")

    assert calls == [_discovered_id(db_conn, url)]


async def test_the_immediate_harvest_takes_the_row_off_the_claim_ticks_list(
    db_conn, monkeypatch
) -> None:
    """THE INTERLOCK, primary half. ``add_discovered_company`` leaves ``next_run_at =
    now()``; once the harvest is on the broker the row is pushed a full cadence ahead,
    so the tick — which selects on ``next_run_at <= now()`` — cannot even see it. That
    is what makes a second, concurrent harvest of the same board impossible rather than
    merely unlikely."""
    _patch_env(monkeypatch)
    user_id = _seed_user(db_conn)
    url = "https://careers.interlock.example/jobs"
    _accepting(monkeypatch)
    _record_defers(monkeypatch)

    await discover_custom_company(user_id, _SUBMITTED, url, "interlock.example")
    company_id = _discovered_id(db_conn, url)

    # A cadence (24h) minus the ±90 min jitter floor — i.e. nowhere near due.
    assert _seconds_until_next_run(db_conn, company_id) > 22 * 3600
    assert company_id not in claim_mod._claim_due_companies(db_conn, 10)


async def test_a_claim_tick_right_after_an_accept_queues_no_second_harvest(
    db_conn, monkeypatch
) -> None:
    """END TO END: accept, then fire the real periodic tick. Exactly ONE
    ``fetch_custom_company`` exists for the board — the tick is a no-op for it, not a
    duplicate."""
    _patch_env(monkeypatch)
    user_id = _seed_user(db_conn)
    url = "https://careers.one-run.example/jobs"
    _accepting(monkeypatch)
    calls = _record_defers(monkeypatch)

    await discover_custom_company(user_id, _SUBMITTED, url, "one-run.example")
    company_id = _discovered_id(db_conn, url)

    # Park every OTHER row this module-scoped schema accumulated, so the tick's budget
    # of 3 cannot be spent elsewhere and mask the result.
    cur = db_conn.cursor()
    cur.execute("UPDATE companies SET next_run_at = NULL WHERE id <> %s", (company_id,))
    db_conn.commit()

    assert await claim_mod.claim_custom_companies(timestamp=1) == 0
    assert calls.count(company_id) == 1


async def test_a_failed_defer_leaves_the_row_due_for_the_next_claim_tick(
    db_conn, monkeypatch
) -> None:
    """The safe direction. A broker that would not take the job must NOT also cost the
    board a cadence: the row stays due so the 15-minute tick runs it — exactly the
    behaviour that existed before the immediate enqueue."""
    _patch_env(monkeypatch)
    user_id = _seed_user(db_conn)
    url = "https://careers.broker-down.example/jobs"
    _accepting(monkeypatch)
    _record_defers(monkeypatch, result="failed")

    await discover_custom_company(user_id, _SUBMITTED, url, "broker-down.example")
    company_id = _discovered_id(db_conn, url)

    assert _seconds_until_next_run(db_conn, company_id) < 60
    assert company_id in claim_mod._claim_due_companies(db_conn, 10)


async def test_a_refusal_never_enqueues_a_harvest(db_conn, monkeypatch) -> None:
    """A refused board has no script and ``enabled=FALSE``; enqueueing a harvest for it
    would be a job that can only no-op, and the row must stay off every schedule."""
    _patch_env(monkeypatch)
    user_id = _seed_user(db_conn)
    url = "https://careers.refused-nofetch.example/jobs"
    calls = _record_defers(monkeypatch)

    async def _fake_discover(u, **kwargs):
        return DiscoveryOutcome(ok=False, refuse_reason="finding the jobs feed: nope",
                                attempts=1)

    monkeypatch.setattr(task_mod, "discover", _fake_discover)
    await discover_custom_company(user_id, _SUBMITTED, url, "refused-nofetch.example")

    assert calls == []


async def test_the_kill_switch_stops_an_immediate_browser_fetch_harvest(
    db_conn, monkeypatch
) -> None:
    """The flag can flip DURING a 240-second discovery. The immediate enqueue applies the
    same rule the leaf task does — a browser_fetch harvest is skipped while discovery is
    off — so we do not queue a job whose only possible outcome is a no-op, and the row
    stays due so the tick picks it up for free once the flag returns."""
    _patch_env(monkeypatch)
    user_id = _seed_user(db_conn)
    url = "https://careers.killswitch.example/jobs"
    calls = _record_defers(monkeypatch)

    script = _recipe()
    script["transport"] = "browser_fetch"
    outcome = DiscoveryOutcome(
        ok=True, script=script, transport="browser_fetch",
        oracle_kind="self_consistent", attempts=1,
    )

    async def _fake_discover(u, **kwargs):
        # Flipped off mid-run, after the task's own entry gate passed.
        monkeypatch.setattr(settings, "custom_company_discovery_enabled", False)
        return outcome

    monkeypatch.setattr(task_mod, "discover", _fake_discover)
    await discover_custom_company(user_id, _SUBMITTED, url, "killswitch.example")

    assert calls == []
    company_id = _discovered_id(db_conn, url)
    assert _seconds_until_next_run(db_conn, company_id) < 60


async def test_an_http_json_board_is_not_gated_by_the_discovery_kill_switch(
    db_conn, monkeypatch
) -> None:
    """The leaf task gates only the browser_fetch tier on that flag (an http_json replay
    opens no browser), so neither does this. Gating it here would quietly stop harvesting
    a whole class of board the leaf task is perfectly willing to run."""
    _patch_env(monkeypatch)
    user_id = _seed_user(db_conn)
    url = "https://careers.httpjson-flag.example/jobs"
    calls = _record_defers(monkeypatch)

    script = _recipe()
    outcome = DiscoveryOutcome(
        ok=True, script=script, transport="http_json",
        oracle_kind="facet_sum", attempts=1,
    )

    async def _fake_discover(u, **kwargs):
        monkeypatch.setattr(settings, "custom_company_discovery_enabled", False)
        return outcome

    monkeypatch.setattr(task_mod, "discover", _fake_discover)
    await discover_custom_company(user_id, _SUBMITTED, url, "httpjson-flag.example")

    assert calls == [_discovered_id(db_conn, url)]
