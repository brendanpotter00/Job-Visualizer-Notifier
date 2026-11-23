# Enricher — e2e gate runbook

Design + reasoning: `e2e/enricher/PLAN.md`. Live case status, fixture corpus and observed
behaviours: `e2e/enricher/CASES.md`. This file is the "sub-skill": how to run it, what each
case proves, what to look at first when it goes red.

## Run it

```bash
e2e/run.sh enricher                                       # full gate, measured 60 s
e2e/run.sh enricher --fast                                # EN-00/01/04/10, measured 27 s — every commit
e2e/run.sh enricher --case EN-04                          # one case, for a fix loop
e2e/run.sh enricher --enricher-ref enricher-prod-eeff1c9  # the code the cutover puts in prod (51 s)
e2e/run.sh enricher --keep-up                             # leave backend, stub and sandbox up
e2e/run.sh enricher --refresh-db                          # re-provision jobscraper_e2e_enricher
```

**Cost: $0, unconditionally.** The enricher's model is `e2e/enricher/stub_ollama.py` on
loopback. The boot guards refuse to run unless the sandbox's engines are `ollama`/`ollama`
(so the wrapper can never reach `claude -p`) and its `OLLAMA_BASE_URL` is `:8215` (never the
real ollama on `:11434`, which prod uses). The backend runs with Browserbase off and an
EMPTY Anthropic key. Nothing touches real JVN, prod's checkout or any prod database.

**Ports `8205` (backend), `8206` (EN-08's kill-switch backend), `8215` (stub), no frontend;
database `jobscraper_e2e_enricher`.** Its own run lock — it runs alongside every other
section, never alongside a second copy of itself.

**What it runs:** a throwaway COPY of `src/enricher` (the working tree, or
`git archive <ref>:src/enricher`) under `$TMPDIR`, never `src/enricher` itself — the
enricher's DB and lock are package-relative, so running the dev tree would write
`src/enricher/data/`. The run refuses unless the copy's own interpreter proves `REPO_ROOT`
is the copy.

## When to run this gate

Before claiming "ready to test" on anything touching:

- `src/enricher/scripts/enrich_tick_wrapper.sh` — always the full gate, and also
  `--enricher-ref` if the change is meant to match prod's behaviour
- `src/enricher/src/job_enricher/{cli,store,lock,writeback,jvn_client,metrics,enrich_config}.py`
- `src/enricher/src/job_enricher/engines/{ollama,base,prompts}.py`
- `src/enricher/src/job_enricher/taxonomy.py` or `.claude/skills/taxonomy/` (EN-00)
- the backend's `routers/internal_enrichment.py`, `services/enrichment_writer.py`,
  `services/enrichment_monitor.py` (`record_tick`), `auth/internal_key.py`
- `e2e/shared/stack/stack_up.sh` (this section uses all three of its newest knobs)

Before deploying a ref to prod with `deploy.sh`, run `--enricher-ref <that ref>`.

## Files this suite does NOT own — report bugs there, don't fix them here

Everything under `src/enricher/` and the backend's enrichment router/services. If a case
fails because of a bug there, the case is doing its job — **report it; never bend the test**.

## Per-case reference

| ID | Proves | First thing to check on red |
|---|---|---|
| **EN-00** | enricher taxonomy == the facets the backend serves | The message lists enricher-only / JVN-only slugs. A slug change belongs in the backend + `taxonomy.json` + `job_enricher.taxonomy` in ONE PR. If JVN-only slugs are `data_scientist`/`intern`, the drift repair did not run — read `artifacts/<run>/drift-repair.txt` |
| **EN-01** | one wrapper fire: claim → clean → classify → write-back → tick-end, all landed | `cases/test_en01*/01-wrapper.log` — the CLI's own summary lines (`pull:`, `classify-run:`, `write-back:`, `tick-end:`) show which stage stopped. `JVN rejected (…): <error>` lines are the backend refusing a row: read `stack/backend.log` |
| **EN-02** | only low-confidence rows reach the judge; corrections land; below the floor → needs_human | `stub-requests.json` (which ids the judge saw) vs `fixtures.expected_judged`. A judge correction that did not land usually hit a code rail in `cli._merge_judge` (level change needs judge confidence ≥ 0.8) |
| **EN-03** | a `running` tick appears in JVN mid-tick; the closing push upserts the same `tick_uuid` | No `running` row: the wrapper's post-classify `metrics-push` failed — grep the wrapper log for `metrics-push`. Two rows: `record_tick` lost its `ON CONFLICT (tick_uuid)` |
| **EN-04** | lock: skip during a tick, dead holder waits for the 3 h backstop, pre-boot lock reclaimed | The wrapper logs per fire. `lock.py` logs `reclaimed stale lock` / `predates current boot` — which one appeared tells you which rule fired |
| **EN-05** | engine outage: tick still closes, nothing sent, next tick delivers once | `write-back:` missing from tick 1's log = the wrapper's delivery-first ordering broke (proven to bite, PLAN.md §6) |
| **EN-06** | bad rows fail alone | The table in the test's docstring maps each row to its contract; `classify-run:`'s `skipped_unknown=` / `abandoned=` counters are the quickest read |
| **EN-07** | re-delivery changes nothing | `snapshot-1.json` vs `snapshot-2.json` in the case dir — the first differing key is the non-idempotent write |
| **EN-08** | kill switch claims nothing | `killswitch-backend.log` in the case dir if the second backend did not come up (port 8206 busy?) |
| **EN-09** | (v7) knob off → NULL not `'{}'`; on → SWE rows only | `'{}'` with the knob off means the write-back started sending the key when it should omit it (`writeback._row_to_result`) |
| **EN-10** | every model call hit the stub; nothing left the sandbox | A count mismatch names both numbers. A dev-tree change means something wrote `src/enricher/data` — the sandbox leaked (proven to bite, PLAN.md §6) |

## Reading a red

`e2e/enricher/artifacts/<run>/summary.md` first, then `cases/<test>/step.txt` (it names the
step that failed in words), then the case's numbered logs: `NN-wrapper*.log` (one per fire,
stdout+stderr), `NN-cli-*.log`, `stub-requests.json`. Every case's local enricher DB is kept
under `enricher-data/NN-<case>/enricher.db` — open it read-only with `sqlite3`.

**Failure modes that are NOT enricher regressions:**

| Symptom | Cause | Fix |
|---|---|---|
| `sandbox: … exited` during the build | uv could not sync (cold cache, no network) | re-run with network; the sync is the only networked step |
| `boot guards refused` | the sandbox `.env.local` / engines are not what the guard requires | read `artifacts/<run>/sandbox.txt`; never relax the guard |
| `refusing to start — :8215 is held` | a previous `--keep-up` run's stub | stop it (`e2e/enricher/.pids/stub.pid`) |
| every row `JVN rejected … search_text` or a `job_categories` FK error | the database lost the drift repair | `--refresh-db` |
| `claimable rows from other sources` at seed | a backend fan-out scraped a real board into the DB before the seed disabled the companies | `--refresh-db` |

## Known non-coverage

launchd itself (the wrapper is exec'd the way launchd does it, but no plist is loaded — that
is `enricher-cutover`'s job), the `claude-code` engine (refused by design), the subcategory
backfill lane, the 3 h watchdog actually firing, and model quality. Details: `PLAN.md` §8.
