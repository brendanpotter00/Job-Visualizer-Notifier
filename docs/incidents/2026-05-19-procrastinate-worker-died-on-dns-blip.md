# Incident: Procrastinate Worker Permanently Dies on Transient DB Unreachability

**Date:** 2026-05-19
**Severity:** Medium
**Impact:** The Procrastinate fan-out worker on the Railway-deployed backend stopped processing periodic tasks at 2026-05-19 23:26:13 UTC after a transient internal-DNS failure on `postgres.railway.internal`. Close-detection paused for the duration: jobs that disappeared from source ATSes between the last successful fan-out at 22:30 UTC and the next manual Railway restart were not marked CLOSED until the worker was redeployed. No user-facing errors — the FastAPI HTTP path and the auto-scraper subprocess were unaffected. The worker is launched inside the FastAPI process lifespan and has no supervisor, so once `run_worker_async` returned with an exception there was nothing to restart it until the next process restart.

## Summary

A transient DNS-resolution failure for the Railway internal Postgres host triggered a two-stage cascade. First, both periodic fan-out tasks (`enqueue_greenhouse_fan_out` and `enqueue_ashby_fan_out`) burned through their 4-attempt retry budget in ~14 seconds while DNS was still down — they both moved to terminal `Error` state at 23:01:18 UTC. Twenty-five minutes later, Procrastinate's own async connector pool — separate from the FastAPI HTTP pool — timed out at the default 30-second `getconn` deadline while trying to fetch the next job (`psycopg_pool.PoolTimeout`). All five `single_worker` coroutines (`concurrency=5`) failed together, the `run_tasks` aggregator raised `RunTaskError`, and `run_worker_async` returned. The lifespan-spawned worker `asyncio.Task` ended. The `_worker_task_done` callback at `src/backend/api/main.py:137-142` only logged the exception — there was no restart loop, no `/health` signal, no supervisor — so the worker stayed dead until manual redeploy.

This is the same class of failure as the prior `psycopg-pool >=3.3` `**kwargs=None` crash that was pinned in commit `6fa12f0` (2026-05-17, see `feedback_use_alembic_migrations.md` adjacent context): "worker dies once, never comes back." That made it clear the right fix is supervision of the worker task, not another upstream pin.

## Timeline

| Time (UTC)            | Event |
|-----------------------|-------|
| 2026-05-19 13:28:47   | Deploy `32029601-e301-402a-91f1-ef9e4a9200d1` of commit `1d0d95a` ("Move Ashby to Backend Cron + Queue" #120) lands. Worker starts cleanly with `queues=['greenhouse_fetch', 'ashby_fetch'], concurrency=5`. |
| 2026-05-19 22:30:30   | Last fully-successful 30-minute fan-out tick: `enqueue_greenhouse_fan_out` + `enqueue_ashby_fan_out` defer ~50 `fetch_*_company` jobs across both queues; all complete within ~25s. |
| 2026-05-19 22:51:23   | First sign of DB connectivity trouble: `scraper[google]` and `scraper[microsoft]` subprocesses log `Failed to apply Alembic migrations` from their own short-lived psycopg2 connections. (These auto-scraper subprocesses are unrelated to the worker, but they share the same DB host and DNS path — they're the canary.) |
| 2026-05-19 23:00:01   | `procrastinate.periodic` defers `enqueue_greenhouse_fan_out[5264]` and `enqueue_ashby_fan_out[5265]`. The worker picks both up immediately. |
| 2026-05-19 23:00:01.829 | First attempt of both tasks fails: `psycopg2.OperationalError: could not translate host name "postgres.railway.internal" to address: Temporary failure in name resolution`. Stack hits `src/backend/api/tasks/enqueue_ashby_fan_out.py:67` (and the Greenhouse twin) → `await asyncio.to_thread(db.get_connection, settings.database_url)` → `psycopg2.connect(...)` at `scripts/shared/database.py:116`. Status: `Error, to retry`. |
| 2026-05-19 23:00:27   | Retry attempt 2 of both tasks. Same `OperationalError`. Status: `Error, to retry`. |
| 2026-05-19 23:00:52   | Retry attempt 3. Same `OperationalError`. Status: `Error, to retry`. |
| 2026-05-19 23:01:18   | Retry attempt 4 (final). Same `OperationalError`. Both tasks reach terminal `Error` status. The retry budget (`RetryStrategy(max_attempts=3, exponential_wait=2)` → attempts at `T+0, T+2s, T+4s, T+8s`) fully drained inside the ~14s DNS-outage window. |
| 2026-05-19 23:25:48   | Procrastinate's main coroutine logs `Main coroutine error, initiating remaining coroutines stop. Cause: ConnectorException('Database error.')`. Root: `psycopg_pool.PoolTimeout: couldn't get a connection after 30.00 sec` while `fetch_job` polled for the next task. Worker logs `Stop requested`. |
| 2026-05-19 23:26:13   | All 5 `single_worker` coroutines exit with `ConnectorException`. `run_tasks` raises `RunTaskError`. `run_worker_async` returns with the exception. `_worker_task_done` logs `Procrastinate worker task crashed: One of the specified coroutines ended with an exception`. **Worker is now dead for the lifetime of the process.** |
| 2026-05-20 ~01:30     | A single isolated `fetch_*_company` job runs to completion. This was an in-flight job from before 23:25:48 that finished its existing connection's work after the worker logged `Stop requested` but before final teardown. **No new fan-outs since 23:01:18.** |
| 2026-05-20 ~03:00     | Side-finding surfaced during Ashby migration verification: close-detection paused for ~4h. Reporter recommends Railway log check; Railway MCP requires re-login from the local environment. |
| 2026-05-20 ~03:30     | Railway login refreshed, logs pulled, root cause confirmed. Branch `fix/procrastinate-worker-restart-loop` opened for the supervised-restart fix. |

## Root Cause

Two defects interacted. The supervision gap is the load-bearing one — the DNS blip itself was transient and would have self-healed.

### Why the periodic fan-outs failed terminally

`src/backend/api/tasks/enqueue_ashby_fan_out.py:43-67` (and the Greenhouse twin) opens a fresh ad-hoc psycopg2 connection inside the task body via:

```python
conn = await asyncio.to_thread(db.get_connection, settings.database_url)
```

That call lands in `scripts/shared/database.py:116` → `psycopg2.connect(db_url, cursor_factory=RealDictCursor)`. When Railway's internal DNS could not resolve `postgres.railway.internal`, `psycopg2.connect` raised `OperationalError` immediately on every attempt.

The decorator's retry config is `RetryStrategy(max_attempts=3, exponential_wait=2)`. In Procrastinate semantics that means the initial attempt plus up to 3 retries with delays of 2s, 4s, 8s — four attempts inside a ~14-second window. The DNS outage was still in effect for the entire window, so every attempt observed the same `OperationalError` and the task moved to terminal `Error` state. The tasks won't be re-deferred until the *next* `*/30 * * * *` periodic boundary — provided the worker is alive to defer them.

This part of the system worked as designed; the retry window is intentionally narrow to bound worst-case retry pile-ups. Losing one 30-minute tick to a DNS outage is acceptable because the next tick re-fans-out the same set of `fetch_*_company` jobs (via the `queueing_lock` deduper). We are deliberately NOT tightening this retry budget — see "Out of scope" below.

### Why the worker stayed dead

Twenty-five minutes after the failed fan-outs, Procrastinate's own background `fetch_job` poll loop hit the same DB unreachability — but instead of a fast `OperationalError` on `psycopg2.connect`, it hit a slow `PoolTimeout` on `psycopg_pool` because the async connector pool's internal connections had gone stale during the outage and could not be reopened within the 30-second `getconn` default. All five `single_worker` coroutines failed in lockstep. `procrastinate.utils.run_tasks` raised `RunTaskError`. `run_worker_async` returned.

The worker is launched here (`src/backend/api/main.py:137-151`):

```python
def _worker_task_done(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("Procrastinate worker task crashed: %s", exc, exc_info=exc)

worker_task = asyncio.create_task(
    procrastinate_app.run_worker_async(
        queues=["greenhouse_fetch", "ashby_fetch"],
        concurrency=5,
    )
)
worker_task.add_done_callback(_worker_task_done)
```

The done-callback **only logs**. There is no `while True`, no restart, no exponential backoff, no `/health` signal. Once the task ends, the worker is gone. `procrastinate_events` does not store error text, so the cause was not visible from the DB — only from Railway container logs.

The FastAPI HTTP path was unaffected because it uses an entirely different connection pool (`dependencies.py:24-35`, `ThreadedConnectionPool(maxconn=15)`). The auto-scraper subprocess (`services/auto_scraper.py`) was also unaffected because it shells out via `asyncio.create_subprocess_exec` and reconnects on each cycle.

## Fixes Applied

### Supervised worker restart loop — `src/backend/api/main.py`

`run_worker_async` is now wrapped in a `_supervised_worker` async function that catches non-`CancelledError` exceptions and retries the worker with exponential backoff (1s → 60s ceiling). On `CancelledError` — which is what FastAPI's lifespan shutdown raises — the supervisor re-raises so the shutdown teardown at `main.py:156-160` runs cleanly.

This means: any transient DB unreachability (DNS hiccup, Railway network blip, primary failover, idle-timeout cascade) now self-heals within ≤60s of connectivity returning, with no human intervention or Railway redeploy.

### What is NOT changed in this PR

- **Periodic-task `RetryStrategy`.** Still `(max_attempts=3, exponential_wait=2)`. Tightening it to survive multi-minute DNS outages would also retry deterministic programmer-error failures more times, which we don't want. The supervisor handles worker-level recovery; per-tick recovery is the next periodic boundary, which is fine.
- **`/health` worker-aware signal.** `/health` still returns 200 when the FastAPI HTTP pool is healthy, regardless of worker state. Adding a worker liveness check is reasonable future work but out of scope here — once the supervisor exists, the worker should not stay dead long enough for an external monitor to care.
- **`psycopg-pool` pin.** Still `>=3.2.0,<3.3.0` per `src/backend/api/requirements.txt:11`. That pin addressed a *different* prior crash (the `kwargs=None` splat); the supervisor would have handled both classes of failure even without the pin, but the pin is still correct.
- **Procrastinate connector pool sizing.** Default is fine; the supervisor handles the failure mode.

## Lessons

- **Background tasks launched in FastAPI lifespan need supervisors, not just done-callbacks.** A `done_callback` that "only logs" is not a recovery mechanism — it's an alert mechanism, and we don't ship our alerts anywhere. The pattern was copied to `_scraper_task_done` too (`main.py:124-135`); the auto-scraper happens to survive because it shells out and reconnects per cycle, but the same risk applies in principle.
- **Procrastinate's async connector pool is separate from the FastAPI HTTP pool.** Two pools, two independent failure modes. `/health` checks the wrong one for worker liveness.
- **Transient cloud DNS failures are real and not catchable with tighter retry alone.** Internal-VPC DNS at Railway, GCP, AWS occasionally fails for tens of seconds to minutes. A retry budget measured in seconds is hopeful; a supervisor measured in minutes is correct.
- **`procrastinate_events` is not enough for incident forensics.** No error text. Always reach for container logs (Railway MCP `get-logs` with `@level:error` filter) when a worker has "just stopped."

## Why we didn't tune the periodic `RetryStrategy`

Tempting first instinct: bump `max_attempts=3, exponential_wait=2` to something like `max_attempts=6, exponential_wait=5` so the fan-out survives a multi-minute DNS outage. Rejected because:

1. The 30-minute periodic boundary is the *real* retry — losing one tick is fine, because the next tick re-fans-out the same set of companies via the `queueing_lock` deduper. The system is already designed around "occasional tick loss is OK."
2. Tightening the per-task budget means deterministic programmer-error failures (TypeError, NameError, etc.) also retry more times, wasting worker capacity and confusing logs.
3. The actual problem isn't "the fan-out couldn't survive the DNS blip." It's "the entire worker died and didn't come back." Fixing the second fixes the first incidentally — the next tick will run cleanly once connectivity returns.

## References

- Prior worker crash, different trigger: commit `6fa12f0` (2026-05-17) pinning `psycopg-pool<3.3.0` for a `**kwargs=None` crash that also took down the worker without restart.
- Prior pool-related incident with a different shape (HTTP pool exhaustion, not worker death): `docs/incidents/2026-05-17-recent-jobs-pool-exhaustion.md`.
- Code touched: `src/backend/api/main.py:137-151`.
