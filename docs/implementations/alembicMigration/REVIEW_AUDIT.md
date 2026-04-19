# Alembic Migration PR Review Audit Log

**Purpose:** Running log of review findings and fixes on this PR. Read this before proposing changes — decisions here may override the original PLAN. Update when you apply a fix so the next reviewer has context.

---

## 2026-04-18 — Review pass 1

Dispatched in parallel: `pr-review-toolkit:code-reviewer`, `pr-review-toolkit:silent-failure-hunter`, `pr-review-toolkit:pr-test-analyzer`, `postgres-prod-verifier`, `railway-prod-verifier`. Vercel verifier not dispatched (diff touches no `api/*.ts`, `vercel.json`, `vercel.ts`, `next.config.*`, or `process.env.*` in Vercel-deployed paths — this PR is backend + scripts only).

### Code-review findings

**Critical:**
- `scripts/run_scraper.py:175-181` — single try/except conflates `apply_alembic_migrations` failure with `db.get_connection` failure, prints misleading `"Database connection failed"` regardless of cause, and loses Alembic's traceback. Operators chase wrong root cause on migration failures. (silent-failure-hunter C1)
- `scripts/run_scraper.py:51-54` — `try: from src.backend.api.migrations ... except ImportError: from api.migrations` catches ANY import failure (typos, missing deps, broken imports inside `migrations.py`) and fires the fallback, masking real bugs and potentially importing a stale shadow module. (silent-failure-hunter C2)
- `scripts/tests/conftest.py:168-183` — `except Exception: conn.rollback()` bare-catches every teardown failure with zero logging. Test tables leak unbounded across CI runs (thousands of `test_<hex>` tables accumulate in the shared `jobscraper` DB). Direct analog of the 2026-04-19 volume incident pattern. (silent-failure-hunter C3)
- `scripts/tests/integration/test_alembic_parity.py:172-187` — `except Exception: pass` on parity DB drop leaks entire databases (not just tables) on every failure. No log, no signal. (silent-failure-hunter C4)
- Missing test: FastAPI lifespan startup failure path. If `apply_alembic_migrations` raises, lifespan must propagate and prevent app from serving. No test enforces this; a future regression wrapping the call in try/except-log would silently serve broken deployments. (pr-test-analyzer C1)
- Missing test: `_resolve_alembic_paths` branch coverage. Three-fallback path logic (env override / dev / Docker) has only the dev branch exercised implicitly. Docker branch is completely untested; regression here surfaces only at prod container startup. (pr-test-analyzer C3)

**Important:**
- `src/backend/api/migrations.py:62-88` — `env` parameter is decorative (only used in log line). The real table suffix comes from `settings.scraper_environment`. If caller passes `env="prod"` while process `SCRAPER_ENVIRONMENT=local`, Alembic targets `alembic_version_local` against a prod DB silently. Same flag from code-reviewer #2 and silent-failure-hunter I1. (code-reviewer 2 / silent-failure-hunter I1)
- `src/backend/api/tests/conftest.py:52-94` and `scripts/tests/conftest.py:140-189` — `db_conn`/`postgres_db` fixtures mutate `os.environ["SCRAPER_ENVIRONMENT"]` and `api.config.ALLOWED_ENVIRONMENTS` directly without restoring original values in teardown. Leaks stale test env across test modules. (code-reviewer 1)
- `src/backend/api/migrations.py:31-56` — `_resolve_alembic_paths()` fallback order is silent; no log line distinguishes which branch won. Debugging a Railway startup failure requires shelling in to check file paths. (silent-failure-hunter I3)
- Missing test: baseline "`upgrade head` is no-op against stamped DB" invariant. The load-bearing DEPLOY.md claim ("operator stamps once, lifespan sees no-op") has no automated check. (pr-test-analyzer I1)
- Missing test: env-widening contract (`ALLOWED_ENVIRONMENTS |= {test_env}` + Settings rebuild). Three subtly different copies of the same pattern in three conftests; any regression silently targets `alembic_version_local`. (pr-test-analyzer I2)
- Missing test: fixture teardown resilience on mid-setup failure. Pytest's generator-teardown semantics skip cleanup on pre-yield exceptions → env-suffixed tables leak on Postgres-transient failures. (pr-test-analyzer I3)

**Suggestion / Nit:**
- `scripts/run_scraper.py:51-54` — narrow `ImportError` to `ModuleNotFoundError` + verify the missing module name matches the path prefix. (code-reviewer S1)
- `src/backend/api/migrations.py:37` — `len(_HERE.parents) > 3` guard is theoretically dead. (code-reviewer S2)
- `src/backend/api/db_models.py:44` — duplicate allow-list (`_ALLOWED_ENVS` + `api.config.ALLOWED_ENVIRONMENTS`) will drift. Architectural cleanup, out of scope. (code-reviewer S3)
- `src/backend/api/main.py:70-73` — pool-close shutdown error logged at `warning` without context. (silent-failure-hunter S1)
- Parity test leaks on `^C` interrupt. Local-dev ergonomic only. (pr-test-analyzer N1)

### Production-environment findings

**Critical:**
- Railway: `alembic_version_prod` does not exist on prod yet. The one-time `alembic stamp 91337142414f` step from `DEPLOY.md` §1–3 must execute before the PR merges, OR a paragraph must be added to `DEPLOY.md` explicitly permitting "stamp-on-first-deploy" for the empty baseline case. **Manual action required before merge.** (railway-prod-verifier)

**Important:**
- Railway: service has `healthcheckPath: null`. `DEPLOY.md:61` claims "container fails health check → Railway keeps prior deployment"; this is not what Railway will actually do today. Rollback on lifespan failure will require manual re-pin, not automatic fallback. Soften the runbook language. (railway-prod-verifier)
- `DEPLOY.md:67` — "The old image runs the legacy migration runner, which is idempotent against the post-5 schema" is only true if the rollback target has already applied 1–5. Tighten the claim. (code-reviewer S6)

**Suggestion:**
- Postgres: both `idx_users_prod_auth0_id` and the unique-constraint-implicit index `users_prod_auth0_id_key` exist on prod (redundant). Preserve in `db_models.py` to match prod (correct for baseline); consider dropping in a future autogenerated revision. (postgres-prod-verifier)
- Monitoring grep on old "Database schema up to date" log line will stop matching silently post-merge — confirm no external alert rules key off it. (railway-prod-verifier)

**Could not verify:**
- None. All three verifiers (postgres-prod, railway-prod) ran successfully. Vercel verifier intentionally skipped (no Vercel-relevant files in diff).

**Postgres schema parity (db_models.py vs prod, all match):** `job_listings_prod` 17 cols + 3 indexes; `scrape_runs_prod` TEXT timestamps preserved; `users_prod` both unique constraints + both redundant btree indexes; `user_enabled_companies_prod` composite PK + FK CASCADE + TIMESTAMPTZ default. Zero divergence. Baseline revision `91337142414f` accurately anchors prod. Verdict from postgres-prod-verifier: **safe to merge after operator stamp**.

**Volume context (for DEPLOY.md Rule 2):** `job_listings_prod` is 12,595 rows / 137 MB today; full-table rewrite costs ~137 MB headroom. `scrape_runs_prod` 4,330 rows / 1 MB. Volume headroom is fine for the baseline (zero DDL).

### Deferred (not fixing this pass)

- Parity test soundness hole: `Base.metadata` is on both sides of the `create_all` + autogenerate comparison; it catches model-vs-autogen drift but not model-vs-real-prod drift. Acknowledged in PLAN Unit 6 rewrite; the original stronger invariant cannot be restored because the old runner is deleted. Mitigation: `postgres-prod-verifier` confirms parity today, and operator-run `alembic stamp` is a one-time check. (pr-test-analyzer C2)
- `db_models._resolve_env()` silently defaults to `"local"` when `SCRAPER_ENVIRONMENT` is unset. Same default is in `api.config.Settings`; documented in `src/backend/CLAUDE.md` as intentional for dev UX. Making it mandatory would break `docker compose up postgres && pytest` for contributors. Not fixing in this PR. (silent-failure-hunter I2)
- Function-scoped fixture performance (`scripts/tests/conftest.py`). Correctness-irrelevant; leave for a follow-up perf PR. (code-reviewer 3)
- Dev-layout path detection collision risk in `_resolve_alembic_paths`. Low probability; fix would complicate the function. Defer unless the logging fix (I3) doesn't disambiguate enough. (code-reviewer 4)
- Duplicate allow-list in `db_models.py` vs `api.config`. Architectural import-cycle concern; separate refactor. (code-reviewer S3)
- Baseline revision Revises: trailing whitespace. Cosmetic template artifact. (code-reviewer S5)
- Offline-mode Alembic path (`run_migrations_offline`) untested. Not used in lifespan or runbook. (pr-test-analyzer N3)
- `ScrapeRun.started_at` TEXT assertion missing. PLAN.md non-goal explicitly locks this. (pr-test-analyzer N4)
- Railway healthcheck configuration. Out of scope (infra change, not code). Noted as follow-up.

### Implementation applied

Fix agent landed all Critical + Important findings from this pass (Suggestion/Nit and Deferred items left alone per scope). Both test suites green: `cd src/backend && pytest api/tests -q` → 173 passed; `cd scripts && pytest tests/ -q` → 366 passed.

**Commits (chronological):**

1. `ce897b7` — Review pass 1: separate scraper migration vs DB-connect errors
   - `scripts/run_scraper.py` (Fix 1: split try/except, distinct exit codes 2 vs 3, logger.exception in each branch; Fix 2: narrow `ImportError` to `ModuleNotFoundError` with `e.name` check so bugs inside `migrations.py` don't get masked by the docker-layout fallback)

2. `505d514` — Review pass 1: log/raise teardown leaks and restore env vars
   - `scripts/tests/conftest.py` (Fix 3: per-table try/except + `drop_errors` accumulator + `RuntimeError` raise; Fix 7: capture/restore `SCRAPER_ENVIRONMENT`, `DATABASE_URL`, `ALLOWED_ENVIRONMENTS`, `api.config.settings`)
   - `scripts/tests/integration/test_alembic_parity.py` (Fix 4: replaced `except Exception: pass` on parity-DB drop with `logging.getLogger(__name__).error(...)` naming the leaked DB)
   - `src/backend/api/tests/conftest.py` (Fix 6: capture/restore env vars + rebuild `_api_config.settings` singleton at teardown end)

3. `e45402d` — Review pass 1: env-mismatch guard + lifespan & path resolution tests
   - `src/backend/api/migrations.py` (Fix 5a: `logger.info` for resolved paths after `_resolve_alembic_paths`; Fix 5b: `RuntimeError` if `os.environ["SCRAPER_ENVIRONMENT"] != env` argument)
   - `src/backend/api/tests/test_main_lifespan.py` **new** (Fix 8: happy-path asserts `apply_alembic_migrations` called with settings.* and BEFORE `init_pool`; failure-path asserts lifespan propagates and `init_pool`/`close_pool` are not called)
   - `src/backend/api/tests/test_migrations_paths.py` **new** (Fix 9: 5 tests covering env override, partial override fallthrough, dev layout, Docker layout, and FileNotFoundError on no-layout-no-env-vars)

4. `7efbaef` — Review pass 1: tighten DEPLOY.md rollback safety claims
   - `docs/implementations/alembicMigration/DEPLOY.md` (Fix 10a: rollback section now warns rollback target must already have run against post-5 schema — do not rollback to pre-migration-5 image without operator review; Fix 10b: deploy sequence + failure modes now reflect that `healthcheckPath: null` means Railway does NOT auto-retain prior deployment, recovery requires manual UI re-pin)

**Do not revert (new in this pass):**

- `apply_alembic_migrations(database_url, env)` is now a strict contract: caller MUST set `SCRAPER_ENVIRONMENT` to match `env` before calling. A future "convenience" PR that mutates `os.environ["SCRAPER_ENVIRONMENT"] = env` inside this function would re-introduce the silent-target-mismatch class of bug. The mismatch must continue to raise — env ownership stays with the caller (FastAPI Settings, scraper CLI driver).
- `scripts/run_scraper.py` exit codes 2 and 3 are now load-bearing for any subprocess driver / cron wrapper that distinguishes "DB unreachable" (transient, retry) from "migration broken" (systemic, page operator). Don't collapse them back into a single exit code.
- `src/backend/api/tests/conftest.py::db_conn` and `scripts/tests/conftest.py::postgres_db` env-restore blocks are required for cross-module test isolation. A future "speed up tests" PR that deletes them would re-introduce the leakage flagged by code-reviewer 1.
- `_resolve_alembic_paths` branch tests (`test_migrations_paths.py`) monkeypatch `migrations._HERE` directly. If `_HERE` ever moves out of module scope (e.g. into a function-local), update the tests — but DON'T delete them; the Docker branch is otherwise un-exercised before prod startup.

**Manual action required before merge:**
- Operator must run `alembic stamp 91337142414f` against prod per `DEPLOY.md` §1–3 **before** merging. This is the one-time stamp that anchors prod at the empty baseline. If merged without the stamp, the first deploy will harmlessly apply the baseline (empty `upgrade()`) and write the version row itself — which works today but the runbook's invariant is "stamp first, upgrade is always no-op."
