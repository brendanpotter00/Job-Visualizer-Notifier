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
