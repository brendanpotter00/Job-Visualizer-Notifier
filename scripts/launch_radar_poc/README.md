# Launch Radar POC (Parallel API)

The main script is `poc.py`; `pedigree_group.py` (pedigree via a Task Group) and `team_stats.py` (the team tally, two approaches) are follow-up experiments that import from it. `poc.py` has PEP 723 inline deps (`parallel-web>=1.3.5`, `httpx`), so nothing needs installing. The SDK reads the key from `PARALLEL_API_KEY`, and the script never prints it. Run every command from the repo root:

```bash
zsh -ic 'cd <repo> && uv run scripts/launch_radar_poc/poc.py <subcommand> ...'
```

Every create call is made with `max_retries=0`, so a retry can't create a second billed run. Before each billable call the script estimates its cost from the pricing page, rounds it up, and checks it against `--budget`.

| Subcommand | What it does | Writes |
| - | - | - |
| `monitor-create [--processor lite\|base] [--frequency 1d]` | Creates an `event_stream` monitor for seed/Series A+ funding and AI product launches, with `include_backfill=true` and a flat 9-field JSON schema. It refuses to create a second monitor while one is still active. | `out/monitor/01-monitor-create.{request,response}.json`, `state.json`, `calls.json`, `spend.json` |
| `monitor-events [--max-wait 480]` | Polls `GET events` with `include_completions` (free) until rows arrive. It narrows rows to `MonitorEventStreamEvent`, parses the content defensively, drops big tech, and ranks the rest: Series A > seed > other funding > launch. | `out/monitor/02-monitor-events.response.json`, `out/monitor/candidates.json` |
| `monitor-cancel` | Cancels the monitor, then re-retrieves it. It exits non-zero if the status is not `cancelled`. Run this at the end every time. | `out/monitor/03-monitor-cancel.response.json`, `04-monitor-retrieve.response.json` |
| `run-company --name --domain --out DIR --budget USD` | Runs the whole pipeline (steps below). It can be resumed: ids saved in `DIR/state.json` are reused, never re-created. | `DIR/01-findall.*`, `02-enrich.*`, `03-brief.*`, `04-ats-*.json`, `calls.json`, `spend.json`, `card.json` |
| `dedupe --candidates FILE [--dry-run]` | Normalizes domains (lowercase, strips scheme, `www.`, path and port) and checks each one against `out/seen.json`. It posts the new ones and rejects repeats. | `out/seen.json` |

## `run-company` steps

1. **Leadership.** One FindAll run with `entity_type=people`, generator `preview` (flat $0.10) and `match_limit` 8, plus one match condition naming the company and its domain. If preview matches fewer than `--min-leaders` (2), the script falls back to a single `base` run.
2. **Pedigree.** `findall.enrich` with processor `core` ($0.025 per matched leader) and a schema covering education, prior roles, earlier companies founded and their outcomes, years of experience and notable signals. The script waits until every matched leader has every enrichment key.
3. **Company brief.** One Task run on `core` ($0.025). It is created at the same time as FindAll so the two run in parallel.
4. **ATS check.** Calls the free public API of Greenhouse, Ashby or Lever with the board token from the brief (or one parsed out of the careers URL). `pr_ready` is true only if the API answers 200 with at least one job.
5. **Scoring.** Done locally with a deterministic rubric, `VC_TIERS` and `TALENT_RUBRIC`. Each signal is weighted by its basis confidence, and every point awarded comes with a reason string.
6. **Card.** Writes `card.json`.

## Costs seen (2026-10-06/07)

| Call | Est. cost | Latency |
| - | - | - |
| Monitor, lite, 1 execution (0 events) | $0.003 | first run finished in ~19 s |
| Monitor, base, 1 execution (1 event) | $0.010 | event visible in ~60 s |
| FindAll preview, Raindrop leadership (3/5 matched) | $0.100 | 154 s |
| FindAll enrich, core × 3 leaders | $0.075 | 124 s |
| Task brief, core | $0.025 | 278 s (in parallel with the above) |
| ATS check, Ashby `Raindrop`: 9 jobs | free | <1 s |
| **Raindrop total** | **$0.20** | about 5 min wall clock |
