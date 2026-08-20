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
        "job_subcategories",
        "job_levels",
        "job_tags",
        "job_enrichment",
        "job_freshness",
        "enrichment_ticks",
        # E7 custom company sources (Phase 1).
        "user_companies",
        "company_scripts",
        "company_harvests",
        "company_add_attempts",
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
        # E7: per-company namespace + boolean outcome for custom-company runs.
        "source_id",
        "success",
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
        # Partial GIN on the subcategory array, OPEN slice only.
        "idx_job_listings_open_subcategories_gin",
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


# --- migration <-> model mirror --------------------------------------------
#
# Two schema-building paths exist and they must agree. Prod runs the Alembic
# chain from the FastAPI lifespan hook; both test bootstraps
# (`api/tests/conftest.py::db_conn`, `scripts/tests/conftest.py::postgres_db`)
# run `Base.metadata.create_all` + `alembic stamp` and never execute a migration
# body at all. So an index that lives in only ONE of the two places is a schema
# that differs between prod and every test in the suite.
#
# `scripts/tests/integration/test_alembic_parity.py` does NOT catch that, despite
# being the obvious candidate: it builds its schema with `create_all` from the
# current models and then diffs autogenerate against those SAME models, so it can
# only detect db_models.py disagreeing with itself. Deleting
# `idx_job_tags_tag_trgm` from db_models.py entirely leaves it green. Nor can the
# gap be closed the obvious way — running `alembic upgrade head` on an empty
# database and diffing that — because this chain is not runnable from zero: the
# baseline revision `91337142414f` is EMPTY (the original tables were materialized
# by `create_all`), so `upgrade` from an empty DB dies at the first migration that
# references `users`. Verified 2026-08-20.
#
# What is left is to compare the two DECLARATIONS directly, which is what these
# do. It is narrow — one migration, the one this PR adds — and it is the check
# that was claimed and not actually held.


def _trigram_migration_ops():
    """Run `536c1cddcd28`'s bodies against a recording stand-in for `op`.

    Importing the module by path rather than by package name because revision
    files are not importable modules of `api`, and swapping the module-global
    `op` because the real proxy needs a live MigrationContext — which would drag
    a database into a test whose whole subject is two declarations.
    """
    import importlib.util
    from pathlib import Path

    class _Recorder:
        def __init__(self):
            self.executed: list[str] = []
            self.created: list[tuple] = []
            self.dropped: list[tuple] = []

        def execute(self, sql):
            self.executed.append(str(sql))

        def create_index(self, name, table, columns, **kwargs):
            self.created.append((name, table, list(columns), kwargs))

        def drop_index(self, name, table_name=None, **kwargs):
            self.dropped.append((name, table_name))

    versions = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    matches = sorted(versions.glob("*536c1cddcd28*.py"))
    assert len(matches) == 1, f"expected one 536c1cddcd28 revision, found {matches}"

    spec = importlib.util.spec_from_file_location("_rev_536c1cddcd28", matches[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    up, down = _Recorder(), _Recorder()
    module.op = up
    module.upgrade()
    module.op = down
    module.downgrade()
    return up, down


def test_the_trigram_index_migration_and_the_model_mirror_declare_the_SAME_index():
    """`idx_job_tags_tag_trgm` must be identical on both schema-building paths.

    Access method and operator class are both load-bearing and both silent when
    wrong: a plain btree, or GIN without `gin_trgm_ops`, still creates an index
    and still answers every query correctly — it simply cannot serve the leading
    wildcard, so the keyword filter goes back to a full `job_tags` scan per term
    with nothing failing anywhere.
    """
    up, _ = _trigram_migration_ops()

    assert len(up.created) == 1, up.created
    name, table, columns, kwargs = up.created[0]

    model_index = next(
        (i for i in db_models.JobTag.__table__.indexes if i.name == name), None
    )
    assert model_index is not None, (
        f"migration 536c1cddcd28 creates {name} but db_models.py does not mirror it — "
        "create_all-built schemas (every test bootstrap) would not have it"
    )

    assert table == db_models.JobTag.__tablename__
    assert columns == [c.name for c in model_index.expressions]
    assert kwargs["postgresql_using"] == model_index.dialect_kwargs["postgresql_using"]
    assert kwargs["postgresql_ops"] == model_index.dialect_kwargs["postgresql_ops"]


def test_the_trigram_migration_installs_the_extension_the_model_hook_installs():
    """Both paths need `pg_trgm` in `public`, and for the same reason.

    A bare `CREATE EXTENSION` lands in the first entry of `search_path`, which
    under `PYTEST_SCHEMA` is a per-module `test_<hex>` schema dropped CASCADE at
    teardown — taking `gin_trgm_ops` with it and breaking every later module in
    the session. If these two statements ever drift, one of the two paths gets
    the extension in the wrong place.
    """
    up, down = _trigram_migration_ops()

    assert str(db_models._PG_TRGM_EXTENSION) in up.executed, up.executed

    # And the asymmetry is deliberate: the index goes, the extension stays. An
    # extension is database-global, so a DROP would either fail (half-applied
    # downgrade) or CASCADE away objects this migration never created.
    assert [d[0] for d in down.dropped] == ["idx_job_tags_tag_trgm"], down.dropped
    assert not any("DROP EXTENSION" in sql.upper() for sql in down.executed), down.executed

def test_job_subcategories_dimension_shape():
    """The subcategory dimension: PK slug, NOT NULL label + parent_slug + sort_order.

    `parent_slug` is NOT NULL and FKs onto job_categories.slug — every row's
    parent is 'software_engineering'. It is a GROUPING edge, unlike
    JobLevel.parent_slug which is a FILTER-EXPANSION edge; the two must never be
    fed to the same code path.
    """
    table = db_models.Base.metadata.tables["job_subcategories"]
    assert set(table.c.keys()) == {"slug", "label", "parent_slug", "sort_order"}
    assert table.c["slug"].primary_key is True
    assert table.c["label"].nullable is False
    assert table.c["parent_slug"].nullable is False
    assert table.c["sort_order"].nullable is False
    fk_targets = {fk.target_fullname for fk in table.c["parent_slug"].foreign_keys}
    assert fk_targets == {"job_categories.slug"}
    # Deliberately unindexed: 15 rows, one parent.
    assert not table.indexes


def test_job_listings_subcategory_columns_are_nullable():
    """NULL is a MEANINGFUL state — "never evaluated", i.e. the backfill queue.

    A NOT NULL default of '{}' here would silently mark the entire corpus
    "evaluated, nothing applies" and empty the queue before it ever filled.
    """
    table = db_models.Base.metadata.tables["job_listings"]
    assert table.c["enrichment_subcategories"].nullable is True
    assert table.c["enrichment_subcategory_source"].nullable is True
    assert table.c["enrichment_subcategories"].server_default is None


def test_job_enrichment_has_subcategory_confidence():
    table = db_models.Base.metadata.tables["job_enrichment"]
    assert "subcategory_confidence" in table.c
    assert table.c["subcategory_confidence"].nullable is True
