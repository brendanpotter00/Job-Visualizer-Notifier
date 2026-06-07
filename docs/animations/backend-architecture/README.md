# Backend Architecture Animations

[Remotion](https://www.remotion.dev/) animations of the Job Posting Analytics backend.

## `CombinedPipelines` (primary) — 43s seamless loop

`IngestionPipeline` + `WebscraperPipeline` back to back in one file. Both segments
start and end idle, so the cut between them and the loop wrap are clean.

Individual compositions:

## `IngestionPipeline` (primary) — 18s seamless loop, no title

Workflow-style walkthrough of one Procrastinate scrape cycle, mirroring the real code
in `src/backend/api/tasks/`:

1. **Cron tick** — the periodic deferrer (`*/30 * * * *`, in-process) defers a fan-out task
2. **Fan-out** — the task reads `companies` and defers one `fetch_<ats>_company` job per
   enabled company into `procrastinate_jobs` (the queue lives in Postgres)
3. **Claim** — 5 concurrent worker slots (`concurrency=5`) pull jobs off the queue; the
   6th job visibly waits in the queue until a worker frees up (backpressure)
4. **Fetch** — each worker hits its ATS public API (Greenhouse, Ashby, Lever, Gem,
   Eightfold, Workday)
5. **Upsert** — results land in `job_listings` + `scrape_runs`; a heartbeat task blips
   late in the cycle
6. **Retry** — the greenhouse fetch errors on attempt 1, re-queues with exponential
   backoff, and succeeds on attempt 2 from a different worker
   (`RetryStrategy(max_attempts=5, exponential_wait=2)`)

Verified against production (Railway logs + prod Postgres, 2026-06-06): worker startup
log confirms the 7 queues and `concurrency=5`; chip multipliers (`ashby ×52`,
`greenhouse ×47`, …, 117 enabled companies total) come from the live `companies` table;
the retry scene mirrors real failed→retried rows in `procrastinate_jobs`.

Frame 539 flows back into frame 0, so the MP4 loops cleanly.

## `WebscraperPipeline` — 25s seamless loop

Companion loop for the other ingestion path: the hourly Playwright scrapers
(`auto_scraper.py` + `scraper_runner.py`):

1. **Wake** — the auto-scraper asyncio task (inside the API process) wakes every 1h
2. **Lock** — acquires the shared `scraper_lock`; scrapes are strictly serial
3. **Spawn** — `run_scraper.py --company X --incremental --headless` child process
4. **Paginate** — headless Chromium walks the career site (live page/jobs-seen counters)
5. **Upsert** — writes `job_listings`, records a `scrape_runs` row, releases the lock

A watchdog card tracks elapsed time against the 90-min kill timeout. Per-company stats
(Google ~748 jobs · ~5 min, Apple ~3,766 · ~22 min, Microsoft ~307 · ~2 min) are 48h
averages from prod `scrape_runs`.

## `BackendArchitecture` — 38s overview

Full-system tour including the React SPA → Vercel proxies → FastAPI serving path and the
Playwright scraper subprocesses (Google/Apple/Microsoft).

## Usage

```bash
npm install

# Live preview / iterate
npm run studio

# Render
npm run render             # → out/backend-pipelines.mp4 (combined 43s loop)
npm run render:ingestion   # → out/ingestion-pipeline.mp4 (queue pipeline only)
npm run render:webscraper  # → out/webscraper-pipeline.mp4 (Playwright pipeline only)
npm run render:overview    # → out/backend-architecture.mp4
```

## Editing

- `src/IngestionPipeline.tsx` — `LOOP_FRAMES` (loop length), `FETCHES` (claim
  frames / slot assignments), `FANOUT`/`SLOT_BUSY` (cycle schedule), `STEPS` (badges),
  layout constants at the top
- `src/BackendArchitecture.tsx` — `NODES`/`EDGES` geometry, `SHOW` reveal frames,
  `buildPackets()` loops, `CAPTIONS`
