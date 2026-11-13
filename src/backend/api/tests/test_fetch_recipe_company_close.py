"""THE CLOSE LADDER ON THE PUBLISHED RECIPE LANE — multi-run, both oracles.

``test_fetch_custom_company_close`` proves the destructive tail on the PRIVATE
lane: only a VERIFIED run may close, the miss threshold, the wall-clock floor,
the VERIFIED streak, the fleet breaker. Every one of those tests seeds
``visibility='user'`` and reads ``custom:<id>``.

The published lane (``companies.ats='recipe'``, ``visibility='public'``, rows at
``recipe:<id>``, deferred by ``enqueue_recipe_fan_out``) reuses that same leaf
task and therefore the same ladder — but nothing proved it, and "reuses the same
code" is a claim about the code, not about the rows. The two lanes differ in
three places that all sit on the destructive path:

* the ``source_id`` every miss/close statement is keyed by
  (``db.get_active_job_ids`` / ``increment_consecutive_misses`` /
  ``get_jobs_exceeding_miss_threshold`` / ``mark_jobs_closed`` all take it);
* ``cadence_hours`` is NULL on a seeded published row (migration
  ``4c1f8a26d7be`` does not set it), so both the close floor
  (``1.5 * cadence``) and the ``none``-oracle streak (``24 / cadence``) come off
  ``ccs.DEFAULT_CADENCE_HOURS``; and
* the two seeded boards land on DIFFERENT oracles — GitHub
  ``declared_probed``, Atlassian ``none`` (history-delta) — which is exactly the
  split that decides whether a streak is required at all.

So this file drives the REAL committed recipes
(``fixtures/recipes/published/*.json``, the same JSON the migration seeds) over
successive harvests and asserts what actually happened to the rows:

1. a second harvest re-upserts unchanged jobs without duplicating them and
   without closing anything (``test_a_second_harvest_...``);
2. a removed job accrues ``consecutive_misses`` and then CLOSES, at the same
   rung the private ``declared_probed`` path closes at;
3. the ``none`` board does NOT close at that rung — it needs its VERIFIED
   streak first, and it closes the run the streak completes;
4. an UNVERIFIED run closes nothing and is not a miss, on a board that is
   otherwise one clean run away from closing; and
5. a job that comes BACK after one absence has its miss counter reset, so a
   board that blinks never latches toward a close.

Nothing here touches the network: the recipes are replayed through
``httpx.MockTransport``, the same mechanism ``test_fetch_custom_company`` and
``test_recipe_corpus_regression`` use.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import httpx
import pytest

import api.tasks.fetch_custom_company as task_mod
from api.services import custom_companies_service as ccs
from api.tasks.fetch_custom_company import fetch_custom_company
from scripts.shared.constants import custom, recipe

from api.tests.test_fetch_custom_company import (
    _company_row,
    _job_status,
    _patch_env,
    _rows,
    _scrape_runs,
    backdate_last_seen,
)
from api.tests.test_fetch_custom_company_close import _max_misses
from api.tests.test_fetch_recipe_company import (
    _job_source_ids,
    _seed_recipe_company,
)

pytestmark = pytest.mark.asyncio

_PUBLISHED_RECIPES = Path(__file__).parent / "fixtures" / "recipes" / "published"


def _published_recipe(name: str) -> dict[str, Any]:
    """The recipe migration ``4c1f8a26d7be`` seeds, read from the committed file.

    Loaded rather than hand-written so a change to what we actually publish has
    to come through here: the close ladder's inputs (oracle kind, whether the
    recipe paginates, whether the request carries a page parameter) are decided
    by this JSON, and a test carrying its own copy would keep passing after the
    real board moved to a shape that cannot close at all.
    """
    return json.loads((_PUBLISHED_RECIPES / f"{name}.json").read_text())


# The two published boards, and the ONE run count that separates them. A
# ``declared_probed`` board proves completeness against a trusted total every
# run, so it may close as soon as the miss threshold and the wall-clock floor
# are met. A ``none`` board proves nothing deductively, so it must additionally
# hold a VERIFIED streak — and on a published row (``cadence_hours`` NULL →
# ``DEFAULT_CADENCE_HOURS`` = 1) that streak is 24 runs.
#
# WORTH KNOWING, and derived rather than hard-coded here so it stays true: the
# published lane's REAL cadence is the ``*/30`` cron in
# ``enqueue_recipe_fan_out``, i.e. 0.5 h, while the leaf task reads
# ``cadence_hours`` off the row and finds NULL, so it computes both
# cadence-derived numbers from 1 h:
#
#   close floor   1.5 * 1.0 = 1.5 h   (intended 0.75 h → STRICTER, safe)
#   ``none`` streak  24 / 1.0 = 24 runs = 12 h of wall clock at */30
#
# ``_NO_ORACLE_STREAK_MIN_HOURS`` is documented as buying "a DAY of observation"
# — the run count is only the mechanism — so a published ``none`` board settles
# in half that. It is not a wrong close (24 clean VERIFIED runs, the id-churn
# guard and check 13 all still apply) and it is not fixable by seeding the
# column either: ``companies.cadence_hours`` is an INTEGER and cannot express 30
# minutes. Recorded here rather than silently encoded as a literal 24.
_STREAK_REQUIRED = task_mod._required_streak("none", ccs.DEFAULT_CADENCE_HOURS)


def _posted_at() -> str:
    """A posting date inside the leaf task's ±window, computed off the clock so
    the fixture does not age out of it."""
    return (datetime.now(timezone.utc) - timedelta(days=3)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


class _GithubBoard:
    """www.github.careers' JSON shape, served from a mutable id list.

    ``totalCount`` is the ``declared_probed`` oracle's total. It AGREES with the
    rows served unless a test overrides it — an override is how a published run
    is driven UNVERIFIED (``count_mismatch``) without failing, which is the only
    way to isolate "the verdict, and nothing else, is what blocked the close".
    """

    def __init__(self, ids: Iterable[Any]) -> None:
        self.ids = [str(i) for i in ids]
        self.declared_total: int | None = None

    def payload(self, request: httpx.Request) -> dict[str, Any]:
        page = int(request.url.params.get("page", 1))
        limit = int(request.url.params.get("limit", 100))
        window = self.ids[(page - 1) * limit: page * limit]
        return {
            "jobs": [
                {
                    "data": {
                        "req_id": job_id,
                        "title": f"Engineer {job_id}",
                        "location_name": "Remote",
                        "posted_date": _posted_at(),
                        "description": "<p>Ship it.</p>",
                    }
                }
                for job_id in window
            ],
            "totalCount": (
                len(self.ids) if self.declared_total is None else self.declared_total
            ),
        }


class _AtlassianBoard:
    """www.atlassian.com/endpoint/careers/listings — a bare root array, no
    pagination, no declared total (``oracle: none``)."""

    def __init__(self, ids: Iterable[Any]) -> None:
        self.ids = [str(i) for i in ids]

    def payload(self, request: httpx.Request) -> list[dict[str, Any]]:
        return [
            {
                "id": job_id,
                "title": f"Engineer {job_id}",
                "category": "Engineering",
                "locations": "Remote",
                "responsibilities": "<p>Ship it.</p>",
                "portalJobPost": {
                    "portalUrl": (
                        f"https://www.atlassian.com/company/careers/details/{job_id}"
                    )
                },
            }
            for job_id in self.ids
        ]


def _patch_board(monkeypatch: pytest.MonkeyPatch, board: Any) -> None:
    """Replay the board offline, through the leaf task's own client seam.

    ``_patch_recipe_http`` in ``test_fetch_custom_company`` binds ONE payload at
    patch time; every test here needs the board to CHANGE between harvests (that
    is the whole subject), so the handler reads the live object instead.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=board.payload(request))

    monkeypatch.setattr(
        task_mod,
        "_recipe_http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _open_ids(db_conn, company_id: str) -> set[str]:
    return {
        job_id
        for job_id, row in _job_status(
            db_conn, company_id, source_id=recipe(company_id)
        ).items()
        if row["status"] == "OPEN"
    }


def _row_count(db_conn, company_id: str) -> int:
    """Every ``job_listings`` row for this company, in ANY namespace.

    Deliberately unscoped: a second harvest that wrote its rows under a second
    ``source_id`` would leave the ``recipe:``-scoped count looking perfect while
    doubling the corpus.
    """
    cur = db_conn.cursor()
    cur.execute(
        "SELECT count(*) AS n FROM job_listings WHERE company = %s", (company_id,)
    )
    return int(cur.fetchone()["n"])


# --------------------------------------------------------------------------- #
# 1 — the second harvest itself
# --------------------------------------------------------------------------- #

async def test_a_second_harvest_reupserts_without_duplicating_or_closing(
    db_conn, monkeypatch
) -> None:
    """The plain re-read, which nothing covered: a published board harvested TWICE.

    Every close test below is a delta against this, so it has to be pinned on its
    own — the ladder can only be trusted to close the right row if the unchanged
    rows survive a second pass untouched. Three separate ways that can go wrong
    and all three are asserted: the second run must not insert a second copy of a
    job (the composite PK is ``(source_id, id)``, so a namespace that moved
    between runs would DOUBLE the corpus rather than conflict), it must refresh
    ``last_seen_at`` rather than let the rows drift toward the miss threshold, and
    it must close nothing at all.
    """
    _patch_env(monkeypatch)
    company_id = "github"
    board = _GithubBoard(range(1001, 1026))          # 25 jobs
    _patch_board(monkeypatch, board)
    _seed_recipe_company(
        db_conn, company_id, script=_published_recipe("github"),
        oracle_kind="declared_probed",
    )

    await fetch_custom_company(company_id=company_id, visibility="public")
    db_conn.rollback()
    first_pass = _job_status(db_conn, company_id, source_id=recipe(company_id))
    assert len(first_pass) == 25
    assert _row_count(db_conn, company_id) == 25

    # Age every row, so a second harvest that failed to refresh last_seen_at is
    # visible as a stale timestamp rather than as a difference of milliseconds.
    for job_id in first_pass:
        backdate_last_seen(
            db_conn, company_id, job_id, 5, source_id=recipe(company_id)
        )

    await fetch_custom_company(company_id=company_id, visibility="public")
    db_conn.rollback()

    assert _row_count(db_conn, company_id) == 25, "the second harvest duplicated rows"
    second_pass = _job_status(db_conn, company_id, source_id=recipe(company_id))
    assert set(second_pass) == set(first_pass)
    assert all(row["status"] == "OPEN" for row in second_pass.values())
    assert _max_misses(db_conn, company_id, source_id=recipe(company_id)) == 0

    cur = db_conn.cursor()
    cur.execute(
        "SELECT count(*) AS n FROM job_freshness "
        "WHERE source_id = %s AND last_seen_at < now() - interval '1 hour'",
        (recipe(company_id),),
    )
    assert cur.fetchone()["n"] == 0, "the second harvest did not refresh last_seen_at"

    # BOTH runs, not just the first: the namespace is re-derived per run from the
    # row, so a regression could move it on any run but the first.
    assert _job_source_ids(db_conn, company_id) == {recipe(company_id)}
    runs = _scrape_runs(db_conn, company_id)
    assert len(runs) == 2
    assert [r["source_id"] for r in runs] == [recipe(company_id)] * 2
    assert all(r["closed_jobs"] == 0 for r in runs)
    assert all(r["success"] is True for r in runs)
    harvests = _rows(db_conn, "company_harvests", company_id)
    assert [h["verdict"] for h in harvests] == ["VERIFIED", "VERIFIED"]
    assert all(h["oracle_kind"] == "declared_probed" for h in harvests)


# --------------------------------------------------------------------------- #
# 2 — GitHub-shaped: declared_probed closes on the 2nd miss past the floor
# --------------------------------------------------------------------------- #

async def test_a_published_declared_probed_board_misses_then_closes_a_removed_job(
    db_conn, monkeypatch
) -> None:
    """The published counterpart of ``test_greenhouse_declared_total_verifies_
    and_closes_removed_job`` — same rungs, ``recipe:`` rows.

    The board's own ``totalCount`` drops with the job, so every run VERIFIES
    ``declared_exact`` and the only thing standing between the removal and the
    close is the ladder: the first VERIFIED run graduates the board and closes
    nothing, the second records ONE miss, and the third closes — but only once
    ``last_seen_at`` is older than ``1.5 * cadence_hours``. ``cadence_hours`` is
    NULL on a seeded published row, so that floor is 1.5 h off
    ``DEFAULT_CADENCE_HOURS`` and NOT the 36 h the private daily boards were
    written against; the run below that closes nothing is what proves the floor
    is real rather than an artefact of the test clock.
    """
    _patch_env(monkeypatch)
    company_id = "github-close"
    board = _GithubBoard(range(2001, 2026))          # 25 jobs
    _patch_board(monkeypatch, board)
    _seed_recipe_company(
        db_conn, company_id, script=_published_recipe("github"),
        oracle_kind="declared_probed",
    )
    source_id = recipe(company_id)

    # --- Run 1: the whole board. First VERIFIED run → tracking, closes nothing.
    await fetch_custom_company(company_id=company_id, visibility="public")
    db_conn.rollback()
    assert _open_ids(db_conn, company_id) == {str(i) for i in range(2001, 2026)}
    assert _company_row(db_conn, company_id)["tracking_started_at"] is not None
    assert _scrape_runs(db_conn, company_id)[-1]["guard_reason"] == "first_verified_run"

    # --- Run 2: job 2025 is pulled from the board → miss 1, still OPEN.
    board.ids.remove("2025")
    await fetch_custom_company(company_id=company_id, visibility="public")
    db_conn.rollback()
    jobs = _job_status(db_conn, company_id, source_id=source_id)
    assert jobs["2025"]["consecutive_misses"] == 1
    assert jobs["2025"]["status"] == "OPEN"
    assert _scrape_runs(db_conn, company_id)[-1]["closed_jobs"] == 0

    # --- Run 3: miss 2 — the threshold — but last_seen_at is still minutes old,
    # so the wall-clock floor holds the close.
    await fetch_custom_company(company_id=company_id, visibility="public")
    db_conn.rollback()
    jobs = _job_status(db_conn, company_id, source_id=source_id)
    assert jobs["2025"]["consecutive_misses"] == 2
    assert jobs["2025"]["status"] == "OPEN", "closed before the wall-clock floor"
    assert _scrape_runs(db_conn, company_id)[-1]["closed_jobs"] == 0

    # --- Run 4: same board, but the job is now older than 1.5 * cadence → CLOSE.
    backdate_last_seen(db_conn, company_id, "2025", 2, source_id=source_id)
    await fetch_custom_company(company_id=company_id, visibility="public")
    db_conn.rollback()

    jobs = _job_status(db_conn, company_id, source_id=source_id)
    assert jobs["2025"]["status"] == "CLOSED"
    assert _open_ids(db_conn, company_id) == {str(i) for i in range(2001, 2025)}
    run = _scrape_runs(db_conn, company_id)[-1]
    assert run["closed_jobs"] == 1
    assert run["guard_reason"] is None
    # The close was written into the published namespace, and the private one was
    # never touched on any of the four runs.
    assert _job_source_ids(db_conn, company_id) == {source_id}
    assert custom(company_id) not in _job_source_ids(db_conn, company_id)
    cur = db_conn.cursor()
    cur.execute(
        "SELECT status, closed_on FROM job_listings WHERE source_id = %s AND id = %s",
        (source_id, "2025"),
    )
    closed = cur.fetchone()
    assert closed["status"] == "CLOSED" and closed["closed_on"] is not None


# --------------------------------------------------------------------------- #
# 3 — Atlassian-shaped: ``none`` needs its VERIFIED streak first
# --------------------------------------------------------------------------- #

async def test_a_published_history_delta_board_needs_its_streak_before_it_closes(
    db_conn, monkeypatch
) -> None:
    """The distinguishing counterpart. Same removal, same floor, no close — yet.

    Atlassian's recipe declares ``oracle: none``, so ``verify_harvest`` runs the
    HISTORY-DELTA oracle: VERIFIED ``history_delta_ok`` means "this board has been
    returning about this many rows and the request does not look like page one",
    which is empirical, not deductive. The leaf task hedges that with a
    consecutive-VERIFIED streak, and on a published row the cadence is NULL →
    ``DEFAULT_CADENCE_HOURS``, so the streak is a full day of runs.

    THE ASSERTION THAT MATTERS is the pair: at the exact rung where the
    ``declared_probed`` board above closed — 2 misses, past the wall-clock floor,
    every gate green — this board reports ``streak_too_short`` and keeps the job
    OPEN. And then it DOES close, on the run the streak completes, so the guard
    is a delay and not a board that can never close (which is the failure mode
    the history-delta oracle was written to end).
    """
    _patch_env(monkeypatch)
    company_id = "atlassian"
    board = _AtlassianBoard(range(3001, 3056))       # 55 jobs, over min 50
    _patch_board(monkeypatch, board)
    _seed_recipe_company(
        db_conn, company_id, script=_published_recipe("atlassian"),
        oracle_kind="none",
    )
    source_id = recipe(company_id)

    # --- Run 1: the whole board. VERIFIED on the history-delta oracle.
    await fetch_custom_company(company_id=company_id, visibility="public")
    db_conn.rollback()
    harvest = _rows(db_conn, "company_harvests", company_id)[-1]
    assert harvest["verdict"] == "VERIFIED"
    assert harvest["verdict_reason"] == "history_delta_ok"
    assert harvest["oracle_kind"] == "none"
    assert len(_open_ids(db_conn, company_id)) == 55

    # --- Runs 2 and 3: job 3055 leaves the board. Two misses, and the job is
    # aged past the wall-clock floor — which is EVERY condition the
    # declared_probed board closed on.
    board.ids.remove("3055")
    for _ in range(2):
        await fetch_custom_company(company_id=company_id, visibility="public")
        db_conn.rollback()
    backdate_last_seen(db_conn, company_id, "3055", 5, source_id=source_id)

    jobs = _job_status(db_conn, company_id, source_id=source_id)
    assert jobs["3055"]["consecutive_misses"] == 2
    assert jobs["3055"]["status"] == "OPEN"
    assert _scrape_runs(db_conn, company_id)[-1]["guard_reason"] == "streak_too_short"

    # --- Runs 4 .. STREAK_REQUIRED-1: still short, misses keep accruing so the
    # run that completes the streak can act on them.
    for run_number in range(4, _STREAK_REQUIRED):
        await fetch_custom_company(company_id=company_id, visibility="public")
        db_conn.rollback()
        assert (
            _job_status(db_conn, company_id, source_id=source_id)["3055"]["status"]
            == "OPEN"
        ), f"closed on run {run_number}, before the {_STREAK_REQUIRED}-run streak"
        run = _scrape_runs(db_conn, company_id)[-1]
        assert run["guard_reason"] == "streak_too_short"
        assert run["closed_jobs"] == 0

    # --- The run that completes the streak: the accrued misses finally close it.
    await fetch_custom_company(company_id=company_id, visibility="public")
    db_conn.rollback()

    runs = _scrape_runs(db_conn, company_id)
    assert len(runs) == _STREAK_REQUIRED
    assert runs[-1]["guard_reason"] is None
    assert runs[-1]["closed_jobs"] == 1
    jobs = _job_status(db_conn, company_id, source_id=source_id)
    assert jobs["3055"]["status"] == "CLOSED"
    assert len(_open_ids(db_conn, company_id)) == 54
    assert _job_source_ids(db_conn, company_id) == {source_id}


# --------------------------------------------------------------------------- #
# 4 — the negative: an UNVERIFIED published run closes nothing, misses nothing
# --------------------------------------------------------------------------- #

async def test_an_unverified_published_run_neither_closes_nor_counts_as_a_miss(
    db_conn, monkeypatch
) -> None:
    """Invariant #2 on the published lane: only a VERIFIED run may be destructive.

    Set up so the verdict is the ONLY thing left. The job has already missed the
    threshold, it is already past the wall-clock floor, the board is already
    graduated, the fleet is healthy — the previous run would have closed it and
    the NEXT one does. The run in between differs in exactly one respect: the
    board's ``totalCount`` disagrees with the rows it served, so the oracle
    answers ``count_mismatch`` and the harvest is UNVERIFIED.

    That run must do NOTHING destructive: no close, and no miss either — an
    UNVERIFIED harvest is not evidence the job left the board, and letting it
    increment would let a broken read latch a live job toward closure. Both are
    asserted by the counter being UNCHANGED across it and then moving by exactly
    one on the VERIFIED run that follows.
    """
    _patch_env(monkeypatch)
    company_id = "github-unverified"
    board = _GithubBoard(range(4001, 4026))          # 25 jobs
    _patch_board(monkeypatch, board)
    _seed_recipe_company(
        db_conn, company_id, script=_published_recipe("github"),
        oracle_kind="declared_probed",
    )
    source_id = recipe(company_id)

    # Runs 1-3: graduate the board, then take job 4025 to the miss threshold and
    # age it past the floor. Everything is now green except the next verdict.
    await fetch_custom_company(company_id=company_id, visibility="public")
    db_conn.rollback()
    board.ids.remove("4025")
    for _ in range(2):
        await fetch_custom_company(company_id=company_id, visibility="public")
        db_conn.rollback()
    backdate_last_seen(db_conn, company_id, "4025", 2, source_id=source_id)
    jobs = _job_status(db_conn, company_id, source_id=source_id)
    assert jobs["4025"]["consecutive_misses"] == 2
    assert jobs["4025"]["status"] == "OPEN"

    # --- The UNVERIFIED run. The board serves 24 rows but declares 25.
    board.declared_total = 25
    await fetch_custom_company(company_id=company_id, visibility="public")
    db_conn.rollback()

    harvest = _rows(db_conn, "company_harvests", company_id)[-1]
    assert harvest["verdict"] == "UNVERIFIED"
    assert harvest["verdict_reason"] == "count_mismatch"
    run = _scrape_runs(db_conn, company_id)[-1]
    assert run["guard_reason"] == "unverified_harvest"
    assert run["closed_jobs"] == 0
    # An UNVERIFIED run is still an executed run (it upserts + refreshes
    # last_seen), so it must not be mistaken for a FAILED one either.
    assert run["success"] is True

    jobs = _job_status(db_conn, company_id, source_id=source_id)
    assert jobs["4025"]["status"] == "OPEN", "an UNVERIFIED run closed a job"
    assert jobs["4025"]["consecutive_misses"] == 2, (
        "an UNVERIFIED run counted a miss — a read that could not prove it saw "
        "the whole board is not evidence the job left it"
    )
    # It also must not have touched anything else on the board.
    assert len(_open_ids(db_conn, company_id)) == 25

    # --- The identical run, with the oracle agreeing again: NOW it closes. The
    # verdict was the only difference.
    board.declared_total = None
    await fetch_custom_company(company_id=company_id, visibility="public")
    db_conn.rollback()

    jobs = _job_status(db_conn, company_id, source_id=source_id)
    assert jobs["4025"]["status"] == "CLOSED"
    assert jobs["4025"]["consecutive_misses"] == 3
    assert _scrape_runs(db_conn, company_id)[-1]["closed_jobs"] == 1
    assert _job_source_ids(db_conn, company_id) == {source_id}


# --------------------------------------------------------------------------- #
# 5 — the other half of "does not spuriously close": a job that comes BACK
# --------------------------------------------------------------------------- #

async def test_a_job_that_returns_to_the_board_resets_its_miss_counter(
    db_conn, monkeypatch
) -> None:
    """A miss counter that only ever goes up is a slow mass closure.

    Boards drop a posting for one read and serve it again on the next — a
    deploy, a cache, a filter that flickered. The counter is CONSECUTIVE misses
    for that reason, and the reset rides the re-upsert (``_upsert_freshness``
    writes 0 for every row in the batch, and ``update_last_seen`` writes it
    again for every id seen this run). If it did not, a board that dropped one
    job per read would accumulate a close for every job it ever blinked on —
    and on the published lane that is a public company's chart losing rows that
    are still live.

    So: miss it once, serve it again, and the counter must be back to zero — and
    a run later, when the job is missing again, it must start over at ONE rather
    than resume at two.
    """
    _patch_env(monkeypatch)
    company_id = "github-flicker"
    board = _GithubBoard(range(5001, 5026))          # 25 jobs
    _patch_board(monkeypatch, board)
    _seed_recipe_company(
        db_conn, company_id, script=_published_recipe("github"),
        oracle_kind="declared_probed",
    )
    source_id = recipe(company_id)

    await fetch_custom_company(company_id=company_id, visibility="public")
    db_conn.rollback()

    # Blink: job 5025 is absent for exactly one read.
    board.ids.remove("5025")
    await fetch_custom_company(company_id=company_id, visibility="public")
    db_conn.rollback()
    assert (
        _job_status(db_conn, company_id, source_id=source_id)["5025"][
            "consecutive_misses"
        ]
        == 1
    )

    board.ids.append("5025")
    await fetch_custom_company(company_id=company_id, visibility="public")
    db_conn.rollback()
    jobs = _job_status(db_conn, company_id, source_id=source_id)
    assert jobs["5025"]["status"] == "OPEN"
    assert jobs["5025"]["consecutive_misses"] == 0, (
        "a job that came back kept its miss — the counter is CONSECUTIVE misses"
    )

    # And the counter really restarted: the next disappearance is miss ONE, not
    # miss two, so the blink cannot have advanced it toward the threshold.
    board.ids.remove("5025")
    await fetch_custom_company(company_id=company_id, visibility="public")
    db_conn.rollback()
    jobs = _job_status(db_conn, company_id, source_id=source_id)
    assert jobs["5025"]["consecutive_misses"] == 1
    assert jobs["5025"]["status"] == "OPEN"
    assert all(r["closed_jobs"] == 0 for r in _scrape_runs(db_conn, company_id))
    assert _job_source_ids(db_conn, company_id) == {source_id}
