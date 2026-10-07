"""Launch Radar service SQL (``api/services/launch_radar.py``) against real Postgres.

Covers the ledger (run budget, global cap, accrued spend past the cap, the
advisory lock under concurrency), run start/finish, the card lifecycle with its
tombstone, the domain dedupe, ``seen``, the PR step and the Monitors.

The ``db_conn`` schema comes from ``create_all``, so the launch_radar_* tables
exist; conftest's ``clean_tables`` does not know about them, so this module's
autouse fixture truncates them before every test. ``make_payload`` and
``start_test_run`` are reused by the router test modules.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
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
    "launch_radar_spend, launch_radar_cards, launch_radar_runs, launch_radar_monitors"
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
            "ex_founders_with_exit": 0,
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
        "pr_ready": True,
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
        # Most recently archived first (c was archived after a).
        assert [r["id"] for r in archived] == [c, a] and archived_total == 2
        assert svc.card_counts(db_conn) == {"new": 1, "archived": 2}

    def test_archive_restore_round_trip(self, db_conn) -> None:
        (card,) = self._seed(db_conn, "a.ai")
        row = svc.set_status(db_conn, card, "archived", "admin@x.com")
        assert row["status"] == "archived" and row["archived_at"] is not None
        assert row["updated_by"] == "admin@x.com"
        row = svc.set_status(db_conn, card, "new", "admin@x.com")
        assert row["status"] == "new" and row["archived_at"] is None

    def test_wrong_state_transitions_conflict(self, db_conn) -> None:
        (card,) = self._seed(db_conn, "a.ai")
        with pytest.raises(svc.Conflict):
            svc.set_status(db_conn, card, "new", "x")  # restore a card that is new
        with pytest.raises(svc.Conflict):
            svc.delete_card(db_conn, card, "x")  # delete before archive
        svc.set_status(db_conn, card, "archived", "x")
        with pytest.raises(svc.Conflict):
            svc.set_status(db_conn, card, "archived", "x")

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
        assert svc.card_counts(db_conn) == {"new": 0, "archived": 0}

    def test_deleted_and_missing_cards_are_not_found(self, db_conn) -> None:
        (card,) = self._seed(db_conn, "a.ai")
        svc.set_status(db_conn, card, "archived", "x")
        svc.delete_card(db_conn, card, "x")
        for fn in (
            lambda: svc.set_status(db_conn, card, "new", "x"),
            lambda: svc.set_status(db_conn, card, "archived", "x"),
            lambda: svc.delete_card(db_conn, card, "x"),
            lambda: svc.delete_card(db_conn, 999_999, "x"),
            lambda: svc.set_status(db_conn, 999_999, "archived", "x"),
        ):
            with pytest.raises(svc.NotFound):
                fn()

    def test_tombstone_check_constraint_holds(self, db_conn) -> None:
        (card,) = self._seed(db_conn, "a.ai")
        with db_conn.cursor() as cur:
            with pytest.raises(psycopg2.errors.CheckViolation):
                cur.execute(
                    "UPDATE launch_radar_cards SET status = 'deleted' WHERE id = %s", (card,)
                )
        db_conn.rollback()


# ---------------------------------------------------------------------------
# Stats, seen, PR step, Monitors
# ---------------------------------------------------------------------------


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
        out = svc.seen(
            db_conn,
            ["HTTPS://www.Ghost.AI/about", "unseen.io", "NA"],
            ["raindrop ai", "Secret Co", "Nobody"],
        )
        assert out == {
            "domains": {"ghost.ai": {"card_id": card, "status": "deleted"}},
            "names": {"raindrop ai": "raindrop-ai"},
        }

    def test_pr_candidates_and_set_pr(self, db_conn) -> None:
        _insert_company(db_conn, "tracked", "ashby", "tracked")
        start_test_run(db_conn)
        ready = svc.insert_card(db_conn, "run-0001", stored_payload(domain="ready.ai"))["id"]
        svc.insert_card(db_conn, "run-0001", stored_payload(domain="notready.ai", pr_ready=False))
        tracked_payload = make_payload(domain="tracked.ai")
        tracked_payload["ats"] = {**tracked_payload["ats"], "board_token": "tracked"}
        tracked = svc.insert_card(
            db_conn,
            "run-0001",
            LaunchRadarPayload.model_validate(tracked_payload).model_dump(mode="json"),
        )["id"]
        cands = svc.pr_candidates(db_conn, 5)
        assert [c["id"] for c in cands] == [ready]
        assert cands[0]["ats_provider"] == "ashby" and cands[0]["job_count"] == 9
        assert cands[0]["board_token"] == "Raindrop" and cands[0]["company"] == "Raindrop AI"

        url = "https://github.com/brendanpotter00/Job-Visualizer-Notifier/pull/400"
        assert svc.set_pr_url(db_conn, ready, url) == (ready, url)
        assert svc.pr_candidates(db_conn, 5) == []
        with pytest.raises(svc.Conflict):
            svc.set_pr_url(db_conn, ready, url)
        with pytest.raises(svc.Conflict):
            svc.set_pr_url(db_conn, tracked, url)
        with pytest.raises(svc.NotFound):
            svc.set_pr_url(db_conn, 999_999, url)

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
