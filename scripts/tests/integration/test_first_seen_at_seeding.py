"""``first_seen_at`` is the effective posted date, seeded once at INSERT.

POSTED-DATE-PLAN.md §5/U3. These tests go through the real write path
(``BatchWriter`` -> ``upsert_jobs_batch``) against a real Postgres, because what
is being pinned is not a Python expression — it is the interaction between the
value ``batch_writer`` computes and the ``ON CONFLICT`` clause that decides
whether that value can ever move again.

The two properties, together, are the whole unit:

1. ``first_seen_at`` = the board's posting date when it publishes a real one,
   the run timestamp otherwise (``batch_writer.add_job``).
2. ``first_seen_at`` is absent from ``_UPSERT_ON_CONFLICT``'s SET list, so (1)
   only ever decides an INSERT and can never rewrite an existing row.

Property (2) is what makes (1) safe with no first-run predicate at all, and it is
the easiest thing in this codebase to break quietly: adding ``first_seen_at`` to
that SET list compiles, passes most tests, imports Workday's daily date slide
into the product, and destroys the reopen guarantee. It is asserted directly.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared import database as db
from shared.batch_writer import BatchWriter
from shared.constants import SourceId
from shared.database import _UPSERT_ON_CONFLICT
from shared.models import JobListing

RUN_TIMESTAMP = "2026-08-26T12:00:00Z"
LATER_RUN_TIMESTAMP = "2026-08-27T12:00:00Z"


class _FakeScraper:
    """Minimal ScraperProtocol impl: turns a dict into a JobListing verbatim.

    Deliberately sets ``first_seen_at``/``last_seen_at`` to a value that is
    obviously neither the provider date nor the run timestamp, so anything the
    assertions below see must have come from ``BatchWriter.add_job``.
    """

    def transform_to_job_model(self, job_data: Dict[str, Any]) -> JobListing:
        return JobListing(
            id=job_data["id"],
            title=job_data.get("title", "Engineer"),
            company="google",
            location="Mountain View, CA, USA",
            url=f"https://example.com/{job_data['id']}",
            source_id=SourceId.GOOGLE,
            details={},
            posted_on=job_data.get("posted_on"),
            created_at="1999-01-01T00:00:00Z",
            closed_on=None,
            status="OPEN",
            has_matched=False,
            ai_metadata={},
            first_seen_at="1999-01-01T00:00:00Z",
            last_seen_at="1999-01-01T00:00:00Z",
            consecutive_misses=0,
            details_scraped=False,
        )


def _write(conn, job_id: str, posted_on: Optional[str], timestamp: str) -> None:
    """One scrape cycle's worth of writing, through the real BatchWriter."""
    writer = BatchWriter(conn, _FakeScraper(), batch_size=50, use_upsert=True)
    writer.add_job({"id": job_id, "posted_on": posted_on}, timestamp)
    writer.flush()


def _row(conn, job_id: str) -> Dict[str, Any]:
    row = db.get_job_by_id(conn, SourceId.GOOGLE, job_id)
    assert row is not None, f"{job_id} was never written"
    return row


class TestUpsertOnConflictOmitsFirstSeenAt:
    """⚠️ never-wrong-close. The single most load-bearing line in U3."""

    def test_on_conflict_never_sets_first_seen_at(self):
        """Adding ``first_seen_at`` to this SET list would compile and pass most
        tests. It would also make every re-scrape overwrite the posting date with
        whatever the board says today — importing Workday's daily slide — and
        destroy the reopen guarantee, since a reopened job's original date would
        be replaced by the date of the scrape that found it again."""
        assert "first_seen_at" not in _UPSERT_ON_CONFLICT, (
            "_UPSERT_ON_CONFLICT now updates first_seen_at; 'seed at insert, "
            "always' is only safe because it does not"
        )

    def test_on_conflict_does_refresh_posted_on(self):
        """The counterpart: the RAW board value is allowed to move, and does.
        That is exactly why the sort key must not be derived from it on update —
        the two columns diverging is the mechanism, not a bug."""
        assert "posted_on = EXCLUDED.posted_on" in _UPSERT_ON_CONFLICT


class TestSeedAtInsert:
    def test_real_provider_date_is_stored(self, in_memory_db):
        _write(in_memory_db, "seed-real", "2026-06-15T08:00:00Z", RUN_TIMESTAMP)

        row = _row(in_memory_db, "seed-real")
        assert row["first_seen_at"] == datetime(2026, 6, 15, 8, 0, tzinfo=timezone.utc)

    def test_absent_provider_date_stores_the_run_timestamp(self, in_memory_db):
        """Dateless boards (google_scraper, tiktok_scraper) fall back to first
        sight. D3: that fallback is silent and their day-one spike is permanent —
        the owner's call, reversible on the frontend with no migration."""
        _write(in_memory_db, "seed-none", None, RUN_TIMESTAMP)

        row = _row(in_memory_db, "seed-none")
        assert row["first_seen_at"] == datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)

    @pytest.mark.parametrize(
        "label,posted_on",
        [
            ("none", None),
            ("real", "2026-06-15T08:00:00Z"),
            ("far-future", "2027-12-31T00:00:00Z"),
            ("ancient", "2009-04-01T00:00:00Z"),
        ],
    )
    def test_first_seen_at_is_never_null(self, in_memory_db, label, posted_on):
        """The column is NOT NULL and it is the keyset sort key. A provider value
        the parser rejects must degrade to first sight, never to a failed INSERT
        that the row-by-row fallback then loses (batch_writer.py:120-128).

        The inputs here are all values Postgres can actually store: ``posted_on``
        is a TIMESTAMPTZ, so a junk STRING never gets as far as this code — it
        fails the INSERT first. That is the live Microsoft bug in §7 and it
        belongs to U5e; the junk-string half of this rule is pinned without a DB
        in ``test_batch_writer.py`` and ``test_posted_date.py``.
        """
        job_id = f"notnull-{label}"
        _write(in_memory_db, job_id, posted_on, RUN_TIMESTAMP)

        assert _row(in_memory_db, job_id)["first_seen_at"] is not None

    def test_created_at_holds_the_true_insert_time(self, in_memory_db):
        """``created_at`` keeps the literal meaning ``first_seen_at`` gave up
        (§2). It is the audit trail that makes the seeding reversible, and the
        predicate health tooling must move to (U8c) now that a uniform
        ``first_seen_at`` no longer means 'bulk insert'."""
        _write(in_memory_db, "audit-1", "2026-06-15T08:00:00Z", RUN_TIMESTAMP)

        row = _row(in_memory_db, "audit-1")
        assert row["created_at"] == datetime(1999, 1, 1, tzinfo=timezone.utc), (
            "created_at was rewritten; the scraper's own insert-time value must "
            "survive untouched"
        )
        assert row["created_at"] != row["first_seen_at"]


class TestImmutableAfterInsert:
    def test_a_second_upsert_never_moves_it_when_the_provider_date_slides(
        self, in_memory_db
    ):
        """THE Workday-slide test.

        Workday recomputes 'Posted N Days Ago' against today, so the same
        listing's provider date walks forward on every scrape. If that reached
        ``first_seen_at`` the whole board would re-sort to the top of the recency
        feed every hour and never age out.
        """
        _write(in_memory_db, "slide-1", "2026-06-15T08:00:00Z", RUN_TIMESTAMP)
        original = _row(in_memory_db, "slide-1")["first_seen_at"]

        # Same job, next cycle, board now claims a much fresher posting date.
        _write(in_memory_db, "slide-1", "2026-08-27T08:00:00Z", LATER_RUN_TIMESTAMP)

        row = _row(in_memory_db, "slide-1")
        assert row["first_seen_at"] == original, (
            "first_seen_at moved on re-upsert — the provider's slide reached the "
            "sort key"
        )
        # ...while the raw board value did move, proving the second write landed.
        assert row["posted_on"] == datetime(2026, 8, 27, 8, 0, tzinfo=timezone.utc)

    def test_a_second_upsert_never_moves_it_when_the_date_disappears(
        self, in_memory_db
    ):
        """The other direction: a board that stops publishing a date must not
        cause the stored posting date to be replaced by today's timestamp."""
        _write(in_memory_db, "slide-2", "2026-06-15T08:00:00Z", RUN_TIMESTAMP)
        original = _row(in_memory_db, "slide-2")["first_seen_at"]

        _write(in_memory_db, "slide-2", None, LATER_RUN_TIMESTAMP)

        assert _row(in_memory_db, "slide-2")["first_seen_at"] == original

    def test_close_then_reopen_leaves_first_seen_at_untouched(self, in_memory_db):
        """The reopen guarantee. D9: a reopened job does NOT resurface as new —
        it keeps the date the company posted it."""
        _write(in_memory_db, "reopen-1", "2026-06-15T08:00:00Z", RUN_TIMESTAMP)
        original = _row(in_memory_db, "reopen-1")["first_seen_at"]

        db.mark_jobs_closed(
            in_memory_db, SourceId.GOOGLE, ["reopen-1"], "2026-08-26T18:00:00Z"
        )
        assert _row(in_memory_db, "reopen-1")["status"] == "CLOSED"

        # It reappears in a later scrape and the upsert reactivates it.
        _write(in_memory_db, "reopen-1", "2026-08-27T08:00:00Z", LATER_RUN_TIMESTAMP)

        row = _row(in_memory_db, "reopen-1")
        assert row["status"] == "OPEN"
        assert row["closed_on"] is None
        assert row["first_seen_at"] == original, (
            "a reopened listing was restamped with a new posting date"
        )

    def test_last_seen_at_still_tracks_the_run_not_the_posting_date(
        self, in_memory_db
    ):
        """``last_seen_at = timestamp`` stays exactly as it was. It is freshness,
        and the close sweep's optional wall-clock floor reads it — backdating it
        to a months-old posting date is how a healthy job gets wrong-closed."""
        _write(in_memory_db, "fresh-1", "2026-06-15T08:00:00Z", RUN_TIMESTAMP)

        row = _row(in_memory_db, "fresh-1")
        assert row["last_seen_at"] == datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        assert row["last_seen_at"] > row["first_seen_at"]


class TestCloseBehaviourIsUnaffected:
    """⚠️ never-wrong-close, proved rather than argued."""

    def test_miss_threshold_query_ignores_first_seen_at_entirely(self, in_memory_db):
        """The sweep is ``consecutive_misses >= threshold``
        (shared/database.py:783-790). A row whose ``first_seen_at`` is years old
        but which was seen this cycle is not closeable, and no seeding change can
        make it so."""
        _write(in_memory_db, "old-1", "2020-01-01T00:00:00Z", RUN_TIMESTAMP)

        closeable = db.get_jobs_exceeding_miss_threshold(
            in_memory_db, SourceId.GOOGLE, ["old-1"], threshold=3
        )
        assert closeable == set()

        db.increment_consecutive_misses(in_memory_db, SourceId.GOOGLE, ["old-1"])
        db.increment_consecutive_misses(in_memory_db, SourceId.GOOGLE, ["old-1"])
        db.increment_consecutive_misses(in_memory_db, SourceId.GOOGLE, ["old-1"])

        assert db.get_jobs_exceeding_miss_threshold(
            in_memory_db, SourceId.GOOGLE, ["old-1"], threshold=3
        ) == {"old-1"}

    def test_a_backdated_row_survives_the_wall_clock_floor(self, in_memory_db):
        """The one time-based clause in the sweep reads ``last_seen_at``, which
        U3 does not change. With misses over threshold but the row seen moments
        ago, the 36h floor still refuses to close it — regardless of a
        ``first_seen_at`` from 2020."""
        _write(in_memory_db, "floor-1", "2020-01-01T00:00:00Z", RUN_TIMESTAMP)
        db.update_last_seen(
            in_memory_db,
            SourceId.GOOGLE,
            ["floor-1"],
            datetime.now(timezone.utc).isoformat(),
        )
        for _ in range(4):
            db.increment_consecutive_misses(in_memory_db, SourceId.GOOGLE, ["floor-1"])

        assert db.get_jobs_exceeding_miss_threshold(
            in_memory_db,
            SourceId.GOOGLE,
            ["floor-1"],
            threshold=3,
            min_seen_age_hours=36,
        ) == set()


class TestScriptScraperConstructors:
    """The four script scrapers agree with the write path (U3).

    Their constructor value is overwritten by ``BatchWriter.add_job`` before it
    reaches the DB, so these assertions are about the MODEL being honest — a
    caller that inspects a transform result must not see a different story from
    the row that gets written.
    """

    def test_amazon_uses_the_provider_date(self):
        from amazon_jobs_scraper.scraper import AmazonJobsScraper

        job = AmazonJobsScraper().transform_to_job_model(
            {
                "id": "10496449",
                "title": "SDE II",
                "job_url": "https://www.amazon.jobs/en/jobs/10496449/sde",
                "posted_date": "2026-08-08",
            }
        )
        assert job.posted_on == "2026-08-08"
        assert job.first_seen_at == "2026-08-08T00:00:00+00:00"
        assert job.first_seen_at != job.created_at

    def test_amazon_falls_back_when_the_card_has_no_date(self):
        from amazon_jobs_scraper.scraper import AmazonJobsScraper

        job = AmazonJobsScraper().transform_to_job_model(
            {
                "id": "10496450",
                "title": "SDE II",
                "job_url": "https://www.amazon.jobs/en/jobs/10496450/sde",
            }
        )
        assert job.posted_on is None
        assert job.first_seen_at == job.created_at

    def test_microsoft_uses_the_provider_date(self):
        from microsoft_jobs_scraper.scraper import MicrosoftJobsScraper

        job = MicrosoftJobsScraper().transform_to_job_model(
            {
                "id": "1234567",
                "title": "Software Engineer",
                "job_url": "https://jobs.careers.microsoft.com/global/en/job/1234567",
                "posted_on": "2026-07-01T00:00:00Z",
            }
        )
        assert job.first_seen_at == "2026-07-01T00:00:00+00:00"
        assert job.first_seen_at != job.created_at


def _future(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


class TestParseSafetyReachesTheDatabase:
    def test_a_far_future_provider_date_never_reaches_the_sort_key(
        self, in_memory_db
    ):
        """D5 end to end: a corrupt/expiry field dated a year out would otherwise
        pin the row to the top of the recency feed forever."""
        _write(in_memory_db, "future-1", _future(400), RUN_TIMESTAMP)

        row = _row(in_memory_db, "future-1")
        assert row["first_seen_at"] == datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)

    def test_a_slightly_future_provider_date_is_kept(self, in_memory_db):
        """Board timezones make 'tomorrow' routine; rejecting it would throw away
        good dates on every board that stamps at day granularity."""
        posted = _future(2)
        _write(in_memory_db, "future-2", posted, RUN_TIMESTAMP)

        row = _row(in_memory_db, "future-2")
        assert row["first_seen_at"] != datetime(
            2026, 8, 26, 12, 0, tzinfo=timezone.utc
        )
