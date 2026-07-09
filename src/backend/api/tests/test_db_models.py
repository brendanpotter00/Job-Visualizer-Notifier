"""Unit tests for src/backend/api/db_models.py."""

from __future__ import annotations

from sqlalchemy import TIMESTAMP
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
        "enrichment_ticks",
    }, f"Unexpected metadata.tables: {sorted(names)}"


def test_job_listings_timestamptz_columns_have_timezone():
    table = db_models.Base.metadata.tables["job_listings"]
    for col_name in ("posted_on", "created_at", "closed_on", "first_seen_at", "last_seen_at"):
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
    assert table.c["last_seen_at"].nullable is False


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


def test_expected_indexes_on_job_listings():
    table = db_models.Base.metadata.tables["job_listings"]
    index_names = {ix.name for ix in table.indexes}
    expected = {
        "idx_job_listings_status",
        "idx_job_listings_company",
        "idx_job_listings_last_seen",
    }
    missing = expected - index_names
    assert not missing, f"Missing indexes: {missing}; present: {index_names}"


def test_expected_indexes_on_users():
    table = db_models.Base.metadata.tables["users"]
    index_names = {ix.name for ix in table.indexes}
    assert "idx_users_auth0_id" in index_names
    assert "idx_users_email" in index_names


def test_user_enabled_companies_has_user_id_index():
    table = db_models.Base.metadata.tables["user_enabled_companies"]
    index_names = {ix.name for ix in table.indexes}
    assert "idx_user_enabled_companies_user_id" in index_names
