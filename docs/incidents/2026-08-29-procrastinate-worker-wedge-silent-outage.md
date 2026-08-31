# Incident: Procrastinate Worker Wedges Silently — 61-Hour ATS Scrape Outage

**Date:** 2026-08-29 01:55 UTC → 2026-08-31 ~15:00 UTC (~61 hours)
**Severity:** High — silent, prolonged data-staleness outage (no user-facing error page)
**Impact:** At ~01:55 UTC on Aug 29 the in-process Procrastinate **worker** stopped executing jobs and never recovered. The FastAPI process stayed up the entire time — `GET /api/jobs` served 200s, the auto-scraper loop kept running — so nothing looked broken from the front end. But every **Procrastinate-driven** job stopped: all **128 ATS companies** (Greenhouse, Ashby, Lever, Gem, Eightfold, Workday) had **zero scrapes for 61 hours**, 2,286 jobs piled up `todo`, and `worker_heartbeats` froze at 2026-08-29 01:11:35 UTC. Only the **5 script scrapers** (Google, Apple, Microsoft, Amazon, TikTok) kept running — they live on the `auto_scraper` asyncio loop, which never touches Procrastinate. `scrape_runs/day` fell from ~6,230 across 133 companies to ~100 across 5. The worker's own liveness monitor (`worker_heartbeats` / `/health/worker`) correctly went 503 the whole time, but nothing acts on that 503 to restart a *live* container. Recovery was a deploy/restart (which the fix in this PR also makes automatic).

## Summary

A **transient Postgres disruption at ~01:54 UTC** wedged the worker permanently. The chain:

1. Five in-flight ATS fetches all blew past the app's **120 s per-task timeout** at once (`_TASK_TIMEOUT_S`), because the database had gone slow/unavailable. Each timeout cancels the task coroutine mid-query.
2. Those cancellations left the tasks' DB transactions aborted — `psycopg2.errors.InFailedSqlTransaction: current transaction is aborted` — and the tasks fell back to their "record the run on a fresh connection" path (`fetch_ashby_company.py:329`).
3. Simultaneously, Procrastinate's **own polling connector** raised `ConnectorException('Database error.')`. That is Procrastinate's *main* coroutine — the one that fetches the next job and multiplexes the periodic deferrer. When it raises, `procrastinate.utils.run_tasks` logs **`Main coroutine error, initiating remaining coroutines stop`** and requests a graceful stop of everything else, then **waits for the in-flight jobs to finish** (`Waiting for job to finish: worker 0..4`).
4. But those five in-flight jobs were themselves wedged on the same dead database, so the graceful drain **never completed**. `run_worker_async` **hung** — it neither returned nor raised.

Because `run_worker_async` never returned, the lifespan supervisor (`_supervised_worker`, which only reacts to a `return` or an `Exception`) never restarted it. The process stayed alive: uvicorn kept serving, and Procrastinate's periodic deferrer kept **enqueuing** `worker_heartbeat` / `scan_unnormalized` / the six `*/30` fan-outs — so `procrastinate_events` stayed *fresh* even though **nothing executed any of them**. The queue grew unbounded. The database recovered within seconds, so the DB watchdog (which probes the DB, not the worker) correctly saw a healthy database and did nothing. **Nothing in the process monitored worker liveness**, so the wedge was invisible to every existing safety net for 61 hours.

Nothing was destroyed. The data went **stale, not wrong**: with no scrapes there were no close sweeps, so `closed_jobs` over the whole window stayed at normal-churn levels (28 in the last 24 h, 395 in 72 h — all from the 5 still-running script scrapers), and 32,204 jobs stayed OPEN.

## Timeline (UTC, 2026-08-29)

| Time | Event |
|------|-------|
| 01:52:22 | Last Procrastinate job ever succeeds (`procrastinate_events` last `succeeded`). |
| 01:52:31 | Worker grabs its last job — `fetch_ashby_company[782807]` (judgmentlabs). Last `started` event; nothing executes after this. |
| 01:54:21–01:54:45 | Five fetches hit the 120 s cap at once: `fetch_greenhouse_company exceeded 120.0s for imc / instacart / jumptrading`, `fetch_ashby_company exceeded 120.0s for harvey / judgmentlabs — Procrastinate will retry`. |
| 01:54:52 | `psycopg2.errors.InFailedSqlTransaction: current transaction is aborted` — tasks fall back to recording the run on a fresh connection (`fetch_ashby_company.py:330`). The DB is unhealthy. |
| 01:55:25 | All five jobs end `Error, to retry` (lasted 160–184 s) with `TimeoutError` / `CancelledError` tracebacks. They are re-queued (`deferred_for_retry`) but scheduled for the future. |
| 01:55:55 | **`ERROR procrastinate.utils: Main coroutine error, initiating remaining coroutines stop. Cause: ConnectorException('Database error.')`** followed by `Stop requested` and `Waiting for job to finish: worker 0..4`. **The worker hangs here — forever.** |
| 01:57 onward | The periodic deferrer keeps deferring `worker_heartbeat` every 5 min and the fan-outs every 30 min. No `started` event ever appears again. `worker_heartbeats.at` frozen at 01:11:35. |
| Aug 29 → Aug 31 | `/health/worker` returns 503 continuously. Railway does not restart a live-but-503 container. 2,286 jobs accumulate `todo`. Watchdog SMS fired once (Aug 29); Aug 30–31 suppressed as duplicates. |

## Root cause

**A worker whose `run()` HANGS is invisible to every supervisor the codebase had.** The supervisor (`_supervised_worker`) restarts the worker only when `run_worker_async` **returns** or **raises**; a hung coroutine does neither. There was no monitor of worker *liveness* — only of DB liveness (`db_watchdog`) and a deploy-cutover healthcheck.

The trigger was a transient DB blip, the same class as the [2026-08-10 Postgres freeze](2026-08-10-postgres-container-freeze-backend-wedge.md) and [2026-05-19 DNS blip](2026-05-19-procrastinate-worker-died-on-dns-blip.md). What made **this** one a 61-hour outage instead of a self-healing blip is that the blip landed while jobs were in flight: Procrastinate's own connector raised, it began a graceful stop, and the graceful stop **waited on jobs that could not drain**. The wait is inside the library (`App.run_worker_async` → `run_tasks`), and the cancellation that would unstick it is swallowed by `psycopg_pool` on the async pool — so the worker **cannot be unstuck in-process**.

### Why every existing defense missed it

| Defense | Why it didn't fire |
|---|---|
| `_supervised_worker` auto-restart | Only restarts on `return` / `Exception` from `run_worker_async`. A **hang** is neither. |
| `db_watchdog` (2026-08-10) | Probes the **database**. The DB recovered in seconds; probes were healthy; correctly did nothing. It never watches the **worker**. |
| `/health/worker` 503 | Railway consults `healthcheckPath` at **deploy cutover only**, never to restart a live container (`railway.toml`). `ON_FAILURE` triggers on process **exit**; a hung process never exits. |
| Ticket [`wdwb1cbqxe`] shutdown-await fix | That fix bounds the *shutdown* `await`. **No shutdown ran here** — no SIGTERM/deploy. It would not have caught this. |
| The `install_signal_handlers=False` + "loud restart on normal return" fix (on `feat/e7-phase3-discovery`, not yet on `main`) | Also only converts a *normal return* into a restart. A **hang** never returns. It would not have caught this either. |

The common thread: everything reasoned about a worker that **stops** (returns/raises/exits) or a **database** that's unreachable. Nothing reasoned about a worker that is **alive-but-not-advancing** while the DB is fine.

## The fix

**Primary — a worker-liveness watchdog (`services/worker_watchdog.py`).** A daemon thread, modeled on `db_watchdog`, that periodically reads `MAX(worker_heartbeats.at)` on a fresh connection and exits the process (`os._exit(75)`, so Railway `ON_FAILURE` restarts a fresh container) when the heartbeat is stale past a bounded budget **while the database is reachable**. This is the exact hole: a wedged executor stops advancing the heartbeat, and a process restart is the only reliable recovery from an un-cancellable hung coroutine.

Design points that matter:

- **Liveness signal is `worker_heartbeats.at`, deliberately NOT `procrastinate_events`.** The periodic deferrer keeps writing `deferred` events even with a dead executor — which is exactly why event freshness stayed green for all 61 h. `worker_heartbeats.at` advances *only* when the worker **executes** the `worker_heartbeat` task, so its staleness is the true "is the executor alive" signal. (`/health/worker` already checks both; the heartbeat half is what tripped 503 here.)
- **DB-unreachable is inconclusive, not a verdict.** If the watchdog can't read the heartbeat (DB down / read times out / no rows yet), it does **not** exit — a sustained DB outage is `db_watchdog`'s responsibility. This watchdog only fires on "heartbeat stale **and** DB reachable" = worker wedged. The two watchdogs partition the failure space cleanly.
- **Boot-safe.** After a restart the pre-restart (stale) heartbeat rows are still present (`cleanup_heartbeats` is itself a worker task, so a dead worker never prunes them), so `MAX(at)` reads stale immediately. A `startup_grace` window ignores that leftover until the freshly-started worker has had a fair chance to write its first beat — long enough for a healthy worker to beat, short enough that a worker that never starts still trips.
- **Trigger-agnostic.** It recovers from *any* cause of a wedged worker — this DB-error hang, the ticket's shutdown-SIGTERM hang, and any future unknown wedge.

Budgets (all env-tunable, `WORKER_WATCHDOG_*`): probe every 60 s, `stale_after` 15 min (= 3 missed 5-min beats, a margin over a legitimately busy worker whose jobs are capped at 120 s), a 2-min sustain window, 10-min startup grace. Worst-case detection ≈ 17 min vs. the 61 h (∞) this time.

**Secondary — bound the shutdown `await` (`main.py`).** The lifespan shutdown previously did a bare `await worker_task` after cancelling it; a wedged worker that swallows the cancellation would hang the whole shutdown until Railway SIGKILLs the container mid-work (ticket `wdwb1cbqxe`). It is now `asyncio.wait_for(..., 15 s)` with a loud ERROR on timeout, so `close_async` / `close_pool` / `shutdown_posthog` are always reached. This closes the *shutdown-path* variant of the same class; the watchdog is the backstop for a wedge even this can't unstick.

### Why not fix it "deeper"?

- **Can't cancel the hang in-process.** `psycopg_pool` consumes `CancelledError` on the async pool (see ticket `wdwb1cbqxe`), so the wedged coroutine can't be cancelled. A process restart is the only reliable recovery. This is the same conclusion `db_watchdog` reached for the DB-freeze case.
- **Can't catch the `ConnectorException`.** It's raised on Procrastinate's *internal* main coroutine and consumed by its graceful-stop path; `run_worker_async` doesn't re-raise it — it hangs. There is nothing for `_supervised_worker` to catch.
- **Upstream `psycopg_pool` `CLIENT_EXCEPTIONS` including `CancelledError`** is the true library-level defect and is worth a separate upstream investigation (noted in ticket `wdwb1cbqxe`), but it is third-party and out of scope for restoring prod.

## Regression analysis — does recovery close jobs too early?

**No.** The watchdog changes **zero** scrape/close logic — it only restarts the process. Job closures happen solely through the incremental lifecycle in `scripts/shared/incremental.py`, which this PR does not touch, and which is guarded:

- **Closure needs `MISSED_RUN_THRESHOLD = 2` *consecutive* missed runs** (`incremental.py:72`). After recovery, the first resumed run **re-sees** every still-open job and **resets** its miss counter to 0; only a job that's genuinely gone gets missed, and even then it closes one run later (~30 min), never on the first run back.
- **Miss counting is per-run, not per-time**, so the 61-hour gap can't spuriously close anything — no runs happened during the outage, so no misses were counted.
- **Mass-closure guards** skip the close phase entirely if a board returns abnormally low counts: `empty_scrape` (`jobs_seen < 0.10 × active`) and `partial_scrape` (`jobs_seen < 0.85 × active` AND `≥15` missing) (`incremental.py:24-33,89`), with bounded auto-release.

A **closure burst in the first ~1–2 hours after recovery is expected and correct** — 61 hours of real board churn finally gets noticed — but it is bounded by the guards above, and it is a property of *recovering after 61 h* (true of any restart: manual, deploy, or watchdog), not of this change. Interrupting an in-flight fetch (on the bounded shutdown or a watchdog restart) closes nothing either: a killed fetch writes no `scrape_runs` row and never reaches the close-detection phase.

The only new behavior the watchdog can cause is a **process restart** when the worker is genuinely wedged — strictly better than a silent 61-hour outage, loud in Railway's restart history, and gated by `restartPolicyMaxRetries = 50`. It fires only when the heartbeat is stale for ~17 min **with the DB reachable**.

**False-positive during the recovery drain — the one real risk, now closed.** The worker fetches jobs `ORDER BY priority DESC, id ASC` (pure FIFO within a priority). Once the ~745 backlogged `worker_heartbeat` jobs drain, the *next* heartbeat is enqueued with a higher `id` than the per-company fetches a fan-out just enqueued — so at default priority it would queue **behind the entire fetch backlog**, and `MAX(worker_heartbeats.at)` would freeze until the fetches drained, even on a perfectly healthy worker. Measured against prod that drain is ~128 fetches × ~7.8 s avg / concurrency 5 ≈ **~3.5 min** — comfortably inside the ~17-min budget, but the margin drifts with scale (more custom companies → more fetches). So `worker_heartbeat` is now deferred at **`priority=9`** (`tasks/heartbeat.py`), which makes `fetch_job` pick it ahead of any fetch regardless of `id`: the beat always runs on schedule and the starvation window closes structurally, not just probabilistically. (The 745 *backlogged* beats were deferred before this change at priority 0, but they drain in the first ~1–2 min regardless, and steady-state is what the priority protects.)

## Recovery & verification

Recovery is a deploy/restart of the Railway backend; the fix in this PR makes it **automatic** thereafter. Post-recovery acceptance criteria (all validated against prod):

1. `/health/worker` → **200** (heartbeat + events both fresh).
2. `worker_heartbeats.at` advancing (fresh row every ~5 min).
3. `procrastinate_jobs` `todo` backlog **draining** toward steady state.
4. `scrape_runs` accruing again across all **133** companies (not just the 5 script scrapers).
5. **New jobs land** from the ATS scrapers (`new_jobs > 0` / recent `first_seen_at` for greenhouse/ashby/lever/gem/eightfold/workday source_ids).
6. Closure burst stays inside the `< 0.1 × active` guard — no mass closure.

Verification SQL:

```sql
-- worker alive again
SELECT max(at) AS last_beat, now() - max(at) AS age FROM worker_heartbeats;
-- queue draining
SELECT status, count(*) FROM procrastinate_jobs GROUP BY status ORDER BY status;
-- all 133 companies scraping again, with fresh jobs
SELECT (started_at::timestamptz)::date AS day, count(*) runs,
       count(distinct company) companies, sum(new_jobs) new_jobs
FROM scrape_runs
WHERE started_at::timestamptz > now() - interval '2 hours'
GROUP BY 1;
-- zombie doing rows must not grow per deploy
SELECT id, task_name, queue_name FROM procrastinate_jobs WHERE status='doing' ORDER BY id;
```

The container should log `Shutdown complete` before it goes away on a deploy (it did not, on the wedged shutdown path this PR fixes).

## Follow-ups (separate tickets)

- **Stalled-job reaper** — requeue/fail-out `doing` rows with no recent `procrastinate_events`, and clear the 8–9 existing `doing` zombies (3 date back to 2026-06-14). Named "Phase 2" at `claim_custom_companies.py:102`; out of scope here (ticket `wdwb1cbqxe`).
- **Port the `install_signal_handlers=False` + loud-restart-on-return work** from `feat/e7-phase3-discovery` to `main` when the E7 stack merges — it hardens the *shutdown-signal* and *normal-return* variants; this watchdog is the liveness backstop underneath all of them.
- **Upstream `psycopg_pool` `CLIENT_EXCEPTIONS`** — investigate whether the async pool swallowing `CancelledError` is a known/fixed upstream bug (ticket `wdwb1cbqxe`).
