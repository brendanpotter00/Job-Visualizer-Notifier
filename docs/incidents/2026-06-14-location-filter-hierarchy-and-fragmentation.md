# Incident: Location Filter Has No Hierarchy + Canonical Codes Are Fragmented

**Date:** 2026-06-14 (surfaced immediately after the tags-wiring work in `feature/location-normalization-monitor`)
**Severity:** Low (no outage, no data loss; wrong/under-inclusive filter results + duplicate dropdown options)
**Impact:** Selecting a **parent** location in the **Location** filter returned **none of its children**. Picking `California, US` showed zero jobs from `Cupertino, CA, US` or `Sunnyvale, CA, US`; `Texas, US` missed `Austin, TX, US`; and `United States` (which worked only by a country-code special case) had no general state/city rollup behavior. Separately, the same physical place appeared as several dropdown options (`London, England, GB` vs `London, England, UK` vs `London, UK`; three `Berlin`s) because the normalizer rendered country/region codes inconsistently. Net effect: users could not filter "everything in California," and the dropdown was noisy with near-duplicates.

## Summary

The previous PR (the "surface location tags" work, commit `41a4367`) correctly plumbed normalized canonical tags from `job_locations` → `/api/jobs` → the frontend filter, and each tag carries structured `kind`/`city`/`region`/`country` fields. But the matcher never used those fields:

```ts
// matchesLocation (jobFilteringUtils.ts) — before
if (filterLoc === 'United States') return tags.some(t => t.country === 'US');
return tags.some(t => t.canonicalName === filterLoc);   // exact string only
```

Filtering was **exact `canonicalName` string equality**, with a single hard-coded special case for "United States". A region option (`California, US`, a `kind='region'` row with `region='CA'`) and a city option (`Cupertino, CA, US`, `region='CA'`) are different strings, so the region never matched its cities — even though the data needed to relate them (`region='CA', country='US'` on both) was already on every tag. The hierarchy was *computable* and simply never computed.

Two gaps compounded:

1. **Matching gap (headline):** no hierarchical containment. A selected country/state/city matched only tags whose canonical string was identical, so parents never matched children.
2. **Data fragmentation:** even with hierarchical matching by code, the codes were inconsistent — `country` was mostly ISO-2 (`US`, `DE`) but also full names (`Brazil`, `India`, `Sweden`) and a `UK`-vs-`GB` split for the same country; `region` was clean 2-letter for US states but free-text abroad (`Bavaria`, `QLD`, `Karnataka`), sometimes equal to the country (`Dublin, IE, IE`), sometimes null. Comparing by `region`/`country` would have mis-grouped, and each rendering was a separate `locations` row = a separate dropdown option (the open `FOLLOWUP-canonical-fragmentation.md`).

This was not a regression — the filter had *always* matched exact strings. The previous PR changed the **expectation** (locations are a structured hierarchy: country ⊃ region ⊃ city) without changing the **matching logic** that the expectation depended on.

## Timeline

| Date | Event |
|------|-------|
| 2026-06-08 | Location normalization subsystem ships (`b8830a2`): `locations` with structured `kind/city/region/country/remote_scope`, the Haiku normalizer, the alias cache. |
| 2026-06-14 (earlier) | Canonical tags wired into `/api/jobs` + the dropdown/filter (`41a4367`). Filter matches by exact `canonicalName`. `FOLLOWUP-canonical-fragmentation.md` filed noting inconsistent country/region rendering (UK vs GB, full-name countries, non-ISO regions, `region == country`). |
| 2026-06-14 | User reports: the dropdown lists `California, US`, `Cupertino, CA, US`, `Sunnyvale, CA, US` as siblings; selecting `California, US` returns nothing from the cities. "Probably United States wouldn't show all of these, and Texas wouldn't show Austin." |
| 2026-06-14 | Investigation (code + prod via read-only Postgres MCP): the matcher is exact-string only; the structured fields exist but are unused; and the codes are fragmented enough that naive code-comparison would mis-group. |
| 2026-06-14 | Fix on `feature/location-normalization-monitor`: tier-aware hierarchical matching + synthesized parent options (frontend), a deterministic post-LLM canonicalization pass + one-off backfill/merge (backend). |

## Root Cause

### Why parents didn't match children

`matchesLocation` compared the selected option's **display string** to each tag's `canonicalName`. The hierarchy is encoded in the structured columns (`region`, `country`), not in the string, so:

- `California, US` (`kind='region'`, `region='CA'`, `country='US'`) ≠ `Cupertino, CA, US` (`kind='city'`, `region='CA'`, `country='US'`) as strings → no match.
- `United States` worked **only** because of a bespoke `country === 'US'` branch — there was no general rule, so no other country, state, or metro rolled up.

The missing invariant: *a selected location of tier T must match any tag contained by it* (country ⊇ all in-country; region ⊇ its cities). Nothing expressed or tested that.

### Why hierarchy-by-code wasn't safe yet

The normalizer prompt asks for "short codes when unambiguous" but does not force a single deterministic rendering, so Haiku varied run-to-run: country as ISO-2 vs full name vs `GB`/`UK`; region as ISO code vs full name vs the country code vs omitted. Because the `locations` uniqueness key is `(kind, city, region, country, remote_scope)`, each rendering became its own row. So even after adding hierarchical matching, comparing `country`/`region` across tags would split one real place across several codes (a London under `GB` and another under `UK` would not roll up together).

### Why tests didn't catch it

The matcher's unit tests asserted exact-string behavior — they **codified** the gap rather than flagging it. The backend eval scores normalization *quality* with field aliasing (`USA→US`, `UK→GB`), so it does not fail on inconsistent rendering. No test asserted "selecting a state surfaces its cities."

## Detection

Manual: a user clicking the live Location dropdown saw a state and its cities listed as siblings and found the state filter returned nothing. No automated signal — the matcher behaved exactly as written.

## Resolution

Fixed on `feature/location-normalization-monitor`. No schema migration (data + code only; `canonical_name` is unconstrained text).

- **A. Frontend — hierarchical matching.** `matchesLocation` resolves a selected option to a structured descriptor (via a per-pass index built from the jobs, plus a synthesized-US-state fallback) and matches by tier: country → any non-remote tag with the same `country`; region → same `region` **and** `country` (the country guard prevents cross-country region clashes like Ontario `ON`/CA); city → same `city`+`region`+`country`; remote → by `remoteScope`. An exact `canonicalName` match is kept as a baseline for tags lacking structured fields. Remote stays its own option (geographic filters don't pull remote in). `jobFilteringUtils.ts`.
- **B. Frontend — pickable parents.** `buildLocationOptions` synthesizes a `United States` meta-option and a `"<State>, US"` option for every US 2-letter region present (even when no job is tagged at state level), tiered country → states → cities. `lib/location.ts`, consumed by both dropdown selectors.
- **C. Backend — prevent recurrence.** A pure, deterministic `canonicalize()` pass (`services/location_canonicalize.py`) maps `country` → ISO-3166-1 alpha-2 (`Brazil→BR`, `UK→GB`), US `region` → USPS 2-letter, drops non-US region, collapses `region == country`, and recomputes the city label. It runs at the single write seam in `persist_llm_result` (downstream of the LLM, so the eval boundary is unchanged) and in the admin override path. Pure unit tests in `tests/test_location_canonicalize.py`; informational eval cases added.
- **D. Backend — backfill existing rows.** `scripts/one_off/2026-06-14_canonicalize_locations.py` applies the same `canonicalize()` to every `locations` row and **merges** rows that collapse onto one canonical identity — repointing `job_locations` and `alias_locations` FKs (composite-PK collision handling, `is_primary` OR-merge) before deleting the duplicates. `--dry-run` by default; in-place and deterministic (no LLM re-run).

## Lessons / Action Items

1. **A hierarchy in the data needs a hierarchy in the matcher.** Storing `kind`/`region`/`country` implies containment semantics; exact-string matching silently ignored them. When a model gains structure, the consumers must use it. — **done (this PR)**
2. **Add a containment seam test.** "Selecting a region surfaces its cities; a country surfaces every tier" now has explicit tests; it would have failed on day one. — **done**
3. **Determinism belongs downstream of the LLM, not in the prompt.** Prompts drift; a pure post-LLM canonicalization pass (covered by unit tests) is the durable fix for code consistency. — **done**
4. **Backfill + prevent-recurrence ship together.** Cleaning history without fixing the write path (or vice-versa) leaves the bug half-fixed; both landed in this PR. — **done**
5. **Some inputs are unfixable deterministically.** A row whose `country` is a *valid-but-wrong* ISO code (e.g. Tel Aviv stored under `IS`/Iceland) or the mis-`kind`-ed `New York, NY, US` region row is left unchanged and logged for manual review rather than guessed. — *backlog*

## Evidence (prod, 2026-06-14, read-only Postgres MCP)

```
canonical locations: 419   (322 city · 52 remote · 24 country · 21 region)
California:           39 CA cities + 1 "California, US" region row — never linked by the matcher
country fragmentation: ISO-2 (US×208, DE, IN, …) BUT also "Brazil"/"India"/"Sweden";
                       TWO "United Kingdom" country rows (country='GB' AND country='UK')
region fragmentation: US states clean 2-letter; intl free-text (QLD, Bavaria, KA);
                      1 US city region=null; "New York, NY, US" mis-stored as kind='region'
fragmented-city impact (FOLLOWUP doc): ~804 OPEN jobs on duplicated/mis-coded city options
```

| Symptom | Before | After |
|---|---|---|
| Select `California, US` | 0 jobs (string ≠ city strings) | every CA city + the CA region |
| Select `Texas, US` | 0 jobs | `Austin, TX, US`, … |
| Dropdown for one London | `London, England, GB` · `London, England, UK` · `London, UK` | one `London, GB` |
| `Berlin` | 3 rows (`Berlin, Berlin, Germany`; `Berlin, DE, DE`; `Berlin, Germany`) | one `Berlin, DE` |
