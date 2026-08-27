"""AC-03 — the ATS path, with an explicit confirm (PLAN.md §5 "AC-03").

Cisco resolves as an EMBEDDED Workday board (tenant_slug=cisco,
career_site_slug=Cisco_Careers), so this covers the embedded-detection branch
of the resolver, not just a bare ATS URL — and Workday is one of the two
`declared_probed` oracle providers, so its harvest can actually VERIFY.
"""

from __future__ import annotations

import boards
import pytest
from conftest import db, poll_until, require_reachable

CISCO_URL = boards.CISCO.url


@pytest.mark.live
def test_ac03_resolve_finds_cisco_as_embedded_workday(http, db_conn):
    require_reachable(boards.CISCO)
    before_user = db.visibility_count(db_conn, "user")

    resp = http.post("/api/companies/resolve", json={"url": CISCO_URL})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["candidate"]["ats"] == "workday", (
        f"expected Cisco to resolve as workday, got {body['candidate']['ats']!r}"
    )
    assert body["candidate"]["boardToken"] == "cisco", (
        f"expected boardToken='cisco', got {body['candidate']['boardToken']!r}"
    )
    assert body["probe"]["ok"] is True, f"probe failed: {body['probe']}"
    assert body["probe"]["jobCount"] > 0, "expected a positive probed job count"

    # Assertion 3: nothing exists in the DB between resolve and the confirm click.
    after_user = db.visibility_count(db_conn, "user")
    assert after_user == before_user, "resolve alone must create no companies row"


@pytest.mark.live
def test_ac03_add_cisco_creates_and_harvests(http, db_conn):
    require_reachable(boards.CISCO)
    resolve = http.post("/api/companies/resolve", json={"url": CISCO_URL})
    assert resolve.status_code == 200, resolve.text

    resp = http.post("/api/users/companies", json={"url": CISCO_URL})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    company_id = body["id"]

    row = db.company_row(db_conn, company_id)
    assert row is not None
    assert row["visibility"] == "user"
    assert row["health_state"] == "unverified", (
        f"expected health_state='unverified' on a freshly-added ATS company, "
        f"got {row['health_state']!r}"
    )

    script = db.company_script_row(db_conn, company_id)
    assert script is not None
    assert script["transport"] == "ats_client"
    assert script["oracle_kind"] == "declared_probed", (
        f"Workday is one of the two declared_probed providers "
        f"(harvest_verification._DECLARED_PROBED_PROVIDERS); got "
        f"oracle_kind={script['oracle_kind']!r}"
    )

    # Assertion 6: the first harvest lands on the RESERVED interactive queue,
    # not the bulk nightly one. Check immediately — before the interactive
    # worker (concurrency=2, dedicated lane) has a chance to drain it.
    n_interactive = db.procrastinate_job_count(
        db_conn,
        queue_name="custom_ats_first_fetch",
        task_name="fetch_custom_company",
        queueing_lock=f"custom:{company_id}",
    )
    assert n_interactive == 1, (
        f"expected exactly one fetch_custom_company job on custom_ats_first_fetch "
        f"(queueing_lock=custom:{company_id}), found {n_interactive}"
    )
    n_bulk = db.procrastinate_job_count(
        db_conn,
        queue_name="custom_ats_fetch",
        task_name="fetch_custom_company",
        queueing_lock=f"custom:{company_id}",
    )
    assert n_bulk == 0, (
        "the add-time first harvest must NOT land on the bulk nightly queue "
        f"(custom_ats_fetch); found {n_bulk}"
    )

    settled = poll_until(
        http,
        company_id,
        lambda r: r.get("lastSuccessAt") is not None,
        timeout_s=180.0,
        what="first harvest completed (lastSuccessAt set)",
    )
    assert settled["openJobCount"] > 0, "expected open_job_count > 0 after the first harvest"
    print(f"AC-03: Cisco harvested {settled['openJobCount']} open jobs (informational)")

    source_id = f"custom:{company_id}"
    total = db.job_listing_count(db_conn, source_id=source_id)
    with_posted_on = _count_with_posted_on(db_conn, source_id)
    assert total > 0
    # PLAN.md §5 claimed "measured 1246/1246" (100%). Measured for real here:
    # 822/1214 (~68%) — confirmed via the backend log that this is NOT a parse
    # failure (zero "unparseable postedOn" warnings for this run), so it is
    # Workday genuinely omitting `postedOn` for a real subset of Cisco's
    # postings, not a bug in workday_client.py's mapping. Asserting 100% would
    # be asserting a live third party's data completeness, which the plan
    # itself warns against for job counts (§6/§13) — the same principle
    # applies here. A `declared_probed` Workday board should still carry SOME
    # posted_on data; a collapse to zero would be a real regression.
    assert with_posted_on > 0, (
        f"expected at least some Cisco jobs to carry posted_on, found 0 of {total}"
    )
    coverage = with_posted_on / total
    print(
        f"AC-03: {with_posted_on} of {total} Cisco jobs carry posted_on "
        f"({coverage:.0%}) — PLAN.md claimed 100%; live board reality is lower, "
        f"see CASES.md non-coverage note."
    )


def _count_with_posted_on(conn, source_id: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM job_listings WHERE source_id = %s AND posted_on IS NOT NULL",
            (source_id,),
        )
        return int(cur.fetchone()["n"])
