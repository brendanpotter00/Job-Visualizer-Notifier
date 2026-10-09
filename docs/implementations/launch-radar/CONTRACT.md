# Launch Radar — implementation contract

The contract between the three parts of Launch Radar as shipped: the **backend** (tables, routes, status codes), the
**frontend** (`/admin/launch-radar`) and the **loop** (`scripts/launch_radar/`). Where this file and `plan.html` (the
approved design) disagree, this file wins. §9 lists the seams that must change together.

**The add-company PR step is back, driven by the Saved column** (2026-10-08, design:
`saved-pr/PLAN.md`). The first version (removed in #335 on 2026-10-07) picked one verified card a day on its own and
opened PRs #333 and #334. Now a human decides: Brendan saves a card, the next nightly run opens one add-company PR for
it, and the card shows a "View PR #N" link. The loop **never merges**. PR tracking lives in its own table
(`launch_radar_pr_requests`, §1.7); the legacy `launch_radar_cards.pr_url` column (§1.4) and the payload flag
`pr_ready` (§4) stay unused.

---

## 0. Rules for every change

- Never print, echo, log or `cat` a secret or a `.env` file. Python code never logs `INTERNAL_API_KEY` or
  `PARALLEL_API_KEY`. It may log only whether each one is set.
- **No billed Parallel call in tests.** All tests mock the Parallel SDK. The loop imports `parallel` lazily inside
  `parallel_client.make_client()`, so the test suite runs without the SDK installed.
- Fix the design when something fails. Do not widen types, catch and ignore errors, or relax constraints just
  to make an error go away.

---

## 1. Database

Models live in `src/backend/api/db_models.py`, after `EnrichmentTick`. Money is `NUMERIC(10,4)`, not Float, because
a cap compared with float sums drifts. psycopg2 returns `Decimal`; convert to `float` only at the response boundary.

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
| `status` | Text | no | `'new'` | `CHECK ck_launch_radar_cards_status: status IN ('new','saved','archived','deleted')` (autogenerate does not compare the CHECKs of an existing table, so `api/tests/test_db_models.py` pins this text against revision `33ff7e590a46`) |
| `tracked_company_id` | Text, soft link to `companies.id` (no FK, house style) | yes | | set by the backend at insert (§2.3). Nothing nulls it when that company row is deleted, so a stale id keeps the card "Already tracked" (harmless) |
| `pr_url` | Text | yes | | **legacy, unused**: written by the first, removed PR step. Nothing reads or writes it now except the tombstone, which still clears it (the CHECK below). The PR step tracks its PRs in `launch_radar_pr_requests` (§1.7), never here |
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

- Lifecycle: new → saved (save) → new (unsave); new or saved → archived (archive) → new (restore); archived → deleted. One guarded
  UPDATE per move: `UPDATE … SET status=%s, archived_at=<now() for archived, else NULL>, updated_at=now(), updated_by=%s WHERE id=%s AND status = ANY(<allowed sources>) RETURNING …`
  (save from `new`; unsave/restore to `new` from `saved` or `archived`; archive from `new` or `saved`). When the PATCH
  body carries `from`, the allowed sources narrow to that one status (compare-and-swap), and a miss whose current status
  is not `from` is a **409** naming it (`card is archived, not saved; reload and try again`).
- delete (tombstone): `UPDATE … SET status='deleted', payload=NULL, pr_url=NULL, tracked_company_id=NULL, archived_at=NULL, deleted_at=now(), updated_at=now(), updated_by=%s WHERE id=%s AND status='archived' RETURNING id`
- If no row comes back, run `SELECT status … WHERE id=%s`. A missing row or `status='deleted'` gives **404**. A row in the wrong
  state gives **409**. Never `DELETE FROM` a card.
- **PR-request hooks** (§1.7), in the **same transaction** as the move:
  - Save: `INSERT INTO launch_radar_pr_requests (card_id) VALUES (%s) ON CONFLICT (card_id) DO UPDATE SET status='queued',
    requested_at=now(), retry_after=NULL, finished_at=NULL, updated_at=now() WHERE launch_radar_pr_requests.status='cancelled'`.
    A `failed`, `no_board`, `already_tracked` or `open` row is left alone (re-saving never retries; `radar.sh pr-requeue`
    does).
  - Unsave and Archive: `UPDATE … SET status='cancelled', finished_at=now(), updated_at=now() WHERE card_id=%s AND
    status='queued'`. An `in_progress` row is left alone: the loop's `pr-check` cancels it before publishing.
  - Restore: nothing.
  - Delete (tombstone): `DELETE FROM launch_radar_pr_requests WHERE card_id=%s`. The card row stays, so the FK's
    `ON DELETE CASCADE` never fires; this is the explicit cleanup.
- `list_cards` reads the request with `LEFT JOIN launch_radar_pr_requests r ON r.card_id = c.id AND r.status = 'open'`
  (`open_pr_url`, `open_pr_number` in `CardRow`); `set_status` reads the same two fields after its UPDATE. So a card
  carries a PR link only while its request is `open`.

### 1.6 Migrations

- One revision, `33ff7e590a46` (`launch radar tables`, after `904d5bc44e4b`), creates the four tables with every CHECK
  (the card status CHECK already includes `'saved'`), UNIQUE and index; its downgrade drops them. It was autogenerated
  from `db_models.py` against a scratch database at `904d5bc44e4b` (`create_all` of every other table, then
  `alembic stamp 904d5bc44e4b`); `alembic check` is clean after it. Its only foreign keys are `launch_radar_cards.run_id`
  and `launch_radar_spend.run_id` → `launch_radar_runs.id`; `tracked_company_id` has none (soft link).
- Autogenerate does not compare the CHECKs of an existing table, so `api/tests/test_db_models.py` pins the model's card
  status CHECK to the same text in the revision, and `api/tests/test_migration_launch_radar_tables.py` round-trips it
  (upgrade, constraints, downgrade, upgrade again) in a throwaway database.
- Revision `b7c4d1370996` (`launch radar pr requests`, after `33ff7e590a46`) creates `launch_radar_pr_requests` (§1.7),
  autogenerated the same way against a scratch database at `33ff7e590a46`. Its hand-written backfill gives every card
  already `saved` a row: `already_tracked` (finished now) when it has a `tracked_company_id`, else `queued`. It ignores
  the legacy `pr_url` (the only values point at the closed PRs #333/#334, and a closed PR does not block a save). Its
  downgrade drops the two indexes and the table, so the queue and every recorded PR link are lost (the PRs stay on
  GitHub). `test_db_models.py` pins its status and PR-URL CHECK text; `test_migration_launch_radar_pr_requests.py`
  round-trips it and checks the backfill.
- Never add files under `scripts/shared/migrations/`.

### 1.7 `launch_radar_pr_requests`: the add-company PR of one Saved card

One row per card, **ever** (`db_models.LaunchRadarPrRequest`, after `LaunchRadarCard`). Saving a card creates it (§1.5);
the loop moves it through the internal routes (§2.3). No branch column: the branch is always `radar/card-<card_id>`.

| column | type | null | default | notes |
|---|---|---|---|---|
| `id` | Integer PK | no | serial | |
| `card_id` | Integer FK → `launch_radar_cards.id` `ON DELETE CASCADE` | no | | `UNIQUE uq_launch_radar_pr_requests_card_id` |
| `status` | Text | no | `'queued'` | `CHECK ck_launch_radar_pr_requests_status: status IN ('queued','in_progress','open','failed','no_board','already_tracked','cancelled')` |
| `attempts` | Integer | no | `0` | `CHECK ck_launch_radar_pr_requests_attempts: attempts >= 0`. +1 at each claim, −1 on an `env_error` report |
| `pr_url` | Text | yes | | `CHECK ck_launch_radar_pr_requests_pr_url: pr_url IS NULL OR pr_url ~ '^https://github\.com/brendanpotter00/Job-Visualizer-Notifier/pull/[0-9]+$'` (a §9 seam) |
| `pr_number` | Integer | yes | | parsed from `pr_url` by the backend. `CHECK ck_launch_radar_pr_requests_pr_pair: (pr_url IS NULL) = (pr_number IS NULL)` |
| `last_reason` | Text | yes | | a `PrReason` code (§2.3), never web text |
| `requested_at` | TIMESTAMP(tz) | no | `now()` | set at queue and re-queue; the queue is FIFO on `(requested_at, id)` |
| `retry_after` | TIMESTAMP(tz) | yes | | a re-queued failure sets `now() + 12 hours` |
| `claimed_at` | TIMESTAMP(tz) | yes | | set at claim |
| `finished_at` | TIMESTAMP(tz) | yes | | set on reaching `open`, `failed`, `no_board`, `already_tracked` or `cancelled` |
| `updated_at` | TIMESTAMP(tz) | no | `now()` | set by every UPDATE |

Also: `CHECK ck_launch_radar_pr_requests_open: (status = 'open') = (pr_url IS NOT NULL)`; a partial unique index
`uq_launch_radar_pr_requests_pr_url ON (pr_url) WHERE pr_url IS NOT NULL` (one PR never recorded for two cards); index
`idx_launch_radar_pr_requests_status_requested (status, requested_at)` (the queue scan).

Loop moves (service functions in §2.3):

```
queued ──claim──▶ in_progress ──open──────────▶ open            (pr_url, pr_number)
                        │──already_tracked──▶ already_tracked
                        │──no_board─────────▶ no_board          (last_reason)
                        │──cancelled────────▶ cancelled         (only when the card is no longer saved)
                        │──failed env_error ─▶ queued, attempts − 1, retry_after = now()+12h
                        │──failed, retryable, attempts < 3 ──▶ queued (retry_after = now()+12h)
                        └──failed, terminal or attempts = 3 ──▶ failed
in_progress, claimed_at older than 2 h ──(at the next claim)──▶ queued (retry_after NULL)
                                          or failed if attempts = 3   (last_reason 'abandoned')
```

`MAX_PR_ATTEMPTS = 3`, `PR_RETRY_AFTER = '12 hours'`, `STALE_PR_AFTER = '2 hours'` (`services/launch_radar.py`).
**Never two PRs for one card:** `UNIQUE(card_id)`; the claim is a guarded UPDATE under `FOR UPDATE OF r SKIP LOCKED`;
`open` is never re-queued (no card move touches it, `requeue` refuses it); the partial unique index on `pr_url`; and on
GitHub one fixed branch per card, whose trusted open PR a later attempt adopts instead of opening another (§6.9).

---

## 2. Backend endpoints

All JSON field casing is exact. **Admin responses are camelCase**, through response models with
`ConfigDict(alias_generator=to_camel, populate_by_name=True)`, the same pattern as the other models in `models.py`.
**Internal requests and responses are snake_case.** Internal request models use `ConfigDict(extra="forbid")` and no
alias generator. Every psycopg2 error rolls back and raises 500 with a generic detail, as in `routers/admin.py`.
The service owns `commit()`.

### 2.1 Admin routes (`src/backend/api/routers/admin.py`, prefix `/api/admin`, every route `Depends(require_admin)`)

#### `GET /api/admin/launch-radar/cards`

Query: `status: Literal['new','saved','archived']` (required; anything else, `deleted` included, gives 422), `limit: int = 25 (1..100)`,
`offset: int = 0 (>=0)`, `sort: Literal['announced','talent','vc','added'] = 'announced'` (anything else gives 422).
Order, the same on every tab: `announced` by `(payload->'event'->>'announced_at') DESC NULLS LAST`; `talent` by
`(payload->'scores'->>'talent')::numeric DESC NULLS LAST`; `vc` by `(payload->'scores'->>'vc')::numeric DESC NULLS LAST`;
`added` by `posted_at DESC`. Every sort then breaks ties by the announced date `DESC NULLS LAST`, then `posted_at DESC`,
then `id DESC`, so paging is deterministic. Each key maps to a fixed `ORDER BY` in the service; the request never reaches SQL text.

```json
{
  "cards": [ /* LaunchRadarCard, §2.4 */ ],
  "total": 2,
  "counts": { "new": 2, "saved": 0, "archived": 1 },
  "stats": {
    "lastRun": { "startedAt": "2026-10-07T01:31:00Z", "endedAt": "2026-10-07T01:36:12Z", "status": "ok", "host": "server-laptop" },
    "spendUsd": 0.46,
    "capUsd": 5.0
  }
}
```

- `total` counts the rows with the requested status. `counts` always covers all three tabs, whatever the filter.
- `lastRun` is the newest `launch_radar_runs` row by `started_at`, or `null` when there are no runs.
- `spendUsd` is `SUM(launch_radar_spend.amount_usd)`, rounded to 4 places. `capUsd` is `settings.launch_radar_spend_cap_usd`.
- The admin page no longer shows `stats` (the sub line under the heading was removed 2026-10-07). The backend still sends
  it, unchanged; the client neither types nor checks it.
- Deleted rows are never selected. The query has `WHERE status IN ('new','saved','archived')`, or the single requested status.

#### `PATCH /api/admin/launch-radar/cards/{card_id}`

`card_id: int` (ge=1). Body `{"status": "saved" | "archived" | "new", "from"?: "new" | "saved" | "archived"}`, with
`extra="forbid"`. `from` is the status the client saw the card in: when sent, the move applies only while the card is
still in it (Unsave and Restore both send `"new"`, so a stale Unsave could otherwise restore an archived card). The page
sends it on every action; omitted, any allowed source moves (backward compatible).
- `"saved"` (Save) applies only to a `new` card; `"archived"` to a `new` or `saved` card; `"new"` (Unsave / Restore) to a
  `saved` or `archived` card.
- 200 returns the updated `LaunchRadarCard`. 404 if the card is missing or deleted. 409 for any other move (already in that
  state, `archived` → `saved`, or a `from` that is not the card's current status), with a detail naming the card's current status.
- Each move also runs its PR-request hook (§1.5) in the same transaction: Save queues the card's add-company PR; Unsave and
  Archive cancel a request that is still `queued`.

#### `DELETE /api/admin/launch-radar/cards/{card_id}`

Permanent delete (the tombstone in §1.5). It also deletes the card's PR request row, if any.
- **204 No Content** with no body (FastAPI `Response(status_code=204)`).
- 404 if the card is missing or already deleted. **409** if `status` is `new` or `saved`: a card must be archived first.

Router functions: `admin_launch_radar_cards`, `admin_set_launch_radar_status`, `admin_delete_launch_radar_card`.
Service functions: `list_cards`, `card_counts`, `run_stats`, `set_status`, `delete_card`.

### 2.2 Proxy allowlist (`api/admin.ts`)

Two entries in `PROXIED_ROUTES`, under a `// launch radar` comment: `'launch-radar/cards'` (GET) and
`'launch-radar/cards/:id'` (PATCH, DELETE). The loop's `/api/internal/launch-radar/*` is never proxied. `api/admin.ts`
forwards PATCH and DELETE bodies (`METHODS_WITH_BODY`), and `forwardResponse` handles a 204.
`src/backend/api/tests/test_proxy_path_allowlists.py` fails in both directions unless the backend routes and the
allowlist agree.

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
| `GET /cards` | query `domain` (repeatable, 0..100, normalized server-side) and/or `missing_talent=true` (no **leaders' part** of Talent: `scores.talent_leaders` null on a blended card, `scores.talent` null on a pre-blend one, so a team-only card with a Talent number is still found), or `all=true` (every live card, `rescore --all`; takes no other filter); `status` (repeatable, `new`/`saved`/`archived`; none = every live status); `after_id` ≥0 (0); `limit` 1..500 (100) | 200 `{"cards": [{"id", "domain", "status", "payload"}]}`: live cards only, `id > after_id`, by id, payload as stored. Keyset-paged: the loop asks again from the last id until a page comes back short | 422 no filter / `all=true` with `domain` or `missing_talent` / more than 100 domains / bad `status` |
| `POST /cards` | `{"run_uuid": str, "payload": LaunchRadarPayload (§4)}` | **201** `{"id": int, "tracked_company_id": str \| null}` | 404 unknown run · 409 run not running · **409 domain already posted** · 422 payload invalid or domain not normalized |
| `PUT /cards/{card_id}/payload` | `{"payload": LaunchRadarPayload (§4)}` (`extra="forbid"`; no run needed) | 200 `{"id", "domain", "status", "posted_at", "updated_at"}` | 404 missing or deleted · 422 payload invalid (URL rules included) or `payload.domain` ≠ the card's |
| `POST /pr-requests/next` | `{}` (`extra="forbid"`) | **200** `PrClaim` · **204** nothing claimable | — |
| `GET /pr-requests/{card_id}` | — | 200 `PrRequestOut` + `card_status` | 404 no request, or the card is deleted |
| `POST /pr-requests/{card_id}/result` | `{"outcome": "open"\|"failed"\|"no_board"\|"already_tracked"\|"cancelled", "pr_url": str<=200 \| null, "reason": PrReason \| null}` (`extra="forbid"`) | 200 `PrRequestOut` | 404 · 409 not `in_progress`, a different URL on an `open` row, the PR already on another card, `cancelled` while the card is still saved · 422 shape (below) |
| `POST /pr-requests/{card_id}/requeue` | `{}` | 200 `PrRequestOut` | 404 · 409 from `queued` / `in_progress` / `open`, or the card is not `saved` |
| `GET /pr-requests` | query `status` (repeatable, optional: none = every status), `limit` 1..500 (100) | 200 `{"requests": [PrRequestOut + "domain", "company"]}`, oldest first | 422 bad status / limit |

`card_id` in a path is `1..2147483647` (an INTEGER column).

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
{ "domains": { "raindrop.ai": { "card_id": 1, "status": "new" | "saved" | "archived" | "deleted" } },   // only seen ones
  "names":   { "Raindrop AI": "raindrop-ai" } }                                             // only names matching a tracked company
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

**`PUT /cards/{card_id}/payload` (`replace_payload`)**, for `radar.py refresh`: `SELECT … FOR UPDATE` (so a delete cannot
race it), 404 for a missing card or a tombstone, 422 when the payload's domain is not the card's, then
`UPDATE … SET payload, company_name = payload.company, updated_at = now()`. Status, `posted_at`,
`tracked_company_id`, `run_id` and `updated_by` stay. `GET /cards` (`find_cards`) is its read-only lookup.

**The PR-request routes** (`radar.sh pr-*`, §6.2; lifecycle in §1.7). Service: `claim_next_pr`, `get_pr_request`,
`report_pr`, `requeue_pr`, `list_pr_requests`.

- **`POST /pr-requests/next` (`claim_next_pr`)**, one transaction: (1) stale recovery: `in_progress` with `claimed_at`
  older than 2 h → `queued`, or `failed` at 3 attempts, `last_reason='abandoned'`; (2) a queued request whose saved card
  has a `tracked_company_id` → `already_tracked`; (3) a queued request whose card is not `saved` → `cancelled`; (4) pick
  the oldest `queued` request of a `saved` card with `retry_after` NULL or past, `ORDER BY requested_at, id`,
  `FOR UPDATE OF r SKIP LOCKED`; it becomes `in_progress`, `attempts + 1`, `claimed_at = now()`. None → 204.
- **`/result` (`report_pr`)** only from `in_progress`, except that an identical repeat of an `open` report (same URL) is a
  200 no-op. `open` stores `pr_url` and `pr_number` (parsed from the URL, `fullmatch`, so a trailing newline is a 422,
  never a CHECK 500). `already_tracked`, `no_board` and `cancelled` are final. `failed` with a terminal reason, or a
  retryable one on the 3rd attempt, is final; a retryable one goes back to `queued` with `retry_after = now() + 12 h`;
  `env_error` does too, and gives the attempt back (`GREATEST(attempts - 1, 0)`).
- **`/requeue` (`requeue_pr`)**, interactive only: `failed`, `no_board`, `already_tracked` or `cancelled` → `queued`,
  `attempts = 0`, `requested_at = now()`, clearing `retry_after`, `last_reason` and `finished_at`.

`/result` validation (`LaunchRadarPrResult`, a `model_validator`, so a bad shape is a 422):
- `open` needs `pr_url` matching the PR URL pattern (§9) and no `reason`; every other outcome forbids `pr_url`.
- `failed` and `no_board` need a `reason` of their group; `already_tracked` and `cancelled` forbid one.

`PrReason` (`LaunchRadarPrReason`, a `Literal`), grouped by what it does:

| group | reasons |
|---|---|
| `no_board` (final) | `board_not_found`, `board_empty`, `unsupported_ats` |
| `failed`, terminal | `unsafe_value`, `pr_closed` |
| `failed`, retryable (12 h, at most 3 attempts) | `step_refused`, `multi_head`, `git_error`, `gh_error`, `timeout`, `other` |
| `failed`, refunded | `env_error` (gh, git or the network broke before any push) |
| set only by stale recovery | `abandoned` (never accepted on `/result`) |

```jsonc
// PrClaim (read from the card's stored payload; never the whole payload)
{ "card_id": 21, "domain": "bluecore.energy", "company": "Bluecore", "website": "https://bluecore.energy",
  "careers_url": "…" | null, "one_liner": "…" | null, "what_they_do": "…" | null,
  "ats": { "provider": "ashby" | null, "board_token": "…" | null, "board_url": "…" | null, "verified": true, "job_count": 9 | null },
  "latest_round": { "round": "Seed" | null, "amount_usd": "$5M" | null, "announced_at": "2026-10-01" | null } | null,
  "attempts": 1, "requested_at": "2026-10-08T03:00:00Z" }
// PrRequestOut
{ "card_id": 21, "status": "open", "attempts": 1,
  "pr_url": "https://github.com/brendanpotter00/Job-Visualizer-Notifier/pull/412" | null, "pr_number": 412 | null,
  "last_reason": "gh_error" | null, "requested_at": "…", "retry_after": "…" | null, "claimed_at": "…" | null,
  "finished_at": "…" | null }
```

### 2.4 `LaunchRadarCard`: admin response model (camelCase)

`models.py` defines one set of nested Pydantic models used **both** to validate the loop's snake_case POST body (by
field name) and to serialize the admin response (by camelCase alias). The admin card is built from the row columns
plus the parsed payload:

```python
LaunchRadarCardOut.model_validate({**row["payload"], "id": row["id"], "status": row["status"],
                                   "tracked_company_id": row["tracked_company_id"],
                                   "posted_at": row["posted_at"], "archived_at": row["archived_at"],
                                   "updated_by": row["updated_by"],
                                   "pr_url": row["open_pr_url"], "pr_number": row["open_pr_number"]})
```

Its JSON is exactly the TypeScript `LaunchRadarCard` in §5.2.

`prUrl` / `prNumber` (`pr_url: str | None = None`, `pr_number: int | None = None`) are the card's add-company PR: set only
while its request (§1.7) is `open`, **whatever the card's tab** (unsaving a card does not hide a PR that already exists),
null otherwise. They are set after the payload keys, so a stray key in a stored payload can never supply them, and the
legacy `launch_radar_cards.pr_url` column never feeds them. No new admin route, so the proxy allowlist (§2.2) is
unchanged.

The URL rules (§4) and the `announced_at` shape are enforced on INPUT (`POST /cards`, `PUT /cards/{id}/payload`).
`LaunchRadarCardOut` reads the stored payload through `tolerate_stored_payload` first: a stored URL that fails the rule is
nulled (a source without a usable URL is dropped; `website`, never null, falls back to `https://<domain>`), a non-ISO
`announced_at` is nulled, and the card is logged, so one old or hand-edited row is never skipped from the list (while
`total` counts it) nor turns a committed PATCH into a 500. The stored row is not changed. Only a payload of a different
shape (a missing key) is skipped from the list, and logged, so one such row cannot blank the dashboard.

### 2.5 Config (`src/backend/api/config.py`)

| env var | field | default | rule |
|---|---|---|---|
| `LAUNCH_RADAR_SPEND_CAP_USD` | `launch_radar_spend_cap_usd: float` | `5.0` | `Field(gt=0, le=50)`. Set only by the operator; the loop cannot raise it |
| `DEV_AUTH_BYPASS_EMAIL` | `dev_auth_bypass_email: str \| None` | `None` | §7.1 |

---

## 3. Domain normalization (shared algorithm, two copies)

The backend (`services/launch_radar.py::normalize_domain`) and the loop (`launch_radar/domains.py::normalize_domain`)
each carry a copy, ported verbatim from the POC's `normalize_domain`:

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

`LaunchRadarPayload` (Pydantic, `extra="forbid"` on input). Every key is required unless shown as nullable. Every URL
(`website`, `careers_url`, `event.source_url`, `ats.board_url`, `ats.checked_url`, `leaders[].linkedin_url`,
`leaders[].profile_url`, `sources[].url`) must be an absolute `http(s)` URL with a host, no whitespace and at most 2000
characters, or null where nullable; anything else is a 422. The loop's `safe_http_url` applies the same rule and nulls a
failing value before it posts. `event.announced_at` must match `^[0-9]{4}-[0-9]{2}(-[0-9]{2})?$` or be null; the loop
normalizes every event date with `card.announced_on` (the admin list sorts this text as a date).

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
    "announced_at": "2026-09-17" | "2026-09" | null, // ISO day, or year-month when only the month is known (422 otherwise)
    "round": "Series A" | null,
    "amount_usd": "$35M" | null,
    "investors": "CRV, Lightspeed" | null,
    "origin": "monitor" | "findall_backfill" | "task brief"   // findall_backfill: `radar.py backfill` (§6.3)
  } | null,
  "scores": {                                     // Talent is a 50/50 blend (§6.6)
    "talent": 49 | null,                           // 0-100: the parts summed, or a lone part doubled; null = no data on either
    "vc": 55 | null,                               // null = brief missing or no investors and no amount
    "talent_reasons": ["Priya Raman: top school (Berkeley)", "…"],   // the leaders' part
    "vc_reasons": ["CRV led (tier 2)", "Lightspeed joined (tier 1)", "round over $20M"],
    "talent_leaders": 24 | null,                   // 0-50, optional (default null): null = no leader people data
    "talent_team": 25 | null,                      // 0-50, optional (default null): null = no usable team tally
    "talent_basis": "both" | "leaders" | "team" | null,  // optional (default null); null with a talent = pre-blend card
    "talent_team_reasons": ["3 of the 3 employers listed across 6 profiles are top employers (+25)", "…"]  // optional (default [])
  },
  "leaders": [{
    "name": "Sam Rivera",
    "title": "Co-Founder & CTO" | null,
    "linkedin_url": "https://linkedin.com/in/example-sam-rivera" | null,
    "profile_url": "https://…" | null,             // the FindAll candidate url (a brief leader: its LinkedIn URL)
    "summary": "WPI. Apple visionOS designer; interned at Google and SpaceX" | null,  // deterministic, built by the loop
    "schools": ["Worcester Polytechnic Institute BS Robotics"],
    "prior_companies": ["Apple (Designer)", "Google (Intern)"],
    "founded_before": ["Ledgerline (acquired, acq. by Northwind, 2025)"],
    "years_experience": 8 | null,                  // int (cast from the string or float the schema returns)
    "industry_experience": "…" | null,
    "signals": ["…"]                               // notable_signals, at most 4
  }],
  "leaders_dropped": 0,                            // FindAll matches is_person() rejected (company pages)
  "team_stats": {                                  // the "pro" team-tally Task; null if it failed. Scored as Talent's team part (§6.6)
    "profiles_found": 6 | null,                    // every count is cast float -> int; null = unknown (never 0)
    "team_size_estimate": "approximately 10-20",
    "schools": [{ "name": "University of California, Davis", "count": 1 }],
    "prior_employers": [{ "name": "Amazon", "count": 2 }],
    "sample_names": ["…"]
    // No prior exits: the team is not checked for them (the leaders are, §6.6). A card tallied before 2026-10-07
    // may carry "ex_founders_with_exit": int | null; it still validates (optional), is dropped on store and never scored.
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
  // no "pr_ready": it fed the removed PR step. An older payload that still carries it validates; the flag is
  // excluded from every dump, so it is neither re-stored nor sent to the admin page (like team_stats.ex_founders_with_exit)
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

**Talent consistency (validated by `LaunchRadarScores`, 422 otherwise).** `talent_basis` null ⇒ `talent_leaders` and
`talent_team` null (a **pre-blend** card when `talent` is set: its `talent` is the leaders' raw 0-94 rubric score, and
`radar.py rescore` converts it); `"both"` ⇒ both parts set and `talent = talent_leaders + talent_team`; `"leaders"` /
`"team"` ⇒ that part set, the other null, and `talent = 2 × part`. So the breakdown on a card always adds up. The four
blend keys are optional with defaults, so every payload stored or exported before the blend
still validates and imports unchanged. `data/cards-2026-10-07.json` is the blended re-export
(its cards carry all four keys).

## 5. Frontend

### 5.1 Route, nav and wiring

- `src/frontend/src/config/routes.ts`: `ADMIN_LAUNCH_RADAR: '/admin/launch-radar'` in `ROUTES`, `'Radar'` in
  `NavIconName`, and `{ path: ROUTES.ADMIN_LAUNCH_RADAR, label: 'Launch Radar', icon: 'Radar' }` in `ADMIN_NAV_ITEMS`
  after Custom Companies. `NavigationDrawer.tsx` maps `Radar` to `@mui/icons-material/Radar`.
- `src/frontend/src/app/App.tsx`: the `ROUTES.ADMIN_LAUNCH_RADAR` route wraps `AdminLaunchRadarPage` (eager import) in
  `<AdminRoute>`, next to the other admin routes.
- `src/frontend/vite.config.ts`: a `'/api/admin'` proxy entry to `http://localhost:8000`, the same shape as
  `/api/users`, so plain `npm run dev` reaches the admin routes.

### 5.2 Types (`src/frontend/src/features/admin/launchRadarTypes.ts`)

```ts
export type LaunchRadarStatus = 'new' | 'saved' | 'archived';
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
    investors: string | null; origin: 'monitor' | 'findall_backfill' | 'task brief';
  } | null;
  scores: {
    talent: number | null; vc: number | null; talentReasons: string[]; vcReasons: string[];
    talentLeaders: number | null; talentTeam: number | null;
    talentBasis: 'leaders' | 'team' | 'both' | null;   // null + a talent = pre-blend card (read with `== null`)
    talentTeamReasons: string[];
  };
  leaders: LaunchRadarLeader[];
  leadersDropped: number;
  teamStats: {
    profilesFound: number | null; teamSizeEstimate: string; schools: LaunchRadarTally[];
    priorEmployers: LaunchRadarTally[]; sampleNames: string[];
  } | null;
  funding: { latestRound: LaunchRadarRound | null; priorRounds: LaunchRadarRound[]; totalRaisedUsd: string | null };
  notableFacts: string[];
  careersUrl: string | null;
  ats: { provider: LaunchRadarAtsProvider; boardToken: string | null; boardUrl: string | null;
         verified: boolean; jobCount: number | null; checkedUrl: string | null };
  sources: { url: string; title: string | null; field: string | null }[];
  parallelRunIds: { findallId: string | null; briefRunId: string | null;
                    teamRunId: string | null; pedigreeGroupId: string | null };
  costUsd: number;
  timingsS: Record<string, number>;
  issues: string[];
  generatedAt: string;
  prUrl?: string | null;                     // the open add-company PR (§2.4); absent from an older backend
  prNumber?: number | null;
}
export interface LaunchRadarCardsResponse {   // the backend also sends `stats`; the page does not read it
  cards: LaunchRadarCard[]; total: number; counts: Record<LaunchRadarStatus, number>;
}
export type LaunchRadarSort = 'announced' | 'talent' | 'vc' | 'added';
export interface LaunchRadarCardsArgs { status: LaunchRadarStatus; page: number; rowsPerPage: number; sort: LaunchRadarSort }
```

### 5.3 RTK Query (`src/frontend/src/features/admin/adminApi.ts`)

- `'LaunchRadarCards'` is in `tagTypes`.
- `getLaunchRadarCards: builder.query<LaunchRadarCardsResponse, LaunchRadarCardsArgs>`: `{ url: '/launch-radar/cards', params: { status, limit: rowsPerPage, offset: page * rowsPerPage, sort } }`
  (`sort` is part of the args, so each sort is its own cache entry).
  A `transformResponse` runtime guard in the style of `getAdminCustomCompanies`: `cards` is an array, `total` is a number,
  `counts.new`, `counts.saved` and `counts.archived` are numbers, and each card has `typeof id === 'number'`,
  `typeof domain === 'string'` and a `status` of `new`, `saved` or `archived`; a present `prUrl` must be a string or
  null and a present `prNumber` a number or null, else the response is a "malformed card" error.
  `providesTags: ['LaunchRadarCards']`.
- `setLaunchRadarCardStatus: builder.mutation<LaunchRadarCard, { id: number; status: LaunchRadarStatus; from: LaunchRadarStatus }>`:
  `{ url: `/launch-radar/cards/${id}`, method: 'PATCH', body: { status, from } }`, `invalidatesTags: ['LaunchRadarCards']`.
  `from` is the card's tab when clicked (Save: `new`; Unsave: `saved`; Archive: `new` or `saved`; Restore: `archived`).
- `deleteLaunchRadarCard: builder.mutation<void, { id: number }>`: `{ url: `/launch-radar/cards/${id}`, method: 'DELETE' }`,
  `invalidatesTags: ['LaunchRadarCards']`.
- Both mutations, once the request succeeds (`onQueryStarted` after `queryFulfilled`), remove the card from every cached
  list (`updateQueryData`, `total - 1`) and move the tab counts, so the card leaves its old tab at once and its buttons
  cannot be pressed again (into a 409 or 404) before the refetch lands.
- Hooks: `useGetLaunchRadarCardsQuery`, `useSetLaunchRadarCardStatusMutation` and `useDeleteLaunchRadarCardMutation`.

### 5.4 Components (`src/frontend/src/pages/AdminLaunchRadarPage/`)

| file | role |
|---|---|
| `AdminLaunchRadarPage.tsx` | `Container maxWidth="md"` with `py: RESPONSIVE.spacing.pageMarginY`. `Typography h4` "Launch Radar", with no sub line under it (the last-run / host / budget line was removed 2026-10-07). MUI `Tabs`: **New**, **Saved** and **Archived** (a card is in exactly one), each with a muted count. On the same row, right-aligned (wrapping under the tabs on a narrow screen): "Sort by" and an exclusive small `ToggleButtonGroup` (`aria-label="Sort cards by"`): **Announced** / **Talent** / **VC** / **Added**. The sort lives in the URL (`?sort=talent`; the default `announced` is omitted), applies to every tab and resets to page 1 when it changes. The page holds the tab, page index and `rowsPerPage = 25`, and keeps the last data to avoid a flash, as `AdminFeedbackPage` does. When a card leaves the list (Save, Unsave, Archive, Restore, Delete) focus moves to the next card's toggle, or the tab panel when it was the last, and a polite live region announces it ("Saved Lightfield"). It shows `LoadingState` and `ErrorState`, and the empty states "No new cards." / "No saved cards." / "No archived cards.". It shows MUI `Pagination` when `total > rowsPerPage`. |
| `components/RadarCard.tsx` | An MUI `Accordion` (outlined, `disableGutters`). The summary is a 2-column grid (no logo tile: we never fetch logos): the name plus a `website` link showing `domain` (`target="_blank" rel="noopener noreferrer"`; plain text unless `safeHttpUrl` passes it); then `oneLiner` and the event line (`EventLine`). On the right sit two `ScoreBadge`s (Talent, VC). Below them, across both columns, is `CardStatusLine`. Action buttons and links call `event.stopPropagation()` so they never toggle the accordion. |
| `components/ScoreBadge.tsx` | A 22px tabular numeral, a 30x3px bar filled to `value%`, and a small label. `null` renders a grey "–" with an empty bar (aria-label "No score"), never 0. Sorted by Talent or VC, that score's numeral is full-strength (`text.primary`) and the other's is `text.secondary`; sorted by Announced or Added both look the same. |
| `components/CardStatusLine.tsx` | One line. Left side, New and Saved tabs: `trackedCompanyId` gives the muted text "Already tracked". Otherwise a muted link "Job board" (`jobBoardHref`: the first of `ats.boardUrl`, `careersUrl` that is an `http(s)` URL; omitted if neither is). Archived tab: "Archived {Oct 7}". Then, on **any** tab, when `prHref(card)` is non-null: a middot and a muted link "View PR #N" (`prLabel`; `target="_blank" rel="noopener noreferrer"`, `aria-label="View PR #N {company}"`, its click stops propagation). Nothing else shows the PR: no status chip, no retry button. Right side, New tab: `Save` and `Archive` text buttons. Saved tab: `Unsave` and `Archive`. Archived tab: a `Restore` button and a `Delete` button (error color) that opens the dialog. Every button and link carries the company in its accessible name (`aria-label="Save Lightfield"`, "Job board Lightfield"), so a list of cards never has two controls with the same name. An unknown status renders no actions rather than crashing. |
| `components/CardBody.tsx` | Accordion details, aligned under the name (the header's 14px side padding). **Research incomplete** (only when `issues` holds a research gap, first, warning colour): one bullet per gap, so partial data never reads as "nothing found". A provenance note (`leaders from the brief …`, the payload has no field for it) is not a gap: it is left out of this block and of the "research incomplete" score lines, and the Team section shows it as a muted "Leaders from the company brief" line. **Team**: the leader bullets (bold name, muted title, `summary` line). When `leaders` is empty, the warning text "No leaders confirmed." is followed by "The people search returned company pages." if `leadersDropped > 0`. When leaders exist but none has `summary`, schools or prior companies, it shows the warning "No background data came back for these leaders". **Rest of team** (only when `teamStats`): the right label is "{profilesFound} public profiles" ("profile count unknown" when null); one bullet "Previously at Amazon (2), Twitter, … and N more" (top 6, count shown when >1); one bullet "{k} schools: …" (top 4 and "N more"); a muted "No schools or employers listed" when both lists are empty. Schools and employers only: there is no prior-exit line (the team is not checked for prior exits; the leaders are), and an old card's `exFoundersWithExit` is never shown. **Funding**: the right label is `totalRaisedUsd` + " total"; a bullet per round: "**{stage} {amountUsd}**, {Mon YYYY}. Led by {leads}, with {others}" (first 3 others, then "and N more"). **Highlights**: `notableFacts.slice(0, 3)`. **Why these scores**: a collapsed toggle (MUI `Collapse` or nested Accordion). Its bullets: the Talent line from `format.talentBreakdown`: "Talent 74: leaders 37 + team 37 (each out of 50)" (or
"Talent 38: leaders 19 of 50, doubled: no team data" / "Talent 24: team 12 of 50, doubled: no leader data") with two
sub-bullets "Leaders 37: {talentReasons.join('; ')}" and "Team 37: {talentTeamReasons.join('; ')}" (a missing part shows
its reason, "Leaders: no people data" when there is none); a pre-blend card (`talentBasis` null) keeps the single line
"Talent {n}: {talentReasons.join('; ')}"; "Talent: no people data, so no score" when Talent is null; and "VC {n}: {vcReasons.join('; ')}" or "VC: no funding data, so no score"; when the score is null AND `issues` holds a research gap the line reads "Talent: not scored, research incomplete" (same for VC). **Footer**: left "{Ashby} board, {9} open jobs" (verified), "{Provider} board, not verified" (unverified with a provider), or "No job board found". Right: "${costUsd.toFixed(2)} research". The source link is not repeated here: it is the "Announcement" link on the event line. |
| `components/EventLine.tsx` | funding: "{round ?? 'Funding'} **{amountUsd}**" then the muted date ("Sep 17", or "Sep 2026" for a `YYYY-MM` date). launch: "Launch" then the date. other: the headline, truncated. Then a small muted "Announcement" link to `event.sourceUrl` (`target="_blank" rel="noopener noreferrer"`, hostname as `title`), shown only when the URL is absolute `http(s)` (`safeHttpUrl`), with `aria-label="Announcement {company}"`; its click stops propagation so it never toggles the card. |
| `components/DeleteCardDialog.tsx` | MUI `Dialog`. Title "Delete {company} permanently?". Body "The card and its research go away. The loop will not post {domain} again." `Cancel` and a `Delete` button (contained, error color). It shows an error `Alert` if the mutation fails, and closes on success. |
| `format.ts` | Pure, unit-tested helpers: dates (`formatShortDate`, `formatMonthYear`, `formatEventDate`), money (`formatUsd`, the footer's research cost), the board (`atsLabel`, `boardLine`, `jobBoardHref`), links (`safeHttpUrl`, `hostnameOf`), lists (`joinWithAnd`, `listWithMore`, `summarizeTally`, `roundLine`), research notes (`researchGaps`, `leadersFromBrief`), the sort (`parseSort`, `scoreEmphasis`), `cardToggleId`, and the PR link (`prHref`: `safeHttpUrl(card.prUrl)` only when it is exactly a pull request of this repository, the §9 pattern; `prLabel`: "View PR #N", the number read from that same URL). Every `href` on a card goes through `safeHttpUrl` (the card's URLs are untrusted web data). |

Style: match the existing MUI admin pages (theme typography and colors, `text.secondary` for muted text). No new CSS
files and no new dependencies.

---

## 6. Loop

### 6.1 Module layout (`scripts/launch_radar/`, a package; relative imports only)

| file | content |
|---|---|
| `__init__.py` | empty |
| `radar.py` | argparse CLI and `main()` (§6.2). Runs as `python -m scripts.launch_radar.radar` from the repo root |
| `radar.sh` | `#!/bin/sh` launcher. `cd` to the repo root (its own `../..`). If `${LAUNCH_RADAR_ENV_FILE:-$HOME/.config/jvn-launch-radar/env}` exists, source it with `set -a`. Then `exec uv run --no-project --python '>=3.11' --with 'parallel-web>=1.3.5' --with 'httpx>=0.27' python -m scripts.launch_radar.radar "$@"`, with `uv` found on `PATH`. Mode 755. The secrets exist only in this process tree, never in Claude's environment |
| `config.py` | Reads `BACKEND_URL` (required), `INTERNAL_API_KEY` (required unless `BACKEND_URL` is a loopback URL), `PARALLEL_API_KEY` (required only by billed subcommands; the SDK reads it, our code only checks presence) and `LAUNCH_RADAR_STATE_DIR` (default `~/Library/Application Support/jvn-launch-radar`). A missing variable exits 1 with the variable's **name** only |
| `backend_client.py` | `BackendClient` (httpx, timeout 30s, sends `X-Internal-Key` when set). One method per §2.3 route. `reserve()` raises `BudgetExceeded(reason, run_spend, total_spend, cap)` on 402, and `post_card()` raises `DomainSeen` on 409. A request is retried only if it is a GET (twice, on connection errors); POSTs are never retried |
| `parallel_client.py` | `make_client()`: a lazy `from parallel import Parallel`, then `Parallel().with_options(max_retries=0)`. This is the **only** place that imports `parallel` at runtime (event-type narrowing uses `getattr(ev, "event_type", None)`, not an SDK import) |
| `schemas.py` | `MONITOR_QUERIES` (§6.4), and from the POC: `MONITOR_OUTPUT_SCHEMA` (verbatim), `PEDIGREE_SCHEMA`, `BRIEF_SCHEMA` (**plus** `ats.board_url: string|null` and `founders: [{name, title|null, linkedin_url|null}]`, both required), `TEAM_SCHEMA` (= `team_stats.py` `A_SCHEMA` minus `ex_founders_with_exit`, removed 2026-10-07: the team is not checked for prior exits, the leaders are), `ATS_ENUM` and the price tables (`MONITOR_PRICE`, `TASK_PRICE`, `FINDALL_PRICE`). New: `backfill_event_schema` (§6.3, "Backfill") |
| `domains.py` | `normalize_domain` (§3) and `BIG_TECH` (POC). `is_big_tech(domain)` |
| `monitors.py` | ensure, read events newer than `last_event_id`, accrue scheduled executions, cancel all |
| `leaders.py` | FindAll create/poll/result, `is_person` (§6.5), the brief-founders fallback (`brief_founders`, `BriefLeader`), pedigree Task Group |
| `research.py` | brief Task (core), team-tally Task (pro), and `wait_task` (408 means still running; uses `api_timeout`) |
| `scoring.py` | `VC_TIERS`, `VC_AMOUNT_BONUS`, `TALENT_RUBRIC` and `CONFIDENCE_WEIGHT`, copied verbatim from POC. `score_vc`, `score_talent`, and the Talent blend (`score_team`, `blend_talent`, `talent_scores`, `rescored_scores`) per §6.6 |
| `ats.py` | `check_board`: the POC's `ats_check` minus the fixture writes. Returns the card's `ats` block (`verified`, `job_count`, `checked_url`, `board_url`) and the candidates that failed transiently. Also `board_has_jobs` (verified with at least one job; a transient failure only counts when this is false), `safe_http_url` and `safe_token` |
| `card.py` | `build_payload(...) -> dict` matching §4 exactly, with the float→int casts and `leader.summary` composition |
| `state.py` | local resumable state under `LAUNCH_RADAR_STATE_DIR`: `queue.json` (pending candidates), `companies/<domain>.json` (created Parallel ids and reserved amounts), `backfill.json`, `refresh/<domain>.json`, `refresh_done.json` and `heartbeat.log` |
| `resolve.py` | the domain lookup for events without a website (§6.3, step 3b) |
| `pipeline.py` | `CompanyJob` (one company's research) and the `run` orchestration (§6.3) |
| `backfill.py` | `radar.py backfill` (§6.3, "Backfill") |
| `refresh.py` | `radar.py refresh` (§6.3, "Refresh"): re-research cards that have no leaders |
| `rescore.py` | `radar.py rescore` (§6.3, "Rescore"): recompute stored cards' scores, free |
| `export_cards.py`, `importer.py` | `export_cards.py` writes the local cards to `docs/implementations/launch-radar/data/cards-<date>.json` (`launch-radar-cards/v1`); `radar.py import` posts them (§6.2) |
| `pr_queue.py` | the `radar.py pr-*` commands (§6.2, §6.9): claim, check, report, refresh, requeue, status; the preflight, the scrubbed child env and the run-id clock. `backend_client.py` gains `pr_next`, `pr_get`, `pr_result`, `pr_requeue`, `pr_requests` |
| `pr_step.py` | the PR step's only way to git, gh, the logo scripts and the job-board APIs (§6.9). A standalone program, not imported by `radar.py`: stdlib only, Python 3.8+, mode 755, run by the session as `scripts/launch_radar/pr_step.py …` and by `pr-refresh` as a child |
| `logo_setup.sh` | one-time, by hand: `$STATE_DIR/logo-venv` with the fetch-company-logo requirements (Pillow, cairosvg; needs `brew install cairo`). Not on the allowlist: the nightly run never installs packages |
| `wrapper.sh`, `com.bp.jvn-launch-radar.plist.template`, `install_launch_agent.sh`, `README.md` | §6.8 |

The POC (`scripts/launch_radar_poc/`) stays **untouched** as a read-only reference. Its code is copied into the modules
above with these changes: Ledger → backend reservations, `out/seen.json` → `GET /seen`, enrich → Task Group, fixtures
→ none, `score_talent` → nullable, `is_person` added, and the base FindAll fallback replaced by the brief's founders.
Do not import from `launch_radar_poc`.

### 6.2 CLI (`radar.py`)

```
monitors-ensure                     create any missing active Monitor (one per slot); billed $0.01 each, reserved first
run [--max-companies N=3] [--budget USD=1.00] [--exclude d1,d2] [--deadline-s 540] [--dry-run]
backfill [--days 30] [--limit 20] [--generator base] [--exclude d1,d2] [--deadline-s 540] [--dry-run] [--new]
                                    one-off FindAll sweep of the past month into the queue (§6.3, "Backfill")
monitors-cancel                     cancel every active Monitor, then PATCH status=cancelled; free
heartbeat --status ok|error [--note TEXT]   append one line to $STATE_DIR/heartbeat.log (the skill's final step)
import --file PATH [--dry-run]      POST /cards for each card in an export_cards.py file (launch-radar-cards/v1) under
                                    one backend run; no Parallel call, nothing reserved; 409 = skip; --dry-run: GET /seen only
refresh (--domains d1,d2 | --missing-talent) [--include-archived] [--budget USD=1.00] [--deadline-s 540] [--dry-run]
                                    re-research cards with no leaders (§6.3, "Refresh"); --dry-run: GET /cards only;
                                    archived cards only with --include-archived
rescore (--domains d1,d2 | --all) [--dry-run]
                                    recompute stored cards' scores from what they store (§6.3, "Rescore"); FREE: no
                                    Parallel client, no backend run, nothing reserved; every live status;
                                    --dry-run: GET /cards only
pr-next                             time check, preflight, then POST /pr-requests/next; writes
                                    .launch-radar-pr/claims/<id>.json and clears that card's earlier scout/published/work
                                    files; prints {"claimed": true, …claim, "time_left_s"} or {"claimed": false,
                                    "reason": "empty"|"time"}. Exit 1 on a backend error or a failed preflight
pr-check --card-id N                before publish: row in_progress and card saved -> {"proceed": true}; card unsaved ->
                                    posts cancelled, {"proceed": false, "why": "unsaved"}; 404 -> "why": "deleted"
pr-report --card-id N --outcome open|failed|no_board|already_tracked [--reason R]
                                    POST …/result. open takes NO URL: it reads .launch-radar-pr/published/N.json (card_id
                                    N, dry_run false, a URL matching the §9 pattern) or exits 1 without a call. --reason
                                    is PrReason minus abandoned. A 404 prints {"card_deleted": true} and exits 0
pr-refresh                          preflight, GET /pr-requests?status=open, then `pr_step.py refresh --card-id N` per
                                    request (oldest first, until the 55-min mark), fixed argv and a scrubbed env; one
                                    summary {"open", "refreshed", "failed", "attention", "results", "stopped"}: failed
                                    counts why in error|timeout|bad_output, attention lists the card ids skipped as
                                    pushed_by_someone|slug_taken|now_tracked|no_record. Exit 1 only on a backend error
                                    or a failed preflight
pr-requeue --card-id N              interactive only: POST …/requeue
pr-status [--status S ...]          interactive only: GET /pr-requests as a table
```

Card ids are `^[1-9][0-9]{0,9}$`. The `pr-*` commands print JSON on stdout and log to stderr.

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
3b. **Find missing domains** (in the live validation every Monitor event arrived with `company_domain: null`). For each
   event with no domain (at most 10 a run), reserve `search(domain:<name>)` at $0.005, then call the Search API
   (`mode="advanced"`, Search's default and best-ranked mode, $5 per 1k requests; `max_results=8`, inside the 10 results
   the price includes; not latency-sensitive, so not `fast`) and keep the highest-ranked result whose host carries the company name and is not a
   news, directory or social site (`resolve.py`; Entity Search returns only LinkedIn/Tracxn URLs for companies). A cap
   refusal here stops the run before the cursors move, so the events are read again next run.
4. **Dedupe** before any spend: `normalize_domain`; drop on no domain, `BIG_TECH`, `--exclude`, a domain already in the local
   queue or this run, or a `GET /seen` hit (domain seen, or name tracked). Append the survivors to `queue.json` with the event.
   Then `PATCH /monitors/{slot} last_event_id`, so the events are never read again (the candidates are already persisted locally).
5. **Research the queue.** Resumed companies (those with a state file) always continue. Up to `--max-companies` new ones
   start their first billed call, queued Monitor events before backfill items (stable: queue order within each), because
   only a Monitor event goes stale. A `ThreadPoolExecutor(max_workers=3)` runs one `CompanyJob` per domain:
   1. Reserve, then create, all three at the same time: FindAll (`entity_type="people"`, generator `preview`, `match_limit=8`,
      objective and match condition as in the POC's leadership FindAll, plus the sentence "The candidate must be one person with a personal
      profile, not a company page."), the brief Task (`core`, `BRIEF_SCHEMA`, input `{company_name, company_domain, context: event headline}`),
      and the team-tally Task (`pro`, `TEAM_SCHEMA`; input asks for current employees who are **not** founders, co-founders or
      C-level executives, because the founders' names are not known yet). Save each id to the state file **before** the next create.
   2. Poll FindAll (`retrieve` every 10s until `is_active` is false), then `result`. Keep the candidates that are matched **and**
      pass `is_person`, at most 8. `leaders_dropped` = matched minus kept. **No base fallback and no FindAll enrich.**
      **Brief fallback** (added 2026-10-07): when that keeps **zero** people, wait for the brief (created at t=0) and use its
      `founders` instead: entries without a name dropped, deduped by normalized name, at most 8, `linkedin_url` kept only when it
      is an http(s) LinkedIn URL. They are saved to the state file (a resume reuses them) and the pedigree runs on them as usual.
      The leader model has no `source` field, so the card says so in `issues`: `leaders from the brief (FindAll found none)`.
   3. Pedigree, when there is at least one leader: reserve `len × TASK_PRICE['base']`, then one Task Group (`task_group.create`,
      `add_runs` with `default_task_spec = PEDIGREE_SCHEMA` and inputs `{person_name, current_title, linkedin_url, company_name, company_domain}`,
      processor `base`, `metadata={"row_id": str(i)}`). `add_runs` bills and is not idempotent, so each attempt is recorded
      before the call; after an ambiguous failure the group is asked first (`retrieve` → `num_task_runs`): runs present =
      marked added, none = reserve `task_group(pedigree)#retryN` and add again. Poll the group status every 10s, then `get_runs(include_input=True, include_output=True)`.
      Join on `run.metadata["row_id"]`, never on stream order. Confidence for each field comes from `basis[].field.split('.')[0]`.
   4. Wait for the brief and the team tally (`wait_task`). On failure, set the output to None and add a string to `issues`.
   5. `check_board(brief.ats.provider, brief.ats.board_token, brief.careers_url, brief.ats.board_url)` against the free
      public APIs. If the brief gave a `board_url`, that is the board URL; otherwise use the public board URL for a verified
      token. A transient failure (HTTP 429/5xx, a dropped connection) here or while collecting a paid result keeps the
      company queued (exit 3); after `MAX_RETRIES` (6) such invocations the card posts with the gap in `issues`.
   6. Score (§6.6), `build_payload`, `POST /cards`. A 409 `DomainSeen` is logged as a skip, not an error. Remove the company from
      the queue and its state file.
   - On a 402 `BudgetExceeded`: stop starting new work. The in-flight companies keep their ids and resume next time. The run
     ends `stopped` and exits 2.
   - **Deadline**: every poll loop checks `--deadline-s` (default 540, under the Bash tool's 600s cap). Past it, save the state,
     stop, finish the run `stopped`, and exit 3. The next `run` resumes from the saved ids and **never re-creates or
     re-reserves** a saved step.
   - A queue item older than 3 days with no progress is dropped and logged, except a `backfill` sweep item (slot
     `backfill`), which waits however long the queue takes.
6. `POST /runs/{uuid}/finish` (`ok` when the queue is empty, otherwise `stopped`, or `error` on an exception) and print one
   summary line per company.

Estimates use the POC's `ceil_cost` (round up to $0.001). A full company costs $0.10 + $0.025 + $0.10 + $0.01 × leaders
(at most 8), so $0.225 to $0.305.

**Refresh (`radar.py refresh`, `refresh.py`; added 2026-10-07).** Applies the brief fallback to cards posted before it
existed. `GET /cards` selects the cards (`--domains`, or `--missing-talent` = every card with no leaders' part of Talent),
new and saved only unless `--include-archived`, paged through to the end (`after_id`) so no cap hides a card;
a card that already has leaders is skipped (its leaders' part cannot be recomputed from the stored card), and so is one in
`$STATE_DIR/refresh_done.json`. One backend run, then for each card: reserve and create a new brief (`core`, with `founders`),
all up front so they research in parallel; then, per card, wait for it, reserve and run the pedigree Task Group on its
founders, rescore deterministically (the kept team tally is scored as Talent's team part) and `PUT /cards/{id}/payload`.
Kept: event, team tally, ATS block, FindAll id,
`leaders_dropped`. Replaced: the brief's fields, leaders, scores, sources and the brief/leader/pedigree issues; `cost_usd` and
`timings_s` add the refresh's own. A failed brief leaves the card unchanged. State lives in `refresh/<domain>.json`
(saved ids and reservations, never re-created or re-reserved; always resumed first); a 402 stops new work (exit 2), the
deadline exits 3. `--dry-run` reads `GET /cards` and prints the cards and the estimate ($0.025 + $0.01 per founder each).

**Rescore (`radar.py rescore`, `rescore.py`; added 2026-10-07).** Free: recomputes the scores of existing cards from
what each card stores, with no Parallel client, no backend run and no reservation. `GET /cards` (`--domains`, or
`all=true` for `--all`), every live status, paged by `after_id`. Per card (`scoring.rescored_scores`): the **leaders'
part is carried**, not recomputed, because the card does not keep the pedigree confidence the rubric weighs by
(`talent_leaders` on a blended card; a pre-blend card's raw `talent` rescaled, `half_up(talent × 50 / 94)`, which is
exact); the team part is scored from `team_stats`; VC is recomputed from the stored `funding`. The event date is
normalized (`card.announced_on`), and `PUT /cards/{id}/payload` runs only when `scores` changed, so a second run is a
no-op. A 404 is counted as gone; any other backend error is counted and exits 1 after the summary
`rescore: changed N, unchanged M, gone G, errors E`. `--dry-run` prints the same per-card lines and writes nothing.

**Backfill (one-off, `radar.py backfill`, `backfill.py`; added 2026-10-07).** Monitors see only events after they are
created, so the past month is swept once and fed into steps 3b-4 above; the next `run` researches it in step 5. It opens
and finishes its own backend run (`budget_usd` = the most it can reserve). (a) Reserve `findall.create(backfill)` =
`0.25 + 0.03 × --limit` (generator `base`), then one FindAll run: `entity_type="companies"`, conditions
`early_stage_startup_check` (independent private startup, not big tech or public) and `recent_announcement_check`
(a newly closed pre-seed to Series B round or a notable launch, dated inside the window; both dates are written into
the text), `match_limit = --limit`. Save the `findall_id` before anything else. (b) Poll until inactive; reserve
`findall.enrich(backfill)` = `0.01 × matches`, then `enrich(processor="base")` with a flat, all-required,
`additionalProperties: false` schema of the nine `MONITOR_OUTPUT_SCHEMA` fields (nullable where unknown). (c) Each
enriched match becomes a Monitor-shaped event with `origin: "findall_backfill"` (numbers cast to text; rows dated
outside the window dropped), then 3b (domain lookup) and 4 (dedupe, append to `queue.json`). Reservations above $1 are
split into $1 rows. `backfill.json` holds the id, the reservations and the progress, so a re-run after a crash, a 402
or the deadline resumes polling and never creates or enriches twice; a finished backfill is not re-run without `--new`.
`--dry-run` prints both requests and the estimate and makes no call at all.

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

- **VC**: the points are exactly the POC's `score_vc`: tier lead/participant points, extra-investor points and the amount
  bonus (> $10M / $20M / $50M). Prior rounds' `investors` count as participants. It returns **None** when the brief is missing or
  there are no named investors and no parseable amount. The reasons are human readable: `"{Name} led (tier 1)"`,
  `"{Name} joined (tier 2)"`, `"Y Combinator joined"`, `"+{n} more tier-1 investors"`, `"named investors, none tiered"`,
  `"round over $20M"`.
- **Talent** is a **50/50 blend** (`talent_scores`; `half_up(x) = floor(x + 0.5)` everywhere, never banker's `round`):
  up to 50 points from the leaders plus up to 50 from the rest of the team.
  - **Blend** (`blend_talent`): both parts → `talent = leaders + team`, `talent_basis = "both"`; one part → that part
    doubled, basis `"leaders"` / `"team"` (missing data is not evidence of a weak team, so it is never scored as 0);
    neither → `talent = null`, basis null.
  - **Leaders part, 0-50** = `half_up(leaders_raw × 50 / LEADERS_MAX)`, `LEADERS_MAX` = the sum of the rubric caps (94),
    where `leaders_raw` is `score_talent` below (null stays null). Reasons: `talent_reasons`.
  - **Team part, 0-50** (`score_team(team_stats, leaders)`), with `n = profiles_found`. The tally lists schools and
    employers, **not people** (one person can list two schools), so on each side `listed` = the summed counts of its
    entries and `hits` = the summed counts of the entries matching the top-school (or top-employer) names, and the share
    is `hits / max(n, listed)`: double counting cannot inflate it, and profiles with nothing listed still count when the
    list is short. Components: `half_up(25 × s × min(1, share / 0.5))` for schools and `half_up(25 × s × min(1, share /
    0.5))` for employers (shares, full points at one half). **No exits component**: prior exits are a leaders' signal
    (the rubric below), so the team tally does not ask for them, and an older card's `ex_founders_with_exit` is ignored
    (revised 2026-10-07; it was 15 + 20 + exits 0/10/15). Each component is **rounded once** and the part is the **sum
    of the shown integers**, so the reason lines add up. `s` is 1 when both sides list something; a side with nothing
    listed is **missing, not 0**: `s = 50 / 25 = 2`, so the other side is scaled up to 50. **Small samples**: with `n < 5` the summed
    part counts `n / 5` and the rest **follows the leaders' part** `L`: `half_up(n/5 × raw + (1 − n/5) × L)`, so as `n`
    goes to 0 the card tends to the leaders-only card (2L), never to L + 0; with no leaders' part the rest is 0 (stated).
    Weight 1.0: the pipeline does not keep the tally's confidence. **Null** with no tally, `n` null or 0, or neither side
    listing anything. Reasons (`talent_team_reasons`):
    `"15 of the 48 schools listed across 33 profiles are top schools (+16)"`, `"none of the 7 schools listed across 24
    profiles is a top school"`, `"no school data listed: employers are scaled to 50"`,
    `"only 3 profiles found: counts at 60%, the other 40% follows the leaders' part (13)"` (`"…counts at 60%"` with no
    leaders' part), or for a null part `"no public profiles found for the rest of the team"` /
    `"the team tally lists no schools or employers"` / `"no team tally on this card"`.
  - **Rounding note**: a lone part is rounded before it is doubled, so a leaders-only card can sit 1 above the direct
    rescale (raw 48: `2 × half_up(48 × 50/94)` = 52 vs 51.06). Accepted: it keeps the validated `talent == 2 × part`.
- **Leader rubric** (`score_talent`, the leaders part's raw score): the points are exactly the POC's `score_talent`: top school 8 (cap 24), top employer 10 (cap 30), **prior exit**
  15 (cap 30, and only `outcome in {acquired, ipo}`; founding without an exit scores 0), 10+ years 5 (cap 10). Each signal is
  multiplied by `CONFIDENCE_WEIGHT` (high 1.0, **medium 0.8**, low 0.5, missing 0.8). It returns **None** when no leader has any of
  schools, prior companies, structured founded-before entries or years. Reasons look like `"{name}: top school (Berkeley)"`,
  `"{name}: prior exit (Ledgerline, acquired by Northwind)"` and `"{name}: 10+ years"`, plus `"medium-confidence facts count at 80%"`
  when any weight was below 1.
- `rescored_scores(payload)` is the same computation on a stored card, for `rescore` (§6.3): the leaders' part is
  carried, the team part (which reads the carried leaders' part when `n < 5`) and VC are recomputed from the card's
  `team_stats` and `funding`. A card with an AI grade keeps it (§6.6.1).

#### 6.6.1 AI Talent grade (`grade.py`, skill `launch-radar-grade`)

The rule blend above counts a fixed list of names, so it misses industry fit (Boeing and
Embry-Riddle for an aircraft company) and team density relative to size. After a run posts its
cards, the nightly skill has **one Claude subagent per card** grade Talent against
`.claude/skills/launch-radar-grade/rubric.md` (`v1`): leaders 0-40, industry fit 0-25, team
density for its size 0-25, track record 0-10, summed to 0-100, with a confidence and 1-6 reasons.
Graders read only the rubric and the card's input file (no web); the card text is untrusted.

- `radar.sh grade-export (--ungraded | --all | --domains) --dir D` writes `D/inputs/<id>.json`
  (company, what it does, stage, leaders' histories, the team tally; no URLs, no team names).
  `--ungraded` = new and saved cards with no grade under the current `RUBRIC_VERSION`.
- Each grader's JSON reply goes to `D/grades/<id>.json`. `radar.sh grade-apply --dir D [--dry-run]`
  validates it (`parse_grade`: the four parts in range, `score` = their sum, 1-6 reasons of at most
  300 chars) and PUTs the card: `scores.talent` = the grade, `scores.talent_ai` = the grade's
  parts/confidence/industry/reasons/`rubric_version`/`graded_at`, `scores.talent_rules` = the rule
  blend's Talent (its parts and reasons stay). Missing or invalid grade: the card keeps its rule
  score and is picked up again the next night.
- The backend validates the same bounds (`LaunchRadarTalentAi`): with a grade, `talent` must equal
  its score and the rule breakdown must add up to `talent_rules`; without one both fields are
  absent from the stored payload and the API (an ungraded card is byte-for-byte unchanged).
- `rescore` keeps a grade (`with_ai_grade` over the recomputed rules); `refresh` (new leaders)
  drops it. Changing the rubric means bumping `v1` in both `rubric.md` and `RUBRIC_VERSION`, after
  which every card re-grades.

### 6.7 Skill and slash command

- `.claude/skills/launch-radar/SKILL.md` has four parts after its hard rules:
  - **§0 Hard rules**: **never merge**; PRs only through `pr_step.py` and `radar.sh pr-*`, for Saved cards; no `git` or `gh`
    entry; the only file writes are the graders' replies (`.launch-radar-grades/grades/`) and the scout's replies
    (`.launch-radar-pr/scout/`); never print secrets; never `Read` `~/.config/jvn-launch-radar/`; Bash only through the
    allowlist (quoted verbatim, §6.8); never call WebSearch or WebFetch from the main session (only the scout does); never
    put web text on a command line; no `--dangerously-skip-permissions`.
  - **§1 Run**: `scripts/launch_radar/radar.sh monitors-ensure`, then `radar.sh run --max-companies 3 --budget 1.00` with Bash
    timeout 600000. Re-run while the exit code is 3, at most 4 invocations. Exit 2 means the budget is spent, so log it and continue
    to §2.
  - **§2 Grade** (§6.6.1): `grade-export`, one grader subagent per card, `grade-apply`.
  - **§3 Add-company PRs for Saved cards** (§6.9): `radar.sh pr-refresh` once, then repeat `pr-next` → scout → `pr_step.py
    worktree` → `verify-board` → `compose` → logos (unless `skip_optional`) → `check-head` → `radar.sh pr-check` →
    `pr_step.py publish` → `radar.sh pr-report --outcome open` → `pr_step.py cleanup`, until `pr-next` says stop. Any
    `pr_step.py` exit 1 is reported as `failed` with the `report_reason` it printed; exit 3 is reported as what it printed.
  - **§4 Heartbeat**: `radar.sh heartbeat --status ok|error --note …` is the **final** step. The note ends with
    `PRs: <opened> opened, <refreshed> refreshed, <refresh_failed> refresh failed, <no_board> no board, <failed> failed`,
    plus `; rebase by hand: cards …` for refresh `attention` ids. A failed PR is not an error; a `radar.sh` exit 1 or a
    refresh `failed` above 0 is.
- `.claude/commands/launch-radar-once.md`: a headless one-shot that mirrors `.claude/commands/health-watch-once.md`. Read the skill
  file relative to the checkout (do not use the Skill tool), no `ScheduleWakeup` or `/loop`, no background Bash, no sleep loops,
  subagents only for the graders (up to 6 at a time) and one scout at a time, all in the foreground, the heartbeat last,
  then end the turn.
- `.claude/agents/launch-radar-scout.md`: `tools: WebSearch, WebFetch` only (no Bash, no Read, no Write). For one claim it
  replies with one `launch-radar-scout/v1` JSON object: up to 5 board candidates (greenhouse, ashby, lever, gem), symbol
  and wordmark logo URLs, a summary and a milestone. The session saves the reply verbatim to `.launch-radar-pr/scout/<id>.json`.

### 6.8 launchd (test on this laptop, install on the always-on server laptop)

- `scripts/launch_radar/wrapper.sh`: a copy of `scripts/health_watch/wrapper.sh` (lock, process-group watchdog,
  `TOTAL_TIMEOUT_SECS=5400`, and a heartbeat mtime check, where exit 0 without a heartbeat becomes 97). Differences:
  - `CLAUDE_BIN` and `PROJECT_DIR` come **from the environment the plist sets** (required, with no hard-coded user path).
  - `STATE_DIR="$HOME/Library/Application Support/jvn-launch-radar"`.
  - No texting.
  - The wrapper does **not** source or export any secret (`radar.sh` does that itself).
  - The command passes `--permission-mode dontAsk --setting-sources project` (the host's user and local
    settings cannot widen the list) and the `--allowedTools` / `--disallowedTools` lists of the `ALLOWED_TOOLS` block.

  **Never `--dangerously-skip-permissions`.** The exact list lives in one place, a `ALLOWED_TOOLS` block in `wrapper.sh`, and
  `SKILL.md` §0 quotes it verbatim. A unit test (`test_launch_radar_wrapper.py`) fails if the skip flag appears, if the
  two copies differ, or if the allowed list is anything but exactly:
  - `Read(./**)`;
  - `Edit(./.launch-radar-grades/grades/**)` and `Edit(./.launch-radar-pr/scout/**)` (no `Write(`, nothing under
    `.claude/worktrees`);
  - `Agent(launch-radar-grader)` and `Agent(launch-radar-scout)` (never a bare `Agent`), plus `WebSearch` and `WebFetch`,
    which are allowed only together with the scout, whose own tools are exactly `WebSearch, WebFetch`;
  - the `radar.sh` Bash entries: `monitors-ensure`, the two `run` lines, the `grade-export` and `grade-apply` lines,
    `pr-next` and `pr-refresh` (exact, no arguments), and the prefixes `pr-check:*`, `pr-report:*`, `heartbeat:*`;
  - `Bash(scripts/launch_radar/pr_step.py:*)`.

  There is no generic `git`, `gh`, `curl`, `python`, `pip` or `npm` entry, since each of those can run code or upload a
  local file (`curl -T ~/.ssh/...`). When the skill records `status=error`, the wrapper exits 98 so the failure reaches the
  `.err` log.
- The PR step's clock (§6.9): the wrapper makes a run id (`<start_epoch>-<pid>`), writes `<start_epoch> <run_id>` to
  `$STATE_DIR/session_started_at` and starts the session as `env LAUNCH_RADAR_RUN_ID="$RUN_ID" "$CLAUDE_BIN" …` (not a
  secret). Its EXIT trap deletes the file. A killed session, a non-zero session exit, or a zero exit without a new
  heartbeat appends `<iso-ts> status=error wrapper: session exit <N>` (or `… without a heartbeat`) to `heartbeat.log`.
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

### 6.9 The PR step (`pr_queue.py`, `pr_step.py`; design `saved-pr/PLAN.md` §4)

One add-company PR per Saved card, opened by the nightly run after grading (§6.7 §3). It never merges.

- **Files** (repo root, gitignored `.launch-radar-pr/`): `claims/<id>.json` (`pr-next`), `scout/<id>.json` (the session:
  the scout's reply verbatim, the only directory it may write), `work/<id>/board.json` (`verify-board`; kept for
  `refresh`), `work/<id>/{raw,masters,lease,gh_login}` (scratch, removed by `cleanup`), `published/<id>.json`
  (`publish`, adoption, `refresh`). The worktree is `.claude/worktrees/radar-<id>/`.
- **Branch** `radar/card-<id>`, from the card id alone, so a retry always looks at the same branch.
- **`pr_step.py` commands** (each prints one JSON line; exit 0 done, 3 "stop for this card, report what it printed",
  1 `{"error", "report_reason"}`): `worktree`, `verify-board`, `compose`, `logo-fetch`, `logo-normalize`, `logo-tile`,
  `check-head`, `publish [--draft] [--dry-run]`, `cleanup`, and `refresh` (run only by `radar.sh pr-refresh`). The session
  passes only `--card-id` plus, for logos, argparse choices and a `#RRGGBB`; every other value comes from `claims/`,
  `scout/` and `board.json`. `report_reason` is `env_error` for a git/gh failure before any push, `git_error` / `gh_error`
  after, `step_refused` for a guard.
- **Trust check** (`trusted_prs`): `gh pr list --head radar/card-<id> --state all`; a PR counts only when
  `isCrossRepository` is false, the head owner is `brendanpotter00`, the author is the gh login, and the body has the line
  `Launch-Radar-Card: <id>`. `worktree`: an open trusted PR is adopted (exit 3 `existing_pr`, reported `open`); a merged one
  → `already_tracked`; one closed after the request's `requested_at` → `pr_closed`. Untrusted PRs are ignored in every state.
- **`verify-board`**: candidates are the card's own `ats`, ATS URLs in its `board_url` / `careers_url`, then the scout's
  boards (≤ 5). Each is checked on a fixed API host (`boards-api.greenhouse.io`, `api.ashbyhq.com`, `api.lever.co`,
  `api.gem.com`), token path-quoted; the first with ≥ 1 job wins. Tracked = an exact `(ats, token)` pair (token lower-cased)
  among `companies.ts` board URLs and the seed migrations' `{'ats', 'board_token'}` literals. The display name is the card's
  `company`, ASCII-folded; the slug is the first free of: the name, the domain with `.` → `-`, `<slug>-<id>`. Exit 3
  `{"no_board": R}`, `{"already_tracked": true}` or `{"failed": "unsafe_value"}`.
- **`compose`**: the worktree's add-company `scaffold_migration.py` (only after `assert_pinned` proves the scaffold scripts
  equal `origin/main`), then templated entries in `companies.ts` (`createBackendScraperCompany` + the `COMPANY_IDS` member),
  `changelog.ts` (`id: 'add-<slug>'`) and `company_profiles.json`. Without a valid scout file the changelog uses the card's
  `one_liner` and the profile entry is skipped.
- **`publish`**: title `feat(companies): add <Name> (<ATS>)`, templated body ending `Launch-Radar-Card: <id>`, label
  `launch-radar`; a draft when the icon or wordmark is missing. Push `git push --no-verify
  --force-with-lease=refs/heads/radar/card-<id>:<lease> origin HEAD:refs/heads/radar/card-<id>` (the lease is the remote sha
  `worktree` recorded; empty = must not exist), then `gh pr create`. Writes `published/<id>.json` `{card_id, dry_run: false,
  pr_url, pr_number, commit, slug, draft}`. `--dry-run` commits locally and stops (no push, no `gh`).
- **`refresh`** (D14): rebuilds an open trusted PR whose branch is behind `main`, unless the branch head is not the recorded
  commit (someone else pushed). Skips with `why`: `no_record`, `not_open`, `pushed_by_someone`, `up_to_date`, `now_tracked`,
  `slug_taken`. A rebuild re-runs `compose` on the new head (the migration is re-chained), copies the logo PNGs from the
  recorded commit, and pushes leased on that commit.
- **Guards kept from the first version**: fixed argv, never a shell; every git call with `core.hooksPath=/dev/null`,
  `core.fsmonitor=false`, `core.pager=cat`, `GIT_*` stripped, `GIT_TERMINAL_PROMPT=0`; the `.git` pointer check before any
  worktree is touched; logo scripts from this checkout with `-I` and the logo venv; the staged-file allowlist
  (`staged_problems`: mode 100644, no renames, only `companies.ts`, `changelog.ts`, `company_profiles.json`, one
  `*_seed_<slug>_company.py` and logo PNGs). No `merge`, `--auto`, `--admin` or bare `--force` anywhere (a test bans them).
- **Logo fetch**: https only, ≤ 5 MB, image types; each hop is resolved, refused unless every address `is_global`, and the
  socket connects to the checked IP with TLS SNI on the host name (no DNS rebinding).
- **`parse_scout`** (`launch-radar-scout/v1`) refuses the whole file on any violation: `card_id` equals the claim; ≤ 5
  boards of a supported ATS with a safe token and an https evidence URL; logo URLs https or null, ≤ 500 chars, query ≤ 200;
  `summary` / `milestone` 20-240 printable chars without `` ` `` `$` `\` `<` `>` `{` `}` and nothing secret-shaped (`sk-`,
  `ghp_`, `gho_`, `ghs_`, `github_pat_`, `xox`, `AKIA`, `postgres://`, `postgresql://`, `-----BEGIN`, a 32+ run of
  key characters); unknown keys refused.
- **Preflight** (`pr-next`, `pr-refresh`), fixed argv: `gh auth status`; `gh api repos/brendanpotter00/Job-Visualizer-Notifier
  --jq .permissions.push` prints `true`; `git ls-remote --exit-code origin refs/heads/main`; the logo venv imports PIL and
  cairosvg. A failure prints `{"preflight": "failed", "check": "<name>"}` on stderr, claims nothing, exits 1.
- **Scrubbed env**: children of `pr_queue.py` get only `PATH`, `HOME`, `LANG`, `LAUNCH_RADAR_STATE_DIR`,
  `LAUNCH_RADAR_RUN_ID` (no backend URL, internal key or Parallel key).
- **Clock** (§6.8): only when `LAUNCH_RADAR_RUN_ID` is set and equals the run id in `session_started_at`. After **3300 s**
  (55 min) `pr-next` claims nothing (`"reason": "time"`) and `pr-refresh` starts no refresh. Every `pr_step.py` output
  carries `time_left_s` (to the 5400 s kill) and `skip_optional: true` under 900 s (skip logos; publish a draft). There is
  no other per-night cap; the rest stay queued.
- **Residual exfiltration channels (accepted, documented in the README and SKILL §0)**: the web tools are allowed
  session-wide, so the main session could call WebFetch and can Read the checkout; it writes the scout file, so up to 240
  chars could reach a public PR through `summary` / `milestone`; the logo URLs in that file are fetched by `pr_step.py`.
  The cuts: secrets denied and absent from the env, the skill forbids main-session web calls, `parse_scout` refuses
  secret-shaped text and caps the URLs.

---

## 7. Local-only admin auth bypass

### 7.1 Backend

- **Env var:** `DEV_AUTH_BYPASS_EMAIL=<admin email>` → `settings.dev_auth_bypass_email`.
- **Module `src/backend/api/auth/dev_bypass.py`:**
  - `RAILWAY_MARKERS = ("RAILWAY_ENVIRONMENT", "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_PROJECT_ID", "RAILWAY_SERVICE_ID", "RAILWAY_DEPLOYMENT_ID")`.
  - `def running_on_railway() -> bool`: returns true if any marker is a non-empty value in `os.environ`.
  - `def enforce_dev_auth_bypass_guard() -> None`: if the var is set and `running_on_railway()`, **raise `RuntimeError`** (the
    message names the variable and the marker, never the email). It also raises when `non_local_database_reason(settings.database_url)`
    is not None: every host libpq would read from `DATABASE_URL` (the URL authority plus any `?host=` / `?hostaddr=`, parsed with
    `psycopg2.extensions.parse_dsn`) must be `localhost`, a loopback IP or the docker-compose service `postgres`; an unparseable or
    host-less URL refuses. The message names the host, never the URL (it carries the password). This keeps a laptop backend pointed
    at the production database from acting as the real admin there (`get_or_create_user` would rewrite the admin's `users` row). If the var is set and we are local, log a loud
    `logger.warning` banner: "DEV_AUTH_BYPASS_EMAIL is ON: unauthenticated loopback requests are treated as <email>. Never set this outside local development."
  - `def dev_bypass_claims(request: Request) -> TokenClaims | None`: returns
    `{"sub": f"dev-bypass|{email}", "email": email, "given_name": None, "family_name": None, "picture": None}` **only if** all of
    these hold:
    1. the setting is set;
    2. `not running_on_railway()`, re-checked on every request;
    3. the request has **no `Authorization` header at all** (check the raw header, because `HTTPBearer(auto_error=False)` also
       yields None for a malformed one);
    4. `request.client` is present and `ipaddress.ip_address(request.client.host).is_loopback`. A `ValueError` (for example
       `"testclient"`) means not loopback;
    5. the `Host` header names this machine (`localhost`, `127.0.0.1`, `[::1]`), which keeps a DNS-rebinding page out.

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
  - rejected for a non-loopback client (`10.0.0.5`, `"testclient"`) and for a non-local `Host` header;
  - a real `Authorization: Bearer x` still goes to `validate_token` (patch it) and an invalid token still returns 401;
  - an `Authorization: Basic …` header disables the bypass;
  - `enforce_dev_auth_bypass_guard` raises with each Railway marker set (monkeypatch env) and does not raise without the var;
  - it also raises for a remote `DATABASE_URL` (including a `?host=` override of a `localhost` authority), and the lifespan then
    never reaches migrations or the pool;
  - `require_admin` with bypass claims gives 403 when the email is not in `admins` and 200 when it is.

### 7.2 Frontend

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

### 7.3 Docs

`.claude/skills/run/SKILL.md` § Local admin bypass (after Mode 2) covers:
- both flags, with `DEV_AUTH_BYPASS_EMAIL=brendanpotter00@gmail.com` on the uvicorn command and `VITE_DEV_AUTH_BYPASS=1 npm run dev -w src/frontend`;
- that it works with plain Vite (the `/api/admin` and `/api/users` proxies go to :8000) and with `vercel dev` (the proxies forward
  no `Authorization` when none is sent);
- the one-time local admin grant, done after the first `/api/users` load creates the user row:
  `docker exec jobscraper-postgres psql -U postgres -d jobscraper -c "INSERT INTO admins (user_id) SELECT id FROM users WHERE email='brendanpotter00@gmail.com' ON CONFLICT DO NOTHING"`;
- the guarantees: the backend refuses to start if a Railway marker is present, the bypass is honoured only for loopback clients
  without an `Authorization` header, the Vite flag is compiled out of production builds, and the Vercel proxy is unchanged.

---

## 8. Checks

Backend tests need Postgres (`docker compose up -d postgres`) and build their own per-worker schema; point
`TEST_DATABASE_URL` and `DATABASE_URL` at a throwaway database.

**Backend** (from `src/backend`, with its `.venv`)
```bash
mypy                                                         # must be clean (CI gate)
pytest api/tests/test_launch_radar_service.py api/tests/test_launch_radar_admin.py \
       api/tests/test_internal_launch_radar.py api/tests/test_migration_launch_radar_tables.py \
       api/tests/test_dev_auth_bypass.py api/tests/test_auth.py api/tests/test_db_models.py \
       api/tests/test_proxy_path_allowlists.py api/tests/test_alembic_single_head.py \
       api/tests/test_migration_launch_radar_pr_requests.py
cd ../.. && alembic heads                                    # exactly one head
```

**Frontend** (from the repo root)
```bash
npm run type-check && npm run lint && npm test -w src/frontend -- --run
npm run build      # the dev bypass compiles out: grep dist for VITE_DEV_AUTH_BYPASS finds nothing
```

**Loop**
```bash
cd scripts && ../src/backend/.venv/bin/python -m pytest tests/unit -k launch_radar   # SDK faked; no network
uv run --with ruff ruff check --select F,E9,I scripts/launch_radar scripts/tests/unit/test_launch_radar_*.py scripts/tests/unit/launch_radar_fakes.py
sh -n scripts/launch_radar/wrapper.sh && sh -n scripts/launch_radar/radar.sh && sh -n scripts/launch_radar/install_launch_agent.sh
sh -n scripts/launch_radar/logo_setup.sh
plutil -lint scripts/launch_radar/com.bp.jvn-launch-radar.plist.template
```

`mypy` covers only `src/backend/api`; ruff is not a CI gate (there is no ruff config).

---

## 9. Seams (the parts that must agree)

| seam | producer → consumer | pinned in |
|---|---|---|
| admin JSON (camelCase) | backend → frontend | §2.1, §2.4, §5.2 |
| proxy allowlist entries | backend (`api/admin.ts`) → frontend fetch paths | §2.2, §5.3 |
| internal JSON (snake_case) and status codes 402/409 | backend ↔ loop | §2.3 |
| card payload | loop → backend (validated, stored) → frontend (camelCase) | §4, §2.4, §5.2 |
| `normalize_domain` vectors | backend and loop | §3 |
| bypass: no `Authorization` header, a loopback client and a local `Host` | frontend → backend | §7 |
| PR request JSON (snake_case), `PrReason` codes, 204 on an empty queue, 404 = card deleted | backend ↔ loop (`pr_queue.py`, `pr_step.py`'s `report_reason`) | §2.3, §6.2, §6.9 |
| **PR URL pattern** `^https://github\.com/brendanpotter00/Job-Visualizer-Notifier/pull/[0-9]+$`, always a full match | DB CHECK `ck_launch_radar_pr_requests_pr_url` ↔ `models.py` `LAUNCH_RADAR_PR_URL_PATTERN` ↔ `pr_queue.py` `PR_URL_PATTERN` (`radar.py pr-report`) ↔ `pr_step.py` `PR_URL_RE` ↔ `format.ts` `PR_URL_RE` (`prHref`, `prLabel`) | §1.7, §2.3, §5.4; `test_db_models.py`, `test_internal_launch_radar.py` (CHECK ↔ model), `test_launch_radar_pr_queue.py` (model ↔ loop ↔ page) |
| `prUrl` / `prNumber` on the admin card | backend (open request only) → frontend (link) | §2.4, §5.2, §5.4 |
