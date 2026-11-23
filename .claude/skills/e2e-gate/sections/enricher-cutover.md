# Enricher cutover — e2e gate runbook

Design + reasoning: `e2e/enricher-cutover/PLAN.md`. Live case status and what each case
found: `e2e/enricher-cutover/CASES.md`. This file is the "sub-skill": how to run it, what
each case proves, what to look at first when it goes red.

## Run it

```bash
e2e/run.sh enricher-cutover               # full gate, measured ~3.3 min
e2e/run.sh enricher-cutover --fast        # refusals, preflight, watcher no-ops (28 s)
e2e/run.sh enricher-cutover --case CO-07  # one case (CO-REAL -> coreal, WT-05 -> its 3 phases)
e2e/run.sh enricher-cutover --keep        # keep the sandboxes for a fix loop
```

**Cost: $0, unconditionally, and no network.** No stack, no ports, no Postgres, no LLM.
Every case builds its own throwaway "machine" (fake `HOME`, fake old prod + old dev git
checkouts, a local bare repo standing in for GitHub JVN, a stub launchd) and runs the REAL
`src/enricher/scripts/cutover/` scripts against it. Remotes are local paths and git refuses
any other transport (`GIT_ALLOW_PROTOCOL=file`); uv runs offline from the real cache;
`launchctl`, `gh` and `send.sh` are stubs. `run.sh` fingerprints the real
`~/Library/LaunchAgents`, the real cutover state dir and `~/developer/personal/{app,
job-enricher,enricher-prod}` before and after, and fails the run on any difference
(**ISOLATION BREACH**).

It runs in GitHub CI too (the `enricher` job, macOS). It has its own run lock, so it runs
alongside every other section.

## When to run this gate

Before claiming "ready to test" on anything touching:

- `src/enricher/scripts/cutover/` (any file) or `src/enricher/scripts/lib/park_worker.py`
- the enricher's lock, tick lifecycle or `cli health` shape (`lock.py`, `cli.py`
  `tick-acquire`/`tick-end`/`health`, `scripts/enrich_tick_wrapper.sh`) — the cutover's
  contract with the enricher (`scripts/cutover/README.md`, "Contract with the enricher");
  change `e2e/enricher-cutover/fixtures/fake_enricher/` with it
- before the orchestrator installs the watcher, and before merging the PR that carries it

## Files this suite does NOT own — report bugs there, don't fix them here

`src/enricher/scripts/cutover/` and `scripts/lib/park_worker.py`. If a case fails because
of a bug there, the case is doing its job — report it; never bend the test.

## Per-case reference

| ID | Proves | First thing to check on red |
|---|---|---|
| **CO-01** | Happy path through the WATCHER: merged main → park → backup → copy → health equality → plist swap (byte diff = exactly the two paths) → load → first tick ok → retire (markers, bundle, banner pushed, `gh repo archive`) → one text → `DONE`; the new worker keeps ticking | `cases/test_happy_path-shared-sandbox/runs.txt` (watcher + cutover output) and its `state.json` (CO-01/14/15 share that sandbox) |
| **CO-02** | Never unloads mid-tick, with the stub's unload killing a running job and with it leaving it | `launchctl-calls.jsonl` (the unload's time, `job_running`, `lock`) vs `launchd-jobs.jsonl` (the in-flight wrapper's end) |
| **CO-03** | Wedged tick: exit 10, nothing touched, one text; the next run completes | `runs.txt` run 1 (`park budget exhausted`), `texts.log` |
| **CO-04** / **CO-05** | No matching JVN ref / a tracked change in old prod → refuse, exit 20, nothing touched | `state.json` `failed_reason` |
| **CO-06** | No tag → the history walk finds the commit | `state.json` `ref_source` |
| **CO-07** | First tick `error` → rollback WITH the DB copy-back, plist bytes restored, old worker runs again, the watcher retires | `cutover.log` `ROLLBACK` lines; `old-prod-enricher.db` (has the new tick?) |
| **CO-08** | First tick never starts → rollback WITHOUT a copy-back | `runs.txt` (`no copy-back needed`) |
| **CO-09** | SIGKILL before the plist write → redo A–C; after it → continue, never re-copy | `runs.txt` run 2's `start: ... -> redo` / `-> continue_swap` |
| **CO-10** | `pyvenv.cfg`'s interpreter missing → refuse in phase A, never parked | `state.json` `failed_reason` |
| **CO-11** | `--preflight` writes nothing (HOME, both remotes, TMPDIR hashed before/after; no state dir) and launchd only sees `list`/`print` | the assertion names the changed paths |
| **CO-12** | `gh`, the banner push and `send.sh` all fail → still `DONE`, each failure logged | `cutover.log` `F:` lines |
| **CO-13** | An orphaned tick lock (dead pid) is reclaimed | `runs.txt` (`reclaimed an orphaned lock`) |
| **CO-14** | `.env.local` arrives byte- and mode-identical; the canary is in no output, log, state, text or other file | the assertion lists the leaking files |
| **CO-15** | `--run` after `DONE` is a no-op; the watcher then retires itself | `runs.txt` (`-> noop_done`) |
| **CO-16** | An unfaithful copy (a rogue writer moves the old DB during the backup) → unpark exactly as found, exit 20 | `state.json` `failed_reason`; `launchctl-calls.jsonl` (unload then load of the OLD plist) |
| **CO-17** | A first tick that never ends: E extends while it progresses, then the hard cap; the rollback TERMs only the python stage and still copies the DB back | `cutover.log` (`still progressing`, `TERM python stage pid(s)`) |
| **CO-18** | A power loss mid first tick (cutover + tick SIGKILLed, the tick's lock and `started_at` back-dated before the boot): the resumed run skips the dead tick and judges the next → `DONE` | `state.json` `orphaned_first_ticks` + history (`orphaned (it started before the current boot)`) |
| **CO-19** | The first tick's wrapper alone SIGKILLed while the cutover waits: once the worker reclaims the lock, tick N+1 takes over → `DONE`, no rollback | `cutover.log` (`can never close (tick #N+1 started after it`) |
| **CO-REAL** | The real `enricher-prod-eeff1c9` tree as old prod: real `uv sync` venv equivalence + real `cli health` equality, then `DONE` | a missing tag FAILS with the fix (`git fetch --tags`; CI needs `fetch-depth: 0` and the pushed tag) |
| **WT-01** | `main` without `cutover.py` → `not merged yet`, nothing else | `runs.txt` |
| **WT-02** | Refused transport (no mirror) and a vanished remote (mirror exists) → exit 0, `retry next interval` | `runs.txt` |
| **WT-03** | Merged → runs main's MARKED `cutover.sh` from `$STATE/run/<sha>/`, hands its lock over through `exec` | `marker.txt` in the sandbox (`--keep`) |
| **WT-04** | A second watcher exits at once while the first runs | `runs.txt` |
| **WT-05** | `DONE`/`FAILED`/`ROLLED_BACK` → plist moved to `retired/`, `launchctl remove`, no fetch | `launchctl-calls.jsonl` |
| **WT-06** | `install_watcher.sh`: `--dry-run` writes nothing; install copies + loads and the `RunAtLoad` fire runs; refuses after `DONE` | `watcher-launchd.log` |
| **WT-07** | JVN unreachable while a cutover is mid-flight (killed right after the plist switch, no worker loaded) → the watcher resumes it from the last fetched `main` → `DONE`; the cutover drops the watcher's lock | `runs.txt` (`resuming it from the last fetched main`) |

## Reading a red

`e2e/enricher-cutover/artifacts/<run>/summary.md` first, then `cases/<test>/step.txt` (the
step that failed, in words), then `cases/<test>/sandbox/`: `runs.txt` (every cutover /
watcher run's stdout + stderr), `state.json`, `cutover.log`, `launchctl-calls.jsonl`,
`launchd-jobs.jsonl`, `fake-enricher-events.jsonl` (acquire / skip / end / killed per tick),
`texts.log`, `gh.log`, and both DBs. `.env.local` is never copied out.

**Failure modes that are NOT cutover regressions:**

| Symptom | Cause | Fix |
|---|---|---|
| `no uv-managed Python 3.12` at session start | uv manages no 3.12 (a system one does not count: prod's venv is built on a managed one) | `uv python install 3.12` (CI does this before the section) |
| CO-REAL: `tag enricher-prod-eeff1c9 is not in this checkout` | tags not fetched / not pushed | `git fetch --tags origin`; push the tag |
| CO-REAL: `uv sync` fails offline | the uv cache lacks the enricher's wheels | run `cd src/enricher && uv sync` once (online), then re-run |
| `ISOLATION BREACH` naming `app/` files under a path the live worker writes | the live worker wrote somewhere `real_manifest.py` does not exclude | read the diff; only `data/`, `.venv/`, `__pycache__/` are excluded |
| `REFUSING TO START — another enricher-cutover run` | a second copy of this section | wait for it |

## Known non-coverage

Real launchd (the stub models `StartInterval`, `RunAtLoad`, unload with and without killing
a job, and a launchd-like environment — not launchd itself), real GitHub (the banner push and
`gh repo archive` against the private repo), a real text, a real multi-hour tick and a real
laptop sleep (the sleep-gap credit is unit-tested with injected clocks), and the rollback's
wedged-tick force path (TERM the python stage, then the wrapper). Details: `PLAN.md` §7.
