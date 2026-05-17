# job_listings Composite PK — Deploy Runbook

This runbook covers the production deploy of the `job_listings` composite primary key swap (Units 1–3 of [PLAN.md](./PLAN.md)). The entire change ships as a **single PR**, backend-only.

---

## Overview & Critical Deploy Ordering

Single-PR backend-only change. No frontend / Vercel work to coordinate.

| Platform | What ships | Typical time to live |
|---|---|---|
| Railway (backend) | Units 1–2: composite PK migration (`ebb479b7eed5`), query-layer cutover, Greenhouse transformer drops the `greenhouse_` prefix, by-id route reshaped to `/{source_id}/{job_id}` | ~2–4 min build + boot |
| Vercel (frontend) | Nothing. `api/jobs.ts` proxies list queries only; `backendScraperClient.ts` does not call the by-id route. | — |

**The migration runs inside the FastAPI lifespan hook BEFORE the Procrastinate worker starts.** The order is explicit in `src/backend/api/main.py:67-151`:

1. `apply_alembic_migrations(settings.database_url)` — runs `ebb479b7eed5`, which strips the `greenhouse_` prefix from existing rows and swaps the PK to `(source_id, id)` in a single combined `ALTER TABLE`.
2. `procrastinate_app.open_async()` + `ensure_schema_async(...)`.
3. `init_pool(...)` for the API connection pool.
4. `auto_scraper_loop` task started.
5. `procrastinate_app.run_worker_async(queues=["greenhouse_fetch"], ...)` task started.

This means the first Greenhouse fan-out tick after deploy is guaranteed to see the composite PK in place. There is no window where the worker can issue an `ON CONFLICT (source_id, id)` upsert against a single-column-PK table or vice versa — both ship in the same lifespan boot.

Because the migration is gated by a `RAISE EXCEPTION` collision pre-flight, a bad data state aborts the lifespan loudly instead of corrupting the table. The boot fails, Railway flags the deploy unhealthy, and the prior container keeps serving until the rollback ships.

---

## Pre-Merge Checklist

- [ ] **Backend tests pass:** `cd src/backend && pytest` clean (includes the new `test_migration_job_listings_composite_pk.py`).
- [ ] **Frontend type-check + tests pass:** `npm run type-check && npm test` from repo root clean. The frontend touches none of these code paths, but run it as a regression guard.
- [ ] **Migration roundtrip clean locally:**
  ```bash
  cd src/backend
  alembic upgrade head
  alembic downgrade -1
  alembic upgrade head
  ```
  `ebb479b7eed5` must apply, revert, and re-apply against a real local Postgres without error.
- [ ] **Env vars unchanged.** Migration reuses `DATABASE_URL` — no new Railway secrets required.
- [ ] **CHANGELOG entry** drafted (per project ship workflow).

---

## Deploy Sequence

1. **Merge the PR to `main`.** Railway auto-deploys on merge.
2. **Watch Railway build logs.** Look for, in order:
   - `Applying database migrations...` (lifespan startup log line).
   - `apply_alembic_migrations: upgrade head` — running migration `ebb479b7eed5`. (If you see the `RAISE EXCEPTION` from the pre-flight collision guard fire here, the deploy fails fast — see "Symptoms → causes" below.)
   - `Procrastinate worker background task started (queues=['greenhouse_fetch'], concurrency=5)` — confirms the worker booted **after** the migration completed. Per `src/backend/api/main.py`, the worker task is created last in the lifespan startup block, so seeing this line means every step above it succeeded.
   - `Auto-scraper background task started` — confirms coexistence with the prior scraper loop.
3. **First Greenhouse fan-out tick after boot.** The periodic scheduler ticks every 30 min. When it fires (or when you manually trigger `/api/jobs-qa/trigger-greenhouse-fan-out` per the [greenhouseBackendMigration runbook](../greenhouseBackendMigration/DEPLOY.md#deploy-sequence)), confirm **no `UniqueViolation` errors** in the Railway logs. The new upserts key on `(source_id, id)`; a `UniqueViolation` here means the query layer didn't get the memo (see Symptoms below).

---

## Idempotency & Rebase Notes

The migration's pre-flight `RAISE EXCEPTION` guards (mirror of [`e6cbbb3c2f17`](../../../src/backend/alembic/versions/20260517_032024_e6cbbb3c2f17_drop_board_token_from_greenhouse_job_ids.py)) make it safe to re-run against any state:

- **`source_id IS NULL` guard** (upgrade): cheap insurance — `source_id` is already `NOT NULL` per the schema, but if some prior migration drift left a NULL through, the migration aborts before the destructive `UPDATE`.
- **Greenhouse-prefix UPDATE** is idempotent: `WHERE source_id = 'greenhouse_api' AND id LIKE 'greenhouse_%'` matches nothing on a re-run.
- **Composite-PK collision pre-flight** (upgrade): counts `(source_id, id)` duplicates *after* the rewrite. If any exist, RAISE and roll back the transaction. A retry sees the same state and aborts the same way until the underlying collision is resolved.
- **Re-prefix collision pre-flight** (downgrade): refuses to re-prefix Greenhouse rows if any non-Greenhouse row already uses the `greenhouse_<raw>` id shape. Symmetric with the upgrade guard.

If the migration has partially executed (e.g. the `UPDATE` landed but the `ALTER TABLE` failed for some unrelated reason), Alembic won't mark the revision complete, so the next deploy retries. The retry hits the same collision guard, which either passes (the `UPDATE` was idempotent) or aborts with the same descriptive error. **No manual cleanup runbook is required for the happy path** — the guards either let the migration through or stop it cold.

---

## Verification

### Scratch-DB collision test (pre-merge)

The migration roundtrip test [`src/backend/api/tests/test_migration_job_listings_composite_pk.py`](../../../src/backend/api/tests/test_migration_job_listings_composite_pk.py) covers all four behaviors against a real Postgres per-test scratch DB:

1. **Greenhouse id rewrite & non-Greenhouse rows untouched** — `test_greenhouse_id_rewrite_and_other_sources_untouched`.
2. **Composite PK enforced after upgrade** — `test_composite_pk_enforced_after_upgrade` (duplicate `(greenhouse_api, 12345)` raises `UniqueViolation`; `(other_source, 12345)` succeeds).
3. **Collision pre-flight aborts** — `test_upgrade_aborts_on_collision_preflight` (seeds two pre-migration rows that would collide after rewrite, asserts the migration RAISES and leaves the table unchanged with the single-column PK still in place).
4. **Downgrade reversibility** — `test_downgrade_round_trip_reversible` (`upgrade → downgrade -1 → upgrade` round-trip preserves data and PK shape).

The runbook does not re-spec these scenarios — point any future investigator at the test file.

### Post-deploy queries

Run against prod Postgres (use the `postgres-prod` MCP or `psql` with the Railway connection string).

**1. Greenhouse rows lost the legacy prefix:**

```sql
SELECT count(*) FROM job_listings
WHERE id LIKE 'greenhouse_%' AND source_id = 'greenhouse_api';
```

Expect: `0`. Any non-zero result means the `UPDATE` in `upgrade()` either didn't run or didn't match — investigate Railway logs for the migration step.

**2. Composite primary key is in place:**

```sql
SELECT conname, conkey
FROM pg_constraint
WHERE conrelid = 'job_listings'::regclass AND contype = 'p';
```

Expect: exactly one row, `conname = 'job_listings_pkey'`, with `conkey` of length 2 (the two `pg_attribute.attnum`s for `source_id` and `id`). A length-1 `conkey` means the `ALTER TABLE` didn't land — the deploy should have failed loudly earlier; investigate.

**3. Spot-check that upserts still write Greenhouse rows after the next fan-out tick:**

```sql
SELECT count(*) FROM job_listings
WHERE source_id = 'greenhouse_api'
  AND last_seen_at > now() - interval '1 hour';
```

Expect: non-zero and growing tick over tick. If 0 after a fan-out has run, the query layer is upserting against the wrong constraint — see Symptoms below.

---

## What to Look For If Things Go Wrong

### Symptoms → likely causes

| Symptom | Where to look | Likely cause |
|---|---|---|
| Railway deploy aborts on boot with `RAISE EXCEPTION … (source_id, id) PK collisions` | Railway build logs, search for `aborting` | Prod has duplicate `(source_id, id)` rows that would land after the prefix strip. **Do not bypass the guard.** Run the collision-counting query against prod, identify the offending rows, and decide whether to delete/merge before retrying the deploy. |
| Railway deploy aborts on boot with `RAISE EXCEPTION … NULL source_id` | Railway build logs | A drifted row has `source_id IS NULL` despite the `NOT NULL` constraint. Investigate where the NULL came from; backfill before retrying. |
| `UniqueViolation` on Greenhouse upsert after deploy | Railway logs grep: `UniqueViolation\|duplicate key`; check the failing query | Query layer didn't update — confirm `scripts/shared/database.py:_UPSERT_ON_CONFLICT` references `(source_id, id)`. If it still says `(id)`, Unit 1 didn't land cleanly; revert. |
| `GET /api/jobs/{job_id}` returns 404 for ids that worked yesterday | Frontend Network tab + Railway logs | Old by-id route shape is gone (Unit 2). The route is now `/api/jobs/{source_id}/{job_id}`. If anything in the frontend is hitting the old path, it shouldn't be — `api/jobs.ts` doesn't proxy by-id and `backendScraperClient.ts` doesn't call it. Investigate the caller. |
| Greenhouse rows in `job_listings` still carry the `greenhouse_` prefix after deploy | `SELECT count(*) … WHERE id LIKE 'greenhouse_%'` (see Verification §1) | Migration `ebb479b7eed5` didn't run. Check Railway boot logs for `apply_alembic_migrations: upgrade head` and the revision id. If the alembic_version table still shows `e6cbbb3c2f17` as current, the lifespan migration step failed silently — but it shouldn't (the lifespan re-raises any migration exception per `main.py:72-74`), so this should manifest as a failed deploy instead. |
| Procrastinate worker logs `Worker starting on queues: ['greenhouse_fetch']` BEFORE migration log | Railway logs ordering | This would mean lifespan ordering is broken — should not happen given `main.py:67-151`. If it does, do not proceed; revert and investigate. |

### Railway log greps

```bash
railway logs | grep -E "apply_alembic_migrations|RAISE EXCEPTION|UniqueViolation|Worker starting|aborting"
```

---

## Rollback

**Railway's deploy-rollback UI does NOT automatically run `alembic downgrade -1` — the operator MUST run it manually against prod (via Railway shell or `psql $DATABASE_URL`) BEFORE clicking the UI rollback button.** The lifespan hook in `src/backend/api/migrations.py` only calls `command.upgrade(cfg, "head")`; redeploying the prior container will land code that expects the single-column PK while the DB still has the composite one, breaking every upsert until the downgrade runs.

The migration's `downgrade()` body re-prefixes Greenhouse rows and restores the single-column PK in one combined `ALTER TABLE`, so a rollback is mechanical:

1. **Run the downgrade against prod Postgres** (via Railway shell or a `psql` with the prod `DATABASE_URL`):
   ```bash
   cd src/backend
   alembic downgrade -1
   ```
   This executes the downgrade pre-flight guard (refuses if any non-Greenhouse row has acquired a `greenhouse_<raw>` id in the interim — see Caveat below), runs the `UPDATE job_listings SET id = 'greenhouse_' || id WHERE source_id = 'greenhouse_api'`, then the combined `ALTER TABLE … DROP CONSTRAINT …, ADD PRIMARY KEY (id)`.
2. **Revert the merge commit:**
   ```bash
   git checkout main
   git pull
   git revert -m 1 <merge-sha>
   git push origin main
   ```
   The `-m 1` flag tells `git revert` to keep the `main`-side parent. Railway redeploys the prior container, which expects the single-column PK and the `greenhouse_` prefix — both restored by step 1.
3. **Verify rollback success:**
   - `SELECT count(*) FROM job_listings WHERE id LIKE 'greenhouse_%' AND source_id = 'greenhouse_api';` is now back to the original count (non-zero).
   - `SELECT conkey FROM pg_constraint WHERE conrelid = 'job_listings'::regclass AND contype = 'p';` shows `conkey` of length 1.
   - Next Greenhouse fan-out tick lands rows without `UniqueViolation`.

### Caveat: downgrade can RAISE

The downgrade pre-flight will RAISE if any non-Greenhouse row has, in the interim between the upgrade and the rollback, acquired an id matching `greenhouse_<raw>` shape (where `<raw>` collides with an existing Greenhouse id). This shouldn't happen — Google/Apple/Microsoft scrapers never emit ids starting with `greenhouse_` — but the guard exists as belt-and-suspenders. If it fires, do not bypass; investigate the rogue row first.

---

## See Also

- [PLAN.md](./PLAN.md) — full plan, Units 1–3 with locked decisions and architecture notes.
- [`src/backend/alembic/versions/20260517_213835_ebb479b7eed5_job_listings_composite_source_id_id_.py`](../../../src/backend/alembic/versions/20260517_213835_ebb479b7eed5_job_listings_composite_source_id_id_.py) — the migration itself, revision `ebb479b7eed5`.
- [`src/backend/api/tests/test_migration_job_listings_composite_pk.py`](../../../src/backend/api/tests/test_migration_job_listings_composite_pk.py) — migration roundtrip test (upgrade, composite-PK enforcement, collision pre-flight, downgrade reversibility).
- [`src/backend/api/main.py`](../../../src/backend/api/main.py) — FastAPI lifespan; confirms migration runs before the Procrastinate worker starts.
- [`docs/implementations/greenhouseBackendMigration/DEPLOY.md`](../greenhouseBackendMigration/DEPLOY.md) — exemplar runbook; admin-gated `/api/jobs-qa/trigger-greenhouse-fan-out` curl pattern for manually firing a fan-out tick post-deploy.
- [`docs/implementations/alembicMigration/DEPLOY.md`](../alembicMigration/DEPLOY.md) — combined-ALTER-TABLE rule that the upgrade/downgrade statements follow.
- Pre-flight `RAISE EXCEPTION` exemplar: [`src/backend/alembic/versions/20260517_032024_e6cbbb3c2f17_drop_board_token_from_greenhouse_job_ids.py`](../../../src/backend/alembic/versions/20260517_032024_e6cbbb3c2f17_drop_board_token_from_greenhouse_job_ids.py).
