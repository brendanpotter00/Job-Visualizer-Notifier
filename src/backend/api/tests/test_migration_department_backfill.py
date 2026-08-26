"""Migration ``c1539fa03b23`` — the ``job_listings.department`` backfill.

The DDL half (one nullable ``ADD COLUMN``, catalog-only) is covered by the fact
that every test DB in this suite is built from ``db_models`` and the whole chain
is replayed by ``conftest``; if the column were missing, every department test
would fail. What this file locks is the **backfill loop**, which is the part with
behaviour rather than shape:

* it copies every non-empty ``details->>'department'`` into the column,
* it walks the whole table in chunks rather than one unbounded UPDATE, and
* it is restartable — re-running writes nothing and never clobbers a value a
  concurrent scrape wrote between chunks.

The last point is the one that matters operationally: the migration runs
in-process at backend boot, and a boot that dies mid-backfill leaves the column
half-filled with the revision unstamped, so the next boot runs it again.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic" / "versions"
    / "20260826_063000_c1539fa03b23_add_department_column_to_job_listings.py"
)


def _module() -> Any:
    """Load the revision file by path — its name is not an importable identifier."""
    spec = importlib.util.spec_from_file_location("_mig_c1539fa03b23", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def seeded(db_conn):
    """Rows whose ``department`` column has been blanked back to the pre-migration
    state, so the backfill has real work to do.

    ``db_conn``'s schema is already at head (the column exists and ``_make_job``
    fills it), which is why this has to undo it rather than build up to it.
    """
    from api.tests.conftest import _insert_job, _make_job

    rows = [
        ("with-dept-1", {"department": "Engineering", "experience_level": "Senior"}),
        ("with-dept-2", {"department": "Data Science"}),
        ("empty-dept", {"department": ""}),
        ("no-dept-key", {"experience_level": "Senior"}),
        ("null-dept", {"department": None}),
    ]
    for job_id, details in rows:
        _insert_job(db_conn, _make_job({"id": job_id, "details": json.dumps(details)}))
    cursor = db_conn.cursor()
    cursor.execute("UPDATE job_listings SET department = NULL")
    db_conn.commit()
    return [job_id for job_id, _ in rows]


def _departments(db_conn) -> dict[str, str | None]:
    cursor = db_conn.cursor()
    cursor.execute("SELECT id, department FROM job_listings")
    return {row["id"]: row["department"] for row in cursor.fetchall()}


def _sqlalchemy_conn(db_conn):
    """A SQLAlchemy connection on the same search_path as the psycopg2 test conn.

    The migration takes ``op.get_bind()``, i.e. a SQLAlchemy connection, and the
    per-worker test schema is selected by ``search_path`` — so the two have to be
    pointed at the same schema or the backfill silently updates ``public``.
    """
    import os

    from sqlalchemy import create_engine

    engine = create_engine(os.environ["DATABASE_URL"])
    conn = engine.connect()
    schema = os.environ.get("PYTEST_SCHEMA")
    if schema:
        conn.execute(text(f'SET search_path TO "{schema}", public'))
    return conn


def test_backfill_copies_every_real_department_and_nothing_else(db_conn, seeded):
    module = _module()
    conn = _sqlalchemy_conn(db_conn)
    try:
        written = module._backfill_department(conn)
        conn.commit()
    finally:
        conn.close()

    departments = _departments(db_conn)
    assert departments["with-dept-1"] == "Engineering"
    assert departments["with-dept-2"] == "Data Science"
    # An empty string is not a department: it would render as a blank option in
    # the Department dropdown and match nothing.
    assert departments["empty-dept"] is None
    assert departments["no-dept-key"] is None
    assert departments["null-dept"] is None
    assert written == 2


def test_backfill_is_restartable_and_writes_nothing_on_a_second_run(db_conn, seeded):
    """Re-running after a completed (or partially completed) run is a no-op.

    ``written == 0`` is the assertion that matters: it proves the second pass
    skipped every already-filled row instead of rewriting all of them, which is
    what makes a crashed boot cheap to retry rather than a second full-table
    UPDATE.
    """
    module = _module()
    conn = _sqlalchemy_conn(db_conn)
    try:
        module._backfill_department(conn)
        conn.commit()
        written_again = module._backfill_department(conn)
        conn.commit()
    finally:
        conn.close()

    assert written_again == 0
    assert _departments(db_conn)["with-dept-1"] == "Engineering"


def test_backfill_never_clobbers_a_value_written_after_the_column_was_added(db_conn, seeded):
    """A scrape landing mid-backfill wins.

    The upsert write path sets ``department`` on every re-seen row, so a value
    already in the column is strictly fresher than the one frozen in ``details``.
    The backfill's ``department IS NULL`` guard is what keeps it from overwriting
    that with stale JSONB.
    """
    cursor = db_conn.cursor()
    cursor.execute(
        "UPDATE job_listings SET department = %s WHERE id = %s",
        ("Renamed By A Scrape", "with-dept-1"),
    )
    db_conn.commit()

    module = _module()
    conn = _sqlalchemy_conn(db_conn)
    try:
        module._backfill_department(conn)
        conn.commit()
    finally:
        conn.close()

    assert _departments(db_conn)["with-dept-1"] == "Renamed By A Scrape"


def test_backfill_walks_the_whole_table_in_bounded_chunks(db_conn, seeded, monkeypatch):
    """With the chunk size forced to 1, every row still gets its department.

    This is the termination/coverage property: the walk advances strictly forward
    through the composite PK, so a table many chunks long is fully covered and the
    loop ends. A chunk size larger than the table would hide an off-by-one that
    skips a chunk boundary; forcing it to 1 makes every row a boundary.
    """
    module = _module()
    monkeypatch.setattr(module, "_CHUNK_ROWS", 1)
    conn = _sqlalchemy_conn(db_conn)
    try:
        module._backfill_department(conn)
        conn.commit()
    finally:
        conn.close()

    departments = _departments(db_conn)
    assert departments["with-dept-1"] == "Engineering"
    assert departments["with-dept-2"] == "Data Science"
