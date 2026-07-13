import json


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
        assert c.execute("PRAGMA user_version").fetchone()[0] == 3
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
        assert c.execute("PRAGMA user_version").fetchone()[0] == 3
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
