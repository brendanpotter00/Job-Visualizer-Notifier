"""U4 — the custom onboarding flow seeds ``first_seen_at`` from the board's date.

POSTED-DATE-PLAN.md §5/U4, and the deferred half of U1. ``first_seen_at`` is now the
**effective posted date**: the board's own posting date when the board publishes a real
one, first sight otherwise. It is still written only at INSERT (absent from
``_UPSERT_ON_CONFLICT``), so no first-run predicate is needed and a re-harvest cannot
move it.

Every test here drives the REAL leaf task against a real Postgres schema and reads the
row that actually landed, because the two invariants at stake are both about what the
task does to the database, not about what a helper returns:

* **never-wrong-close** — a bad date degrades one row. It may not raise, may not abort
  the harvest, and may never fall back to ``now()`` for the stored ``posted_on``.
* **RAISES-never-empty** — a genuine failure must still raise rather than return ``[]``,
  because an empty success is what silently closes a whole board.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from psycopg2 import sql

import api.tasks.fetch_custom_company as task_mod
from api.tasks.fetch_custom_company import _validated_posted_on, fetch_custom_company
from scripts.shared.constants import custom

from api.tests.test_fetch_custom_company import (
    _patch_env,
    _rows,
    _scrape_runs,
    _seed_discovered_company,
    _job_status,
)

# NOT a module-level ``pytestmark``: the second half of this file tests a pure
# function, and a blanket asyncio mark warns on every one of them.
_asyncio = pytest.mark.asyncio


# --------------------------------------------------------------------------
# a discovered board whose payload we control, end to end
# --------------------------------------------------------------------------

def _script() -> dict:
    """A page-1-only http_json recipe. ``oracle: none`` on purpose — an UNVERIFIED
    harvest still upserts, which is the path a first onboarding actually takes."""
    return {
        "script_version": 1,
        "transport": "http_json",
        "expected_min_jobs": 1,
        "steps": [
            {"op": "fetch", "method": "GET",
             "url": "https://careers.acme.example/api/jobs", "headers": {}},
            {"op": "extract_json_path", "records_path": "jobs",
             "fields": {"id": "id", "title": "title", "url": "url",
                        "posted_at": "posted"}},
            {"op": "dedupe_key", "field": "id"},
            {"op": "assert_unique", "field": "id"},
        ],
        "oracle": {"kind": "none"},
    }


def _payload(posted: object, *, n: int = 3, key: str = "posted") -> dict:
    jobs = []
    for i in range(1, n + 1):
        job = {"id": str(i), "title": f"Engineer {i}",
               "url": f"https://careers.acme.example/j/{i}"}
        if posted is not ...:
            job[key] = posted
        jobs.append(job)
    return {"jobs": jobs}


def _patch_http(monkeypatch, payload: dict) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(
        task_mod, "_recipe_http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _job_rows(db_conn, company_id: str) -> list[dict]:
    db_conn.rollback()
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "SELECT id, posted_on, first_seen_at, created_at FROM {} "
            "WHERE source_id = %s ORDER BY id"
        ).format(sql.Identifier("job_listings")),
        (custom(company_id),),
    )
    return list(cur.fetchall())


@_asyncio
async def test_a_board_with_a_real_iso_date_seeds_real_dates_on_the_first_harvest(
    db_conn, monkeypatch
) -> None:
    """The onboarding case the whole plan exists for: a board that publishes a date
    gets that date in the sort key, so its jobs are not all stamped "today" and shown
    as a day-one hiring spike that never happened."""
    company_id = "u-pdiso00001"
    _patch_env(monkeypatch)
    _seed_discovered_company(db_conn, company_id, script=_script(), oracle_kind="none")
    posted = (datetime.now(timezone.utc) - timedelta(days=30)).replace(microsecond=0)
    _patch_http(monkeypatch, _payload(posted.isoformat()))

    await fetch_custom_company(company_id=company_id)

    rows = _job_rows(db_conn, company_id)
    assert len(rows) == 3
    for row in rows:
        assert row["posted_on"] == posted
        # THE seeding assertion: the sort key is the board's date, not our clock.
        assert row["first_seen_at"] == posted
        # ...and the audit trail still holds the true insert time, which is what
        # makes the seeding reversible.
        assert row["created_at"] > posted


@_asyncio
async def test_a_board_publishing_no_date_seeds_first_sight_and_stores_null(
    db_conn, monkeypatch
) -> None:
    """No date is not "today's date" and not an error — it is a NULL ``posted_on``
    with ``first_seen_at`` falling back to when we actually saw the job."""
    company_id = "u-pdnone0001"
    _patch_env(monkeypatch)
    _seed_discovered_company(db_conn, company_id, script=_script(), oracle_kind="none")
    _patch_http(monkeypatch, _payload(...))          # the key is absent entirely
    before = datetime.now(timezone.utc)

    await fetch_custom_company(company_id=company_id)

    rows = _job_rows(db_conn, company_id)
    assert len(rows) == 3
    for row in rows:
        assert row["posted_on"] is None
        assert row["first_seen_at"] >= before - timedelta(minutes=5)
        assert abs((row["first_seen_at"] - row["created_at"]).total_seconds()) < 60


@_asyncio
async def test_a_humanized_string_is_no_date_so_it_seeds_first_sight_too(
    db_conn, monkeypatch
) -> None:
    """POSTED-DATE-PLAN.md §3 — a board that gives us a bucket has given us no date.
    ``"about 12 hours"`` must not become a timestamp, here or anywhere."""
    company_id = "u-pdhuman001"
    _patch_env(monkeypatch)
    _seed_discovered_company(db_conn, company_id, script=_script(), oracle_kind="none")
    _patch_http(monkeypatch, _payload("about 12 hours"))
    before = datetime.now(timezone.utc)

    await fetch_custom_company(company_id=company_id)

    rows = _job_rows(db_conn, company_id)
    assert len(rows) == 3
    assert all(r["posted_on"] is None for r in rows)
    assert all(r["first_seen_at"] >= before - timedelta(minutes=5) for r in rows)


@_asyncio
async def test_the_harvest_still_returns_rows_and_closes_nothing_when_every_date_fails(
    db_conn, monkeypatch
) -> None:
    """never-wrong-close, at the seam where it would actually break. A board whose
    every posting date is garbage is a board with bad dates, not a board that stopped
    hiring — the run must succeed, upsert every row, and close nothing."""
    company_id = "u-pdbad00001"
    _patch_env(monkeypatch)
    _seed_discovered_company(db_conn, company_id, script=_script(), oracle_kind="none")

    # Run 1 seeds three OPEN jobs with good dates.
    good = (datetime.now(timezone.utc) - timedelta(days=10)).replace(microsecond=0)
    _patch_http(monkeypatch, _payload(good.isoformat()))
    await fetch_custom_company(company_id=company_id)
    assert len(_job_rows(db_conn, company_id)) == 3

    # Run 2: the board keeps every job but its dates turn to prose.
    _patch_http(monkeypatch, _payload("¯\\_(ツ)_/¯"))
    await fetch_custom_company(company_id=company_id)

    jobs = _job_status(db_conn, company_id)
    assert len(jobs) == 3
    assert all(j["status"] == "OPEN" for j in jobs.values())
    assert max(j["consecutive_misses"] for j in jobs.values()) == 0

    runs = _scrape_runs(db_conn, company_id)
    assert len(runs) == 2
    assert all(r["success"] is True for r in runs)
    assert all(r["closed_jobs"] == 0 for r in runs)
    assert all(r["jobs_seen"] == 3 for r in runs)
    harvests = _rows(db_conn, "company_harvests", company_id)
    assert all(h["verdict"] != "FAILED" for h in harvests)


@_asyncio
async def test_a_provider_date_that_moves_never_moves_first_seen_at(
    db_conn, monkeypatch
) -> None:
    """The Workday-slide property, on the custom path. ``first_seen_at`` is absent from
    ``_UPSERT_ON_CONFLICT``, so a board that re-stamps its dates every night cannot
    walk the sort key forward — while ``posted_on`` (a diagnostic) does follow."""
    company_id = "u-pdslide001"
    _patch_env(monkeypatch)
    _seed_discovered_company(db_conn, company_id, script=_script(), oracle_kind="none")
    first = (datetime.now(timezone.utc) - timedelta(days=60)).replace(microsecond=0)
    _patch_http(monkeypatch, _payload(first.isoformat()))
    await fetch_custom_company(company_id=company_id)

    later = (datetime.now(timezone.utc) - timedelta(days=1)).replace(microsecond=0)
    _patch_http(monkeypatch, _payload(later.isoformat()))
    await fetch_custom_company(company_id=company_id)

    rows = _job_rows(db_conn, company_id)
    assert all(r["first_seen_at"] == first for r in rows)   # unmoved
    assert all(r["posted_on"] == later for r in rows)       # the raw value follows


@_asyncio
async def test_a_replay_failure_is_still_a_raise_not_an_empty_success(
    db_conn, monkeypatch
) -> None:
    """RAISES-never-empty. Date handling must not turn a broken harvest into a
    successful zero-row one — that is the shape that closes a whole board."""
    company_id = "u-pdraise001"
    _patch_env(monkeypatch)
    _seed_discovered_company(db_conn, company_id, script=_script(), oracle_kind="none")
    _patch_http(monkeypatch, {"totally": "wrong shape"})

    with pytest.raises(Exception):
        await fetch_custom_company(company_id=company_id)

    db_conn.rollback()
    harvests = _rows(db_conn, "company_harvests", company_id)
    assert harvests[0]["verdict"] == "FAILED"
    assert _job_rows(db_conn, company_id) == []


# --------------------------------------------------------------------------
# _validated_posted_on — the window U1 kept, now on the shared parser
# --------------------------------------------------------------------------

_NOW = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)


def test_the_shipped_window_is_unchanged_in_both_directions() -> None:
    """``[now-365d, now+7d]``, exactly as it shipped. Re-tuning it is explicitly not
    this plan's business — U1 moved the PARSING to the shared helper and left the
    window alone."""
    assert _validated_posted_on((_NOW - timedelta(days=364)).isoformat(), _NOW)
    assert _validated_posted_on((_NOW - timedelta(days=366)).isoformat(), _NOW) is None
    assert _validated_posted_on((_NOW + timedelta(days=3)).isoformat(), _NOW)
    assert _validated_posted_on((_NOW + timedelta(days=30)).isoformat(), _NOW) is None


@pytest.mark.parametrize(
    "value", [None, "", "   ", "not a date", "about 12 hours", 0, -1, True, [], {}]
)
def test_an_unreadable_value_is_null_and_never_now(value: object) -> None:
    assert _validated_posted_on(value, _NOW) is None


def test_a_naive_timestamp_is_read_as_utc_not_as_the_runners_local_zone() -> None:
    parsed = _validated_posted_on("2026-08-20T09:00:00", _NOW)
    assert parsed == "2026-08-20T09:00:00+00:00"


def test_it_now_reads_the_epoch_a_recipe_without_a_parse_date_step_hands_it() -> None:
    """The widening U1 buys: delegating to the shared parser means a board on the raw
    epoch (Microsoft's ``postedTs``) is readable even before its recipe is
    re-captured with U6's ``parse_date`` step."""
    epoch = int((_NOW - timedelta(days=2)).timestamp())
    assert _validated_posted_on(str(epoch), _NOW) == (_NOW - timedelta(days=2)).isoformat()
    assert _validated_posted_on(epoch * 1000, _NOW) == (_NOW - timedelta(days=2)).isoformat()


def test_a_naive_now_does_not_raise() -> None:
    """never-wrong-close: this runs in the same task as the close sweep, so a caller
    handing it a naive clock must degrade, not explode."""
    assert _validated_posted_on("2026-08-20T09:00:00", _NOW.replace(tzinfo=None))
