# /enrich-tick-once — headless single cycle (no self-scheduling)

Identical to `/enrich-tick` **Steps 0–6.5**, but:
- **Omit Step 7** (`ScheduleWakeup`) — launchd (`StartInterval`) owns cadence.
- Use **absolute paths** for `uv`/project (`/opt/homebrew/bin/uv`, `PROJECT=/Users/bpotter/developer/personal/job-enricher`).
- The wrapper (`scripts/enrich_tick_wrapper.sh`) has already run `tick-acquire`, `pull`, and `clean` before invoking `claude -p /enrich-tick-once`, so you begin at **Step 3 (classify)**. If the wrapper indicates the lock was held (exit 75), do nothing.
- The wrapper exports `ENRICH_TICK_ID` (the acquired tick id) and `ENRICH_LOCK_OWNER_PID`; `tick-end` reads both from the environment, so you may omit `--tick-id` — the stray-tick-end guard still applies.
- The wrapper also runs `metrics-push` itself after this command exits (even on timeout), so Step 6.5 is optional here — running it twice is harmless (idempotent on the tick uuid).

Follow enrich-tick.md Steps 3, 4, 5, 6 exactly (classify fan-out with `subagent_type: "classifier"` -> judge fan-out with `subagent_type: "judge"` -> write-back -> tick-end). Record results between waves. Do not schedule a wakeup.

Steps 3 and 4 use the **chunk-file handoff**: `classify-queue` / `judge-queue` print only a small `[{chunk_file, count}]` manifest and write the actual job text to files under `data/chunks/` (stale ones are deleted server-side first). Fan out one Agent per manifest entry in waves of up to `CLASSIFY_FAN_OUT`, passing each entry's `chunk_file` path into the CLASSIFY/JUDGE PROMPT from enrich-tick.md — the sub-agent Reads the file itself. **Never Read a chunk file into your own context**: this headless run must survive a 60-job tick without compaction, and the manifest keeps all job text out of your transcript.
