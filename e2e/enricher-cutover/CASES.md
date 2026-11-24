# Enricher cutover — case table

The contract `.claude/skills/e2e-gate/sections/enricher-cutover.md` reads. `PLAN.md` carries
the reasoning (how each failure is induced: §3); this is the quick reference + the status.

**Last real runs: 2026-11-23, `feat/consolidate-enricher`, this Mac (Apple silicon, uv 0.11.14).**

| Run | Collected | Result | Measured |
|---|---|---|---|
| `e2e/run.sh enricher-cutover` | 31 + the isolation check | **32 PASS / 0 FAIL / 0 BLOCKED — GREEN** (after the self-review's CO-18 / CO-19 / WT-07; before them, 3 consecutive full runs of 28 + isolation were green; one earlier run's isolation check flagged a third-party LaunchAgent, now out of scope, PLAN §4) | **~195–200 s** |
| `e2e/run.sh enricher-cutover --fast` | 10 + the isolation check | **11 PASS — GREEN** | **28 s** |
| M1 / M2 mutations (PLAN §6) | CO-02 ×2 / CO-07 (+ CO-08) | **RED, as they must be** | |
| The pre-review scripts (`E2E_CUTOVER_SRC`) | CO-18 / CO-19 / WT-07 | **RED, as they must be** (CO-19 rolled a healthy cutover back at the hard cap; CO-18 never skipped the dead tick; WT-07 exited on the failed fetch) | |

Per case: a happy-path cutover against the fake enricher takes ~5–7 s (1 s ticks, a 1 s
fire interval); the slow ones wait for real ticks (CO-02 a 6 s tick, CO-03 a 3 s park
budget, CO-17 an 8 s hard cap). CO-REAL is ~7 s with a warm uv cache.

**Cost: $0 and no network, with no flag that changes that.** No `BLOCKED` state exists here:
there is no third party to be blocked by.

## Case table

| ID | Proves | Marker | Status |
|---|---|---|---|
| **CO-01** | Happy path through the WATCHER: merged main → park → online backup → untracked copy → health equality → plist swap (exactly the two paths) → load → first tick `ok` → retire (markers, bundle, banner, archive) → one text → `DONE`; the new worker keeps ticking | — | 🟢 |
| **CO-02** | Never unloads mid-tick — with the stub's unload killing a running job, and leaving it | — | 🟢 2/2 |
| **CO-03** | Wedged tick → exit 10, nothing touched, the tick's lock left alone, ONE text; after it ends the rerun completes | — | 🟢 |
| **CO-04** | No JVN ref carries prod's tree → refuse (20), nothing touched, never parked | fast | 🟢 |
| **CO-05** | A tracked change in old prod → refuse (20); the change is left as it was | fast | 🟢 |
| **CO-06** | No `enricher-prod-*` tag → the history walk finds the commit → `DONE` | — | 🟢 |
| **CO-07** | First tick `error` → rollback WITH the DB copy-back (the new tick is in the old DB, `pre-rollback-*` kept), original plist bytes, old worker runs again, exit 30, one text; the watcher retires | — | 🟢 |
| **CO-08** | First tick never starts → rollback WITHOUT a copy-back | — | 🟢 |
| **CO-09** | SIGKILL before the plist write → rerun redoes A–C, deleting only the owned dir; SIGKILL after it → rerun continues and never re-copies | — | 🟢 2/2 |
| **CO-10** | The interpreter `pyvenv.cfg` names is gone → refuse in phase A, never parked | fast | 🟢 |
| **CO-11** | `--preflight` (human + `--json`) is read-only: HOME, both remotes, TMPDIR byte-identical; no state dir; launchd saw only `list`/`print`; every check ok | fast | 🟢 (after a fix: §"Found") |
| **CO-12** | `gh`, the banner push and `send.sh` all fail → still `DONE`; each failure recorded + logged | — | 🟢 |
| **CO-13** | An orphaned lock (dead pid; the worker itself waits 3 h on it) is reclaimed | — | 🟢 |
| **CO-14** | `.env.local` byte- and mode-identical; the canary in no output/log/state/text/file/history | — | 🟢 |
| **CO-15** | `--run` after `DONE` is a no-op; `--status` prints the state; the watcher retires itself | — | 🟢 |
| **CO-16** | An unfaithful copy (the old DB moved during the backup) → unpark exactly as found, refuse (20) | — | 🟢 |
| **CO-17** | *(added)* A first tick that never ends: E extends while it progresses, then the hard cap; the rollback TERMs the python stage only and still copies the DB back | — | 🟢 |
| **CO-18** | *(added)* A power loss mid first tick: cutover + tick SIGKILLed, the tick's lock and `started_at` back-dated before the boot; the resumed run skips the dead tick (boot rule), judges the next → `DONE` | — | 🟢 |
| **CO-19** | *(added)* The first tick's wrapper alone SIGKILLed while the cutover waits; once the worker reclaims the lock (aged past 3 h), tick N+1 takes over (later-tick rule) → `DONE`, no rollback | — | 🟢 |
| **CO-REAL** | The real `enricher-prod-eeff1c9` tree: real `uv sync` (venv equivalence), real `cli health` equality, `DONE`; a missing tag FAILS | — | 🟢 |
| **WT-01** | `main` without `cutover.py` → `not merged yet`, mirror built, nothing else | fast | 🟢 |
| **WT-02** | Refused transport (no mirror) / vanished remote (mirror exists) → exit 0, `retry next interval`, no state | fast | 🟢 |
| **WT-03** | Merged → runs MAIN's (marked) `cutover.sh` from `$STATE/run/<sha>/`, with `lib/`; the lock passes through `exec` | fast | 🟢 |
| **WT-04** | A second watcher exits at once while the first runs | — | 🟢 |
| **WT-05** | `DONE` / `FAILED` / `ROLLED_BACK` → plist to `retired/`, `launchctl remove`, no fetch, no cutover | fast | 🟢 3/3 |
| **WT-06** | *(added)* `install_watcher.sh`: `--dry-run` writes nothing; install copies + loads, the `RunAtLoad` fire runs it; refuses after `DONE` | — | 🟢 |
| **WT-07** | *(added)* JVN unreachable while a cutover is mid-flight (killed right after the plist switch, no worker loaded) → resumed from the last fetched `main` → `DONE`; the cutover dropped the watcher's lock | — | 🟢 |
| isolation | the real `com.bp.*` LaunchAgents, cutover state dir and `~/developer/personal/{app,job-enricher,enricher-prod}` unchanged by the run | always | 🟢 |

## Corrections to the design table (consolidation PLAN §5), found while building

* **CO-16's mechanism.** The plan suggested "a PATH-stubbed backup that drops rows, or a
  `.backup` target pre-seeded wrong". Neither can work: the backup is Python's in-process
  `sqlite3` API (no PATH lookup), and `online_backup` unlinks the target and its sidecars
  first. The case instead keeps the old DB MOVING during the backup (a writer started by a
  `git` stub at phase C's untracked scan — a process ignoring the tick lock, e.g. a CLI run
  by hand), which is exactly what the count check exists to catch.
* **CO-09's kill points.** "Killed after the copy, before the plist write" is a SIGKILL from
  a `plutil` stub on phase D's lint (the last call before the write); "killed after the swap"
  is a SIGKILL from the `launchctl` stub when asked to load the new plist.
* **CO-REAL's first tick** is not the real wrapper (it hardcodes `/opt/homebrew/bin/uv`, which
  CI lacks, and would call JVN and ollama) but the real CLI's tick-acquire / lock hand-over /
  tick-end, run by the stub launchd in place of the program.
* **CO-17 and WT-06 are additions.** Unit 3 listed the close-deadline extension, the hard cap
  and the rollback's wedged-tick path as never exercised; and the orchestrator will run
  `install_watcher.sh` for real. **CO-18, CO-19 and WT-07** came from the self-review
  ("Found and fixed" below).

## Found and fixed

| Finding | Where | Fix |
|---|---|---|
| `--preflight` left `enricher.db-wal` (empty) and `enricher.db-shm` in prod's `data/` when the DB was idle: a `mode=ro` reader of a WAL database creates them | `cutover.py` `connect_ro` (preflight's DB checks) | read `immutable=1` when no `-wal` exists (`quiescent_immutable`); unit test in `tests/test_cutover_untracked.py`. CO-11 was red before, green after |
| The isolation fingerprint flagged a Creative Cloud agent rewriting its own plist mid-run | `real_manifest.py` | scoped to `com.bp.*` |
| *(self-review)* Once the real watcher is installed it fires every 5 min — longer than a run takes — so its appended log line and refreshed `jvn.git` mirror would read as an ISOLATION BREACH on a green run | `real_manifest.py` | the watcher's logs are fingerprinted by existence, and its own `jvn.git` / `run/` / `watcher.lock` are excluded from the state-dir hash (`state.json` still is not) |
| *(self-review)* A first tick left `running` by a reboot / SIGKILL was waited on into the 24 h hard cap, then a healthy cutover rolled back | `cutover.py` phase E | skip an orphaned tick (a later tick exists, or it started before this boot) and judge the next; CO-18, CO-19 |
| *(self-review)* The "old prod DB changed" tripwire hashed bytes; a `cli init` there (same-value `user_version`) rewrote the header | `cutover.py` phase E | compare a content snapshot taken in phase C; unit tests |
| *(self-review)* Venv equivalence read `pyvenv.cfg`'s `version_info`, which goes stale after a `uv python upgrade` | `cutover.py` phase A | ask each venv's `bin/python`; CO-REAL + unit test |
| *(self-review)* The watcher exited on a failed fetch even mid-rollback / after the swap | `watcher.sh` | resume `PARKED`…`SWAPPED`/`ROLLING_BACK` from the last fetched `main`; WT-07 |
| `--case CO-07` also ran CO-08 (`pytest -k` matches module names) | module names | modules holding several cases carry no case id |

## Behaviours observed and pinned (pre-existing, not changed here)

| Observation | Why it matters |
|---|---|
| A wrapper SIGTERMed by `launchctl unload` still runs its EXIT trap and clears its own lock (macOS `/bin/sh` runs EXIT traps on SIGTERM) | An unload mid-tick loses the tick's work but does not orphan the lock; only a SIGKILL / power loss does (CO-13) |
| `--rehearse`'s online backup of an idle live DB still creates `-wal`/`-shm` beside it | Harmless (SQLite's own reader files, created by the worker on every tick); `--rehearse` is documented as taking a shared lock for the backup |
| `watcher.sh` hands `watcher.lock` to the cutover through `exec` (same pid) | The cutover removes it on exit (CO-01, WT-07); before the self-review it stayed until a fire found the pid dead, so a recycled pid could block the watcher until a reboot |
