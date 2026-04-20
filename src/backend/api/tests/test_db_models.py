"""Unit tests for src/backend/api/db_models.py."""

from __future__ import annotations

import importlib
import sys

import pytest
from sqlalchemy import TIMESTAMP
from sqlalchemy.schema import ForeignKeyConstraint, UniqueConstraint


@pytest.fixture(scope="module")
def monkeypatch_module():
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def db_models_module(monkeypatch_module):
    monkeypatch_module.setenv("SCRAPER_ENVIRONMENT", "local")
    for mod_name in ("api.db_models", "src.backend.api.db_models"):
        if mod_name in sys.modules:
            del sys.modules[mod_name]
    return importlib.import_module("api.db_models")


def test_all_four_tables_present(db_models_module):
    names = set(db_models_module.Base.metadata.tables.keys())
    assert names == {
        "job_listings_local",
        "scrape_runs_local",
        "users_local",
        "user_enabled_companies_local",
        "features_local",
        "feature_upvotes_local",
    }, f"Unexpected metadata.tables: {sorted(names)}"


def test_job_listings_timestamptz_columns_have_timezone(db_models_module):
    table = db_models_module.Base.metadata.tables["job_listings_local"]
    for col_name in ("posted_on", "created_at", "closed_on", "first_seen_at", "last_seen_at"):
        col = table.c[col_name]
        assert isinstance(col.type, TIMESTAMP), (
            f"{col_name}: expected TIMESTAMP, got {type(col.type).__name__}"
        )
        assert col.type.timezone is True, f"{col_name}: timezone must be True"


def test_job_listings_nullability(db_models_module):
    table = db_models_module.Base.metadata.tables["job_listings_local"]
    assert table.c["posted_on"].nullable is True
    assert table.c["created_at"].nullable is False
    assert table.c["closed_on"].nullable is True
    assert table.c["first_seen_at"].nullable is False
    assert table.c["last_seen_at"].nullable is False


def test_users_email_unique_constraint_named(db_models_module):
    table = db_models_module.Base.metadata.tables["users_local"]
    constraint_names = {
        c.name
        for c in table.constraints
        if isinstance(c, UniqueConstraint) and c.name
    }
    assert "users_local_email_key" in constraint_names, (
        f"Expected users_local_email_key UNIQUE constraint; found: {sorted(constraint_names)}"
    )


def test_user_enabled_companies_fk_to_users_cascade(db_models_module):
    table = db_models_module.Base.metadata.tables["user_enabled_companies_local"]
    fks = [c for c in table.constraints if isinstance(c, ForeignKeyConstraint)]
    assert len(fks) == 1, f"Expected exactly one FK, found {len(fks)}"
    fk = fks[0]
    assert fk.referred_table.name == "users_local"
    referred_cols = [el.column.name for el in fk.elements]
    assert referred_cols == ["id"], f"FK points to {referred_cols}, expected ['id']"
    ondelete = fk.ondelete or fk.elements[0].ondelete
    assert (ondelete or "").upper() == "CASCADE", f"Expected ondelete=CASCADE, got {ondelete!r}"


def test_expected_indexes_on_job_listings(db_models_module):
    table = db_models_module.Base.metadata.tables["job_listings_local"]
    index_names = {ix.name for ix in table.indexes}
    expected = {
        "idx_job_listings_local_status",
        "idx_job_listings_local_company",
        "idx_job_listings_local_last_seen",
    }
    missing = expected - index_names
    assert not missing, f"Missing indexes: {missing}; present: {index_names}"


def test_expected_indexes_on_users(db_models_module):
    table = db_models_module.Base.metadata.tables["users_local"]
    index_names = {ix.name for ix in table.indexes}
    assert "idx_users_local_auth0_id" in index_names
    assert "idx_users_local_email" in index_names


def test_user_enabled_companies_has_user_id_index(db_models_module):
    table = db_models_module.Base.metadata.tables["user_enabled_companies_local"]
    index_names = {ix.name for ix in table.indexes}
    assert "idx_user_enabled_companies_local_user_id" in index_names
