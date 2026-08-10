# Incident: Railway Postgres Container Freeze Wedges the Entire Backend

**Date:** 2026-08-10 (03:12–04:25 UTC; ~73 min)
**Severity:** High — full user-facing outage
**Impact:** The Railway-hosted Postgres container froze at ~03:12 UTC. The backend degraded in two stages: first the Procrastinate worker crash-looped (03:13–03:21), then by ~03:30 every layer of the process was blocked awaiting the frozen database and the public API stopped responding entirely — `https://onesecondswe.dev/api/jobs` timed out, so the job board was down. Railway showed **both** services as healthy/SUCCESS the whole time. Recovery required manually redeploying both containers (`railway redeploy --service Postgres`, then the backend) at ~04:20 UTC; the stack was fully healthy by 04:25 UTC.

## Summary

The Postgres container began a routine checkpoint at 03:11:52 UTC and never completed it — its last *checkpoint* line ever (only error/reset lines followed before total silence at 03:30). Within a minute, client connections started dying (`Connection reset by peer` server-side, `SSL SYSCALL error: EOF detected` client-side — each side blaming the other, the signature of a mid-path/host-level break rather than a process crash on either end). The database entered a zombie state: its TCP stack still **accepted** new connections (the host kernel was alive) but backends stopped completing queries, stopped writing checkpoints, and eventually stopped logging entirely. New connections were accepted and then dropped without a Postgres error message.

The backend app was collateral damage, in two stages:

1. **Worker crash-loop (03:13–03:21).** An orphaned server-side session held an uncommitted `INSERT` into `procrastinate_periodic_defers`. Every periodic-deferrer tick then blocked on that speculative-insert lock (`while inserting index tuple` / `while locking tuple` in the Postgres log), hit the 60s worker `statement_timeout`, and Procrastinate treated the failure as fatal for the whole worker. The 2026-05-19 supervisor did its job — restart with 1s→16s backoff — but each restart ran into the same wall.
2. **Total wedge (~03:30 onward).** As the freeze deepened, connections stopped erroring and started **hanging**. This defeated every timeout the app had:
   - **libpq TCP keepalives** (30s/10s/×3, already configured in `augment_db_url`) never fired — the frozen host's *kernel* still ACKed the probes; only the Postgres *process* was dead.
   - **`connect_timeout=10`** only bounds connection establishment — established sockets blocked in `recv()` forever.
   - **Server-side `statement_timeout`** requires a functioning server to enforce it — the frozen server enforced nothing.

   The FastAPI pool's checkout probe (`SELECT 1` in `dependencies.get_db`) blocked forever one checkout at a time, the Procrastinate connector hung mid-await, the heartbeat task froze, and the process emitted **zero log lines from 03:30 to the manual restart** — alive, green in Railway, and completely unable to serve.

No platform recovery ever came, because the assumed safety net did not exist: `railway.toml` said *"Railway auto-restarts the container on 503"* via `healthcheckPath = /health/worker` — the intended fix for exactly this silent-hang class after the 2026-05-19 incident. Railway's docs are explicit that healthchecks gate **deploy cutover only**: *"Railway does not monitor the healthcheck endpoint after the deployment has gone live."* The endpoint was unreachable for 45+ minutes and nothing restarted. The restart policy (`ON_FAILURE`) never engaged either — it triggers on process **exit**, and a wedged process never exits.

### Which company was scraping, and did it cause this?

The **Apple** scraper (Playwright, page 163 of jobs.apple.com) and the **Google** scraper were both mid-scrape when the freeze hit. They were victims, not causes: Apple's incremental writer observed its DB connection die mid-batch (`SSL SYSCALL error: EOF detected`), logged `Incremental scrape failed - Seen: 3430, New: 0, Errors: 1`, and correctly did **not** run close-detection — the #232 truncation guard held, so no mass closure resulted. The freeze started inside Postgres during its own checkpoint, on a database doing routine load it had been sustaining for months (~215 MB WAL per 5-min checkpoint cycle at peak, CPU ≈ 0). Nothing the app did that night was unusual.

## Timeline (UTC, 2026-08-10)

| Time | Event |
|------|-------|
| 03:11:52 | Postgres logs `checkpoint starting: time` — **the checkpoint never completes** (historically every checkpoint logged completion in 3–270 s; no checkpoint line ever appears again). |
| 03:12:53–03:13:14 | Postgres logs `could not receive data from client: Connection reset by peer` ×2 — client connections dying. Simultaneously, backend logs `psycopg.pool: error connecting in 'pool-1': connection timeout expired`. |
| 03:13:05 | Procrastinate main coroutine errors: `ConnectorException('Database error.')`. First worker crash; supervisor restarts in 1s. |
| 03:14:59, 03:19:26, 03:20:35 | Postgres: `canceling statement due to statement timeout` **while inserting index tuple in `procrastinate_periodic_defers`** — each new worker's periodic deferrer blocked behind an orphaned session's uncommitted insert. Worker crash-loop continues, backoff growing toward 16s. |
| 03:20:31 | Apple scraper's DB connection dies mid-batch: `SSL SYSCALL error: EOF detected`; run recorded as failed, no close-detection ran (truncation guard held). |
| 03:21:34–03:21:51 | Last signs of life: `/api/jobs` requests still return 200; worker restarts once more; Postgres logs one final statement-timeout (`while locking tuple`, the periodic-defer DELETE ... FOR UPDATE). |
| ~03:30 | Backend goes **completely silent** — no log line of any kind until manual restart. Postgres logs two final `Connection reset by peer` lines and also goes silent. The public API now hangs (no response) — job board down. |
| 04:15 | Investigation confirms from outside: `GET /api/jobs` times out (20s, HTTP 000); Railway `environment_status` still reports both services SUCCESS; Postgres metrics show CPU ≈ 0.15%, disk flat at 4.43 GB — no resource exhaustion. Direct `psql` to the DB: `server closed the connection unexpectedly` on connect. Postgres has logged nothing for 45 min (no checkpoints — it logs one every 5 min when healthy). |
| ~04:20 | Operator manually redeploys the Postgres service, then the backend service. |
| 04:24:03 | Backend boots clean: migrations apply, worker starts on all 8 queues. |
| 04:25:02 | First heartbeat tick succeeds; `/health/worker` reports `status: ok`; `GET /api/jobs` back to 200 in ~0.6s. Full recovery. |

## Root Cause

**Primary (trigger):** infrastructure-level freeze of the Railway Postgres container, beginning during the 03:11:52 checkpoint. From the tenant's view the exact substrate mechanism is opaque (Railway host or storage stall; the mid-checkpoint onset is suggestive of storage I/O), but the observable signature is unambiguous: process stopped completing work and logging, kernel kept accepting TCP and ACKing keepalives, metrics kept flowing, platform status stayed green. Not resource exhaustion (CPU ~0, disk flat, memory stable), not an app deploy (last deploy 30+ hours prior), not load (routine).

**Secondary (why it took the whole product down): the app had no detector or recovery for a database that hangs rather than errors.** Every existing defense assumed the DB either responds or *refuses*:

| Defense | Why it was blind |
|---|---|
| libpq TCP keepalives (`augment_db_url`) | Frozen *process*, live *kernel* — probes get ACKed, socket looks healthy |
| `connect_timeout=10` | Bounds new connections only; established sockets hung in `recv()` |
| Server-side `statement_timeout` | Enforced by the server, which was frozen |
| `get_db` checkout probe (`SELECT 1`) | The probe itself hung, wedging the checkout it was protecting |
| 2026-05-19 worker supervisor | Handles worker *exceptions*; the final state produced none — just silence |
| `healthcheckPath = /health/worker` restart | **Does not exist.** Railway healthchecks gate deploy cutover only; no post-deploy monitoring, no restart-on-503 |
| `restartPolicyType = ON_FAILURE` | Triggers on process exit; a wedged process never exits |
| Daily scraper-health-watch / GH Action | Correct but slow-loop (daily) — next-morning detection for an evening outage |

**Tertiary (persistence of the lock pile-up):** the freeze orphaned a server-side session mid-transaction holding an uncommitted `procrastinate_periodic_defers` insert. Postgres would only reap it via its own TCP timeouts — which never progressed on a frozen process — so every worker restart re-queued behind the same lock until the container was replaced.

## Fixes Applied (this PR)

1. **`api/services/db_watchdog.py` (new)** — in-process DB liveness watchdog on a plain daemon thread (immune to event-loop wedges). Every 30s it probes on a **fresh** connection, with the probe running in its own thread joined against a **hard wall-clock deadline (15s)** — a probe that hangs counts as a failure the moment the deadline passes, which is precisely the case keepalives cannot see. After ~5–6 sustained minutes of failure it writes a CRITICAL line straight to fd 2 (immune to blocked log handlers) and `os._exit(70)`s the process, converting an invisible wedge into a Railway `ON_FAILURE` restart. Started at the top of the lifespan — **before migrations** — so a frozen DB can't wedge boot either. Configurable via `DB_WATCHDOG_*` env vars.
2. **`migrations.apply_alembic_migrations_with_retry` (new)** — startup migrations run on an `augment_db_url`-hardened DSN (keepalives + `connect_timeout`; Alembic's engine otherwise gets the raw URL and would hang instead of erroring) and retry **server-unreachable** failures every 15s for up to 10 minutes (`DB_BOOT_CONNECT_RETRY_SECONDS`). Classification is marker-based, not "any `OperationalError`" — auth failures, `DiskFull` (the 2026-04-18 incident class), `QueryCanceled` etc. fail the deploy immediately instead of retrying for hours.
3. **`railway.toml`** — the false "Railway auto-restarts the container on 503" comment replaced with the documented reality (deploy-gating only) and a pointer to the watchdog; `restartPolicyMaxRetries` raised 10 → 50 (~5 h of outage coverage at ~6 min per restart cycle — the watchdog window caps the boot retry budget); `healthcheckTimeout` raised to 600 to match the boot retry budget.
4. **`main.py`** — watchdog wired into the lifespan; the `/health/worker` docstring and `_WORKER_FRESHNESS_SECONDS` comment no longer claim a platform restart behavior that doesn't exist.
5. **Tests** — `api/tests/test_db_watchdog.py` covers: sustained failure → fatal; **hung** probe → fatal (the incident signature); intervening success resets the failure window; `stop()` halts cleanly; the fresh-augmented-connection probe contract; and migration-retry classification (connection-refused retries; auth failure, `DiskFull`, non-operational errors fail fast; budget exhaustion re-raises). An autouse conftest fixture disables the watchdog in tests.

### Expected behavior in a recurrence

- **DB freezes, kernel alive (this incident):** watchdog probes hang → ~5–6 min later the process exits → Railway restarts it → each boot cycle waits for the DB (retry budget, capped by the watchdog window) until it returns → clean recovery with zero human action once the DB is back. The Railway dashboard shows a crash-looping backend instead of a green lie, and the CRITICAL exit line is greppable in logs.
- **DB container replaced/rebooted (old IP gone):** existing keepalives kill the dead sockets in ~60s; pool checkout probes replace connections; worker supervisor reconnects — app self-heals without restart (this is also why the app recovered instantly once the operator redeployed Postgres).
- **What this does NOT fix:** the Postgres container freezing in the first place — that layer belongs to Railway. If freezes recur, the remaining lever is moving the database (e.g., managed Postgres with an SLA).

## What is NOT changed

- **Procrastinate periodic-defer lock behavior.** The 60s worker `statement_timeout` and the supervisor already bounded and survived the lock pile-up correctly; the pile-up resolves itself once the zombie session dies with its container. No procrastinate internals patched.
- **Scraper retry budgets and the #232 truncation guard.** Both behaved exactly as designed under fire.
- **`/health/worker` semantics.** Still the deploy-cutover gate and still useful there; only the comments claiming more were corrected.
- **Client-side keepalive tuning.** Already present and correct for the failure modes it can see (dead host, dead path, replaced container).

## Lessons

- **A frozen database is not an erroring database.** Every timeout in the stack assumed errors. The hang case needs a wall-clock deadline enforced *outside* the connection, from a thread that cannot itself be wedged by the thing it monitors.
- **Verify platform behavior against platform docs, not comments.** The restart-on-503 assumption lived in `railway.toml` for months, survived a code review, and shaped the mental model during two incidents. Railway's docs state the limitation in one sentence.
- **"Green" on the platform dashboard means "the process hasn't exited"** — nothing more. A liveness claim must be backed by something that *makes* the process exit when it stops being alive. That is now the watchdog's one job.
- **Both sides blaming the other (`reset by peer` server-side, `SSL EOF` client-side) plus dual-container silence points at the substrate**, not at either process. Checking "when did each container last log *anything*" (checkpoint cadence for Postgres) located the freeze faster than any query could.
- **Restart budgets and boot behavior are one system.** A watchdog that exits during an outage is only safe alongside a boot path that waits the outage out; shipping the first without the second converts "wedged forever" into "permanently down after N crash-loops."

## References

- Prior incident, same organ, different disease: `docs/incidents/2026-05-19-procrastinate-worker-died-on-dns-blip.md` (worker died on *erroring* DB; fixed by the supervisor that tonight's *hanging* DB walked straight past).
- Related: `docs/incidents/2026-05-17-recent-jobs-pool-exhaustion.md` (HTTP pool exhaustion), `docs/incidents/2026-05-06-apple-scraper-hang.md`.
- Railway docs: [Healthchecks](https://docs.railway.com/deployments/healthchecks) ("not used for continuous monitoring"), [Restart Policy](https://docs.railway.com/deployments/restart-policy).
- Code touched: `src/backend/api/services/db_watchdog.py`, `src/backend/api/migrations.py`, `src/backend/api/main.py`, `src/backend/api/config.py`, `railway.toml`, `src/backend/api/tests/test_db_watchdog.py`.
