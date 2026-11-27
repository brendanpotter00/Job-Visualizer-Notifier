# Enricher — case table

The contract `.claude/skills/e2e-gate/sections/enricher.md` reads. `PLAN.md` carries the
reasoning; this is the quick reference + the current status.

**Last real runs: 2026-11-26, `claude/fde-software-engineering` (first row); 2026-11-23,
`feat/consolidate-enricher` (the rest).**

| Run | Collected | Result | Measured |
|---|---|---|---|
| `E2E_SOURCE_DB=jobscraper e2e/run.sh enricher` (working tree, v7 + scoped reenrich) | 17 | **17 PASS / 0 FAIL / 0 BLOCKED — GREEN** | **48 s** |
| `e2e/run.sh enricher` (working tree, v7) | 16 | **16 PASS / 0 FAIL / 0 BLOCKED — GREEN** | **60 s** |
| `e2e/run.sh enricher --fast` | 7 (9 deselected) | **7 PASS — GREEN** | **27 s** |
| `e2e/run.sh enricher --enricher-ref enricher-prod-eeff1c9` (pre-v7) | 12 (4 `v7` deselected) | **12 PASS — GREEN** | **51 s** |

Each wrapper fire (one full tick: 13 `uv run` CLI calls) takes ~2–3 s against the stub; the
rest is the stack (~5 s with the database already provisioned; the first provision adds
~20 s) and the sandbox (`uv sync` from a warm cache, <1 s).

**Cost: $0, and there is no flag that changes that.** The model is `stub_ollama.py` on
loopback; the boot guards refuse unless the sandbox's engines are `ollama`/`ollama` and its
`OLLAMA_BASE_URL` is `:8215`; the backend runs with Browserbase off and an EMPTY Anthropic
key. No `BLOCKED` state exists here: there is no third party to be blocked by.

## Case table

| ID | Proves | Marker | HEAD | prod tag |
|---|---|---|---|---|
| **EN-00** | The sandbox enricher's `taxonomy.CATEGORIES` / `LEVELS` equal what the running backend SERVES on `GET /api/jobs/facets`; (v7) the 17 `SUBCATEGORIES` too | fast (+ v7) | 🟢 2/2 | 🟢 1/1 (subcategory half deselected) |
| **EN-01** | One real wrapper fire enriches every seeded OPEN row end to end: JVN `enrichment_status` `claimed`→`done`, facets = the stub's answer, `job_enrichment` carries taxonomy version / confidence / reasoning / cleaned description, `job_tags` exact; locally one tick `ok` with `claimed == cleaned == classified == sent`, `classify_model = qwen3:32b`, `tick_id` stamped; the stub saw only `/api/chat`, `qwen3:32b`, `temperature 0`, `stream false`, an array schema, one row per call; `/enrichment/health` reflects it | fast | 🟢 | 🟢 |
| **EN-02** | Judge routing: only rows classified below `judge:confidence_ceiling` (0.85) reach the judge; a judge correction (category + level at 0.90) is what JVN shows; a verdict at 0.40 (< `judge:human_floor` 0.60) arrives as `needs_human` while the row still publishes; a confirmation changes nothing; the pre-judge snapshot is kept locally | — | 🟢 | 🟢 |
| **EN-03** | Metrics channel: a `running` row appears in JVN's `enrichment_ticks` mid-tick (stub `slow` on the judge stage), the closing push UPSERTS the same `tick_uuid` to `ok` (one row, not two), the knobs snapshot names `qwen3:32b` / `ollama`, stage timings ride along, `/enrichment/health` reflects `last_enriched_at` | — | 🟢 | 🟢 |
| **EN-04** | Single-flight lock through the real wrapper: a fire during a running tick prints `lock held; skipping this fire`, exits 0, leaves the lock's content and mtime untouched and opens no tick; a dead-holder lock blocks until it ages past 3 h, then is reclaimed **by the age rule**; a lock older than the current boot is reclaimed immediately **even with a live pid** | fast | 🟢 3/3 | 🟢 3/3 |
| **EN-05** | Delivery-first under an engine outage (stub `http500`): the tick still reaches `write-back` + `tick-end` and closes `ok`, sends nothing, both rows stay `claimed` in JVN and `cleaned` locally; two attempts per chunk (one with the retry nudge); the next tick claims nothing new and delivers both, once each. (v7) the abandoned chunks are COUNTED (`errors`, `inbox.attempts`) | slow (+ v7) | 🟢 2/2 | 🟢 1/1 (v7 half deselected) |
| **EN-06** | Bad model output never kills a wave — one tick, six rows: a hallucinated extra object is skipped and counted (`skipped_unknown=1`), an invalid category is nulled LOCALLY + `needs_human` + judged + shipped as NULL, prose content records nothing, a non-JSON HTTP body abandons that chunk only, an over-long tag is dropped by JVN and JVN's `warnings[]` entry reaches the enricher's log; the four good-enough rows land. (v7) the two garbage shapes differ: HTML body = engine error (attempts +1, `errors` +1), prose = silent re-queue | — (+ v7) | 🟢 2/2 | 🟢 1/1 (v7 half deselected) |
| **EN-07** | Idempotent re-delivery: a lost ack (sandbox rows flipped back to unsent) re-delivered through the real `cli write-back` leaves `job_listings` facets, `job_enrichment` values, `job_tags`, `job_locations` and row counts identical (only `enriched_at` refreshes); a quiet tick touches nothing | — | 🟢 | 🟢 |
| **EN-08** | Kill switch: against a backend with `ENRICHMENT_USE_EXTERNAL=false` a tick reports the provider DISABLED, claims 0, makes no model call, closes `ok`, touches no JVN row — and its metrics push still lands | slow | 🟢 | 🟢 |
| **EN-09** | (v7) The subcategory dark knob: off (default), an SWE row lands with `enrichment_subcategories IS NULL` — not `'{}'` — while the label is recorded locally; after `writeback-send-subcategories on` the next tick's SWE row carries `{mobile}` + `subcategory_source='classify'` + its confidence, the non-SWE row stays NULL, and rows already sent are not re-sent | v7 | 🟢 | deselected |
| **EN-11** | (scoped reenrich) The FDE backfill runbook against real JVN: `reenrich --title-regex … --title-exclude … --category business_ops` dry run lists exactly the 2 FDE engineers and changes nothing; the reset re-queues only them (a "Strategist" look-alike and an FDE row already in SWE are not re-classified); the next tick's new answer REPLACES JVN's `business_ops` with `software_engineering` on rows already `done`, **a CLOSED row included and left CLOSED**; with `writeback:send_subcategories` OFF `["forward_deployed"]` stays local and JVN's subcategory stays NULL; knob ON + `subcategory-push` ships it (and the label the knob-off tick recorded for the SWE row: the drain is not scoped) | v7 + scoped_reenrich | 🟢 | deselected |
| **EN-10** | Isolation + accounting (runs LAST): the stub's request count EQUALS the chunks the enricher says it queued (so no model call went anywhere else, e.g. `:11434`), every request carried `e2e_enricher` + `qwen3:32b` + `Host: 127.0.0.1:8215`, the DB is under the sandbox, and the dev tree's `src/enricher/data` is exactly as `run.sh` found it (absent) | fast | 🟢 | 🟢 |

## Corrections to the design table (PLAN.md §3.2), found while building

* **EN-01 provenance.** JVN's `job_enrichment` does NOT store the model or the tick id. Those
  are LOCAL provenance (the enricher's `enrichments.classify_model` / `tick_id`); the model
  reaches JVN only in the tick's `knobs` on `/metrics`. Each is asserted where it lives.
* **EN-06 invalid facet.** The enricher nulls an invalid slug BEFORE write-back
  (`taxonomy.validate_facets`), so JVN receives `category: null` and has nothing to warn
  about. JVN's `warnings[]` channel is exercised by an over-long tag instead.
* **EN-06 hallucinated id.** The in-process engines run one row per call, and
  `_call_with_repair` stamps the input's identity onto a lone answer, so a mis-echoed id is
  REPAIRED, not skipped. A hallucination shows up only as an EXTRA object — which is what the
  stub sends.
* **EN-10.** "The sandbox DB holds every tick" became per-case accounting: each case starts
  from a fresh local DB (archived per case into `artifacts/<run>/enricher-data/`).

## Behaviours observed and pinned (pre-existing, not changed here)

| Observation | Where | Why it matters |
|---|---|---|
| A model answer whose CONTENT is prose (valid envelope) records nothing and counts **no** error and **no** attempt — the row is silently re-queued every tick | HEAD and the prod tag (`engines/base.py` `_call_with_repair` returns `[]` without raising) | A model that persistently garbles one row loops on it forever with `errors=0`; only `recorded < chunks` shows it. Pinned in EN-06 (v7 half) |
| An abandoned chunk is silent at the prod tag (`errors=0`, `inbox.attempts` untouched) | `enricher-prod-eeff1c9` | Fixed on main by P0-3, which ships with the undeployed v7 epic; the EN-05 v7 case is the proof once it deploys |
| `cli health` on a never-initialised checkout fails `unable to open database file` (it does not create `data/`; `cli init` does) | HEAD and the tag | The boot guard runs `cli init` first, as the README's first-time setup does |
| Every tick leaves its watchdog's `sleep $ENRICH_TICK_TIMEOUT_SECS` running as an orphan (the subshell is killed, its `sleep` child is not) | the wrapper | Harmless (the `kill` lines never run), ~1–2 orphans at a time in prod. Shortened to 600 s here |
| The local `jobscraper_pr243` source DB is drifted (see PLAN.md §4) | every local `jobscraper*` DB | Repaired in this section's own DB only |

## The fixture corpus

`fixtures.py`, one group per case, ids unique across groups. Every expected value in every
case comes from this table — the answer the stub was told to give.

| Group | Rows | What each row is for |
|---|---|---|
| EN01 | SWE senior, PM mid, SWE new grad (`level_includes` = `[new_grad, entry]`), DS senior | four categories + the hierarchy, all confident (no judge) |
| EN02 | confident SWE staff; unsure → judge revises; unsure → judge below the floor; unsure → judge confirms | the three verdict outcomes + the not-judged control |
| EN03 | unsure SWE (judged, so the slow judge holds the tick open), confident ops | the running window |
| EN04 | one SRE row | a tick to hold the lock |
| EN05 | iOS, hardware | two chunks to abandon and then deliver |
| EN06 | OK, GHOST, BADSLUG, GARBLED, HTTPJUNK, LONGTAG | one per failure shape |
| EN07 | platform, analytics, mobile EM | three rows with tags + a location |
| EN08 | embedded, operations | rows that must stay untouched |
| EN09_A / EN09_B | SWE + PM, twice | before / after the knob flip |
| EN10 | robotics, quant (unsure → 1 judge chunk), recruiter | 3 classify + 1 judge chunk to count |

## Environment notes (2026-11-23)

* The repo's root `.venv` had been committed as a self-referential symlink (#261), so no
  e2e section could start in the main checkout. Untracked by this branch; recreate a local
  venv with the backend + scripts requirements.
* An orphaned `vite` from a 2026-09-16 `subcategories` run in the `flagout` worktree still
  holds `:3203`, so a FULL `e2e/run.sh subcategories` cannot start on this machine until it
  is stopped. `E2E_SKIP_FRONTEND=1 e2e/run.sh subcategories --fast` runs (36/36 GREEN).
