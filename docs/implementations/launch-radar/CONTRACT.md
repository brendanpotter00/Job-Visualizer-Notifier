# Launch Radar — implementation contract

The contract between the three parts of Launch Radar as shipped: the **backend** (tables, routes, status codes), the
**frontend** (`/admin/launch-radar`) and the **loop** (`scripts/launch_radar/`). Where this file and `plan.html` (the
approved design) disagree, this file wins. §9 lists the seams that must change together.

**Removed: the add-company PR step** (2026-10-07). The design's last stage, where the loop turned one verified card a
day into an add-company pull request, is gone: it opened PRs (#333, #334) on its own, and tracking a company is a human
call made from the admin page. The loop now only researches and posts cards. What is left of it: the legacy
`launch_radar_cards.pr_url` column (§1.4, unused, kept so the removal needed no migration) and the tolerated legacy
payload flag `pr_ready` (§4).

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
| `pr_url` | Text | yes | | **legacy, unused**: written by the removed add-company PR step. Nothing reads or writes it now except the tombstone, which still clears it (the CHECK below). Kept so the removal needed no migration |
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

### 1.6 Migrations

- One revision, `33ff7e590a46` (`launch radar tables`, after `904d5bc44e4b`), creates the four tables with every CHECK
  (the card status CHECK already includes `'saved'`), UNIQUE and index; its downgrade drops them. It was autogenerated
  from `db_models.py` against a scratch database at `904d5bc44e4b` (`create_all` of every other table, then
  `alembic stamp 904d5bc44e4b`); `alembic check` is clean after it. Its only foreign keys are `launch_radar_cards.run_id`
  and `launch_radar_spend.run_id` → `launch_radar_runs.id`; `tracked_company_id` has none (soft link).
- Autogenerate does not compare the CHECKs of an existing table, so `api/tests/test_db_models.py` pins the model's card
  status CHECK to the same text in the revision, and `api/tests/test_migration_launch_radar_tables.py` round-trips it
  (upgrade, constraints, downgrade, upgrade again) in a throwaway database.
- Never add files under `scripts/shared/migrations/`.

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

#### `DELETE /api/admin/launch-radar/cards/{card_id}`

Permanent delete (the tombstone in §1.5).
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

### 2.4 `LaunchRadarCard`: admin response model (camelCase)

`models.py` defines one set of nested Pydantic models used **both** to validate the loop's snake_case POST body (by
field name) and to serialize the admin response (by camelCase alias). The admin card is built from the row columns
plus the parsed payload:

```python
LaunchRadarCardOut.model_validate({**row["payload"], "id": row["id"], "status": row["status"],
                                   "tracked_company_id": row["tracked_company_id"],
                                   "posted_at": row["posted_at"], "archived_at": row["archived_at"],
                                   "updated_by": row["updated_by"]})
```

Its JSON is exactly the TypeScript `LaunchRadarCard` in §5.2.

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
  `typeof domain === 'string'` and a `status` of `new`, `saved` or `archived`. `providesTags: ['LaunchRadarCards']`.
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
| `components/CardStatusLine.tsx` | One line. Left side, New and Saved tabs: `trackedCompanyId` gives the muted text "Already tracked". Otherwise a muted link "Job board" (`jobBoardHref`: the first of `ats.boardUrl`, `careersUrl` that is an `http(s)` URL; omitted if neither is). Archived tab: "Archived {Oct 7}". Right side, New tab: `Save` and `Archive` text buttons. Saved tab: `Unsave` and `Archive`. Archived tab: a `Restore` button and a `Delete` button (error color) that opens the dialog. Every button and link carries the company in its accessible name (`aria-label="Save Lightfield"`, "Job board Lightfield"), so a list of cards never has two controls with the same name. An unknown status renders no actions rather than crashing. |
| `components/CardBody.tsx` | Accordion details, aligned under the name (the header's 14px side padding). **Research incomplete** (only when `issues` holds a research gap, first, warning colour): one bullet per gap, so partial data never reads as "nothing found". A provenance note (`leaders from the brief …`, the payload has no field for it) is not a gap: it is left out of this block and of the "research incomplete" score lines, and the Team section shows it as a muted "Leaders from the company brief" line. **Team**: the leader bullets (bold name, muted title, `summary` line). When `leaders` is empty, the warning text "No leaders confirmed." is followed by "The people search returned company pages." if `leadersDropped > 0`. When leaders exist but none has `summary`, schools or prior companies, it shows the warning "No background data came back for these leaders". **Rest of team** (only when `teamStats`): the right label is "{profilesFound} public profiles" ("profile count unknown" when null); one bullet "Previously at Amazon (2), Twitter, … and N more" (top 6, count shown when >1); one bullet "{k} schools: …" (top 4 and "N more"); a muted "No schools or employers listed" when both lists are empty. Schools and employers only: there is no prior-exit line (the team is not checked for prior exits; the leaders are), and an old card's `exFoundersWithExit` is never shown. **Funding**: the right label is `totalRaisedUsd` + " total"; a bullet per round: "**{stage} {amountUsd}**, {Mon YYYY}. Led by {leads}, with {others}" (first 3 others, then "and N more"). **Highlights**: `notableFacts.slice(0, 3)`. **Why these scores**: a collapsed toggle (MUI `Collapse` or nested Accordion). Its bullets: the Talent line from `format.talentBreakdown`: "Talent 74: leaders 37 + team 37 (each out of 50)" (or
"Talent 38: leaders 19 of 50, doubled: no team data" / "Talent 24: team 12 of 50, doubled: no leader data") with two
sub-bullets "Leaders 37: {talentReasons.join('; ')}" and "Team 37: {talentTeamReasons.join('; ')}" (a missing part shows
its reason, "Leaders: no people data" when there is none); a pre-blend card (`talentBasis` null) keeps the single line
"Talent {n}: {talentReasons.join('; ')}"; "Talent: no people data, so no score" when Talent is null; and "VC {n}: {vcReasons.join('; ')}" or "VC: no funding data, so no score"; when the score is null AND `issues` holds a research gap the line reads "Talent: not scored, research incomplete" (same for VC). **Footer**: left "{Ashby} board, {9} open jobs" (verified), "{Provider} board, not verified" (unverified with a provider), or "No job board found". Right: "${costUsd.toFixed(2)} research". The source link is not repeated here: it is the "Announcement" link on the event line. |
| `components/EventLine.tsx` | funding: "{round ?? 'Funding'} **{amountUsd}**" then the muted date ("Sep 17", or "Sep 2026" for a `YYYY-MM` date). launch: "Launch" then the date. other: the headline, truncated. Then a small muted "Announcement" link to `event.sourceUrl` (`target="_blank" rel="noopener noreferrer"`, hostname as `title`), shown only when the URL is absolute `http(s)` (`safeHttpUrl`), with `aria-label="Announcement {company}"`; its click stops propagation so it never toggles the card. |
| `components/DeleteCardDialog.tsx` | MUI `Dialog`. Title "Delete {company} permanently?". Body "The card and its research go away. The loop will not post {domain} again." `Cancel` and a `Delete` button (contained, error color). It shows an error `Alert` if the mutation fails, and closes on success. |
| `format.ts` | Pure, unit-tested helpers: dates (`formatShortDate`, `formatMonthYear`, `formatEventDate`), money (`formatUsd`, the footer's research cost), the board (`atsLabel`, `boardLine`, `jobBoardHref`), links (`safeHttpUrl`, `hostnameOf`), lists (`joinWithAnd`, `listWithMore`, `summarizeTally`, `roundLine`), research notes (`researchGaps`, `leadersFromBrief`), the sort (`parseSort`, `scoreEmphasis`) and `cardToggleId`. Every `href` on a card goes through `safeHttpUrl` (the card's URLs are untrusted web data). |

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

- `.claude/skills/launch-radar/SKILL.md` has three parts:
  - **§0 Hard rules**: no pull requests and no repo changes (no `git`, `gh`, Edit, Write or Agent); never print secrets;
    never `Read` `~/.config/jvn-launch-radar/`; Bash only through the allowlist; no `--dangerously-skip-permissions`.
  - **§1 Run**: `scripts/launch_radar/radar.sh monitors-ensure`, then `radar.sh run --max-companies 3 --budget 1.00` with Bash
    timeout 600000. Re-run while the exit code is 3, at most 4 invocations. Exit 2 means the budget is spent, so log it and continue
    to §2.
  - **§2**: `radar.sh heartbeat --status ok|error --note …` is the **final** step.

  (The PR step that sat between the run and the heartbeat, opening at most one add-company PR per run, was removed on
  2026-10-07; see the note at the top.)
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
  - The command passes `--permission-mode dontAsk --setting-sources project` (the host's user and local
    settings cannot widen the list) and the `--allowedTools` / `--disallowedTools` lists of the `ALLOWED_TOOLS` block.

  **Never `--dangerously-skip-permissions`.** The exact list lives in one place, a `ALLOWED_TOOLS` block in `wrapper.sh`, and
  `SKILL.md` §0 quotes it verbatim. A unit test (`test_launch_radar_wrapper.py`) fails if the skip flag appears, if the
  two copies differ, or if the allowed list is anything but `Read(./**)` and the exact `radar.sh` commands
  (`monitors-ensure`, the two `run` lines, `heartbeat:*`). There is no generic `git`, `gh`, `curl`, `python`, `pip` or
  `npm` entry, since each of those can run code or upload a local file (`curl -T ~/.ssh/...`),
  and no Edit, Write, Agent or web tool: the run only drives the loop. When the skill records `status=error`, the wrapper
  exits 98 so the failure reaches the `.err` log.
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
       api/tests/test_proxy_path_allowlists.py api/tests/test_alembic_single_head.py
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
