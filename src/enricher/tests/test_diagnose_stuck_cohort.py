"""P0-1 — the read-only diagnostic harness.

Two things are actually load-bearing here and both are asserted:
  1. the connection is PROVABLY read-only (the script aborts if `PRAGMA
     query_only` does not read back 1), and
  2. it never constructs `Store()` — `Store.init_schema()` WRITES, so opening the
     live prod DB through the normal class would mutate it.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "diagnose_stuck_cohort.py"


def _load():
    spec = importlib.util.spec_from_file_location("diagnose_stuck_cohort", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


diag = _load()


def _v3_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE inbox (
          job_listing_id TEXT NOT NULL, source_id TEXT NOT NULL, title TEXT NOT NULL,
          company TEXT NOT NULL, raw_location TEXT, description_html TEXT,
          details_json TEXT, content_hash TEXT NOT NULL, first_seen_at TEXT,
          claimed_at TEXT NOT NULL, cleaned_at TEXT, clean_description TEXT,
          status TEXT NOT NULL DEFAULT 'claimed', attempts INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY (source_id, job_listing_id));
        CREATE TABLE enrichments (
          job_listing_id TEXT NOT NULL, source_id TEXT NOT NULL, category TEXT,
          enriched_at TEXT NOT NULL,
          PRIMARY KEY (source_id, job_listing_id));
        CREATE TABLE ticks (
          id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL,
          ended_at TEXT, status TEXT, claimed INTEGER DEFAULT 0,
          cleaned INTEGER DEFAULT 0, classified INTEGER DEFAULT 0,
          judged INTEGER DEFAULT 0, errors INTEGER DEFAULT 0);
        INSERT INTO inbox VALUES ('1','gh','SWE','a','SF','<p>x</p>',NULL,'h1','2026-08-01','t','t','c','cleaned',0);
        INSERT INTO inbox VALUES ('2','gh','SWE','a','SF','<p>x</p>',NULL,'h2',NULL,'t','t','c','cleaned',0);
        INSERT INTO inbox VALUES ('3','gh','SWE','a','SF','<p>x</p>',NULL,'h3',NULL,'t','t','c','failed',3);
        INSERT INTO enrichments VALUES ('1','gh','software_engineering','t');
        INSERT INTO ticks (started_at, status, classified, errors) VALUES ('t','ok',38,0);
        INSERT INTO ticks (started_at, status, classified, errors) VALUES ('t','ok',40,0);
        PRAGMA user_version = 3;
        """
    )
    conn.commit()
    conn.close()


def test_report_shape(tmp_path):
    db = tmp_path / "v3.db"
    _v3_db(db)
    conn = diag.open_read_only(db)
    try:
        report = diag.collect_report(conn, per_tick_limit=40)
    finally:
        conn.close()

    assert report["schema_version"] == 3
    assert report["inbox_by_status"] == {"cleaned": 2, "failed": 1}
    assert report["cleaned_total"] == 2
    assert report["starved_null_recency"] == 1
    assert report["starved_null_recency_ratio"] == 0.5
    assert "REPORT ONLY" in report["starved_null_recency_action"]
    assert report["enrichments_by_category"] == {"software_engineering": 1}
    assert report["failed_rows"] == 1
    # H1: one tick at 38/40 with errors=0 is the silent-abandonment fingerprint;
    # the tick at 40/40 is not.
    assert report["h1_silent_abandonment_ticks"] == 1
    assert report["h1_rows_lost_estimate"] == 2
    assert report["subcategory_backlog"] == "n/a (schema is pre-v4)"


def test_read_only_connection_refuses_writes(tmp_path):
    db = tmp_path / "v3.db"
    _v3_db(db)
    conn = diag.open_read_only(db)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("UPDATE inbox SET status='claimed'")
    finally:
        conn.close()


def test_open_read_only_aborts_when_query_only_cannot_be_set(tmp_path, monkeypatch):
    """The abort is the whole point: a connection that merely *tried* to be
    read-only is not evidence of anything."""

    class _FakeCur:
        def fetchone(self):
            return (0,)   # query_only reads back 0 -> the pragma did not take

    class _LyingConn:
        row_factory = None

        def execute(self, sql, *a):
            return _FakeCur()

        def close(self):
            pass

    monkeypatch.setattr(diag.sqlite3, "connect", lambda *a, **kw: _LyingConn())
    with pytest.raises(RuntimeError, match="provably read-only"):
        diag.open_read_only(tmp_path / "anything.db")


def test_missing_db_exits_non_zero(tmp_path, capsys):
    assert diag.main(["--db", str(tmp_path / "nope.db")]) == 2


def test_main_prints_every_section(tmp_path, capsys):
    db = tmp_path / "v3.db"
    _v3_db(db)
    assert diag.main(["--db", str(db)]) == 0
    out = capsys.readouterr()
    for section in (
        "inbox_by_status", "starved_null_recency", "enrichments_by_category",
        "recent_ticks", "h1_silent_abandonment_ticks", "attempts_histogram",
        "subcategory_backlog",
    ):
        assert section in out.out, section
    # 50% NULL-recency is above the 10% escalation ratio -> the STOP notice fires
    assert "STOP" in out.err


def test_script_never_constructs_store():
    """Store.init_schema() WRITES (store.py:219 journal_mode, :232 user_version),
    so this script must not import or construct it at all. Asserted over the
    PARSED module, so the docstring that explains the rule cannot satisfy it."""
    import ast

    tree = ast.parse(_SCRIPT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "job_enricher"
        ):
            raise AssertionError(f"imports {node.module}")
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("job_enricher"), alias.name
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "Store"


def test_the_live_db_is_provably_unmodified(tmp_path):
    """Run the whole report and assert the file bytes are byte-identical after."""
    import hashlib

    db = tmp_path / "v3.db"
    _v3_db(db)
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    assert diag.main(["--db", str(db)]) == 0
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
