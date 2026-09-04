# Performance Audit — Owner Decisions

Recorded 2026-09-03. These three decisions were made by the owner against the
findings in [`PERF-AUDIT-FINDINGS.md`](./PERF-AUDIT-FINDINGS.md) §7 ("The decisions
the owner must make"). They drive the Wave-1 build — see
[`WAVE1-PLAN.md`](./WAVE1-PLAN.md).

---

## The three decisions

### ① `filtered_total` — defer / approximate. **APPROVED.**

> Exact "N results" totals on filtered searches are **not** worth 250–600 ms on
> every page-1. Fast searches beat exact counts.

- Corresponds to audit decision #1 (the single cheapest high-leverage decision) and
  finding **B1**.
- The exact `COUNT(*)` (`filtered_total`) is the expensive half of every filtered
  page-1 search (keyword ~600 ms, location ~444 ms). It is dropped from the hot path.
- Consequence: **B1 ships in THIS wave.** The page returns immediately; the total is
  deferred (returned `null`) and the UI approximates it from the rows already loaded.
- Knock-on: this also makes **C3 unnecessary** — deferring the count removes the
  keyword-search predicate from the hot path for free, so there is no need to
  denormalize `search_text` + GIN just to make the exact synchronous count cheap.

### ② Keyword search IS a product priority → **C3 greenlit, but LATER wave.**

> Keyword search matters, so `search_text` + GIN trigram (C3) is approved in
> principle — but it belongs to a **later wave, NOT this one.**

- C3 = denormalize `job_listings.search_text` + one `gin_trgm_ops` index (audit
  finding C3 / SCHEMA-AUDIT Finding 3).
- **Wave assignment: WAVE 2.** It is a schema + write-path change (`search_text`
  includes tags, which change on enrichment, so every write must recompute it; a GIN
  trigram is expensive to maintain on writes). B1 (decision ①) already removes the
  keyword count from the hot path, so C3 is an optimisation of the *exact synchronous
  count*, not a page-latency fix — no urgency.
- **Do NOT implement C3 in this workflow.**

### ③ Location filter — the real fix is `primary_country` → **C2 greenlit, but LATER wave.**

> Location is the #1 slow endpoint and the real fix is the denormalized column, so
> `primary_country` (C2) is approved — but it belongs to a **later wave, NOT this one.**

- C2 = denormalize `job_listings.primary_country` + partial compound keyset index
  (audit finding C2 / SCHEMA-AUDIT Finding 2).
- **Wave assignment: WAVE 2.** Migration + bounded backfill + a write-path change in
  every `fetch_*_company` upsert; coordinate schema + query owners.
- For THIS wave, the app-only half — **B2** (pre-resolve selections to a
  `normalized_location_id` set) — plus **B1** (kill the location count) takes location
  page-1 from 2.08 s → ~1.4 s **with no migration**. C2 later takes it to ~0.9 s.
- **Do NOT implement C2 in this workflow.**

---

## Wave map (what this decision set produces)

| Item | What | Wave | In this workflow? |
|---|---|---|---|
| **A1** | Edge-cache `facets` / `companies` / `locations` proxies | 1 | ✅ yes |
| **RTK TTLs** | `companiesApi` 60→3600, `locationsApi` 60→900 | 1 | ✅ yes |
| **C1** | Drop `idx_job_freshness_last_seen` + dup-user-index hygiene | 1 | ✅ yes |
| **B1** | Defer/approximate `filtered_total` (decision ①) | 1 | ✅ yes |
| **B2** | Pre-resolve location ids (app half of decision ③) | 1 | ✅ yes |
| **B3** | Thin the trend-page projection | 1 | ✅ yes (scoped — see plan) |
| **C2** | Denormalize `primary_country` (decision ③, real fix) | **2** | ❌ NO |
| **C3** | Denormalize `search_text` + GIN (decision ②) | **2** | ❌ NO |

**This workflow is WAVE 1 ONLY.** No new denormalized columns, no scraper write-path
changes. C2 and C3 are explicitly out of scope.
