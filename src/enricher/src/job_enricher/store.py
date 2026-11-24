"""SQLite store for the enricher pipeline.

Port of job-watcher's connection contract (WAL set once in init_schema;
foreign_keys + busy_timeout set on every connection; row_factory=Row; commit on
clean exit, rollback on exception). The schema is enrichment-specific:

  inbox        rows the laptop has PULLED from JVN and not yet fully enriched
  enrichments  the per-job enrichment result (category/level/tags/locations +
               judge verdict + provenance), the durable artifact written
               between waves and the source for write-back to JVN
  ticks        one row per /enrich-tick run (durability + observability)
  stage_timings per-(tick, stage) latency + counts (feeds the metrics surface)
  meta         key/value runtime knobs + heartbeat (read fresh each tick)

Identity is the COMPOSITE (source_id, job_listing_id) pair everywhere — JVN
documents that job ids are NOT globally unique across sources, so both inbox
and enrichments key on the pair (schema v1). ``PRAGMA user_version`` tracks the
schema version; ``init_schema`` migrates v0 (bare job_listing_id keys) in one
transaction (rebuild + data copy), preserving WAL + the per-connection FK
pragma behavior.

Integrity is enforced at the app layer; the FKs are enrichments(source_id,
job_listing_id) -> inbox (a result always has a claimed job behind it) and
stage_timings.tick_id -> ticks (a timing always belongs to a tick).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid as uuid_mod
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]


def monorepo_root(repo_root: Path) -> Path:
    """The enricher lives at <JVN>/src/enricher, so the JVN monorepo root is two
    levels up. Outside the monorepo (a bare copy of src/enricher) that path holds
    no JVN files and callers that read from it must say so; a copy too close to
    ``/`` to have two parents gets ``repo_root`` itself rather than an import-time
    IndexError that would take every CLI command down with it."""
    parents = repo_root.parents
    return parents[1] if len(parents) > 1 else repo_root


JVN_ROOT = monorepo_root(REPO_ROOT)
DEFAULT_DB_PATH = REPO_ROOT / "data" / "enricher.db"

# meta keys
HEARTBEAT_KEY = "heartbeat:last_poll_at"
CURRENT_TICK_KEY = "current_tick_id"
LAST_SCORECARD_HASH_KEY = "metrics:last_scorecard_hash"

# The one category subcategories may hang off. Mirrors taxonomy.SUBCATEGORY_PARENT;
# duplicated as a literal here so store.py stays import-free of the taxonomy
# module (which reads files at import time). ENR-PAR-1 asserts the two match.
SUBCATEGORY_PARENT_CATEGORY = "software_engineering"

SCHEMA_VERSION = 4

# poison-row lifecycle: after this many per-row JVN rejections the inbox row is
# moved to the terminal 'failed' status (excluded from every queue + write-back)
MAX_WRITEBACK_ATTEMPTS = 5


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS inbox (
  job_listing_id   TEXT NOT NULL,
  source_id        TEXT NOT NULL,
  title            TEXT NOT NULL,
  company          TEXT NOT NULL,
  raw_location     TEXT,
  description_html TEXT,
  details_json     TEXT,
  content_hash     TEXT NOT NULL,
  -- v3: the job's posting-recency signal from JVN (first_seen_at, ISO). Ordered
  -- DESC (nulls last) by the clean/classify queues so the local pipeline honors
  -- JVN's newest-first claim order instead of local FIFO. NULL on pre-v3 rows.
  first_seen_at    TEXT,
  claimed_at       TEXT NOT NULL,
  cleaned_at       TEXT,
  clean_description TEXT,
  status           TEXT NOT NULL DEFAULT 'claimed'
                     CHECK (status IN ('claimed','cleaned','enriched','sent','failed')),
  attempts         INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (source_id, job_listing_id)
);

CREATE INDEX IF NOT EXISTS idx_inbox_status ON inbox(status);
CREATE INDEX IF NOT EXISTS idx_inbox_content_hash ON inbox(content_hash);

CREATE TABLE IF NOT EXISTS enrichments (
  job_listing_id   TEXT NOT NULL,
  source_id        TEXT NOT NULL,
  category         TEXT,
  level            TEXT,
  level_includes   TEXT,        -- JSON array
  tags             TEXT,        -- JSON array
  locations        TEXT,        -- JSON array, byte-compatible with JVN _LOCATIONS_SCHEMA
  classify_confidence REAL,
  classify_reasoning  TEXT,
  classify_latency_ms INTEGER,  -- v2: per-item wall time of the classify call
  taxonomy_version TEXT,
  judged           INTEGER NOT NULL DEFAULT 0,
  judge_pass       INTEGER,     -- 1 pass / 0 corrected-or-judge-failed / NULL not judged
  judge_confidence REAL,
  judge_notes      TEXT,
  judge_reasoning  TEXT,        -- v2: the judge's "why" (fuller than the terse notes)
  judge_latency_ms INTEGER,     -- v2: per-item wall time of the judge call
  needs_human      INTEGER NOT NULL DEFAULT 0,
  -- v3: this row was classified from title+company+location alone because the
  -- source captured no description (a low-confidence STOPGAP label). Local-only
  -- marker for finding the cohort to re-enrich once real descriptions land; not
  -- sent to JVN.
  title_only       INTEGER NOT NULL DEFAULT 0,
  -- provenance (schema v1): pre-judge snapshot taken ONCE before the first
  -- judge merge, plus which models/tick produced the row
  pre_judge_category TEXT,
  pre_judge_level    TEXT,
  pre_judge_tags     TEXT,      -- JSON array
  classify_model     TEXT,
  judge_model        TEXT,
  tick_id            INTEGER,
  enriched_at      TEXT NOT NULL,
  sent_at          TEXT,
  -- v4: SWE sub-specialties. subcategories is a JSON array and is TRI-STATE:
  --   NULL = never evaluated  -- THIS IS THE BACKFILL QUEUE
  --   '[]' = evaluated, no specialty applies -- TERMINAL, never re-queued
  --   '["backend"]' = labelled, ORDERED, index 0 primary, MAX 2
  -- The NULL/'[]' distinction is load-bearing and must never be collapsed.
  subcategories          TEXT,
  subcategory_confidence REAL,
  -- one of taxonomy.SUBCATEGORY_SOURCES (rule|classify|backfill|judge|human):
  -- the only thing that makes a rollback scoped instead of nuclear, and the
  -- only way to tell the compact-rubric classify lane's labels apart from the
  -- full-rubric backfill lane's.
  subcategory_source     TEXT,
  subcategory_attempts   INTEGER NOT NULL DEFAULT 0,
  pre_judge_subcategories TEXT,   -- JSON array; mirrors the pre_judge_* trio above
  subcategory_run_id     INTEGER, -- NULL = not written by a backfill run; scopes rollback to ONE run
  subcategory_sent_at    TEXT,    -- NULL = this row's subcategory has not shipped to JVN (D2's drain walks this)
  PRIMARY KEY (source_id, job_listing_id),
  FOREIGN KEY (source_id, job_listing_id) REFERENCES inbox(source_id, job_listing_id)
);

CREATE INDEX IF NOT EXISTS idx_enrichments_unsent
  ON enrichments(sent_at) WHERE sent_at IS NULL;

-- v4: the backfill selector's (category, attempts) predicate over the NULL queue.
CREATE INDEX IF NOT EXISTS idx_enrichments_subcat_backlog
  ON enrichments(category, subcategory_attempts) WHERE subcategories IS NULL;

-- v4: D2's throttled drain — labelled rows that have not shipped to JVN yet.
CREATE INDEX IF NOT EXISTS idx_enrichments_subcat_push
  ON enrichments(subcategory_sent_at) WHERE subcategories IS NOT NULL AND subcategory_sent_at IS NULL;

CREATE TABLE IF NOT EXISTS ticks (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  uuid          TEXT,
  started_at    TEXT NOT NULL,
  ended_at      TEXT,
  status        TEXT NOT NULL DEFAULT 'running',
  claimed       INTEGER NOT NULL DEFAULT 0,
  cleaned       INTEGER NOT NULL DEFAULT 0,
  classified    INTEGER NOT NULL DEFAULT 0,
  judged        INTEGER NOT NULL DEFAULT 0,
  corrected     INTEGER NOT NULL DEFAULT 0,
  needs_human   INTEGER NOT NULL DEFAULT 0,
  sent          INTEGER NOT NULL DEFAULT 0,
  errors        INTEGER NOT NULL DEFAULT 0,
  nulled_facets INTEGER NOT NULL DEFAULT 0,
  -- v4: subcategory coverage per tick. All THREE are in TICK_COUNTER_COLS
  -- below; bump_tick_counters SILENTLY DROPS any key absent from that frozenset,
  -- so omitting one makes the drift breaker read 0 forever with no error.
  swe_classified       INTEGER NOT NULL DEFAULT 0,  -- rows recorded as software_engineering
  swe_subcat_evaluated INTEGER NOT NULL DEFAULT 0,  -- of those, subcategories non-NULL (INCLUDING [])
  swe_subcategorized   INTEGER NOT NULL DEFAULT 0,  -- of those, the list is non-empty
  notes         TEXT
);

CREATE INDEX IF NOT EXISTS idx_ticks_started ON ticks(started_at);

CREATE TABLE IF NOT EXISTS stage_timings (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  tick_id     INTEGER NOT NULL,
  stage       TEXT NOT NULL,       -- 'clean'|'classify'|'judge'|'writeback'
  started_at  TEXT NOT NULL,
  ended_at    TEXT NOT NULL,
  duration_ms INTEGER NOT NULL,
  item_count  INTEGER NOT NULL DEFAULT 0,
  retry_count INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY (tick_id) REFERENCES ticks(id)
);

CREATE INDEX IF NOT EXISTS idx_stage_timings_tick ON stage_timings(tick_id);

CREATE TABLE IF NOT EXISTS meta (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- v4: ONE ledger, TWO lanes. `kind` is 'label' (the model run) or 'push' (the
-- throttled drain to JVN), so the morning report reads one table. `taxonomy_version`
-- and `rubric_version` are stamped SEPARATELY: without the second stamp a run
-- cannot prove which rubric produced its labels.
-- Created here, NOT in _migrate_v3_to_v4: init_schema runs the ladder and THEN
-- executescript(_SCHEMA_SQL), and every table here is CREATE TABLE IF NOT EXISTS,
-- so a new TABLE lands identically on a fresh DB and on an upgraded one. Only
-- new COLUMNS on existing tables need ALTERs.
CREATE TABLE IF NOT EXISTS backfill_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  uuid TEXT,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  status TEXT NOT NULL DEFAULT 'running',
  kind TEXT NOT NULL DEFAULT 'label',
  engine TEXT,
  model TEXT,
  taxonomy_version TEXT,
  rubric_version TEXT,
  deadline_at TEXT,
  selected INTEGER NOT NULL DEFAULT 0,
  rule_labelled INTEGER NOT NULL DEFAULT 0,
  tag_labelled INTEGER NOT NULL DEFAULT 0,
  model_labelled INTEGER NOT NULL DEFAULT 0,
  empty_labelled INTEGER NOT NULL DEFAULT 0,
  nulled_slugs INTEGER NOT NULL DEFAULT 0,
  echo_mismatch INTEGER NOT NULL DEFAULT 0,
  unanswered INTEGER NOT NULL DEFAULT 0,
  transport_errors INTEGER NOT NULL DEFAULT 0,
  parse_errors INTEGER NOT NULL DEFAULT 0,
  errors INTEGER NOT NULL DEFAULT 0,
  retired INTEGER NOT NULL DEFAULT 0,
  model_calls INTEGER NOT NULL DEFAULT 0,
  pushed INTEGER NOT NULL DEFAULT 0,
  push_batches INTEGER NOT NULL DEFAULT 0,
  push_rejected INTEGER NOT NULL DEFAULT 0,
  push_skipped_human INTEGER NOT NULL DEFAULT 0,
  push_nulled_by_jvn INTEGER NOT NULL DEFAULT 0,
  pool_pressure_events INTEGER NOT NULL DEFAULT 0,
  aborted_reason TEXT,
  notes TEXT
);

-- v4: the point-in-time OPEN-SWE scope imported from JVN (P0-4). There is
-- exactly ONE scope table; `backfill_roster` does not exist and must not appear.
CREATE TABLE IF NOT EXISTS backfill_scope (
  source_id TEXT NOT NULL,
  job_listing_id TEXT NOT NULL,
  imported_at TEXT NOT NULL,
  PRIMARY KEY (source_id, job_listing_id)
);
"""

# bump_tick_counters filters counters.items() against this set and SILENTLY
# DROPS anything absent — a counter missing from here is a metric that reads 0
# forever with no error anywhere. All three v4 names are here deliberately.
TICK_COUNTER_COLS = frozenset(
    {
        "claimed", "cleaned", "classified", "judged", "corrected",
        "needs_human", "sent", "errors", "nulled_facets",
        "swe_classified", "swe_subcat_evaluated", "swe_subcategorized",
    }
)

# The `backfill_runs` counter columns `bump_backfill_counters` may increment.
# Same silent-drop SHAPE as _TICK_COUNTER_COLS above, but DELIBERATELY NOT the
# same silent BEHAVIOUR: a dropped key here LOGS A WARNING. The tick version's
# silence is the exact trap this workstream keeps hitting (a counter absent from
# the frozenset reads 0 forever with no error anywhere), so the newer of the two
# is loud on purpose.
_BACKFILL_COUNTER_COLS = frozenset(
    {
        "selected", "rule_labelled", "tag_labelled", "model_labelled",
        "empty_labelled", "nulled_slugs", "echo_mismatch", "unanswered",
        "transport_errors", "parse_errors", "errors", "retired", "model_calls",
        "pushed", "push_batches", "push_rejected", "push_skipped_human",
        "push_nulled_by_jvn", "pool_pressure_events",
    }
)

# `backfill_runs.kind` — ONE ledger, TWO lanes, so the morning report reads one
# table: 'label' is BF-9's model run, 'push' is BF-12b's throttled drain.
BACKFILL_RUN_KINDS: frozenset[str] = frozenset({"label", "push"})

# ⚠ The scope is a POINT-IN-TIME export of JVN's OPEN-SWE jobs, and jobs open and
# close overnight. `--open-only` REFUSES on a scope older than this (or an empty
# one) rather than returning []: a silently-empty scope table makes --open-only a
# no-op that reports success, and a stale scope is a WRONG scope.
SCOPE_MAX_AGE_HOURS = 24


class ScopeUnavailableError(RuntimeError):
    """`open_only` was requested but `backfill_scope` is empty or stale.

    Raised rather than returning [] so the caller exits 2. Returning an empty
    list here would make the whole night's run a successful no-op."""

# v0 column lists (kept verbatim for the rebuild data copy)
_V0_INBOX_COLS = (
    "job_listing_id, source_id, title, company, raw_location, description_html, "
    "details_json, content_hash, claimed_at, cleaned_at, clean_description, status"
)
_V0_ENRICHMENTS_COLS = (
    "job_listing_id, source_id, category, level, level_includes, tags, locations, "
    "classify_confidence, classify_reasoning, taxonomy_version, judged, judge_pass, "
    "judge_confidence, judge_notes, needs_human, enriched_at, sent_at"
)


class Store:
    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Yield a Connection with row_factory=Row, foreign_keys=ON,
        busy_timeout=5000ms. Commit on clean exit, rollback on exception."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self) -> None:
        """Idempotent. Run on every CLI startup. WAL is a one-shot persisted
        setting (concurrent readers + single writer = the tick + serve pattern).

        Schema versions are tracked with ``PRAGMA user_version``: a fresh DB is
        created directly at the current version; an existing v0 DB (bare
        job_listing_id primary keys, pre-composite-identity) is migrated with a
        table rebuild + data copy inside ONE transaction."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.isolation_level = None  # manual transaction control for the rebuild
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA busy_timeout = 5000")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            has_inbox = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='inbox'"
            ).fetchone() is not None
            if version < 1 and has_inbox:
                _migrate_v0_to_v1(conn)
            if version < 2 and has_inbox:
                _migrate_v1_to_v2(conn)
            if version < 3 and has_inbox:
                _migrate_v2_to_v3(conn)
            if version < 4 and has_inbox:
                _migrate_v3_to_v4(conn)
            conn.executescript(_SCHEMA_SQL)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        finally:
            conn.close()

    # ---- meta knobs -------------------------------------------------------
    def set_meta(self, key: str, value: str, ts: str | None = None) -> None:
        when = ts or now_iso()
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO meta (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                "updated_at = excluded.updated_at",
                (key, value, when),
            )

    def get_meta(self, key: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row is not None else None

    def delete_meta(self, key: str) -> None:
        """Remove a meta row so its enrich_config getter falls back to the committed
        default. Deleting an absent key is a harmless no-op."""
        with self.connect() as conn:
            conn.execute("DELETE FROM meta WHERE key = ?", (key,))

    def all_meta(self) -> dict[str, str]:
        with self.connect() as conn:
            rows = conn.execute("SELECT key, value FROM meta").fetchall()
        return {r["key"]: r["value"] for r in rows}

    def heartbeat(self, ts: str | None = None) -> None:
        self.set_meta(HEARTBEAT_KEY, ts or now_iso())

    # ---- inbox ------------------------------------------------------------
    def enqueue_inbox(self, jobs: Iterable[dict[str, Any]]) -> tuple[int, int]:
        """Upsert claimed jobs. Returns (inserted, skipped_unchanged).

        Idempotent on the composite (source_id, job_listing_id) pair:
        - a re-claim of an unchanged job (same content_hash) that is mid-flight
          ('cleaned'/'enriched') is left untouched so we don't redo work;
        - an unchanged job whose row is terminal 'failed' stays failed (a
          poison row must not resurrect itself via the TTL-reclaim loop);
        - an unchanged job whose row is 'sent' is an EXPLICIT JVN re-enrich
          request (JVN only re-hands sent work after an admin reset): the row
          resets to 'claimed', its enrichment is deleted, and the pipeline
          reruns from clean (the re-queue trap fix);
        - a changed job resets to 'claimed' (attempts cleared)."""
        inserted = 0
        skipped = 0
        ts = now_iso()
        with self.connect() as conn:
            for j in jobs:
                key = (j["source_id"], j["job_listing_id"])
                existing = conn.execute(
                    "SELECT content_hash, status FROM inbox "
                    "WHERE source_id = ? AND job_listing_id = ?",
                    key,
                ).fetchone()
                if existing is not None and existing["content_hash"] == j["content_hash"]:
                    if existing["status"] in ("cleaned", "enriched", "failed"):
                        skipped += 1
                        continue
                    if existing["status"] == "sent":
                        # Explicit re-enrich handshake: drop the stale result so
                        # record_enrichment starts fresh, then reset below.
                        conn.execute(
                            "DELETE FROM enrichments "
                            "WHERE source_id = ? AND job_listing_id = ?",
                            key,
                        )
                        logger.info(
                            "enqueue_inbox: JVN re-handed sent row (source_id=%s, "
                            "job_listing_id=%s) with unchanged content — treating as "
                            "an explicit re-enrich request (reset to 'claimed')",
                            key[0], key[1],
                        )
                conn.execute(
                    "INSERT INTO inbox (job_listing_id, source_id, title, company, "
                    "raw_location, description_html, details_json, content_hash, "
                    "first_seen_at, claimed_at, status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'claimed') "
                    "ON CONFLICT(source_id, job_listing_id) DO UPDATE SET "
                    "title=excluded.title, "
                    "company=excluded.company, raw_location=excluded.raw_location, "
                    "description_html=excluded.description_html, "
                    "details_json=excluded.details_json, content_hash=excluded.content_hash, "
                    "first_seen_at=excluded.first_seen_at, "
                    "claimed_at=excluded.claimed_at, cleaned_at=NULL, "
                    "clean_description=NULL, status='claimed', attempts=0",
                    (
                        j["job_listing_id"], j["source_id"], j["title"], j["company"],
                        j.get("raw_location"), j.get("description_html"),
                        j.get("details_json"), j["content_hash"], j.get("first_seen_at"), ts,
                    ),
                )
                inserted += 1
        return inserted, skipped

    def jobs_needing_clean(self, limit: int | None = None) -> list[sqlite3.Row]:
        # Newest posting first (first_seen_at DESC), pre-v3/legacy null-recency
        # rows last, claimed_at as a stable tiebreak — mirrors JVN's claim order
        # so the local pipeline stays newest-first instead of local FIFO.
        sql = (
            "SELECT * FROM inbox WHERE status = 'claimed' "
            "ORDER BY first_seen_at IS NULL, first_seen_at DESC, claimed_at"
        )
        params: tuple[Any, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        with self.connect() as conn:
            return conn.execute(sql, params).fetchall()

    def record_clean(self, source_id: str, job_listing_id: str, clean_description: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE inbox SET clean_description = ?, cleaned_at = ?, status = 'cleaned' "
                "WHERE source_id = ? AND job_listing_id = ?",
                (clean_description, now_iso(), source_id, job_listing_id),
            )

    def jobs_needing_classify(self, limit: int | None = None) -> list[sqlite3.Row]:
        # Newest posting first (see jobs_needing_clean): the per-tick cap only
        # takes `limit` rows, so this ORDER BY decides WHICH rows get labelled
        # while fresh. cleaned_at is the stable tiebreak within a first_seen_at.
        sql = (
            "SELECT * FROM inbox WHERE status = 'cleaned' "
            "ORDER BY first_seen_at IS NULL, first_seen_at DESC, cleaned_at"
        )
        params: tuple[Any, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        with self.connect() as conn:
            return conn.execute(sql, params).fetchall()

    def inbox_sources_by_id(self, job_listing_ids: list[str]) -> dict[str, list[str]]:
        """Map job_listing_id -> ALL source_ids that claim it. Used to resolve
        (or refuse to guess) the composite identity when an agent echoes only
        the bare id back."""
        ids = [i for i in job_listing_ids if i]
        if not ids:
            return {}
        ph = ",".join("?" for _ in ids)
        out: dict[str, list[str]] = {}
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT job_listing_id, source_id FROM inbox "
                f"WHERE job_listing_id IN ({ph})",
                ids,
            ).fetchall()
        for r in rows:
            out.setdefault(r["job_listing_id"], []).append(r["source_id"])
        return out

    def empty_clean_description_pairs(
        self, job_listing_ids: list[str]
    ) -> set[tuple[str, str]]:
        """Return the (source_id, job_listing_id) pairs among `job_listing_ids`
        whose inbox row has an empty cleaned description — i.e. the source
        captured no description, so the classification is title-only. Used to
        mark those rows low-confidence at record time (a code-level guarantee
        that doesn't rely on the classify agent honoring the taxonomy guidance)."""
        ids = [i for i in job_listing_ids if i]
        if not ids:
            return set()
        ph = ",".join("?" for _ in ids)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT source_id, job_listing_id FROM inbox "
                f"WHERE job_listing_id IN ({ph}) "
                f"AND (clean_description IS NULL OR TRIM(clean_description) = '')",
                ids,
            ).fetchall()
        return {(r["source_id"], r["job_listing_id"]) for r in rows}

    # ---- enrichments (durable artifact) ----------------------------------
    def record_enrichment(self, e: dict[str, Any]) -> None:
        """Idempotent upsert of a classify result. Marks inbox row 'enriched'.

        `needs_human` is carried through (defaults 0) so the ingest slug
        validator can flag a row whose category/level was a hallucination
        without shipping the bad slug (E4). Provenance: `classify_model` comes
        from the caller (the active knob) and `tick_id` is stamped from meta
        current_tick_id at record time; a re-classify resets the judge fields
        AND the pre-judge snapshot (a fresh classification has no judge yet)."""
        needs_human = 1 if e.get("needs_human") else 0
        title_only = 1 if e.get("title_only") else 0
        tick_id = self.current_tick_id()
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO enrichments (job_listing_id, source_id, category, level, "
                "level_includes, tags, locations, classify_confidence, classify_reasoning, "
                "classify_latency_ms, taxonomy_version, needs_human, title_only, classify_model, "
                "subcategories, subcategory_confidence, subcategory_source, "
                "tick_id, enriched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(source_id, job_listing_id) DO UPDATE SET "
                "category=excluded.category, level=excluded.level, "
                "level_includes=excluded.level_includes, tags=excluded.tags, "
                "locations=excluded.locations, "
                "classify_confidence=excluded.classify_confidence, "
                "classify_reasoning=excluded.classify_reasoning, "
                "classify_latency_ms=excluded.classify_latency_ms, "
                "taxonomy_version=excluded.taxonomy_version, "
                "classify_model=excluded.classify_model, tick_id=excluded.tick_id, "
                "enriched_at=excluded.enriched_at, "
                "judged=0, judge_pass=NULL, judge_confidence=NULL, judge_notes=NULL, "
                "judge_reasoning=NULL, judge_latency_ms=NULL, "
                "judge_model=NULL, pre_judge_category=NULL, pre_judge_level=NULL, "
                "pre_judge_tags=NULL, "
                "subcategories=excluded.subcategories, "
                "subcategory_confidence=excluded.subcategory_confidence, "
                "subcategory_source=excluded.subcategory_source, "
                # A re-classify is a FRESH evaluation: the attempt count resets
                # and the pre-judge snapshot clears alongside the pre_judge_*
                # resets just above. ⚠ BF-8 item 6: `subcategory_run_id` and
                # `subcategory_sent_at` reset TOO. The new value did not come
                # from a backfill run (so the run stamp is a lie that would make
                # BF-14's scoped rollback reset a row it never wrote), and it has
                # not shipped to JVN (so a stale `subcategory_sent_at` would make
                # BF-12b's drain skip the fresh label FOREVER — the cursor is
                # exactly that column).
                "subcategory_attempts=0, pre_judge_subcategories=NULL, "
                "subcategory_run_id=NULL, subcategory_sent_at=NULL, "
                "needs_human=excluded.needs_human, title_only=excluded.title_only, "
                "sent_at=NULL",
                (
                    e["job_listing_id"], e["source_id"], e.get("category"), e.get("level"),
                    e.get("level_includes"), e.get("tags"), e.get("locations"),
                    e.get("classify_confidence"), e.get("classify_reasoning"),
                    e.get("classify_latency_ms"),
                    e.get("taxonomy_version"), needs_human, title_only, e.get("classify_model"),
                    e.get("subcategories"), e.get("subcategory_confidence"),
                    e.get("subcategory_source"),
                    tick_id, now_iso(),
                ),
            )
            conn.execute(
                "UPDATE inbox SET status = 'enriched' "
                "WHERE source_id = ? AND job_listing_id = ?",
                (e["source_id"], e["job_listing_id"]),
            )

    def record_judge(self, j: dict[str, Any]) -> None:
        """Apply a judge verdict in place (corrections already merged into the
        category/level/tags/locations fields by the caller).

        ⚠ The caller (`cli._merge_judge`) supplies `subcategories` TOGETHER with
        `subcategory_confidence` and `subcategory_source`; all three are written
        in one statement. A caller that omits them NULLs all three, which is the
        correct reading of "this verdict carries no subcategory answer".

        Provenance: on the FIRST judge merge for a row (judged still 0) the
        current classify-stage category/level/tags are snapshotted into the
        pre_judge_* columns so judge deltas stay reconstructable; `judge_model`
        is stamped from the caller.

        If the verdict CHANGES a shipped facet (category/level/level_includes/
        tags/locations/subcategories) on a row that was ALREADY written back (`sent_at` set),
        the correction is stranded unless we re-open it: clear `sent_at` and put
        the inbox row back to 'enriched' so the fix re-ships next tick (E9). A
        judge pass that changes nothing on a sent row leaves it sent."""
        jid = j["job_listing_id"]
        sid = j["source_id"]
        with self.connect() as conn:
            cur = conn.execute(
                "SELECT category, level, level_includes, tags, locations, "
                "subcategories, sent_at, judged "
                "FROM enrichments WHERE source_id = ? AND job_listing_id = ?",
                (sid, jid),
            ).fetchone()
            facet_changed = cur is not None and (
                cur["category"] != j.get("category")
                or cur["level"] != j.get("level")
                or cur["level_includes"] != j.get("level_includes")
                or cur["tags"] != j.get("tags")
                or cur["locations"] != j.get("locations")
                # WITHOUT THIS CLAUSE a subcategory-only judge correction on an
                # already-sent row is STRANDED: `reopen` never fires, `sent_at`
                # is never cleared, and the fix never re-ships.
                or cur["subcategories"] != j.get("subcategories")
            )
            reopen = facet_changed and cur is not None and cur["sent_at"] is not None
            first_judge = cur is not None and not cur["judged"]
            snapshot_sql = ""
            snapshot_params: tuple[Any, ...] = ()
            if first_judge:
                snapshot_sql = (
                    ", pre_judge_category=?, pre_judge_level=?, pre_judge_tags=?, "
                    "pre_judge_subcategories=?"
                )
                snapshot_params = (
                    cur["category"], cur["level"], cur["tags"], cur["subcategories"]
                )
            conn.execute(
                # ⚠ subcategory_confidence AND subcategory_source are written in
                # the SAME statement as subcategories. They used to be omitted
                # here, which left two corrupt states behind every judge pass:
                #   * a stale confidence measured against a label the judge just
                #     replaced (or that RAIL D just forced to `[]` — the row kept
                #     ('[]', 0.91, 'classify'), which contract 1.2 A forbids), and
                #   * a source still reading 'classify' after the judge overwrote
                #     the label, so a rollback scoped to the classify lane reverts
                #     the wrong rows.
                # `_merge_judge` computes both (it is the only place that knows
                # the stored label AND the merged one); persisting them apart from
                # the array is what made the corruption possible.
                "UPDATE enrichments SET category=?, level=?, level_includes=?, tags=?, "
                "locations=?, subcategories=?, subcategory_confidence=?, "
                "subcategory_source=?, "
                "judged=1, judge_pass=?, judge_confidence=?, judge_notes=?, "
                "judge_reasoning=?, judge_latency_ms=?, "
                "judge_model=?, needs_human=?" + snapshot_sql
                + (", sent_at=NULL" if reopen else "") + " "
                "WHERE source_id = ? AND job_listing_id = ?",
                (
                    j.get("category"), j.get("level"), j.get("level_includes"),
                    j.get("tags"), j.get("locations"), j.get("subcategories"),
                    j.get("subcategory_confidence"), j.get("subcategory_source"),
                    1 if j.get("judge_pass") else 0,
                    j.get("judge_confidence"), j.get("judge_notes"),
                    j.get("judge_reasoning"), j.get("judge_latency_ms"),
                    j.get("judge_model"),
                    1 if j.get("needs_human") else 0, *snapshot_params, sid, jid,
                ),
            )
            if reopen:
                conn.execute(
                    "UPDATE inbox SET status = 'enriched' "
                    "WHERE source_id = ? AND job_listing_id = ?",
                    (sid, jid),
                )
                logger.info(
                    "record_judge: re-opened already-sent (source_id=%s, "
                    "job_listing_id=%s) (post-send facet correction will re-ship "
                    "next tick)", sid, jid,
                )

    def enriched_unjudged(self, limit: int | None = None) -> list[sqlite3.Row]:
        """Unjudged enrichments joined to their inbox row (composite key) so the
        judge queue has title/company/raw_location/clean_description without an
        ambiguous bare-id lookup. Terminal 'failed' rows are excluded."""
        sql = (
            "SELECT e.*, i.title AS title, i.company AS company, "
            "i.raw_location AS raw_location, i.clean_description AS clean_description "
            "FROM enrichments e JOIN inbox i "
            "ON i.source_id = e.source_id AND i.job_listing_id = e.job_listing_id "
            "WHERE e.judged = 0 AND i.status != 'failed' ORDER BY e.enriched_at"
        )
        params: tuple[Any, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        with self.connect() as conn:
            return conn.execute(sql, params).fetchall()

    def enriched_unsent(self, limit: int | None = None) -> list[sqlite3.Row]:
        """Unsent enrichments joined to inbox (clean_description + raw_location
        ride along for the write-back payload). Terminal 'failed' rows (poison
        rows past MAX_WRITEBACK_ATTEMPTS) are excluded so one bad row can't
        error every tick forever."""
        sql = (
            "SELECT e.*, i.clean_description AS clean_description, "
            "i.raw_location AS raw_location "
            "FROM enrichments e JOIN inbox i "
            "ON i.source_id = e.source_id AND i.job_listing_id = e.job_listing_id "
            "WHERE e.sent_at IS NULL AND i.status != 'failed' ORDER BY e.enriched_at"
        )
        params: tuple[Any, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        with self.connect() as conn:
            return conn.execute(sql, params).fetchall()

    def mark_sent(self, pairs: Iterable[tuple[str, str]]) -> None:
        """Mark rows sent, keyed by (source_id, job_listing_id) pairs.

        ⚠ BF-8 item 5: this ALSO stamps `subcategory_sent_at`, but only when the
        row's `subcategories` is non-NULL **AND** the
        `writeback:send_subcategories` knob is ON. The knob condition is
        load-bearing and easy to miss: with the knob OFF `_row_to_result` OMITS
        the field entirely, so stamping anyway would mark live-lane rows as
        pushed when nothing was ever sent — and BF-12b's drain, whose cursor IS
        this column, would skip them forever."""
        from job_enricher import enrich_config as ec

        ts = now_iso()
        send_subcategories = ec.get_writeback_send_subcategories(self)
        with self.connect() as conn:
            for sid, jid in pairs:
                if send_subcategories:
                    conn.execute(
                        "UPDATE enrichments SET sent_at = ?, "
                        "subcategory_sent_at = CASE WHEN subcategories IS NOT NULL "
                        "THEN ? ELSE subcategory_sent_at END "
                        "WHERE source_id = ? AND job_listing_id = ?",
                        (ts, ts, sid, jid),
                    )
                else:
                    conn.execute(
                        "UPDATE enrichments SET sent_at = ? "
                        "WHERE source_id = ? AND job_listing_id = ?",
                        (ts, sid, jid),
                    )
                conn.execute(
                    "UPDATE inbox SET status = 'sent' "
                    "WHERE source_id = ? AND job_listing_id = ?",
                    (sid, jid),
                )

    def record_writeback_failure(
        self, source_id: str, job_listing_id: str,
        max_attempts: int = MAX_WRITEBACK_ATTEMPTS,
    ) -> tuple[int, bool]:
        """Bump inbox.attempts after a per-row JVN failed[] rejection. At
        `max_attempts` the row becomes terminal status='failed' (excluded from
        all queues + write-back; visible in `cli health`). Returns
        (attempts_now, now_failed)."""
        with self.connect() as conn:
            conn.execute(
                "UPDATE inbox SET attempts = attempts + 1 "
                "WHERE source_id = ? AND job_listing_id = ?",
                (source_id, job_listing_id),
            )
            row = conn.execute(
                "SELECT attempts FROM inbox WHERE source_id = ? AND job_listing_id = ?",
                (source_id, job_listing_id),
            ).fetchone()
            attempts = int(row["attempts"]) if row is not None else 0
            now_failed = attempts >= max_attempts
            if now_failed:
                conn.execute(
                    "UPDATE inbox SET status = 'failed' "
                    "WHERE source_id = ? AND job_listing_id = ?",
                    (source_id, job_listing_id),
                )
                logger.error(
                    "write-back: poison row (source_id=%s, job_listing_id=%s) hit "
                    "%d rejections — moved to terminal status='failed'",
                    source_id, job_listing_id, attempts,
                )
        return attempts, now_failed

    def record_classify_failure(
        self, pairs: list[tuple[str, str]],
        max_attempts: int = MAX_WRITEBACK_ATTEMPTS,
    ) -> list[tuple[str, str]]:
        """THE MISSING UN-FAIL PATH (P0-3). Bump inbox.attempts on every row of a
        chunk an engine call abandoned, and flip the row terminal at
        `max_attempts`.

        WITHOUT THIS, an engine timeout is a SILENT capacity leak: `_cmd_classify_run`
        catches EngineError and `continue`s, so the chunk is skipped, `errors` is
        never bumped, `inbox.attempts` is never touched, and the tick still closes
        `status=ok / errors=0` — the same rows are re-claimed and re-abandoned
        every tick forever. Mirrors record_writeback_failure's shape.

        Returns the pairs that went terminal on THIS call. `cli unfail` brings
        them back."""
        newly_failed: list[tuple[str, str]] = []
        if not pairs:
            return newly_failed
        with self.connect() as conn:
            for sid, jid in pairs:
                conn.execute(
                    "UPDATE inbox SET attempts = attempts + 1 "
                    "WHERE source_id = ? AND job_listing_id = ?",
                    (sid, jid),
                )
                row = conn.execute(
                    "SELECT attempts, status FROM inbox "
                    "WHERE source_id = ? AND job_listing_id = ?",
                    (sid, jid),
                ).fetchone()
                if row is None:
                    continue
                if int(row["attempts"]) >= max_attempts and row["status"] != "failed":
                    conn.execute(
                        "UPDATE inbox SET status = 'failed' "
                        "WHERE source_id = ? AND job_listing_id = ?",
                        (sid, jid),
                    )
                    newly_failed.append((sid, jid))
                    logger.error(
                        "classify: poison row (source_id=%s, job_listing_id=%s) hit "
                        "%d abandoned chunks — moved to terminal status='failed'",
                        sid, jid, int(row["attempts"]),
                    )
        return newly_failed

    def unfail(self, limit: int | None = None) -> int:
        """Return terminal 'failed' rows to the queue: status back to 'cleaned'
        (or 'claimed' when there is no clean_description yet) and attempts to 0.

        A terminal row is a JUDGEMENT, not a fact — the cause may have been a
        transient engine outage. Without a way back, `status='failed'` is a
        one-way drain on the corpus."""
        sql = "SELECT source_id, job_listing_id, clean_description FROM inbox WHERE status='failed'"
        params: tuple[Any, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            for r in rows:
                status = "cleaned" if r["clean_description"] else "claimed"
                conn.execute(
                    "UPDATE inbox SET status = ?, attempts = 0 "
                    "WHERE source_id = ? AND job_listing_id = ?",
                    (status, r["source_id"], r["job_listing_id"]),
                )
        return len(rows)

    def starved_null_recency(self) -> int:
        """Rows stuck at 'cleaned' with no posting-recency signal. They sort LAST
        forever (jobs_needing_classify's ORDER BY at :360), so behind a queue
        longer than the per-tick limit they are never reached.

        SURFACED, NOT REPAIRED — both candidate remedies change the live tick's
        claim order (or corrupt a provenance column), and r11 declined an order
        change. See docs/RUNBOOK-subcategory-backfill.md §2.3."""
        with self.connect() as conn:
            return int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM inbox "
                    "WHERE status='cleaned' AND first_seen_at IS NULL"
                ).fetchone()["n"]
            )

    # ---- backfill scope (P0-4) --------------------------------------------
    def import_backfill_scope(self, pairs: list[tuple[str, str]]) -> tuple[int, int]:
        """Idempotent upsert of the OPEN-SWE scope on the composite key.

        Returns (imported, matched_local) where `matched_local` is how many of
        the imported pairs the local enrichments table actually has — that number
        is `PARAM_BACKFILL_DENOMINATOR` and replaces the 8,126 placeholder
        everywhere downstream, INCLUDING the 90% coverage gate."""
        ts = now_iso()
        with self.connect() as conn:
            for sid, jid in pairs:
                conn.execute(
                    "INSERT INTO backfill_scope (source_id, job_listing_id, imported_at) "
                    "VALUES (?, ?, ?) "
                    "ON CONFLICT(source_id, job_listing_id) DO UPDATE SET "
                    "imported_at=excluded.imported_at",
                    (sid, jid, ts),
                )
            imported = int(
                conn.execute("SELECT COUNT(*) AS n FROM backfill_scope").fetchone()["n"]
            )
            matched = int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM backfill_scope s JOIN enrichments e "
                    "ON e.source_id = s.source_id AND e.job_listing_id = s.job_listing_id"
                ).fetchone()["n"]
            )
        return imported, matched

    def backfill_scope_age_hours(self) -> float | None:
        """Hours since the NEWEST scope row was imported, or None when empty."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT MAX(imported_at) AS newest FROM backfill_scope"
            ).fetchone()
        if row is None or row["newest"] is None:
            return None
        try:
            imported = datetime.fromisoformat(row["newest"])
        except ValueError:
            return None
        if imported.tzinfo is None:
            imported = imported.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - imported).total_seconds() / 3600.0

    # ---- subcategory write path (ENR-ST-2 base + BF-8's backfill concerns) -
    def record_subcategories(
        self,
        source_id: str,
        job_listing_id: str,
        subcategories: list[str] | None,
        confidence: float | None = None,
        source: str | None = None,
        run_id: int | None = None,
        bump_attempt: bool = True,
    ) -> None:
        """Write ONE row's subcategory facet. An ADDITIVE write, nothing else.

        `subcategories` is the tri-state: ``None`` stays the backfill queue,
        ``[]`` is stored as the literal ``'[]'`` and is TERMINAL, a 1-2 element
        list is a label. `confidence` is forced to NULL whenever the array is
        empty or NULL — a confidence with no label behind it poisons calibration
        on the far side.

        ⚠ INVARIANT 1 — THIS METHOD NEVER TOUCHES `sent_at` OR `inbox.status`,
        and it has NO `reopen` parameter at all. The draft's `reopen=True`
        variant is DELETED along with the re-open drain it served. Clearing
        `sent_at` puts the row back into `enriched_unsent()`, which takes
        `limit=None`, and `_row_to_result` carries the full `clean_description`
        — an unconditional re-open of the 11,144 already-sent prod SWE rows is
        ~163 batches of full descriptions at Railway inside ONE tick.

        ⚠ INVARIANT 2 — THIS METHOD NEVER TOUCHES ANY JUDGE OR `pre_judge_*`
        COLUMN. A subcategory is an ADDITIVE facet, unlike `record_enrichment`,
        which deliberately resets them all because a re-classification has no
        judge yet.

        `run_id` stamps `subcategory_run_id`, which is what makes BF-14's
        rollback scoped to ONE run instead of all-or-nothing. `bump_attempt` is
        True by default so the selector always advances (see
        `rows_needing_subcategory`'s anti-spin note)."""
        value = None if subcategories is None else json.dumps(list(subcategories))
        conf = confidence if subcategories else None
        with self.connect() as conn:
            conn.execute(
                "UPDATE enrichments SET subcategories = ?, "
                "subcategory_confidence = ?, subcategory_source = ?, "
                "subcategory_run_id = ?, "
                "subcategory_attempts = subcategory_attempts + ? "
                "WHERE source_id = ? AND job_listing_id = ?",
                (
                    value, conf, source, run_id, 1 if bump_attempt else 0,
                    source_id, job_listing_id,
                ),
            )

    def record_subcategory_failure(
        self, source_id: str, job_listing_id: str
    ) -> None:
        """⚠ THE PARSE-FAILURE DISPOSITION: bump `subcategory_attempts` ONLY and
        leave `subcategories` NULL.

        This is the highest-value distinction in the write path. An explicit
        `[]` from the model is a LEGITIMATE TERMINAL ANSWER — evaluated, no
        specialty applies — and it removes the row from the queue permanently. A
        FAILURE (unparseable output, an unanswered row, an echo mismatch, a row
        whose every slug was invalid) must stay NULL so the row is retried and,
        at the cap, retired VISIBLY. Writing `[]` on a failure is the silent
        corruption this lane exists to avoid."""
        with self.connect() as conn:
            conn.execute(
                "UPDATE enrichments "
                "SET subcategory_attempts = subcategory_attempts + 1 "
                "WHERE source_id = ? AND job_listing_id = ?",
                (source_id, job_listing_id),
            )

    # ---- subcategory backlog selector (ENR-ST-2 base + BF-4's edits) ------
    def rows_needing_subcategory(
        self,
        limit: int | None = None,
        max_attempts: int = 3,
        open_only: bool = False,
    ) -> list[sqlite3.Row]:
        """SWE rows whose `subcategories` is still NULL — THE BACKFILL QUEUE.

        Joined to inbox so the caller has title/company beside the enrichment's
        tags. `clean_description` is deliberately NOT selected: the row handed to
        the prompt builder must have nowhere to put a description (see
        `backfill.chunk_rows`).

        ⚠ TWO PREDICATES ARE DELIBERATELY ABSENT, and the decision record
        (docs/plans/2026-08-20-swe-subcategories.md) overturns both. Do not
        restore them:

          (a) `title_only = 0` — the record replaces "those rows can never be
              labelled" with "title-first labels 1,081 of them; 747 remain". The
              title_only SWE rows are precisely where the free rule pass pays.
          (b) `clean_description IS NOT NULL AND TRIM(...) <> ''` — the backfill
              prompt NEVER reads a description (the injection boundary, made
              structural in `backfill.chunk_rows`), so requiring one is both
              pointless and re-excludes the same cohort.

        ⚠ KEPT AND DELIBERATE: `i.status IN ('sent','enriched')` excludes the
        terminal 'failed' rows and the ~262-row 'cleaned' cohort that is
        mid-reclassification. Note the direction — this EXCLUDES the poison
        cohort rather than being BLOCKED by it. The discarded `SEL-1` design
        vetoed the whole run while `classify_deferred > 0`, which would have
        emitted an empty manifest forever, silently.

        ⚠ THERE ARE NO CLAIM SEMANTICS, deliberately. Single-flight is BF-9's
        `.backfill.lock`; a written row stops being NULL, so re-running the
        selector after each chunk advances with no OFFSET, no claim column and no
        checkpoint.

        ⚠ THAT IS TRUE ONLY OF THE REAL RUN. A `--dry-run` writes nothing, so
        nothing here retires and this selector returns the SAME head every pass;
        `backfill.run_backfill` carries its own in-memory cursor and over-fetches
        by its size to page past it. See the DRY-RUN PAGING note there.

        ⚠ THAT IS ONLY SAFE BECAUSE `subcategory_attempts` IS BUMPED ON FAILURE
        TOO (`record_subcategory_failure`). Without the failure bump a
        permanently-failing row is re-selected forever and the loop spins in
        place while reporting progress."""
        if open_only:
            reason = self.scope_refusal_reason()
            if reason is not None:
                raise ScopeUnavailableError(reason)
        sql = (
            "SELECT e.*, i.title AS title, i.company AS company, "
            "i.first_seen_at AS first_seen_at "
            "FROM enrichments e JOIN inbox i "
            "ON i.source_id = e.source_id AND i.job_listing_id = e.job_listing_id "
            "WHERE e.subcategories IS NULL "
            "AND e.category = ? "
            "AND e.subcategory_attempts < ? "
            "AND i.status IN ('sent', 'enriched') "
        )
        params: list[Any] = [SUBCATEGORY_PARENT_CATEGORY, max_attempts]
        if open_only:
            sql += (
                "AND EXISTS (SELECT 1 FROM backfill_scope s "
                "WHERE s.source_id = e.source_id "
                "AND s.job_listing_id = e.job_listing_id) "
            )
        sql += "ORDER BY i.first_seen_at IS NULL, i.first_seen_at DESC, e.enriched_at"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self.connect() as conn:
            return conn.execute(sql, params).fetchall()

    def scope_refusal_reason(
        self, max_age_hours: float = SCOPE_MAX_AGE_HOURS
    ) -> str | None:
        """None when `backfill_scope` is fresh and non-empty; else the reason."""
        age = self.backfill_scope_age_hours()
        if age is None:
            return "backfill_scope is EMPTY — re-run the export + import"
        if age > max_age_hours:
            return (
                f"backfill_scope is {age:.1f}h old (> {max_age_hours}h) — jobs "
                f"open and close overnight; re-run the export + import"
            )
        return None

    def subcategory_backlog_counts(self, max_attempts: int = 3) -> dict[str, int]:
        """The label lane's standing arithmetic over the SWE cohort.

        `evaluated` is COVERAGE (non-NULL, INCLUDING `[]`) and `labelled` is
        YIELD (non-empty). They are different numbers and conflating them is
        what made the draft's single drift breaker blind."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT "
                " COUNT(*) AS total_swe,"
                " SUM(CASE WHEN e.subcategories IS NOT NULL THEN 1 ELSE 0 END)"
                "   AS evaluated,"
                " SUM(CASE WHEN e.subcategories IS NOT NULL "
                "      AND e.subcategories NOT IN ('[]', '') THEN 1 ELSE 0 END)"
                "   AS labelled,"
                " SUM(CASE WHEN e.subcategories = '[]' THEN 1 ELSE 0 END) AS empty,"
                " SUM(CASE WHEN e.subcategories IS NULL"
                "      AND e.subcategory_attempts < ?"
                "      AND i.status IN ('sent','enriched') THEN 1 ELSE 0 END)"
                "   AS eligible,"
                " SUM(CASE WHEN e.subcategories IS NULL"
                "      AND e.subcategory_attempts >= ? THEN 1 ELSE 0 END)"
                "   AS retired,"
                " SUM(CASE WHEN e.subcategories IS NOT NULL"
                "      AND e.subcategory_sent_at IS NULL"
                "      AND e.sent_at IS NOT NULL THEN 1 ELSE 0 END)"
                "   AS pending_push,"
                " SUM(CASE WHEN e.subcategory_sent_at IS NOT NULL THEN 1 ELSE 0 END)"
                "   AS shipped "
                "FROM enrichments e JOIN inbox i "
                "ON i.source_id = e.source_id AND i.job_listing_id = e.job_listing_id "
                "WHERE e.category = ?",
                (max_attempts, max_attempts, SUBCATEGORY_PARENT_CATEGORY),
            ).fetchone()
        return {k: int(row[k] or 0) for k in row.keys()}

    # ---- BF-12b: the throttled drain's queue and cursor --------------------
    def rows_needing_subcategory_push(self, limit: int | None = None) -> list[sqlite3.Row]:
        """Labelled rows JVN has not been told about yet.

        ⚠ THE `sent_at IS NOT NULL` CLAUSE MAKES THE TWO LANES DISJOINT BY
        CONSTRUCTION: `sent_at IS NULL` belongs to the live write-back;
        `sent_at IS NOT NULL AND subcategory_sent_at IS NULL` belongs to the
        drain. Neither can ship the other's rows and there is no lock between
        them. Same JOIN and the same `status != 'failed'` exclusion as
        `enriched_unsent`.

        `run_taxonomy_version` rides along from the run ledger: for a BACKFILLED
        row the version that produced the subcategory is the RUN's, not the row's
        classify-time `taxonomy_version`."""
        sql = (
            "SELECT e.*, b.taxonomy_version AS run_taxonomy_version "
            "FROM enrichments e JOIN inbox i "
            "ON i.source_id = e.source_id AND i.job_listing_id = e.job_listing_id "
            "LEFT JOIN backfill_runs b ON b.id = e.subcategory_run_id "
            "WHERE e.subcategories IS NOT NULL "
            "AND e.subcategory_sent_at IS NULL "
            "AND e.sent_at IS NOT NULL "
            "AND i.status != 'failed' "
            "ORDER BY e.enriched_at"
        )
        params: tuple[Any, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        with self.connect() as conn:
            return conn.execute(sql, params).fetchall()

    def mark_subcategory_sent(self, pairs: Iterable[tuple[str, str]]) -> None:
        """⚠ STAMPS `subcategory_sent_at` ONLY. Never writes `sent_at`, never
        writes `inbox.status` — those two writes are the entire difference between
        this drain and the DELETED re-open drain it replaced."""
        ts = now_iso()
        with self.connect() as conn:
            for sid, jid in pairs:
                conn.execute(
                    "UPDATE enrichments SET subcategory_sent_at = ? "
                    "WHERE source_id = ? AND job_listing_id = ?",
                    (ts, sid, jid),
                )

    # ---- BF-14: scoped rollback -------------------------------------------
    def reset_subcategories(
        self,
        run_id: int | None = None,
        sources: Iterable[str] = ("rule", "backfill"),
        category: str | None = None,
        limit: int | None = None,
        dry_run: bool = False,
    ) -> tuple[int, int]:
        """Un-write machine-written subcategories. Returns (affected, already_pushed).

        ⚠ THE ONLY THING THAT MAKES A SYSTEMATICALLY-WRONG NIGHT RECOVERABLE.
        `'[]'` is TERMINAL in the tri-state, so a bad run does not leave rows
        retryable — it removes them from the queue permanently.

        ⚠ `subcategory_attempts = 0` IS LOAD-BEARING and easy to omit: without it
        a row that hit the cap stays out of `rows_needing_subcategory` FOREVER and
        the reset silently fails to re-queue it.

        ⚠ `subcategory_sent_at = NULL` IS EQUALLY LOAD-BEARING now that BF-12b
        uses it as the drain's cursor: leaving it set means the corrected label is
        never pushed.

        ⚠ NEVER touches a `'judge'`- or `'human'`-sourced row (they are simply not
        in the default `sources`, and the caller must name them to reach them),
        and never touches `category`, `level`, `tags`, `locations`, any judge
        column, `sent_at`, `inbox.status`, or the schema.

        The `sources` predicate accepts any of the FIVE values in the contract,
        not a hardcoded 'backfill': a value written by one repo and unrecognised
        by the reset's default tuple means the rollback silently misses rows.

        `already_pushed` is the count of in-scope rows whose `subcategory_sent_at`
        was non-NULL — ⚠ exactly the set JVN still holds. This command CANNOT
        un-write those; the JVN-side statement is `ADM-15` and is a hard
        prerequisite for calling the rollback complete."""
        source_list = list(sources)
        where = ["subcategory_source IN (%s)" % ",".join("?" * len(source_list))]
        params: list[Any] = list(source_list)
        if run_id is not None:
            where.append("subcategory_run_id = ?")
            params.append(run_id)
        if category is not None:
            where.append("category = ?")
            params.append(category)
        clause = " AND ".join(where)
        with self.connect() as conn:
            # COUNT FIRST, ALWAYS — before a single mutation, so the dry run and
            # the caller's confirmation guard see the same true blast radius.
            rowids = [
                r["rowid"] for r in conn.execute(
                    f"SELECT rowid FROM enrichments WHERE {clause} "
                    f"ORDER BY rowid" + (" LIMIT ?" if limit is not None else ""),
                    params + ([limit] if limit is not None else []),
                ).fetchall()
            ]
            already_pushed = 0
            if rowids:
                ph = ",".join("?" * len(rowids))
                already_pushed = int(
                    conn.execute(
                        f"SELECT COUNT(*) AS n FROM enrichments "
                        f"WHERE rowid IN ({ph}) AND subcategory_sent_at IS NOT NULL",
                        rowids,
                    ).fetchone()["n"]
                )
                if not dry_run:
                    conn.execute(
                        f"UPDATE enrichments SET subcategories = NULL, "
                        f"subcategory_confidence = NULL, subcategory_source = NULL, "
                        f"subcategory_run_id = NULL, subcategory_attempts = 0, "
                        f"subcategory_sent_at = NULL WHERE rowid IN ({ph})",
                        rowids,
                    )
        return len(rowids), already_pushed

    # ---- backfill run ledger (BF-1) ---------------------------------------
    def start_backfill_run(
        self,
        kind: str = "label",
        engine: str | None = None,
        model: str | None = None,
        taxonomy_version: str | None = None,
        rubric_version: str | None = None,
        deadline_at: str | None = None,
    ) -> int:
        """Open a `backfill_runs` row and return its id.

        `rubric_version` is stamped SEPARATELY from `taxonomy_version` because
        under D3 the subcategory rubric lives in its own file
        (.claude/skills/taxonomy/SUBCATEGORIES.md): without the second stamp a
        run cannot prove which rubric produced its labels."""
        if kind not in BACKFILL_RUN_KINDS:
            raise ValueError(
                f"invalid backfill run kind {kind!r}; expected one of "
                f"{sorted(BACKFILL_RUN_KINDS)}"
            )
        ts = now_iso()
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO backfill_runs (uuid, started_at, kind, engine, model, "
                "taxonomy_version, rubric_version, deadline_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid_mod.uuid4()), ts, kind, engine, model,
                    taxonomy_version, rubric_version, deadline_at,
                ),
            )
        return int(cur.lastrowid)

    def bump_backfill_counters(self, run_id: int, **counters: int) -> None:
        """Increment run-ledger counters.

        ⚠ Unknown keys are DROPPED — but a dropped key LOGS A WARNING, unlike
        `bump_tick_counters`, which returns in silence. That silence is how a
        counter can read 0 forever while the run looks healthy; this lane refuses
        to repeat it."""
        cols: dict[str, int] = {}
        for key, value in counters.items():
            if key in _BACKFILL_COUNTER_COLS:
                cols[key] = value
            else:
                logger.warning(
                    "bump_backfill_counters: dropping unknown counter %r "
                    "(run_id=%s); add it to _BACKFILL_COUNTER_COLS and to the "
                    "backfill_runs DDL or it will read 0 forever",
                    key, run_id,
                )
        if not cols:
            return
        set_clause = ", ".join(f"{c} = {c} + ?" for c in cols)
        params = list(cols.values()) + [run_id]
        with self.connect() as conn:
            conn.execute(
                f"UPDATE backfill_runs SET {set_clause} WHERE id = ?", params
            )

    def end_backfill_run(
        self,
        run_id: int,
        status: str,
        aborted_reason: str | None = None,
        notes: str | None = None,
    ) -> None:
        """Close a run row. `aborted_reason` is what the morning report prints
        FIRST when a run did not finish cleanly."""
        with self.connect() as conn:
            conn.execute(
                "UPDATE backfill_runs SET ended_at = ?, status = ?, "
                "aborted_reason = ?, notes = ? WHERE id = ?",
                (now_iso(), status, aborted_reason, notes, run_id),
            )

    def get_backfill_run(self, run_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM backfill_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return dict(row) if row else None

    def latest_backfill_run(self, kind: str | None = None) -> dict[str, Any] | None:
        """Newest run row, optionally restricted to ONE lane. `kind='push'`
        must never return a label run — the report reads one ledger and the
        lane filter is what keeps the two apart."""
        sql = "SELECT * FROM backfill_runs"
        params: tuple[Any, ...] = ()
        if kind is not None:
            sql += " WHERE kind = ?"
            params = (kind,)
        sql += " ORDER BY id DESC LIMIT 1"
        with self.connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    # ---- tick lifecycle ---------------------------------------------------
    def start_tick(self) -> int:
        ts = now_iso()
        tick_uuid = str(uuid_mod.uuid4())
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO ticks (uuid, started_at) VALUES (?, ?)", (tick_uuid, ts)
            )
            tick_id = cur.lastrowid
            conn.execute(
                "INSERT INTO meta (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                "updated_at=excluded.updated_at",
                (CURRENT_TICK_KEY, str(tick_id), ts),
            )
        return int(tick_id)

    def current_tick_id(self) -> int | None:
        raw = self.get_meta(CURRENT_TICK_KEY)
        return int(raw) if raw is not None else None

    def bump_tick_counters(self, **counters: int) -> None:
        cols = {c: v for c, v in counters.items() if c in TICK_COUNTER_COLS}
        if not cols:
            return
        tick_id = self.current_tick_id()
        if tick_id is None:
            return
        set_clause = ", ".join(f"{c} = {c} + ?" for c in cols)
        params = list(cols.values()) + [tick_id]
        with self.connect() as conn:
            conn.execute(f"UPDATE ticks SET {set_clause} WHERE id = ?", params)

    def record_stage_timing(
        self, stage: str, started_at: str, ended_at: str, duration_ms: int,
        item_count: int = 0, retry_count: int = 0,
    ) -> None:
        tick_id = self.current_tick_id()
        if tick_id is None:
            return
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO stage_timings (tick_id, stage, started_at, ended_at, "
                "duration_ms, item_count, retry_count) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (tick_id, stage, started_at, ended_at, duration_ms, item_count, retry_count),
            )

    def last_stage_event_at(self) -> str | None:
        """The end timestamp of the current tick's most recent stage event
        (falls back to the tick's started_at). Used to attribute wall time to
        the classify/judge stages, which have no in-process timer."""
        tick_id = self.current_tick_id()
        if tick_id is None:
            return None
        with self.connect() as conn:
            row = conn.execute(
                "SELECT MAX(ended_at) AS ts FROM stage_timings WHERE tick_id = ?",
                (tick_id,),
            ).fetchone()
            if row is not None and row["ts"]:
                return str(row["ts"])
            trow = conn.execute(
                "SELECT started_at FROM ticks WHERE id = ?", (tick_id,)
            ).fetchone()
        return str(trow["started_at"]) if trow is not None else None

    def end_tick(self, status: str = "ok", notes: str | None = None) -> int | None:
        tick_id = self.current_tick_id()
        if tick_id is None:
            return None
        ts = now_iso()
        with self.connect() as conn:
            conn.execute(
                "UPDATE ticks SET ended_at = ?, status = ?, notes = ? WHERE id = ?",
                (ts, status, notes, tick_id),
            )
            conn.execute("DELETE FROM meta WHERE key = ?", (CURRENT_TICK_KEY,))
        return tick_id

    def latest_tick(self) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM ticks ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row is not None else None

    def get_tick(self, tick_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM ticks WHERE id = ?", (tick_id,)).fetchone()
        return dict(row) if row is not None else None

    def ensure_tick_uuid(self, tick_id: int) -> str | None:
        """Return the tick's uuid, generating + persisting one for legacy (v0)
        rows migrated without it. The uuid is the metrics-push idempotency key."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT uuid FROM ticks WHERE id = ?", (tick_id,)
            ).fetchone()
            if row is None:
                return None
            if row["uuid"]:
                return str(row["uuid"])
            fresh = str(uuid_mod.uuid4())
            conn.execute(
                "UPDATE ticks SET uuid = ? WHERE id = ? AND uuid IS NULL",
                (fresh, tick_id),
            )
        return fresh

    def stage_timings_for_tick(self, tick_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT stage, duration_ms, item_count, retry_count "
                "FROM stage_timings WHERE tick_id = ? ORDER BY id",
                (tick_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def latency_summary_for_tick(self, tick_id: int) -> dict[str, Any]:
        """Per-tick engine latency (avg/max ms + sample count) for classify and
        judge, from the v2 per-item latency columns. None per side when nothing
        recorded latency (e.g. a claude-code sub-agent tick, which doesn't self-time)."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT AVG(classify_latency_ms) AS c_avg, MAX(classify_latency_ms) AS c_max, "
                "COUNT(classify_latency_ms) AS c_n, AVG(judge_latency_ms) AS j_avg, "
                "MAX(judge_latency_ms) AS j_max, COUNT(judge_latency_ms) AS j_n "
                "FROM enrichments WHERE tick_id = ?",
                (tick_id,),
            ).fetchone()

        def side(avg: Any, mx: Any, n: Any) -> dict[str, Any] | None:
            return {"avg_ms": round(float(avg), 1), "max_ms": int(mx), "n": int(n)} if n else None

        return {
            "classify": side(row["c_avg"], row["c_max"], row["c_n"]),
            "judge": side(row["j_avg"], row["j_max"], row["j_n"]),
        }

    def recent_ticks(self, limit: int = 50) -> list[dict[str, Any]]:
        """Most recent ticks (newest first) for the dashboard's tick history."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM ticks ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def list_jobs(
        self,
        status: str | None = None,
        needs_human: bool | None = None,
        limit: int = 50,
        offset: int = 0,
        swe_without_subcategories: bool = False,
    ) -> tuple[list[dict[str, Any]], int]:
        """Paginated inbox LEFT JOIN enrichments (a claimed/cleaned job may have
        no enrichment yet). Filter by inbox.status and/or the enrichment
        needs_human flag. Returns (rows, total) where total is the match count
        before LIMIT/OFFSET. Job text is returned verbatim (untrusted scraper
        input) — the caller renders it as escaped data, never HTML."""
        where: list[str] = []
        params: list[Any] = []
        if status is not None:
            where.append("i.status = ?")
            params.append(status)
        if needs_human is not None:
            where.append("COALESCE(e.needs_human, 0) = ?")
            params.append(1 if needs_human else 0)
        if swe_without_subcategories:
            # OPS-4's Jobs-panel filter: the backfill queue, plus the TERMINAL
            # '[]' rows, so an operator can eyeball what "no specialty applies"
            # actually landed on.
            where.append("e.category = ?")
            params.append(SUBCATEGORY_PARENT_CATEGORY)
            where.append("(e.subcategories IS NULL OR e.subcategories = '[]')")
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        join = (
            "FROM inbox i LEFT JOIN enrichments e "
            "ON e.source_id = i.source_id AND e.job_listing_id = i.job_listing_id"
        )
        with self.connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS n {join}{clause}", params
            ).fetchone()["n"]
            rows = conn.execute(
                "SELECT i.source_id, i.job_listing_id, i.title, i.company, "
                "i.raw_location, i.status, i.claimed_at, e.category, e.level, "
                "e.classify_confidence, e.judged, e.judge_pass, "
                "COALESCE(e.needs_human, 0) AS needs_human, e.tick_id, "
                f"e.subcategories, e.enriched_at, e.sent_at {join}{clause} "
                "ORDER BY i.claimed_at DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        return [dict(r) for r in rows], int(total)

    def job_detail(self, source_id: str, job_listing_id: str) -> dict[str, Any] | None:
        """Full drill-down for one job (inbox columns + the enrichment verdict)
        keyed on the composite identity, or None if the pair is unknown."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT i.*, e.category, e.level, e.level_includes, e.tags, "
                "e.locations, e.classify_confidence, e.classify_reasoning, "
                "e.judged, e.judge_pass, e.judge_confidence, e.judge_notes, "
                "e.needs_human AS enr_needs_human, e.pre_judge_category, "
                "e.pre_judge_level, e.pre_judge_tags, e.classify_model, "
                "e.judge_model, e.tick_id, e.subcategories, "
                "e.subcategory_confidence, e.subcategory_source, "
                "e.subcategory_attempts, e.pre_judge_subcategories, "
                "e.subcategory_sent_at, e.enriched_at, e.sent_at "
                "FROM inbox i LEFT JOIN enrichments e "
                "ON e.source_id = i.source_id AND e.job_listing_id = i.job_listing_id "
                "WHERE i.source_id = ? AND i.job_listing_id = ?",
                (source_id, job_listing_id),
            ).fetchone()
        return dict(row) if row is not None else None


def _migrate_v3_to_v4(conn: sqlite3.Connection) -> None:
    """Add the v4 subcategory columns to enrichments and the three subcategory
    counters to ticks.

    ALTER-only — ten columns, no table rebuild, both primary keys unchanged —
    and idempotent, so a half-applied migration re-runs cleanly. Existing rows
    get ``subcategories IS NULL`` (never evaluated: THE BACKFILL QUEUE, and
    emphatically not ``'[]'``) and ``subcategory_attempts = 0``.

    The two new TABLES (backfill_runs, backfill_scope) are deliberately NOT here:
    they live in _SCHEMA_SQL as CREATE TABLE IF NOT EXISTS, which executes after
    this ladder on both a fresh and an upgraded DB. Only new COLUMNS need ALTERs.

    Wrapped in one transaction; the version stamp is deferred to init_schema's
    final PRAGMA exactly as v3 does."""
    logger.info("store: migrating schema v3 -> v4 (subcategory columns + tick counters)")
    enr_cols = {row["name"] for row in conn.execute("PRAGMA table_info(enrichments)")}
    # A pre-v1 DB has no `ticks` table at all; _SCHEMA_SQL creates it (already
    # carrying the v4 columns) right after this ladder, so there is nothing to
    # ALTER. PRAGMA table_info on a missing table returns an empty set, which
    # would otherwise make us try to ALTER a table that does not exist.
    has_ticks = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='ticks'"
    ).fetchone() is not None
    tick_cols = {row["name"] for row in conn.execute("PRAGMA table_info(ticks)")}
    enr_additions = [
        ("subcategories", "TEXT"),
        ("subcategory_confidence", "REAL"),
        ("subcategory_source", "TEXT"),
        ("subcategory_attempts", "INTEGER NOT NULL DEFAULT 0"),
        ("pre_judge_subcategories", "TEXT"),
        ("subcategory_run_id", "INTEGER"),
        ("subcategory_sent_at", "TEXT"),
    ]
    tick_additions = [
        ("swe_classified", "INTEGER NOT NULL DEFAULT 0"),
        ("swe_subcat_evaluated", "INTEGER NOT NULL DEFAULT 0"),
        ("swe_subcategorized", "INTEGER NOT NULL DEFAULT 0"),
    ]
    conn.execute("BEGIN")
    try:
        for name, coltype in enr_additions:
            if name not in enr_cols:
                conn.execute(f"ALTER TABLE enrichments ADD COLUMN {name} {coltype}")
        for name, coltype in tick_additions:
            if has_ticks and name not in tick_cols:
                conn.execute(f"ALTER TABLE ticks ADD COLUMN {name} {coltype}")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _migrate_v2_to_v3(conn: sqlite3.Connection) -> None:
    """Add inbox.first_seen_at (JVN posting-recency signal, for newest-first
    ordering) and enrichments.title_only (the description-less stopgap marker).

    ALTER-only (both PKs unchanged, no rebuild) and idempotent — each column is
    added only if absent, so a half-applied migration re-runs cleanly. Existing
    rows get NULL first_seen_at (sorted last by the queues) and title_only=0.
    Wrapped in one transaction; the version stamp is deferred to init_schema's
    final PRAGMA."""
    logger.info("store: migrating schema v2 -> v3 (inbox.first_seen_at + enrichments.title_only)")
    inbox_cols = {row["name"] for row in conn.execute("PRAGMA table_info(inbox)")}
    enr_cols = {row["name"] for row in conn.execute("PRAGMA table_info(enrichments)")}
    conn.execute("BEGIN")
    try:
        if "first_seen_at" not in inbox_cols:
            conn.execute("ALTER TABLE inbox ADD COLUMN first_seen_at TEXT")
        if "title_only" not in enr_cols:
            conn.execute(
                "ALTER TABLE enrichments ADD COLUMN title_only INTEGER NOT NULL DEFAULT 0"
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """Add the v2 reasoning + latency columns to enrichments.

    ALTER-only (the primary key is unchanged, so no table rebuild) and idempotent
    — each column is added only if absent, so a half-applied migration re-runs
    cleanly. Wrapped in one transaction with the version stamp deferred to
    init_schema's final PRAGMA."""
    logger.info("store: migrating schema v1 -> v2 (judge_reasoning + latency columns)")
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(enrichments)")}
    additions = [
        ("classify_latency_ms", "INTEGER"),
        ("judge_reasoning", "TEXT"),
        ("judge_latency_ms", "INTEGER"),
    ]
    conn.execute("BEGIN")
    try:
        for name, coltype in additions:
            if name not in existing:
                conn.execute(f"ALTER TABLE enrichments ADD COLUMN {name} {coltype}")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _migrate_v0_to_v1(conn: sqlite3.Connection) -> None:
    """Rebuild inbox + enrichments on the composite (source_id, job_listing_id)
    primary key, add the v1 provenance/lifecycle columns, and extend ticks —
    all inside ONE transaction (CREATE new -> INSERT SELECT -> DROP -> RENAME).
    FKs are turned off for the rebuild (they cannot change mid-transaction, so
    this runs before BEGIN) and restored after."""
    logger.info("store: migrating schema v0 -> v1 (composite keys + provenance columns)")
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("BEGIN")
    try:
        conn.execute(
            """
            CREATE TABLE inbox_v1 (
              job_listing_id   TEXT NOT NULL,
              source_id        TEXT NOT NULL,
              title            TEXT NOT NULL,
              company          TEXT NOT NULL,
              raw_location     TEXT,
              description_html TEXT,
              details_json     TEXT,
              content_hash     TEXT NOT NULL,
              claimed_at       TEXT NOT NULL,
              cleaned_at       TEXT,
              clean_description TEXT,
              status           TEXT NOT NULL DEFAULT 'claimed'
                                 CHECK (status IN ('claimed','cleaned','enriched','sent','failed')),
              attempts         INTEGER NOT NULL DEFAULT 0,
              PRIMARY KEY (source_id, job_listing_id)
            )
            """
        )
        conn.execute(
            f"INSERT INTO inbox_v1 ({_V0_INBOX_COLS}, attempts) "
            f"SELECT {_V0_INBOX_COLS}, 0 FROM inbox"
        )
        conn.execute("DROP TABLE inbox")
        conn.execute("ALTER TABLE inbox_v1 RENAME TO inbox")

        conn.execute(
            """
            CREATE TABLE enrichments_v1 (
              job_listing_id   TEXT NOT NULL,
              source_id        TEXT NOT NULL,
              category         TEXT,
              level            TEXT,
              level_includes   TEXT,
              tags             TEXT,
              locations        TEXT,
              classify_confidence REAL,
              classify_reasoning  TEXT,
              taxonomy_version TEXT,
              judged           INTEGER NOT NULL DEFAULT 0,
              judge_pass       INTEGER,
              judge_confidence REAL,
              judge_notes      TEXT,
              needs_human      INTEGER NOT NULL DEFAULT 0,
              pre_judge_category TEXT,
              pre_judge_level    TEXT,
              pre_judge_tags     TEXT,
              classify_model     TEXT,
              judge_model        TEXT,
              tick_id            INTEGER,
              enriched_at      TEXT NOT NULL,
              sent_at          TEXT,
              PRIMARY KEY (source_id, job_listing_id),
              FOREIGN KEY (source_id, job_listing_id) REFERENCES inbox(source_id, job_listing_id)
            )
            """
        )
        conn.execute(
            f"INSERT INTO enrichments_v1 ({_V0_ENRICHMENTS_COLS}) "
            f"SELECT {_V0_ENRICHMENTS_COLS} FROM enrichments"
        )
        conn.execute("DROP TABLE enrichments")
        conn.execute("ALTER TABLE enrichments_v1 RENAME TO enrichments")

        conn.execute("ALTER TABLE ticks ADD COLUMN uuid TEXT")
        conn.execute("ALTER TABLE ticks ADD COLUMN nulled_facets INTEGER NOT NULL DEFAULT 0")

        # indexes dropped with the old tables; _SCHEMA_SQL recreates them.
        # Stamp v1 (this step only builds v1 structures) — NOT SCHEMA_VERSION:
        # _migrate_v1_to_v2 runs next and advances it, and init_schema stamps the
        # final SCHEMA_VERSION only after ALL steps succeed. Stamping the final
        # version here would let a crash before v1->v2 leave a v2-stamped DB that
        # lacks the v2 columns, permanently skipping the ALTERs.
        conn.execute("PRAGMA user_version = 1")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
