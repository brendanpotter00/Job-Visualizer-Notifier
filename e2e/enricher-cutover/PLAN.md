# E2E gate — the enricher cutover (section `enricher-cutover`)

The design is `docs/implementations/enricher-consolidation/PLAN.md` §4 (the cutover) and §5
(this section). This file is how the section is built and why. Case status: `CASES.md`.
Runbook: `.claude/skills/e2e-gate/sections/enricher-cutover.md`.

## What this gates

`src/enricher/scripts/cutover/` — `cutover.sh`/`cutover.py` (moves the live enricher from
`~/developer/personal/app` to a JVN clone), `watcher.sh` (the launchd merge trigger that
runs the cutover from merged `main`) and `install_watcher.sh` — plus
`scripts/lib/park_worker.py`. They run **unattended** on Brendan's Mac after the merge, so
every path that matters (happy, refuse, defer, roll back, crash, resume) is exercised end to
end here, against the REAL scripts.

## 0. TL;DR

| | |
|---|---|
| Runs | `e2e/run.sh enricher-cutover` (full, ~3.3 min) · `--fast` (~28 s) · `--case CO-07` · `--keep` |
| Cases | CO-01..CO-19, CO-REAL, WT-01..WT-07 (31) + the isolation check (1) |
| Stack | **none** — no backend, no ports, no Postgres |
| Cost | **$0, unconditionally, and no network** |
| Where | locally **and** in GitHub CI (the `enricher` job, macOS) |
| Proven to bite | M1 (unload before park) → CO-02 red in both unload modes; M2 (skip the rollback copy-back) → CO-07 red (§6) |

## 1. The sandbox — one throwaway "machine" per case

`cutover_sandbox.Sandbox.build()` makes, under the case's tmp dir (run.sh points pytest's
`--basetemp` OUTSIDE the repo, at `$TMPDIR/jvn-e2e-<hash>/enricher-cutover/<run>/`):

| Piece | What it is |
|---|---|
| fake `HOME` | `Library/LaunchAgents/com.bp.job-enricher.plist` in the real plist's shape (same keys, `ProgramArguments` = the wrapper only, `StartInterval 60`, `RunAtLoad false`, logs in `~/Library/Logs`, `EnvironmentVariables.PATH`), `Library/Logs/`, and the stub `send.sh` at `~/.claude/skills/message-brendan/send.sh` |
| old prod | `$HOME/developer/personal/app`: a git repo whose tree is `fixtures/fake_enricher/` (+ a generated `CLAUDE.md`, so the JVN repo carries none under `e2e/`), `.venv` made by `uv sync --frozen --python <uv's 3.12>`, `cli init --seed-ticks 3`, `.env.local` holding a **canary** secret (mode 600), `.checkout-role=prod`, an untracked `data/classify-run-t1.log`; `origin` = the job-enricher remote |
| old dev | `$HOME/developer/personal/job-enricher`: a clone of that remote with one unported branch |
| job-enricher remote | a local bare repo (README + CLAUDE.md on `main`; accepts the banner push unless a case installs a rejecting hook) |
| JVN remote | a local bare repo: commit 1 has `src/enricher` = the old prod's tree, tagged `enricher-prod-fake0001` (unless the case says no tag), plus a non-matching tag the lookup must ignore; "merged" adds commit 2 with `src/enricher/scripts/{cutover,lib}` copied from the scripts under test |
| stubs | `bin/launchctl`, `bin/gh`, `send.sh`, and two crash/rogue hooks (§2) |

**The path knobs are left UNSET.** The cutover derives the old prod, new prod, old dev, state
dir, enricher plist and `send.sh` from `$HOME` (PLAN §4.2) — so every case also tests that a
fake `HOME` really sandboxes everything. Only what must never default to the real machine is
set: `JVN_REMOTE_URL` (a local path), `LAUNCHCTL`/`GH_BIN` (the stubs), `UV_BIN` (real uv),
`CUTOVER_OLD_REPO_SLUG`, and the budgets scaled from hours to seconds.

**Every process starts from a built env**, never the developer's: `HOME`/`USER`/`TMPDIR`
(sandbox), `PATH` = stubs first, `GIT_CONFIG_NOSYSTEM=1`, `GIT_ALLOW_PROTOCOL=file`,
`UV_OFFLINE=1` + `UV_PYTHON_DOWNLOADS=never` with the REAL `UV_CACHE_DIR` and
`UV_PYTHON_INSTALL_DIR` (a fake `HOME` would otherwise hide uv's cache and interpreters),
every proxy variable at a dead `127.0.0.1:9`. `Sandbox.check_isolation()` refuses to build if
`HOME`, any path knob, the remote, `LAUNCHCTL` or `GH_BIN` points outside the sandbox, if
`launchctl` on the sandbox `PATH` is not the stub, or if the no-network guards are off (it
caught its own ordering bug while this was built: the check ran before the stub existed).

**The scripts under test** are copied once per session from `src/enricher/scripts/{cutover,lib}`
(or from `$E2E_CUTOVER_SRC`, §6) into the basetemp, so the cutover's bytecode never lands in
the repo. CO-01 runs them the real way — the installed watcher extracts them from the fake
merged `main` — and the other cases call `cutover.sh` directly for precise control.

## 2. The fake enricher and the stubs

`fixtures/fake_enricher/` honours **exactly** the contract `scripts/cutover/README.md`
("Contract with the enricher") lists, and nothing else: `data/enricher.db` (WAL,
`user_version` 3: `ticks`, `meta`, `stage_timings`, `enrichments`), the `"<pid>|<iso>"`
O_EXCL lock with `lock.py`'s rules (live holder blocks; dead holder blocks until 3 h;
pre-boot lock reclaimed), `cli tick-acquire` exit 75 while held, `cli health` JSON with
volatile keys, and `scripts/enrich_tick_wrapper.sh` with the real wrapper's lock hand-over.
It is a zero-dependency, non-package uv project, so `uv sync --frozen` needs no network and
no build backend. Behaviour per checkout comes from `control.env` (`OLD_*` / `NEW_*`:
`START`, `TICK_S`, `STATUS`, counters), re-read while a tick runs (lower `TICK_S` to
unwedge). Every lifecycle step appends to `events.jsonl` (`acquire`, `skip`, `end`, `killed` = SIGTERMed while it owned a tick, `killed_idle` = SIGTERMed before owning one, e.g. a fire that raced the unload).

**Stub `launchctl`** (Python; conftest rewrites its shebang to the test interpreter):

* `load` starts a detached fire loop: the plist's program in its `WorkingDirectory` every
  `FAKE_INTERVAL_S` after the previous run ended, at once with `RunAtLoad`, never two at a
  time — `StartInterval` semantics. Each run is its own process group, with a launchd-like
  env built from scratch (+ the sandbox's knobs, and the stub dir first on `PATH` so a
  watcher fired this way can only ever reach the stub).
* `unload`/`remove` stop the loop; `FAKE_UNLOAD_KILLS=1` (default — the real label's exit
  timeout is 5 s) SIGTERMs a running job's group, `0` leaves it running. CO-02 runs both.
* Records `calls.jsonl` (every call; for an unload, whether a job ran and the tick lock's
  content at that instant) and `jobs.jsonl` (each run's start, end, exit code).
* Hooks: `FAKE_JOB_OVERRIDE` (CO-REAL's faked first tick), `FAKE_KILL_CALLER_ON_LOAD`
  (CO-09b), hidden `__seed` (WT-05).

**Hooks that induce failures** (all via the cutover's own `CUTOVER_*_BIN` knobs):
`plutil_crash` (CUTOVER_PLUTIL_BIN) SIGKILLs the cutover on phase D's lint — the call right
before the plist write (CO-09a); `git_rogue` (CUTOVER_GIT_BIN) starts a writer on the old DB
at phase C's untracked scan and waits until it is writing (CO-16).

## 3. Cases — and how each failure is induced

| ID | Induced by | Asserts (beyond exit code + phase) |
|---|---|---|
| CO-01 | the installed watcher, merged main | unload only with the cutover's lock held and no tick-owning wrapper running (`Sandbox.unload_hit_a_tick`: a fire that raced the unload owns none); plist = original with exactly the two paths replaced (other keys equal; `.orig` saved); new prod clean at the prod commit, roles, swapped marker, **no** `CLAUDE.local.md`; every old tick copied, old DB untouched after the swap; first tick ok and a second one follows; retire markers, verified bundle, banner on both files, one `gh repo archive`, one text |
| CO-02 | a 6 s tick in flight; `FAKE_UNLOAD_KILLS` 1 and 0 | that tick closes `ok`, its wrapper exits 0, no `killed` event; the cutover logged `lock held (live`; the one unload is after the wrapper's exit, hit no tick-owning wrapper (`unload_hit_a_tick`; a fire that raced the unload owns none), lock = the cutover's payload |
| CO-03 | `OLD_TICK_S=600`, park budget 3 s | exit 10, `PENDING`, one deferral; launchd untouched; the lock still the live wrapper's; exactly one text (`looks wedged`); after unwedging, the rerun redoes and finishes with exactly one wedge text in total |
| CO-04 | JVN's commit differs from prod by one line | exit 20; no launchd call, no park, no new prod; plist/role/HEAD/lock as found; one `FAILED` text |
| CO-05 | a tracked edit in old prod | as CO-04, and the edit is still there |
| CO-06 | no `enricher-prod-*` tag | `ref_source=history`, the new prod at that commit, `DONE` |
| CO-07 | `NEW_STATUS=error` | exit 30; plist bytes restored; launchd runs the old wrapper; roles; locks released; the first tick (status `error`) is in the old DB; `pre-rollback-*` kept; the old worker ticks again; the watcher retires on its next fire |
| CO-08 | `NEW_START=0`, start window 4 s | exit 30; `no copy-back needed`; no `pre-rollback-*`; the new DB still byte-equal to the copy |
| CO-09a | `plutil_crash` on call 2 | killed in `SWAPPING` with the plist unchanged; rerun `-> redo`, deletes the owned dir (a planted sentinel is gone), takes back its own lock, `DONE`, one text |
| CO-09b | stub launchctl kills its caller on the new plist's load | killed with the plist switched and nothing loaded; rerun `-> continue_swap`, no `C:` line, the DB inode unchanged, one `COPIED` in history |
| CO-10 | `pyvenv.cfg` `home` → a missing dir | exit 20 naming the interpreter; never parked (no payloads, no lock), no launchd call, no new prod |
| CO-11 | `--preflight` and `--preflight --json` | exit 0, every check ok, ref = the tag; sha256 of every file under HOME, both remotes and TMPDIR unchanged; no state dir; launchd saw only `list`/`print` |
| CO-12 | `gh` exit 1, a rejecting `pre-receive` hook, `send.sh` exit 1 | still `DONE`; each failure in `state.retire` and the log; markers + bundle ok; the remote unchanged |
| CO-13 | a lock with a dead pid written after boot (the worker skips on it) | `reclaimed an orphaned lock`, `DONE` |
| CO-14 | (the CO-01 run) | `.env.local` byte- and mode-identical (600); the canary in no output, state, log, text, launchd record or other file, nor in any repo's history |
| CO-15 | (the CO-01 run) a second `--run`, `--status`, a watcher fire | `-> noop_done` with state, plist, launchd and texts unchanged; the watcher retires itself |
| CO-16 | `git_rogue` moves the old DB during the backup | exit 20 (`row counts differ in: enrichments`); unload then load of the OLD plist; `unloaded_by_us` false; as found; the old worker ticks again |
| CO-17 | `NEW_TICK_S=600` with short close/progress/hard-cap budgets | E extends while the tick writes progress rows, then the hard cap; the rollback TERMs the python stage only, the wrapper closes the tick, the DB is copied back |
| CO-18 | `NEW_TICK_S=600`; SIGKILL the cutover AND the first tick's job group (a power loss), then predate the boot on the tick's lock + `started_at`; worker held off (`NEW_START=0`) until phase E has skipped it | the resumed run (`continue_swap`, no re-copy) records the tick in `orphaned_first_ticks` by the boot rule, waits for the next tick, judges it ok → `DONE`, one text |
| CO-19 | `NEW_TICK_S=600`; SIGKILL only the first tick's job group while the cutover waits; age its lock past 3 h so the worker reclaims it | the later-tick rule hands phase E to tick N+1 → `DONE`, no rollback |
| CO-REAL | `git archive enricher-prod-eeff1c9:src/enricher` as old prod | real `uv sync` venv equivalence (≥ 10 packages), real `cli health` identical, ref = the tag, first tick through the real CLI (`real_first_tick.sh`), `DONE`; a missing tag **fails** with the fix |
| WT-01..07 | see `CASES.md` | |

## 4. Isolation — proven, not assumed

* **Inside each case:** `check_isolation()` (§1); every remote a local path with
  `GIT_ALLOW_PROTOCOL=file` (git refuses http/https/ssh outright — WT-02 shows it);
  `UV_OFFLINE=1`; the stubs. CO-11's manifest and CO-14's scan cover the sandbox side.
* **Around the run:** `real_manifest.py` fingerprints the real `~/Library/LaunchAgents/com.bp.*`,
  the real cutover state dir (every file except the installed watcher's own `jvn.git`, `run/` and
  `watcher.lock` — it fires every 5 min; `state.json` IS hashed), whether the watcher's log files
  exist, and `~/developer/personal/{app,job-enricher,enricher-prod}` (HEAD, tracked changes, role,
  `CLAUDE.local.md`, a stat of every file except what the live worker writes —
  `real_manifest.py`'s `LIVE_WRITES`), before and after pytest.
  A difference is recorded as a FAILED case `real_machine_paths_unchanged` in the JUnit
  file, so the summary's verdict is RED. It started out fingerprinting all of
  `LaunchAgents` and immediately flagged a Creative Cloud agent rewriting its own plist
  mid-run — so it is scoped to the `com.bp.*` agents, the only ones the cutover or the
  watcher can write.
* Teardown kills every process a sandbox started (fire loops and job process groups from
  the stub's records, then anything whose command line names the sandbox); `run.sh` sweeps
  `pgrep -f <basetemp>` again before the after-fingerprint.

## 5. CI

`.github/workflows/ci.yml`, job `enricher` (macOS, `fetch-depth: 0`): after the unit suite,
`bash e2e/run.sh enricher-cutover`; on failure the artifacts are uploaded. There is no root
venv in CI, so `run.sh` runs pytest under `uv run --project src/enricher --frozen python`
(`E2E_CUTOVER_ROOT_VENV=0` forces that path locally — measured GREEN, 29/29, 174 s)
(the enricher's dev group has pytest; `pytest-timeout` is used only when present). The unit
step's `uv sync` fills the uv cache, which is what lets every `uv sync` here run offline;
the step runs `uv python install 3.12` first, because the sandboxes are built on a
uv-MANAGED 3.12 like prod's (a runner's system or Homebrew 3.12 has no `bin/python3` next
to it, which `cutover.sh` and the cutover's interpreter check need). CO-REAL needs tag `enricher-prod-eeff1c9` on the remote
(orchestrator checklist, consolidation PLAN §8).

## 6. Proven to bite

Two deliberate mutations, applied to a COPY of the scripts (`E2E_CUTOVER_SRC=<copy>`; the
working tree was never edited), the cases re-run:

| Mutation | Result |
|---|---|
| **M1** — `phase_b` calls `launchctl unload` BEFORE `park()` | **CO-02 RED in both modes.** `unload-kills`: `FAILED while: tick #4 finished on its own and closed ok` (`tick #4 did not close ok: []` — the stub SIGTERMed the in-flight wrapper, rc 143, a `killed` event; the mutated cutover still reported `DONE`). `unload-leaves`: `FAILED while: the unload came after that wrapper exited…` (`unload at …355.221 came before the in-flight wrapper exited at …360.662` — 5.4 s before the tick ended). |
| **M2** — `rollback()` skips `copy_db_back` (`copied = False`) | **CO-07 RED**: `FAILED while: rolled back: plist bytes, launchd, roles, locks, one text` (`rollback_db_copied=False, expected True: the new prod's work was NOT copied back (lost)`). CO-08 also goes red under M2 (`no copy-back needed` never logged): it pins that the copy-back step ran and judged the DB unchanged, not that it was skipped. |

Reproduce: copy `src/enricher/scripts/{cutover,lib}` somewhere, edit the copy, then
`E2E_CUTOVER_SRC=<copy> e2e/run.sh enricher-cutover --case CO-02`.

## 7. What this section does NOT cover

* **Real launchd.** The stub models `StartInterval`, `RunAtLoad`, unload with and without
  killing a job, `list`/`print` output and a launchd-like env — not launchd itself (e.g.
  `bootstrap`/`bootout`, throttling, the exact `unload` exit codes).
* **Real GitHub**: the banner push to the private job-enricher repo (credentials under a
  launchd job) and `gh repo archive`; a real text.
* **A real multi-hour tick, a real laptop sleep and a real reboot.** CO-17 exercises the
  close-deadline extension and the hard cap with second-scale budgets; the sleep-gap credit
  itself is unit-tested with injected clocks (`tests/test_cutover_clock.py`). CO-18 stands
  in for the reboot by SIGKILLing everything and back-dating the dead tick's lock mtime and
  `started_at` before `kern.boottime`.
* **The rollback's last resort** (unload + SIGTERM/SIGKILL the wrapper when TERMing the
  python stage does not free the lock): CO-17 shows the first step suffices.
* **`--rehearse`** (unit-tested by Unit 3 and run in its scratch sandbox; a `mode=ro`
  backup of an idle WAL DB still creates `-wal`/`-shm` next to it — harmless, noted in §8).
* The live enricher's real tick: CO-REAL fakes the first tick through the real CLI's
  tick-acquire/tick-end (the real wrapper hardcodes `/opt/homebrew/bin/uv` and would call
  JVN and ollama). The real wrapper is the `enricher` section's job.

## 8. Found while building

* **`--preflight` was not read-only on an idle database (fixed in `cutover.py`).** CO-11
  failed: a `mode=ro` reader of a WAL database CREATES its `-wal`/`-shm` files when no
  connection has it open, so a preflight run between two ticks left `enricher.db-wal`
  (empty) and `enricher.db-shm` in prod's `data/`. Harmless to SQLite, but the preflight's
  contract is "writes nothing". `connect_ro(..., quiescent_immutable=True)` now reads with
  `immutable=1` when no `-wal` exists (no connection open; writes land in the `-wal` first,
  so the main file is consistent while we read). Used by `--preflight`'s DB checks only;
  `--run` and `--rehearse`'s backup are unchanged. Unit test:
  `tests/test_cutover_untracked.py::test_quiescent_read_leaves_no_sqlite_sidecars`.
* `pytest -k` matches module names too, so modules holding several cases carry no case id
  in their name (`--case CO-07` must not also run CO-08).
* A SIGTERMed wrapper does NOT orphan its lock: macOS `/bin/sh` (bash 3.2) runs the EXIT
  trap on SIGTERM, and the real wrapper's trap clears a lock holding its own pid (checked
  with a two-line script). The fake does the same. An orphan needs a SIGKILL or a power
  loss — which is what CO-13 plants.
