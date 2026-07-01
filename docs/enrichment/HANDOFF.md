# Enrichment — frontend + admin monitoring HANDOFF

This PR is **backend-only** (per the agreed scope). This document is the handoff
for the two follow-up surfaces that are **documented here but not implemented**:
a frontend for the new facets, and an admin monitoring dashboard for the pull
integration. Everything below builds on the API this PR ships.

> Companion: the enrichment workflow itself lives in the separate **job-enricher**
> repo (the laptop-side Claude Code agent that pulls, cleans, classifies, judges,
> and writes back). See that repo's `CLAUDE.md` + `README.md`.

---

## 1. What the backend already exposes (build against this)

### Read / filter (public jobs API — behind the existing internal-key proxy)
`GET /api/jobs` now returns four extra fields on every `JobListingResponse`
(camelCase): `category`, `level`, `tags: string[]`, `enrichmentStatus`. They are
`null` / `[]` until a job is enriched, so nothing changes visually until data lands.

New query params:
- `GET /api/jobs?category=software_engineering`
- `GET /api/jobs?level=entry` — **note the hierarchy: `entry` also returns `new_grad`
  jobs; `new_grad` returns only new-grad jobs.** This is the load-bearing contract.

The category enum is `software_engineering | product_manager | data_scientist |
data_engineer | business`. The level enum is `new_grad | entry | mid | senior |
senior_plus | manager`, seeded (with labels + ordering + the `new_grad→entry`
parent) in `job_levels` / `job_categories` so a dropdown can be **driven from data**.

### Monitoring (internal)
`GET /api/internal/enrichment/health` (internal-key) returns:
```json
{
  "enabled": true,
  "open_by_status": {"unenriched": 12000, "claimed": 60, "done": 16500, "needs_human": 40},
  "stale_claims": 0,
  "needs_human": 40,
  "last_enriched_at": "2026-07-01T03:10:00Z",
  "last_enriched_age_s": 92,
  "claim_ttl_minutes": 15
}
```
The laptop-side enricher exposes a richer per-stage metrics surface via its own
`cli health` (per-stage latency, throughput, retry counts, heartbeat age).

---

## 2. Frontend follow-up (React dropdowns)

Scope: add **Category** and **Level** filter controls to the companies/recent-jobs
views, mirroring the existing `GraphFilters` pattern (`createFilterSlice` factory).

1. **Types** (`src/frontend/src/types/index.ts`): add `category?: JobCategory` and
   `level?: JobLevel` to `GraphFilters`; add the two union types + a `tags: string[]`
   field to the job model (the transformer already receives them from the API).
2. **Dropdown data**: either hard-code the enums or add a tiny `GET /api/jobs/facets`
   endpoint (returns `job_categories` + `job_levels` rows with labels/order) so the
   dropdown labels stay data-driven. Recommend the endpoint — it future-proofs the
   taxonomy.
3. **Filter slice** (`createFilterSlice`): add `setCategory` / `setLevel`; thread
   into `graphFilteredJobs` selector. Server-side filtering is available
   (`?category=&level=`), but the list is already client-filtered per company, so
   filtering the already-fetched array is simplest — just match `job.category` and
   apply the **`entry`→{entry,new_grad}** expansion client-side too (mirror
   `_LEVEL_FILTER_EXPANSION`).
4. **UI**: two `<Select>`s in `GraphFilters.tsx`. Show `tags` as chips on the job
   row. Keep the "entry includes new grad" note in a tooltip so the hierarchy is
   discoverable.
5. **Tests**: selector tests under `src/frontend/src/__tests__/features/filters/`
   for the level-expansion behavior.

Gotcha: the level filter must expand on BOTH ends (server already does; if you
filter client-side, replicate it) or new-grad jobs vanish from the entry view.

---

## 3. Admin monitoring dashboard follow-up

Scope: an admin-only page (mirror `/api/admin` + the existing admin UI) that makes
the pull integration observable — the whole point of the pull model is that JVN
must notice when the unmanaged laptop goes dark.

Surface these (all already available):
- **Backlog funnel** from `/api/internal/enrichment/health` `open_by_status`
  (unenriched → claimed → done → needs_human) as a stacked bar.
- **Liveness**: `last_enriched_age_s` + `stale_claims`. Alert when
  `last_enriched_age_s` exceeds, say, 3× the tick interval (laptop stopped polling)
  or `stale_claims > 0` (laptop died mid-batch; those auto-reclaim after
  `claim_ttl_minutes`).
- **Needs-human queue**: list `job_enrichment` rows with `needs_human=true`
  (add a small admin endpoint: `GET /api/admin/enrichment/needs-human`) with the
  job title + the judge's `judge_notes`, so a human can correct the label. A
  correction writes back through the same facets.
- **Throughput / per-stage latency**: pull from the enricher's `cli health`
  (surface it via a tiny authenticated endpoint on the laptop edge, or have the
  enricher POST periodic metrics to a new `/api/internal/enrichment/metrics`).
- **Quality**: last eval scorecard (category accuracy, level exact vs
  filter-consistent, judge κ) — the enricher writes `golden/scorecards/*.json`;
  surface the latest.

Auth: reuse `require_admin`. Do not expose enrichment internals on the public API.

---

## 4. Rollout / operational notes

- The whole path is gated by `ENRICHMENT_USE_EXTERNAL` (default **false**). With it
  off, `/pending` hands out nothing and the cloud-Haiku location pipeline is the
  sole floor — the frontend fields are all null and nothing changes.
- Turn on for a subset first with `ENRICHMENT_COMPANY_ALLOWLIST` (csv), watch
  `/api/internal/enrichment/health` + the existing `/api/admin/locations/health`,
  then widen.
- Kill switch: set the flag off (or just stop the laptop). In-flight `claimed`
  rows auto-reclaim to `NULL` after `ENRICHMENT_CLAIM_TTL_MINUTES` and the Haiku
  floor keeps filling location. No data loss; `/results` is idempotent.
- `ENRICHMENT_REQUIRE_JUDGE_PASS=true` makes JVN refuse to publish facets for rows
  the judge flagged `needs_human` (they land as `enrichment_status='needs_human'`
  with the audit row, awaiting a human).
