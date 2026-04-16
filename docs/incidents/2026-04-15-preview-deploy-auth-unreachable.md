# Decision: Preview-deploy auth unreachable → GoogleOneTap crash + VITE_AUTH_BYPASS

**Date:** 2026-04-15
**Severity:** Medium (QA environment blocked; production unaffected)
**Impact:** Vercel preview deploys (`*-git-*.vercel.app`) crashed on load after the Auth0 / Google One Tap integration merged. `ErrorBoundary` caught `"Google OAuth components must be used within GoogleOAuthProvider"` and blanked the app, so PRs couldn't be visually reviewed on their preview URLs.

## Summary

After the Auth0 / Google One Tap integration shipped (PLAN.md), the production deploy worked but **every preview deploy** crashed on first render. Two related issues converged:

1. **Crash** — `<GoogleOneTap />` was rendered unconditionally in `App.tsx`, but `<GoogleOAuthProvider>` only mounted when `AUTH_CONFIG.isEnabled` was true. On previews, `VITE_AUTH0_*` env vars weren't scoped to the Preview environment, `isEnabled` evaluated false at build time (Vite inlines `import.meta.env.VITE_*` at build), the provider didn't mount, and `useGoogleOneTapLogin()` threw on the missing context.

2. **Fundamental gap** — even if we fixed the crash and uploaded the real auth env vars to Preview, auth still couldn't *function* on previews because:
   - Preview URLs are dynamic (`job-visualizer-notifier-git-<branch>-<hash>.vercel.app`).
   - **Google OAuth does not support wildcards** in Authorized JavaScript origins — each preview URL would need manual whitelisting.
   - Auth0 does support wildcard callbacks, but we hadn't configured them.
   - `vercel.json` pins `Access-Control-Allow-Origin` to the production domain, so `/api/*` calls from previews CORS-fail regardless.

The combination meant preview deploys couldn't run any feature that required a signed-in user — a regression the moment we started adding auth-gated features.

## Root Cause

### The crash (component rendered outside its required provider)

```tsx
// main.tsx → AuthProviders conditionally mounts real providers
if (!AUTH_CONFIG.isEnabled) return <>{children}</>;   // no provider

// App.tsx rendered GoogleOneTap unconditionally
<GoogleOneTap />                                      // crashes
```

`useGoogleOneTapLogin`'s `disabled: true` flag suppresses the prompt, **not** the context lookup — the hook reads `GoogleOAuthContext` on every render regardless. The component-provider coupling was accidental rather than enforced.

### Why previews can't do real OAuth

| Constraint | Wildcards? |
|---|---|
| Google OAuth Authorized JavaScript origins | ❌ No |
| Google One Tap allowed origins | ❌ No |
| Auth0 Allowed Callback URLs | ✅ Yes (`*.vercel.app`) |
| `vercel.json` `Access-Control-Allow-Origin` | N/A — literal string, pinned to prod |

Google's hard refusal to accept origin wildcards is the binding constraint. Every preview URL would need to be added by hand, which is incompatible with branch-based preview deploys.

## Decisions Made

### 1. Gate `GoogleOneTap` inside `AuthProviders` (PR #64)

Moved `<GoogleOneTap />` out of `App.tsx` and into `AuthProviders`, so it shares the `isEnabled` gate with the provider it depends on. Also extended `GoogleOneTap`'s `disabled` expression to cover an empty `googleClientId`.

**Why this over "just add the env vars to Preview":** env vars only mask the crash — a typo, a mis-scoped var, or a future change could re-trigger it. The component has a hard dependency on the provider's context; the code should enforce that structurally. Small diff (~10 LOC) and crash-proof regardless of env var state.

### 2. `VITE_AUTH_BYPASS=true` on Preview (PR for `feature/auth-bypass-for-qa`)

Added a **frontend-only** bypass flag. When the env var is set:
- `AuthProviders` short-circuits above the real Auth0/Google providers.
- `useAuth` module-dispatches to a fake-user implementation that never calls `useAuth0` or `useGoogleCredential`.
- Auth-gated UI renders with a static "QA Dev User".
- `getToken()` returns a placeholder string — backend calls that require a valid JWT will still 401.

The bypass env var is set to `Preview` scope only (`vercel env ls preview`), so production builds never see it.

**Why frontend-only, not a backend magic token:** a matching `AUTH_BYPASS_TOKEN` on Railway would enable full e2e testing on previews, but it creates real auth-bypass risk — if the token ever gets set on prod by mistake, anyone knowing the token can impersonate any user. Making bypass frontend-only means the flag has zero authn value outside Preview scope. The trade-off: you can test that auth-gated UI *renders* on previews, but not that backend auth integration actually works.

**Why not configure real OAuth for previews:** Google's no-wildcard policy for authorized origins means every dynamic preview URL would need manual whitelisting. Not feasible for branch-based previews.

## How to Fix for More Extensible Infrastructure

Three paths, increasing in effort and capability:

### Path A — Stable Vercel alias for QA (minimal infra work)

Use a Vercel deployment alias that always points at the latest preview for a chosen branch (e.g., `job-visualizer-qa.vercel.app` → most recent deploy of `main` or a `qa` branch).

- Pros: One stable URL to whitelist in Auth0 + Google Cloud + `vercel.json` CORS. Real OAuth works. Real e2e tests on previews.
- Cons: Only one QA environment at a time — doesn't help PR-specific previews. Requires discipline about promoting a preview to the alias.
- Effort: ~10 minutes Vercel + ~15 minutes Auth0/Google config.

### Path B — Dynamic CORS + Auth0 wildcards (per-PR previews mostly work)

- `vercel.json` → replace the literal `Access-Control-Allow-Origin` with a reflective origin check in each serverless function (`api/*.ts`), allowlisting `*-brendanpotter00s-projects.vercel.app` plus the prod domain.
- Auth0 → add `https://*-brendanpotter00s-projects.vercel.app` to callback/logout/web-origin lists.
- Google One Tap / social login → still won't work (no wildcard support); would fall back to Auth0 redirect or remain bypassed on previews.
- Effort: ~1–2 hours, requires updating every serverless proxy.

### Path C — Signed preview backend tokens (full e2e on previews, safely)

Replace the static bypass token with a short-lived, cryptographically signed token that both the preview frontend and the backend can verify. Token is issued only when `VITE_AUTH_BYPASS=true` *and* the matching signing key is present on the backend (Railway). Production has neither, so the bypass path is structurally unreachable in prod.

- Pros: Full e2e testing of auth-gated features on previews, no token-leakage risk.
- Cons: Real design work — key management, rotation, token expiry, separate backend auth path. Worth doing only once preview e2e testing is a load-bearing QA requirement.

**Recommended sequencing:** ship bypass now (✅ done), adopt Path A when the first auth-gated feature needs real e2e QA, revisit Path B/C only if per-PR preview auth becomes a hard requirement.

## Fix Applied

- **PR #64 (`fix/google-one-tap-missing-provider-crash`)** — Structural coupling:
  - `src/frontend/src/components/shared/AuthProviders.tsx` — `<GoogleOneTap />` rendered inside `<GoogleCredentialProvider>`.
  - `src/frontend/src/app/App.tsx` — removed `GoogleOneTap` import/render.
  - `src/frontend/src/features/auth/GoogleOneTap.tsx` — `disabled` now also short-circuits on empty `googleClientId`.

- **`feature/auth-bypass-for-qa`** — Frontend-only bypass:
  - `src/frontend/src/config/auth.ts` — `bypassEnabled` field, warns on boot.
  - `src/frontend/src/features/auth/useAuth.ts` — module-level dispatch to `useAuthReal` vs `useAuthBypass`.
  - `src/frontend/src/components/shared/AuthProviders.tsx` — bypass short-circuits above real providers.
  - Vercel: `VITE_AUTH_BYPASS=true` set on **Preview scope only** via `vercel env add VITE_AUTH_BYPASS preview`.

## Related

- `docs/implementations/auth0/PLAN.md` — original auth plan, gotcha #3 (HTTPS requirement) and the deployment-step section noted the Preview-scope concern but didn't resolve it.
- `docs/incidents/2026-04-12-vercel-dev-env-var-override.md` — related env-var precedence pitfalls in Vercel Dev.
