"""Launch Radar service SQL (``api/services/launch_radar.py``) against real Postgres.

Covers the ledger (run budget, global cap, accrued spend past the cap, the
advisory lock under concurrency), run start/finish, the card lifecycle with its
tombstone, the PR-request hooks on each card move (PLAN §2.1), the loop's PR
queue (claim, report, requeue, list; PLAN §2.2), the domain dedupe, ``seen``
and the Monitors.

The ``db_conn`` schema comes from ``create_all``, so the launch_radar_* tables
exist; conftest's ``clean_tables`` does not know about them, so this module's
autouse fixture truncates them before every test. ``make_payload`` and
``start_test_run`` are reused by the router test modules.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import psycopg2
import pytest
from psycopg2.extras import RealDictCursor

from api.config import settings
from api.models import LaunchRadarPayload
from api.services import launch_radar as svc

from .conftest import TEST_DB_URL

_LR_TABLES = (
    "launch_radar_pr_requests, launch_radar_spend, launch_radar_cards, "
    "launch_radar_runs, launch_radar_monitors"
)


def truncate_launch_radar(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute(f"TRUNCATE {_LR_TABLES} RESTART IDENTITY CASCADE")
    conn.commit()


@pytest.fixture(autouse=True)
def _launch_radar_isolation(db_conn):
    truncate_launch_radar(db_conn)
    prev_cap = settings.launch_radar_spend_cap_usd
    settings.launch_radar_spend_cap_usd = 5.0
    yield
    settings.launch_radar_spend_cap_usd = prev_cap
    db_conn.rollback()


def make_payload(domain: str = "raindrop.ai", **overrides: Any) -> dict[str, Any]:
    """A complete, valid snake_case card payload (CONTRACT §4)."""
    payload: dict[str, Any] = {
        "company": "Raindrop AI",
        "domain": domain,
        "website": f"https://www.{domain}",
        "one_liner": "Monitoring for AI agents",
        "what_they_do": "Observability for agent products.",
        "blurb": "Raindrop watches AI agents in production.",
        "event": {
            "type": "funding",
            "headline": "Raindrop raises $35M Series A",
            "source_url": "https://techcrunch.com/raindrop",
            "announced_at": "2026-09-17",
            "round": "Series A",
            "amount_usd": "$35M",
            "investors": "CRV, Lightspeed",
            "origin": "monitor",
        },
        "scores": {
            "talent": 49,
            "vc": 55,
            "talent_reasons": ["Sam Rivera: top employer (Apple)"],
            "vc_reasons": ["CRV led (tier 2)"],
        },
        "leaders": [
            {
                "name": "Sam Rivera",
                "title": "Co-Founder & CTO",
                "linkedin_url": "https://linkedin.com/in/example-sam-rivera",
                "profile_url": "https://example.com/ben",
                "summary": "WPI. Apple visionOS designer",
                "schools": ["Worcester Polytechnic Institute BS Robotics"],
                "prior_companies": ["Apple (Designer)"],
                "founded_before": [],
                "years_experience": 8,
                "industry_experience": None,
                "signals": ["Apple Design"],
            }
        ],
        "leaders_dropped": 1,
        "team_stats": {
            "profiles_found": 6,
            "team_size_estimate": "approximately 10-20",
            "schools": [{"name": "UC Davis", "count": 1}],
            "prior_employers": [{"name": "Amazon", "count": 2}],
            "sample_names": ["A Person"],
        },
        "funding": {
            "latest_round": {
                "stage": "Series A",
                "amount_usd": "$35M",
                "announced_at": "2026-09-17",
                "lead_investors": ["CRV"],
                "other_investors": ["Lightspeed Venture Partners"],
            },
            "prior_rounds": [],
            "total_raised_usd": "$50M",
        },
        "notable_facts": ["Fact one", "Fact two"],
        "careers_url": "https://jobs.ashbyhq.com/Raindrop",
        "ats": {
            "provider": "ashby",
            "board_token": "Raindrop",
            "board_url": "https://jobs.ashbyhq.com/Raindrop",
            "verified": True,
            "job_count": 9,
            "checked_url": "https://api.ashbyhq.com/posting-api/job-board/Raindrop",
        },
        "sources": [{"url": "https://techcrunch.com/raindrop", "title": None, "field": None}],
        "parallel_run_ids": {
            "findall_id": "findall_1",
            "brief_run_id": "trun_1",
            "team_run_id": "trun_2",
            "pedigree_group_id": "tgrp_1",
        },
        "cost_usd": 0.3,
        "timings_s": {"findall_s": 154.0},
        "issues": [],
        "generated_at": "2026-10-07T01:36:00Z",
    }
    payload.update(overrides)
    return payload


def stored_payload(**kw: Any) -> dict[str, Any]:
    """What the route stores: the validated model dumped in JSON mode."""
    return LaunchRadarPayload.model_validate(make_payload(**kw)).model_dump(mode="json")


def start_test_run(conn: Any, run_uuid: str = "run-0001", budget: float = 1.0) -> int:
    return svc.start_run(conn, run_uuid, "test-host", budget)["run_id"]


def _insert_company(conn: Any, cid: str, ats: str, token: str, *, visibility: str = "public",
                    name: str | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO companies (id, display_name, ats, board_token, visibility) "
            "VALUES (%s, %s, %s, %s, %s)",
            (cid, name or cid.title(), ats, token, visibility),
        )
    conn.commit()


def _card(conn: Any, card_id: int) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM launch_radar_cards WHERE id = %s", (card_id,))
        row = cur.fetchone()
    conn.rollback()
    return dict(row)


# ---------------------------------------------------------------------------
# normalize_domain — the shared vectors (CONTRACT §3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HTTPS://WWW.Raindrop.AI/blog/series-a/", "raindrop.ai"),
        ("athennian.com", "athennian.com"),
        ("ghost.ai:443", "ghost.ai"),
        ("user@www.Example.com/x?y#z", "example.com"),
        ("NA", None),
        ("localhost", None),
        ("", None),
        (None, None),
        (42, None),
    ],
)
def test_normalize_domain_vectors(raw: Any, expected: str | None) -> None:
    assert svc.normalize_domain(raw) == expected


# ---------------------------------------------------------------------------
# Runs and the ledger
# ---------------------------------------------------------------------------


class TestRuns:
    def test_start_run_is_idempotent_on_run_uuid(self, db_conn) -> None:
        first = svc.start_run(db_conn, "run-abcdef01", "laptop", 1.0)
        again = svc.start_run(db_conn, "run-abcdef01", "other", 2.0)
        assert again["run_id"] == first["run_id"]
        assert again["budget_usd"] == 1.0  # the original row, not the retry's budget
        assert first["cap_usd"] == 5.0
        assert first["remaining_usd"] == 5.0
        assert first["monitors"] == []

    def test_start_run_reports_existing_spend_and_active_monitors_only(self, db_conn) -> None:
        start_test_run(db_conn, "run-old-0001")
        svc.reserve_spend(db_conn, "run-old-0001", "findall.create", 0.46, None, False)
        now = datetime(2026, 10, 7, 7, tzinfo=timezone.utc)
        svc.put_monitor(db_conn, "seed", "monitor_a", "q", "base", "1d", "active", now)
        svc.put_monitor(db_conn, "launch", "monitor_b", "q", "base", "1d", "cancelled", now)
        started = svc.start_run(db_conn, "run-new-0001", None, 1.0)
        assert started["run_spend_usd"] == 0.0
        assert started["total_spend_usd"] == 0.46
        assert started["remaining_usd"] == 4.54
        assert [m["slot"] for m in started["monitors"]] == ["seed"]

    def test_finish_run_then_finish_again_is_conflict(self, db_conn) -> None:
        start_test_run(db_conn)
        svc.reserve_spend(db_conn, "run-0001", "task_run.create(brief)", 0.1, "x.ai", False)
        done = svc.finish_run(db_conn, "run-0001", "ok", 3, 0, "fine")
        assert done["status"] == "ok"
        assert done["run_spend_usd"] == 0.1
        with pytest.raises(svc.Conflict):
            svc.finish_run(db_conn, "run-0001", "ok", 3, 0, None)

    def test_finish_stores_the_backend_card_count_and_notes_a_mismatch(self, db_conn) -> None:
        start_test_run(db_conn)
        svc.insert_card(db_conn, "run-0001", stored_payload())  # committed; the loop never saw the 201
        svc.finish_run(db_conn, "run-0001", "error", 2, 0, "error 1; 0 queued")
        with db_conn.cursor() as cur:
            cur.execute("SELECT cards_posted, notes FROM launch_radar_runs WHERE run_uuid = 'run-0001'")
            row = cur.fetchone()
        db_conn.rollback()
        assert row["cards_posted"] == 1
        assert row["notes"] == "error 1; 0 queued; loop reported 0 card(s), backend counted 1"

    def test_start_run_closes_runs_abandoned_while_running(self, db_conn) -> None:
        start_test_run(db_conn, "run-dead-0001")
        start_test_run(db_conn, "run-fresh-001")
        with db_conn.cursor() as cur:
            cur.execute("UPDATE launch_radar_runs SET started_at = now() - interval '2 hours' "
                        "WHERE run_uuid = 'run-dead-0001'")
        db_conn.commit()
        start_test_run(db_conn, "run-next-0001")
        with db_conn.cursor() as cur:
            cur.execute("SELECT run_uuid, status, notes, ended_at FROM launch_radar_runs ORDER BY id")
            rows = {r["run_uuid"]: r for r in cur.fetchall()}
        db_conn.rollback()
        assert rows["run-dead-0001"]["status"] == "error"
        assert rows["run-dead-0001"]["notes"] == "abandoned: never finished"
        assert rows["run-dead-0001"]["ended_at"] is not None
        assert rows["run-fresh-001"]["status"] == "running"  # recent: may still be alive
        assert rows["run-next-0001"]["status"] == "running"

    def test_finish_unknown_run_is_not_found(self, db_conn) -> None:
        with pytest.raises(svc.NotFound):
            svc.finish_run(db_conn, "run-missing", "ok", 0, 0, None)


class TestLedger:
    def test_reserve_records_and_reports_totals(self, db_conn) -> None:
        start_test_run(db_conn)
        out = svc.reserve_spend(db_conn, "run-0001", "findall.create", 0.1, "a.ai", False)
        assert out == {
            "reserved_usd": 0.1,
            "run_spend_usd": 0.1,
            "total_spend_usd": 0.1,
            "cap_usd": 5.0,
            "over_cap": False,
        }
        out = svc.reserve_spend(db_conn, "run-0001", "task_run.create(brief)", 0.035, "a.ai", False)
        assert out["run_spend_usd"] == 0.135

    def test_tiny_estimate_rounds_up_never_to_zero(self, db_conn) -> None:
        start_test_run(db_conn)
        out = svc.reserve_spend(db_conn, "run-0001", "s", 0.00001, None, False)
        assert out["reserved_usd"] == 0.0001

    def test_run_budget_refuses_and_writes_nothing(self, db_conn) -> None:
        start_test_run(db_conn, budget=0.2)
        svc.reserve_spend(db_conn, "run-0001", "a", 0.15, None, False)
        with pytest.raises(svc.BudgetExceeded) as exc:
            svc.reserve_spend(db_conn, "run-0001", "b", 0.1, None, False)
        assert exc.value.detail() == {
            "reason": "run_budget",
            "run_spend_usd": 0.15,
            "total_spend_usd": 0.15,
            "cap_usd": 5.0,
        }
        with db_conn.cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM launch_radar_spend")
            assert cur.fetchone()["n"] == 1
        db_conn.rollback()

    def test_global_cap_spans_runs(self, db_conn) -> None:
        settings.launch_radar_spend_cap_usd = 1.0
        start_test_run(db_conn, "run-aaaa0001", budget=1.0)
        svc.reserve_spend(db_conn, "run-aaaa0001", "a", 0.9, None, False)
        start_test_run(db_conn, "run-bbbb0001", budget=1.0)
        with pytest.raises(svc.BudgetExceeded) as exc:
            svc.reserve_spend(db_conn, "run-bbbb0001", "b", 0.2, None, False)
        assert exc.value.reason == "cap"
        assert exc.value.detail()["total_spend_usd"] == 0.9
        # Exactly at the cap is allowed; only PAST it is refused.
        out = svc.reserve_spend(db_conn, "run-bbbb0001", "c", 0.1, None, False)
        assert out["total_spend_usd"] == 1.0
        assert out["over_cap"] is False

    def test_accrued_spend_is_recorded_past_the_cap(self, db_conn) -> None:
        settings.launch_radar_spend_cap_usd = 0.5
        start_test_run(db_conn, budget=0.5)
        svc.reserve_spend(db_conn, "run-0001", "a", 0.45, None, False)
        out = svc.reserve_spend(db_conn, "run-0001", "monitor.accrued", 0.09, None, True)
        assert out["over_cap"] is True
        assert out["total_spend_usd"] == 0.54
        # ...and the next billed call is refused against the cap.
        with pytest.raises(svc.BudgetExceeded):
            svc.reserve_spend(db_conn, "run-0001", "b", 0.01, None, False)

    def test_reserve_on_unknown_or_finished_run(self, db_conn) -> None:
        with pytest.raises(svc.NotFound):
            svc.reserve_spend(db_conn, "run-missing", "a", 0.1, None, False)
        start_test_run(db_conn)
        svc.finish_run(db_conn, "run-0001", "stopped", 0, 0, None)
        with pytest.raises(svc.Conflict):
            svc.reserve_spend(db_conn, "run-0001", "a", 0.1, None, False)

    def test_concurrent_reservations_never_both_pass_the_cap(self, db_conn) -> None:
        """Two runs racing for the last $0.30 of a $1.00 cap: the advisory lock
        serializes them, so exactly one succeeds."""
        settings.launch_radar_spend_cap_usd = 1.0
        start_test_run(db_conn, "run-cccc0001", budget=1.0)
        svc.reserve_spend(db_conn, "run-cccc0001", "seed", 0.7, None, False)
        start_test_run(db_conn, "run-dddd0001", budget=1.0)
        start_test_run(db_conn, "run-eeee0001", budget=1.0)
        schema = os.environ["PYTEST_SCHEMA"]
        barrier = threading.Barrier(2)
        results: list[str] = []

        def _worker(run_uuid: str) -> None:
            conn = psycopg2.connect(TEST_DB_URL, cursor_factory=RealDictCursor)
            try:
                with conn.cursor() as cur:
                    cur.execute(f'SET search_path TO "{schema}", public')
                conn.commit()
                barrier.wait()
                try:
                    svc.reserve_spend(conn, run_uuid, "race", 0.2, None, False)
                    results.append("ok")
                except svc.BudgetExceeded as exc:
                    results.append(exc.reason)
            finally:
                conn.close()

        threads = [
            threading.Thread(target=_worker, args=(u,)) for u in ("run-dddd0001", "run-eeee0001")
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert sorted(results) == ["cap", "ok"]
        with db_conn.cursor() as cur:
            cur.execute("SELECT SUM(amount_usd) AS s FROM launch_radar_spend")
            assert cur.fetchone()["s"] == Decimal("0.9000")
        db_conn.rollback()


# ---------------------------------------------------------------------------
# Cards: insert, dedupe, tracked resolution
# ---------------------------------------------------------------------------


class TestInsertCard:
    def test_insert_counts_on_the_run_and_stores_payload(self, db_conn) -> None:
        start_test_run(db_conn)
        out = svc.insert_card(db_conn, "run-0001", stored_payload())
        assert out["tracked_company_id"] is None
        row = _card(db_conn, out["id"])
        assert row["status"] == "new"
        assert row["domain"] == "raindrop.ai"
        assert row["company_name"] == "Raindrop AI"
        assert row["payload"]["scores"]["talent"] == 49
        with db_conn.cursor() as cur:
            cur.execute("SELECT cards_posted FROM launch_radar_runs")
            assert cur.fetchone()["cards_posted"] == 1
        db_conn.rollback()

    def test_same_domain_twice_is_domain_seen(self, db_conn) -> None:
        start_test_run(db_conn)
        svc.insert_card(db_conn, "run-0001", stored_payload())
        with pytest.raises(svc.DomainSeen):
            svc.insert_card(db_conn, "run-0001", stored_payload(company="Other"))

    def test_tombstoned_domain_is_still_seen(self, db_conn) -> None:
        start_test_run(db_conn)
        card = svc.insert_card(db_conn, "run-0001", stored_payload())["id"]
        svc.set_status(db_conn, card, "archived", "a@x.com")
        svc.delete_card(db_conn, card, "a@x.com")
        with pytest.raises(svc.DomainSeen):
            svc.insert_card(db_conn, "run-0001", stored_payload())

    def test_unnormalized_domain_is_invalid(self, db_conn) -> None:
        start_test_run(db_conn)
        with pytest.raises(svc.InvalidDomain):
            svc.insert_card(db_conn, "run-0001", stored_payload(domain="www.raindrop.ai"))

    def test_run_must_exist_and_be_running(self, db_conn) -> None:
        with pytest.raises(svc.NotFound):
            svc.insert_card(db_conn, "run-missing", stored_payload())
        start_test_run(db_conn)
        svc.finish_run(db_conn, "run-0001", "ok", 0, 0, None)
        with pytest.raises(svc.Conflict):
            svc.insert_card(db_conn, "run-0001", stored_payload())

    def test_tracked_company_resolved_case_insensitively_public_only(self, db_conn) -> None:
        _insert_company(db_conn, "raindrop", "ashby", "raindrop")
        _insert_company(db_conn, "private-ghost", "ashby", "ghost", visibility="user")
        start_test_run(db_conn)
        tracked = svc.insert_card(db_conn, "run-0001", stored_payload())
        assert tracked["tracked_company_id"] == "raindrop"
        ghost = make_payload(domain="ghost.ai")
        ghost["ats"] = {**ghost["ats"], "board_token": "ghost"}
        untracked = svc.insert_card(
            db_conn, "run-0001", LaunchRadarPayload.model_validate(ghost).model_dump(mode="json")
        )
        assert untracked["tracked_company_id"] is None

    def test_null_board_token_skips_the_lookup(self, db_conn) -> None:
        _insert_company(db_conn, "raindrop", "ashby", "raindrop")
        payload = make_payload()
        payload["ats"] = {**payload["ats"], "board_token": None}
        start_test_run(db_conn)
        out = svc.insert_card(
            db_conn, "run-0001", LaunchRadarPayload.model_validate(payload).model_dump(mode="json")
        )
        assert out["tracked_company_id"] is None

    def test_tracked_id_outlives_its_company_row(self, db_conn) -> None:
        """A soft link (no FK): deleting the company does not fail and does not
        null the card's id, so the card keeps reading as tracked. Harmless, and
        pinned so it stays chosen."""
        _insert_company(db_conn, "raindrop", "ashby", "raindrop")
        start_test_run(db_conn)
        card = svc.insert_card(db_conn, "run-0001", stored_payload())["id"]
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM companies WHERE id = 'raindrop'")
        db_conn.commit()
        rows, total = svc.list_cards(db_conn, "new", 25, 0)
        assert total == 1 and rows[0]["id"] == card
        assert rows[0]["tracked_company_id"] == "raindrop"


# ---------------------------------------------------------------------------
# Lifecycle: list / archive / restore / delete (tombstone)
# ---------------------------------------------------------------------------


class TestLifecycle:
    def _seed(self, db_conn, *domains: str) -> list[int]:
        start_test_run(db_conn)
        return [
            svc.insert_card(db_conn, "run-0001", stored_payload(domain=d))["id"] for d in domains
        ]

    def test_list_counts_and_order(self, db_conn) -> None:
        a, b, c = self._seed(db_conn, "a.ai", "b.ai", "c.ai")
        svc.set_status(db_conn, a, "archived", "x@y.com")
        svc.set_status(db_conn, c, "archived", "x@y.com")
        new_rows, new_total = svc.list_cards(db_conn, "new", 25, 0)
        assert [r["id"] for r in new_rows] == [b] and new_total == 1
        archived, archived_total = svc.list_cards(db_conn, "archived", 25, 0)
        # The default sort (announced) on every tab: same announcement date, so
        # newest posted first (c was posted after a).
        assert [r["id"] for r in archived] == [c, a] and archived_total == 2
        assert svc.list_cards(db_conn, "saved", 25, 0) == ([], 0)
        assert svc.card_counts(db_conn) == {"new": 1, "saved": 0, "archived": 2}

    def test_saved_tab_lists_newest_posted_first_and_counts(self, db_conn) -> None:
        a, b, c, d = self._seed(db_conn, "a.ai", "b.ai", "c.ai", "d.ai")
        # Saved in the order c, a: with equal announcement dates the tab still
        # reads newest-POSTED first, not most-recently-saved.
        svc.set_status(db_conn, c, "saved", "x@y.com")
        svc.set_status(db_conn, a, "saved", "x@y.com")
        svc.set_status(db_conn, d, "archived", "x@y.com")
        saved, saved_total = svc.list_cards(db_conn, "saved", 25, 0)
        assert [r["id"] for r in saved] == [c, a] and saved_total == 2
        assert [r["id"] for r in svc.list_cards(db_conn, "saved", 1, 1)[0]] == [a]
        new_rows, new_total = svc.list_cards(db_conn, "new", 25, 0)
        assert [r["id"] for r in new_rows] == [b] and new_total == 1
        # A card is in exactly one tab.
        assert svc.card_counts(db_conn) == {"new": 1, "saved": 2, "archived": 1}

    def test_archive_restore_round_trip(self, db_conn) -> None:
        (card,) = self._seed(db_conn, "a.ai")
        row = svc.set_status(db_conn, card, "archived", "admin@x.com")
        assert row["status"] == "archived" and row["archived_at"] is not None
        assert row["updated_by"] == "admin@x.com"
        row = svc.set_status(db_conn, card, "new", "admin@x.com")
        assert row["status"] == "new" and row["archived_at"] is None

    def test_save_unsave_round_trip(self, db_conn) -> None:
        (card,) = self._seed(db_conn, "a.ai")
        row = svc.set_status(db_conn, card, "saved", "admin@x.com")
        assert row["status"] == "saved" and row["archived_at"] is None
        assert row["updated_by"] == "admin@x.com"
        assert row["payload"] is not None and row["domain"] == "a.ai"
        row = svc.set_status(db_conn, card, "new", "other@x.com")  # Unsave
        assert row["status"] == "new" and row["archived_at"] is None
        assert row["updated_by"] == "other@x.com"

    def test_archive_a_saved_card_then_restore_lands_in_new(self, db_conn) -> None:
        (card,) = self._seed(db_conn, "a.ai")
        svc.set_status(db_conn, card, "saved", "x")
        row = svc.set_status(db_conn, card, "archived", "x")
        assert row["status"] == "archived" and row["archived_at"] is not None
        row = svc.set_status(db_conn, card, "new", "x")  # Restore -> New, not Saved
        assert row["status"] == "new" and row["archived_at"] is None

    def test_expected_from_makes_the_move_a_compare_and_swap(self, db_conn) -> None:
        """Unsave and Restore both send ``new``: without ``from`` a stale Unsave (the
        card was archived meanwhile) would restore an archived card."""
        (card,) = self._seed(db_conn, "a.ai")
        svc.set_status(db_conn, card, "saved", "x", expected_from="new")  # Save
        svc.set_status(db_conn, card, "archived", "x", expected_from="saved")  # Archive elsewhere
        before = _card(db_conn, card)
        with pytest.raises(svc.Conflict, match="^card is archived, not saved; reload and try again$"):
            svc.set_status(db_conn, card, "new", "stale@x.com", expected_from="saved")  # the stale Unsave
        after = _card(db_conn, card)
        assert after["status"] == "archived" and after["updated_at"] == before["updated_at"]
        row = svc.set_status(db_conn, card, "new", "x", expected_from="archived")  # Restore
        assert row["status"] == "new" and row["archived_at"] is None
        # A ``from`` the target cannot be reached from is refused like any wrong move.
        svc.set_status(db_conn, card, "archived", "x", expected_from="new")
        with pytest.raises(svc.Conflict, match="^card is archived; only a new card can move to saved$"):
            svc.set_status(db_conn, card, "saved", "x", expected_from="archived")
        with pytest.raises(svc.Conflict, match="^card is already archived$"):
            svc.set_status(db_conn, card, "archived", "x", expected_from="archived")
        with pytest.raises(svc.NotFound):
            svc.set_status(db_conn, 999_999, "saved", "x", expected_from="new")

    def test_wrong_state_transitions_conflict(self, db_conn) -> None:
        (card,) = self._seed(db_conn, "a.ai")
        with pytest.raises(svc.Conflict):
            svc.set_status(db_conn, card, "new", "x")  # restore a card that is new
        with pytest.raises(svc.Conflict):
            svc.delete_card(db_conn, card, "x")  # delete before archive
        svc.set_status(db_conn, card, "archived", "x")
        with pytest.raises(svc.Conflict):
            svc.set_status(db_conn, card, "archived", "x")

    @pytest.mark.parametrize(
        ("path", "target", "message"),
        [
            ((), "new", "card is already new"),
            (("saved",), "saved", "card is already saved"),
            (("archived",), "archived", "card is already archived"),
            (("archived",), "saved", "card is archived; only a new card can move to saved"),
            (("saved", "archived"), "saved", "card is archived; only a new card can move to saved"),
        ],
    )
    def test_refused_transitions_are_conflicts_and_change_nothing(
        self, db_conn, path: tuple[str, ...], target: str, message: str
    ) -> None:
        (card,) = self._seed(db_conn, "a.ai")
        for step in path:
            svc.set_status(db_conn, card, step, "first@x.com")
        before = _card(db_conn, card)
        with pytest.raises(svc.Conflict, match=f"^{message}$"):
            svc.set_status(db_conn, card, target, "second@x.com")
        after = _card(db_conn, card)
        assert after["status"] == before["status"]
        assert after["updated_by"] == before["updated_by"]
        assert after["updated_at"] == before["updated_at"]

    @pytest.mark.parametrize(
        ("path", "target", "raced_to"),
        [
            (("archived",), "saved", "new"),  # Save missed, then a Restore landed
            ((), "new", "saved"),  # Unsave of a new card missed, then a Save landed
            ((), "new", "archived"),  # Restore of a new card missed, then an Archive landed
            (("archived",), "archived", "new"),  # Archive missed, then a Restore landed
        ],
    )
    def test_a_status_that_moved_after_the_missed_update_gets_a_generic_409(
        self, db_conn, monkeypatch, path: tuple[str, ...], target: str, raced_to: str
    ) -> None:
        """Another request commits between the guarded UPDATE and the follow-up
        read, leaving the card in a status the move IS allowed from. Naming it
        would contradict the refusal ("card is new; only a new card can move
        to saved"), so that case gets the generic message."""
        (card,) = self._seed(db_conn, "a.ai")
        for step in path:
            svc.set_status(db_conn, card, step, "x")
        real = svc._status_after_missed_update

        def raced(conn: Any, cur: Any, card_id: int) -> str:
            real(conn, cur, card_id)  # the real read (and its rollback)...
            return raced_to  # ...but the card moved in between

        monkeypatch.setattr(svc, "_status_after_missed_update", raced)
        with pytest.raises(
            svc.Conflict, match="^card changed while this request ran; reload and try again$"
        ):
            svc.set_status(db_conn, card, target, "y")
        assert _card(db_conn, card)["updated_by"] != "y"  # nothing was written

    def test_a_delete_that_raced_a_concurrent_archive_gets_a_generic_409(
        self, db_conn, monkeypatch
    ) -> None:
        (card,) = self._seed(db_conn, "a.ai")  # new: the delete's UPDATE misses
        monkeypatch.setattr(svc, "_status_after_missed_update", lambda *_: "archived")
        with pytest.raises(
            svc.Conflict, match="^card changed while this request ran; reload and try again$"
        ):
            svc.delete_card(db_conn, card, "x")
        assert _card(db_conn, card)["status"] == "new"

    def test_a_saved_card_cannot_be_deleted(self, db_conn) -> None:
        (card,) = self._seed(db_conn, "a.ai")
        svc.set_status(db_conn, card, "saved", "x")
        with pytest.raises(svc.Conflict, match="archive it before deleting"):
            svc.delete_card(db_conn, card, "x")
        assert _card(db_conn, card)["status"] == "saved"

    def test_delete_tombstones_and_hides(self, db_conn) -> None:
        _insert_company(db_conn, "raindrop", "ashby", "raindrop")
        (card,) = self._seed(db_conn, "raindrop.ai")
        assert _card(db_conn, card)["tracked_company_id"] == "raindrop"
        svc.set_status(db_conn, card, "archived", "x")
        svc.delete_card(db_conn, card, "admin@x.com")
        row = _card(db_conn, card)
        assert row["status"] == "deleted"
        assert row["payload"] is None
        assert row["tracked_company_id"] is None and row["pr_url"] is None
        assert row["archived_at"] is None and row["deleted_at"] is not None
        assert row["domain"] == "raindrop.ai"  # the dedupe key survives
        assert svc.list_cards(db_conn, "archived", 25, 0) == ([], 0)
        assert svc.card_counts(db_conn) == {"new": 0, "saved": 0, "archived": 0}

    def test_deleted_and_missing_cards_are_not_found(self, db_conn) -> None:
        (card,) = self._seed(db_conn, "a.ai")
        svc.set_status(db_conn, card, "archived", "x")
        svc.delete_card(db_conn, card, "x")
        for fn in (
            lambda: svc.set_status(db_conn, card, "new", "x"),
            lambda: svc.set_status(db_conn, card, "saved", "x"),
            lambda: svc.set_status(db_conn, card, "archived", "x"),
            lambda: svc.set_status(db_conn, 999_999, "saved", "x"),
            lambda: svc.delete_card(db_conn, card, "x"),
            lambda: svc.delete_card(db_conn, 999_999, "x"),
            lambda: svc.set_status(db_conn, 999_999, "archived", "x"),
        ):
            with pytest.raises(svc.NotFound):
                fn()

    def test_status_check_constraint_allows_saved_only_among_new_values(self, db_conn) -> None:
        (card,) = self._seed(db_conn, "a.ai")
        with db_conn.cursor() as cur:
            cur.execute("UPDATE launch_radar_cards SET status = 'saved' WHERE id = %s", (card,))
        db_conn.commit()
        with db_conn.cursor() as cur:
            with pytest.raises(psycopg2.errors.CheckViolation):
                cur.execute(
                    "UPDATE launch_radar_cards SET status = 'starred' WHERE id = %s", (card,)
                )
        db_conn.rollback()

    def test_tombstone_check_constraint_holds(self, db_conn) -> None:
        (card,) = self._seed(db_conn, "a.ai")
        with db_conn.cursor() as cur:
            with pytest.raises(psycopg2.errors.CheckViolation):
                cur.execute(
                    "UPDATE launch_radar_cards SET status = 'deleted' WHERE id = %s", (card,)
                )
        db_conn.rollback()


# ---------------------------------------------------------------------------
# PR requests: the §2.1 hooks on each card move (saved-pr/PLAN.md)
# ---------------------------------------------------------------------------

_PR = "https://github.com/brendanpotter00/Job-Visualizer-Notifier/pull/{n}"

# The request states a test can start from; ``None`` = no row.
_PR_STATES = (None, "queued", "in_progress", "open", "failed", "no_board", "already_tracked", "cancelled")


def _pr_row(conn: Any, card_id: int) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM launch_radar_pr_requests WHERE card_id = %s", (card_id,))
        row = cur.fetchone()
    conn.rollback()
    return dict(row) if row else None


def _force_pr(conn: Any, card_id: int, state: str | None) -> None:
    """Put the card's request in ``state`` directly (no row for None), with an
    old ``requested_at``, a pending ``retry_after`` and some attempts, so a hook
    that touches the row is visible."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM launch_radar_pr_requests WHERE card_id = %s", (card_id,))
        if state is not None:
            is_open = state == "open"
            finished = state in ("open", "failed", "no_board", "already_tracked", "cancelled")
            cur.execute(
                "INSERT INTO launch_radar_pr_requests (card_id, status, attempts, pr_url, "
                "pr_number, last_reason, requested_at, retry_after, claimed_at, finished_at) "
                "VALUES (%s, %s, 2, %s, %s, %s, now() - interval '3 days', "
                "now() + interval '1 hour', %s, %s)",
                (
                    card_id,
                    state,
                    _PR.format(n=500 + card_id) if is_open else None,
                    500 + card_id if is_open else None,
                    "step_refused" if state == "failed" else None,
                    datetime(2026, 10, 1, tzinfo=timezone.utc) if state != "queued" else None,
                    datetime(2026, 10, 2, tzinfo=timezone.utc) if finished else None,
                ),
            )
    conn.commit()


class TestPrRequestHooks:
    """Every cell of PLAN §2.1: what Save / Unsave / Archive / Restore / Delete do
    to the card's PR request, in the same transaction as the move."""

    # (event, the card status the event starts from, the move)
    _EVENTS = {
        "save": ("new", "saved"),
        "unsave": ("saved", "new"),
        "archive_new": ("new", "archived"),
        "archive_saved": ("saved", "archived"),
        "restore": ("archived", "new"),
    }

    def _card_in(self, db_conn: Any, status: str, domain: str = "a.ai") -> int:
        start_test_run(db_conn)
        card = svc.insert_card(db_conn, "run-0001", stored_payload(domain=domain))["id"]
        if status != "new":
            svc.set_status(db_conn, card, status, "setup")  # type: ignore[arg-type]
        return int(card)

    @pytest.mark.parametrize("event", list(_EVENTS))
    @pytest.mark.parametrize("state", _PR_STATES)
    def test_the_matrix(self, db_conn, event: str, state: str | None) -> None:
        source, target = self._EVENTS[event]
        card = self._card_in(db_conn, source)
        _force_pr(db_conn, card, state)
        before = _pr_row(db_conn, card)

        svc.set_status(db_conn, card, target, "admin@x.com")  # type: ignore[arg-type]
        after = _pr_row(db_conn, card)

        if event == "save" and state is None:
            # A fresh row: queued now, no attempts.
            assert after is not None and after["status"] == "queued"
            assert after["attempts"] == 0 and after["pr_url"] is None
            assert after["retry_after"] is None and after["finished_at"] is None
        elif event == "save" and state == "cancelled":
            # Re-queued: fresh requested_at, no pending retry, not finished. The
            # attempt count and history are kept.
            assert before is not None and after is not None
            assert after["status"] == "queued"
            assert after["requested_at"] > before["requested_at"]
            assert after["retry_after"] is None and after["finished_at"] is None
            assert after["updated_at"] > before["updated_at"]
            assert after["attempts"] == before["attempts"]
        elif event in ("unsave", "archive_new", "archive_saved") and state == "queued":
            assert before is not None and after is not None
            assert after["status"] == "cancelled" and after["finished_at"] is not None
            assert after["updated_at"] > before["updated_at"]
            assert after["requested_at"] == before["requested_at"]
            assert after["attempts"] == before["attempts"]
        else:
            # Every other cell: the row (or its absence) is untouched. Re-saving a
            # failed / no_board / already_tracked card is NOT a retry (D7).
            assert after == before

    @pytest.mark.parametrize("state", _PR_STATES)
    def test_delete_removes_the_row_in_every_state(self, db_conn, state: str | None) -> None:
        card = self._card_in(db_conn, "archived")
        _force_pr(db_conn, card, state)
        svc.delete_card(db_conn, card, "admin@x.com")
        assert _pr_row(db_conn, card) is None
        assert _card(db_conn, card)["status"] == "deleted"  # the card row stays

    def test_save_unsave_save_round_trip(self, db_conn) -> None:
        card = self._card_in(db_conn, "new")
        svc.set_status(db_conn, card, "saved", "x")
        first = _pr_row(db_conn, card)
        assert first is not None and first["status"] == "queued"
        svc.set_status(db_conn, card, "new", "x")
        assert (_pr_row(db_conn, card) or {})["status"] == "cancelled"
        svc.set_status(db_conn, card, "saved", "x")
        again = _pr_row(db_conn, card)
        assert again is not None and again["status"] == "queued" and again["id"] == first["id"]
        assert again["finished_at"] is None and again["requested_at"] >= first["requested_at"]

    def test_archive_then_restore_then_save_requeues(self, db_conn) -> None:
        card = self._card_in(db_conn, "saved")
        svc.set_status(db_conn, card, "archived", "x")
        assert (_pr_row(db_conn, card) or {})["status"] == "cancelled"
        svc.set_status(db_conn, card, "new", "x")  # Restore: nothing
        assert (_pr_row(db_conn, card) or {})["status"] == "cancelled"
        svc.set_status(db_conn, card, "saved", "x")
        assert (_pr_row(db_conn, card) or {})["status"] == "queued"

    def test_a_refused_move_leaves_the_request_alone(self, db_conn) -> None:
        card = self._card_in(db_conn, "saved")
        before = _pr_row(db_conn, card)
        with pytest.raises(svc.Conflict):
            svc.set_status(db_conn, card, "saved", "x")  # already saved
        with pytest.raises(svc.Conflict):
            svc.set_status(db_conn, card, "new", "x", expected_from="archived")  # stale view
        with pytest.raises(svc.Conflict):
            svc.delete_card(db_conn, card, "x")  # saved: archive first
        assert _pr_row(db_conn, card) == before

    def test_set_status_returns_the_open_pr_only(self, db_conn) -> None:
        card = self._card_in(db_conn, "new")
        row = svc.set_status(db_conn, card, "saved", "x")
        assert row["open_pr_url"] is None and row["open_pr_number"] is None
        _force_pr(db_conn, card, "open")
        row = svc.set_status(db_conn, card, "new", "x")  # Unsave keeps an open PR
        assert row["open_pr_url"] == _PR.format(n=500 + card)
        assert row["open_pr_number"] == 500 + card
        row = svc.set_status(db_conn, card, "archived", "x")  # D6: any tab
        assert row["open_pr_url"] == _PR.format(n=500 + card)

    def test_list_cards_joins_only_an_open_request(self, db_conn) -> None:
        start_test_run(db_conn)
        ids = {
            state: svc.insert_card(db_conn, "run-0001", stored_payload(domain=f"{state}.ai"))["id"]
            for state in ("open", "failed", "queued", "none", "legacy")
        }
        for state, card in ids.items():
            svc.set_status(db_conn, card, "saved", "x")
            _force_pr(db_conn, card, None if state in ("none", "legacy") else state)
        with db_conn.cursor() as cur:  # the legacy column never feeds the link
            cur.execute(
                "UPDATE launch_radar_cards SET pr_url = %s WHERE id = %s",
                (_PR.format(n=333), ids["legacy"]),
            )
        db_conn.commit()
        rows, total = svc.list_cards(db_conn, "saved", 25, 0)
        assert total == 5 and len(rows) == 5
        by_id = {r["id"]: r for r in rows}
        assert by_id[ids["open"]]["open_pr_url"] == _PR.format(n=500 + ids["open"])
        assert by_id[ids["open"]]["open_pr_number"] == 500 + ids["open"]
        for state in ("failed", "queued", "none", "legacy"):
            assert by_id[ids[state]]["open_pr_url"] is None
            assert by_id[ids[state]]["open_pr_number"] is None
        # The join does not disturb any sort or the paging.
        for sort in ("announced", "talent", "vc", "added"):
            page, n = svc.list_cards(db_conn, "saved", 2, 1, sort)  # type: ignore[arg-type]
            assert n == 5 and len(page) == 2

    def test_the_card_fk_cascades(self, db_conn) -> None:
        """Nothing here deletes a card row, but the FK is ON DELETE CASCADE, so a
        hand-run DELETE could never leave an orphan request behind."""
        card = self._card_in(db_conn, "saved")
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM launch_radar_cards WHERE id = %s", (card,))
        db_conn.commit()
        assert _pr_row(db_conn, card) is None


# ---------------------------------------------------------------------------
# The loop's PR queue: claim, report, requeue, list (PLAN §2.2, §3.1)
# ---------------------------------------------------------------------------


def saved_card(conn: Any, domain: str = "a.ai", **payload: Any) -> int:
    """A saved card (so a ``queued`` request) posted by the test run."""
    start_test_run(conn)
    card = svc.insert_card(conn, "run-0001", stored_payload(domain=domain, **payload))["id"]
    svc.set_status(conn, card, "saved", "admin@x.com")
    return int(card)


def _set_pr(conn: Any, card_id: int, sql_assignments: str) -> None:
    """Test-only: a fixed SET clause on the card's request."""
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE launch_radar_pr_requests SET {sql_assignments} WHERE card_id = %s",
            (card_id,),
        )
    conn.commit()


def _seconds_until_retry(conn: Any, card_id: int) -> float:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXTRACT(EPOCH FROM retry_after - now()) AS s "
            "FROM launch_radar_pr_requests WHERE card_id = %s",
            (card_id,),
        )
        row = cur.fetchone()
    conn.rollback()
    return float(row["s"])


def _claimed(conn: Any, domain: str = "a.ai") -> int:
    """A saved card whose request this test has just claimed (``in_progress``)."""
    card = saved_card(conn, domain)
    claim = svc.claim_next_pr(conn)
    assert claim is not None and claim["card_id"] == card
    return card


_TWELVE_HOURS = 12 * 3600


class TestPrClaim:
    def test_nothing_queued_is_none(self, db_conn) -> None:
        assert svc.claim_next_pr(db_conn) is None

    def test_claim_is_fifo_and_marks_the_row(self, db_conn) -> None:
        first = saved_card(db_conn, "a.ai")
        second = saved_card(db_conn, "b.ai")
        third = saved_card(db_conn, "c.ai")
        # Same requested_at for two of them: the id breaks the tie.
        _set_pr(db_conn, second, "requested_at = now() - interval '2 days'")
        _set_pr(db_conn, third, "requested_at = now() - interval '2 days'")
        order = []
        for _ in range(3):
            claim = svc.claim_next_pr(db_conn)
            assert claim is not None
            order.append(claim["card_id"])
        assert order == [second, third, first]
        assert svc.claim_next_pr(db_conn) is None
        row = _pr_row(db_conn, first)
        assert row is not None and row["status"] == "in_progress"
        assert row["attempts"] == 1 and row["claimed_at"] is not None
        assert row["finished_at"] is None

    def test_the_claim_carries_the_payload_fields_only(self, db_conn) -> None:
        card = saved_card(db_conn, "raindrop.ai")
        claim = svc.claim_next_pr(db_conn)
        assert claim is not None
        requested_at = claim.pop("requested_at")
        assert isinstance(requested_at, datetime)
        assert claim == {
            "card_id": card,
            "domain": "raindrop.ai",
            "company": "Raindrop AI",
            "website": "https://www.raindrop.ai",
            "careers_url": "https://jobs.ashbyhq.com/Raindrop",
            "one_liner": "Monitoring for AI agents",
            "what_they_do": "Observability for agent products.",
            "ats": {
                "provider": "ashby",
                "board_token": "Raindrop",
                "board_url": "https://jobs.ashbyhq.com/Raindrop",
                "verified": True,
                "job_count": 9,
            },
            "latest_round": {
                "round": "Series A",
                "amount_usd": "$35M",
                "announced_at": "2026-09-17",
            },
            "attempts": 1,
        }

    def test_a_bad_stored_url_is_nulled_and_no_round_is_null(self, db_conn) -> None:
        card = saved_card(
            db_conn,
            "b.ai",
            funding={"latest_round": None, "prior_rounds": []},
        )
        with db_conn.cursor() as cur:  # a row stored before the URL rule
            cur.execute(
                "UPDATE launch_radar_cards SET payload = jsonb_set(payload, '{careers_url}', "
                "'\"javascript:alert(1)\"') WHERE id = %s",
                (card,),
            )
        db_conn.commit()
        claim = svc.claim_next_pr(db_conn)
        assert claim is not None
        assert claim["careers_url"] is None and claim["latest_round"] is None

    def test_a_pending_retry_waits(self, db_conn) -> None:
        card = saved_card(db_conn)
        _set_pr(db_conn, card, "retry_after = now() + interval '1 hour'")
        assert svc.claim_next_pr(db_conn) is None
        _set_pr(db_conn, card, "retry_after = now() - interval '1 second'")
        claim = svc.claim_next_pr(db_conn)
        assert claim is not None and claim["card_id"] == card

    def test_a_stale_claim_is_requeued_as_abandoned_and_claimable(self, db_conn) -> None:
        card = _claimed(db_conn)
        _set_pr(db_conn, card, "claimed_at = now() - interval '3 hours'")
        claim = svc.claim_next_pr(db_conn)
        assert claim is not None and claim["card_id"] == card
        assert claim["attempts"] == 2  # the killed run counted as an attempt
        row = _pr_row(db_conn, card)
        assert row is not None and row["status"] == "in_progress"
        assert row["last_reason"] == "abandoned"

    def test_a_stale_claim_on_its_last_attempt_fails(self, db_conn) -> None:
        card = _claimed(db_conn)
        _set_pr(db_conn, card, "attempts = 3, claimed_at = now() - interval '3 hours'")
        assert svc.claim_next_pr(db_conn) is None
        row = _pr_row(db_conn, card)
        assert row is not None and row["status"] == "failed"
        assert row["last_reason"] == "abandoned" and row["finished_at"] is not None

    def test_a_fresh_claim_is_left_alone(self, db_conn) -> None:
        card = _claimed(db_conn)
        _set_pr(db_conn, card, "claimed_at = now() - interval '90 minutes'")
        before = _pr_row(db_conn, card)
        assert svc.claim_next_pr(db_conn) is None
        assert _pr_row(db_conn, card) == before

    def test_a_tracked_card_becomes_already_tracked(self, db_conn) -> None:
        _insert_company(db_conn, "raindrop", "ashby", "raindrop")
        tracked = saved_card(db_conn, "raindrop.ai")  # resolved at insert
        assert _card(db_conn, tracked)["tracked_company_id"] == "raindrop"
        other = saved_card(db_conn, "b.ai", ats={**make_payload()["ats"], "board_token": "bee"})
        claim = svc.claim_next_pr(db_conn)
        assert claim is not None and claim["card_id"] == other
        row = _pr_row(db_conn, tracked)
        assert row is not None and row["status"] == "already_tracked"
        assert row["finished_at"] is not None and row["attempts"] == 0

    def test_a_queued_row_of_an_unsaved_card_is_cancelled(self, db_conn) -> None:
        card = saved_card(db_conn)
        with db_conn.cursor() as cur:  # behind the hooks' back
            cur.execute("UPDATE launch_radar_cards SET status = 'new' WHERE id = %s", (card,))
        db_conn.commit()
        assert svc.claim_next_pr(db_conn) is None
        row = _pr_row(db_conn, card)
        assert row is not None and row["status"] == "cancelled" and row["attempts"] == 0

    def test_a_locked_row_is_skipped(self, db_conn) -> None:
        first = saved_card(db_conn, "a.ai")
        second = saved_card(db_conn, "b.ai")
        schema = os.environ["PYTEST_SCHEMA"]
        other = psycopg2.connect(TEST_DB_URL, cursor_factory=RealDictCursor)
        try:
            with other.cursor() as cur:
                cur.execute(f'SET search_path TO "{schema}", public')
                cur.execute(
                    "SELECT id FROM launch_radar_pr_requests WHERE card_id = %s FOR UPDATE",
                    (first,),
                )
            claim = svc.claim_next_pr(db_conn)  # does not wait for the lock
            assert claim is not None and claim["card_id"] == second
        finally:
            other.rollback()
            other.close()

    def test_two_concurrent_claims_get_two_cards(self, db_conn) -> None:
        cards = {saved_card(db_conn, "a.ai"), saved_card(db_conn, "b.ai")}
        schema = os.environ["PYTEST_SCHEMA"]
        barrier = threading.Barrier(2)
        got: list[int | None] = []

        def _worker() -> None:
            conn = psycopg2.connect(TEST_DB_URL, cursor_factory=RealDictCursor)
            try:
                with conn.cursor() as cur:
                    cur.execute(f'SET search_path TO "{schema}", public')
                conn.commit()
                barrier.wait()
                claim = svc.claim_next_pr(conn)
                got.append(claim["card_id"] if claim else None)
            finally:
                conn.close()

        threads = [threading.Thread(target=_worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert sorted(c for c in got if c is not None) == sorted(cards)


class TestPrReport:
    def test_open_records_the_pr(self, db_conn) -> None:
        card = _claimed(db_conn)
        row = svc.report_pr(db_conn, card, "open", _PR.format(n=412), None)
        assert row["status"] == "open" and row["pr_url"] == _PR.format(n=412)
        assert row["pr_number"] == 412 and row["finished_at"] is not None
        assert row["last_reason"] is None and row["attempts"] == 1
        assert _pr_row(db_conn, card) is not None
        cards, _ = svc.list_cards(db_conn, "saved", 25, 0)
        assert cards[0]["open_pr_url"] == _PR.format(n=412)

    def test_a_repeated_open_is_a_no_op_and_another_url_conflicts(self, db_conn) -> None:
        card = _claimed(db_conn)
        first = svc.report_pr(db_conn, card, "open", _PR.format(n=7), None)
        again = svc.report_pr(db_conn, card, "open", _PR.format(n=7), None)
        assert again == first
        with pytest.raises(svc.Conflict, match="different PR"):
            svc.report_pr(db_conn, card, "open", _PR.format(n=8), None)
        assert _pr_row(db_conn, card)["pr_number"] == 7  # type: ignore[index]

    def test_the_same_pr_on_two_cards_conflicts(self, db_conn) -> None:
        a = _claimed(db_conn, "a.ai")
        svc.report_pr(db_conn, a, "open", _PR.format(n=9), None)
        b = _claimed(db_conn, "b.ai")
        with pytest.raises(svc.Conflict, match="another card"):
            svc.report_pr(db_conn, b, "open", _PR.format(n=9), None)
        assert (_pr_row(db_conn, b) or {})["status"] == "in_progress"

    @pytest.mark.parametrize("reason", ["step_refused", "multi_head", "git_error", "gh_error",
                                        "timeout", "other"])
    def test_a_retryable_failure_requeues_for_12_hours(self, db_conn, reason: str) -> None:
        card = _claimed(db_conn)
        row = svc.report_pr(db_conn, card, "failed", None, reason)  # type: ignore[arg-type]
        assert row["status"] == "queued" and row["last_reason"] == reason
        assert row["attempts"] == 1 and row["finished_at"] is None
        assert _TWELVE_HOURS - 120 < _seconds_until_retry(db_conn, card) <= _TWELVE_HOURS
        assert svc.claim_next_pr(db_conn) is None  # waits for retry_after

    def test_the_third_retryable_failure_is_final(self, db_conn) -> None:
        card = _claimed(db_conn)
        for attempt in (1, 2, 3):
            if attempt > 1:
                _set_pr(db_conn, card, "retry_after = NULL")
                claim = svc.claim_next_pr(db_conn)
                assert claim is not None and claim["attempts"] == attempt
            row = svc.report_pr(db_conn, card, "failed", None, "git_error")
        assert row["status"] == "failed" and row["attempts"] == 3
        assert row["retry_after"] is None and row["finished_at"] is not None
        _set_pr(db_conn, card, "retry_after = NULL")
        assert svc.claim_next_pr(db_conn) is None

    @pytest.mark.parametrize("reason", ["unsafe_value", "pr_closed"])
    def test_a_terminal_failure_is_final_at_once(self, db_conn, reason: str) -> None:
        card = _claimed(db_conn)
        row = svc.report_pr(db_conn, card, "failed", None, reason)  # type: ignore[arg-type]
        assert row["status"] == "failed" and row["last_reason"] == reason
        assert row["attempts"] == 1 and row["finished_at"] is not None

    def test_env_error_gives_the_attempt_back_and_requeues(self, db_conn) -> None:
        card = _claimed(db_conn)
        row = svc.report_pr(db_conn, card, "failed", None, "env_error")
        assert row["status"] == "queued" and row["attempts"] == 0
        assert row["last_reason"] == "env_error" and row["finished_at"] is None
        assert _TWELVE_HOURS - 120 < _seconds_until_retry(db_conn, card) <= _TWELVE_HOURS

    def test_env_error_on_the_last_attempt_still_requeues(self, db_conn) -> None:
        card = _claimed(db_conn)
        _set_pr(db_conn, card, "attempts = 3")
        row = svc.report_pr(db_conn, card, "failed", None, "env_error")
        assert row["status"] == "queued" and row["attempts"] == 2

    def test_env_error_never_goes_below_zero(self, db_conn) -> None:
        card = _claimed(db_conn)
        _set_pr(db_conn, card, "attempts = 0")
        row = svc.report_pr(db_conn, card, "failed", None, "env_error")
        assert row["attempts"] == 0

    @pytest.mark.parametrize("reason", ["board_not_found", "board_empty", "unsupported_ats"])
    def test_no_board_is_final(self, db_conn, reason: str) -> None:
        card = _claimed(db_conn)
        row = svc.report_pr(db_conn, card, "no_board", None, reason)  # type: ignore[arg-type]
        assert row["status"] == "no_board" and row["last_reason"] == reason
        assert row["finished_at"] is not None and row["pr_url"] is None

    def test_already_tracked_is_final(self, db_conn) -> None:
        card = _claimed(db_conn)
        row = svc.report_pr(db_conn, card, "already_tracked", None, None)
        assert row["status"] == "already_tracked" and row["finished_at"] is not None

    def test_cancelled_only_for_an_unsaved_card(self, db_conn) -> None:
        card = _claimed(db_conn)
        with pytest.raises(svc.Conflict, match="still saved"):
            svc.report_pr(db_conn, card, "cancelled", None, None)
        assert (_pr_row(db_conn, card) or {})["status"] == "in_progress"
        svc.set_status(db_conn, card, "new", "admin@x.com")  # Unsave mid-run
        assert (_pr_row(db_conn, card) or {})["status"] == "in_progress"
        row = svc.report_pr(db_conn, card, "cancelled", None, None)
        assert row["status"] == "cancelled" and row["finished_at"] is not None

    def test_an_open_report_after_an_unsave_is_still_recorded(self, db_conn) -> None:
        card = _claimed(db_conn)
        svc.set_status(db_conn, card, "archived", "admin@x.com")
        row = svc.report_pr(db_conn, card, "open", _PR.format(n=31), None)
        assert row["status"] == "open"

    @pytest.mark.parametrize(
        "state", ["queued", "open", "failed", "no_board", "already_tracked", "cancelled"]
    )
    def test_only_an_in_progress_row_takes_a_report(self, db_conn, state: str) -> None:
        card = saved_card(db_conn)
        _force_pr(db_conn, card, state)
        before = _pr_row(db_conn, card)
        with pytest.raises(svc.Conflict, match="not in_progress"):
            svc.report_pr(db_conn, card, "failed", None, "other")
        assert _pr_row(db_conn, card) == before

    def test_missing_request_or_deleted_card_is_not_found(self, db_conn) -> None:
        with pytest.raises(svc.NotFound):
            svc.report_pr(db_conn, 999, "already_tracked", None, None)
        card = _claimed(db_conn)
        svc.set_status(db_conn, card, "archived", "x")
        svc.delete_card(db_conn, card, "x")
        with pytest.raises(svc.NotFound):
            svc.report_pr(db_conn, card, "open", _PR.format(n=5), None)

    def test_a_malformed_report_is_refused_before_any_write(self, db_conn) -> None:
        card = _claimed(db_conn)
        before = _pr_row(db_conn, card)
        for outcome, url, reason in (
            ("open", None, None),
            ("open", "https://github.com/evil/repo/pull/1", None),
            ("failed", None, None),
            ("failed", None, "board_empty"),
            ("no_board", None, "git_error"),
            ("failed", None, "abandoned"),
        ):
            with pytest.raises(ValueError):
                svc.report_pr(db_conn, card, outcome, url, reason)  # type: ignore[arg-type]
        assert _pr_row(db_conn, card) == before


class TestPrRequeueGetList:
    @pytest.mark.parametrize("state", ["failed", "no_board", "already_tracked", "cancelled"])
    def test_requeue_resets_a_finished_request(self, db_conn, state: str) -> None:
        card = saved_card(db_conn)
        _force_pr(db_conn, card, state)
        before = _pr_row(db_conn, card)
        row = svc.requeue_pr(db_conn, card)
        assert row["status"] == "queued" and row["attempts"] == 0
        assert row["retry_after"] is None and row["last_reason"] is None
        assert row["finished_at"] is None
        assert before is not None and row["requested_at"] > before["requested_at"]
        claim = svc.claim_next_pr(db_conn)
        assert claim is not None and claim["card_id"] == card and claim["attempts"] == 1

    @pytest.mark.parametrize("state", ["queued", "in_progress", "open"])
    def test_requeue_refuses_a_live_request(self, db_conn, state: str) -> None:
        card = saved_card(db_conn)
        _force_pr(db_conn, card, state)
        before = _pr_row(db_conn, card)
        with pytest.raises(svc.Conflict, match=state):
            svc.requeue_pr(db_conn, card)
        assert _pr_row(db_conn, card) == before

    @pytest.mark.parametrize("card_status", ["new", "archived"])
    def test_requeue_refuses_an_unsaved_card(self, db_conn, card_status: str) -> None:
        card = saved_card(db_conn)
        _force_pr(db_conn, card, "failed")
        svc.set_status(db_conn, card, card_status, "x")  # type: ignore[arg-type]
        with pytest.raises(svc.Conflict, match="only a saved card"):
            svc.requeue_pr(db_conn, card)
        assert (_pr_row(db_conn, card) or {})["status"] == "failed"

    def test_requeue_missing_request_or_card_is_not_found(self, db_conn) -> None:
        with pytest.raises(svc.NotFound):
            svc.requeue_pr(db_conn, 999)
        start_test_run(db_conn)
        never_saved = svc.insert_card(db_conn, "run-0001", stored_payload(domain="n.ai"))["id"]
        with pytest.raises(svc.NotFound):
            svc.requeue_pr(db_conn, never_saved)

    def test_get_returns_the_row_and_the_card_status(self, db_conn) -> None:
        card = _claimed(db_conn)
        row = svc.get_pr_request(db_conn, card)
        assert row["status"] == "in_progress" and row["card_status"] == "saved"
        svc.set_status(db_conn, card, "new", "x")
        assert svc.get_pr_request(db_conn, card)["card_status"] == "new"
        with pytest.raises(svc.NotFound):
            svc.get_pr_request(db_conn, 999)
        svc.set_status(db_conn, card, "archived", "x")
        svc.delete_card(db_conn, card, "x")
        with pytest.raises(svc.NotFound):
            svc.get_pr_request(db_conn, card)

    def test_list_filters_orders_oldest_first_and_limits(self, db_conn) -> None:
        a = saved_card(db_conn, "a.ai")
        b = saved_card(db_conn, "b.ai")
        c = saved_card(db_conn, "c.ai")
        _force_pr(db_conn, a, "open")  # requested 3 days ago
        _force_pr(db_conn, c, "failed")  # requested 3 days ago, larger id
        everything = svc.list_pr_requests(db_conn, [], 100)
        assert [r["card_id"] for r in everything] == [a, c, b]
        assert everything[0]["domain"] == "a.ai" and everything[0]["company"] == "Raindrop AI"
        assert everything[0]["pr_number"] == 500 + a
        opened = svc.list_pr_requests(db_conn, ["open"], 100)
        assert [r["card_id"] for r in opened] == [a]
        some = svc.list_pr_requests(db_conn, ["open", "queued", "failed"], 2)
        assert [r["card_id"] for r in some] == [a, c]
        assert svc.list_pr_requests(db_conn, ["no_board"], 100) == []


# ---------------------------------------------------------------------------
# Sorting the admin list (``list_cards(..., sort)``)
# ---------------------------------------------------------------------------


class TestSort:
    """Every sort key, null placement and the tie-breaks: announced date DESC
    NULLS LAST, then posted_at DESC, then id DESC, so paging is deterministic."""

    def _card(
        self,
        db_conn: Any,
        domain: str,
        *,
        announced: str | None = "2026-09-17",
        talent: int | None = 50,
        vc: int | None = 50,
        posted: str = "2026-10-01T00:00:00Z",
        event: bool = True,
    ) -> int:
        base = make_payload(domain=domain)
        payload = stored_payload(
            domain=domain,
            event={**base["event"], "announced_at": announced} if event else None,
            scores={**base["scores"], "talent": talent, "vc": vc},
        )
        card_id = svc.insert_card(db_conn, "run-0001", payload)["id"]
        with db_conn.cursor() as cur:
            cur.execute(
                "UPDATE launch_radar_cards SET posted_at = %s WHERE id = %s", (posted, card_id)
            )
        db_conn.commit()
        return card_id

    def _ids(self, db_conn: Any, sort: str, status: str = "new") -> list[int]:
        rows, _ = svc.list_cards(db_conn, status, 25, 0, sort)  # type: ignore[arg-type]
        return [r["id"] for r in rows]

    def test_announced_is_the_default_newest_first_and_undated_last(self, db_conn) -> None:
        start_test_run(db_conn)
        no_event = self._card(db_conn, "a.ai", event=False, posted="2026-10-05T00:00:00Z")
        undated = self._card(db_conn, "b.ai", announced=None, posted="2026-10-04T00:00:00Z")
        older = self._card(db_conn, "c.ai", announced="2026-09-01")
        newer = self._card(db_conn, "d.ai", announced="2026-09-30")
        expected = [newer, older, no_event, undated]  # the two nulls: newest posted first
        assert self._ids(db_conn, "announced") == expected
        rows, _ = svc.list_cards(db_conn, "new", 25, 0)  # no sort given
        assert [r["id"] for r in rows] == expected

    @pytest.mark.parametrize("key", ["talent", "vc"])
    def test_score_sorts_highest_first_unscored_last_ties_by_announced(
        self, db_conn, key: str
    ) -> None:
        start_test_run(db_conn)
        other = "vc" if key == "talent" else "talent"

        def card(domain: str, score: int | None, **kw: Any) -> int:
            # The other score runs the opposite way, so a wrong column shows.
            opposite = None if score is None else 100 - score
            return self._card(db_conn, domain, **{key: score, other: opposite}, **kw)

        low = card("a.ai", 10)
        unscored = card("b.ai", None, announced="2026-09-30")
        top = card("c.ai", 90)
        tie_older = card("d.ai", 60, announced="2026-09-01")
        tie_newer = card("e.ai", 60, announced="2026-09-20")
        zero = card("f.ai", 0)  # a real 0 is a score, so it sorts above null
        assert self._ids(db_conn, key) == [top, tie_newer, tie_older, low, zero, unscored]

    def test_added_is_newest_posted_first_ties_by_announced_then_id(self, db_conn) -> None:
        start_test_run(db_conn)
        oldest = self._card(db_conn, "a.ai", posted="2026-10-01T00:00:00Z", announced="2026-09-30")
        same_a = self._card(db_conn, "b.ai", posted="2026-10-03T00:00:00Z", announced="2026-09-01")
        same_b = self._card(db_conn, "c.ai", posted="2026-10-03T00:00:00Z", announced="2026-09-10")
        same_c = self._card(db_conn, "d.ai", posted="2026-10-03T00:00:00Z", announced="2026-09-10")
        newest = self._card(db_conn, "e.ai", posted="2026-10-06T00:00:00Z", announced=None)
        # same_b and same_c tie on posted AND announced: id DESC decides.
        assert self._ids(db_conn, "added") == [newest, same_c, same_b, same_a, oldest]

    @pytest.mark.parametrize("key", ["announced", "talent", "vc", "added"])
    def test_full_ties_page_in_one_stable_order(self, db_conn, key: str) -> None:
        """Identical sort values everywhere: id DESC alone orders the page, so
        walking it one row at a time neither repeats nor skips a card."""
        start_test_run(db_conn)
        ids = [self._card(db_conn, f"t{i}.ai") for i in range(5)]
        assert self._ids(db_conn, key) == sorted(ids, reverse=True)
        walked = [
            r["id"]
            for offset in range(5)
            for r in svc.list_cards(db_conn, "new", 1, offset, key)[0]  # type: ignore[arg-type]
        ]
        assert walked == sorted(ids, reverse=True)

    @pytest.mark.parametrize("status", ["saved", "archived"])
    def test_every_tab_takes_the_sort(self, db_conn, status: str) -> None:
        start_test_run(db_conn)
        low = self._card(db_conn, "a.ai", talent=10, announced="2026-09-30")
        high = self._card(db_conn, "b.ai", talent=90, announced="2026-09-01")
        kept_new = self._card(db_conn, "c.ai", talent=99)
        for card_id in (low, high):
            svc.set_status(db_conn, card_id, status, "x")  # type: ignore[arg-type]
        assert self._ids(db_conn, "talent", status) == [high, low]
        assert self._ids(db_conn, "announced", status) == [low, high]
        assert self._ids(db_conn, "talent") == [kept_new]  # the New tab keeps only its own

    def test_every_sort_key_has_a_fixed_order_clause(self) -> None:
        assert set(svc._CARD_ORDER) == {"announced", "talent", "vc", "added"}
        for clause in svc._CARD_ORDER.values():
            assert clause.endswith("id DESC")
            assert "%" not in clause  # nothing is formatted into it at request time


# ---------------------------------------------------------------------------
# Stats, seen, PR step, Monitors
# ---------------------------------------------------------------------------


class TestFindCards:
    def test_status_filter_and_keyset_pages(self, db_conn) -> None:
        start_test_run(db_conn)
        ids = [
            svc.insert_card(db_conn, "run-0001", stored_payload(domain=f"c{i}.ai"))["id"]
            for i in range(5)
        ]
        svc.set_status(db_conn, ids[1], "archived", "x")
        svc.set_status(db_conn, ids[2], "saved", "x")
        svc.set_status(db_conn, ids[4], "archived", "x")
        svc.delete_card(db_conn, ids[4], "x")
        live = [r["id"] for r in svc.find_cards(db_conn, ["c0.ai", "c1.ai", "c2.ai", "c3.ai", "c4.ai"], False, 100)]
        assert live == ids[:4]  # every live status by default; the tombstone never
        assert [r["id"] for r in svc.find_cards(db_conn, [f"c{i}.ai" for i in range(5)], False, 100, [])] == live
        no_archived = svc.find_cards(
            db_conn, [f"c{i}.ai" for i in range(5)], False, 100, ["new", "saved"]
        )
        assert [r["id"] for r in no_archived] == [ids[0], ids[2], ids[3]]
        # Keyset paging: id > after_id, at most limit, by id.
        domains = [f"c{i}.ai" for i in range(5)]
        page1 = svc.find_cards(db_conn, domains, False, 2)
        page2 = svc.find_cards(db_conn, domains, False, 2, after_id=page1[-1]["id"])
        page3 = svc.find_cards(db_conn, domains, False, 2, after_id=page2[-1]["id"])
        assert [r["id"] for r in page1 + page2] == live and page3 == []


class TestStatsSeenPr:
    def test_run_stats(self, db_conn) -> None:
        assert svc.run_stats(db_conn) == {"last_run": None, "spend_usd": 0.0, "cap_usd": 5.0}
        start_test_run(db_conn)
        svc.reserve_spend(db_conn, "run-0001", "a", 0.12345, None, False)
        stats = svc.run_stats(db_conn)
        assert stats["spend_usd"] == 0.1235
        assert stats["last_run"] is not None and stats["last_run"]["status"] == "running"
        assert stats["last_run"]["host"] == "test-host"

    def test_seen_domains_any_status_and_tracked_names(self, db_conn) -> None:
        _insert_company(db_conn, "raindrop-ai", "ashby", "raindrop", name="Raindrop AI")
        _insert_company(db_conn, "secret", "ashby", "secret", visibility="user", name="Secret Co")
        start_test_run(db_conn)
        card = svc.insert_card(db_conn, "run-0001", stored_payload(domain="ghost.ai"))["id"]
        svc.set_status(db_conn, card, "archived", "x")
        svc.delete_card(db_conn, card, "x")
        saved = svc.insert_card(db_conn, "run-0001", stored_payload(domain="kept.ai"))["id"]
        svc.set_status(db_conn, saved, "saved", "x")
        out = svc.seen(
            db_conn,
            ["HTTPS://www.Ghost.AI/about", "kept.ai", "unseen.io", "NA"],
            ["raindrop ai", "Secret Co", "Nobody"],
        )
        assert out == {
            "domains": {
                "ghost.ai": {"card_id": card, "status": "deleted"},
                "kept.ai": {"card_id": saved, "status": "saved"},
            },
            "names": {"raindrop ai": "raindrop-ai"},
        }

    def test_monitor_put_patch_and_reset_cursor_on_new_id(self, db_conn) -> None:
        t0 = datetime(2026, 10, 7, 7, tzinfo=timezone.utc)
        svc.put_monitor(db_conn, "seed", "monitor_a", "q1", "base", "1d", "active", t0)
        row = svc.patch_monitor(db_conn, "seed", {"last_event_id": "mevt_1"})
        assert row["last_event_id"] == "mevt_1"
        # Same monitor re-PUT keeps the cursor...
        row = svc.put_monitor(db_conn, "seed", "monitor_a", "q2", "base", "1d", "active", t0)
        assert row["last_event_id"] == "mevt_1" and row["query"] == "q2"
        # ...a replacement monitor for the slot starts a fresh cursor.
        row = svc.put_monitor(db_conn, "seed", "monitor_b", "q2", "base", "1d", "active", t0)
        assert row["last_event_id"] is None
        with pytest.raises(svc.NotFound):
            svc.patch_monitor(db_conn, "launch", {"status": "cancelled"})
        assert [m["slot"] for m in svc.list_monitors(db_conn)] == ["seed"]
