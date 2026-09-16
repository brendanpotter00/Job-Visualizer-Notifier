import json
import sqlite3

import pytest

from job_enricher.store import Store


def _job(jid, h="h1", source_id="greenhouse"):
    return {
        "job_listing_id": jid, "source_id": source_id, "title": "SWE",
        "company": "acme", "raw_location": "SF", "description_html": "<p>x</p>",
        "details_json": None, "content_hash": h,
    }


def test_enqueue_idempotent(store):
    ins, skip = store.enqueue_inbox([_job("1"), _job("2")])
    assert (ins, skip) == (2, 0)
    # re-enqueue unchanged, but still 'claimed' -> reinserted (not yet past claimed)
    store.record_clean("greenhouse", "1", "clean text")
    ins2, skip2 = store.enqueue_inbox([_job("1")])  # now cleaned + same hash -> skipped
    assert (ins2, skip2) == (0, 1)


def test_clean_and_classify_flow(store):
    store.enqueue_inbox([_job("1")])
    assert len(store.jobs_needing_clean()) == 1
    store.record_clean("greenhouse", "1", "clean")
    assert len(store.jobs_needing_clean()) == 0
    assert len(store.jobs_needing_classify()) == 1


def test_enqueue_persists_first_seen_at(store):
    job = _job("1")
    job["first_seen_at"] = "2026-07-12T18:00:00+00:00"
    store.enqueue_inbox([job])
    with store.connect() as c:
        row = c.execute("SELECT first_seen_at FROM inbox WHERE job_listing_id='1'").fetchone()
    assert row["first_seen_at"] == "2026-07-12T18:00:00+00:00"


def test_jobs_needing_classify_newest_first_nulls_last(store):
    # older, newer, and a legacy row with no recency signal
    old = _job("old", h="ho"); old["first_seen_at"] = "2026-01-01T00:00:00+00:00"
    new = _job("new", h="hn"); new["first_seen_at"] = "2026-07-12T00:00:00+00:00"
    legacy = _job("legacy", h="hl")  # no first_seen_at
    store.enqueue_inbox([old, legacy, new])
    for jid in ("old", "new", "legacy"):
        store.record_clean("greenhouse", jid, "clean")
    order = [r["job_listing_id"] for r in store.jobs_needing_classify()]
    # newest first_seen_at first, legacy (null recency) last
    assert order == ["new", "old", "legacy"]
    # the per-tick cap takes the newest rows
    assert [r["job_listing_id"] for r in store.jobs_needing_classify(limit=1)] == ["new"]


def test_empty_clean_description_pairs(store):
    store.enqueue_inbox([_job("has", h="h1"), _job("empty", h="h2"), _job("blank", h="h3")])
    store.record_clean("greenhouse", "has", "real description text")
    store.record_clean("greenhouse", "empty", "")
    store.record_clean("greenhouse", "blank", "   ")
    pairs = store.empty_clean_description_pairs(["has", "empty", "blank"])
    assert pairs == {("greenhouse", "empty"), ("greenhouse", "blank")}


def test_record_enrichment_and_unsent(store):
    store.enqueue_inbox([_job("1")])
    store.record_clean("greenhouse", "1", "clean")
    store.record_enrichment({
        "job_listing_id": "1", "source_id": "greenhouse", "category": "software_engineering",
        "level": "senior", "level_includes": json.dumps(["senior"]), "tags": json.dumps(["backend"]),
        "locations": json.dumps([]), "classify_confidence": 0.9, "classify_reasoning": "r",
        "taxonomy_version": "v1+abc",
    })
    assert len(store.enriched_unsent()) == 1
    assert len(store.enriched_unjudged()) == 1
    store.mark_sent([("greenhouse", "1")])
    assert len(store.enriched_unsent()) == 0
    with store.connect() as c:
        assert c.execute("SELECT status FROM inbox WHERE job_listing_id='1'").fetchone()["status"] == "sent"


def test_tick_counters(store):
    store.start_tick()
    store.bump_tick_counters(claimed=5, classified=3)
    store.bump_tick_counters(classified=2)
    t = store.latest_tick()
    assert t["claimed"] == 5 and t["classified"] == 5
    store.end_tick(status="ok")
    assert store.current_tick_id() is None


def test_record_judge_updates(store):
    store.enqueue_inbox([_job("1")])
    store.record_clean("greenhouse", "1", "clean")
    store.record_enrichment({
        "job_listing_id": "1", "source_id": "greenhouse", "category": "software_engineering",
        "level": "senior", "level_includes": "[]", "tags": "[]", "locations": "[]",
        "classify_confidence": 0.9, "classify_reasoning": "r", "taxonomy_version": "v1",
    })
    store.record_judge({
        "job_listing_id": "1", "source_id": "greenhouse", "category": "business_ops",
        "level": "senior", "level_includes": "[]", "tags": "[]", "locations": "[]",
        "judge_pass": False, "judge_confidence": 0.8, "judge_notes": "n", "needs_human": False,
    })
    assert len(store.enriched_unjudged()) == 0
    with store.connect() as c:
        row = c.execute("SELECT * FROM enrichments WHERE job_listing_id='1'").fetchone()
    assert row["category"] == "business_ops" and row["judged"] == 1


def _seed_enriched(store, jid="1", category="software_engineering", level="senior"):
    store.enqueue_inbox([_job(jid)])
    store.record_clean("greenhouse", jid, "clean")
    store.record_enrichment({
        "job_listing_id": jid, "source_id": "greenhouse", "category": category, "level": level,
        "level_includes": "[]", "tags": json.dumps(["backend"]), "locations": "[]",
        "classify_confidence": 0.9, "classify_reasoning": "r", "taxonomy_version": "v1",
    })


def test_record_judge_reopens_sent_row_on_facet_change(store):
    """E9: a post-send judge correction must clear sent_at + reset inbox status
    so the fix re-ships next tick."""
    _seed_enriched(store, "1", category="software_engineering")
    store.mark_sent([("greenhouse", "1")])
    assert store.enriched_unsent() == []  # shipped

    store.record_judge({
        "job_listing_id": "1", "source_id": "greenhouse", "category": "business_ops",
        "level": "senior", "level_includes": "[]", "tags": json.dumps(["backend"]),
        "locations": "[]", "judge_pass": False, "judge_confidence": 0.8,
        "judge_notes": "fix", "needs_human": False,
    })

    # correction re-opened for the next write-back
    reopened = [r["job_listing_id"] for r in store.enriched_unsent()]
    assert reopened == ["1"]
    with store.connect() as c:
        assert c.execute("SELECT status FROM inbox WHERE job_listing_id='1'").fetchone()["status"] == "enriched"


def test_record_judge_no_change_leaves_sent_row_sent(store):
    """A judge pass that changes nothing must NOT re-open an already-sent row."""
    _seed_enriched(store, "1", category="software_engineering")
    store.mark_sent([("greenhouse", "1")])
    store.record_judge({
        "job_listing_id": "1", "source_id": "greenhouse", "category": "software_engineering",
        "level": "senior", "level_includes": "[]", "tags": json.dumps(["backend"]),
        "locations": "[]", "judge_pass": True, "judge_confidence": 0.95,
        "judge_notes": None, "needs_human": False,
    })
    assert store.enriched_unsent() == []  # still sent — no stranded correction


# ---- composite identity (source_id, job_listing_id) -------------------------
def test_same_id_across_sources_are_distinct_rows(store):
    """JVN job ids are NOT globally unique: (src-a, X) and (src-b, X) must both
    survive enqueue and be independently enrichable/markable."""
    store.enqueue_inbox([
        _job("X", h="ha", source_id="src-a"),
        _job("X", h="hb", source_id="src-b"),
    ])
    rows = store.jobs_needing_clean()
    assert sorted(r["source_id"] for r in rows) == ["src-a", "src-b"]
    # second enqueue did NOT clobber the first row's content
    with store.connect() as c:
        hashes = {
            r["source_id"]: r["content_hash"]
            for r in c.execute("SELECT source_id, content_hash FROM inbox").fetchall()
        }
    assert hashes == {"src-a": "ha", "src-b": "hb"}

    for src in ("src-a", "src-b"):
        store.record_clean(src, "X", f"clean {src}")
        store.record_enrichment({
            "job_listing_id": "X", "source_id": src, "category": "software_engineering",
            "level": "mid", "level_includes": "[]", "tags": "[]", "locations": "[]",
            "classify_confidence": 0.9, "classify_reasoning": "r", "taxonomy_version": "v1",
        })
    assert len(store.enriched_unsent()) == 2
    store.mark_sent([("src-a", "X")])
    left = [(r["source_id"], r["job_listing_id"]) for r in store.enriched_unsent()]
    assert left == [("src-b", "X")]


def test_migration_v0_to_v1_preserves_data(tmp_path):
    """A v0 DB (bare job_listing_id PKs, no attempts/uuid/provenance columns)
    is rebuilt to v1 with all data intact and user_version stamped."""
    import sqlite3

    from job_enricher.store import Store

    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE inbox (
          job_listing_id TEXT PRIMARY KEY, source_id TEXT NOT NULL,
          title TEXT NOT NULL, company TEXT NOT NULL, raw_location TEXT,
          description_html TEXT, details_json TEXT, content_hash TEXT NOT NULL,
          claimed_at TEXT NOT NULL, cleaned_at TEXT, clean_description TEXT,
          status TEXT NOT NULL DEFAULT 'claimed'
            CHECK (status IN ('claimed','cleaned','enriched','sent','failed'))
        );
        CREATE TABLE enrichments (
          job_listing_id TEXT PRIMARY KEY, source_id TEXT NOT NULL,
          category TEXT, level TEXT, level_includes TEXT, tags TEXT, locations TEXT,
          classify_confidence REAL, classify_reasoning TEXT, taxonomy_version TEXT,
          judged INTEGER NOT NULL DEFAULT 0, judge_pass INTEGER,
          judge_confidence REAL, judge_notes TEXT,
          needs_human INTEGER NOT NULL DEFAULT 0,
          enriched_at TEXT NOT NULL, sent_at TEXT,
          FOREIGN KEY (job_listing_id) REFERENCES inbox(job_listing_id)
        );
        CREATE TABLE ticks (
          id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL,
          ended_at TEXT, status TEXT NOT NULL DEFAULT 'running',
          claimed INTEGER NOT NULL DEFAULT 0, cleaned INTEGER NOT NULL DEFAULT 0,
          classified INTEGER NOT NULL DEFAULT 0, judged INTEGER NOT NULL DEFAULT 0,
          corrected INTEGER NOT NULL DEFAULT 0, needs_human INTEGER NOT NULL DEFAULT 0,
          sent INTEGER NOT NULL DEFAULT 0, errors INTEGER NOT NULL DEFAULT 0,
          notes TEXT
        );
        CREATE TABLE stage_timings (
          id INTEGER PRIMARY KEY AUTOINCREMENT, tick_id INTEGER NOT NULL,
          stage TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT NOT NULL,
          duration_ms INTEGER NOT NULL, item_count INTEGER NOT NULL DEFAULT 0,
          retry_count INTEGER NOT NULL DEFAULT 0,
          FOREIGN KEY (tick_id) REFERENCES ticks(id)
        );
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
        INSERT INTO inbox VALUES ('1','greenhouse','SWE','acme','SF','<p>x</p>',NULL,'h1','t0','t1','clean','sent');
        INSERT INTO enrichments VALUES ('1','greenhouse','software_engineering','senior','[]','[]','[]',0.9,'r','v1+abc',1,1,0.9,NULL,0,'t2','t3');
        INSERT INTO ticks (started_at, ended_at, status, sent) VALUES ('t0','t4','ok',1);
        INSERT INTO meta VALUES ('heartbeat:last_poll_at','t0','t0');
        """
    )
    conn.commit()
    conn.close()

    store = Store(db_path=db)
    store.init_schema()  # migrates v0 -> v1 -> v2 -> v3
    store.init_schema()  # idempotent second run

    with store.connect() as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 4
        inbox = c.execute("SELECT * FROM inbox").fetchone()
        assert inbox["job_listing_id"] == "1" and inbox["attempts"] == 0
        # v3 column exists and defaults to NULL on a migrated row
        assert inbox["first_seen_at"] is None
        enr = c.execute("SELECT * FROM enrichments").fetchone()
        assert enr["category"] == "software_engineering"
        assert enr["pre_judge_category"] is None and enr["tick_id"] is None
        # v2 columns exist and default to NULL on a migrated row
        assert enr["classify_latency_ms"] is None
        assert enr["judge_reasoning"] is None and enr["judge_latency_ms"] is None
        # v3 column exists and defaults to 0 on a migrated row
        assert enr["title_only"] == 0
        tick = c.execute("SELECT * FROM ticks").fetchone()
        assert tick["uuid"] is None and tick["nulled_facets"] == 0
        assert c.execute("SELECT value FROM meta WHERE key='heartbeat:last_poll_at'").fetchone()[0] == "t0"
    # a new tick on the migrated DB gets a uuid; legacy rows get one on demand
    tid = store.start_tick()
    assert store.get_tick(tid)["uuid"]
    assert store.ensure_tick_uuid(1)  # backfills the legacy row
    assert store.get_tick(1)["uuid"]


def test_migration_v1_to_v2_adds_columns(tmp_path):
    """A v1-stamped DB (composite PKs, no reasoning/latency columns) gains the v2
    columns on init_schema — and guards crash-recovery: v0->v1 stamps 1, so a
    crash before v1->v2 re-runs the ALTERs rather than skipping them."""
    import sqlite3

    from job_enricher.store import Store

    db = tmp_path / "v1.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE inbox (
          job_listing_id TEXT NOT NULL, source_id TEXT NOT NULL, title TEXT NOT NULL,
          company TEXT NOT NULL, raw_location TEXT, description_html TEXT, details_json TEXT,
          content_hash TEXT NOT NULL, claimed_at TEXT NOT NULL, cleaned_at TEXT,
          clean_description TEXT, status TEXT NOT NULL DEFAULT 'claimed', attempts INTEGER DEFAULT 0,
          PRIMARY KEY (source_id, job_listing_id));
        CREATE TABLE enrichments (
          job_listing_id TEXT NOT NULL, source_id TEXT NOT NULL, category TEXT, level TEXT,
          level_includes TEXT, tags TEXT, locations TEXT, classify_confidence REAL,
          classify_reasoning TEXT, taxonomy_version TEXT, judged INTEGER DEFAULT 0,
          judge_pass INTEGER, judge_confidence REAL, judge_notes TEXT, needs_human INTEGER DEFAULT 0,
          pre_judge_category TEXT, pre_judge_level TEXT, pre_judge_tags TEXT, classify_model TEXT,
          judge_model TEXT, tick_id INTEGER, enriched_at TEXT NOT NULL, sent_at TEXT,
          PRIMARY KEY (source_id, job_listing_id));
        INSERT INTO inbox VALUES ('1','gh','SWE','acme','SF','<p>x</p>',NULL,'h1','t0','t1','clean','enriched',0);
        INSERT INTO enrichments (job_listing_id, source_id, category, level, enriched_at)
          VALUES ('1','gh','software_engineering','senior','t2');
        PRAGMA user_version = 1;
        """
    )
    conn.commit()
    conn.close()

    store = Store(db_path=db)
    store.init_schema()
    with store.connect() as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 4
        cols = {r["name"] for r in c.execute("PRAGMA table_info(enrichments)")}
        assert {"classify_latency_ms", "judge_reasoning", "judge_latency_ms", "title_only"} <= cols
        inbox_cols = {r["name"] for r in c.execute("PRAGMA table_info(inbox)")}
        assert "first_seen_at" in inbox_cols
        # existing data preserved
        assert c.execute("SELECT category FROM enrichments").fetchone()["category"] == "software_engineering"


def test_migration_v2_to_v3_is_idempotent(tmp_path):
    """Re-running init_schema on a v3 DB (columns already present) is a no-op —
    the _migrate_v2_to_v3 column-existence guards must not error on the ALTERs."""
    from job_enricher.store import Store, _migrate_v2_to_v3

    db = tmp_path / "v3.db"
    store = Store(db_path=db)
    store.init_schema()  # fresh -> v3 directly
    store.init_schema()  # second run: version already 3, no migration
    # calling the migration directly on an already-migrated DB is also a no-op
    with store.connect() as c:
        _migrate_v2_to_v3(c)
        cols = {r["name"] for r in c.execute("PRAGMA table_info(inbox)")}
        assert "first_seen_at" in cols
        enr_cols = {r["name"] for r in c.execute("PRAGMA table_info(enrichments)")}
        assert "title_only" in enr_cols


def test_reenrich_handshake_resets_sent_row(store):
    """An unchanged (same content_hash) re-hand of a 'sent' row is an explicit
    JVN re-enrich request — reset to 'claimed', drop the enrichment."""
    store.enqueue_inbox([_job("1")])
    store.record_clean("greenhouse", "1", "clean")
    store.record_enrichment({
        "job_listing_id": "1", "source_id": "greenhouse", "category": "software_engineering",
        "level": "mid", "level_includes": "[]", "tags": "[]", "locations": "[]",
        "classify_confidence": 0.9, "classify_reasoning": "r", "taxonomy_version": "v1",
    })
    store.mark_sent([("greenhouse", "1")])

    ins, skip = store.enqueue_inbox([_job("1")])  # same hash, status='sent'
    assert (ins, skip) == (1, 0)
    with store.connect() as c:
        row = c.execute("SELECT status, attempts FROM inbox WHERE job_listing_id='1'").fetchone()
        assert row["status"] == "claimed" and row["attempts"] == 0
        assert c.execute("SELECT COUNT(*) AS n FROM enrichments").fetchone()["n"] == 0


def test_failed_row_stays_failed_on_unchanged_rehand(store):
    """A terminal poison row must NOT resurrect via the TTL-reclaim loop."""
    store.enqueue_inbox([_job("1")])
    with store.connect() as c:
        c.execute("UPDATE inbox SET status='failed' WHERE job_listing_id='1'")
    ins, skip = store.enqueue_inbox([_job("1")])  # same hash
    assert (ins, skip) == (0, 1)
    with store.connect() as c:
        assert c.execute("SELECT status FROM inbox WHERE job_listing_id='1'").fetchone()["status"] == "failed"


def test_writeback_failure_attempts_and_terminal_failed(store):
    """Poison-row lifecycle: attempts increments per rejection; at the cap the
    row goes terminal 'failed' and drops out of enriched_unsent()."""
    _seed_enriched(store, "1")
    assert len(store.enriched_unsent()) == 1
    for i in range(1, 5):
        attempts, failed = store.record_writeback_failure("greenhouse", "1")
        assert (attempts, failed) == (i, False)
    attempts, failed = store.record_writeback_failure("greenhouse", "1")
    assert (attempts, failed) == (5, True)
    assert store.enriched_unsent() == []      # excluded from write-back
    assert store.enriched_unjudged() == []    # excluded from the judge queue
    with store.connect() as c:
        assert c.execute("SELECT status FROM inbox WHERE job_listing_id='1'").fetchone()["status"] == "failed"


def test_record_judge_snapshots_pre_judge_once(store):
    """Provenance: the FIRST judge merge snapshots the classify-stage labels;
    a second judge merge must not overwrite the snapshot."""
    _seed_enriched(store, "1", category="software_engineering", level="senior")
    store.record_judge({
        "job_listing_id": "1", "source_id": "greenhouse", "category": "business_ops",
        "level": "senior", "level_includes": "[]", "tags": json.dumps(["backend"]),
        "locations": "[]", "judge_pass": False, "judge_confidence": 0.9,
        "judge_notes": "fix", "needs_human": False, "judge_model": "opus",
    })
    with store.connect() as c:
        row = c.execute("SELECT * FROM enrichments WHERE job_listing_id='1'").fetchone()
    assert row["pre_judge_category"] == "software_engineering"
    assert row["pre_judge_level"] == "senior"
    assert json.loads(row["pre_judge_tags"]) == ["backend"]
    assert row["judge_model"] == "opus"

    # second judge pass: snapshot unchanged
    store.record_judge({
        "job_listing_id": "1", "source_id": "greenhouse", "category": "growth",
        "level": "senior", "level_includes": "[]", "tags": json.dumps(["backend"]),
        "locations": "[]", "judge_pass": False, "judge_confidence": 0.9,
        "judge_notes": "again", "needs_human": False, "judge_model": "opus",
    })
    with store.connect() as c:
        row = c.execute("SELECT * FROM enrichments WHERE job_listing_id='1'").fetchone()
    assert row["pre_judge_category"] == "software_engineering"


def test_reclassify_resets_pre_judge_snapshot(store):
    """A re-classify (record_enrichment upsert) resets judge fields AND the
    pre-judge snapshot — a fresh classification has no judge history."""
    _seed_enriched(store, "1")
    store.record_judge({
        "job_listing_id": "1", "source_id": "greenhouse", "category": "business_ops",
        "level": "senior", "level_includes": "[]", "tags": "[]", "locations": "[]",
        "judge_pass": False, "judge_confidence": 0.9, "judge_notes": "n", "needs_human": False,
    })
    store.record_enrichment({
        "job_listing_id": "1", "source_id": "greenhouse", "category": "growth",
        "level": "mid", "level_includes": "[]", "tags": "[]", "locations": "[]",
        "classify_confidence": 0.8, "classify_reasoning": "r2", "taxonomy_version": "v2",
        "classify_model": "sonnet",
    })
    with store.connect() as c:
        row = c.execute("SELECT * FROM enrichments WHERE job_listing_id='1'").fetchone()
    assert row["judged"] == 0 and row["judge_model"] is None
    assert row["pre_judge_category"] is None
    assert row["classify_model"] == "sonnet"


def test_record_enrichment_stamps_tick_id(store):
    tid = store.start_tick()
    _seed_enriched(store, "1")
    with store.connect() as c:
        row = c.execute("SELECT tick_id FROM enrichments WHERE job_listing_id='1'").fetchone()
    assert row["tick_id"] == tid


def test_start_tick_generates_uuid(store):
    tid = store.start_tick()
    tick = store.get_tick(tid)
    assert tick["uuid"] and len(tick["uuid"]) >= 32


def test_last_stage_event_at(store):
    store.start_tick()
    tick = store.latest_tick()
    assert store.last_stage_event_at() == tick["started_at"]
    store.record_stage_timing(
        "clean", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:05+00:00", 5000, item_count=3
    )
    assert store.last_stage_event_at() == "2026-01-01T00:00:05+00:00"


def test_delete_meta_round_trip(store):
    store.set_meta("classify:model", "sonnet")
    assert store.get_meta("classify:model") == "sonnet"
    store.delete_meta("classify:model")
    assert store.get_meta("classify:model") is None
    # deleting an absent key is a harmless no-op
    store.delete_meta("classify:model")
    assert store.get_meta("classify:model") is None


# --- v3 -> v4: the subcategory migration (ENR-ST-1) --------------------------

_V4_ENRICHMENT_COLS = [
    "subcategories",
    "subcategory_confidence",
    "subcategory_source",
    "subcategory_attempts",
    "pre_judge_subcategories",
    "subcategory_run_id",
    "subcategory_sent_at",
]
_V4_TICK_COLS = ["swe_classified", "swe_subcat_evaluated", "swe_subcategorized"]


def _build_v3_db(path):
    """A populated v3 DB (inbox + enrichments + ticks rows), stamped user_version=3."""
    import sqlite3

    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE inbox (
          job_listing_id TEXT NOT NULL, source_id TEXT NOT NULL, title TEXT NOT NULL,
          company TEXT NOT NULL, raw_location TEXT, description_html TEXT, details_json TEXT,
          content_hash TEXT NOT NULL, claimed_at TEXT NOT NULL, cleaned_at TEXT,
          clean_description TEXT, status TEXT NOT NULL DEFAULT 'claimed',
          attempts INTEGER DEFAULT 0, first_seen_at TEXT,
          PRIMARY KEY (source_id, job_listing_id));
        CREATE TABLE enrichments (
          job_listing_id TEXT NOT NULL, source_id TEXT NOT NULL, category TEXT, level TEXT,
          level_includes TEXT, tags TEXT, locations TEXT, classify_confidence REAL,
          classify_reasoning TEXT, classify_latency_ms INTEGER, taxonomy_version TEXT,
          judged INTEGER DEFAULT 0, judge_pass INTEGER, judge_confidence REAL,
          judge_notes TEXT, judge_reasoning TEXT, judge_latency_ms INTEGER,
          needs_human INTEGER DEFAULT 0, title_only INTEGER NOT NULL DEFAULT 0,
          pre_judge_category TEXT, pre_judge_level TEXT, pre_judge_tags TEXT,
          classify_model TEXT, judge_model TEXT, tick_id INTEGER,
          enriched_at TEXT NOT NULL, sent_at TEXT,
          PRIMARY KEY (source_id, job_listing_id));
        CREATE TABLE ticks (
          id INTEGER PRIMARY KEY AUTOINCREMENT, uuid TEXT, started_at TEXT NOT NULL,
          ended_at TEXT, status TEXT NOT NULL DEFAULT 'running',
          claimed INTEGER NOT NULL DEFAULT 0, cleaned INTEGER NOT NULL DEFAULT 0,
          classified INTEGER NOT NULL DEFAULT 0, judged INTEGER NOT NULL DEFAULT 0,
          corrected INTEGER NOT NULL DEFAULT 0, needs_human INTEGER NOT NULL DEFAULT 0,
          sent INTEGER NOT NULL DEFAULT 0, errors INTEGER NOT NULL DEFAULT 0,
          nulled_facets INTEGER NOT NULL DEFAULT 0, notes TEXT);
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
        INSERT INTO inbox VALUES
          ('1','gh','SWE','acme','SF','<p>x</p>',NULL,'h1','t0','t1','clean','enriched',0,NULL);
        INSERT INTO enrichments (job_listing_id, source_id, category, level, enriched_at)
          VALUES ('1','gh','software_engineering','senior','t2');
        INSERT INTO ticks (started_at, status) VALUES ('t0','ok');
        PRAGMA user_version = 3;
        """
    )
    conn.commit()
    conn.close()


def test_migration_v3_to_v4_adds_every_column_and_preserves_rows(tmp_path):
    from job_enricher.store import Store

    db = tmp_path / "v3.db"
    _build_v3_db(db)
    store = Store(db_path=db)
    store.init_schema()

    with store.connect() as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 4
        # BY NAME, all ten — a dropped column fails HERE loudly, not at 02:00.
        enr_cols = {r["name"] for r in c.execute("PRAGMA table_info(enrichments)")}
        for name in _V4_ENRICHMENT_COLS:
            assert name in enr_cols, name
        tick_cols = {r["name"] for r in c.execute("PRAGMA table_info(ticks)")}
        for name in _V4_TICK_COLS:
            assert name in tick_cols, name
        # both new tables land via _SCHEMA_SQL's CREATE TABLE IF NOT EXISTS
        tables = {
            r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {"backfill_runs", "backfill_scope"} <= tables
        assert "backfill_roster" not in tables
        # PRE-EXISTING ROWS: subcategories must be NULL (never evaluated -- the
        # backfill queue), NOT '[]' (which would mean evaluated + none apply and
        # would silently drain the queue before it ever filled).
        row = c.execute(
            "SELECT category, subcategories, subcategory_attempts FROM enrichments"
        ).fetchone()
        assert row["category"] == "software_engineering"
        assert row["subcategories"] is None
        assert row["subcategory_attempts"] == 0
        # both v4 indexes exist
        indexes = {
            r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index'")
        }
        assert "idx_enrichments_subcat_backlog" in indexes
        assert "idx_enrichments_subcat_push" in indexes


def test_migration_v3_to_v4_is_idempotent(tmp_path):
    from job_enricher.store import Store, _migrate_v3_to_v4

    db = tmp_path / "v3.db"
    _build_v3_db(db)
    store = Store(db_path=db)
    store.init_schema()
    store.init_schema()  # second run: already at 4, no migration
    with store.connect() as c:
        _migrate_v3_to_v4(c)  # calling it directly is also a no-op
        assert c.execute("PRAGMA user_version").fetchone()[0] == 4
        enr_cols = {r["name"] for r in c.execute("PRAGMA table_info(enrichments)")}
        assert set(_V4_ENRICHMENT_COLS) <= enr_cols
        assert c.execute("SELECT COUNT(*) FROM enrichments").fetchone()[0] == 1


class _FailOnNthAlter:
    """A connection proxy that raises on the Nth `ALTER TABLE`, simulating a
    mid-migration disk/lock failure. Everything else passes straight through, so
    `_migrate_v3_to_v4` runs its real BEGIN / ALTER / COMMIT / ROLLBACK path."""

    def __init__(self, conn, fail_on):
        self._conn = conn
        self._fail_on = fail_on
        self.alters = 0
        self.statements = []

    def execute(self, sql, *args):
        self.statements.append(sql)
        if sql.startswith("ALTER TABLE"):
            self.alters += 1
            if self.alters == self._fail_on:
                raise sqlite3.OperationalError("disk I/O error")
        return self._conn.execute(sql, *args)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_migration_v3_to_v4_rolls_back_a_mid_alter_failure(tmp_path):
    """⚠ THE FAILURE PATH OF A ONE-WAY MIGRATION. `_migrate_v3_to_v4` runs LIVE
    IN PROD inside `deploy.sh` step 6 with the worker parked, and `init_schema`
    has NO downgrade. If the ROLLBACK is broken or the exception is swallowed,
    prod is left half-migrated and NOTHING says so — the deploy reports success.

    The assertions are made on the SAME connection, deliberately: closing a
    connection with an open transaction auto-rolls-back, so a test that only
    re-opened the file would pass even with the ROLLBACK deleted."""
    import pytest

    from job_enricher.store import Store, _migrate_v3_to_v4

    db = tmp_path / "v3.db"
    _build_v3_db(db)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None          # manual transaction control, as init_schema does
    proxy = _FailOnNthAlter(conn, fail_on=4)

    # 1. the exception PROPAGATES — a swallowed one is a silent half-migration
    with pytest.raises(sqlite3.OperationalError):
        _migrate_v3_to_v4(proxy)

    # 2. some ALTERs really did run before the failure (the test is not vacuous)
    assert proxy.alters == 4
    # 3. the ROLLBACK actually executed: no transaction is left dangling
    assert conn.in_transaction is False
    # 4. ...and it UNDID the partial work — none of the v4 columns survive
    enr_cols = {r["name"] for r in conn.execute("PRAGMA table_info(enrichments)")}
    assert not (set(_V4_ENRICHMENT_COLS) & enr_cols)
    # 5. the DB is still consistent and still v3 — rows intact, version unmoved
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    row = conn.execute("SELECT category FROM enrichments").fetchone()
    assert row["category"] == "software_engineering"
    conn.close()

    # 6. and because it is still a CLEAN v3, the next deploy migrates it fully —
    #    a half-migrated DB would make this second run explode on a duplicate
    #    column instead.
    store = Store(db_path=db)
    store.init_schema()
    with store.connect() as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 4
        cols = {r["name"] for r in c.execute("PRAGMA table_info(enrichments)")}
        assert set(_V4_ENRICHMENT_COLS) <= cols
        tick_cols = {r["name"] for r in c.execute("PRAGMA table_info(ticks)")}
        assert set(_V4_TICK_COLS) <= tick_cols
        assert c.execute("SELECT COUNT(*) FROM enrichments").fetchone()[0] == 1


def test_migration_v3_to_v4_rolls_back_a_failure_on_the_TICKS_alters(tmp_path):
    """The ticks loop runs AFTER the enrichments loop, so a failure there has
    seven successful ALTERs to undo — the case where a broken rollback leaves the
    most damage."""
    from job_enricher.store import _migrate_v3_to_v4

    db = tmp_path / "v3.db"
    _build_v3_db(db)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None
    proxy = _FailOnNthAlter(conn, fail_on=9)   # 7 enrichment ALTERs, then ticks

    with pytest.raises(sqlite3.OperationalError):
        _migrate_v3_to_v4(proxy)

    assert conn.in_transaction is False
    enr_cols = {r["name"] for r in conn.execute("PRAGMA table_info(enrichments)")}
    tick_cols = {r["name"] for r in conn.execute("PRAGMA table_info(ticks)")}
    assert not (set(_V4_ENRICHMENT_COLS) & enr_cols)
    assert not (set(_V4_TICK_COLS) & tick_cols)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    conn.close()


def test_fresh_db_is_created_directly_at_v4_with_both_tables(tmp_path):
    from job_enricher.store import Store

    store = Store(db_path=tmp_path / "fresh.db")
    store.init_schema()
    with store.connect() as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 4
        enr_cols = {r["name"] for r in c.execute("PRAGMA table_info(enrichments)")}
        assert set(_V4_ENRICHMENT_COLS) <= enr_cols
        tick_cols = {r["name"] for r in c.execute("PRAGMA table_info(ticks)")}
        assert set(_V4_TICK_COLS) <= tick_cols
        tables = {
            r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {"backfill_runs", "backfill_scope"} <= tables


def test_backfill_runs_carries_the_full_ledger_shape(tmp_path):
    """One ledger, two lanes: `kind` ('label'|'push') and a SEPARATE
    `rubric_version` are what make the morning report readable from one table."""
    from job_enricher.store import Store

    store = Store(db_path=tmp_path / "fresh.db")
    store.init_schema()
    with store.connect() as c:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(backfill_runs)")}
    for name in (
        "kind", "rubric_version", "taxonomy_version", "deadline_at", "selected",
        "rule_labelled", "tag_labelled", "model_labelled", "empty_labelled",
        "nulled_slugs", "echo_mismatch", "unanswered", "transport_errors",
        "parse_errors", "errors", "retired", "model_calls", "pushed",
        "push_batches", "push_rejected", "push_skipped_human",
        "push_nulled_by_jvn", "pool_pressure_events", "aborted_reason", "notes",
    ):
        assert name in cols, name


def test_bump_tick_counters_increments_all_three_subcategory_counters(store):
    """THE TICK_COUNTER_COLS SILENT-DROP GUARD. bump_tick_counters filters its
    kwargs against that frozenset and drops unlisted keys WITHOUT ERROR, so this
    asserts the ticks ROW, never the return value."""
    tick_id = store.start_tick()
    store.bump_tick_counters(
        swe_classified=3, swe_subcat_evaluated=2, swe_subcategorized=1
    )
    with store.connect() as c:
        row = c.execute("SELECT * FROM ticks WHERE id = ?", (tick_id,)).fetchone()
    assert row["swe_classified"] == 3
    assert row["swe_subcat_evaluated"] == 2
    assert row["swe_subcategorized"] == 1


def test_operator_projections_carry_the_new_columns(store):
    store.enqueue_inbox([_job("1")])
    store.record_clean("greenhouse", "1", "clean")
    store.record_enrichment({
        "job_listing_id": "1", "source_id": "greenhouse",
        "category": "software_engineering", "level": "mid", "level_includes": "[]",
        "tags": "[]", "locations": "[]", "classify_confidence": 0.9,
        "classify_reasoning": "r", "taxonomy_version": "v1",
    })
    rows, _ = store.list_jobs()
    assert "subcategories" in rows[0]
    detail = store.job_detail("greenhouse", "1")
    for key in (
        "subcategories", "subcategory_confidence", "subcategory_source",
        "subcategory_attempts", "pre_judge_subcategories", "subcategory_sent_at",
    ):
        assert key in detail, key


# --- ENR-ST-2: subcategory persistence on the classify + judge paths ---------

def _swe(store, jid, **extra):
    store.enqueue_inbox([_job(jid)])
    store.record_clean("greenhouse", jid, "clean")
    payload = {
        "job_listing_id": jid, "source_id": "greenhouse",
        "category": "software_engineering", "level": "mid", "level_includes": "[]",
        "tags": "[]", "locations": "[]", "classify_confidence": 0.9,
        "classify_reasoning": "r", "taxonomy_version": "v7+abc",
    }
    payload.update(extra)
    store.record_enrichment(payload)


def _enr(store, jid):
    with store.connect() as c:
        return dict(
            c.execute("SELECT * FROM enrichments WHERE job_listing_id=?", (jid,)).fetchone()
        )


def test_record_enrichment_stores_the_three_tri_state_values(store):
    _swe(store, "1", subcategories='["backend"]', subcategory_confidence=0.8,
         subcategory_source="classify")
    _swe(store, "2", subcategories="[]", subcategory_confidence=None,
         subcategory_source="classify")
    _swe(store, "3")  # neither key supplied -> NULL, no source
    assert _enr(store, "1")["subcategories"] == '["backend"]'
    assert _enr(store, "1")["subcategory_source"] == "classify"
    assert _enr(store, "2")["subcategories"] == "[]"
    assert _enr(store, "3")["subcategories"] is None
    assert _enr(store, "3")["subcategory_source"] is None


def test_reclassify_overwrites_and_resets_attempts_and_pre_judge_snapshot(store):
    _swe(store, "1", subcategories='["backend"]', subcategory_source="classify")
    with store.connect() as c:
        c.execute(
            "UPDATE enrichments SET subcategory_attempts=4, "
            "pre_judge_subcategories='[\"frontend\"]' WHERE job_listing_id='1'"
        )
    _swe(store, "1", subcategories='["frontend"]', subcategory_source="classify")
    row = _enr(store, "1")
    assert row["subcategories"] == '["frontend"]'
    assert row["subcategory_attempts"] == 0
    assert row["pre_judge_subcategories"] is None


def test_record_judge_subcategory_only_change_reopens_a_sent_row(store):
    """THE STRANDED-CORRECTION REGRESSION. Without `subcategories` in the
    facet-changed comparison, `reopen` never fires and the fix never re-ships."""
    _swe(store, "1", subcategories='["backend"]', subcategory_source="classify")
    store.mark_sent([("greenhouse", "1")])
    store.record_judge({
        "job_listing_id": "1", "source_id": "greenhouse",
        "category": "software_engineering", "level": "mid", "level_includes": "[]",
        "tags": "[]", "locations": "[]", "subcategories": '["full_stack"]',
        "judge_pass": 0, "judge_confidence": 0.9,
    })
    row = _enr(store, "1")
    assert row["subcategories"] == '["full_stack"]'
    assert row["sent_at"] is None
    with store.connect() as c:
        status = c.execute(
            "SELECT status FROM inbox WHERE job_listing_id='1'"
        ).fetchone()["status"]
    assert status == "enriched"


def test_record_judge_no_change_leaves_a_sent_row_sent(store):
    _swe(store, "1", subcategories='["backend"]', subcategory_source="classify")
    store.mark_sent([("greenhouse", "1")])
    store.record_judge({
        "job_listing_id": "1", "source_id": "greenhouse",
        "category": "software_engineering", "level": "mid", "level_includes": "[]",
        "tags": "[]", "locations": "[]", "subcategories": '["backend"]',
        "judge_pass": 1, "judge_confidence": 0.9,
    })
    assert _enr(store, "1")["sent_at"] is not None


def test_first_judge_snapshots_pre_judge_subcategories(store):
    _swe(store, "1", subcategories='["backend"]', subcategory_source="classify")
    store.record_judge({
        "job_listing_id": "1", "source_id": "greenhouse",
        "category": "software_engineering", "level": "mid", "level_includes": "[]",
        "tags": "[]", "locations": "[]", "subcategories": '["full_stack"]',
        "judge_pass": 0, "judge_confidence": 0.9,
    })
    assert _enr(store, "1")["pre_judge_subcategories"] == '["backend"]'


# BF-8's `Store.record_subcategories` lands in PR-E. Until it exists there is no
# production write path to point a regression test at, and the test below is a
# PLACEHOLDER that must SAY SO. It used to issue a hand-written UPDATE naming
# only the three subcategory columns and then assert the judge columns were
# untouched — vacuously true, and green even if `record_subcategories` were
# deleted or written to wipe every judge column, i.e. green against exactly the
# regression it exists to catch.
#
# `strict=True` is the point: the day BF-8 lands, this stops being an expected
# failure and either passes for real or reports the regression. An XPASS also
# fails the suite, so the marker cannot be left behind.
_HAS_RECORD_SUBCATEGORIES = hasattr(Store, "record_subcategories")


@pytest.mark.xfail(
    condition=not _HAS_RECORD_SUBCATEGORIES,
    strict=True,
    reason=(
        "PENDING BF-8 (PR-E): Store.record_subcategories does not exist yet. "
        "This is a placeholder, not a passing guard — do NOT satisfy it with a "
        "hand-written UPDATE that names only the columns it then asserts are "
        "unchanged."
    ),
)
def test_a_backfill_subcategory_write_must_not_wipe_judge_state(store):
    """CONTRAST WITH record_enrichment, which deliberately DOES reset the judge
    fields (a re-classify invalidates a judge verdict). BF-8's
    `record_subcategories` is an ADDITIVE facet write on an already-correct row;
    wiping judge state there would re-queue the whole cohort for judging.

    The expectation is pinned HERE, beside the reset behaviour it contrasts
    with (`ENR-ST-2`), but it is asserted against BF-8's REAL METHOD — never
    against a stand-in UPDATE, which cannot fail.

    ⚠ If BF-8 lands a different call signature, fix the CALL below. Do not
    replace it with raw SQL: that is how this test became a tautology.
    """
    _swe(store, "1", subcategories=None)
    store.record_judge({
        "job_listing_id": "1", "source_id": "greenhouse",
        "category": "software_engineering", "level": "senior", "level_includes": "[]",
        "tags": "[]", "locations": "[]", "subcategories": None,
        "judge_pass": 1, "judge_confidence": 0.77, "judge_notes": "ok",
    })
    before = _enr(store, "1")
    store.record_subcategories([{
        "source_id": "greenhouse", "job_listing_id": "1",
        "subcategories": '["backend"]', "subcategory_confidence": 0.7,
        "subcategory_source": "backfill",
    }])
    after = _enr(store, "1")
    for key in (
        "judged", "judge_pass", "judge_confidence", "judge_notes",
        "pre_judge_category", "pre_judge_level", "pre_judge_tags",
    ):
        assert after[key] == before[key], key
    assert after["subcategories"] == '["backend"]'
    assert after["subcategory_source"] == "backfill"


# --- P0-3: the un-fail path (an abandoned chunk is no longer silent) --------

def test_record_classify_failure_bumps_attempts_on_every_row(store):
    store.enqueue_inbox([_job("1"), _job("2")])
    store.record_clean("greenhouse", "1", "clean")
    store.record_clean("greenhouse", "2", "clean")
    failed = store.record_classify_failure(
        [("greenhouse", "1"), ("greenhouse", "2")], max_attempts=5
    )
    assert failed == []
    with store.connect() as c:
        rows = {
            r["job_listing_id"]: r["attempts"]
            for r in c.execute("SELECT job_listing_id, attempts FROM inbox")
        }
    assert rows == {"1": 1, "2": 1}


def test_row_goes_terminal_at_max_attempts_and_leaves_the_classify_queue(store):
    store.enqueue_inbox([_job("1")])
    store.record_clean("greenhouse", "1", "clean")
    for _ in range(2):
        assert store.record_classify_failure([("greenhouse", "1")], max_attempts=3) == []
    assert store.record_classify_failure([("greenhouse", "1")], max_attempts=3) == [
        ("greenhouse", "1")
    ]
    assert [r["job_listing_id"] for r in store.jobs_needing_classify()] == []


def test_a_successful_chunk_leaves_attempts_alone(store):
    store.enqueue_inbox([_job("1")])
    store.record_clean("greenhouse", "1", "clean")
    store.record_enrichment({
        "job_listing_id": "1", "source_id": "greenhouse",
        "category": "software_engineering", "level": "mid", "level_includes": "[]",
        "tags": "[]", "locations": "[]", "classify_confidence": 0.9,
        "classify_reasoning": "r", "taxonomy_version": "v1",
    })
    with store.connect() as c:
        assert c.execute("SELECT attempts FROM inbox").fetchone()["attempts"] == 0


def test_unfail_returns_terminal_rows_to_the_queue(store):
    store.enqueue_inbox([_job("1")])
    store.record_clean("greenhouse", "1", "clean")
    store.record_classify_failure([("greenhouse", "1")], max_attempts=1)
    assert store.jobs_needing_classify() == []
    assert store.unfail() == 1
    with store.connect() as c:
        row = c.execute("SELECT status, attempts FROM inbox").fetchone()
    assert (row["status"], row["attempts"]) == ("cleaned", 0)
    assert len(store.jobs_needing_classify()) == 1


def test_unfail_sends_an_uncleaned_row_back_to_claimed(store):
    store.enqueue_inbox([_job("1")])
    store.record_classify_failure([("greenhouse", "1")], max_attempts=1)
    assert store.unfail() == 1
    with store.connect() as c:
        assert c.execute("SELECT status FROM inbox").fetchone()["status"] == "claimed"


def test_starved_null_recency_counts_only_cleaned_rows_with_no_recency(store):
    store.enqueue_inbox([_job("1"), _job("2")])
    store.record_clean("greenhouse", "1", "clean")
    store.record_clean("greenhouse", "2", "clean")
    with store.connect() as c:
        c.execute("UPDATE inbox SET first_seen_at='2026-08-01' WHERE job_listing_id='1'")
    assert store.starved_null_recency() == 1


# --- P0-4: the OPEN-only backfill scope -------------------------------------

def test_import_backfill_scope_is_idempotent_and_reports_matched_local(store):
    _swe(store, "1")  # exists locally
    imported, matched = store.import_backfill_scope(
        [("greenhouse", "1"), ("greenhouse", "999")]
    )
    assert (imported, matched) == (2, 1)  # 999 is JVN-side only
    # re-running changes nothing but the timestamp
    assert store.import_backfill_scope([("greenhouse", "1"), ("greenhouse", "999")]) == (2, 1)


def test_backfill_scope_age_is_none_when_empty(store):
    assert store.backfill_scope_age_hours() is None


def test_backfill_scope_age_is_fresh_right_after_an_import(store):
    store.import_backfill_scope([("greenhouse", "1")])
    age = store.backfill_scope_age_hours()
    assert age is not None and age < 1.0


# --- P0-7: the rehearsal script's contract ----------------------------------

def test_rehearse_script_uses_backup_not_cp_and_checks_all_ten_columns():
    """A text guard on the rehearsal harness itself. `cp` of a WAL DB silently
    drops the -wal sibling, so the copy you rehearse on is not the database you
    have — and a rehearsal that checks five of the ten columns proves nothing."""
    from pathlib import Path

    script = (
        Path(__file__).resolve().parents[1] / "scripts" / "rehearse_v4_migration.sh"
    ).read_text(encoding="utf-8")
    assert '.backup' in script
    for name in _V4_ENRICHMENT_COLS + _V4_TICK_COLS:
        assert name in script, name
    assert "backfill_runs" in script and "backfill_scope" in script
    assert "integrity_check" in script
    assert "MIGRATION_V3_V4_SECONDS" in script
    assert "> 30" in script          # the split decision rule
    assert "ROLLBACK ARTIFACT" in script   # v3->v4 is a one-way door
