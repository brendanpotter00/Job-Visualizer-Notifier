# Workday via residential proxy, every 2h

> **Superseded 2026-11-17.** The proxy turned out to be unnecessary: the real
> trigger was Python's TLS fingerprint, fixed by OpenSSL `DEFAULT` ciphers. The
> proxy code was removed and the cadence went back to `*/30`. See
> `docs/incidents/2026-11-16-workday-cloudflare-challenge.md`.

Incident: `docs/incidents/2026-11-16-workday-cloudflare-challenge.md`.

## Why

Since 2026-11-16 ~07:00 UTC every Workday request from Railway gets
`429` + `cf-mitigated: challenge`. That is Workday's Cloudflare sending a bot
challenge to Railway's datacenter egress IP. It is **not** a rate limit.
The same POST from a residential IP returns 200. #365 (429 retries, pod
cooldown) and #366 (non-2xx diagnostics) can't fix it: a challenge never
clears on retry from the same IP.

Fix: send Workday traffic through a paid rotating **residential proxy**
(`WORKDAY_PROXY_URL`). Run it every 2h instead of every 30 min to cut
proxy bandwidth (~7–15 GB/mo → ~2–4 GB/mo).

## Scope (backend only; no frontend, no migration)

### 1. Config — `src/backend/api/config.py`

- Add `workday_proxy_url: SecretStr | None = None` (env `WORKDAY_PROXY_URL`).
  It holds credentials (`http://user:pass@host:port`), so it is a `SecretStr`
  and is **never** logged, put in an exception message, or written to
  `scrape_runs`.
- Unset or empty means a direct connection, which is today's behavior. Local dev
  and tests work unchanged.

### 2. Client wiring — `src/backend/api/tasks/fetch_workday_company.py`

- Build the client with `httpx.AsyncClient(proxy=<url>)` when the setting is
  set, otherwise `httpx.AsyncClient()`. `httpx>=0.27`: use the `proxy=` kwarg.
  `proxies=` is removed in 0.28.
- Put the client construction in one small helper in `workday_client.py`
  (e.g. `workday_http_client() -> httpx.AsyncClient`). Then the task, and the
  admin trigger if it builds its own client, all share it. Grep for every
  `httpx.AsyncClient(` that talks to Workday and route them through the helper.
- Log once per task at INFO which egress is used: `egress=proxy host=<host>`
  or `egress=direct`. Host only, never userinfo.
- Do **not** fall back to direct when the proxy errors. Direct is known-blocked,
  and a silent fallback would hide a broken proxy. A proxy failure
  (`httpx.ProxyError`, 407, connect error) is an `httpx.HTTPError`, so it
  already records a failed scrape run.

### 3. Challenge ≠ rate limit — `src/backend/api/services/workday_client.py`

- New `WorkdayBlockedError(WorkdayRateLimitedError)`. Raise it when a response
  is a Cloudflare challenge. Detect that the same way `_diag_blocker` returns
  `cloudflare` (a `cf-mitigated` header, or a challenge-page body). Reuse that
  function; don't duplicate the logic.
- A challenge must **not** trip the per-pod cooldown. The pod isn't overloaded;
  our exit IP is flagged. Cooling down the pod would block the other tenants'
  fresh proxy IPs.
- Retry a challenge in place (same `WORKDAY_429_MAX_RETRIES` budget and backoff)
  **only when a proxy is configured**. A rotating proxy gives a new exit IP
  per request, so a retry can succeed. With no proxy, raise immediately: zero
  retries, since the same IP will just be challenged again.
- Real 429s (no challenge marker) keep the existing #365 behavior unchanged.
- Subclassing `WorkdayRateLimitedError` means `_NoRetryOnRateLimit` in the task
  already skips Procrastinate re-runs for it. Add a test that proves it.
- The error message names the host and says "Cloudflare challenge", so the
  scrape-run error and the health-watch text are self-explanatory.

### 4. Cadence — `src/backend/api/tasks/enqueue_workday_fan_out.py`

- `cron="*/30 * * * *"` → `cron="0 */2 * * *"`. Keep `periodic_id`.
- Update the module docstring and the comments that say "30-min" for Workday
  (the `_DEFER_SPACING_S` comment, the retry comment). Leave the other fan-outs
  alone.
- Check: `_WORKER_FRESHNESS_SECONDS` (main.py) depends on the heartbeat and
  the other `*/30` fan-outs, not Workday, so it needs no change. The
  health-watch `STALE_AFTER_HOURS = 6` is still 3 Workday ticks, so it is fine.
  Confirm both and leave a comment where a reader would look.

### 5. Tests — `src/backend/api/tests/`

Extend `test_workday_client.py`, `test_fetch_workday_company.py`, and
`test_enqueue_workday_fan_out.py`:
- The helper builds a proxied client when the setting is set and a direct one
  when it is unset or empty. Assert on the transport/mounts or monkeypatch the
  constructor. No real network.
- A challenge response with a proxy set retries in place, then raises
  `WorkdayBlockedError`, and does not trip the pod cooldown.
- A challenge response with no proxy raises `WorkdayBlockedError` after exactly
  one request.
- A plain 429 (no `cf-mitigated`) still follows the #365 path: retries, then
  cooldown.
- The task's retry strategy returns no-retry for `WorkdayBlockedError`.
- The fan-out periodic cron is `0 */2 * * *`.
- Neither the proxy URL nor its credentials appear in any log record. Use
  caplog with a URL containing `user:secret@`.

### 6. Docs

- `src/backend/AGENTS.md`: document `WORKDAY_PROXY_URL`, the 2h Workday
  cadence, and "challenge vs 429" in a short Workday section. Say plainly
  that direct egress from Railway is Cloudflare-challenged as of 2026-11-16.
- Root `AGENTS.md` lists Workday among the worker-fetched ATSs. Add one line
  saying Workday egresses through `WORKDAY_PROXY_URL`.

## Out of scope

- Buying the proxy and setting `WORKDAY_PROXY_URL` on Railway. Brendan does
  that; credentials are never handled by an agent.
- Browser impersonation (repo rule: never impersonate a browser).
- Other ATSs.

## Gates

- `PYTHONPATH=. pytest src/backend/api/tests -q` against local Postgres
  (`docker compose up -d postgres`). Run the Workday test files at minimum,
  then the full suite.
- `mypy` clean on changed files (same invocation CI uses; see
  `.github/workflows`).
- No frontend changes, so `npm run type-check` is not required.

## Rollout

1. Merge. Railway deploys; with no proxy set, Workday fails fast with
   `WorkdayBlockedError`, 1 request per company per 2h, so no retry noise.
2. Brendan sets `WORKDAY_PROXY_URL` on Railway, which redeploys.
3. Verify: `scrape_runs` for `ats='workday'` show `error_count=0` and
   `jobs_seen>0`, and Railway logs show `egress=proxy` with no `blocker=cloudflare`.
