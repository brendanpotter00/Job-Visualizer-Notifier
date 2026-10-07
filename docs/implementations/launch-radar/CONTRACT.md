# Launch Radar — implementation contract

The single source of truth for the three parallel build units: **backend**, **frontend** and **loop**.
Where this file and `plan.html` disagree, this file wins. `plan.html` is owned by the plan-sync agent and
no build unit edits it. The decided design (16 points in the orchestrator brief) is not up for debate;
this file only makes it concrete.

Branch `claude/launch-radar` in the worktree
`/Users/brendanpotter/Documents/develop/Job-Visualizer-Notifier/.claude/worktrees/env-plugin-setup-8f11ff`
is level with `origin/main` (`dd2a641b`, checked 2026-10-07 with 0 commits ahead and 0 behind). Alembic head on main
is `904d5bc44e4b`.

---

## 0. Ground rules (every unit)

- Work only inside the worktree above. **No git commit, push, PR or branch change.** The orchestrator commits.
- Edit only the files your unit owns (§9). If you need a change in another unit's file, stop and report it.
  Do not make the change yourself.
- Never print, echo, log or `cat` a secret or a `.env` file. Python code never logs `INTERNAL_API_KEY` or
  `PARALLEL_API_KEY`. It may log only whether each one is set.
- **No billed Parallel call in any build unit.** Only the later Validate phase may call billed endpoints, and it
  runs them as `zsh -ic '<cmd>'` because `PARALLEL_API_KEY` is exported by `~/.zshrc`. All tests mock the
  Parallel SDK. The loop imports `parallel` lazily inside `parallel_client.make_client()`, so the test suite runs
  without the SDK installed.
- Fix the design when something fails. Do not widen types, catch and ignore errors, or relax constraints just
  to make an error go away.
- Python environment: the worktree's `.venv` is a **broken symlink** (it points at `/Users/bpotter/...`). Use the main
  checkout's venv by absolute path: `V=/Users/brendanpotter/Documents/develop/Job-Visualizer-Notifier/.venv/bin`
  (`$V/python`, `$V/pytest`, `$V/mypy`, `$V/alembic`). `uv` is at `/opt/homebrew/bin/uv`.
- Node: the worktree has no `node_modules`. **Only the frontend unit** runs `npm ci` (once, at the worktree root),
  so two installs never race. The backend unit runs no npm commands.
- The local Docker Postgres (`jobscraper-postgres`, :5432) holds DB `jobscraper` at a **different branch's**
  revision (`7ccc685e2cd6`). Do not autogenerate against it, and do not migrate it (see §1.6).

---

## 1. Database (backend unit)

Models go in `src/backend/api/db_models.py`, appended after `EnrichmentTick`. Add `CheckConstraint` and
`Numeric` to the `sqlalchemy` import. Money is `NUMERIC(10,4)`, not Float, because a cap compared with float
sums drifts. psycopg2 returns `Decimal`; convert to `float` only at the response boundary.

### 1.1 `launch_radar_runs`: one row per loop invocation

| column | type | null | default | notes |
|---|---|---|---|---|
| `id` | Integer PK | no | serial | |
| `run_uuid` | Text | no | | idempotency key from the loop. `UNIQUE uq_launch_radar_runs_run_uuid` |
| `host` | Text | yes | | e.g. `server-laptop` |
| `status` | Text | no | `'running'` | `CHECK ck_launch_radar_runs_status: status IN ('running','ok','stopped','error')` |
| `budget_usd` | Numeric(10,4) | no | | the run's own cap (the loop's `--budget`). `CHECK ck_launch_radar_runs_budget: budget_usd > 0` |
| `events_read` | Integer | no | `0` | |
| `cards_posted` | Integer | no | `0` | |
| `notes` | Text | yes | | short free text from finish |
| `started_at` | TIMESTAMP(tz) | no | `now()` | |
| `ended_at` | TIMESTAMP(tz) | yes | | |

Index: `idx_launch_radar_runs_started_at (started_at)`.

### 1.2 `launch_radar_spend`: the ledger, one row per reservation (append-only)

| column | type | null | default | notes |
|---|---|---|---|---|
| `id` | Integer PK | no | serial | |
| `run_id` | Integer FK → `launch_radar_runs.id` `ON DELETE CASCADE` | no | | |
| `step` | Text | no | | e.g. `findall.create`, `task_run.create(brief)`, `monitor.accrued` |
| `domain` | Text | yes | | the company the spend is for, if any |
| `amount_usd` | Numeric(10,4) | no | | `CHECK ck_launch_radar_spend_amount: amount_usd > 0` |
| `accrued` | Boolean | no | `false` | true = a cost already incurred (scheduled Monitor executions), recorded even past the cap |
| `created_at` | TIMESTAMP(tz) | no | `now()` | |

Index: `idx_launch_radar_spend_run_id (run_id)`. Total spend = `SUM(amount_usd)` over the whole table. Run spend
= the sum for that `run_id`. No counter is stored anywhere else.

### 1.3 `launch_radar_monitors`: the three Monitors and each one's read cursor

| column | type | null | default | notes |
|---|---|---|---|---|
| `slot` | Text PK | no | | `CHECK ck_launch_radar_monitors_slot: slot IN ('seed','series_a_plus','launch')` |
| `monitor_id` | Text | no | | Parallel `monitor_…`. `UNIQUE uq_launch_radar_monitors_monitor_id` |
| `query` | Text | no | | |
| `processor` | Text | no | | always `base` |
| `frequency` | Text | no | | always `1d` |
| `status` | Text | no | `'active'` | `CHECK ck_launch_radar_monitors_status: status IN ('active','cancelled')` |
| `last_event_id` | Text | yes | | the newest `event_id` read so far |
| `charged_through` | TIMESTAMP(tz) | no | | scheduled executions before this time are already in the ledger |
| `created_at` | TIMESTAMP(tz) | no | `now()` | |
| `updated_at` | TIMESTAMP(tz) | no | `now()` | set explicitly by every UPDATE |

### 1.4 `launch_radar_cards`: one row per normalized domain, ever

| column | type | null | default | notes |
|---|---|---|---|---|
| `id` | Integer PK | no | serial | |
| `domain` | Text | no | | normalized (§4.1). `UNIQUE uq_launch_radar_cards_domain` is the dedupe guard. `CHECK ck_launch_radar_cards_domain_lower: domain = lower(domain)` |
| `company_name` | Text | no | | kept on the tombstone so a log can name it |
| `status` | Text | no | `'new'` | `CHECK ck_launch_radar_cards_status: status IN ('new','archived','deleted')` |
| `tracked_company_id` | Text FK → `companies.id` `ON DELETE SET NULL` | yes | | set by the backend at insert (§2.3) |
| `pr_url` | Text | yes | | set by `PATCH …/cards/{id}/pr` |
| `payload` | JSONB | yes | | the card (§4, snake_case). NULL only on a tombstone |
| `run_id` | Integer FK → `launch_radar_runs.id` `ON DELETE SET NULL` | yes | | |
| `posted_at` | TIMESTAMP(tz) | no | `now()` | |
| `updated_at` | TIMESTAMP(tz) | no | `now()` | set explicitly by every UPDATE |
| `archived_at` | TIMESTAMP(tz) | yes | | set on archive, cleared on restore |
| `deleted_at` | TIMESTAMP(tz) | yes | | |
| `updated_by` | Text | yes | | admin email from `require_admin` claims (`admin.get("email", "unknown")`) |

Constraints: `CHECK ck_launch_radar_cards_tombstone: (status = 'deleted') = (payload IS NULL)` and
`CHECK ck_launch_radar_cards_tombstone_clean: status <> 'deleted' OR (pr_url IS NULL AND tracked_company_id IS NULL)`.
Index: `idx_launch_radar_cards_status_posted (status, posted_at)`.

There are deliberately **no score, event_type or cost columns**. They live in `payload`, so a tombstone
(`payload = NULL`) clears all of them at once and nothing is stored twice.

### 1.5 Lifecycle SQL (in `services/launch_radar.py`)

- archive: `UPDATE … SET status='archived', archived_at=now(), updated_at=now(), updated_by=%s WHERE id=%s AND status='new' RETURNING …`
- restore: `UPDATE … SET status='new', archived_at=NULL, updated_at=now(), updated_by=%s WHERE id=%s AND status='archived' RETURNING …`
- delete (tombstone): `UPDATE … SET status='deleted', payload=NULL, pr_url=NULL, tracked_company_id=NULL, archived_at=NULL, deleted_at=now(), updated_at=now(), updated_by=%s WHERE id=%s AND status='archived' RETURNING id`
- If no row comes back, run `SELECT status … WHERE id=%s`. A missing row or `status='deleted'` gives **404**. A row in the wrong
  state gives **409**. Never `DELETE FROM` a card.

### 1.6 Migration: autogenerate against a scratch DB (recipe verified on this machine 2026-10-07)

```bash
V=/Users/brendanpotter/Documents/develop/Job-Visualizer-Notifier/.venv/bin
U=postgresql://postgres:postgres@localhost:5432/lr_autogen
cd /Users/brendanpotter/Documents/develop/Job-Visualizer-Notifier/.claude/worktrees/env-plugin-setup-8f11ff
docker exec jobscraper-postgres psql -U postgres -qc "DROP DATABASE IF EXISTS lr_autogen" -c "CREATE DATABASE lr_autogen"
# bootstrap every table EXCEPT the new ones (works whether or not db_models.py is already edited)
(cd src/backend && $V/python -c "
from sqlalchemy import create_engine
from api.db_models import Base
e = create_engine('$U'.replace('postgresql://', 'postgresql+psycopg2://'))
Base.metadata.create_all(e, tables=[t for n, t in Base.metadata.tables.items() if not n.startswith('launch_radar_')])")
DATABASE_URL=$U $V/alembic stamp head                      # -> 904d5bc44e4b
DATABASE_URL=$U $V/alembic revision --autogenerate -m "launch radar tables"
# review the file: 4 create_table + indexes, FKs and CHECKs present; no unrelated ops
DATABASE_URL=$U $V/alembic upgrade head && DATABASE_URL=$U $V/alembic downgrade -1 && DATABASE_URL=$U $V/alembic upgrade head
DATABASE_URL=$U $V/alembic check                           # "No new upgrade operations detected."
$V/alembic heads                                           # exactly ONE head
docker exec jobscraper-postgres psql -U postgres -qc "DROP DATABASE IF EXISTS lr_autogen"
```

Never hand-write the revision, and never add files under `scripts/shared/migrations/`. A plain `CREATE TABLE` revision needs no
batch_alter collapsing.

---

## 2. Backend endpoints

All JSON field casing is exact. **Admin responses are camelCase**, through response models with
`ConfigDict(alias_generator=to_camel, populate_by_name=True)`, the same pattern as the other models in `models.py`.
**Internal requests and responses are snake_case.** Internal request models use `ConfigDict(extra="forbid")` and no
alias generator. Every psycopg2 error rolls back and raises 500 with a generic detail, as in `routers/admin.py`.
The service owns `commit()`.

### 2.1 Admin routes (`src/backend/api/routers/admin.py`, prefix `/api/admin`, every route `Depends(require_admin)`)

#### `GET /api/admin/launch-radar/cards`

Query: `status: Literal['new','archived']` (required; anything else, `deleted` included, gives 422), `limit: int = 25 (1..100)`,
`offset: int = 0 (>=0)`. Order: `new` by `posted_at DESC, id DESC`; `archived` by `archived_at DESC, id DESC`.

```json
{
  "cards": [ /* LaunchRadarCard, §2.4 */ ],
  "total": 2,
  "counts": { "new": 2, "archived": 1 },
  "stats": {
    "lastRun": { "startedAt": "2026-10-07T01:31:00Z", "endedAt": "2026-10-07T01:36:12Z", "status": "ok", "host": "server-laptop" },
    "spendUsd": 0.46,
    "capUsd": 5.0
  }
}
```

- `total` counts the rows with the requested status. `counts` always covers both tabs, whatever the filter.
- `lastRun` is the newest `launch_radar_runs` row by `started_at`, or `null` when there are no runs.
- `spendUsd` is `SUM(launch_radar_spend.amount_usd)`, rounded to 4 places. `capUsd` is `settings.launch_radar_spend_cap_usd`.
- Deleted rows are never selected. The query has `WHERE status IN ('new','archived')`, or the single requested status.

#### `PATCH /api/admin/launch-radar/cards/{card_id}`

`card_id: int` (ge=1). Body `{"status": "archived" | "new"}`, with `extra="forbid"`.
- `"archived"` applies only to a `new` card, and `"new"` (Restore) only to an `archived` card.
- 200 returns the updated `LaunchRadarCard`. 404 if the card is missing or deleted. 409 if the card is already in that state.

#### `DELETE /api/admin/launch-radar/cards/{card_id}`

Permanent delete (the tombstone in §1.5).
- **204 No Content** with no body (FastAPI `Response(status_code=204)`).
- 404 if the card is missing or already deleted. **409** if `status='new'`: a card must be archived first.

Router functions: `admin_launch_radar_cards`, `admin_set_launch_radar_status`, `admin_delete_launch_radar_card`.
Service functions: `list_cards`, `run_stats`, `set_status`, `delete_card`.

### 2.2 Proxy allowlist (`api/admin.ts`, **owned by the backend unit**)

Add these two lines under a `// launch radar` comment in `PROXIED_ROUTES`. Change nothing else; the production proxy
behaviour stays the same:

```ts
  // launch radar (admin dashboard cards; the loop's /api/internal/launch-radar/* is NEVER proxied)
  'launch-radar/cards', // GET — list by status
  'launch-radar/cards/:id', // PATCH (archive / restore) · DELETE (permanent, archived only)
```

`api/admin.ts` already forwards PATCH and DELETE (`METHODS_WITH_BODY`), and `forwardResponse` already handles a
204. The backend unit owns this file because `src/backend/api/tests/test_proxy_path_allowlists.py` fails in both
directions until the backend routes and the allowlist agree. One unit can then keep both green.

### 2.3 Internal routes (`src/backend/api/routers/internal_launch_radar.py`)

Mounted in `main.py` at `prefix="/api/internal/launch-radar", tags=["internal-launch-radar"]`. The only auth is the
global `require_internal_key` middleware (no per-route dependency), as for `internal_enrichment`. Never proxy these
routes. The loop calls the backend directly (`BACKEND_URL`).

| method & path | request (snake_case) | success | errors |
|---|---|---|---|
| `POST /runs` | `{"run_uuid": str 8..64 [A-Za-z0-9-], "host": str<=64 \| null, "budget_usd": float >0 <=5}` | **201** `RunStarted` | — (idempotent: same `run_uuid` → 201 with the existing row) |
| `POST /runs/{run_uuid}/reserve` | `{"step": str 1..64, "est_usd": float >0 <=1, "domain": str \| null, "accrued": bool = false}` | 200 `Reserved` | 404 unknown run · 409 run not `running` · **402** budget (see below) |
| `POST /runs/{run_uuid}/finish` | `{"status": "ok"\|"stopped"\|"error", "events_read": int>=0, "cards_posted": int>=0, "notes": str<=500 \| null}` | 200 `RunFinished` | 404 · 409 already finished |
| `GET /monitors` | — | 200 `{"monitors": [MonitorRow]}` | — |
| `PUT /monitors/{slot}` | `{"monitor_id", "query", "processor": "base", "frequency": "1d", "status": "active"\|"cancelled", "charged_through": iso}` | 200 `MonitorRow` (upsert by slot) | 422 bad slot |
| `PATCH /monitors/{slot}` | any subset of `{"last_event_id": str, "status": "active"\|"cancelled", "charged_through": iso}` (at least 1 key) | 200 `MonitorRow` | 404 · 422 |
| `GET /seen` | query `domain` (repeatable, 0..100) and `name` (repeatable, 0..100) | 200 `SeenOut` | 422 when more than 100 |
| `POST /cards` | `{"run_uuid": str, "payload": LaunchRadarPayload (§4)}` | **201** `{"id": int, "tracked_company_id": str \| null}` | 404 unknown run · 409 run not running · **409 domain already posted** · 422 payload invalid or domain not normalized |
| `PATCH /cards/{card_id}/pr` | `{"pr_url": str}`, matching `^https://github\.com/brendanpotter00/Job-Visualizer-Notifier/pull/\d+$` | 200 `{"id", "pr_url"}` | 404 missing/deleted · 409 `pr_url` already set, or card is tracked |
| `GET /pr-candidates` | query `limit` 1..5 (default 1) | 200 `{"cards": [PrCandidate]}` | — |

Shapes (snake_case):

```jsonc
// RunStarted
{ "run_id": 7, "run_uuid": "…", "budget_usd": 1.0, "run_spend_usd": 0.0,
  "total_spend_usd": 0.46, "cap_usd": 5.0, "remaining_usd": 4.54,
  "monitors": [ /* MonitorRow, status='active' only */ ] }
// Reserved
{ "reserved_usd": 0.1, "run_spend_usd": 0.135, "total_spend_usd": 0.595, "cap_usd": 5.0, "over_cap": false }
// 402 body (HTTPException detail object)
{ "detail": { "reason": "run_budget" | "cap", "run_spend_usd": 0.98, "total_spend_usd": 4.98, "cap_usd": 5.0 } }
// RunFinished
{ "run_id": 7, "status": "ok", "run_spend_usd": 0.33, "total_spend_usd": 0.79 }
// MonitorRow
{ "slot": "seed", "monitor_id": "monitor_…", "query": "…", "processor": "base", "frequency": "1d",
  "status": "active", "last_event_id": "mevt_…" | null, "charged_through": "2026-10-07T07:00:00Z" }
// SeenOut
{ "domains": { "raindrop.ai": { "card_id": 1, "status": "new" | "archived" | "deleted" } },   // only seen ones
  "names":   { "Raindrop AI": "raindrop-ai" } }                                             // only names matching a tracked company
// PrCandidate (from the row + payload)
{ "id": 4, "domain": "ghost.ai", "company": "Ghost AI", "ats_provider": "ashby",
  "board_token": "ghost", "job_count": 1, "posted_at": "…" }
```

**Ledger semantics** (`reserve_spend`, one transaction):
1. `SELECT pg_advisory_xact_lock(<fixed bigint constant>)` serializes every reservation, so concurrent runs can never
   both pass the cap.
2. Lock the run row (`FOR UPDATE`). 404 if it is missing, 409 if `status <> 'running'`.
3. `run_spend = SUM(amount) WHERE run_id` and `total = SUM(amount)` over the table.
4. When `accrued = false`: if `run_spend + est > budget_usd`, roll back with **402** `reason=run_budget`. If
   `total + est > cap`, roll back with **402** `reason=cap`.
5. INSERT the spend row (accrued rows are always inserted, because the money is already spent) and commit. `over_cap` =
   `total + est > cap`.

**`POST /cards` (`insert_card`)**, one transaction:
1. Verify the run exists and is `running`.
2. Server-side `normalize_domain(payload.domain)` must equal `payload.domain`, or 422.
3. `tracked_company_id = SELECT id FROM companies WHERE visibility='public' AND ats = payload.ats.provider AND lower(board_token) = lower(payload.ats.board_token) LIMIT 1`.
   Skip this when `board_token` is null.
4. `INSERT … (domain, company_name, status, tracked_company_id, payload, run_id, posted_at, updated_at) VALUES (…, 'new', …, now(), now()) ON CONFLICT ON CONSTRAINT uq_launch_radar_cards_domain DO NOTHING RETURNING id`.
5. If no row comes back, raise `DomainSeen`, which the route turns into **409** `{"detail": "domain already posted"}`.
6. On success, `UPDATE launch_radar_runs SET cards_posted = cards_posted + 1` and commit. The payload is stored as
   `model_dump(mode="json")` (snake_case).

**`GET /seen`**: `domains` matches `launch_radar_cards.domain = ANY(%s)` for **any** status, tombstones included.
`names` matches `lower(companies.display_name) = ANY(lower …)` with `visibility='public'`. Each input domain is
normalized server-side first, and the response is keyed by the normalized form.

**`GET /pr-candidates`**: `status='new' AND pr_url IS NULL AND tracked_company_id IS NULL AND (payload->>'pr_ready')::boolean`,
newest `posted_at` first.

### 2.4 `LaunchRadarCard`: admin response model (camelCase)

`models.py` defines one set of nested Pydantic models used **both** to validate the loop's snake_case POST body (by
field name) and to serialize the admin response (by camelCase alias). The admin card is built from the row columns
plus the parsed payload:

```python
LaunchRadarCardOut(id=row.id, status=row.status, tracked_company_id=row.tracked_company_id, pr_url=row.pr_url,
                   posted_at=row.posted_at, archived_at=row.archived_at, updated_by=row.updated_by,
                   **LaunchRadarPayload.model_validate(row.payload).model_dump())
```

Its JSON is exactly the TypeScript `LaunchRadarCard` in §5.2.

### 2.5 Config (`src/backend/api/config.py`)

| env var | field | default | rule |
|---|---|---|---|
| `LAUNCH_RADAR_SPEND_CAP_USD` | `launch_radar_spend_cap_usd: float` | `5.0` | `Field(gt=0, le=50)`. Set only by the operator; the loop cannot raise it |
| `DEV_AUTH_BYPASS_EMAIL` | `dev_auth_bypass_email: str \| None` | `None` | §7.1 |

---

## 3. Domain normalization (shared algorithm, two copies)

The backend (`services/launch_radar.py::normalize_domain`) and the loop (`launch_radar/domains.py::normalize_domain`)
each carry a copy, ported verbatim from POC `poc.py:155`:

1. Non-string or empty → None. Strip, then lowercase.
2. `{"", "na", "n/a", "none", "null", "unknown"}` → None.
3. Drop the scheme (`^[a-z][a-z0-9+.-]*://`), then everything from the first `/ ? #`, the userinfo before `@` and the port.
4. Strip a leading `www.` and a trailing `.`. Return None unless the result contains a `.`.

Both test suites must pass the same vectors:

| input | output |
|---|---|
| `HTTPS://WWW.Raindrop.AI/blog/series-a/` | `raindrop.ai` |
| `athennian.com` | `athennian.com` |
| `ghost.ai:443` | `ghost.ai` |
| `user@www.Example.com/x?y#z` | `example.com` |
| `NA` | None |
| `localhost` | None |

---

## 4. Card payload the loop posts (snake_case, stored in `payload`)

`LaunchRadarPayload` (Pydantic, `extra="forbid"` on input). Every key is required unless shown as nullable.

```jsonc
{
  "company": "Raindrop AI",
  "domain": "raindrop.ai",                         // normalized (§3)
  "website": "https://www.raindrop.ai",            // brief.website_url, else "https://<domain>"
  "one_liner": "Monitoring for AI agents" | null,  // null only when the brief failed
  "what_they_do": "…" | null,
  "blurb": "…" | null,
  "event": {                                       // monitor event, else brief.latest_announcement, else null
    "type": "funding" | "launch" | "other",
    "headline": "…",
    "source_url": "https://…" | null,
    "announced_at": "2026-09-17" | null,
    "round": "Series A" | null,
    "amount_usd": "$35M" | null,
    "investors": "CRV, Lightspeed" | null,
    "origin": "monitor" | "task brief"
  } | null,
  "scores": {
    "talent": 49 | null,                           // null = no people data (never 0 for "no data")
    "vc": 55 | null,                               // null = brief missing or no investors and no amount
    "talent_reasons": ["Priya Raman: top school (Berkeley)", "…"],
    "vc_reasons": ["CRV led (tier 2)", "Lightspeed joined (tier 1)", "round over $20M"]
  },
  "leaders": [{
    "name": "Sam Rivera",
    "title": "Co-Founder & CTO" | null,
    "linkedin_url": "https://linkedin.com/in/example-sam-rivera" | null,
    "profile_url": "https://…" | null,             // the FindAll candidate url
    "summary": "WPI. Apple visionOS designer; interned at Google and SpaceX" | null,  // deterministic, built by the loop
    "schools": ["Worcester Polytechnic Institute BS Robotics"],
    "prior_companies": ["Apple (Designer)", "Google (Intern)"],
    "founded_before": ["Ledgerline (acquired, acq. by Northwind, 2025)"],
    "years_experience": 8 | null,                  // int (cast from the string or float the schema returns)
    "industry_experience": "…" | null,
    "signals": ["…"]                               // notable_signals, at most 4
  }],
  "leaders_dropped": 0,                            // FindAll matches is_person() rejected (company pages)
  "team_stats": {                                  // the "pro" team-tally Task; null if it failed. Display only
    "profiles_found": 6 | null,                    // every count is cast float -> int; null = unknown (never 0)
    "team_size_estimate": "approximately 10-20",
    "schools": [{ "name": "University of California, Davis", "count": 1 }],
    "prior_employers": [{ "name": "Amazon", "count": 2 }],
    "ex_founders_with_exit": 0 | null,             // null = unknown
    "sample_names": ["…"]
  } | null,
  "funding": {
    "latest_round": Round | null,
    "prior_rounds": [Round],                       // brief's "investors" string is split on commas into other_investors
    "total_raised_usd": "$50M" | null
  },
  "notable_facts": ["…"],                          // at most 6 stored; the UI shows 3
  "careers_url": "https://…" | null,
  "ats": {
    "provider": "greenhouse"|"ashby"|"lever"|"gem"|"workday"|"eightfold"|"other"|"none",
    "board_token": "Raindrop" | null,
    "board_url": "https://jobs.ashbyhq.com/Raindrop" | null,
    "verified": true,                              // the free public API returned 200
    "job_count": 9 | null,
    "checked_url": "https://api.ashbyhq.com/posting-api/job-board/Raindrop" | null
  },
  "pr_ready": true,                                // verified && provider in {greenhouse, ashby, lever} && job_count >= 1
  "sources": [{ "url": "https://…", "title": "…" | null, "field": "one_liner" | null }],   // at most 40, deduped by url
  "parallel_run_ids": { "findall_id": "…" | null, "brief_run_id": "…" | null,
                        "team_run_id": "…" | null, "pedigree_group_id": "…" | null },
  "cost_usd": 0.30,                                // sum of this domain's reservations
  "timings_s": { "findall_s": 154.0, "pedigree_s": 60.1, "brief_s": 124.0, "team_s": 167.0 },
  "issues": ["team tally failed: …"],
  "generated_at": "2026-10-07T01:36:00Z"
}
// Round
{ "stage": "Series A" | null, "amount_usd": "$35M" | null, "announced_at": "2026-09-17" | null,
  "lead_investors": ["CRV"], "other_investors": ["Lightspeed Venture Partners", "Y Combinator"] }
```

---

## 5. Frontend (frontend unit)

### 5.1 Route, nav and wiring

- `src/frontend/src/config/routes.ts`: add `ADMIN_LAUNCH_RADAR: '/admin/launch-radar'` to `ROUTES` (after
  `ADMIN_CUSTOM_COMPANIES`). Add `'Radar'` to `NavIconName`. In `ADMIN_NAV_ITEMS`, add
  `{ path: ROUTES.ADMIN_LAUNCH_RADAR, label: 'Launch Radar', icon: 'Radar' }` right after the Custom Companies entry.
- `src/frontend/src/components/layout/NavigationDrawer.tsx`: `import RadarIcon from '@mui/icons-material/Radar'`
  (it is installed) and `Radar: RadarIcon` in `iconMap`.
- `src/frontend/src/app/App.tsx`: `<Route path={ROUTES.ADMIN_LAUNCH_RADAR} element={<AdminRoute><AdminLaunchRadarPage /></AdminRoute>} />`
  next to the other admin routes. Use an eager import, as the other admin pages do.
- `src/frontend/vite.config.ts`: add a `'/api/admin'` proxy entry to `http://localhost:8000`
  (`changeOrigin: true, secure: false`), the same shape as `/api/users`. Without it, plain `npm run dev` cannot reach the admin routes.

### 5.2 Types (`src/frontend/src/features/admin/launchRadarTypes.ts`, new)

```ts
export type LaunchRadarStatus = 'new' | 'archived';
export type LaunchRadarAtsProvider =
  'greenhouse' | 'ashby' | 'lever' | 'gem' | 'workday' | 'eightfold' | 'other' | 'none';

export interface LaunchRadarRound {
  stage: string | null; amountUsd: string | null; announcedAt: string | null;
  leadInvestors: string[]; otherInvestors: string[];
}
export interface LaunchRadarLeader {
  name: string; title: string | null; linkedinUrl: string | null; profileUrl: string | null;
  summary: string | null; schools: string[]; priorCompanies: string[]; foundedBefore: string[];
  yearsExperience: number | null; industryExperience: string | null; signals: string[];
}
export interface LaunchRadarTally { name: string; count: number }
export interface LaunchRadarCard {
  id: number;
  status: LaunchRadarStatus;                 // deleted rows never reach the client
  trackedCompanyId: string | null;
  prUrl: string | null;
  postedAt: string;
  archivedAt: string | null;
  updatedBy: string | null;
  company: string;
  domain: string;
  website: string;
  oneLiner: string | null;
  whatTheyDo: string | null;
  blurb: string | null;
  event: {
    type: 'funding' | 'launch' | 'other'; headline: string; sourceUrl: string | null;
    announcedAt: string | null; round: string | null; amountUsd: string | null;
    investors: string | null; origin: 'monitor' | 'task brief';
  } | null;
  scores: { talent: number | null; vc: number | null; talentReasons: string[]; vcReasons: string[] };
  leaders: LaunchRadarLeader[];
  leadersDropped: number;
  teamStats: {
    profilesFound: number | null; teamSizeEstimate: string; schools: LaunchRadarTally[];
    priorEmployers: LaunchRadarTally[]; exFoundersWithExit: number | null; sampleNames: string[];
  } | null;
  funding: { latestRound: LaunchRadarRound | null; priorRounds: LaunchRadarRound[]; totalRaisedUsd: string | null };
  notableFacts: string[];
  careersUrl: string | null;
  ats: { provider: LaunchRadarAtsProvider; boardToken: string | null; boardUrl: string | null;
         verified: boolean; jobCount: number | null; checkedUrl: string | null };
  prReady: boolean;
  sources: { url: string; title: string | null; field: string | null }[];
  parallelRunIds: { findallId: string | null; briefRunId: string | null;
                    teamRunId: string | null; pedigreeGroupId: string | null };
  costUsd: number;
  timingsS: Record<string, number>;
  issues: string[];
  generatedAt: string;
}
export interface LaunchRadarStats {
  lastRun: { startedAt: string; endedAt: string | null; status: 'running' | 'ok' | 'stopped' | 'error';
             host: string | null } | null;
  spendUsd: number;
  capUsd: number;
}
export interface LaunchRadarCardsResponse {
  cards: LaunchRadarCard[]; total: number; counts: { new: number; archived: number }; stats: LaunchRadarStats;
}
export interface LaunchRadarCardsArgs { status: LaunchRadarStatus; page: number; rowsPerPage: number }
```

### 5.3 RTK Query (`src/frontend/src/features/admin/adminApi.ts`)

- Add `'LaunchRadarCards'` to `tagTypes`.
- `getLaunchRadarCards: builder.query<LaunchRadarCardsResponse, LaunchRadarCardsArgs>`: `{ url: '/launch-radar/cards', params: { status, limit: rowsPerPage, offset: page * rowsPerPage } }`.
  Add a `transformResponse` runtime guard in the style of `getAdminCustomCompanies`: `cards` is an array, `total` is a number,
  `counts.new` and `counts.archived` are numbers, `stats.capUsd` is a number, and each card has `typeof id === 'number'` and
  `typeof domain === 'string'`. `providesTags: ['LaunchRadarCards']`.
- `setLaunchRadarCardStatus: builder.mutation<LaunchRadarCard, { id: number; status: LaunchRadarStatus }>`:
  `{ url: `/launch-radar/cards/${id}`, method: 'PATCH', body: { status } }`, `invalidatesTags: ['LaunchRadarCards']`.
- `deleteLaunchRadarCard: builder.mutation<void, { id: number }>`: `{ url: `/launch-radar/cards/${id}`, method: 'DELETE' }`,
  `invalidatesTags: ['LaunchRadarCards']`.
- Export `useGetLaunchRadarCardsQuery`, `useSetLaunchRadarCardStatusMutation` and `useDeleteLaunchRadarCardMutation`.

### 5.4 Components (`src/frontend/src/pages/AdminLaunchRadarPage/`)

| file | role |
|---|---|
| `AdminLaunchRadarPage.tsx` | `Container maxWidth="md"` with `py: RESPONSIVE.spacing.pageMarginY`. `Typography h4` "Launch Radar". The sub line reads: "Startups the Parallel loop found, newest first. Last run {Oct 7 at 01:31 UTC} on {host}. ${spend} of the ${cap} budget used." (or "No runs yet."). MUI `Tabs`: **New** and **Archived**, each with a count chip or a muted count. The page holds the tab, page index and `rowsPerPage = 25`, and keeps the last data to avoid a flash, as `AdminFeedbackPage` does. It shows `LoadingState` and `ErrorState`, and the empty states "No new cards." / "No archived cards.". It shows MUI `Pagination` when `total > rowsPerPage`. |
| `components/RadarCard.tsx` | An MUI `Accordion` (outlined, `disableGutters`). The summary is a 3-column grid: a 32px black rounded square with the white first letter of `company`; the name plus a `website` link showing `domain` (`target="_blank" rel="noopener noreferrer"`); then `oneLiner` and the event line (`EventLine`). On the right sit two `ScoreBadge`s (Talent, VC). Below them is `CardStatusLine`. Action buttons call `event.stopPropagation()` so they never toggle the accordion. |
| `components/ScoreBadge.tsx` | A 22px tabular numeral, a 30x3px bar filled to `value%`, and a small label. `null` renders a grey "–" with an empty bar (aria-label "No score"), never 0. |
| `components/CardStatusLine.tsx` | One line. Left side, New tab: `prUrl` gives the success-colored link "Add-company PR ready". Otherwise `trackedCompanyId` gives the muted text "Already tracked". Otherwise "No PR" plus a link "Open job board" (`ats.boardUrl ?? careersUrl`, omitted if both are null). Archived tab: "Archived {Oct 7}". Right side, New tab: an `Archive` text button. Archived tab: a `Restore` button and a `Delete` button (error color) that opens the dialog. |
| `components/CardBody.tsx` | Accordion details, indented under the name. **Research incomplete** (only when `issues` is non-empty, first, warning colour): one bullet per issue, so partial data never reads as "nothing found". **Team**: the leader bullets (bold name, muted title, `summary` line). When `leaders` is empty, the warning text "No leaders confirmed." is followed by "The people search returned company pages." if `leadersDropped > 0`. When leaders exist but none has `summary`, schools or prior companies, it shows the warning "No background data came back for these leaders". **Rest of team** (only when `teamStats`): the right label is "{profilesFound} public profiles" ("profile count unknown" when null); one bullet "Previously at Amazon (2), Twitter, … and N more" (top 6, count shown when >1); one bullet "{k} schools: …" (top 4 and "N more"); a muted "No prior exits found" when `exFoundersWithExit === 0` ("Prior exits unknown" when null). **Funding**: the right label is `totalRaisedUsd` + " total"; a bullet per round: "**{stage} {amountUsd}**, {Mon YYYY}. Led by {leads}, with {others}" (first 3 others, then "and N more"). **Highlights**: `notableFacts.slice(0, 3)`. **Why these scores**: a collapsed toggle (MUI `Collapse` or nested Accordion). Its bullets: "Talent {n}: {talentReasons.join('; ')}" or "Talent: no people data, so no score", and "VC {n}: {vcReasons.join('; ')}" or "VC: no funding data, so no score"; when the score is null AND `issues` is non-empty the line reads "Talent: not scored, research incomplete" (same for VC). **Footer**: left "{Ashby} board, {9} open jobs" (verified), "{Provider} board, no PR" (unverified with a provider), or "No job board found". Right: a link to `event.sourceUrl` labelled with its hostname, then "${costUsd.toFixed(2)} research". |
| `components/EventLine.tsx` | funding: "{round ?? 'Funding'} **{amountUsd}**" then the muted date. launch: "Launch" then the date. other: the headline, truncated. |
| `components/DeleteCardDialog.tsx` | MUI `Dialog`. Title "Delete {company} permanently?". Body "The card and its research go away. The loop will not post {domain} again." `Cancel` and a `Delete` button (contained, error color). It shows an error `Alert` if the mutation fails, and closes on success. |
| `format.ts` | Pure helpers: `formatShortDate`, `formatRunLine`, `formatUsd`, `atsLabel`, `hostnameOf`, `summarizeTally`, `roundLine`. These are unit tested. |

Style: match the existing MUI admin pages (theme typography and colors, `text.secondary` for muted text). No new CSS
files and no new dependencies.

---

## 6. Loop (loop unit)

### 6.1 Module layout (`scripts/launch_radar/`, a package; relative imports only)

| file | content |
|---|---|
| `__init__.py` | empty |
| `radar.py` | argparse CLI and `main()` (§6.2). Runs as `python -m scripts.launch_radar.radar` from the repo root |
| `radar.sh` | `#!/bin/sh` launcher. `cd` to the repo root (its own `../..`). If `${LAUNCH_RADAR_ENV_FILE:-$HOME/.config/jvn-launch-radar/env}` exists, source it with `set -a`. Then `exec /opt/homebrew/bin/uv run --no-project --python '>=3.11' --with 'parallel-web>=1.3.5' --with 'httpx>=0.27' python -m scripts.launch_radar.radar "$@"`. Mode 755. The secrets exist only in this process tree, never in Claude's environment |
| `config.py` | Reads `BACKEND_URL` (required), `INTERNAL_API_KEY` (required unless `BACKEND_URL` is a loopback URL), `PARALLEL_API_KEY` (required only by billed subcommands; the SDK reads it, our code only checks presence) and `LAUNCH_RADAR_STATE_DIR` (default `~/Library/Application Support/jvn-launch-radar`). A missing variable exits 1 with the variable's **name** only |
| `backend_client.py` | `BackendClient` (httpx, timeout 30s, sends `X-Internal-Key` when set). One method per §2.3 route. `reserve()` raises `BudgetExceeded(reason, run_spend, total_spend, cap)` on 402, and `post_card()` raises `DomainSeen` on 409. A request is retried only if it is a GET (twice, on connection errors); POSTs are never retried |
| `parallel_client.py` | `make_client()`: a lazy `from parallel import Parallel`, then `Parallel().with_options(max_retries=0)`. This is the **only** place that imports `parallel` at runtime (event-type narrowing uses `getattr(ev, "event_type", None)`, not an SDK import) |
| `schemas.py` | `MONITOR_QUERIES` (§6.4), `MONITOR_OUTPUT_SCHEMA` (POC `poc.py:178`, verbatim), `PEDIGREE_SCHEMA` (POC `poc.py:410`), `BRIEF_SCHEMA` (POC `poc.py:485` **plus** `ats.board_url: string|null`, required), `TEAM_SCHEMA` (= `team_stats.py` `A_SCHEMA`), `ATS_ENUM`, and the price tables (`MONITOR_PRICE`, `TASK_PRICE`, `FINDALL_PRICE` from POC) |
| `domains.py` | `normalize_domain` (§3) and `BIG_TECH` (POC). `is_big_tech(domain)` |
| `monitors.py` | ensure, read events newer than `last_event_id`, accrue scheduled executions, cancel all |
| `leaders.py` | FindAll create/poll/result, `is_person` (§6.5), pedigree Task Group |
| `research.py` | brief Task (core), team-tally Task (pro), and `wait_task` (408 means still running; uses `api_timeout`) |
| `scoring.py` | `VC_TIERS`, `VC_AMOUNT_BONUS`, `TALENT_RUBRIC` and `CONFIDENCE_WEIGHT`, copied verbatim from POC. `score_vc` and `score_talent` per §6.6 |
| `ats.py` | `ats_check` (POC `poc.py:752`), minus the fixture writes. Returns `verified`, `job_count`, `checked_url` and `board_url` |
| `card.py` | `build_payload(...) -> dict` matching §4 exactly, with the float→int casts and `leader.summary` composition |
| `state.py` | local resumable state under `LAUNCH_RADAR_STATE_DIR`: `queue.json` (pending candidates) and `companies/<domain>.json` (created Parallel ids and reserved amounts) |
| `pipeline.py` | `research_company(...)` and the `run` orchestration (§6.3) |
| `wrapper.sh`, `com.bp.jvn-launch-radar.plist.template`, `install_launch_agent.sh`, `README.md` | §6.8 |

The POC (`scripts/launch_radar_poc/`) stays **untouched** as a read-only reference. Its code is copied into the modules
above with these changes: Ledger → backend reservations, `out/seen.json` → `GET /seen`, enrich → Task Group, fixtures
→ none, `score_talent` → nullable, and `is_person` added. Do not import from `launch_radar_poc`.

### 6.2 CLI (`radar.py`)

```
monitors-ensure                     create any missing active Monitor (one per slot); billed $0.01 each, reserved first
run [--max-companies N=3] [--budget USD=1.00] [--exclude d1,d2] [--deadline-s 540] [--dry-run]
monitors-cancel                     cancel every active Monitor, then PATCH status=cancelled; free
pr-candidates [--limit 1]           print GET /pr-candidates as JSON
set-pr --card-id N --pr-url URL     PATCH /cards/{id}/pr
heartbeat --status ok|error [--note TEXT]   append one line to $STATE_DIR/heartbeat.log (the skill's final step)
```

Exit codes: `0` done · `2` stopped on the budget (402 or the cancel floor) · `3` incomplete, so re-run to resume · `1` error.

`--dry-run` makes **no billed call and no backend write**. It reads events (a free GET) and `GET /seen`, then prints the
candidates it would research. It posts no `POST /runs`. `monitors-ensure` and `monitors-cancel` each open and finish their
own backend run (`budget_usd = 0.10`), so every reservation belongs to a run.

### 6.3 `run` order (one invocation)

1. `POST /runs` with a fresh `run_uuid` (uuid4 hex), `host = socket.gethostname()` and `budget_usd = --budget`.
2. **Accrue Monitor executions.** For each active monitor, `days = floor((now - charged_through) / 1 day)`. If `days >= 1`,
   reserve `days × MONITOR_PRICE['base']` with `accrued=true, step='monitor.accrued'`, then `PATCH charged_through += days`.
   If the reserve reports `over_cap`, or `remaining_usd < 0.10`, cancel every monitor, finish the run `stopped`, and exit 2.
   Monitors are the only spend that happens without a call from us, so the cap stops them.
3. **Read events.** For each active monitor, page `client.monitor.events(id, limit=100)` (newest first, `next_cursor`) until
   the page holds `last_event_id`. Keep only `event_type == "event_stream"` rows. Parse `output.content` the way POC
   `_parse_content` does. Remember the newest `event_id` per slot.
3b. **Find missing domains** (added after the live validation on 2026-10-07: every Monitor event arrived with
   `company_domain: null`, because news articles rarely print a website). For each event with no domain (at most 10 a run),
   reserve `search(domain:<name>)` at $0.001, then call the Search API (`mode="fast"`, `max_results=8`) and keep the
   highest-ranked result whose host carries the company name and is not a news, directory or social site
   (`resolve.py`). Entity Search was tried first and returns only LinkedIn/Tracxn URLs. A cap refusal here stops the
   run before the cursors move, so the events are read again next run.
4. **Dedupe** before any spend: `normalize_domain`; drop on no domain, `BIG_TECH`, `--exclude`, a domain already in the local
   queue or this run, or a `GET /seen` hit (domain seen, or name tracked). Append the survivors to `queue.json` with the event.
   Then `PATCH /monitors/{slot} last_event_id`, so the events are never read again (the candidates are already persisted locally).
5. **Research the queue.** Resumed companies (those with a state file) always continue. Up to `--max-companies` new ones
   start their first billed call. A `ThreadPoolExecutor(max_workers=3)` runs `research_company` per domain:
   1. Reserve, then create, all three at the same time: FindAll (`entity_type="people"`, generator `preview`, `match_limit=8`,
      objective and match condition as in POC `poc.py:858`, plus the sentence "The candidate must be one person with a personal
      profile, not a company page."), the brief Task (`core`, `BRIEF_SCHEMA`, input `{company_name, company_domain, context: event headline}`),
      and the team-tally Task (`pro`, `TEAM_SCHEMA`; input asks for current employees who are **not** founders, co-founders or
      C-level executives, because the founders' names are not known yet). Save each id to the state file **before** the next create.
   2. Poll FindAll (`retrieve` every 10s until `is_active` is false), then `result`. Keep the candidates that are matched **and**
      pass `is_person`, at most 8. `leaders_dropped` = matched minus kept. **No base fallback and no FindAll enrich.**
   3. Pedigree, when there is at least one leader: reserve `len × TASK_PRICE['base']`, then one Task Group (`task_group.create`,
      `add_runs` with `default_task_spec = PEDIGREE_SCHEMA` and inputs `{person_name, current_title, linkedin_url, company_name, company_domain}`,
      processor `base`, `metadata={"row_id": str(i)}`). Poll the group status every 10s, then `get_runs(include_input=True, include_output=True)`.
      Join on `run.metadata["row_id"]`, never on stream order. Confidence for each field comes from `basis[].field.split('.')[0]`.
   4. Wait for the brief and the team tally (`wait_task`). On failure, set the output to None and add a string to `issues`.
   5. `ats_check(brief.ats.provider, brief.ats.board_token, brief.careers_url)` against the free public APIs. If the brief gave
      a `board_url`, that is the board URL; otherwise use the public board URL for a verified token.
   6. Score (§6.6), `build_payload`, `POST /cards`. A 409 `DomainSeen` is logged as a skip, not an error. Remove the company from
      the queue and its state file.
   - On a 402 `BudgetExceeded`: stop starting new work. The in-flight companies keep their ids and resume next time. The run
     ends `stopped` and exits 2.
   - **Deadline**: every poll loop checks `--deadline-s` (default 540, under the Bash tool's 600s cap). Past it, save the state,
     stop, finish the run `stopped`, and exit 3. The next `run` resumes from the saved ids and **never re-creates or
     re-reserves** a saved step.
   - A queue item older than 3 days with no progress is dropped and logged.
6. `POST /runs/{uuid}/finish` (`ok` when the queue is empty, otherwise `stopped`, or `error` on an exception) and print one
   summary line per company.

Estimates use `ceil_cost` from POC (round up to $0.001). A full company costs about $0.10 + $0.025 + $0.10 + $0.01 × leaders,
roughly $0.27 to $0.31.

### 6.4 Monitors (three, narrow)

Each is created with `type="event_stream", frequency="1d", processor="base"` and
`settings={"query": Q, "include_backfill": True, "output_schema": {"type": "json", "json_schema": MONITOR_OUTPUT_SCHEMA}}`,
`metadata={"app": "launch-radar", "slot": slot}`.

| slot | query |
|---|---|
| `seed` | "Startups announcing a newly closed pre-seed or seed venture funding round, as reported in press releases or tech/business news. One specific company per event." |
| `series_a_plus` | "Startups announcing a newly closed Series A, Series B or later venture funding round, as reported in press releases or tech/business news. One specific company per event." |
| `launch` | "Notable new product launches by early-stage AI and software startups, as reported in press releases or tech/business news. One specific company per event." |

`monitors-ensure` makes, per slot without an `active` row: a reserve of $0.01 (`step='monitor.create'`, since the first
execution runs at creation), then `client.monitor.create`, then `PUT /monitors/{slot}` with `charged_through = now`.

### 6.5 `is_person`

```python
COMPANY_PAGE = re.compile(r"tracxn\.com/.*/company/|crunchbase\.com/organization/|linkedin\.com/company/", re.I)
def is_person(cd) -> bool:
    if COMPANY_PAGE.search(cd.url or ""):
        return False
    return len((cd.name or "").split()) >= 2
```

### 6.6 Scoring (deterministic, `scoring.py`)

- **VC**: the points are exactly POC `score_vc` (`poc.py:647`): tier lead/participant points, extra-investor points and the amount
  bonus (> $10M / $20M / $50M). Prior rounds' `investors` count as participants. It returns **None** when the brief is missing or
  there are no named investors and no parseable amount. The reasons are human readable: `"{Name} led (tier 1)"`,
  `"{Name} joined (tier 2)"`, `"Y Combinator joined"`, `"+{n} more tier-1 investors"`, `"named investors, none tiered"`,
  `"round over $20M"`.
- **Talent**: the points are exactly POC `score_talent` (`poc.py:698`): top school 8 (cap 24), top employer 10 (cap 30), **prior exit**
  15 (cap 30, and only `outcome in {acquired, ipo}`; founding without an exit scores 0), 10+ years 5 (cap 10). Each signal is
  multiplied by `CONFIDENCE_WEIGHT` (high 1.0, **medium 0.8**, low 0.5, missing 0.8). It returns **None** when no leader has any of
  schools, prior companies, structured founded-before entries or years. Reasons look like `"{name}: top school (Berkeley)"`,
  `"{name}: prior exit (Ledgerline, acquired by Northwind)"` and `"{name}: 10+ years"`, plus `"medium-confidence facts count at 80%"`
  when any weight was below 1.
- The team tally never feeds a score.

### 6.7 Skill and slash command

- `.claude/skills/launch-radar/SKILL.md` has three parts:
  - **§0 Hard rules**: never merge; at most **1 PR per run**; never print secrets; never `Read` `~/.config/jvn-launch-radar/`;
    Bash only through the allowlist; no `--dangerously-skip-permissions`.
  - **§1 Run**: `scripts/launch_radar/radar.sh monitors-ensure`, then `radar.sh run --max-companies 3 --budget 1.00` with Bash
    timeout 600000. Re-run while the exit code is 3, at most 4 invocations. Exit 2 means the budget is spent, so log it and continue
    to §2.
  - **§2 PR step**, ported from plan.html's PR-step sketch:
    1. `radar.sh pr-candidates --limit 1`, and stop if it returns none.
    2. `git fetch origin main` and `git worktree add .claude/worktrees/radar-<id> origin/main -b radar/add-<slug>`.
    3. In the worktree, grep `src/frontend/src/config/companies.ts` for the token; if found, stop and clean up.
    4. Read `.claude/skills/add-company/SKILL.md` and do steps 0, 0.5, 1, 2, 3, 5 and 6. Do not use the Skill tool.
    5. Step 4 (logos) is the run's one Agent call; if it fails, open a draft PR with "logos missing" in the body.
    6. `current_head.py` must show one head.
    7. `gh pr create --label launch-radar` with no attribution footer.
    8. `radar.sh set-pr --card-id <id> --pr-url <url>`, then `git worktree remove … --force`.
    9. A 30-minute limit applies to the whole PR step.
  - **§3**: `radar.sh heartbeat --status ok|error --note …` is the **final** step.
- `.claude/commands/launch-radar-once.md`: a headless one-shot that mirrors `.claude/commands/health-watch-once.md`. Read the skill
  file relative to the checkout (do not use the Skill tool), no `ScheduleWakeup` or `/loop`, no background Bash, no sleep loops,
  the heartbeat last, then end the turn.

### 6.8 launchd (test on this laptop, install on the always-on server laptop)

- `scripts/launch_radar/wrapper.sh`: a copy of `scripts/health_watch/wrapper.sh` (lock, process-group watchdog,
  `TOTAL_TIMEOUT_SECS=5400`, and a heartbeat mtime check, where exit 0 without a heartbeat becomes 97). Differences:
  - `CLAUDE_BIN` and `PROJECT_DIR` come **from the environment the plist sets** (required, with no hard-coded user path).
  - `STATE_DIR="$HOME/Library/Application Support/jvn-launch-radar"`.
  - No texting.
  - The wrapper does **not** source or export any secret (`radar.sh` does that itself).
  - The command is:

  ```sh
  "$CLAUDE_BIN" -p /launch-radar-once \
    --allowedTools "Read(./**)" "Edit(./.claude/worktrees/radar-*/**)" "Write(./.claude/worktrees/radar-*/**)" "Agent" \
      "WebSearch" "WebFetch" \
      "Bash(scripts/launch_radar/radar.sh monitors-ensure)" \
      "Bash(scripts/launch_radar/radar.sh run --max-companies 3 --budget 1.00)" \
      "Bash(scripts/launch_radar/radar.sh run --max-companies 0 --budget 1.00)" \
      "Bash(scripts/launch_radar/radar.sh pr-candidates --limit 1)" \
      "Bash(scripts/launch_radar/radar.sh set-pr:*)" "Bash(scripts/launch_radar/radar.sh heartbeat:*)" \
      "Bash(scripts/launch_radar/pr_step.py:*)" \
    --disallowedTools "Read(~/.config/jvn-launch-radar/**)" "Read(~/.ssh/**)" "Read(~/.aws/**)" \
      "Read(~/.zshrc)" "Read(~/.zprofile)" "Read(~/.zshenv)" "Read(~/.bash_profile)" "Read(~/.bashrc)" \
      "Read(~/.netrc)" "Read(~/.config/gh/**)" "Read(./**/.env)" "Read(./**/.env.*)" "Read(./.vercel/**)" \
      "Edit(./.claude/worktrees/*/.git)" "Write(./.claude/worktrees/*/.git)" \
      "Bash(env:*)" "Bash(printenv:*)"
  ```

  **Never `--dangerously-skip-permissions`.** The exact list lives in one place, a `ALLOWED_TOOLS` block in `wrapper.sh`, and
  `SKILL.md` §0 quotes it verbatim. A unit test (`test_launch_radar_wrapper.py`) fails if the skip flag appears, if the
  two copies differ, or if any Bash entry is not one of the exact `radar.sh` commands or `pr_step.py`. There is no
  generic `git`, `gh`, `curl`, `python`, `pip` or `npm` entry: each of those can run code the session wrote or upload a
  local file (`curl -T`, `gh pr create --body-file ~/.ssh/...`), and a `git push` prefix allows `radar/x:main`.
  `scripts/launch_radar/pr_step.py` (stdlib, no secrets, in the main checkout the session cannot write) is the PR
  step's only entry point: it validates every value, runs git with hooks and fsmonitor off, checks the temp
  worktree's `.git` pointer and that the scripts it runs there match `origin/main`, commits only the add-company files
  and pushes only `HEAD:refs/heads/radar/add-<slug>`. The headless PR step does not run `npm ci`/type-check/tests;
  the PR's CI does. When the skill records `status=error`, the wrapper exits 98 so the failure reaches the `.err` log.
- `com.bp.jvn-launch-radar.plist.template`:
  - Label `com.bp.jvn-launch-radar`.
  - `ProgramArguments`: `/bin/sh __PROJECT_DIR__/scripts/launch_radar/wrapper.sh`.
  - `StartCalendarInterval` daily at 07:00.
  - `EnvironmentVariables`: `PATH`, `PROJECT_DIR=__PROJECT_DIR__`, `CLAUDE_BIN=__CLAUDE_BIN__`.
  - Logs `__HOME__/Library/Logs/jvn-launch-radar.{log,err}`. `RunAtLoad` false.
- `install_launch_agent.sh`: fills the placeholders from `$PWD`, `$HOME` and `command -v claude` (or `--claude-bin`), installs the
  agent to `~/Library/LaunchAgents/` and runs `launchctl bootstrap`. It also takes `--uninstall`.
- `README.md` covers the server-laptop setup. Create `~/.config/jvn-launch-radar/env` (mode 600) with `BACKEND_URL`,
  `INTERNAL_API_KEY` and `PARALLEL_API_KEY`, and **do not** export `PARALLEL_API_KEY` from that laptop's `~/.zshrc`, so Claude's
  Bash never sees it. Then run the install script, and test with `PROJECT_DIR=… CLAUDE_BIN=… sh scripts/launch_radar/wrapper.sh`.

---

## 7. Local-only admin auth bypass (design point 13)

### 7.1 Backend (backend unit)

- **Env var:** `DEV_AUTH_BYPASS_EMAIL=<admin email>` → `settings.dev_auth_bypass_email`.
- **New module `src/backend/api/auth/dev_bypass.py`:**
  - `RAILWAY_MARKERS = ("RAILWAY_ENVIRONMENT", "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_PROJECT_ID", "RAILWAY_SERVICE_ID", "RAILWAY_DEPLOYMENT_ID")`.
  - `def running_on_railway() -> bool`: returns true if any marker is a non-empty value in `os.environ`.
  - `def enforce_dev_auth_bypass_guard() -> None`: if the var is set and `running_on_railway()`, **raise `RuntimeError`** (the
    message names the variable and the marker, never the email). If the var is set and we are local, log a loud
    `logger.warning` banner: "DEV_AUTH_BYPASS_EMAIL is ON: unauthenticated loopback requests are treated as <email>. Never set this outside local development."
  - `def dev_bypass_claims(request: Request) -> TokenClaims | None`: returns
    `{"sub": f"dev-bypass|{email}", "email": email, "given_name": None, "family_name": None, "picture": None}` **only if** all of
    these hold:
    1. the setting is set;
    2. `not running_on_railway()`, re-checked on every request;
    3. the request has **no `Authorization` header at all** (check the raw header, because `HTTPBearer(auto_error=False)` also
       yields None for a malformed one);
    4. `request.client` is present and `ipaddress.ip_address(request.client.host).is_loopback`. A `ValueError` (for example
       `"testclient"`) means not loopback.

    Otherwise it returns None.
- **`src/backend/api/main.py`:** call `enforce_dev_auth_bypass_guard()` as the **first** line of `lifespan`, before
  `warn_if_unset()`. If it raises, startup fails.
- **`src/backend/api/auth/dependencies.py`:** `get_optional_user` gains a `request: Request` parameter. When `credentials is None`, it
  returns `dev_bypass_claims(request)` (None means anonymous, as before). A real `Authorization` header always takes the normal
  `validate_token` path. `require_admin` is unchanged and still checks `admins` by email. `get_optional_user_lenient` is
  **not** changed.
- **Tests** (`src/backend/api/tests/test_dev_auth_bypass.py`):
  - ignored without the var;
  - honoured for `127.0.0.1` and `::1` with no header (call `dev_bypass_claims` with a hand-built Starlette `Request` scope, and run
    one route-level test with `TestClient(app, client=("127.0.0.1", 50000))`; starlette 1.0.0 supports `client=`);
  - rejected for a non-loopback client (`10.0.0.5`, `"testclient"`);
  - a real `Authorization: Bearer x` still goes to `validate_token` (patch it) and an invalid token still returns 401;
  - an `Authorization: Basic …` header disables the bypass;
  - `enforce_dev_auth_bypass_guard` raises with each Railway marker set (monkeypatch env) and does not raise without the var;
  - `require_admin` with bypass claims gives 403 when the email is not in `admins` and 200 when it is.

### 7.2 Frontend (frontend unit)

- **Flag:** `VITE_DEV_AUTH_BYPASS=1`. In `src/frontend/src/config/auth.ts`, add `devAdminBypassEnabled: boolean` to `AuthConfig`:
  ```ts
  // LOCAL-ONLY. Vite replaces import.meta.env.DEV with `false` in `vite build`, so this branch is dead code in production.
  const devAdminBypassEnabled = import.meta.env.DEV && import.meta.env.VITE_DEV_AUTH_BYPASS === '1';
  ```
  If both `bypassEnabled` (the existing QA `VITE_AUTH_BYPASS`) and `devAdminBypassEnabled` are true, **throw** at module evaluation.
  When it is on, log a loud `console.warn`. Declare `readonly VITE_DEV_AUTH_BYPASS?: string` in `src/frontend/src/vite-env.d.ts`.
- **`src/frontend/src/features/auth/useAuth.ts`:** add a module-stable `DEV_ADMIN_BYPASS_RESULT` / `useAuthDevAdminBypass`. It returns
  `isEnabled: true, isAuthenticated: true, isLoading: false`, a placeholder user `{ sub: 'dev-bypass|local', name: 'Local admin (dev bypass)' }`,
  no-op login and logout, and a `getToken` that **rejects with `NotAuthenticatedError`**. That makes `getTokenOrNull()` return null,
  so RTK Query sends **no** `Authorization` header. Dispatch:
  `export const useAuth = AUTH_CONFIG.devAdminBypassEnabled ? useAuthDevAdminBypass : AUTH_CONFIG.bypassEnabled ? useAuthBypass : useAuthReal;`
- **`src/frontend/src/features/auth/authService.ts`:** `fetchCurrentUser(token: string | null, signal?)` omits the `Authorization`
  header when `token` is null.
- **`src/frontend/src/features/auth/useCurrentUser.ts`:** in dev-bypass mode, call `fetchCurrentUser(null, signal)` and do not call
  `getToken()`. `/api/users` then resolves through the backend bypass, and `AdminRoute` reads the real `isAdmin` from the backend.
  `AdminRoute.tsx` itself is **not** changed.
- **`src/frontend/src/components/shared/AuthProviders.tsx`:** skip the real providers when `devAdminBypassEnabled`, as it already
  does for `bypassEnabled`.
- Other user-scoped calls that use `getToken()` directly may hit `NotAuthenticatedError` in bypass mode and fall back to their
  anonymous path. That is accepted locally; do not widen any type to hide it.
- **Tests (Vitest):**
  - `src/__tests__/config/authDevBypass.test.ts`: `vi.stubEnv('VITE_DEV_AUTH_BYPASS','1')` together with `vi.stubEnv('DEV', true)`
    enables the bypass and `vi.stubEnv('DEV', false)` disables it (use `vi.resetModules()` and a dynamic import); setting both flags
    throws.
  - `src/__tests__/features/auth/useAuthDevAdminBypass.test.ts`: authenticated, `getToken` rejects with `NotAuthenticatedError`, and
    `getTokenOrNull` gives null.
  - An `authService` test: `fetchCurrentUser(null)` sends no `Authorization` header.

### 7.3 Docs (backend unit)

In `.claude/skills/run/SKILL.md`, add a `## Local admin bypass` section (after Mode 2) covering:
- both flags, with `DEV_AUTH_BYPASS_EMAIL=brendanpotter00@gmail.com` on the uvicorn command and `VITE_DEV_AUTH_BYPASS=1 npm run dev -w src/frontend`;
- that it works with plain Vite (the `/api/admin` and `/api/users` proxies go to :8000) and with `vercel dev` (the proxies forward
  no `Authorization` when none is sent);
- the one-time local admin grant, done after the first `/api/users` load creates the user row:
  `docker exec jobscraper-postgres psql -U postgres -d jobscraper -c "INSERT INTO admins (user_id) SELECT id FROM users WHERE email='brendanpotter00@gmail.com' ON CONFLICT DO NOTHING"`;
- the guarantees: the backend refuses to start if a Railway marker is present, the bypass is honoured only for loopback clients
  without an `Authorization` header, the Vite flag is compiled out of production builds, and the Vercel proxy is unchanged.

---

## 8. Test and check commands per unit

`V=/Users/brendanpotter/Documents/develop/Job-Visualizer-Notifier/.venv/bin`. Postgres must be up (`jobscraper-postgres`).
Backend tests build their own per-worker schema, so the foreign revision on DB `jobscraper` does not matter.

**Backend**
```bash
cd <worktree>/src/backend
$V/mypy                                                     # must be clean (CI gate)
$V/pytest api/tests/test_launch_radar_service.py api/tests/test_launch_radar_admin.py \
          api/tests/test_internal_launch_radar.py api/tests/test_dev_auth_bypass.py \
          api/tests/test_proxy_path_allowlists.py api/tests/test_alembic_single_head.py \
          api/tests/test_main_lifespan.py api/tests/test_auth.py api/tests/test_dependencies.py
$V/pytest                                                   # full backend suite before handing back
cd <worktree> && $V/alembic heads                           # exactly one head
cd <worktree>/scripts && $V/pytest tests/integration/test_alembic_parity.py
```

**Frontend** (run `npm ci` once at the worktree root first)
```bash
cd <worktree>
npm run type-check                                          # zero errors
npx -w src/frontend eslint src --max-warnings 149           # CI gate; add no new warnings
npm test -- --run                                           # full Vitest suite, including admin.serverless and routes/nav tests
npm run build                                               # proves the dev bypass compiles out (grep dist for VITE_DEV_AUTH_BYPASS → none)
```

**Loop**
```bash
cd <worktree>/scripts && $V/pytest tests/unit -k launch_radar   # SDK fully faked; no network (httpx.MockTransport)
cd <worktree> && sh -n scripts/launch_radar/wrapper.sh && sh -n scripts/launch_radar/radar.sh && sh -n scripts/launch_radar/install_launch_agent.sh
plutil -lint scripts/launch_radar/com.bp.jvn-launch-radar.plist.template
```

There is no Python linter gate in CI (no ruff config). `mypy` covers only `src/backend/api`.

---

## 9. File ownership (no overlap)

Paths are relative to the worktree root. "new" = create, "edit" = modify an existing file. Nobody edits `plan.html`,
`plan.packed.html`, `scripts/launch_radar_poc/**`, `.gitignore` or `.claude/launch.json`.

### Backend unit
- edit `src/backend/api/db_models.py`
- new `src/backend/alembic/versions/<autogen>_launch_radar_tables.py`
- edit `src/backend/api/models.py` (append the Launch Radar models)
- new `src/backend/api/services/launch_radar.py`
- edit `src/backend/api/routers/admin.py`
- new `src/backend/api/routers/internal_launch_radar.py`
- edit `src/backend/api/main.py` (include the router; call the bypass guard first in lifespan)
- edit `src/backend/api/config.py`
- new `src/backend/api/auth/dev_bypass.py`
- edit `src/backend/api/auth/dependencies.py`
- new `src/backend/api/tests/test_launch_radar_service.py`
- new `src/backend/api/tests/test_launch_radar_admin.py`
- new `src/backend/api/tests/test_internal_launch_radar.py`
- new `src/backend/api/tests/test_dev_auth_bypass.py`
- edit (only if needed) `src/backend/api/tests/test_auth.py`, `src/backend/api/tests/test_dependencies.py`, `src/backend/api/tests/test_main_lifespan.py`
- edit `api/admin.ts` (the two allowlist lines in §2.2 only)
- edit `src/backend/CLAUDE.md` (routes, env vars, tables), `src/backend/docs/database-schema.md` (four tables)
- edit `.claude/skills/run/SKILL.md` (`## Local admin bypass`)

### Frontend unit
- edit `src/frontend/src/config/routes.ts`
- edit `src/frontend/src/components/layout/NavigationDrawer.tsx`
- edit `src/frontend/src/app/App.tsx`
- edit `src/frontend/src/features/admin/adminApi.ts`
- new `src/frontend/src/features/admin/launchRadarTypes.ts`
- new `src/frontend/src/pages/AdminLaunchRadarPage/AdminLaunchRadarPage.tsx`
- new `src/frontend/src/pages/AdminLaunchRadarPage/format.ts`
- new `src/frontend/src/pages/AdminLaunchRadarPage/components/{RadarCard,ScoreBadge,CardStatusLine,CardBody,EventLine,DeleteCardDialog}.tsx`
- edit `src/frontend/src/config/auth.ts`
- edit `src/frontend/src/vite-env.d.ts`
- edit `src/frontend/src/features/auth/useAuth.ts`
- edit `src/frontend/src/features/auth/useCurrentUser.ts`
- edit `src/frontend/src/features/auth/authService.ts`
- edit `src/frontend/src/components/shared/AuthProviders.tsx`
- edit `src/frontend/vite.config.ts` (the `/api/admin` dev proxy)
- new `src/frontend/src/__tests__/pages/AdminLaunchRadarPage/{AdminLaunchRadarPage,RadarCard,format}.test.ts(x)`
- new `src/frontend/src/__tests__/features/admin/launchRadarApi.test.ts`
- new `src/frontend/src/__tests__/config/authDevBypass.test.ts`
- new `src/frontend/src/__tests__/features/auth/useAuthDevAdminBypass.test.ts`
- edit (only if they break or need a case) existing tests under `src/frontend/src/__tests__/` for routes/nav, `config/auth`,
  `features/auth/*`, `components/shared/AuthProviders` and `features/admin/adminApi`. This does **not** include
  `__tests__/api/serverless/admin.serverless.test.ts`, which nobody edits.
- edit `src/frontend/CLAUDE.md` (one line for the page and the flag)
- runs `npm ci` (generates `node_modules`, which is never committed)

### Loop unit
- new `scripts/launch_radar/__init__.py`, `radar.py`, `radar.sh`, `config.py`, `backend_client.py`, `parallel_client.py`,
  `schemas.py`, `domains.py`, `monitors.py`, `leaders.py`, `research.py`, `scoring.py`, `ats.py`, `card.py`, `state.py`, `pipeline.py`
- new `scripts/launch_radar/wrapper.sh`, `com.bp.jvn-launch-radar.plist.template`, `install_launch_agent.sh`, `README.md`
- new `scripts/tests/unit/launch_radar_fakes.py` (the fake Parallel client and backend transport)
- new `scripts/tests/unit/test_launch_radar_{domains,scoring,leaders,research,ats,card,state,pipeline,backend_client,monitors,cli,wrapper}.py`
- edit `scripts/requirements-dev.txt` (add `httpx>=0.27`, which the tests import; the runtime gets it from `radar.sh`'s `uv --with`)
- new `.claude/skills/launch-radar/SKILL.md`
- new `.claude/commands/launch-radar-once.md`
- edit `CLAUDE.md` (root): a "Launch Radar" entry under Common Tasks pointing at the skill
- edit `scripts/CLAUDE.md`: one line in Shared/Architecture pointing at `scripts/launch_radar/README.md`

---

## 10. Cross-unit seams (the parts that must agree)

| seam | producer → consumer | pinned in |
|---|---|---|
| admin JSON (camelCase) | backend → frontend | §2.1, §2.4, §5.2 |
| proxy allowlist entries | backend (`api/admin.ts`) → frontend fetch paths | §2.2, §5.3 |
| internal JSON (snake_case) and status codes 402/409 | backend ↔ loop | §2.3 |
| card payload | loop → backend (validated, stored) → frontend (camelCase) | §4, §2.4, §5.2 |
| `normalize_domain` vectors | backend and loop | §3 |
| bypass: no `Authorization` header and a loopback client | frontend → backend | §7 |
