# Eightfold ATS — Review Audit

## Reviewer 1 (first pass)

**Date**: 2026-04-18
**Scope**: git diff main (Eightfold integration) + untracked new files (`api/eightfold.ts`, `eightfoldClient.ts`, `eightfoldTransformer.ts`, and their tests).

### Summary

Overall the integration closely follows the PLAN and mirrors the existing `workdayClient` / `api/workday.ts` pattern. Transformer field mapping matches the live Eightfold response shape (verified by the plan's `curl`), pagination terminates on the real-world "partial final page" signal, abort is threaded through, and the retryable/non-retryable error classification is correct. Tests cover almost all the critical branches.

**However, there is one critical SSRF vulnerability in `api/eightfold.ts` that must be fixed before merge** — the tenant-host allowlist regex effectively allows any `*.com` or `*.net` hostname, which turns the proxy into an open relay for arbitrary HTTP GETs against any `.com`/`.net` host (rate-limit scrapers, Slack webhooks, private IaaS endpoints on custom domains, etc.). One additional important issue around swallowing partial results on abort and a couple of smaller items are noted below.

**Verdict: needs changes (blocked on the SSRF fix).**

### Findings

#### Critical (must fix before merge)

1. **SSRF: tenant-host regex is far too permissive** — `api/eightfold.ts:16`
   - Issue: `EIGHTFOLD_HOST_PATTERN = /^[a-z0-9.-]+\.(eightfold\.ai|net|com)$/i` allows **any** hostname ending in `.com` or `.net`. Verified empirically: `evil.com`, `attacker.net`, `localhost.net`, `burpcollaborator.net`, and even `attacker.eightfold.ai.evil.com` all pass. Combined with the `api/apply/` path prefix this still lets an attacker hit arbitrary `https://<anything>.com/api/apply/...` endpoints through our Vercel deployment — a classic open-proxy / SSRF primitive. Workday's equivalent regex is tight (`^https:\/\/[a-z0-9-]+\.wd\d+\.myworkdayjobs\.com$`); Eightfold's should be equally tight.
   - Fix: Narrow to the actual tenant shapes we need. For example:
     ```ts
     const EIGHTFOLD_HOST_PATTERN = /^(?:[a-z0-9-]+\.)*eightfold\.ai$|^explore\.jobs\.netflix\.net$/i;
     ```
     or — even better — build the allowlist at module load from `companies.ts` tenant hosts (the plan already flagged this as future hardening in §10 risk #7; do it now). The regex change alone closes the hole; the `companies.ts`-derived allowlist is defense in depth.

#### Important (should fix)

2. **Silent partial results on abort** — `src/frontend/src/api/clients/eightfoldClient.ts:68-71`
   - Issue: When `options.signal.aborted` is true between pages, the loop `break`s and the function returns whatever was aggregated so far with no indication to the caller that the fetch was interrupted. `workdayClient` doesn't have this check — it just lets the next `fetch` throw an `AbortError`, which is the more defensive pattern and matches the user's stated preference for "correctness over don't crash" (don't swallow partial state to look successful). Returning a normal `FetchJobsResult` with a truncated `jobs` array could poison the RTK Query cache with an incomplete dataset that looks authoritative.
   - Fix: After `break`-ing on aborted signal, throw an `AbortError` (or let the next iteration's `fetch` throw naturally by removing the preemptive check). Either way the caller should see a rejection, not a success with partial data.

3. **Client re-derives `companyId` from `cfg.domain` instead of using the caller's `Company.id`** — `src/frontend/src/api/clients/eightfoldClient.ts:208`
   - Issue: `const companyId = cfg.domain.split('.')[0] || cfg.domain;` happens to produce `'netflix'` for `netflix.com`, which matches `COMPANY_IDS.Netflix = 'netflix'`. But the plan already flagged this as risk #8: any future tenant whose domain slug doesn't match the internal company id (e.g. `createEightfoldCompany('foo-inc', 'Foo Inc', { domain: 'foocorp.com' })`) will silently produce `Job.company = 'foocorp'`, mismatching the `byCompany` key `'foo-inc'` and breaking the RTK Query cache + selectors. This is a trap waiting for the next company to step on.
   - Fix: Add a required `companyId: string` (or reuse `id`) to `EightfoldConfig` and pass it through from the factory. Other factories already carry the id implicitly via their identifier pattern; do the same here. Alternative: rename `domain` to make the constraint explicit (`internalCompanyId`) — but an explicit field is clearer.

4. **Tenant-host header validation doesn't reject empty-after-trim payloads consistently** — `api/eightfold.ts:58`
   - Issue: `typeof tenantHeader !== 'string' || !tenantHeader.trim()` correctly rejects empty/whitespace, but the following regex test then runs against the un-trimmed value. Leading/trailing whitespace will fail the regex anyway, but it's easy to end up with `" explore.jobs.netflix.net "` slipping through if someone later loosens the regex. Minor hardening.
   - Fix: `const tenant = tenantHeader.trim();` once and use `tenant` for both the regex test and the URL template.

#### Nice-to-have (optional)

5. **JSON parse failure masks upstream 5xx HTML bodies** — `api/eightfold.ts:98-101`
   - When the upstream returns non-JSON (a maintenance HTML page, a gateway error, a CAPTCHA interstitial), `response.json()` throws and the proxy returns a generic 500 "Proxy error: Unknown error", losing the real upstream status. This is the same pattern as `api/workday.ts`, so it's consistent with the codebase — but the user's memory flags Workday Netflix broke silently this way. Consider checking `response.ok` first, and if the body isn't JSON, forward the upstream status + a structured error payload. Not strictly in scope for this PR but worth a follow-up.

6. **`MAX_ITERATIONS` guard returns silently with stale metadata** — `src/frontend/src/api/clients/eightfoldClient.ts:179-184`
   - If the guard triggers (no partial page signal and `count` over-reports), we log an error and return partial results without any indication on the returned `metadata`. Same class of silent-failure pattern as #2. Consider surfacing this via an `incomplete: true` metadata flag or throwing, rather than trusting callers to check logs.

7. **`APIError.atsProvider` cast in `baseClient.ts` still omits `'gem'`** — `src/frontend/src/api/clients/baseClient.ts:160-166, 210-216`
   - Pre-existing: the cast union excludes `'gem'` even though the `APIError` class type union includes it. The PR extends the cast to include `'eightfold'` but doesn't add `'gem'`. Not strictly part of this change; happy to leave for a follow-up, but note that anyone reviewing this hunk will see it.

8. **Dead `baseUrl` local in eightfoldClient** — N/A (no such variable; clean). (Cross-check: the client is notably clean compared to workdayClient's trailing-slash massaging — good.)

9. **Minor test-coverage gap**: `eightfoldClient.test.ts` does not assert that `MAX_ITERATIONS` triggers a corresponding error log / metadata flag — only that the fetch count caps at 200. If #6 is addressed, add a matching assertion.

### Things that looked good

- Transformer correctly handles unix-seconds → ms conversion, null `work_location_option`, comma-delimited locations with whitespace collapse, id fallback chain, and raw reference preservation. Tests cover all of these.
- Pagination stop conditions are complete: `hitTotal`, `hitLimit`, `emptyPage`, and the real-world `partialPage` (which is what actually catches Eightfold's count over-reporting). The "count=100 but only 23 rows exist" test proves this works.
- Page-size cap is clamped both client-side (`Math.min(requestedPageSize, 10)`) and enforced by the server — belt-and-braces, verified by the `defaultPageSize: 50` test.
- Error classification (500/502/503/504/429 retryable; 404/401 non-retryable; network/JSON-parse wrapped and retryable) matches the workdayClient pattern and is tested.
- `vercel.json` changes are correct: new rewrite follows the existing `:path(.*)` pattern, and the `Access-Control-Allow-Headers` value has `X-Eightfold-Tenant-Host` appended without breaking other proxies.
- Netflix Workday block fully removed; `COMPANY_IDS.Netflix = 'netflix'` preserved; Eightfold block placed in its own labeled section.
- No `any`/unsafe casts beyond the pre-existing `config.type as ...` pattern that already existed for the other providers. Types on `EightfoldJobPosition` and `EightfoldAPIResponse` are appropriately permissive (`[key: string]: unknown`) for an undocumented endpoint.
- `getClientForATS` dispatch test added (`src/frontend/src/__tests__/api/utils.test.ts`) — the exact test the plan called for.
- CORS preflight, method gating (GET/OPTIONS only, 405 otherwise), and path-prefix restriction in the proxy are all unit-tested.

### Resolutions (Reviewer 1 fixes applied)

- **#1 SSRF (Critical)**: Tightened `api/eightfold.ts` allowlist. Replaced the permissive `/^[a-z0-9.-]+\.(eightfold\.ai|net|com)$/i` regex with `/^(?:[a-z0-9-]+\.)*eightfold\.ai$/i` plus an explicit `EIGHTFOLD_VANITY_HOSTS` Set containing `explore.jobs.netflix.net`. Added parameterised regression tests for `evil.com`, `attacker.net`, `burpcollaborator.net`, `attacker.eightfold.ai.evil.com`, `localhost`, `127.0.0.1`, and `eightfold.ai.evil.com` (all correctly 400).
- **#2 Silent partial on abort (Important)**: `eightfoldClient.ts` now throws `DOMException(..., 'AbortError')` instead of `break`ing and returning partial results. Updated the existing abort test to assert `.rejects.toMatchObject({ name: 'AbortError' })`.
- **#3 Fragile companyId derivation (Important)**: Added required `companyId: string` to `EightfoldConfig`. `createEightfoldCompany` now sets `companyId: id` from the factory's first argument. Client uses `cfg.companyId` directly (removed `cfg.domain.split('.')[0]` guess). Updated the test to prove the client uses the explicit field by passing `companyId: 'foo-inc'` with `domain: 'foocorp.com'`.
- **#4 Tenant header trim (Important)**: Introduced a `const tenantHost = tenantHeader.trim();` local and use it for both the allowlist check and the target URL. Added a regression test: header `"  explore.jobs.netflix.net  "` now forwards correctly.

Nice-to-haves #5–#9 deferred (not blockers, shared-pattern cleanup).

Post-fix verification: `npm run type-check` = 0 errors. `npm test` = 1011/1011 passing (up from 1003; 8 new SSRF + trim + explicit-companyId tests).

---

## Reviewer 2 (second pass)

**Date**: 2026-04-18
**Scope**: Post-Reviewer-1 state. Independent second-pass review.

### Summary

Reviewer 1's four resolutions are all applied correctly and the tightened SSRF
guard holds up against an aggressive battery of attack vectors (uppercase,
leading/trailing dots, zero-width spaces, IDN/punycode, URL-embedded
credentials, `eightfold.ai.evil.com`, IPv6 literals, `:port` suffixes, double
dots). `DOMException('AbortError')` works in Node's vitest runtime, the browser,
and Vercel's Fluid Compute runtime, so the abort fix is portable. `companyId`
is non-optional and every caller provides it. I found one legitimate data-
correctness bug in the client (AbortError wrapped as retryable APIError),
one design omission (`MAX_ITERATIONS` silently returns partial results), one
doc gap (CLAUDE.md unchanged), and a couple of minor cleanups. None is a hard
blocker, but finding 1 below is worth addressing before merge if RTK Query
retries are wired up.

### New findings

#### Critical
_(none that weren't already flagged by Reviewer 1)_

#### Important

1. **`AbortError` thrown mid-fetch gets wrapped as a retryable `APIError`** — `src/frontend/src/api/clients/eightfoldClient.ts:86-103` (confidence ~85)

   When `fetch()` is aborted while in flight (as opposed to between pages), the
   browser/Node fetch throws `DOMException('AbortError')`. The current `try/catch`
   around `fetch` unconditionally rewraps that as
   `APIError(..., retryable=true)`. This defeats the between-pages fix from
   Reviewer 1: a caller that aborts during the first fetch will see a retryable
   APIError instead of an AbortError, and RTK Query / caller retry logic may
   re-issue the request the user explicitly cancelled. It also silently loses
   the abort signal shape (`err.name === 'AbortError'`) that callers typically
   check.

   Fix: detect abort before wrapping:
   ```ts
   } catch (err) {
     if (err instanceof Error && err.name === 'AbortError') throw err;
     // ... existing wrap ...
   }
   ```
   Same pattern likely wanted in `workdayClient.ts` but that's pre-existing and
   out of scope. The `fetch` aborted path is not covered by a test — add one
   that calls `controller.abort()` mid-`fetch` and asserts `name: 'AbortError'`.

2. **`MAX_ITERATIONS` guard returns success with partial data** — `src/frontend/src/api/clients/eightfoldClient.ts:181-186` (confidence ~80)

   Reviewer 1 listed this as Nice-to-have #6 and deferred it. I'm upgrading it
   to Important because it directly contradicts the user's stated
   "correctness over don't crash" memory rule — on hitting the cap we log an
   error and return a `FetchJobsResult` that looks authoritative to RTK Query.
   The existing test (`respects MAX_ITERATIONS safety guard`) explicitly
   asserts `result.jobs.length).toBeGreaterThan(0)`, pinning the wrong behaviour
   in. Fix: throw an `APIError('Eightfold pagination exceeded MAX_ITERATIONS',
   undefined, 'eightfold', false)` (non-retryable — raising MAX_ITERATIONS is a
   code change, not a transient failure). Update the test accordingly.

#### Nice-to-have

3. **CLAUDE.md docs not updated** — root `CLAUDE.md` and `src/frontend/CLAUDE.md` still list Greenhouse/Lever/Ashby/Workday/Gem as the ATS set and don't mention Eightfold. The plan's §11 step 11 explicitly called for this. The frontend CLAUDE.md even says "Six ATS providers … supported" and enumerates them. Minor; easy fix.

4. **Stale "Netflix" in `workdayClient.test.ts:591`** — A test named `'should send correct header for wd1 instance (Netflix)'` still uses `netflix.wd1.myworkdayjobs.com` as the generic wd1 example. Test still passes (the logic is tenant-agnostic), but the fixture is misleading post-migration. Rename the case to a non-Netflix wd1 tenant or drop it.

5. **`baseClient.ts` `config.type as ...` cast still omits `'gem'`** — pre-existing, Reviewer 1 noted it. This PR extended the cast to add `'eightfold'` but didn't fix `'gem'`. The cast's narrowed union is a latent footgun; calling the factory with a gem config will emit a runtime string that the `APIError.atsProvider` union doesn't allow. Out of scope for this PR but leaves one more line to touch.

6. **Final-page-exactly-equals-pageSize + missing `count` → over-fetches to MAX_ITERATIONS** — Edge case: if Eightfold omits `count` (→ `total = Infinity`) AND the last page happens to be exactly 10 rows, none of the stop conditions fire (`hitTotal` can't, `partialPage` can't, `emptyPage` triggers on page N+1). Client then does N+1 fetches and aggregates one empty page. Not a correctness bug (the empty page adds nothing and stops the loop), but it's one wasted round-trip. Low value to fix; document or ignore.

### Agreement / disagreement with Reviewer 1's resolutions

- **Finding #1 (SSRF)**: **Correct**. Tested 22 attack vectors locally (uppercase, punycode/IDN, trailing dot, leading dot, zero-width spaces, `:port`, IPv6 `[::1]`, `eightfold.ai.evil.com`, `attacker.eightfold.ai.evil.com`, `user@evil.com`, path injection, double dot) — all rejected. Legitimate hosts (`eightfold.ai`, nested `*.eightfold.ai`, uppercase `EXPLORE.JOBS.NETFLIX.NET`) all pass. The `EIGHTFOLD_VANITY_HOSTS` Set + regex combo is the right shape and the parameterised tests lock it in.

- **Finding #2 (abort between pages)**: **Correct but incomplete**. The between-pages path now throws `DOMException('AbortError')` — confirmed that works in Node ≥14.17 (vitest), browsers, and Fluid Compute. But the mid-`fetch` abort path (more common in practice, since `signal.aborted` is only checked at loop boundaries) is still silently rewrapped as a retryable `APIError`. See new Important #1 above.

- **Finding #3 (companyId)**: **Correct**. `EightfoldConfig.companyId` is required (non-optional), the factory sets `companyId: id` from its first arg, the client uses `cfg.companyId` directly, and the test proves divergent `companyId`/`domain` pass through correctly.

- **Finding #4 (trim)**: **Correct**. `tenantHost = tenantHeader.trim()` is used for both the allowlist check and the URL template, with a regression test for `"  explore.jobs.netflix.net  "`.

### Verdict

**needs changes** — approve on condition of fixing Important #1 (AbortError unwrapping) and Important #2 (MAX_ITERATIONS → throw). The rest are follow-ups. Reviewer 1's four resolutions themselves are applied correctly and the code quality is solid.

---

## Reviewer 2 resolution notes

### Important #1 — AbortError mid-fetch wrapped as retryable APIError — FIXED

`src/frontend/src/api/clients/eightfoldClient.ts:94-99` — the fetch catch block
now detects native `AbortError` and rethrows it unchanged so RTK Query sees a
cancellation, not a retryable network failure:

```ts
} catch (err) {
  if (err instanceof Error && err.name === 'AbortError') {
    throw err;
  }
  // ... existing wrap as retryable APIError ...
}
```

### Important #2 — MAX_ITERATIONS silently returns partial success — FIXED

`src/frontend/src/api/clients/eightfoldClient.ts:189-201` — hitting the cap now
throws a non-retryable `APIError` with fetched/reported counts so the caller
sees the truncation instead of caching it:

```ts
if (iteration >= MAX_ITERATIONS) {
  logger.error('[Eightfold Client] Max iterations reached', { ... });
  throw new APIError(
    `Eightfold pagination exceeded ${MAX_ITERATIONS} iterations (fetched ${allPositions.length}, reported ${total})`,
    undefined, 'eightfold', false
  );
}
```

Test at `eightfoldClient.test.ts:185-202` updated from
`expect(result.jobs.length).toBeGreaterThan(0)` (which pinned the old silent
behaviour) to `rejects.toMatchObject({ name: 'APIError', retryable: false })`.

### Verification

- `npm run type-check` — passes
- `npm test` — 1011 / 1011 passing (64 files)
- `npx vitest run src/frontend/src/__tests__/api/eightfoldClient.test.ts src/frontend/src/__tests__/api/serverless/eightfold.serverless.test.ts` — 51 / 51 passing

---

## Vercel deployment verification

The serverless path was verified end-to-end for the production environment:

1. **Catch-all rewrite present** — `vercel.json:28-30` routes
   `/api/eightfold/:path(.*)` → `/api/eightfold?path=:path`, which matches how
   every other ATS proxy is wired. The client hits `/api/eightfold/api/apply/v2/jobs`
   and the handler reconstructs the path from `req.query.path`.

2. **CORS preflight header allowed globally** — `vercel.json:82` includes
   `X-Eightfold-Tenant-Host` in the global `Access-Control-Allow-Headers`. The
   handler also sets per-response CORS (`api/eightfold.ts`) so OPTIONS requests
   short-circuit with 204 before any upstream call.

3. **Runtime compatibility** — Vercel's default is Node 24 (Fluid Compute).
   `DOMException('AbortError')`, `fetch`, and `URLSearchParams` are all
   native in that runtime; no polyfills required. The handler has no
   `process.env` reads, so the known Vercel Dev env-var trap (cloud env vars
   override local `.env` files) cannot bite us.

4. **Tenant-host allowlist anchored** — `isAllowedEightfoldHost()` uses
   `^(?:[a-z0-9-]+\.)*eightfold\.ai$` + a literal vanity-host Set
   (`explore.jobs.netflix.net`). No wildcard TLD escapes; 7 SSRF vectors are
   locked down by the parameterised test in `eightfold.serverless.test.ts`.

5. **Body forwarding** — handler forwards status + JSON body verbatim, so the
   client's retryability mapping (500/502/503/504/429 → retryable) still
   applies end-to-end through the proxy.

No deployment-environment deltas vs. local; the same fetch code path, the same
CORS headers, and the same runtime primitives apply.
