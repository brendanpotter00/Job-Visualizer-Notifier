# `job_listings` write amplification & index bloat (runbook)

Why `idx_job_listings_last_seen` bloats, which "obvious" fixes are **refuted**, the
one-line REINDEX stopgap, and what to watch instead now that the `job_freshness`
sidecar owns the churn.

> **Status, 2026-08-05.** The churn is **frozen**. Sidecar Units 2-3 (PR **#224**,
> commit `0380e8a`, merged 2026-08-04 23:39 CDT = **2026-08-05 04:39 UTC**) repointed
> the write path so `job_listings.last_seen_at` is no longer re-stamped. The REINDEX
> stopgap below is therefore **moot in practice** and is **superseded outright** once
> Unit 4 (PR-B) drops the index and both freshness columns. The live watch has moved
> to `idx_job_freshness_last_seen` — see §4.

Companion postmortem: [`docs/incidents/2026-07-13-api-jobs-outage.md`](../../../docs/incidents/2026-07-13-api-jobs-outage.md).
Read it first if you are here because `/api/jobs` is slow — index bloat was the
**decoy** in that incident, not the cause.

---

## 1. The corrected analysis

All figures measured **read-only against prod on 2026-08-05 ~05:17 UTC**
(`mcp__postgres-prod__query`). They supersede the round numbers in the postmortem
timeline, which were taken on 2026-08-04 at a smaller row count.

### 1a. The mechanism

`update_last_seen` (`scripts/shared/database.py`) used to re-stamp `last_seen_at` on
**every open job on every hourly scrape cycle**. Because `last_seen_at` carries an
index, **none of those updates can be HOT**: each one writes a new heap tuple *and* a
new btree entry, and the dead entries pile up at the high end of the index — exactly
where an `ORDER BY last_seen_at DESC` scan enters. Over ~182 M lifetime updates that
produced a 46,800,896-byte (44.6 MiB) index on a 67 k-row table.

### 1b. Index sizes — the apples-to-apples comparison

`idx_job_freshness_last_seen` is the correct baseline: **same column type**
(`timestamptz`), **same row count**, **same access pattern**. The only differences are
its age and its storage tuning.

| Index | Bytes | Binary | Rows | Bytes/row |
|---|---:|---:|---:|---:|
| `idx_job_listings_last_seen` (bloated) | 46,800,896 | 44.6 MiB | 67,648 | **691.8** |
| `idx_job_freshness_last_seen` (healthy baseline) | 1,851,392 | 1.8 MiB | 67,648 | **27.4** |
| `job_listings_pkey` (scale reference) | 6,627,328 | 6.3 MiB | 67,648 | 98.0 |

> **Units.** Raw bytes are authoritative here; the monitor renders **binary** units
> (1 MiB = 1024² B, see `_fmt_bytes`). The postmortem's historical figures — "46.8 MB",
> "27.8 MB" — are the same byte counts read as *decimal* MB. 46,800,896 B = 44.6 MiB
> = 46.8 MB. Nothing changed size; only the convention differs.

The parent index is **25× the bytes-per-row** of its own baseline, and **7× the size of
the composite `(source_id, id)` text primary key** covering the same table — for a
single 8-byte timestamp column. That ratio is the tell.

> **The sidecar's steady state is not yet known — do not quote 27.4 as one.** The only
> stable reference point is a **fresh rebuild: 1,122,304 B / 17.7 B-row (2026-08-04)**.
> It packs that tightly because every row in a scrape cycle shares one timestamp value,
> so btree deduplication collapses them. The 27.4 above is a sample taken **38 minutes**
> after the sidecar took over the churn; 23 minutes later it read **29.5 B-row**
> (1,998,848 B / 67,650 rows) — still climbing ~8 % in under half an hour, and not yet
> through an autovacuum cycle at `scale_factor = 0.02`. Treat 17.7 as the floor, 27–30
> as early settling, and **recalibrate after ~a week** (§4).

### 1c. Churn counters (`pg_stat_user_tables`)

| Table | `n_tup_upd` | `n_tup_hot_upd` | HOT % | `n_dead_tup` | `autovacuum_count` |
|---|---:|---:|---:|---:|---:|
| `job_listings` | 182,158,867 | 209,910 | **0.115 %** | 7,163 | 9,181 |
| `job_freshness` | 88,350 | 22 | **0.025 %** | 0 | 5 |

Supporting sizes: `job_listings` heap 110,133,248 B (105 MiB), **total relation
897,228,800 B (856 MiB)** once TOAST and indexes are counted — the `details` JSONB is
~10 KB/row. `job_freshness` heap 8,478,720 B (8.1 MiB).

### 1d. Growth history, and the freeze

| Date | Size (decimal MB, per the postmortem) | Bytes/row | Note |
|---|---:|---:|---|
| 2026-07-13 | ~0 | — | manual `REINDEX INDEX CONCURRENTLY` during the outage |
| 2026-07-25 | 27.8 MB | 438 | re-bloating under the hourly re-stamp |
| 2026-08-04 | 46.8 MB | 737.7 | **~1.9 MB/day** over those ten days |
| 2026-08-05 | 46,800,896 B (44.6 MiB) | 691.8 | **+8,192 B — one 8 KB page — in 24 h** |

Three independent confirmations that the freeze is real, not a measurement artifact:

1. **Zero re-stamps.** `job_listings` rows that existed before the cutover and have been
   re-stamped since: **0**. Sidecar rows stamped in the same window: **24,763**.
2. **The index stopped growing.** It gained **exactly one 8 KB page** in the 24 h
   spanning the cutover, against ~1.9 MB/day before it.
3. **The HOT ratio inverted — the strongest signal.** `job_listings` is *not* idle: it
   took **24,786 updates in the 22 minutes** from 05:18 to 05:40 UTC (~25 k/hour, from
   enrichment, status and `normalization_status` writes). But **22,532 of them were HOT
   — 90.9 %** — against a **0.115 % lifetime** figure. Residual updates continue; the
   non-HOT freshness stamping that built the bloat is gone, because those residual
   updates touch no indexed column.

Bytes-per-row *fell* from 737.7 to 691.8 only because the corpus grew (63,406 → 67,648
rows over the preceding ~10 days) while the index stood still — not because anything
shrank.

`job_listings.last_seen_at` is still written on **INSERT** — it is `NOT NULL` and new
listings seed it — which is why `max(last_seen_at)` on the parent still looks current.
That is ~24 rows/2 h (**578 inserts in the last 24 h**), not 67 k rows/hour, and inserts
are not a churn source: they add index entries, they do not orphan old ones.

---

## 2. The three refuted fixes

These were each proposed, tested against the evidence, and **refuted**. They are
recorded here so nobody re-litigates them.

### 2a. `fillfactor` on `job_listings` — REFUTED

**Claim:** leave free space on each heap page so the re-stamp can be a HOT update.

**Why it cannot work:** HOT requires that **no indexed column changes**. `last_seen_at`
*is* indexed, so the update is non-HOT no matter how much free space the page has —
free space is not the binding constraint, the index is.

**Measured proof:** `job_freshness` carries `fillfactor=90` and its updates run at
**0.025 % HOT** — *lower* than the un-tuned parent's 0.115 %. Adding fillfactor to
`job_listings` would have bought a bigger table and nothing else.

> **`job_listings.reloptions` must stay `NULL`.** `job_freshness` is the **only**
> relation in this database carrying storage parameters, and that is deliberate — see
> the postmortem's "no autovacuum reloptions on `job_listings`" deviation.
> `grep -rn "fillfactor" src/backend/` must only hit `job_freshness` contexts.

### 2b. Autovacuum tuning on `job_listings` — REFUTED

**Claim:** vacuum more aggressively so the dead entries get reclaimed.

**Why it cannot work:** autovacuum is **already keeping up** — 9,181 runs, `n_dead_tup`
7,163 against 67,648 live rows (~10 %, mid-cycle, routine). Dead *tuples* are being
reclaimed on schedule. What remains is btree **fragmentation**: half-empty leaf pages
that `VACUUM` marks reusable but never compacts and never returns to the OS. Only
`REINDEX` rebuilds a btree densely. Tuning a mechanism that is already winning its own
race cannot fix a problem it does not own.

### 2c. Dropping `idx_job_listings_last_seen` ad-hoc — REFUSED (but read the nuance)

**Claim:** the index is pure cost; delete it now.

**The nuance matters, because the honest answer changed at the cutover.**

- **Before 2026-08-05 04:39 UTC** it was genuinely **load-bearing**: the driving access
  path for `ORDER BY last_seen_at DESC LIMIT <= 5000`, EXPLAIN-verified `Index Scan
  Backward` on 2026-07-13. Dropping it then would have converted that into a full sort.
- **Since the cutover it is dead weight.** Both read paths now order by the sidecar
  (`api/services/database.py:274`, `api/services/location_admin.py:518`), and prod
  `EXPLAIN` confirms `Parallel Index Scan Backward using idx_job_freshness_last_seen`.
  The parent index appears in **no live query plan**.

So it is not refused because dropping it would break a query today. It is refused
because **an ad-hoc `DROP INDEX` is the wrong instrument**:

1. `last_seen_at` is still a live, `NOT NULL` column that every INSERT writes. Dropping
   only the index leaves a half-migrated state — exactly the "no half-migrated state"
   criterion the epic is held to.
2. It becomes load-bearing again the moment PR #224 is reverted, and reverting a
   one-day-old write-path cutover is a live possibility.
3. The index and both columns are **one contract**. Unit 4 removes them together, with a
   reviewed migration and a real `downgrade()`. A manual `DROP INDEX` on the console has
   neither, and Alembic would then disagree with the live schema.

Dropping it is therefore **correct and scheduled** — as Unit 4, not as a shortcut (§5).

### 2d. What actually works — and why

The durable fix is the **`job_freshness` sidecar**. Note carefully that it does **not**
work by making the updates HOT — it can't, for the same reason as §2a, and its measured
HOT ratio is 0.025 %. It works by **moving the churn onto a relation small enough for
autovacuum to hold steady**:

| | `job_listings` | `job_freshness` |
|---|---:|---:|
| Heap rewritten per update | 105 MiB table, ~10 KB rows + TOAST | 8.1 MiB table, ~50 B rows |
| Total relation | 856 MiB | 8.5 MiB |
| Freshness index | 44.6 MiB | 1.8 MiB |
| Storage tuning | none (`reloptions` NULL, deliberately) | `fillfactor=90`, `autovacuum_*_scale_factor=0.02` |

Same number of dead index entries per cycle; two orders of magnitude less work to
recycle them, on a table whose aggressive autovacuum settings actually fit.

---

## 3. Stopgap: `REINDEX INDEX CONCURRENTLY`

The exact command, run by a **human** against the Railway Postgres console
(onesecondswe → Postgres → Connect). Never from application code, never from a
migration:

```sql
REINDEX INDEX CONCURRENTLY idx_job_listings_last_seen;
```

- **Non-blocking.** `CONCURRENTLY` takes no `ACCESS EXCLUSIVE` lock on the table; reads
  and writes continue throughout. It needs transient disk space for the rebuilt copy and
  it can leave an `INVALID` index behind if it is interrupted — check
  `pg_index.indisvalid` afterwards and `DROP` any invalid leftover.
- **It works.** On 2026-07-13 this took the `ORDER BY last_seen_at DESC LIMIT 5000`
  query to **~20 ms**. It did **not** fix the outage, because the outage was a different
  query shape (JSONB detoast on the batched list path) — read the postmortem before
  reaching for this under pressure.
- **It re-bloats.** At the historical churn: 0 → 27.8 MB by 2026-07-25 → 46.8 MB by
  2026-08-04. Roughly **two weeks** to be back where it started. It buys time, not a fix.

> **Moot in practice since 2026-08-05, superseded by Unit 4.** The churn froze at the
> Units 2-3 cutover (§1d), so the index is no longer growing, and Unit 4 deletes it
> outright. Do **not** run this as routine maintenance. It is only warranted if Unit 4
> is abandoned **and** the write path is reverted to stamping `job_listings`.

---

## 4. Go-forward: watch the sidecar index

The bloat watch has moved to **`idx_job_freshness_last_seen`** — the index that now
carries the churn. It is designed to stay small (fillfactor=90 + aggressive autovacuum);
if it climbs like its predecessor did, the sidecar is not holding and that is the signal.

> **Open item: recalibrate the sidecar thresholds after ~a week.** As of 2026-08-05 the
> sidecar has carried the churn for about an hour and its bytes-per-row is still rising
> (§1b). The current 80 B/row line is anchored on the one stable number available — ~4.5×
> the 17.7 B/row fresh-rebuild baseline — not on an observed plateau. Once it has been
> through many autovacuum cycles at `scale_factor = 0.02`, take a reading and tighten
> toward the plateau. Keep the `--json` snapshots so the curve is reconstructable.

Automated as group **S** of the read-only prod monitor:

```bash
# from the repo ROOT
MONITOR_DATABASE_URL='postgresql://readonly:...@host:port/db' PYTHONPATH=. \
  python -m src.backend.api.eval.monitor_prod --verbose
```

| Check | Reports | `warn` |
|---|---|---|
| `S1_index_bloat` | size + bytes-per-row for both indexes, side by side | parent > 10 MiB **or** > 150 B/row · sidecar > 8 MiB **or** > 80 B/row |
| `S2_hot_churn` | `n_tup_upd`, `n_tup_hot_upd`, HOT %, `n_dead_tup`, `autovacuum_count` for both tables | *(info only — see below)* |
| `S3_listings_without_freshness` | `job_listings ⟕ job_freshness` anti-join | **`crit` if > 0** |
| `S4_freshness_without_listing` | reverse anti-join | **`crit` if > 0** |

**Reading the results:**

- **S1 is warn-only, no crit tier.** Bloat degrades gradually and is never a page-me
  event. The parent line stays lit at warn until Unit 4 removes the index; that is
  expected, not new information. `absent (dropped by Unit 4 contract)` on the parent is
  reported as **`info`** — the check never errors on a missing index and never assumes
  either one exists. An absent **sidecar** index is a `warn`: that one the read path
  needs.
  - *Thresholds:* bytes-per-row is the scale-free signal; the byte caps are backstops
    against corpus growth. The sidecar's 80 B/row is **~4.5× the 17.7 B/row fresh-rebuild
    baseline** — deliberately anchored there rather than on the still-climbing
    post-cutover samples (§1b) — loose enough not to fire during initial settling, tight
    enough to fire ~9× below the parent's 691.8 B/row failure mode. **Provisional: see
    the recalibration note above.** The constants and this rationale live in
    `api/eval/monitor_prod.py` (`_INDEX_WARN_BYTES*`); unit-tested in
    `api/tests/test_monitor_prod.py`.
- **S2 is info-only by design.** Read the **HOT ratio, not the update count**:
  `job_listings` is *not* idle post-cutover — ~25 k updates/hour continue from
  enrichment, status and `normalization_status` writes — but they touch no indexed
  column, so they run ~91 % HOT against a 0.115 % lifetime figure (§1d). What froze is
  the freshness stamping, not all writes. One point-in-time read of a cumulative counter
  cannot establish a trend, so the check asserts nothing; a human diffs it against §1c
  and the previous run's `--json` snapshot.
- **S3/S4 are the load-bearing ones.** The `/api/jobs` read path **INNER JOINs**
  `job_freshness` (`api/services/database.py::_FRESHNESS_JOIN`). A listing with no
  freshness row does not 404 — it **silently disappears** from the list response, with no
  error anywhere. Nothing else in production detects that; these two anti-joins are the
  detection. Both were **0** on 2026-08-05. A non-zero `S3` means jobs are missing from
  the site right now: find the insert path that bypassed the `AFTER INSERT` trigger, then
  backfill the missing freshness rows.

> **The A1 gate is location-specific.** If the location-normalization schema gate fails,
> the CLI exits 2 *before* the S-checks run. Run their SQL directly in that case — the
> `Check.sql` strings in `api/eval/monitor_prod.py` are the source of truth, and all four
> are plain `SELECT`s safe to paste into `mcp__postgres-prod__query`.

---

## 5. Interaction with Unit 4 (PR-B)

Unit 4 is the contract change: `DROP INDEX idx_job_listings_last_seen;` plus
`ALTER TABLE job_listings DROP COLUMN last_seen_at, DROP COLUMN consecutive_misses;`
(metadata-only; dropping the index *frees* space). When it lands:

| | Before Unit 4 | After Unit 4 |
|---|---|---|
| `idx_job_listings_last_seen` | present, 44.6 MiB, frozen, in no query plan | **gone** |
| `S1_index_bloat` parent line | `warn` (bloated) | `info` — `absent (dropped by Unit 4 contract)` |
| This runbook's §3 | a stopgap nobody needs | dead letter — keep for the history |
| The watch | sidecar index | sidecar index (unchanged) |
| `db_models.py` comment block | present | **deleted with the index** |

Nothing in the monitor needs editing when Unit 4 ships — that is the point of the
absent-index handling. §2 and §3 stay as the written record of *why* the index existed
and why the three shortcuts were rejected.

---

## 6. Source map

| Path | Role |
|---|---|
| `docs/incidents/2026-07-13-api-jobs-outage.md` | The postmortem. Index bloat was the **decoy**; the outage was JSONB detoast on `_LIST_COLUMNS`. |
| `src/backend/api/db_models.py` | The `idx_job_listings_last_seen` comment block (the short form of §2) and the `JobFreshness` docstring (the sidecar's design rationale). |
| `src/backend/api/eval/monitor_prod.py` | Group **S** checks + the threshold constants. The `Check.sql` strings are the single source of truth for the SQL. |
| `src/backend/api/tests/test_monitor_prod.py` | Pure threshold / formatting / absent-index tests. No DB — runs in `cd src/backend && pytest`. |
| `scripts/shared/database.py` | The write path. `_UPSERT_ON_CONFLICT` no longer touches freshness; `_FRESHNESS_UPSERT` / `update_last_seen` / `increment_consecutive_misses` write the sidecar. |
| `src/backend/api/services/database.py` | The read path — `_FRESHNESS_JOIN` (the INNER JOIN that S3/S4 protect). |
| `scripts/tests/integration/test_job_freshness.py` | The same anti-drift invariants asserted in CI against a real scrape cycle. |
| `src/backend/docs/location-normalization-monitoring.md` | Sibling runbook: groups A–F of the same CLI. |
