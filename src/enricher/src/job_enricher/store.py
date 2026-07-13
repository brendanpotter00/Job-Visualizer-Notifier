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

import logging
import sqlite3
import uuid as uuid_mod
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "data" / "enricher.db"

# meta keys
HEARTBEAT_KEY = "heartbeat:last_poll_at"
CURRENT_TICK_KEY = "current_tick_id"
LAST_SCORECARD_HASH_KEY = "metrics:last_scorecard_hash"

SCHEMA_VERSION = 3

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
  PRIMARY KEY (source_id, job_listing_id),
  FOREIGN KEY (source_id, job_listing_id) REFERENCES inbox(source_id, job_listing_id)
);

CREATE INDEX IF NOT EXISTS idx_enrichments_unsent
  ON enrichments(sent_at) WHERE sent_at IS NULL;

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
"""

_TICK_COUNTER_COLS = frozenset(
    {
        "claimed", "cleaned", "classified", "judged", "corrected",
        "needs_human", "sent", "errors", "nulled_facets",
    }
)

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
                "tick_id, enriched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
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
                "needs_human=excluded.needs_human, title_only=excluded.title_only, "
                "sent_at=NULL",
                (
                    e["job_listing_id"], e["source_id"], e.get("category"), e.get("level"),
                    e.get("level_includes"), e.get("tags"), e.get("locations"),
                    e.get("classify_confidence"), e.get("classify_reasoning"),
                    e.get("classify_latency_ms"),
                    e.get("taxonomy_version"), needs_human, title_only, e.get("classify_model"),
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

        Provenance: on the FIRST judge merge for a row (judged still 0) the
        current classify-stage category/level/tags are snapshotted into the
        pre_judge_* columns so judge deltas stay reconstructable; `judge_model`
        is stamped from the caller.

        If the verdict CHANGES a shipped facet (category/level/level_includes/
        tags/locations) on a row that was ALREADY written back (`sent_at` set),
        the correction is stranded unless we re-open it: clear `sent_at` and put
        the inbox row back to 'enriched' so the fix re-ships next tick (E9). A
        judge pass that changes nothing on a sent row leaves it sent."""
        jid = j["job_listing_id"]
        sid = j["source_id"]
        with self.connect() as conn:
            cur = conn.execute(
                "SELECT category, level, level_includes, tags, locations, sent_at, judged "
                "FROM enrichments WHERE source_id = ? AND job_listing_id = ?",
                (sid, jid),
            ).fetchone()
            facet_changed = cur is not None and (
                cur["category"] != j.get("category")
                or cur["level"] != j.get("level")
                or cur["level_includes"] != j.get("level_includes")
                or cur["tags"] != j.get("tags")
                or cur["locations"] != j.get("locations")
            )
            reopen = facet_changed and cur is not None and cur["sent_at"] is not None
            first_judge = cur is not None and not cur["judged"]
            snapshot_sql = ""
            snapshot_params: tuple[Any, ...] = ()
            if first_judge:
                snapshot_sql = ", pre_judge_category=?, pre_judge_level=?, pre_judge_tags=?"
                snapshot_params = (cur["category"], cur["level"], cur["tags"])
            conn.execute(
                "UPDATE enrichments SET category=?, level=?, level_includes=?, tags=?, "
                "locations=?, judged=1, judge_pass=?, judge_confidence=?, judge_notes=?, "
                "judge_reasoning=?, judge_latency_ms=?, "
                "judge_model=?, needs_human=?" + snapshot_sql
                + (", sent_at=NULL" if reopen else "") + " "
                "WHERE source_id = ? AND job_listing_id = ?",
                (
                    j.get("category"), j.get("level"), j.get("level_includes"),
                    j.get("tags"), j.get("locations"), 1 if j.get("judge_pass") else 0,
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
        """Mark rows sent, keyed by (source_id, job_listing_id) pairs."""
        ts = now_iso()
        with self.connect() as conn:
            for sid, jid in pairs:
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
        cols = {c: v for c, v in counters.items() if c in _TICK_COUNTER_COLS}
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
                f"e.enriched_at, e.sent_at {join}{clause} "
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
                "e.judge_model, e.tick_id, e.enriched_at, e.sent_at "
                "FROM inbox i LEFT JOIN enrichments e "
                "ON e.source_id = i.source_id AND e.job_listing_id = i.job_listing_id "
                "WHERE i.source_id = ? AND i.job_listing_id = ?",
                (source_id, job_listing_id),
            ).fetchone()
        return dict(row) if row is not None else None


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
