# Location-normalization eval (Tier-2 Haiku quality guard)

An **on-demand, human-run, never-CI** golden-set eval that scores the **real**
Claude Haiku output of `normalize_location_via_llm()`
(`api/services/llm_client.py`) against a curated + prod-sampled set of
`raw → expected structured fields`. It exists because every *unit* test mocks the
LLM, so the suite catches code regressions but is blind to **quality** regressions
in the prompt, model, or schema. This harness is the only thing that would catch a
`SYSTEM_PROMPT` / `FEW_SHOT_GUIDE` / `HAIKU_MODEL` / `_LOCATIONS_SCHEMA` / SDK
change that starts mis-parsing real inputs.

It targets the **client directly** — no DB, no Procrastinate. It needs only
`ANTHROPIC_API_KEY`.

## How to run

Run from the **repo root** so `Settings` auto-loads `ANTHROPIC_API_KEY` from
`.env.local` (`config.py` loads `(".env", ".env.local")` relative to CWD):

```bash
source .venv/bin/activate
PYTHONPATH=. python -m src.backend.api.eval.eval_locations --set all
```

Baseline workflow (the recommended pre-merge check) — save a baseline, then after
a prompt/model change print only regressions and fail if any case that passed now
fails:

```bash
# capture a baseline (do this on a known-good commit)
PYTHONPATH=. python -m src.backend.api.eval.eval_locations --set all --json eval-baseline.json
# ...after changing location logic...
PYTHONPATH=. python -m src.backend.api.eval.eval_locations --set all --baseline eval-baseline.json
```

The **pure scorer** runs in the normal backend test suite (mocks nothing, no key,
no network):

```bash
cd src/backend && pytest api/tests/test_eval_scoring.py
```

### Flags
- `--set {curated,prod,all}` (default `all`)
- `--json PATH` — write the full structured report (for baselining)
- `--baseline PATH` — compare verdicts; print only passed→failed **gating** regressions, fail if any
- `--repeat N` (default 1) — run each distinct string N times; gate on majority, flag flaky
- `--threshold FLOAT` (default `0.90`) — minimum gating accuracy
- `--concurrency N` (default 5) — max concurrent calls (sync mode)
- `--batch` — use the Anthropic **Message Batches API** (50% cost, async). See below.
- `--poll-interval N` (default 5.0) — batch poll interval seconds
- `--verbose` — print every case, not just failures

### Efficiency: dedup + `--batch`

- **Dedup (always on).** The runner calls the model **once per distinct raw string**
  and reuses the outcome for every case that shares it — mirroring production's
  by-string alias cache. The 110-case `all` set collapses to **94 distinct calls**.
- **`--batch` (opt-in).** Submits the distinct requests as one Message Batch at
  **50% cost** (async: submit → poll → map back). It reuses the *same*
  `build_message_params` (incl. the structured-outputs schema) and
  `parse_locations_text` as production — only the transport differs.
  - **Default is the sync path**, which exercises the exact production
    `messages.create(...)` call (`normalize_location_via_llm`). Use `--batch` for
    the 50% discount / to avoid rate-limit pressure on larger runs; use the default
    when you want the production-call smoke test.
  - Note: the pinned SDK's *typed* batch params don't list `output_config`, but the
    live API accepts it at runtime (verified — 0 errors, valid structured JSON), so
    batch results are field-identical to sync. The sync path stays canonical.

### Exit codes
- `0` — gating accuracy ≥ `--threshold` **and** no `--baseline` regressions
- `1` — below threshold, or a case that passed in the baseline now fails
- `2` — setup error: `ANTHROPIC_API_KEY` unset, or **every** call failed on API
  access (bad key / billing / outage) — that's not a quality result, so it never
  reports a misleading 0%.

### Run outputs (`results/`)

**Every run** (including failed/exit-2 ones) auto-writes its full report to
`results/eval-<UTC-timestamp>-<set>[-batch].json` — no flag needed. Each file holds
the run metadata (timestamp, set, mode, repeat, threshold, total calls, elapsed,
exit code), the `summary`, any `regressions`, and the per-case `expected` /
`produced` / verdict for all cases. The path is printed at the end of each run.

`results/` is **gitignored** — these are transient run logs, not committed
artifacts. The one committed reference is `eval-baseline.json` in the package root
(the `--baseline` comparison target); promote a good run to it by copying, e.g.
`cp results/eval-<ts>-all.json eval-baseline.json`. `--json PATH` still writes the
same report to an explicit location if you want one outside `results/`.

## When to run

**Governing rule: run the eval + a baseline diff before merging ANY change that
affects how a raw location string becomes structured locations.** Concretely:
- `api/services/llm_client.py` — `SYSTEM_PROMPT`, `FEW_SHOT_GUIDE`, `HAIKU_MODEL`,
  `MAX_TOKENS`, `_LOCATIONS_SCHEMA`, or the `CanonicalLocation` validators.
- `api/services/location_normalization.py` — `normalize_string` / `lookup_alias`
  and the pipeline writers.
- `api/tasks/normalize_location.py` — orchestration glue and `CONFIDENCE_FLOOR`.
- `api/tasks/scan_unnormalized.py` — the safety-net.
- `api/services/location_admin.py` + the `routers/admin.py` location endpoints
  (manual overrides / re-normalize-all) and the `LocationSpec` model in `models.py`.
- The `anthropic` SDK pin in `api/requirements.txt` (model/SDK bump).
- Any new module added to the location-normalization feature.

Also run it:
- **Before a `re-normalize-all` backfill** (admin `POST /api/admin/locations/re-normalize-all`) — confirm quality before spending real budget across the corpus.
- As a **periodic drift spot-check** when in doubt about model drift.
- **The first time `ANTHROPIC_API_KEY` is set in Railway prod** — run it locally against the same key/model to confirm the structured-outputs path works end-to-end.

## The golden set

- `golden_set.py` — ~40 hand-written curated cases spanning every category
  (simple, reversed, multi via `;`/`/`/`or`/newline, remote, region/country-scoped
  remote, parenthetical/building codes, region-only, country-only, accents,
  misspelling, ambiguous, low-confidence). Does **not** reuse the model's few-shot
  inputs verbatim (memorized examples are worthless).
- `prod_sample.json` — ~70 hand-labeled real prod strings (40 top-frequency + 30
  long-tail), labeled by geographic judgment. **`_meta`** records the pull date
  (2026-06-13), corpus size, and the exact queries.

Cases marked `"gating": false` are **reported but not pass/fail** — genuinely
ambiguous shapes (region/country-scoped remotes, bare international cities needing
country inference, metros, misspellings, few-shot-memorized strings). They keep
the headline number clean while still surfacing what the model does.

### Refreshing `prod_sample.json`

Re-run the two queries in `prod_sample.json["_meta"]["queries"]` against prod
(read-only `mcp__postgres-prod__query`), then **hand-label** `expected` by
geographic judgment — do **not** relabel by running the current model (that bakes
in today's mistakes). Update `_meta.pulled_on` and `_meta.corpus_at_pull`.

## Cost & status

- A full `--set all` run is **~110 LLM calls ≈ a few cents** of Haiku. **Never CI.**
- **Initial baseline: 100% gating accuracy (66/66)** — captured 2026-06-13 against
  `claude-haiku-4-5-20251001`, 110 cases (66 gating), `--repeat 3` majority vote,
  0 API errors. Saved to `eval-baseline.json` (the `--baseline` reference for
  regression diffs).
  - Two `SYSTEM_PROMPT` rules were added to reach 100% on genuinely-ambiguous
    inputs: prefer the standard short city name ("New York", not "New York City")
    and treat a bare city-state ("Singapore") as `kind='country'`.
  - All region/country-scoped remotes round-tripped with geography preserved
    (`US - AZ - Remote` → `Remote (AZ, US)`, `CA-Quebec-Remote` → `Remote (QC, CA)`),
    confirming the `CanonicalLocation` / `LocationSpec` schema fix works on the live model.
  - The model is nondeterministic — gate on `--repeat 3` (majority) for a stable
    number; a single `--repeat 1` run can flip an ambiguous case. Re-capture the
    baseline after any intentional prompt/model change.
