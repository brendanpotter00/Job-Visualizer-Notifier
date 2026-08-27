"""AC-04 / AC-05 — one-time discovery, and boards with no posted date
(PLAN.md §5 "AC-04 / AC-05").

Live, not hermetic (PLAN.md §6): real Chromium, real Haiku, real board. Each
case is a genuine ~30-90s round trip through discovery + the first harvest.
"""

from __future__ import annotations

import boards
import pytest
from conftest import db, find_company, poll_until, require_reachable

EXPECTED_STEP_KEYS = {"open_page", "find_feed", "verify_read", "ready", "first_scan"}
TERMINAL = {"done", "failed"}


def _first_scan_settled(row: dict) -> bool:
    discovery = row.get("discovery") or {}
    steps = discovery.get("steps") or []
    for step in steps:
        if step["key"] == "first_scan" and step["status"] in TERMINAL:
            return True
    return False


def _run_discovery_case(http, db_conn, board: "boards.Board"):
    require_reachable(board)
    resp = http.post("/api/users/companies", json={"url": board.url})
    assert resp.status_code == 202, (
        f"{board.case_id}: expected 202 discovery_pending for {board.url!r}, "
        f"got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert body["status"] == "discovery_pending"
    company_id = body["id"]
    assert body["finalUrl"]

    # Assertion 2: a provisional row exists immediately.
    provisional = find_company(http, company_id)
    assert provisional is not None, f"{board.case_id}: no provisional row immediately after 202"
    assert provisional["healthState"] == "discovering"
    row = db.company_row(db_conn, company_id)
    assert row is not None
    assert row["enabled"] is False, f"{board.case_id}: provisional row must be enabled=false"

    # Assertion 3: exactly one custom_discovery job, correctly locked.
    user_id = db.user_id_for_email(db_conn, "e2e+add-companies@jvn.test")
    expected_lock = f"discover:{user_id}:{body['finalUrl']}"
    n_jobs = db.procrastinate_job_count(
        db_conn, queue_name="custom_discovery", queueing_lock=expected_lock
    )
    assert n_jobs == 1, (
        f"{board.case_id}: expected exactly one custom_discovery job under "
        f"queueing_lock={expected_lock!r}, found {n_jobs}"
    )

    settled = poll_until(
        http, company_id, _first_scan_settled, timeout_s=240.0, what="first_scan settled"
    )

    discovery = settled["discovery"]
    assert discovery["outcome"] == "tracking", (
        f"{board.case_id}: expected discovery.outcome='tracking' for a board on the "
        f"validated six-board list; got {discovery['outcome']!r} "
        f"(steps={discovery.get('steps')})"
    )
    assert settled["healthState"] == "unverified", (
        f"{board.case_id}: expected healthState='unverified' after discovery accepts "
        f"a Phase-1 board (no oracle yet); got {settled['healthState']!r}"
    )

    step_keys = {s["key"] for s in discovery["steps"]}
    assert step_keys == EXPECTED_STEP_KEYS, (
        f"{board.case_id}: expected exactly the five checklist keys "
        f"{EXPECTED_STEP_KEYS}, got {step_keys}"
    )
    for step in discovery["steps"]:
        assert step["status"] in TERMINAL, (
            f"{board.case_id}: step {step['key']!r} did not reach a terminal state "
            f"(status={step['status']!r})"
        )

    script = db.company_script_row(db_conn, company_id)
    assert script is not None
    assert script["transport"] == "http_json", (
        f"{board.case_id}: expected company_scripts.transport='http_json' for a "
        f"discovered board, got {script['transport']!r}"
    )

    assert settled["openJobCount"] > 0, (
        f"{board.case_id}: expected open_job_count > 0 after the first harvest, got 0"
    )
    if board.approx_job_count:
        lo, hi = board.approx_job_count * 0.4, board.approx_job_count * 2.5
        if not (lo <= settled["openJobCount"] <= hi):
            print(
                f"{board.case_id}: DRIFT NOTICE — open_job_count={settled['openJobCount']} "
                f"is outside the loose sanity band [{lo:.0f}, {hi:.0f}] around the last "
                f"measured {board.approx_job_count}. Not a failure — live boards drift "
                "(PLAN.md §6) — reported for visibility."
            )
    print(f"{board.case_id}: harvested {settled['openJobCount']} open jobs (live count, informational)")

    source_id = f"custom:{company_id}"
    total = db.job_listing_count(db_conn, source_id=source_id)
    with_posted_on = _count_with_posted_on(db_conn, source_id)
    with_first_seen = _count_with_first_seen(db_conn, source_id)
    assert with_posted_on == 0, (
        f"{board.case_id}: posted_on must be NULL for every harvested job "
        f"(the board publishes no date field) — found {with_posted_on} of {total} set"
    )
    assert with_first_seen == total, (
        f"{board.case_id}: first_seen_at must be set for every job — "
        f"{with_first_seen} of {total} set"
    )
    return company_id


def _count_with_posted_on(conn, source_id: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM job_listings WHERE source_id = %s AND posted_on IS NOT NULL",
            (source_id,),
        )
        return int(cur.fetchone()["n"])


def _count_with_first_seen(conn, source_id: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM job_listings WHERE source_id = %s AND first_seen_at IS NOT NULL",
            (source_id,),
        )
        return int(cur.fetchone()["n"])


class TestDiscoveryAtlassian:
    @pytest.mark.live
    def test_ac04_atlassian_discovers_and_harvests(self, http, db_conn):
        _run_discovery_case(http, db_conn, boards.ATLASSIAN)


class TestDiscoveryJaneStreet:
    @pytest.mark.live
    def test_ac05_jane_street_discovers_and_harvests_with_no_date_field(self, http, db_conn):
        _run_discovery_case(http, db_conn, boards.JANE_STREET)
