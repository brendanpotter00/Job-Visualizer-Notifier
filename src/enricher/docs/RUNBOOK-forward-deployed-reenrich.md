# Runbook — re-enrich the mislabelled Forward Deployed Engineer rows

**Why.** Before the FDE correction, SKILL.md said *"Solutions / Sales / Forward-Deployed
Engineer: `business_ops` unless the core deliverable is committed product code"*. The
enricher read customer-facing FDE postings (Braintrust's post-sales FDE, Cognition, Exa,
Salesforce, Cisco, Google gTech…) as Business Ops, so they never showed under Software
Engineering › Forward Deployed. The rubric now defaults FDE titles to
`software_engineering` + `["forward_deployed"]` and vetoes only non-engineer hires.

**Why not `reenrich --taxonomy-below`.** The fix is a rubric-only edit: the declared
version stays `v7` and only the hash moves, so no row is "below" it. Bumping to `v8` to
force it would re-queue the whole corpus. The scoped form selects by title + current
category instead.

**Scope (measured read-only against prod JVN, 2026-11-25): ~70 rows — 40 OPEN, 30
CLOSED.** Every forward-deployed engineer, FDE manager and Forward Deployed Architect
title currently in `business_ops`, with the look-alike role nouns (strategist, TPM /
program, engagement manager, recruiter, analyst, operations, consultant) left out. The
re-run decides each one under the new rubric: most move to SWE; Harvey's "Forward
Deployed Finance Engineer" rows (domain experts) and workflow-configuring Notion
architects are expected to stay Business Ops. Human-corrected rows are skipped by JVN.
JVN accepts the write for CLOSED rows too (the writer updates by key, with no status
filter), so hiring-trend history is corrected as well.

Everything below runs **by hand on the enricher host**, from the **prod** checkout,
after this PR is merged. Merging deploys nothing.

## 0. (Recommended) confirm the numbers on the production engine first

The PR's before/after scores were measured with the `claude-code` engine (Haiku classify
+ Sonnet judge). Prod runs `ollama` / `qwen3:32b`. To see the same A/B on the prod model
before deploying, run it in a **dev** checkout on the enricher host (never the prod one),
same batch size both times:

```bash
cd ~/developer/personal/Job-Visualizer-Notifier && git fetch && git checkout <merge-sha>
cd src/enricher && uv sync --locked && uv run python -m job_enricher.cli init
git show <merge-sha>~1:src/enricher/.claude/skills/taxonomy/SKILL.md > .claude/skills/taxonomy/SKILL.md
git show <merge-sha>~1:src/enricher/.claude/skills/taxonomy/SUBCATEGORIES.md > .claude/skills/taxonomy/SUBCATEGORIES.md
uv run python -m job_enricher.cli eval-run --engine ollama --batch 1 --judge off --tag fde-before
git checkout .claude/skills/taxonomy/
uv run python -m job_enricher.cli eval-run --engine ollama --batch 1 --judge off --tag fde-after
uv run python -m job_enricher.cli eval --engine ollama --tag fde-before --judge off
uv run python -m job_enricher.cli eval --engine ollama --tag fde-after  --judge off \
  --gate --gate-group category --baseline golden/scorecards/scorecard.fde-before.ollama.judge_off.json
```

(`<merge-sha>~1` is main just before the merge. At ~90–140 s per row on qwen3:32b each arm
is several hours for 313 rows, and it competes with the live worker for the GPU — add
`--human-only` for the 57 gated rows only.)

## 1. Deploy

```bash
cd ~/developer/personal/enricher-prod/src/enricher
scripts/deploy.sh <merge-sha>
uv run python -m job_enricher.cli taxonomy-version   # must print the PR's new v7+<hash>
```

## 2. Park the worker, back up the DB, dry-run

```bash
P=~/developer/personal/enricher-prod/src/enricher; cd "$P"
.venv/bin/python -I scripts/lib/park_worker.py claim --lock data/.tick.lock \
  --wrapper "$P/scripts/enrich_tick_wrapper.sh" --budget-s 14400 --owner-pid $$
sqlite3 data/enricher.db ".backup $HOME/enricher-pre-fde-reenrich.db"   # never cp a WAL DB

uv run python -m job_enricher.cli reenrich \
  --title-regex 'forward[\s-]?deploy|\bFDE\b' \
  --title-exclude 'strateg|program|recruit|engagement|analyst|operations|consult|sourcer|talent|\bGRC\b|assurance|production lead' \
  --category business_ops \
  --dry-run
```

The dry run prints the count and **every matched row** (source, id, current category,
title). Expect roughly 70; the local DB can hold a few more or fewer than JVN. Stop if it
lists anything that is not a forward-deployed engineer, FDE manager or architect.

## 3. Reset, then release the worker

```bash
uv run python -m job_enricher.cli reenrich \
  --title-regex 'forward[\s-]?deploy|\bFDE\b' \
  --title-exclude 'strateg|program|recruit|engagement|analyst|operations|consult|sourcer|talent|\bGRC\b|assurance|production lead' \
  --category business_ops
.venv/bin/python -I scripts/lib/park_worker.py release --lock data/.tick.lock --owner-pid $$
```

The rows go back to `cleaned`. The next ticks re-classify them (`enrich:per_tick_limit`
is 40, so about two ticks), the judge runs as usual, and write-back sends them to JVN.

## 3b. ⚠ Ship the `forward_deployed` subcategory (a separate step)

Step 3 moves the **category**. The **subcategory** reaches JVN only when
`writeback:send_subcategories` is ON, and prod JVN suggests it is OFF: on 2026-11-26
every one of the 10,575 SWE rows that carry a subcategory came from the backfill drain
(`enrichment_subcategory_source = 'backfill'`), none from a tick, and the ~1,000 SWE rows
the ticks wrote in the six days before had none. These ~70 rows were `business_ops`
during that backfill (it labels SWE rows only), so **after step 3 they sit in Software
Engineering with no subcategory and do not show under the Forward Deployed filter.**

The re-classify DOES record `["forward_deployed"]` locally. With the knob OFF it stays
there (`subcategory_sent_at IS NULL`) for the drain to pick up. Check the knob, then
see what the drain would send:

```bash
uv run python -m job_enricher.cli enrich-config | python3 -c 'import json,sys; print(json.load(sys.stdin)["writeback_send_subcategories"])'
uv run python -m job_enricher.cli subcategory-push --dry-run
```

`subcategory-push` refuses (exit 2) while the knob is OFF, and it drains **every**
labelled row not yet pushed: the FDE rows **and** every tick-classified SWE row since
the knob went off. Shipping those is a rollout decision
(`RUNBOOK-subcategory-backfill.md` §6 step 8, `BACKFILL.md` §1.2), not part of this
fix. If you take it: `cli writeback-send-subcategories on`, then the paced
`subcategory-push --probe …` from `BACKFILL.md`. Leave the knob ON afterwards and new
FDE postings get their subcategory on their first tick. Turn it back OFF and they wait
for the next drain.

## 4. Verify (read-only, prod Postgres)

```sql
SELECT enrichment_category, status, count(*)
FROM job_listings
WHERE title ~* '(forward[- ]?deploy|\mFDE\M)'
  AND title !~* '(strateg|program|recruit|engagement|analyst|operations|consult|sourcer|talent|grc|assurance|production lead)'
GROUP BY 1, 2 ORDER BY 1, 2;
```

Before the backfill this showed 70 `business_ops` rows. After it, `business_ops` should be
down to the vetoed ones (Harvey's finance "engineers", configuration-only architects).

## Rollback

There is no undo for a reset row: its old enrichment is deleted locally. To return the
DB to its pre-backfill state, park the worker and restore `~/enricher-pre-fde-reenrich.db`
the way `docs/ENVIRONMENTS.md` ("Rolling it back") restores a backup, then redeploy the
previous ref. Rows already written back to JVN keep their new labels until re-enriched.
