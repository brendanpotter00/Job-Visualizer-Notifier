# Perf Wave 2 — Plan (C2 `primary_country` + C3 `search_text`)

**Branch:** `feat/perf-wave2` (off main `c800bcb3`). **Alembic head / new `down_revision`:** `cfa099f2e1e0` (confirmed via `.venv/bin/alembic -c alembic.ini heads`). Single head. Lands on a PR for human review — **do not merge, commit only in the final stage.**

Scope = the two greenlit denormalizations from the audit:

- **C2** — denormalize `primary_country` onto `job_listings` + a partial compound keyset index → fix the #1 slow endpoint (`location=United States`, 2.08 s: the planner mis-estimates the cross-table location `EXISTS` 139× and drops the keyset index).
- **C3** — denormalize `search_text` onto `job_listings` + one GIN trigram index → fix keyword search (the 4-way OR across 2 tables cannot use a per-column trigram).

Out of scope: freshness index (C1, already shipped in `a1f7c9d2e8b4`), caching, count deferral (Wave-1 B1, already shipped — `filtered_total` already returns `None`, so **C2/C3 never touch the count path**).

---

## 0. The headline — correctness under partial population AND multi-country

Both columns start **NULL** (catalog-only ADD) and get filled by new writes + a lazy backfill. A query that *seeks* on them would be **wrong for not-yet-filled rows**. Separately, I measured a second correctness hazard the audit did not flag: a **scalar** `primary_country` cannot represent a job that sits in two countries.

**Prod reality (measured live, 2026-09-04, 38,786 OPEN):**

| bucket | count | share of OPEN |
|---|---|---|
| single non-remote country == US | **24,826** | 64.0 % |
| single non-remote country (any) | 31,698 | 81.7 % |
| **≥2 distinct non-remote countries (multi)** | **649** | 1.7 % |
| remote-only / no country tag | 2,373 | 6.1 % |
| no location tag at all (unnormalized/failed) | 4,070 | 10.5 % |

`location=United States` matches 25,039 rows today; **24,826 of them (99.1 %) are single-country-US** and land on the fast path. The other 213 are multi-country-US.

**Chosen strategy = (b), the NULL-fallback, extended to cover multi-country — NOT gating.** One mechanism solves both hazards and needs no "is the backfill done?" flag or deploy coordination:

- `primary_country` = the job's **single** distinct non-remote ISO country, or **NULL** when a scalar can't answer faithfully (zero non-remote countries, **or ≥2** → NULL, or not-yet-backfilled). NULL means exactly "the fast column cannot answer for this job — use the EXISTS."
- The country-tier predicate keeps the **original cross-table `EXISTS` as a fallback for NULL rows only**:
  ```
  ( job_listings.primary_country = %s )
  OR ( job_listings.primary_country IS NULL AND <original country-tier EXISTS> )
  ```
- Same shape for keyword: `search_text ILIKE %s OR (search_text IS NULL AND <original 4-way OR>)`.

This is **provably parity-exact** with today's predicates (proof in §5), correct from the instant the migration lands, and self-heals as the backfill/new-writes drive NULLs toward zero. `test_server_results_match_client_filter_oracle` stays the guard and must pass unchanged.

**Why not gating (strategy a):** it needs a "backfill complete" flag + a deploy where the flag flips, and a scalar *still* can't answer multi-country even after a full backfill — so gating alone is both more coordination *and* still wrong for the 649. The fallback is strictly simpler and strictly more correct.

**Why the fast path still wins with an OR (the crux, measured):** `primary_country='US'` has **real column stats** (~64 % selectivity), so `(primary_country='US' OR (IS NULL AND EXISTS…))` estimates ≥64 % regardless of the un-estimable EXISTS. The planner therefore keeps the **ordered backward walk of `idx_job_listings_open_first_seen_keyset` + a heap `Filter`** and early-stops at the LIMIT — I confirmed this exact plan shape on prod for the analogous `enrichment_category = ANY(...)` case (Index Scan Backward, no Sort, 610 rows removed by filter, **3.4 ms**). The EXISTS is gated behind `IS NULL`, so it runs only for the few NULL rows encountered before the page fills (~155 rows walked for a 100-row US page). 631 ms → single-digit ms, and the un-estimable EXISTS is no longer the dominant term.

---

## 1. Migration — `src/backend/alembic/versions/<ts>_<rev>_add_primary_country_and_search_text.py`

`down_revision = 'cfa099f2e1e0'`. Autogenerate the file (`alembic revision --autogenerate` after editing `db_models.py` per §6), then hand-adjust the index builds to `CONCURRENTLY` and add the retry-safety guards — the established idiom in `a1f7c9d2e8b4` / `08765ce81d35`.

**upgrade():**

```python
# 1) Catalog-only ADD — nullable, NO default, NO backfill (2026-04-18 volume incident).
#    ONE combined ALTER TABLE (principles §10 / combined-ALTER rule). IF NOT EXISTS
#    for retry-safety since the CONCURRENTLY steps below commit outside this tx.
op.execute("SET LOCAL lock_timeout = '5s'")
op.execute(
    "ALTER TABLE job_listings "
    "ADD COLUMN IF NOT EXISTS primary_country text, "
    "ADD COLUMN IF NOT EXISTS search_text text"
)

# 2) Indexes built CONCURRENTLY, OUTSIDE the migration transaction (job_listings
#    is on the scrape write path). autocommit_block + IF NOT EXISTS = retry-safe
#    (a failed CONCURRENTLY build can leave an INVALID index of the same name).
with op.get_context().autocommit_block():
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_job_listings_open_country_keyset "
        "ON job_listings (primary_country, first_seen_at, source_id, id) "
        "WHERE status = 'OPEN'"
    )
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_job_listings_search_text_trgm "
        "ON job_listings USING gin (search_text gin_trgm_ops)"
    )
```

**downgrade()** — real, reversible: drop both indexes `CONCURRENTLY IF EXISTS` in an `autocommit_block`, then `op.execute("SET LOCAL lock_timeout='5s'")` + `ALTER TABLE job_listings DROP COLUMN IF EXISTS search_text, DROP COLUMN IF EXISTS primary_country`.

**Notes.**
- **`primary_country`** keyset index mirrors the category-keyset shape (equality leading, sort tuple `(first_seen_at, source_id, id)` trailing, partial `WHERE status='OPEN'`, plain-ASC → backward scan). At build time the column is all-NULL; btree indexes NULLs, so it's ~38k OPEN entries and the backfill later moves each row NULL→country (cheap, ~38k btree updates).
- **`search_text`** GIN needs `pg_trgm` — already installed prod-side (job_tags trigram, `536c1cddcd28`). GIN does **not** index NULLs, so the concurrent build on an all-NULL column is trivially fast; the backfill populates it incrementally.
- **CONCURRENTLY here, unlike `08765ce81d35`** (which was plain): that one built a ~1.6 MB index on the 4 narrow keyset columns in sub-second and chose the all-or-nothing transaction. Here the GIN on a text column is comparatively heavy to maintain and `job_listings` is 859 MB / on the write path, so both builds go concurrent — matching `a1f7c9d2e8b4`'s reasoning for the freshness DROP.

---

## 2. Backfill — separate, bounded-batch, run **post-deploy** (never in the ALTER)

A standalone idempotent script, **not** an in-migration UPDATE and **not** blocking Railway startup. The query paths are correct under NULL (§0 fallback), so backfill runs at leisure after deploy; as NULLs drain, the EXISTS/ILIKE fallback fires less and perf improves monotonically. No gating flag.

**File:** `scripts/backfill_wave2_denorm.py` (run manually: `PYTHONPATH=. .venv/bin/python scripts/backfill_wave2_denorm.py`). Re-runnable; each batch commits.

**Loop (both columns, OPEN rows first — that's what the hot endpoints read):**
```
batch_size = 2000
loop:
  UPDATE job_listings jl
     SET primary_country = <PRIMARY_COUNTRY_EXPR>,      -- §4
         search_text     = <SEARCH_TEXT_EXPR>           -- §4
   WHERE (jl.source_id, jl.id) IN (
       SELECT source_id, id FROM job_listings
       WHERE status='OPEN' AND (primary_country IS NULL OR search_text IS NULL)
       -- NOTE: this WHERE re-selects rows a *legitimately*-NULL primary_country
       -- would keep re-touching (remote-only / multi). Gate on search_text IS NULL
       -- alone for the OPEN pass, then a final one-shot primary_country pass keyed
       -- on a sentinel/`backfilled` marker OR simply accept idempotent re-touch is
       -- bounded by the batch loop terminating when 0 search_text rows remain.
       LIMIT batch_size
       FOR UPDATE SKIP LOCKED
   );
  commit; sleep(0.1)
  stop when 0 rows updated
```
Two practical refinements the IMPLEMENT stage should pick one of, to avoid the "primary_country legitimately NULL re-selected forever" trap: **(i)** drive the loop off `search_text IS NULL` only (every row gets a non-null search_text, so the loop terminates), setting `primary_country` in the same UPDATE — remote-only/multi rows just get NULL and are never re-selected because their `search_text` is now set; **(ii)** then a second, separate bounded pass for CLOSED rows if desired (low priority — the hot indexes are partial on OPEN). Recommend **(i)**. Batch 2000, `FOR UPDATE SKIP LOCKED` so it never fights a live scrape write, `sleep(0.1)` between batches to bound WAL/lock pressure (principles §7).

Cost: ~38k OPEN rows, each `search_text` recompute runs one `string_agg` subquery on `job_tags` (indexed by the composite PK prefix). Minutes, not hours. Optionally `REINDEX INDEX CONCURRENTLY idx_job_listings_open_country_keyset` after to tighten the btree churned NULL→country (nice-to-have, not required).

---

## 3. Derivation — exactly how each column is computed

### `primary_country`  (from the job's normalized locations — country tier)
```sql
-- The single distinct non-remote ISO country of this job's location tags,
-- or NULL when a scalar can't answer (0 countries, or ≥2 → NULL). NOT tied to
-- is_primary: a job whose is_primary tag is remote but which has a non-remote
-- secondary tag must still resolve to that country.
(SELECT CASE WHEN count(DISTINCT upper(l.country)) = 1
             THEN max(upper(l.country)) END
   FROM job_locations j2
   JOIN locations l ON l.id = j2.normalized_location_id
  WHERE j2.job_listing_id = jl.id
    AND l.kind <> 'remote' AND l.country IS NOT NULL)
```
`count = 0` → aggregate over empty set → CASE ELSE → NULL. `count = 1` → that country. `count ≥ 2` → NULL (folds "multi" into the NULL fallback bucket). `upper()` matches the tier predicate's `upper(l.country)`.

### `search_text`  (title + raw location + company + tags)
```sql
lower(
  coalesce(jl.title,'')    || ' ' ||
  coalesce(jl.location,'')  || ' ' ||   -- RAW location text (the frontend haystack field), not normalized locations
  coalesce(jl.company,'')   || ' ' ||
  coalesce((SELECT string_agg(t.tag, ' ' ORDER BY t.tag)
              FROM job_tags t
             WHERE t.source_id = jl.source_id AND t.job_listing_id = jl.id), '')
)
```
Mirrors the client haystack `matchesSearchTags` builds (`[title, location, ...tags]`) + `company` (the endpoint already searches company; parity comment in `job_search.py:143`). `department`/`team` deliberately excluded — matches the deployed client (see the long note at `job_search.py:126`). Lower-cased once so the `ILIKE` degrades to a plain trigram substring test; escaping of the *term* stays exactly as `_like_pattern` does today. **Always recomputed from scratch** (never appended-to) so title/location edits and tag deletes can't leave stale text.

---

## 4. Write-path — where to compute + set both columns (preserve all existing behavior)

`scripts/shared/database.py` is the single writer for `job_listings` content (both the backend `fetch_*_company` tasks and the standalone scrapers funnel through `insert_job` / `upsert_job` / `*_batch`). But **`primary_country` and `search_text` depend on data written by *other* async pipelines** (job_locations by normalization; job_tags by enrichment), so the write hooks are in three places, mirroring the existing `_upsert_freshness` pattern (a helper called after the main upsert, same transaction, no commit).

### 4a. `search_text` — recompute wherever title/location/company/tags change

| Site | File / fn | What changes | Action |
|---|---|---|---|
| **Scraper upsert** | `scripts/shared/database.py` — `upsert_job`, `upsert_jobs_batch`, `insert_job`, `insert_jobs_batch` | title/location refreshed on `ON CONFLICT` | Add `_recompute_search_text(cursor, jobs)` called right after the upsert + `_upsert_freshness`, same tx. Bulk `UPDATE … SET search_text = <expr> WHERE (source_id,id) IN %s` over the upserted keys. **Do NOT** add `search_text` to `_JOB_COLUMNS`/`_build_job_values` (it's derived, not a scalar input; keeps the placeholder-lockstep contract intact). |
| **Enrichment write-back** | `src/backend/api/services/enrichment_writer.py` — `apply_result` (INSERT/DELETE `job_tags`, lines 199/218/242, both publish and demote branches) | tags added/dropped | After the tag writes, recompute `search_text` for that one `(source_id, id)` in the same tx (before the function returns). |
| **Admin correct / reenrich** | `src/backend/api/services/enrichment_monitor.py` (DELETE/INSERT `job_tags`, lines 397/402/563) | tags rewritten by an admin | Same one-row recompute after the tag writes. |
| Custom-company teardown | `custom_companies_service.py:1389` (`DELETE FROM job_tags WHERE source_id=%s`) | all tags for a source dropped | **Verify:** this is company-deletion teardown that also deletes the `job_listings` rows → no recompute needed. Confirm the jobs are deleted in the same path; if any survive, recompute there too. |

Put the recompute SQL expression in **one shared constant** (e.g. `_SEARCH_TEXT_EXPR` in `scripts/shared/database.py`, imported by the backend services) so all sites stay identical. New-job inserts: a brand-new job has no `job_tags` yet, so the subquery yields `''` and `search_text` = title+location+company — correct at that moment; enrichment recomputes it (with tags) later.

### 4b. `primary_country` — recompute wherever `job_locations` changes

Normalization is a *separate* async pipeline (`tasks/normalize_location.py`), so the scraper upsert can't set `primary_country` (no normalized locations exist yet at INSERT) — it stays NULL and the §5 EXISTS fallback covers the row until normalization runs.

| Site | File / fn | Action |
|---|---|---|
| **Tier-1 cache hit** | `location_normalization.py` — `write_job_locations_from_ids` | after the `job_locations` REPLACE + `normalization_status='done'` UPDATE, add `UPDATE job_listings SET primary_country = <expr> WHERE id = %s` (keys on `id` alone, exactly like the existing statements in this fn). No commit — the task owns the tx. |
| **Tier-2 LLM write** | `location_normalization.py` — `persist_llm_result` | same recompute after its `job_locations` REPLACE. Reached by both `normalize_location` (task) and `enrichment_writer.apply_result` (which calls `persist_llm_result`), so both converge. |

Put `primary_country`'s expression in one shared constant too. Both writers already end with an `UPDATE job_listings … WHERE id=%s`, so this is one extra statement in the same cursor/tx — behavior-preserving.

### 4c. `db_models.py` + create_all/pg_trgm
- Add to `JobListing`: `primary_country = Column(Text, nullable=True)`, `search_text = Column(Text, nullable=True)` (both nullable, no default — catalog-only, matching the `experience_level`/`enrichment_*` precedent).
- Add the two `Index(...)` entries to `JobListing.__table_args__`: the partial compound (`postgresql_where=text("status = 'OPEN'")`) and the GIN (`postgresql_using="gin"`, `postgresql_ops={"search_text": "gin_trgm_ops"}`) — declared normally; CONCURRENTLY is migration-only, like `idx_job_tags_tag_trgm`.
- **Add a `before_create` pg_trgm hook on `JobListing.__table__`** (idempotent `CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public`), mirroring the existing `JobTag` hook — otherwise `create_all` in the test/parity bootstrap fails on `gin_trgm_ops` if `job_listings` is created before `job_tags`.
- The parity test (`test_alembic_parity`) then round-trips model ↔ migration; autogenerate the migration *from* these model edits so they match.

---

## 5. Query rewrites — `src/backend/api/services/job_search.py`

Two predicates change; **everything else (region/city tiers, `since`, cursor, company/category/level, the private/hidden-company guards, ordering) stays byte-identical.** The count path is untouched (already deferred).

### 5a. Country tier — `_tier_condition` / `_location_predicate`
Today the whole location filter is one `EXISTS` over the pre-resolved `normalized_location_id` set (`_location_predicate`), and `resolve_location_ids` walks the hierarchy once against the 1,186-row `locations` catalog. **Keep all of that** for region/city/remote tiers and for the exact-`canonical_name` fallback — it's correct and those tiers match far fewer rows, so the planner behaves.

Add a **country-tier fast path**, applied per country-tier selection whose descriptor has a concrete `country`, in `build_search_where`'s `if locations:` branch:
```
( job_listings.primary_country = %s
  OR ( job_listings.primary_country IS NULL AND <country-tier EXISTS for this selection> ) )
```
where `<country-tier EXISTS>` is the *existing* `EXISTS(SELECT 1 FROM job_locations jl JOIN locations l … WHERE l.kind<>'remote' AND upper(l.country)=%s)` shape (the same one `resolve_location_ids` currently front-loads). Because the location filter is `loc(sel₁) OR loc(sel₂) OR …`, each country-tier selection contributes its own `(fast OR (NULL AND exists))` disjunct, ORed with the other selections — same distribution the current id-set union relies on.

Implementation shape: extend the request-time resolution so a country-tier selection carries both its `country` code (for `primary_country = %s`) **and** its member `location_ids` (for the fallback `EXISTS`, reusing `_location_predicate`'s int-array probe restricted to that selection). Non-country tiers (region/city/remote) and the exact-name fallback keep the pure id-set EXISTS unchanged.

**Parity proof (matches today's "job has a non-remote tag with country X"):**
- single-country == X → `primary_country = X` → branch 1 ✓
- single-country ≠ X → `primary_country ≠ X`, not NULL → excluded ✓
- multi-country → `primary_country = NULL` → branch 2 EXISTS decides (true iff it has an X tag) ✓
- remote-only / no country → `primary_country = NULL` → branch 2 EXISTS false → excluded ✓
- **not-yet-backfilled** → `primary_country = NULL` → branch 2 EXISTS decides correctly ✓

### 5b. Keyword — `_KEYWORD_PREDICATE` / `_keyword_condition`
Replace the per-term 4-way OR with:
```
( job_listings.search_text ILIKE %s ESCAPE '\'
  OR ( job_listings.search_text IS NULL AND <existing 4-way OR predicate> ) )
```
The existing 4-way OR (title/location/company + `job_tags` EXISTS) stays verbatim as the `IS NULL` fallback. Binds: one pattern for the `search_text ILIKE`, plus the four the current predicate already binds (so 5 copies of the pattern per term; `_keyword_condition` updates its param count). Exclude terms wrap in `NOT (...)` exactly as now — and note `search_text` is built with `coalesce`s so it is **never NULL for a backfilled row**, which keeps `NOT (…)` from the null-drops-the-row hazard the `COALESCE(location,'')` comment at `job_search.py:151` documents (the fallback branch still needs its existing `COALESCE`).

Parity: a backfilled `search_text` contains title‖location‖company‖tags lower-cased, so `search_text ILIKE '%term%'` matches iff any of those substrings match — identical to the OR, modulo the one already-documented divergence (per-field vs one joined string: a term straddling a field boundary now *can* match across the join, which is a superset the audit already noted at `SCHEMA-AUDIT.md` Finding 3 and is harmless). NULL rows fall to the exact old predicate.

**Verification gate (IMPLEMENT stage):** `EXPLAIN (ANALYZE, BUFFERS)` on prod-shape data for (a) `location=United States` — confirm Index Scan Backward on `idx_job_listings_open_first_seen_keyset` + `Filter` (or a country-keyset seek), **no top-N sort of 25k rows**; (b) a rare country — confirm it doesn't regress badly under the OR (acceptable even if it filters the walk, since rare countries match few rows); (c) a keyword term — confirm a `Bitmap Index Scan on idx_job_listings_search_text_trgm`. The `< 3-char` term blind spot (`go`/`ai`/`ml`) persists (no complete trigram) and is fine — it falls to the fallback only on NULL rows; on backfilled rows the trigram simply can't be used and it's a filter, same cost class as today.

---

## 6. Tests / gates
- `test_server_results_match_client_filter_oracle` (the parity oracle) — **must pass unchanged**; add fixture rows exercising multi-country, remote-only, and NULL-`primary_country`/`search_text` jobs so the fallback branches are covered.
- `test_alembic_parity` (autogenerate round-trip) — passes after the `db_models.py` edits + autogenerated migration.
- Captured-SQL tests for `/api/jobs/search` (the module has them) — update expected SQL for the two predicates.
- New unit tests: `primary_country`/`search_text` derivation (single/multi/remote/none), and that each write-path site recomputes (scraper upsert, enrichment apply_result, admin correct, normalization writers).
- Backend pytest needs a throwaway clean DB (stale-alembic gotcha). Redirect test/build output to a file, never pipe through `tail`. Node 22.14.0 if any FE check runs.

## 7. Decisions made (flagging for the human reviewer)
- **Multi-country (649 OPEN, 1.7 %) fold into NULL, not a `'MULTI'` sentinel** — simpler predicate, same correctness (both route to the EXISTS fallback). Chosen over a sentinel because NULL already needs the fallback for freshness, so one branch covers both.
- **Fallback (strategy b), not gating (strategy a)** — correct from deploy, no flag, and gating still couldn't fix multi-country anyway.
- **Backfill = post-deploy standalone script, not in the migration** — columns are nullable + fallback-correct, so backfill is lazy and non-blocking.
- **`primary_country` derived from ALL non-remote tags, not the `is_primary` tag** — avoids the remote-primary-with-geographic-secondary miss.
- **Residual risk to verify in IMPLEMENT:** the country-tier OR could, for a *rare* country, stop the planner from using the new `idx_job_listings_open_country_keyset` seek and make it filter the first_seen walk. Bounded (rare countries match few rows) and gated by the EXPLAIN gate in §5b; the US case — the actual 2.08 s endpoint — is proven fast.
