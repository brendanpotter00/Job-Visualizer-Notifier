"""A PUBLISHED recipe board through the shared leaf task — namespace + refusal.

``tasks.fetch_custom_company`` is the ONE harvest leaf for the recipe engine. The
private lane (``claim_custom_companies``) and the published lane
(``enqueue_recipe_fan_out``) both defer it, and everything that decides whether a
job may CLOSE — the structural gate, ``harvest_verification``'s verdict, the
close-eligibility ladder — is the same code for both, deliberately.

What this file pins is the small, load-bearing difference and the guard around it:

* a published board's rows land under ``recipe:<id>``, never ``custom:<id>``;
* a private board is completely unchanged (still ``custom:<id>``);
* the ``visibility`` argument is NOT trusted — the task re-reads the row and
  refuses a run whose declared visibility disagrees, writing nothing and closing
  nothing.

Reuses the seeding/monkeypatch helpers from ``test_fetch_custom_company``.
"""

from __future__ import annotations

import json

import pytest
from psycopg2 import sql

from api.services import custom_companies_service as ccs
from api.tasks.fetch_custom_company import fetch_custom_company
from scripts.shared.constants import RECIPE_ATS, custom, recipe
from scripts.shared.utils import get_iso_timestamp

from api.tests.test_fetch_custom_company import (
    _HTTP_JSON_PAYLOAD,
    _company_row,
    _http_json_script,
    _patch_env,
    _patch_recipe_http,
    _rows,
    _scrape_runs,
    _seed_discovered_company,
)

pytestmark = pytest.mark.asyncio


def _seed_recipe_company(db_conn, company_id: str, *, script: dict) -> None:
    """A PUBLISHED recipe board: ``ats='recipe'``, ``visibility='public'``.

    No ``user_companies`` row and no ``next_run_at`` bookkeeping — it is scheduled
    by the ``*/30`` cron, not by the private claim tick.
    """
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token, enabled, "
            "provider_config, visibility, health_state) "
            "VALUES (%s, %s, %s, %s, TRUE, '{{}}'::jsonb, 'public', 'unverified')"
        ).format(sql.Identifier("companies")),
        (company_id, company_id.title(), RECIPE_ATS,
         "https://careers.acme.example/jobs"),
    )
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (company_id, script, script_version, transport, "
            "oracle_kind) VALUES (%s, %s::jsonb, 1, 'http_json', 'facet_sum')"
        ).format(sql.Identifier("company_scripts")),
        (company_id, json.dumps(script)),
    )
    db_conn.commit()


def _job_source_ids(db_conn, company_id: str) -> set[str]:
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL("SELECT DISTINCT source_id FROM {} WHERE company = %s").format(
            sql.Identifier("job_listings")
        ),
        (company_id,),
    )
    return {r["source_id"] for r in cur.fetchall()}


async def test_a_published_board_writes_the_recipe_namespace_not_the_custom_one(
    db_conn, monkeypatch
) -> None:
    """THE namespace split, end to end.

    ``recipe:<id>`` is not cosmetic. ``routers/internal_enrichment`` partitions the
    enrichment queue on ``source_id LIKE 'custom:%'`` and reserves ~10% of every
    batch for that slice; a published board carrying a ``custom:`` id would silently
    ride the private-board fairness brake. The same prefix is also what
    ``services/database._ORPHANED_CUSTOM_PREDICATE`` treats as "private by
    definition" and what ``list_owned_source_ids`` hands out as an owner-scoped
    read exemption.

    The rest of the harvest is asserted too — verdict, oracle, counts — because
    "reuse the leaf task" is only true if the published lane really does run the
    same gate and reach the same verdict.
    """
    _patch_env(monkeypatch)
    _patch_recipe_http(monkeypatch, _HTTP_JSON_PAYLOAD)
    company_id = "atlassian"
    _seed_recipe_company(db_conn, company_id, script=_http_json_script())

    await fetch_custom_company(company_id=company_id, visibility="public")
    db_conn.rollback()

    assert _job_source_ids(db_conn, company_id) == {recipe(company_id)}
    assert custom(company_id) not in _job_source_ids(db_conn, company_id)

    # The shared tail really ran: same gate, same oracle, same verdict.
    (harvest,) = _rows(db_conn, "company_harvests", company_id)
    assert harvest["verdict"] == "VERIFIED"
    assert harvest["oracle_kind"] == "facet_sum"
    assert harvest["records_harvested"] == 3

    (run,) = _scrape_runs(db_conn, company_id)
    assert run["success"] is True
    assert run["source_id"] == recipe(company_id)
    assert _company_row(db_conn, company_id)["health_state"] == "healthy"


async def test_a_private_board_still_writes_the_custom_namespace(
    db_conn, monkeypatch
) -> None:
    """The other half of the same assertion: nothing moved for the private lane.

    Deferred exactly the way ``claim_custom_companies`` defers it — with no
    ``visibility`` argument at all, so this also pins that the parameter's default
    is what the private lane relies on.
    """
    _patch_env(monkeypatch)
    _patch_recipe_http(monkeypatch, _HTTP_JSON_PAYLOAD)
    company_id = "u-privns001"
    _seed_discovered_company(db_conn, company_id, script=_http_json_script())

    await fetch_custom_company(company_id=company_id)
    db_conn.rollback()

    assert _job_source_ids(db_conn, company_id) == {custom(company_id)}
    (run,) = _scrape_runs(db_conn, company_id)
    assert run["source_id"] == custom(company_id)


@pytest.mark.parametrize(
    "seeded_public, declared_visibility",
    [
        # A published board deferred as if it were private.
        (True, "user"),
        # A private board deferred as if it were published — the dangerous one.
        (False, "public"),
    ],
)
async def test_a_visibility_mismatch_refuses_the_run_and_writes_nothing(
    db_conn, monkeypatch, seeded_public: bool, declared_visibility: str
) -> None:
    """The deferrer does not get the last word on the namespace.

    ``visibility`` rides in a Procrastinate job payload. If it disagrees with the
    row — a hand-deferred job, a board promoted between defer and run, a future
    caller that forgets the argument — harvesting anyway would write job rows under
    a namespace we cannot confirm, and every consequence of that is silent (wrong
    enrichment slice one way; no orphan guard and no owner-scoped read exemption
    the other).

    So the run is REFUSED: FAILED, no job rows, closes nothing, not a miss — the
    same shape as the disabled-company path. And it does NOT raise, so Procrastinate
    does not retry a job that will fail identically forever.
    """
    _patch_env(monkeypatch)
    _patch_recipe_http(monkeypatch, _HTTP_JSON_PAYLOAD)

    if seeded_public:
        company_id = "oracle"
        _seed_recipe_company(db_conn, company_id, script=_http_json_script())
    else:
        company_id = "u-mismatch01"
        _seed_discovered_company(db_conn, company_id, script=_http_json_script())

    await fetch_custom_company(
        company_id=company_id, visibility=declared_visibility
    )
    db_conn.rollback()

    assert _job_source_ids(db_conn, company_id) == set(), (
        "a run whose declared visibility disagreed with the row still wrote job "
        "rows — under a source_id namespace nothing confirmed"
    )
    (harvest,) = _rows(db_conn, "company_harvests", company_id)
    assert harvest["verdict"] == "FAILED"
    assert harvest["verdict_reason"] == "visibility_mismatch"
    (run,) = _scrape_runs(db_conn, company_id)
    assert run["success"] is False
    assert run["closed_jobs"] == 0


# --- the fleet circuit breaker spans BOTH lanes -------------------------------


def _insert_run(db_conn, company_id: str, source_id: str, *, success: bool) -> None:
    cur = db_conn.cursor()
    ts = get_iso_timestamp()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (run_id, company, started_at, completed_at, mode, "
            "jobs_seen, new_jobs, closed_jobs, details_fetched, error_count, "
            "source_id, success) "
            "VALUES (%s, %s, %s, %s, 'full', 0, 0, 0, 0, 0, %s, %s)"
        ).format(sql.Identifier("scrape_runs")),
        (f"run-{source_id}-{ts}", company_id, ts, ts, source_id, success),
    )
    db_conn.commit()


def test_the_fleet_breaker_counts_published_recipe_runs_too(db_conn):
    """A shared-engine outage must trip the breaker even if it only shows up on
    the published lane.

    ``fleet_breaker_tripped`` is the backstop written for the 2026-03-29 mass
    closure. Both lanes run the SAME leaf task over the SAME replay runner and the
    SAME guarded client, so a shared bug hits both — and a night of purely
    ``recipe:`` failures scoped out of the aggregate would leave every board (both
    lanes) closing jobs through an outage.

    Six ``recipe:`` runs, five failed (83% > the 20% fraction), no ``custom:`` runs
    at all: the breaker must trip.
    """
    for i in range(5):
        _insert_run(db_conn, f"pub{i}", recipe(f"pub{i}"), success=False)
    _insert_run(db_conn, "pub9", recipe("pub9"), success=True)

    assert ccs.fleet_breaker_tripped(db_conn) is True


def test_the_breaker_still_ignores_the_public_ats_fleet(db_conn):
    """Scope check, so the widening above is not "count everything".

    The breaker is about the recipe engine. A bad night on ``greenhouse_api`` is a
    vendor-client problem with its own guards, and folding it in would let an
    unrelated ATS outage freeze every custom board's close ladder.
    """
    for i in range(9):
        _insert_run(db_conn, f"gh{i}", "greenhouse_api", success=False)
    _insert_run(db_conn, "gh9", "greenhouse_api", success=True)

    assert ccs.fleet_breaker_tripped(db_conn) is False


# --- ... but each lane gets its OWN fraction, and EITHER one trips ------------
#
# THE BUG THESE PIN. The breaker is a RATIO, so folding a second lane into it widens
# the DENOMINATOR as well as the numerator. A pooled ``custom: OR recipe:`` fraction is
# therefore strictly HARDER to trip than the ``custom:``-only one it replaced — the
# opposite of what "count both lanes" is supposed to buy. The numbers below are the
# measured production volumes, so the arithmetic is not hypothetical:
#
#   custom lane   ~65 runs / 24h        (the */15 claim tick, <=3 boards per tick)
#   recipe lane   ~192 runs / 24h       (4 curated boards x 48 */30 ticks)
#
# A bad night of 14 custom failures is 21.5% of 65 (TRIPS) and 5.4% of 257 (does NOT).
# Worse still, ``success = scrape_error IS NULL AND verdict != FAILED``, so Oracle —
# permanently UNVERIFIED by construction, closing nothing — contributes 48 guaranteed
# SUCCESSES a day to a pooled denominator.

_CUSTOM_LANE_RUNS = 65      # measured: the */15 claim tick over the private fleet
_RECIPE_LANE_RUNS = 192     # measured: 4 curated boards x 48 */30 ticks


def _insert_runs(db_conn, namespace, *, tag: str, total: int, failed: int) -> None:
    """``total`` runs under ``namespace`` (``custom`` / ``recipe``), ``failed`` FAILED."""
    ts = get_iso_timestamp()
    rows = [
        (f"run-{tag}-{i}", f"{tag}{i}", ts, ts, namespace(f"{tag}{i}"), i >= failed)
        for i in range(total)
    ]
    cur = db_conn.cursor()
    cur.executemany(
        sql.SQL(
            "INSERT INTO {} (run_id, company, started_at, completed_at, mode, "
            "jobs_seen, new_jobs, closed_jobs, details_fetched, error_count, "
            "source_id, success) "
            "VALUES (%s, %s, %s, %s, 'full', 0, 0, 0, 0, 0, %s, %s)"
        ).format(sql.Identifier("scrape_runs")),
        rows,
    )
    db_conn.commit()


def test_a_custom_lane_failure_storm_trips_through_a_healthy_recipe_lane(db_conn):
    """THE regression. 14 of 65 custom runs failed while every published board was fine.

    21.5% of the custom lane, which is what the breaker is for. Pooled with the 192
    healthy ``recipe:`` runs it is 5.4% of 257 and the night's closes go ahead — a
    fleet-wide mass closure with the backstop reporting green.
    """
    failed = 14
    _insert_runs(db_conn, custom, tag="priv", total=_CUSTOM_LANE_RUNS, failed=failed)
    _insert_runs(db_conn, recipe, tag="pub", total=_RECIPE_LANE_RUNS, failed=0)

    pooled = failed / (_CUSTOM_LANE_RUNS + _RECIPE_LANE_RUNS)
    assert pooled < 0.20 < failed / _CUSTOM_LANE_RUNS, "the numbers must state the trap"
    assert ccs.fleet_breaker_tripped(db_conn) is True


def test_a_recipe_lane_failure_storm_trips_through_a_healthy_custom_lane(db_conn):
    """The mirror, so neither lane can be diluted by the other.

    40 of 192 published runs failed (20.8%) with every private board healthy. Pooled
    that is 15.6% of 257 — under the fraction, so the published fleet would keep
    closing through its own outage.
    """
    failed = 40
    _insert_runs(db_conn, recipe, tag="pub", total=_RECIPE_LANE_RUNS, failed=failed)
    _insert_runs(db_conn, custom, tag="priv", total=_CUSTOM_LANE_RUNS, failed=0)

    pooled = failed / (_CUSTOM_LANE_RUNS + _RECIPE_LANE_RUNS)
    assert pooled < 0.20 < failed / _RECIPE_LANE_RUNS, "the numbers must state the trap"
    assert ccs.fleet_breaker_tripped(db_conn) is True


def test_each_lane_carries_its_own_min_sample(db_conn):
    """A lane too small to have said anything cannot trip on the OTHER lane's volume.

    Four failed published runs is 100% of a 4-run lane, but four runs is below
    ``min_sample`` — the lane has not established a rate yet. Borrowing the custom
    lane's 65 runs to clear the sample floor would be the same denominator confusion
    running the other way.
    """
    _insert_runs(db_conn, recipe, tag="pub", total=4, failed=4)
    _insert_runs(db_conn, custom, tag="priv", total=_CUSTOM_LANE_RUNS, failed=0)

    assert ccs.fleet_breaker_tripped(db_conn) is False
