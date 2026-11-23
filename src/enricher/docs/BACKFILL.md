# The SWE subcategory backfill — the night run and the morning drain

**This is the single page you follow at 22:00 and again at 09:00.** The *design*
lives in `docs/RUNBOOK-subcategory-backfill.md`; this page is the procedure.

Two lanes, two commands, one ledger:

| lane | command | lock | ledger row |
|---|---|---|---|
| **label** (the model run) | `cli subcategory-backfill` | `data/.backfill.lock` (12 h stale) | `backfill_runs.kind='label'` |
| **push** (the drain to JVN) | `cli subcategory-push` | `data/.subcategory-push.lock` (6 h stale) | `backfill_runs.kind='push'` |

---

## 1. PRE-FLIGHT — in order, every time

### ⚠ 1.1 Confirm you are in the PROD checkout

```sh
cat .checkout-role     # must print: prod
```

It says `prod` **only** in `/Users/bpotter/developer/personal/enricher-prod/src/enricher`. **A dev checkout (your JVN checkout's
`src/enricher`) has no such file, or says `dev` — either is the signal to stop.**

> ⚠ **Merging to JVN main deploys NOTHING to the enricher.** `scripts/deploy.sh` is
> the path. Running the backfill from the dev checkout against the prod DB is on
> the DO-NOT list below.

### 1.2 Confirm the JVN side is deployed

`SCHEMA-14` must be live and accepting the slim contract.

> ⚠ **If it is not: leave `writeback:send_subcategories` OFF and do not run the
> push.** Labelling is still safe — it is local. Pushing is not.

### ⚠ 1.3 Confirm the taxonomy is at v7 and the rubric hash is stamped

```sh
uv run python -m job_enricher.cli taxonomy-version    # must start v7+
```

It must match **what the eval gate scored**. A v6 rubric would label the whole
corpus against a taxonomy the gate never scored, and you would not find out.

### 1.4 Import the scope (only if running `--open-only`)

```sh
uv run python -m job_enricher.cli subcategory-scope-import --json-file <export>
```

> ⚠ The scope is a **point-in-time** export. The run **refuses (exit 2)** on a
> scope older than 24 h or an empty one — jobs open and close overnight, so a
> stale scope is a *wrong* scope, and a silently-empty one would make
> `--open-only` a no-op that reports success.

### 1.5 The smoke test

```sh
uv run python -m job_enricher.cli subcategory-backfill --dry-run --limit 20
```

Writes **nothing** and emits `data/backfill-probe-<ISO>.json`. It works with
`backfill:enabled` still off — that is deliberate, so this step comes before you
arm anything.

---

## 2. THE NIGHT

```sh
uv run python -m job_enricher.cli set-backfill-enabled on
uv run python -m job_enricher.cli subcategory-backfill \
    --until 09:00 --tz America/Chicago --open-only \
    --model <tier from EV-12's A/B> --batch <from P0-5>
```

> ⚠ **There is no `--concurrency`, and this is not an oversight.**
> `ChunkEngine._call_with_repair` runs **one `claude -p` at a time**; `ChunkEngine`
> has no parallel path at all; and a threadpool would multiply SQLite write
> contention against the live tick (`busy_timeout` is 5000 ms). The levers for
> wall time are `--batch` and the model tier.

`--until` is an absolute local wall-clock time resolved to its **next**
occurrence. It is checked **between chunks only**, so a chunk in flight always
finishes its write.

---

## 3. THE MORNING — in this order

### ⚠ 3.1 Read the report, and read two fields FIRST

```sh
uv run python -m job_enricher.cli subcategory-report
```

Read **`aborted_reason`** and **`echo_mismatch`** before anything else.

> ⚠ **A non-zero `echo_mismatch` means the batch size is TOO HIGH. Lower
> `--batch`. Do not rerun at the same size** — you will get the same result and
> burn another night.

### ⚠ 3.2 Disarm the knob

```sh
uv run python -m job_enricher.cli reset-knob backfill:enabled
```

> ⚠ **An explicit knob overrides the committed default FOREVER.** Leaving it on
> means the next operator inherits an armed backfill they did not arm. `reset-knob`
> deletes the override so the getter falls back to the committed `False`.

### 3.3 Drain to JVN

```sh
uv run python -m job_enricher.cli subcategory-push \
    --probe data/subcategory-push-probe-<ISO>.json \
    --batch <chosen B> --duty <chosen duty_pct>
```

> ⚠ **`--probe` IS NOT OPTIONAL IN PRACTICE.** The sleep, rows/hour and ETA are
> all derived from `S_p95`, and without `--probe` (or `--slot-hold <seconds>`)
> that number is the **UNMEASURED `PUSH_SLOT_HOLD_CEILING_S = 5.0` placeholder**
> — so the ETA you read would have nothing to do with the table you just filled
> in. The command says so loudly when it falls back, and it **refuses (exit 2)**
> rather than fall back silently when a `--probe` file carries no usable cell.
> `--batch` also picks which measured cell is read; omit it and the probe's own
> `chosen_batch` wins.

**Read the printed ETA before walking away.** `--max-seconds` defaults to one
hour, so a single invocation cannot drift into the day; re-invoke to continue —
the drain is resumable by construction (`subcategory_sent_at` is the cursor).

#### `BF-16`'s measured table — fill this in, do not guess

| B | `T_req` p50 | `T_req` p95 | `T_ping` p50 | `S_p95` | bytes |
|---|---|---|---|---|---|
| 50 | ☐ | ☐ | ☐ | ☐ | ☐ |
| 100 | ☐ | ☐ | ☐ | ☐ | ☐ |
| 250 | ☐ | ☐ | ☐ | ☐ | ☐ |
| 500 | ☐ | ☐ | ☐ | ☐ | ☐ |

**Chosen (batch, duty_pct) = ☐, ☐** — the largest B whose `S_p95` stays under
`PUSH_SLOT_HOLD_CEILING_S`. **Derived rows/hour = ☐. ETA = ☐ h.**

> ⚠ **Keep the probe JSON.** The table above is for humans; `--probe` is how the
> numbers actually reach the command. Transcribing them into the table and not
> passing the file is exactly the mistake that leaves the pace unmeasured.

> ⚠ **`S_p95 = T_req_p95 − T_ping_p50` is the estimated POOL-SLOT HOLD TIME, and
> it is the only input the rate may be derived from.** Batch size is capped by
> slot-hold time, **not** by request count.

---

## 4. KILL SWITCHES — both lanes, with their latency

```sh
touch data/.backfill.stop            # label lane, stops at the next CHUNK
touch data/.subcategory-push.stop    # push lane,  stops at the next BATCH
uv run python -m job_enricher.cli set-backfill-enabled off   # same, via the DB
```

`SIGTERM`/`SIGINT` finishes the unit in flight and closes the run row cleanly.

> ⚠ **There is deliberately no mid-unit stop. That is what protects a write in
> flight.** See `RUNBOOK-subcategory-backfill.md` §9 for the three levels and
> their latencies.

---

## 5. IF IT WENT WRONG

```sh
uv run python -m job_enricher.cli subcategory-reset --run-id <N> --dry-run
uv run python -m job_enricher.cli subcategory-reset --run-id <N>
```

> ⚠ **Do NOT add `--source backfill`.** One run writes **two** sources under the
> same `run_id` — `rule` (the free title/tag pass) and `backfill` (the model
> pass) — and the default covers **both**. Narrowing it to `backfill` resets only
> the model half and leaves every rule-pass row of that run labelled and out of
> the queue, while still printing a confident count.

> ⚠ **A run aborted on `empty_rate` has STILL WRITTEN some `'[]'` rows**, and
> `'[]'` is TERMINAL — those rows are out of the queue until you reset them. The
> abort did not undo anything.

> ⚠ **The enricher reset is HALF THE JOB.** Any row already pushed is live in JVN
> Postgres and `subcategory-reset` cannot un-write it. The command prints how many
> in-scope rows were already pushed — that number is the size of the second half,
> and the JVN-side statement is **`ADM-15`**.

---

## 6. IF THE PUSH BACKS OFF

A `pool_pressure` abort means the drain saw the **2026-05-17 failure signature**
(`docs/incidents/2026-05-17-recent-jobs-pool-exhaustion.md`).

> ⚠ **Do NOT raise `duty_pct` to catch up.** Lower the batch, confirm the JVN side
> is healthy, and resume. The drain is resumable by construction, so there is
> nothing to catch up to.

---

## 7. DO NOT

- ⚠ **Do not run `reenrich`.** `ENR-REN-1` blocks the wide form, but the reason
  matters: **the v7 bump needs no reenrich at all.** The backfill exists precisely
  so the corpus gains subcategories **without discarding its category/level/tags
  labels**. `reenrich --taxonomy-below` would re-queue all 19,396 rows — roughly
  40 days of worker time.
- **Do not add either command to `scripts/enrich_tick_wrapper.sh`.** Both are
  hand-launched, and both take their own lock precisely so they cannot collide
  with the live tick's `.tick.lock`.
- **Do not run two of either at once.** The second exits **75**.
- **Do not run from the dev checkout against the prod DB.** See §1.1.
