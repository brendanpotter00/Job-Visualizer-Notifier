# Row-Level Security (RLS) — Findings & Future Implementation Plan

> Status: **Investigation only — nothing implemented.** This doc captures what
> we found in production and how RLS *would* be implemented later. It exists so
> the work is tracked when user-created dashboards make it worthwhile.
>
> Investigated: 2026-06-07 (during PR #114, "lock down Railway backend").

## 1. Context & trigger

Today, isolation of per-user data is **application-level only**: every user-scoped
route validates a JWT (`get_current_user`), resolves it to an internal `users.id`,
and queries filter explicitly (`WHERE user_id = %s`). There is **no database-level
backstop** — if any future query forgets the filter, it leaks another user's rows.

This is fine at the current scale (3 user-owned tables, all hand-audited). The
trigger to add RLS is the planned feature where **users create their own
dashboards / custom objects**. Once users own arbitrary rows across new tables, a
single forgotten `WHERE user_id = …` becomes a cross-tenant data leak. RLS makes
the database itself refuse to return other users' rows — defense in depth.

**Recommendation:** adopt RLS *alongside the first user-owned dashboard table*, not
as a retrofit later. It is far cheaper to introduce with one new table than across
a sprawl of endpoints. This doc is the pre-work for that moment.

## 2. Evidence from live production (2026-06-07)

All queries run against prod via the read-only `claude_readonly` MCP role.

### 2a. RLS is off everywhere; zero policies

```sql
SELECT c.relname, c.relrowsecurity AS rls_enabled, c.relforcerowsecurity AS rls_forced
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'r' AND n.nspname = 'public' ORDER BY c.relname;
```

→ `rls_enabled = false`, `rls_forced = false` for **all 13 tables**
(`admins`, `alembic_version`, `companies`, `feature_upvotes`, `features`,
`job_listings`, `procrastinate_events`, `procrastinate_jobs`,
`procrastinate_periodic_defers`, `scrape_runs`, `user_enabled_companies`,
`users`, `worker_heartbeats`).

```sql
SELECT * FROM pg_policies;   -- → [] (no policies defined)
```

### 2b. The app connects as the `postgres` superuser

```sql
SELECT usename, application_name, count(*)
FROM pg_stat_activity WHERE datname = current_database()
GROUP BY usename, application_name;
```

| connected_role | application_name       | connections |
| -------------- | ---------------------- | ----------- |
| `postgres`     | `procrastinate_worker` | 5           |
| `postgres`     | `fastapi_pool`         | 1           |
| `claude_readonly` | *(MCP audit)*       | 1           |

Both the API request pool (`fastapi_pool`) and the background worker
(`procrastinate_worker`) connect as **`postgres`**.

### 2c. `postgres` bypasses RLS and owns the tables

```sql
SELECT rolname, rolsuper, rolbypassrls, rolcanlogin
FROM pg_roles WHERE rolcanlogin = true;
```

| rolname           | superuser | bypassrls | can_login |
| ----------------- | --------- | --------- | --------- |
| `postgres`        | **true**  | **true**  | true      |
| `claude_readonly` | false     | false     | true      |

```sql
SELECT c.relname, pg_get_userbyid(c.relowner) AS owner
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relname IN
  ('users','feature_upvotes','user_enabled_companies','admins');
```

→ all four owned by `postgres`. The only two login roles are `postgres`
(superuser/owner) and `claude_readonly` (read-only audit).

## 3. Why naive RLS is a NO-OP here

Postgres RLS has two hard bypasses:

1. **Superusers** ignore every RLS policy, unconditionally.
2. Roles with **`BYPASSRLS`** ignore every policy.

`FORCE ROW LEVEL SECURITY` overrides only the **table-owner** bypass — it does
**not** override the superuser/`BYPASSRLS` bypass.

Since the app connects as `postgres` (superuser **and** `BYPASSRLS` **and** owner),
**`ENABLE ROW LEVEL SECURITY` + policies would change nothing** — every query still
sails straight through. Adding it today would be security theater: a control that
looks real but enforces nothing, creating false confidence.

**RLS cannot protect anything until the app stops connecting as `postgres`.**

## 4. Per-user tables & query semantics (what shapes the policies)

Source of truth: `src/backend/api/db_models.py`. All user ids are `Text` (UUID hex).

| Table | Scoping column | Access pattern | Policy implication |
| --- | --- | --- | --- |
| `users` | `id` (PK) | looked up by `email`/`auth0_id` **before** internal id is known (login resolution, `user_service.get_or_create_user`); read in aggregate by admin stats | Restrictive RLS here breaks login + admin dashboard. Needs an admin bypass and/or a policy keyed on the JWT subject GUC, not the internal id. |
| `feature_upvotes` | `user_id` (FK) | **aggregate read** for public upvote counts (`COUNT(u.user_id)`, `features_service.py`); per-user INSERT/DELETE | SELECT must stay **open** (counts are public) — only INSERT/DELETE scoped to owner. Command-specific policies, not a blanket `USING`. |
| `user_enabled_companies` | `user_id` (FK) | always `WHERE user_id = %s` (`user_preferences_service.py`) | Cleanest case: simple `USING/WITH CHECK (user_id = current_app_user_id())`. |
| `admins` | `user_id` (FK) | already HTTP-gated by `require_admin`; read in aggregate for the user roster | RLS optional (belt-and-suspenders). HTTP gate is already sufficient. |

**Background paths do not touch these tables** — Procrastinate worker tasks and
the scrapers only write `companies`, `job_listings`, `scrape_runs`,
`procrastinate_*`, `worker_heartbeats`. So RLS on the four user tables won't affect
worker/scraper code (but see §5 — they'd still be affected by a role swap because
they share `DATABASE_URL`).

Key takeaway: a *correct* policy set is **command-specific**, not a single blanket
rule. A naive `USING (user_id = current_user)` on `feature_upvotes` would reduce
public upvote counts to the caller's own votes — a functional regression.

## 5. Future implementation design (the real rollout)

### 5a. Provision a non-superuser app role

```sql
-- Run once as postgres
CREATE ROLE app_user LOGIN PASSWORD '<generated>';        -- NOT superuser, NOT BYPASSRLS
GRANT USAGE ON SCHEMA public TO app_user;
-- Precise grants on EVERY runtime table, not just the 4 user tables:
GRANT SELECT, INSERT, UPDATE, DELETE ON
  users, feature_upvotes, user_enabled_companies, admins,
  features, companies, job_listings, scrape_runs, worker_heartbeats,
  procrastinate_jobs, procrastinate_events, procrastinate_periodic_defers
  TO app_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_user;
-- Default privileges so future tables created by postgres are reachable:
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_user;
```

`app_user` must **not** own the tables (owner = `postgres`) so that `FORCE ROW
LEVEL SECURITY` actually binds it.

### 5b. Split migration vs runtime credentials (two DSNs)

Alembic needs DDL/CREATE → migrations keep running as `postgres`. Runtime
(requests + worker) switches to `app_user`. This means **two** connection strings:

- `DATABASE_URL` (runtime) → `app_user`
- `MIGRATION_DATABASE_URL` (startup migrations) → `postgres`

`apply_alembic_migrations` (`src/backend/api/migrations.py`) takes the migration
DSN; the pool (`src/backend/api/dependencies.py`) and Procrastinate connector take
the runtime DSN. Verify the worker/scrapers have every grant they need as
`app_user` — a missing grant surfaces as a 500, not a clean error.

### 5c. Per-request user context (GUC)

Set a transaction-scoped GUC carrying the authenticated identity, inside the
request transaction in `get_db` so it resets when the connection returns to the
pool:

```sql
SET LOCAL app.user_id = '<internal users.id>';   -- or app.auth_subject = '<jwt sub>'
```

Policies read it via a stable helper:

```sql
CREATE FUNCTION current_app_user_id() RETURNS text
  LANGUAGE sql STABLE AS $$ SELECT current_setting('app.user_id', true) $$;
```

- Use `current_setting(..., true)` (the `true` = "missing_ok") so **anonymous
  requests** (no GUC set) get NULL instead of erroring.
- For `users`, key the policy on the JWT subject (known *before* the internal-id
  lookup) to avoid the login chicken-and-egg, or exempt `users` and rely on the
  HTTP layer.

### 5d. Enable + policies (command-specific)

```sql
ALTER TABLE user_enabled_companies ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_enabled_companies FORCE ROW LEVEL SECURITY;
CREATE POLICY uec_owner ON user_enabled_companies
  USING (user_id = current_app_user_id())
  WITH CHECK (user_id = current_app_user_id());

ALTER TABLE feature_upvotes ENABLE ROW LEVEL SECURITY;
ALTER TABLE feature_upvotes FORCE ROW LEVEL SECURITY;
CREATE POLICY fu_read_all   ON feature_upvotes FOR SELECT USING (true);     -- public counts
CREATE POLICY fu_write_self ON feature_upvotes FOR INSERT
  WITH CHECK (user_id = current_app_user_id());
CREATE POLICY fu_del_self   ON feature_upvotes FOR DELETE
  USING (user_id = current_app_user_id());
-- users / admins: prefer an admin-bypass GUC or keep on the HTTP gate (see §4).
```

### 5e. Alembic delivery

RLS DDL (`ENABLE/FORCE ROW LEVEL SECURITY`, `CREATE POLICY`) is **invisible to
`alembic revision --autogenerate`** — it isn't SQLAlchemy model metadata, so the
diff comes back empty. Two ways to honor the repo's "always autogenerate" norm:

- **Hand-written `op.execute(...)` migration** — the repo's already-documented
  exception (the seed-company and id-rewrite migrations do exactly this). No new
  dependency. *Default choice.*
- **`alembic-utils`** — registers RLS policies as model-level "replaceable
  entities" so autogenerate detects them. Honors the rule more literally, but adds
  a dependency and doesn't cleanly cover the `ENABLE/FORCE` table toggles.

Final mechanism to be decided at implementation time.

## 6. Activation / rollout order

1. Land code + dormant policies (migration) while app is still `postgres` (no-op,
   safe to deploy any time).
2. Provision `app_user` + grants on prod (as `postgres`).
3. Add `MIGRATION_DATABASE_URL` (=`postgres`) and repoint `DATABASE_URL`
   (=`app_user`) on Railway.
4. Redeploy backend; **immediately verify** worker + scrapers + all routes (a
   missing grant = 500s).
5. Confirm RLS now bites (see §7).

**Rollback:** repoint `DATABASE_URL` back to `postgres` → policies become no-ops
again, backend fully functional.

## 7. Verification (after `app_user` is live)

```sql
-- As app_user, with NO app.user_id set: should return 0 rows from a scoped table
SET ROLE app_user;  RESET app.user_id;
SELECT count(*) FROM user_enabled_companies;       -- expect 0 (RLS hides all)

-- With the GUC set to a known user: should return only that user's rows
SET app.user_id = '<some-real-user-id>';
SELECT count(*) FROM user_enabled_companies;       -- expect that user's count

-- Public upvote counts must be UNCHANGED for anonymous reads
RESET app.user_id;
SELECT id, (SELECT count(*) FROM feature_upvotes u WHERE u.feature_id = f.id)
FROM features f;                                    -- counts match pre-RLS values
RESET ROLE;
```

Plus end-to-end: anonymous browsing, sign-in, `/account`, `/vote-features`,
`/admin`, and a worker scrape cycle all still work.

## 8. What this plan does NOT do (now)

- Does **not** create the `app_user` role, change any Railway env var, or split DSNs.
- Does **not** add any migration, `ENABLE/FORCE ROW LEVEL SECURITY`, or policy.
- Does **not** modify `get_db` / connection plumbing.

It is a tracked design to execute when user-owned dashboards land.
