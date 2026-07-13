"""Integration tests for the ``job_freshness`` sidecar's DB-level anti-drift guarantees.

Unit 1 (expand) adds ``job_freshness`` with a composite FK
``(source_id, id) -> job_listings`` ``ON DELETE CASCADE`` and an ``AFTER INSERT``
trigger on ``job_listings`` that materialises the matching freshness row for
every new listing. These tests assert the drift-prevention invariants hold under
the *real* insert paths (``insert_job`` / ``upsert_jobs_batch`` /
``insert_jobs_batch``): every listing has exactly one freshness row, the trigger
seeds it from ``first_seen_at`` + ``0`` misses, deletes cascade, and neither
anti-join ever finds a stray row.

The trigger is installed in the test schema by the ``create_all`` DDL events in
``api/db_models.py`` (the conftest fixtures stamp Alembic head rather than run
migration bodies), so this exercises behavior identical to the prod migration.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.constants import SourceId
from shared.models import JobListing
from shared import database as db


def _make_job(job_id: str, *, first_seen: str, last_seen: str, misses: int) -> JobListing:
    """A minimal valid listing with independently-set freshness fields."""
    return JobListing(
        id=job_id,
        title=f"Engineer {job_id}",
        company="google",
        location="Mountain View, CA, USA",
        url=f"https://example.com/{job_id}",
        source_id=SourceId.GOOGLE,
        details={},
        created_at=first_seen,
        status="OPEN",
        has_matched=False,
        ai_metadata={},
        first_seen_at=first_seen,
        last_seen_at=last_seen,
        consecutive_misses=misses,
        details_scraped=True,
    )


def _freshness_row(conn, source_id: str, job_id: str):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT last_seen_at, consecutive_misses FROM job_freshness "
            "WHERE source_id = %s AND id = %s",
            (source_id, job_id),
        )
        return cur.fetchone()


def _listings_missing_freshness(conn) -> int:
    """Anti-join: listings with no freshness row (the drift the trigger prevents)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM job_listings l "
            "LEFT JOIN job_freshness f ON f.source_id = l.source_id AND f.id = l.id "
            "WHERE f.source_id IS NULL"
        )
        return cur.fetchone()["n"]


def _orphan_freshness(conn) -> int:
    """Reverse anti-join: freshness rows with no listing (the FK prevents this)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM job_freshness f "
            "LEFT JOIN job_listings l ON l.source_id = f.source_id AND l.id = f.id "
            "WHERE l.source_id IS NULL"
        )
        return cur.fetchone()["n"]


def _listings_raw_freshness(conn, source_id: str, job_id: str):
    """Read the RAW job_listings.last_seen_at/consecutive_misses columns.

    These still exist (until the Unit 4 contract migration) but are no longer
    written by the freshness helpers — used to prove the write path is decoupled
    from the wide table.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT last_seen_at, consecutive_misses FROM job_listings "
            "WHERE source_id = %s AND id = %s",
            (source_id, job_id),
        )
        return cur.fetchone()


class TestFreshnessTrigger:
    def test_trigger_seeds_from_first_seen_at_not_last_seen(self, in_memory_db):
        """The trigger seeds last_seen_at from NEW.first_seen_at and misses from 0.

        Uses a listing whose last_seen_at (2024-06-01) and consecutive_misses (9)
        differ from first_seen_at (2024-01-15) / 0, so this pins the exact seed
        contract — the one that must keep working after Unit 4 drops those columns.
        """
        job = _make_job(
            "seed-1",
            first_seen="2024-01-15T10:30:00Z",
            last_seen="2024-06-01T00:00:00Z",
            misses=9,
        )
        db.insert_job(in_memory_db, job)

        row = _freshness_row(in_memory_db, SourceId.GOOGLE, "seed-1")
        assert row is not None, "trigger did not create a freshness row"
        assert row["consecutive_misses"] == 0
        assert row["last_seen_at"] == datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc)

    def test_reupsert_advances_freshness_to_scrape_time(self, in_memory_db):
        """Unit 2: re-upserting an existing listing advances its sidecar
        ``last_seen_at`` to the scrape's timestamp and resets
        ``consecutive_misses`` to 0.

        This is the re-seen write path (``_upsert_freshness`` after the
        ``ON CONFLICT DO UPDATE`` on job_listings) — distinct from the AFTER
        INSERT trigger, which fires only for genuinely new rows. Regression
        guard for the two failure modes: the value must NOT stay frozen at the
        trigger's ``first_seen_at`` seed, and the re-upsert must NOT duplicate
        the freshness row.
        """
        job = _make_job(
            "reup-1", first_seen="2024-01-15T10:30:00Z", last_seen="2024-01-15T10:30:00Z", misses=0
        )
        db.insert_job(in_memory_db, job)

        # Simulate misses accrued by earlier missed cycles.
        with in_memory_db.cursor() as cur:
            cur.execute(
                "UPDATE job_freshness SET consecutive_misses = 4 "
                "WHERE source_id = %s AND id = %s",
                (SourceId.GOOGLE, "reup-1"),
            )
        in_memory_db.commit()

        # A later scrape re-sees the job: upsert with a fresher last_seen_at.
        reseen = _make_job(
            "reup-1", first_seen="2024-01-15T10:30:00Z", last_seen="2024-10-01T09:00:00Z", misses=0
        )
        db.upsert_jobs_batch(in_memory_db, [reseen])

        row = _freshness_row(in_memory_db, SourceId.GOOGLE, "reup-1")
        assert row["last_seen_at"] == datetime(2024, 10, 1, 9, 0, tzinfo=timezone.utc), (
            "re-upsert did not advance last_seen_at to the scrape time"
        )
        assert row["consecutive_misses"] == 0, "re-upsert did not reset consecutive_misses"
        with in_memory_db.cursor() as cur:
            cur.execute(
                "SELECT count(*) AS n FROM job_freshness WHERE source_id = %s AND id = %s",
                (SourceId.GOOGLE, "reup-1"),
            )
            assert cur.fetchone()["n"] == 1

    def test_conflicting_insert_does_not_duplicate_freshness(self, in_memory_db):
        """A DO NOTHING conflict re-inserting an existing listing keeps one row."""
        job = _make_job(
            "dup-1", first_seen="2024-01-15T10:30:00Z", last_seen="2024-01-15T10:30:00Z", misses=0
        )
        db.insert_job(in_memory_db, job)
        db.insert_jobs_batch(in_memory_db, [job])  # ON CONFLICT DO NOTHING

        with in_memory_db.cursor() as cur:
            cur.execute(
                "SELECT count(*) AS n FROM job_freshness WHERE source_id = %s AND id = %s",
                (SourceId.GOOGLE, "dup-1"),
            )
            assert cur.fetchone()["n"] == 1
        assert _listings_missing_freshness(in_memory_db) == 0


class TestFreshnessInvariants:
    def test_upsert_batch_keeps_both_anti_joins_zero(self, in_memory_db, multiple_job_listings):
        db.upsert_jobs_batch(in_memory_db, multiple_job_listings)
        assert _listings_missing_freshness(in_memory_db) == 0
        assert _orphan_freshness(in_memory_db) == 0

    def test_insert_batch_keeps_both_anti_joins_zero(self, in_memory_db, multiple_job_listings):
        db.insert_jobs_batch(in_memory_db, multiple_job_listings)
        assert _listings_missing_freshness(in_memory_db) == 0
        assert _orphan_freshness(in_memory_db) == 0


class TestFreshnessCascade:
    def test_delete_listing_cascades_to_freshness(self, in_memory_db):
        job = _make_job(
            "cascade-1", first_seen="2024-01-15T10:30:00Z", last_seen="2024-01-15T10:30:00Z", misses=0
        )
        db.insert_job(in_memory_db, job)
        assert _freshness_row(in_memory_db, SourceId.GOOGLE, "cascade-1") is not None

        with in_memory_db.cursor() as cur:
            cur.execute(
                "DELETE FROM job_listings WHERE source_id = %s AND id = %s",
                (SourceId.GOOGLE, "cascade-1"),
            )
        in_memory_db.commit()

        assert _freshness_row(in_memory_db, SourceId.GOOGLE, "cascade-1") is None
        assert _orphan_freshness(in_memory_db) == 0


class TestFreshnessWritePathDecoupled:
    """Unit 2: the freshness helpers write the sidecar and leave the wide
    job_listings row (and its indexes) untouched — the decoupling that fixes the
    index-bloat outage."""

    def test_update_last_seen_writes_sidecar_not_listings(self, in_memory_db):
        job = _make_job(
            "dec-1", first_seen="2024-01-15T10:30:00Z", last_seen="2024-01-15T10:30:00Z", misses=0
        )
        db.insert_job(in_memory_db, job)

        db.update_last_seen(
            in_memory_db, SourceId.GOOGLE, ["dec-1"], "2024-08-20T08:00:00Z"
        )

        # Sidecar advanced...
        sidecar = _freshness_row(in_memory_db, SourceId.GOOGLE, "dec-1")
        assert sidecar["last_seen_at"] == datetime(2024, 8, 20, 8, 0, tzinfo=timezone.utc)
        # ...but the wide job_listings row's column is untouched (still the
        # insert-time value). This is the whole point: no per-cycle rewrite of
        # job_listings / idx_job_listings_last_seen.
        raw = _listings_raw_freshness(in_memory_db, SourceId.GOOGLE, "dec-1")
        assert raw["last_seen_at"] == datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc)

    def test_increment_misses_writes_sidecar_not_listings(self, in_memory_db):
        job = _make_job(
            "dec-2", first_seen="2024-01-15T10:30:00Z", last_seen="2024-01-15T10:30:00Z", misses=0
        )
        db.insert_job(in_memory_db, job)

        db.increment_consecutive_misses(in_memory_db, SourceId.GOOGLE, ["dec-2"])

        sidecar = _freshness_row(in_memory_db, SourceId.GOOGLE, "dec-2")
        assert sidecar["consecutive_misses"] == 1
        raw = _listings_raw_freshness(in_memory_db, SourceId.GOOGLE, "dec-2")
        assert raw["consecutive_misses"] == 0

    def test_reactivate_splits_status_and_freshness(self, in_memory_db):
        job = _make_job(
            "dec-3", first_seen="2024-01-15T10:30:00Z", last_seen="2024-01-15T10:30:00Z", misses=0
        )
        db.insert_job(in_memory_db, job)
        db.mark_jobs_closed(in_memory_db, SourceId.GOOGLE, ["dec-3"], "2024-02-01T00:00:00Z")

        db.reactivate_job(in_memory_db, SourceId.GOOGLE, "dec-3", "2024-09-09T09:00:00Z")

        # Status/closed_on came off job_listings; freshness came off the sidecar.
        row = db.get_job_by_id(in_memory_db, SourceId.GOOGLE, "dec-3")
        assert row["status"] == "OPEN"
        assert row["closed_on"] is None
        sidecar = _freshness_row(in_memory_db, SourceId.GOOGLE, "dec-3")
        assert sidecar["last_seen_at"] == datetime(2024, 9, 9, 9, 0, tzinfo=timezone.utc)
        assert sidecar["consecutive_misses"] == 0
        # job_listings freshness column stays at the insert-time value.
        raw = _listings_raw_freshness(in_memory_db, SourceId.GOOGLE, "dec-3")
        assert raw["last_seen_at"] == datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc)
