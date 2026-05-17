# Lock Down Railway Backend with Shared-Secret Middleware

## Context

A stranger emailed Brendan offering to use his "public API" for their own agentic workflows. Investigation confirmed the Railway-hosted FastAPI backend at `https://job-visualizer-notifier-production.up.railway.app` is reachable from anywhere on the internet, and `GET /api/jobs` returns up to 10,000 normalized jobs per request without authentication. `CORS_ORIGINS` is correctly restricted, but CORS is browser-enforced only — `curl` and scripted agents ignore it entirely. The Railway public domain is also discoverable via certificate transparency logs and Railway's predictable subdomain pattern, so URL obscurity is not a defense.

Decision (per user):
- **Scope**: Railway backend only (`/api/jobs`, `/api/features`, plus everything else on the FastAPI app). The Vercel ATS proxies (`/api/workday`, `/api/eightfold`, etc.) stay open for now — that's a separate, lower-priority concern.
- **Anonymous browsing must keep working** on `onesecondswe.dev` — visitors should still see jobs without signing in. The lockdown must be transparent to the browser, which means a **server-side shared secret** between the Vercel proxy layer and the Railway backend.
- **Foundation for future MCP/API key system**: design the gate as a single middleware that today checks one internal header, but is structured so a future `Authorization: Bearer <api_key>` check (DB-backed, with per-key rate limits) drops in as a second branch without restructuring. No premature `api_keys` table or billing scaffolding yet.

## Approach

Add a FastAPI middleware that requires `X-Internal-Key: <secret>` on every request except `/health`. The four Vercel serverless proxies (`api/jobs.ts`, `api/jobs-qa.ts`, `api/users.ts`, `api/features.ts`) attach this header from `process.env.INTERNAL_API_KEY`. JWT-based per-route auth (Auth0/Google) continues to layer on top of this gate — the internal key only proves "the call came from our infrastructure," not who the user is.

This kills direct scraping of `https://job-visualizer-notifier-production.up.railway.app/api/jobs` without changing how the browser talks to the app, and gives a clean future hook for issuing per-customer API keys.

### Why not other options

- **JWT on every route**: would force every visitor to sign in. Rejected — user wants anonymous browsing preserved.
- **Origin/Referer header check**: trivially spoofable and provides no real defense against scripted agents.
- **Vercel BotID / IP rate limiting only**: doesn't actually deny access, just slows scrapers; rotating IPs defeat it.
- **Pre-build the full API key DB + rate limit infra**: rejected as premature — MCP/monetization is "later down the line," not now. Build the gate now, layer keys when MCP is real.

## Files to modify

### Backend (Python / FastAPI)

- **`src/backend/api/config.py`** — add a new `internal_api_key: str | None = None` setting (Pydantic reads it from the `INTERNAL_API_KEY` env var).
- **`src/backend/api/auth/internal_key.py`** *(new file)* — middleware function `require_internal_key(request, call_next)` that:
  - Allows `/health` through unconditionally (Railway internal healthcheck + external uptime monitors).
  - Reads `X-Internal-Key` from the request headers, compares against `settings.internal_api_key` using `secrets.compare_digest` (constant-time, defends against timing attacks).
  - Returns `JSONResponse({"detail": "Unauthorized"}, status_code=401)` on mismatch or missing header.
  - If `settings.internal_api_key` is `None` (local dev where the env var isn't set), allow all requests through and log a single WARNING at startup so the gap is visible. In prod the env var is always set so the gate is always active.
  - **Future extension point** (documented in a one-line comment, not implemented now): a second branch checking `Authorization: Bearer <api_key>` against a future `api_keys` table will slot in here.
- **`src/backend/api/main.py`** — register the middleware via `app.middleware("http")(require_internal_key)`. Must be registered **after** `CORSMiddleware` so CORS preflight `OPTIONS` requests still work (Starlette runs middleware in reverse-registration order; the CORS middleware needs to wrap the auth check).
- **`src/backend/api/tests/conftest.py`** — extend the existing `TestClient` fixture (or wherever the FastAPI test client is built) to set `X-Internal-Key` to a known test value, and set `settings.internal_api_key` to the same value via env var (`monkeypatch.setenv("INTERNAL_API_KEY", "test-key")` before app import). Then add one new test file `src/backend/api/tests/test_internal_key_middleware.py` covering: (a) request without header → 401, (b) request with wrong header → 401, (c) request with correct header → passes through to the route, (d) `/health` works without the header.

### Vercel proxies (TypeScript)

Each proxy adds `X-Internal-Key: process.env.INTERNAL_API_KEY` to its upstream `fetch`. To avoid four copies of the same logic, add a small helper:

- **`api/utils/internalKey.ts`** *(new file)* — exports `getInternalKeyHeader(): Record<string, string>` that returns `{ 'X-Internal-Key': process.env.INTERNAL_API_KEY }` when the env var is set, or `{}` when it isn't (local dev fallback). One source of truth for the header name.
- **`api/jobs.ts`** — currently calls `fetch(url)` with no options at all (line 18). Change to `fetch(url, { headers: getInternalKeyHeader() })`.
- **`api/jobs-qa.ts`** — merge `getInternalKeyHeader()` into the existing `headers` object.
- **`api/users.ts`** — same pattern.
- **`api/features.ts`** — same pattern.

The `Authorization` header forwarding stays untouched — that's the user-facing JWT, separate from the infra-level internal key.

### Existing utilities being reused (no changes)

- `api/utils/backendUrl.ts` — the localhost-vs-prod detection already works correctly; the helper just gets the URL.
- `api/utils/forwardResponse.ts` — response forwarding is unchanged.
- `secrets.compare_digest` from Python stdlib — no new dependency.
- The existing JWT validation chain (`src/backend/api/auth/dependencies.py`, `auth/jwt.py`) — unchanged. Layers on top of the internal-key gate.

## Rollout order (critical — get this wrong and the frontend breaks)

1. **Generate the secret locally**: `openssl rand -hex 32` → 64-char hex string.
2. **Set `INTERNAL_API_KEY` on Vercel** (Production, Preview, Development scopes) via `vercel env add` or the dashboard. **Vercel first**, before Railway, so the proxies start sending the header before the backend starts requiring it.
3. **Deploy the Vercel proxy changes** (steps from "Vercel proxies" section above). Backend isn't requiring the header yet, so this is forward-compatible — the header just gets ignored.
4. **Set `INTERNAL_API_KEY` on Railway** (same value) via Railway dashboard or `railway variables --set`.
5. **Deploy the backend changes** (middleware enforcement). This is the cutover — once this deploys, any request without the header gets 401.
6. **Verify** (see verification section).

If step 5 deploys before step 2/3, the frontend immediately 401s on every Railway call.

## Verification

After deployment, all of these must hold:

1. **Direct backend scraping is blocked**:
   ```bash
   curl -sI https://job-visualizer-notifier-production.up.railway.app/api/jobs
   # expect: HTTP/2 401
   curl -s https://job-visualizer-notifier-production.up.railway.app/api/jobs | head
   # expect: {"detail":"Unauthorized"}
   ```

2. **Health check still works** (for Railway probe + external monitors):
   ```bash
   curl -s https://job-visualizer-notifier-production.up.railway.app/health
   # expect: OK
   ```

3. **Frontend still works via Vercel proxy**:
   - Visit `https://onesecondswe.dev` (or `https://job-visualizer-notifier.vercel.app`) in a browser.
   - Pick a backend-scraped company (Google or Apple — they go through Railway, not direct ATS).
   - Confirm jobs render. Open DevTools Network tab and confirm `/api/jobs?company=google` returns 200.
   - Sign in, visit account/features pages, confirm `/api/users` and `/api/features` still work.
   - As an admin, visit `/admin` and confirm `/api/admin/users` and `/api/jobs-qa/*` work.

4. **Tests pass**: `cd src/backend && pytest` — including the new `test_internal_key_middleware.py`.

5. **Auto-scraper still runs**: tail Railway logs for the next scrape cycle (default interval 1 hour) — it should fire and complete. The auto-scraper is an in-process asyncio task that calls `get_db()` directly, not over HTTP, so it should be unaffected; this is a sanity check.

6. **Local dev still works**: `npm run dev:vercel -w src/frontend` + `uvicorn …` with no `INTERNAL_API_KEY` env var set anywhere. The backend should log one WARNING about the missing key on startup and accept all requests. The Vercel proxy sends no header (helper returns `{}`), backend allows it through. App fully functional.

## What this plan does NOT do

- **Does not touch the Vercel ATS proxies** (`/api/workday`, `/api/eightfold`, etc.). They remain open. A follow-up effort can apply a similar pattern (or Vercel BotID + IP rate limiting + Origin checks) — file a separate issue.
- **Does not implement rate limiting, API keys, or billing.** Those are the future MCP work; this plan only adds the structural foundation (one middleware to extend).
- **Does not address the leak in the test file** (`src/frontend/src/__tests__/api/serverless/users.serverless.test.ts` references a placeholder `api.production.railway.app`). The placeholder isn't the real URL, and the real URL is discoverable via CT logs regardless, so this is hygiene-only; not a security fix worth bundling here.
- **Does not respond to the stranger's email.** That's Brendan's call (decline, ignore, or have a conversation).
