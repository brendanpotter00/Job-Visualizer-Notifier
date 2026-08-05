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


def _listings_freshness_columns(conn) -> set:
    """Freshness columns still present on ``job_listings``.

    The Unit 4 contract migration (18fe9c20a8fd) dropped both, so this must be
    empty. Post-contract the write path can't touch the wide table's freshness
    columns even by accident — the decoupling that fixes the index-bloat outage
    is enforced by the SCHEMA now, not by discipline in shared/database.py.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'job_listings' "
            "  AND table_schema = current_schema() "
            "  AND column_name IN ('last_seen_at', 'consecutive_misses')"
        )
        return {row["column_name"] for row in cur.fetchall()}


class TestFreshnessTrigger:
    def test_trigger_seeds_from_first_seen_at_not_last_seen(self, in_memory_db):
        """The trigger seeds last_seen_at from NEW.first_seen_at and misses from 0.

        Uses a listing whose model-level last_seen_at (2024-06-01) and
        consecutive_misses (9) differ from first_seen_at (2024-01-15) / 0, so this
        pins the exact seed contract — the one that had to keep working once the
        Unit 4 contract migration dropped those columns from job_listings.
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

    def test_trigger_fires_on_bare_sql_insert(self, in_memory_db):
        """A raw ``INSERT INTO job_listings`` — no helper, no ORM — still gets a
        freshness row.

        This is the point of enforcing the invariant in the DATABASE rather than
        in application code. Every other test in this file goes through
        ``shared/database.py``, so they would all still pass if the guarantee
        secretly depended on those helpers. This one bypasses them entirely: a
        psql session, a future code path, an admin backfill script, a migration
        — none of them can create a listing without freshness. If someone drops
        the trigger and re-implements the seed in Python, this test fails.
        """
        with in_memory_db.cursor() as cur:
            cur.execute(
                "INSERT INTO job_listings "
                "(id, title, company, location, url, source_id, details, "
                " created_at, status, has_matched, ai_metadata, "
                " first_seen_at, details_scraped) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s::jsonb, "
                "        %s, %s)",
                (
                    "bare-1", "Bare Engineer", "google", "Mountain View, CA, USA",
                    "https://example.com/bare-1", SourceId.GOOGLE, "{}",
                    "2024-03-04T12:00:00Z", "OPEN", False, "{}",
                    # The INSERT supplies no freshness at all — post-Unit-4 it
                    # cannot. The seed contract (first_seen_at / 0) is the only
                    # thing that can produce the assertions below.
                    "2024-03-04T12:00:00Z", True,
                ),
            )
        in_memory_db.commit()

        row = _freshness_row(in_memory_db, SourceId.GOOGLE, "bare-1")
        assert row is not None, (
            "AFTER INSERT trigger did not fire for a bare job_listings INSERT — "
            "the sidecar's existence guarantee has regressed to depending on "
            "application code"
        )
        assert row["last_seen_at"] == datetime(2024, 3, 4, 12, 0, tzinfo=timezone.utc)
        assert row["consecutive_misses"] == 0
        assert _listings_missing_freshness(in_memory_db) == 0
        assert _orphan_freshness(in_memory_db) == 0

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

    def test_full_scrape_cycle_keeps_both_anti_joins_zero(self, in_memory_db):
        """Both anti-joins stay 0 across an entire simulated scrape cycle.

        The tests above each exercise ONE write path in isolation. Drift,
        though, is a whole-cycle property: the real scraper interleaves new
        listings, re-seen listings, misses, closures and reactivations in one
        pass, and it only takes one of those paths forgetting the sidecar for
        `/api/jobs` to start silently dropping jobs behind the INNER JOIN.
        This walks the full 5-phase shape (``shared/incremental.py``) and
        re-checks BOTH invariants after every phase, so a regression names the
        phase that broke it instead of just "something drifted".

        The invariants asserted: no listing without freshness (the trigger's
        job), and no orphan freshness (the FK's job). These have no production
        monitor yet — wiring them into ``api/eval/monitor_prod.py`` is planned
        work alongside its bloat checks.
        """
        def assert_no_drift(phase: str) -> None:
            assert _listings_missing_freshness(in_memory_db) == 0, (
                f"listing(s) without a freshness row after phase: {phase}"
            )
            assert _orphan_freshness(in_memory_db) == 0, (
                f"orphan freshness row(s) after phase: {phase}"
            )

        # --- Prior state: two listings already known from an earlier cycle.
        prior = [
            _make_job(f"cycle-prior-{i}", first_seen="2024-01-01T00:00:00Z",
                      last_seen="2024-01-01T00:00:00Z", misses=0)
            for i in range(2)
        ]
        db.upsert_jobs_batch(in_memory_db, prior)
        assert_no_drift("seed prior cycle")

        # --- Phase 1/3: this cycle discovers two brand-new listings (trigger path)
        #     and re-sees one of the prior ones (ON CONFLICT + _upsert_freshness).
        now = "2024-02-01T06:00:00Z"
        discovered = [
            _make_job("cycle-new-0", first_seen=now, last_seen=now, misses=0),
            _make_job("cycle-new-1", first_seen=now, last_seen=now, misses=0),
            _make_job("cycle-prior-0", first_seen="2024-01-01T00:00:00Z",
                      last_seen=now, misses=0),
        ]
        db.upsert_jobs_batch(in_memory_db, discovered)
        assert_no_drift("upsert new + re-seen")

        # --- Phase 4: stamp the re-seen set (the per-cycle freshness write that
        #     used to rewrite job_listings on every job, every hour).
        db.update_last_seen(in_memory_db, SourceId.GOOGLE, ["cycle-prior-0"], now)
        assert_no_drift("update_last_seen")

        # --- Phase 5a: the other prior listing was NOT in this scrape — miss it.
        db.increment_consecutive_misses(in_memory_db, SourceId.GOOGLE, ["cycle-prior-1"])
        assert_no_drift("increment_consecutive_misses")

        # --- Phase 5b: it crosses the threshold and gets closed.
        missed = db.get_jobs_exceeding_miss_threshold(
            in_memory_db, SourceId.GOOGLE, ["cycle-prior-1"], threshold=1
        )
        assert missed == {"cycle-prior-1"}, (
            "miss threshold must read consecutive_misses from the sidecar"
        )
        db.mark_jobs_closed(
            in_memory_db, SourceId.GOOGLE, sorted(missed), "2024-02-01T07:00:00Z"
        )
        assert_no_drift("mark_jobs_closed")

        # --- Next cycle: the closed listing reappears and is reactivated.
        db.reactivate_job(
            in_memory_db, SourceId.GOOGLE, "cycle-prior-1", "2024-03-01T06:00:00Z"
        )
        assert_no_drift("reactivate_job")

        # Every listing the cycle touched has exactly one freshness row.
        with in_memory_db.cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM job_listings")
            listings = cur.fetchone()["n"]
            cur.execute("SELECT count(*) AS n FROM job_freshness")
            freshness = cur.fetchone()["n"]
        assert listings == 4
        assert freshness == listings


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
        # ...and the wide job_listings row cannot have been touched: post-Unit-4
        # it carries no freshness columns at all. This is the whole point — no
        # per-cycle rewrite of job_listings / idx_job_listings_last_seen.
        assert _listings_freshness_columns(in_memory_db) == set()

    def test_increment_misses_writes_sidecar_not_listings(self, in_memory_db):
        job = _make_job(
            "dec-2", first_seen="2024-01-15T10:30:00Z", last_seen="2024-01-15T10:30:00Z", misses=0
        )
        db.insert_job(in_memory_db, job)

        db.increment_consecutive_misses(in_memory_db, SourceId.GOOGLE, ["dec-2"])

        sidecar = _freshness_row(in_memory_db, SourceId.GOOGLE, "dec-2")
        assert sidecar["consecutive_misses"] == 1
        assert _listings_freshness_columns(in_memory_db) == set()

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
        # job_listings carries no freshness columns to go stale.
        assert _listings_freshness_columns(in_memory_db) == set()
