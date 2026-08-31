"""The ATS clients seed ``first_seen_at`` with the board's date — once, at INSERT.

POSTED-DATE-PLAN.md §5/U3, ATS half. §5 claims "the six backend ATS tasks need no
change (they flow through ``upsert_jobs_batch``)". That is **false**: each client
stamps ``first_seen_at`` itself in its ``_transform_one`` and the fetch tasks hand
those objects straight to ``db.upsert_jobs_batch``, which writes the value
verbatim. ``batch_writer.py`` is never in that path. So the rule has to be applied
in the clients, and this module proves it end-to-end against a real Postgres for
**all six**: ashby, lever, gem, greenhouse, eightfold, workday.

Everything is parametrised by provider on purpose. Each board expresses "I have
no date" differently — Lever omits ``createdAt``, Workday says
``"Posted 30+ Days Ago"`` — and a suite that only knew ``None`` would test a
shape three of these boards never emit. ``_no_date`` / ``_junk_date`` hold those
per-provider spellings so the seventh client added here needs one table entry,
not a new test.

⚠️ **never-wrong-close.** The whole safety argument for "seed at insert, always,
with no first-run predicate" is that ``first_seen_at`` is absent from
``_UPSERT_ON_CONFLICT``. That is asserted here for the ATS path too, because the
ATS clients are where the Workday date slide actually originates.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from scripts.shared import database as db
from scripts.shared.database import _UPSERT_ON_CONFLICT

from api.services import (
    ashby_client,
    eightfold_client,
    gem_client,
    greenhouse_client,
    lever_client,
    workday_client,
)

WORKDAY_CONFIG = {
    "base_url": "https://nvidia.wd5.myworkdayjobs.com",
    "tenant_slug": "nvidia",
    "career_site_slug": "NVIDIAExternalCareerSite",
}

RUN_ONE = "2026-08-26T12:00:00+00:00"
RUN_TWO = "2026-08-27T12:00:00+00:00"
RUN_ONE_DT = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)


def _pin_clock(module, now: str):
    """Freeze one client's run clock.

    Only ``workday_client`` takes a ``now`` parameter; the other five do not, and
    adding one purely for a test would widen a public signature to suit the test
    tree. Patching the timestamp helper they all call keeps the production
    surface unchanged.
    """
    return patch.object(module, "get_iso_timestamp", lambda: now)


def _ashby(job_id: str, published_at, now: str):
    raw = {
        "id": job_id,
        "title": "Software Engineer",
        "jobUrl": f"https://jobs.ashbyhq.com/notion/{job_id}",
        "location": "New York, NY",
        "publishedAt": published_at,
        "descriptionHtml": "<p>Build things.</p>",
    }
    with _pin_clock(ashby_client, now):
        return ashby_client.transform_to_job_listings("notion", [raw])


def _lever(job_id: str, created_at_ms, now: str):
    raw = {
        "id": job_id,
        "text": "Software Engineer",
        "hostedUrl": f"https://jobs.lever.co/palantir/{job_id}",
        "categories": {"location": "Palo Alto, CA"},
        "createdAt": created_at_ms,
        "description": "<p>Build things.</p>",
    }
    with _pin_clock(lever_client, now):
        return lever_client.transform_to_job_listings("palantir", [raw])


def _gem(job_id: str, first_published_at, now: str):
    raw = {
        "id": job_id,
        "title": "Software Engineer",
        "absolute_url": f"https://jobs.gem.com/retool/{job_id}",
        "offices": [{"name": "San Francisco, CA"}],
        "first_published_at": first_published_at,
        "created_at": None,
        "content": "<p>Build things.</p>",
    }
    with _pin_clock(gem_client, now):
        return gem_client.transform_to_job_listings("retool", [raw])


def _greenhouse(job_id: str, first_published, now: str):
    raw = {
        "id": job_id,
        "title": "Software Engineer",
        "absolute_url": f"https://boards.greenhouse.io/stripe/jobs/{job_id}",
        "location": {"name": "San Francisco, CA"},
        "first_published": first_published,
        "updated_at": None,
        "content": "<p>Build things.</p>",
    }
    with _pin_clock(greenhouse_client, now):
        return greenhouse_client.transform_to_job_listings("stripe", [raw])


def _eightfold(job_id: str, t_create, now: str):
    raw = {
        "id": job_id,
        "ats_job_id": f"req-{job_id}",
        "display_job_id": job_id,
        "name": "Software Engineer",
        "canonicalPositionUrl": f"https://explore.jobs.netflix.net/jobs/{job_id}",
        "location": "Los Angeles,California,United States",
        "locations": ["Los Angeles,California,United States"],
        "t_create": t_create,
        "job_description": "Build things.",
    }
    with _pin_clock(eightfold_client, now):
        return eightfold_client.transform_to_job_listings("netflix", [raw])


def _workday(job_id: str, posted_on, now: str):
    """Workday's ``postedOn`` is relative English, so the fixtures are too.

    ``None`` here means "the board published no usable date", which for Workday
    is overwhelmingly the ``30+`` bucket — 42.3% of open rows — mapped to None by
    ``_parse_workday_date`` (U5a) precisely because a bucket boundary is not a
    date. ``_no_date`` below turns the parametrised ``None`` into that string, so
    the fallback under test is Workday's real one.
    """
    raw = {
        "title": "Software Engineer",
        "externalPath": f"/job/US-CA-Santa-Clara/Software-Engineer_{job_id}",
        "locationsText": "Santa Clara, CA",
        "postedOn": posted_on,
        "bulletFields": [job_id],
    }
    return workday_client.transform_to_job_listings(
        "nvidia", [raw], WORKDAY_CONFIG, now=now
    )


# provider -> (builder, a dated value, a LATER dated value)
BUILDERS = {
    "ashby": (_ashby, "2026-06-15T08:00:00Z", "2026-08-25T08:00:00Z"),
    "lever": (_lever, 1781510400000, 1787788800000),
    "gem": (_gem, "2026-06-15T08:00:00Z", "2026-08-25T08:00:00Z"),
    "greenhouse": (_greenhouse, "2026-06-15T08:00:00Z", "2026-08-25T08:00:00Z"),
    "eightfold": (_eightfold, 1781510400, 1787788800),
    # Workday re-derives these against TODAY, which is the whole point: run one
    # says "72 days ago", run two says "1 day ago" for the same listing.
    "workday": (_workday, "Posted 72 Days Ago", "Posted Yesterday"),
}

# What "the board published nothing usable" looks like per provider. Workday
# cannot express it as None — it expresses it as a bucket.
_NO_DATE = {"workday": "Posted 30+ Days Ago"}

# What "the board published something unreadable" looks like per provider.
_JUNK_DATE = {"lever": "not-a-number", "eightfold": "not-a-number"}


def _no_date(provider: str):
    return _NO_DATE.get(provider, None)


def _junk_date(provider: str):
    return _JUNK_DATE.get(provider, "not-a-real-date")


def _row(conn, source_id: str, job_id: str):
    row = db.get_job_by_id(conn, source_id, job_id)
    assert row is not None, f"{source_id}/{job_id} was never written"
    return row


class TestUpsertOnConflictOmitsFirstSeenAt:
    """⚠️ never-wrong-close, restated on the ATS side.

    Duplicated on purpose from the scripts-side suite: the ATS clients are where
    the Workday slide originates, and whoever changes them should trip this
    without having to know the scraper test tree exists.
    """

    def test_on_conflict_never_sets_first_seen_at(self):
        assert "first_seen_at" not in _UPSERT_ON_CONFLICT, (
            "_UPSERT_ON_CONFLICT now updates first_seen_at; 'seed at insert, "
            "always' is only safe because it does not"
        )


@pytest.mark.parametrize("provider", sorted(BUILDERS))
class TestBoardDateReachesTheDatabase:
    def test_a_real_board_date_is_stored(self, db_conn, provider):
        build, dated, _ = BUILDERS[provider]
        jobs = build(f"{provider}-real", dated, RUN_ONE)
        db.upsert_jobs_batch(db_conn, jobs)

        row = _row(db_conn, jobs[0].source_id, f"{provider}-real")
        assert row["first_seen_at"] == row["posted_on"], (
            "the stored sort key is not the board's own date"
        )
        assert row["first_seen_at"] < datetime(2026, 8, 1, tzinfo=timezone.utc)

    def test_an_absent_board_date_stores_the_run_timestamp(self, db_conn, provider):
        build, _, _ = BUILDERS[provider]
        jobs = build(f"{provider}-none", _no_date(provider), RUN_ONE)
        db.upsert_jobs_batch(db_conn, jobs)

        row = _row(db_conn, jobs[0].source_id, f"{provider}-none")
        assert row["posted_on"] is None
        assert row["first_seen_at"] == RUN_ONE_DT

    def test_an_unparseable_board_date_stores_the_run_timestamp(
        self, db_conn, provider
    ):
        """Degrades per row. The client already NULLs ``posted_on`` and logs; the
        seed must follow it down rather than fabricating a date or failing the
        batch (a failed batch retries row-by-row and loses exactly those rows)."""
        build, _, _ = BUILDERS[provider]
        jobs = build(f"{provider}-junk", _junk_date(provider), RUN_ONE)
        db.upsert_jobs_batch(db_conn, jobs)

        row = _row(db_conn, jobs[0].source_id, f"{provider}-junk")
        assert row["posted_on"] is None
        assert row["first_seen_at"] == RUN_ONE_DT

    def test_a_second_upsert_never_moves_it_when_the_board_date_slides(
        self, db_conn, provider
    ):
        """THE Workday-slide case, on the path Workday actually uses.

        Workday recomputes "Posted N Days Ago" against today, so the same listing's
        provider date walks forward every scrape. If that reached ``first_seen_at``
        the whole board would re-sort to the top of the recency feed every hour and
        never age out. The guarantee is structural — ``_UPSERT_ON_CONFLICT`` omits
        the column — so it holds for every client, including the three still
        pending.
        """
        build, dated, slid = BUILDERS[provider]
        job_id = f"{provider}-slide"

        first = build(job_id, dated, RUN_ONE)
        db.upsert_jobs_batch(db_conn, first)
        original = _row(db_conn, first[0].source_id, job_id)["first_seen_at"]

        second = build(job_id, slid, RUN_TWO)
        db.upsert_jobs_batch(db_conn, second)

        row = _row(db_conn, first[0].source_id, job_id)
        assert row["first_seen_at"] == original, (
            "first_seen_at moved on re-upsert — the board's slide reached the "
            "sort key"
        )
        # ...while the raw board value DID move, proving the second write landed.
        assert row["posted_on"] > original

    def test_a_far_future_board_date_never_reaches_the_sort_key(
        self, db_conn, provider
    ):
        """Parse safety (D5). A corrupt or expiry-shaped field dated a year out
        would otherwise pin the row to the top of the recency feed forever."""
        build, _, _ = BUILDERS[provider]
        far = datetime.now(timezone.utc) + timedelta(days=400)
        if provider == "lever":
            value = int(far.timestamp() * 1000)
        elif provider == "eightfold":
            value = int(far.timestamp())
        elif provider == "workday":
            # Workday cannot express a future date at all — its vocabulary is
            # "N Days Ago". Skip rather than fake a shape the board never emits.
            pytest.skip("Workday's relative-date vocabulary has no future form")
        else:
            value = far.isoformat()

        jobs = build(f"{provider}-future", value, RUN_ONE)
        db.upsert_jobs_batch(db_conn, jobs)

        row = _row(db_conn, jobs[0].source_id, f"{provider}-future")
        assert row["first_seen_at"] == RUN_ONE_DT, "a date 400 days out was accepted as the posting date"
