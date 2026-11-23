# Enricher cutover: `app/` → `enricher-prod/`

Moves the live enricher off the retired `job-enricher` clone (`~/developer/personal/app`)
onto a JVN clone (`~/developer/personal/enricher-prod`, worker dir `src/enricher`).

- **What changes:** where prod's code comes from.
- **What does not change:** what runs. The new prod is pinned to the JVN commit whose
  `src/enricher` tree equals `app/`'s tree (today tag `enricher-prod-eeff1c9`). No ref
  matches → the cutover refuses.
- **When:** only after the consolidation PR is merged. A launchd watcher polls JVN `main`
  and runs the cutover **taken from merged `main`**.

Design and reasoning: `docs/implementations/enricher-consolidation/PLAN.md` §4 (JVN root).

## Files

| File | Role |
|---|---|
| `cutover.sh` | entry; runs `cutover.py` under `app/`'s own Python 3.12 with `-I` |
| `cutover.py` | the state machine (stdlib + `../lib/park_worker.py` only) |
| `watcher.sh` | the merge trigger; installed as a **copy** in the state dir |
| `com.bp.jvn-enricher-cutover.plist.template` | the watcher's launchd agent (every 300 s, `RunAtLoad`) |
| `install_watcher.sh` | installs / re-arms the watcher (`--dry-run` writes nothing) |
| `../lib/park_worker.py` | parks the worker between ticks; also used by `deploy.sh` |

## Modes and exit codes

```bash
sh cutover.sh --preflight [--jvn-repo <JVN checkout>] [--json]   # read-only, any time
sh cutover.sh --rehearse --scratch <empty dir> [--jvn-repo <path>]
sh cutover.sh --run        # what the watcher calls; resumable
sh cutover.sh --status     # print state.json
```

| Exit | Meaning | Watcher |
|---|---|---|
| 0 | done, or nothing to do | stops on its next fire |
| 10 | deferred (transient: network, wedged tick, not merged yet) | retries in 5 min |
| 20 | failed **before** any swap; prod untouched | stops (terminal) |
| 30 | rolled back to `app/` | stops (terminal) |
| 2 | usage | — |

- `--preflight` never writes: not `app/`, not a plist, not the state dir. It calls
  `launchctl` only for `list`/`print`, and deletes its temp dir.
- `--rehearse` runs phases A + C into `--scratch`: clone, `uv sync`, an online backup of
  the **live** DB (a shared lock of a few seconds), untracked files **except `.env.local`**,
  `cli health` on the scratch copy only. No launchd call, no write to `app/`. Report:
  `<scratch>/rehearsal.json`.

## What `--run` does

| Phase | Worker | Steps |
|---|---|---|
| A prepare | running | read-only checks; refresh the JVN mirror; refuse unless `main` has the cutover; derive the ref (tags `enricher-prod-*` first, then all history); clone into `enricher-prod` (writes `.cutover-owned` first); `uv sync --frozen` with `app/`'s interpreter; same Python + same `uv pip list` |
| B park | parked | wait (≤ 4 h) for the gap between ticks; take `data/.tick.lock` with `O_EXCL`; let the wrapper exit; **then** `launchctl unload`; no process may hold the DB |
| C copy | parked | SQLite online backup of each `data/*.db`; integrity, `user_version`, every table count, max tick, `meta` equal; copy untracked files (`.env.local`, logs) with mode, checked by sha256; `cli health` equal in both |
| D swap | — | roles (`app/` → `retiring`); rewrite the plist (exactly two path changes, `plutil -lint`, atomic). **This write is the switch.** `launchctl load`; `launchctl print` must name the new wrapper |
| E verify | new | a new tick must start (≤ 15 min) and close (≤ 5 h, extended while the DB keeps changing, ≤ 24 h) with `status=ok`, and if it claimed rows it must classify and send some |
| F retire | new | `.checkout-role=retired` + `CLAUDE.local.md` in `app/` and `job-enricher/`; a bundle of every `job-enricher` ref; a "moved" banner pushed to `job-enricher` `main`; `gh repo archive`; a text. Each step is best effort and never rolls back |

Failure handling:

- **Before the plist write:** `app/` is put back exactly as found (role, lock, launchd).
  Exit 10 or 20.
- **After it:** rollback. Park the new worker, copy its DB back if it did any work (the old
  DB is kept as `enricher.db.pre-rollback-<ts>`), restore the original plist and role,
  reload `app/`. Exit 30. A rollback that cannot finish stays `ROLLING_BACK`, texts once,
  and retries on the next fire.

Every start re-derives where the plist points before trusting `phase`, so a crash or reboot
at any point resumes safely. It never re-copies the DB after the swap.

## Knobs

All are env vars, defaulted from `$HOME`, so a fake `HOME` sandboxes everything.

| Knob | Default |
|---|---|
| `CUTOVER_OLD_PROD` / `CUTOVER_NEW_PROD` / `CUTOVER_OLD_DEV` | `~/developer/personal/{app,enricher-prod,job-enricher}` |
| `CUTOVER_STATE_DIR` | `~/Library/Application Support/jvn-enricher-cutover` |
| `JVN_REMOTE_URL` | `https://github.com/brendanpotter00/Job-Visualizer-Notifier.git` |
| `CUTOVER_ENRICHER_PLIST` | `~/Library/LaunchAgents/com.bp.job-enricher.plist` |
| `CUTOVER_SEND_SH` | `~/.claude/skills/message-brendan/send.sh` |
| `UV_BIN`, `LAUNCHCTL`, `GH_BIN`, `CUTOVER_GIT_BIN`, `CUTOVER_PLUTIL_BIN`, `CUTOVER_LSOF_BIN` | `/opt/homebrew/bin/uv`, `launchctl`, `gh`, `git`, `/usr/bin/plutil`, `/usr/sbin/lsof` |
| `CUTOVER_OLD_REPO_SLUG` | parsed from `app/`'s `origin` URL |
| `CUTOVER_PARK_BUDGET_S` | 14400 |
| `CUTOVER_FIRST_TICK_START_S` / `_CLOSE_S` / `_HARD_CAP_S` | 900 / 18000 / 86400 |
| `CUTOVER_POLL_S` / `CUTOVER_LOCK_POLL_S` | 5 / 1 |
| `CUTOVER_WRAPPER_EXIT_S`, `CUTOVER_ROLLBACK_PARK_BUDGET_S`, `CUTOVER_PROGRESS_WINDOW_S` | 120, 1800, 1800 |
| `CUTOVER_DEFER_ALERT_AFTER` | 24 deferrals → one text |

Clocks: every wait is a wall-clock deadline polled in short steps. Time the laptop spent
asleep is credited back to every deadline, so a night's sleep never reads as a wedged tick.

## Texts

One per event, never repeated: `DONE`, `FAILED`, `ROLLED_BACK`, `ROLLBACK_STUCK`,
`DEFERRED:wedged` (a tick outlived the 4 h park budget), `DEFERRED:repeated`. Texts never
contain secrets or `.env.local` content.

## Operating it

Install (the orchestrator does this once the PR is up):

```bash
sh src/enricher/scripts/cutover/install_watcher.sh --dry-run   # prints the plan
sh src/enricher/scripts/cutover/install_watcher.sh
```

Watch:

```bash
tail -f ~/Library/Logs/jvn-enricher-cutover.log                 # "not merged yet" every 5 min
cat "$HOME/Library/Application Support/jvn-enricher-cutover/cutover.log"
sh src/enricher/scripts/cutover/cutover.sh --status
```

Re-arm after `FAILED` or `ROLLED_BACK` (a human decides):

1. Read `state.json` (`failed_reason` / `rollback_reason`) and fix the cause.
2. After a rollback, move `~/developer/personal/enricher-prod` aside (it is kept for
   diagnosis, `.checkout-role=failed-cutover`).
3. `sh src/enricher/scripts/cutover/install_watcher.sh --rearm` (archives the old state).

## Contract with the enricher

The cutover relies only on these, all present at `enricher-prod-eeff1c9` and on `main`:

- `data/enricher.db` with tables `ticks(id, status, claimed, classified, sent, …)` and `meta`;
- the lock `data/.tick.lock` holding `"<pid>|<iso>"`, and `cli tick-acquire` exiting 75 while
  a live pid holds it;
- `scripts/enrich_tick_wrapper.sh`, the launchd program, run with cwd = the checkout;
- `uv run python -m job_enricher.cli health` printing one JSON object.

`e2e/enricher-cutover/fixtures/fake_enricher/` (JVN root) is a fake enricher that honours
exactly this contract; the `enricher-cutover` e2e section runs these scripts against it
(`e2e/run.sh enricher-cutover`, also in CI). Change the contract → change the fake too.
