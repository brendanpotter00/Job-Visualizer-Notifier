"""Unit tests for src/backend/api/db_models.py."""

from __future__ import annotations

from sqlalchemy import TIMESTAMP, Boolean
from sqlalchemy.schema import ForeignKeyConstraint, UniqueConstraint

from api import db_models


def test_all_tables_present():
    names = set(db_models.Base.metadata.tables.keys())
    assert names == {
        "job_listings",
        "scrape_runs",
        "users",
        "user_enabled_companies",
        "user_saved_filters",
        "user_keyword_lists",
        "user_visits",
        "features",
        "feature_upvotes",
        "feedback",
        "admins",
        "companies",
        "worker_heartbeats",
        "locations",
        "location_aliases",
        "alias_locations",
        "job_locations",
        "job_categories",
        "job_levels",
        "job_tags",
        "job_enrichment",
        "job_freshness",
        "enrichment_ticks",
        "company_submissions",
    }, f"Unexpected metadata.tables: {sorted(names)}"


def test_job_listings_timestamptz_columns_have_timezone():
    table = db_models.Base.metadata.tables["job_listings"]
    for col_name in ("posted_on", "created_at", "closed_on", "first_seen_at"):
        col = table.c[col_name]
        assert isinstance(col.type, TIMESTAMP), (
            f"{col_name}: expected TIMESTAMP, got {type(col.type).__name__}"
        )
        assert col.type.timezone is True, f"{col_name}: timezone must be True"


def test_job_listings_nullability():
    table = db_models.Base.metadata.tables["job_listings"]
    assert table.c["posted_on"].nullable is True
    assert table.c["created_at"].nullable is False
    assert table.c["closed_on"].nullable is True
    assert table.c["first_seen_at"].nullable is False


def test_scrape_runs_columns():
    """Pin the full ``scrape_runs`` column set.

    ``skipped_update`` is the difference between "a truncated scrape is
    visible in the table" and "a truncated scrape is byte-for-byte
    identical to a perfect run" — which is exactly how seven real Apple
    truncations went unnoticed for three weeks. Dropping it must fail
    loudly, not silently degrade the QA table to guesswork.
    """
    table = db_models.Base.metadata.tables["scrape_runs"]
    assert set(table.c.keys()) == {
        "run_id",
        "company",
        "started_at",
        "completed_at",
        "mode",
        "jobs_seen",
        "new_jobs",
        "closed_jobs",
        "details_fetched",
        "error_count",
        "skipped_update",
        "guard_reason",
    }


def test_scrape_runs_skipped_update_is_nullable_with_no_server_default():
    """Nullable + no server default is load-bearing on two axes.

    Migration safety: a nullable column with no default is a catalog-only
    ADD COLUMN — Postgres does not rewrite the ~455k-row table (see
    docs/incidents/2026-04-18-migration-filled-postgres-volume/).

    Data honesty: NULL means "written before this column existed". A
    ``server_default='false'`` would retroactively claim the seven real
    Apple truncations were clean runs.
    """
    col = db_models.Base.metadata.tables["scrape_runs"].c["skipped_update"]
    assert isinstance(col.type, Boolean)
    assert col.nullable is True
    assert col.server_default is None
    assert col.default is None


def test_scrape_runs_guard_reason_is_nullable_text():
    """``guard_reason`` records WHICH rule tripped. Not redundant with
    ``skipped_update``: both rules set that boolean, so counting it let a
    dead scraper's ``empty_scrape`` runs release the next truncated run."""
    col = db_models.Base.metadata.tables["scrape_runs"].c["guard_reason"]
    assert col.nullable is True
    assert col.server_default is None
    assert col.default is None


def test_scrape_runs_has_company_started_at_index():
    """Without it, ``count_consecutive_partial_skips`` is a Parallel Seq
    Scan over ~452k rows (~70 MB buffers) — the LIMIT bounds the top-N
    heapsort, not the scan."""
    table = db_models.Base.metadata.tables["scrape_runs"]
    by_name = {idx.name: idx for idx in table.indexes}
    assert "idx_scrape_runs_company_started_at" in by_name, sorted(by_name)
    cols = [c.name for c in by_name["idx_scrape_runs_company_started_at"].columns]
    assert cols == ["company", "started_at"], (
        "company must lead — the query filters on company and only then "
        f"orders by started_at; got {cols}"
    )


def test_users_email_unique_constraint_named():
    table = db_models.Base.metadata.tables["users"]
    constraint_names = {
        c.name
        for c in table.constraints
        if isinstance(c, UniqueConstraint) and c.name
    }
    assert "users_email_key" in constraint_names, (
        f"Expected users_email_key UNIQUE constraint; found: {sorted(constraint_names)}"
    )


def test_user_enabled_companies_fk_to_users_cascade():
    table = db_models.Base.metadata.tables["user_enabled_companies"]
    fks = [c for c in table.constraints if isinstance(c, ForeignKeyConstraint)]
    assert len(fks) == 1, f"Expected exactly one FK, found {len(fks)}"
    fk = fks[0]
    assert fk.referred_table.name == "users"
    referred_cols = [el.column.name for el in fk.elements]
    assert referred_cols == ["id"], f"FK points to {referred_cols}, expected ['id']"
    ondelete = fk.ondelete or fk.elements[0].ondelete
    assert (ondelete or "").upper() == "CASCADE", f"Expected ondelete=CASCADE, got {ondelete!r}"


def test_job_freshness_composite_fk_to_job_listings_cascade():
    """The sidecar's drift guarantee: a real composite FK onto job_listings'
    (source_id, id) PK with ON DELETE CASCADE (no orphaned freshness rows)."""
    table = db_models.Base.metadata.tables["job_freshness"]
    fks = [c for c in table.constraints if isinstance(c, ForeignKeyConstraint)]
    assert len(fks) == 1, f"Expected exactly one FK, found {len(fks)}"
    fk = fks[0]
    assert fk.referred_table.name == "job_listings"
    referred_cols = [el.column.name for el in fk.elements]
    assert referred_cols == ["source_id", "id"], (
        f"FK points to {referred_cols}, expected ['source_id', 'id']"
    )
    ondelete = fk.ondelete or fk.elements[0].ondelete
    assert (ondelete or "").upper() == "CASCADE", f"Expected ondelete=CASCADE, got {ondelete!r}"


def test_job_freshness_last_seen_index_present():
    table = db_models.Base.metadata.tables["job_freshness"]
    index_names = {ix.name for ix in table.indexes}
    assert "idx_job_freshness_last_seen" in index_names, (
        f"Missing idx_job_freshness_last_seen; present: {index_names}"
    )


def test_expected_indexes_on_job_listings():
    table = db_models.Base.metadata.tables["job_listings"]
    index_names = {ix.name for ix in table.indexes}
    expected = {
        "idx_job_listings_status",
        "idx_job_listings_company",
        "idx_job_listings_problem_jobs",
    }
    missing = expected - index_names
    assert not missing, f"Missing indexes: {missing}; present: {index_names}"
    # Unit 4 contract (18fe9c20a8fd): the bloated parent freshness index is
    # gone for good. Its sidecar replacement is asserted separately above.
    assert "idx_job_listings_last_seen" not in index_names


def test_job_listings_has_no_freshness_columns():
    """Unit 4 contract: freshness lives ONLY on the job_freshness sidecar.

    Re-adding either column here would silently re-create the write
    amplification that caused the 2026-07-13 /api/jobs outage.
    """
    table = db_models.Base.metadata.tables["job_listings"]
    assert "last_seen_at" not in table.c
    assert "consecutive_misses" not in table.c
    sidecar = db_models.Base.metadata.tables["job_freshness"]
    assert "last_seen_at" in sidecar.c
    assert "consecutive_misses" in sidecar.c


def test_expected_indexes_on_users():
    table = db_models.Base.metadata.tables["users"]
    index_names = {ix.name for ix in table.indexes}
    assert "idx_users_auth0_id" in index_names
    assert "idx_users_email" in index_names


def test_user_enabled_companies_has_user_id_index():
    table = db_models.Base.metadata.tables["user_enabled_companies"]
    index_names = {ix.name for ix in table.indexes}
    assert "idx_user_enabled_companies_user_id" in index_names
