# Location Normalization — Golden-Set Eval Harness (Implementation Plan)

> **For the implementing agent.** This is a self-contained build plan for a
> standalone, on-demand eval that guards the **quality** of Tier-2 location
> normalization (the Claude Haiku call) against prompt/model regressions. It is
> NOT a code-plumbing change — the plumbing already ships and is unit-tested.
> Read the "Why" section, then build the deliverables in order. All file paths
> are relative to the repo root `/Users/brendanpotter/Documents/develop/Job-Visualizer-Notifier`.

**Companion to the main implementation plan.** This doc is a follow-on to the
feature build plan; read it alongside:
- [`PLAN.md`](./PLAN.md) — the location-normalization implementation plan (the
  8 work units, the two-tier cascade, and the Verified-Context Addendum). This
  eval plan references it for prod facts (1,438 distinct strings, `PLAN.md:544`),
  the no-key degradation design (`PLAN.md:578`), and where the eval slots into
  End-to-End Verification (`PLAN.md:481`).
- [`REVIEW_AUDIT.md`](./REVIEW_AUDIT.md) — the review-pass log for the feature.
- [`location-normalization-plan.html`](./location-normalization-plan.html) — the
  rendered/annotated version of the plan.

---

## 1. Why this exists (the gap it closes)

The location-normalization feature (branch `feature/location-normalization`) has
a two-tier cascade:

- **Tier 1** — deterministic alias-cache lookup. Pure/deterministic, already
  unit-tested: `src/backend/api/services/location_normalization.py`
  (`normalize_string`, `lookup_alias`) and `test_location_normalization.py`.
- **Tier 2** — `normalize_location_via_llm()` in
  `src/backend/api/services/llm_client.py:179`, which sends one raw location
  string to **Claude Haiku** (`HAIKU_MODEL = "claude-haiku-4-5-20251001"`,
  `llm_client.py:32`) and parses the structured JSON into
  `list[CanonicalLocation]` (`llm_client.py:46`).

**Every existing test mocks the LLM.** `src/backend/api/tests/test_llm_client.py`
patches `api.services.llm_client.AsyncAnthropic` and feeds canned responses; it
verifies *parsing, schema validation, and the `kind`↔`remote_scope` invariant* —
never the model's actual output. So the test suite catches **code** regressions
but is blind to **quality** regressions: a change to `SYSTEM_PROMPT`
(`llm_client.py:97`), `FEW_SHOT_GUIDE` (`llm_client.py:117`), `HAIKU_MODEL`, the
`_LOCATIONS_SCHEMA` (`llm_client.py:139`), or an Anthropic SDK bump
(`anthropic>=0.107.0,<1.0.0` in `src/backend/api/requirements.txt`) could start
mis-parsing real inputs (reversed order, remote scopes, building codes, accents)
and **no test would fail**.

This harness fills that gap: a curated + prod-sampled **golden set** of
`raw → expected structured fields`, run against the **real** Haiku model, scored
on structured fields, producing a pass/fail report. It doubles as a live smoke
test that the structured-outputs API path
(`output_config={"format": {"type": "json_schema", ...}}`, `llm_client.py:203`)
actually works against the pinned SDK.

### Non-goals (do NOT build these)
- Not a CI gate. It costs real Anthropic spend and the LLM is nondeterministic —
  it is **run on demand by a human**, never in automated CI.
- Not a re-test of Tier 1 / `normalize_string` / the cache (already deterministic
  and unit-tested).
- Not a DB/task test. Target the **client** `normalize_location_via_llm()`
  directly — it makes **no DB calls** (Decision #3), so the harness needs **no
  Postgres**, only `ANTHROPIC_API_KEY`.

---

## 2. Deliverables & file layout

Create a new package `src/backend/api/eval/`:

```
src/backend/api/eval/
├── __init__.py            # empty package marker
├── golden_set.py          # curated edge cases (hand-written, in code)
├── prod_sample.json       # labeled sample pulled from prod (data file)
├── scoring.py             # field-normalization + match/score logic (pure, unit-testable)
├── eval_locations.py      # the runnable CLI entrypoint
└── README.md              # how to run + when to run (also linked from backend CLAUDE.md)
```

Plus a unit test for the **pure** scorer (the only deterministic part):
```
src/backend/api/tests/test_eval_scoring.py
```

And doc updates (see §7).

> **Package note:** `src/backend/api/__init__.py` already exists; `src/` and
> `src/backend/` are PEP-420 namespace packages (no `__init__.py`) — confirmed.
> `python -m` supports this (the documented uvicorn command
> `src.backend.api.main:app` relies on the same fact).

---

## 3. The golden set

### 3a. Case schema

Each case is a dict with a raw input and an ordered list of expected locations.
Only the **structured fields** are gated (per the chosen match rule); `kind` ∈
`{"city","region","country","remote"}` (mirror `_VALID_KINDS`, `llm_client.py:35`).

```python
# golden_set.py — illustrative shape
{
    "id": "multi-semicolon",            # stable slug, used in the report
    "raw": "Sunnyvale, CA, USA; Kirkland, WA, USA",
    "expected": [
        {"kind": "city", "city": "Sunnyvale", "region": "CA", "country": "US", "remote_scope": None},
        {"kind": "city", "city": "Kirkland",  "region": "WA", "country": "US", "remote_scope": None},
    ],
    "gating": True,                     # False => reported but not counted toward pass/fail
    "notes": "two locations split on ';'",
}
```

### 3b. Curated cases (hand-write ~30–50)

**Do NOT reuse the four `FEW_SHOT_GUIDE` inputs verbatim** (`llm_client.py:117-137`:
`"San Francisco, CA"`, `"Sunnyvale, CA, USA; Kirkland, WA, USA"`,
`"Remote - United States"`, `"Remote"`) — testing memorized examples is worthless.
Use fresh-but-similar inputs. Cover at minimum these categories (the prompt at
`llm_client.py:97-115` is what we're stress-testing):

- **Simple city** with/without region/country (`"Austin, Texas"`, `"Toronto, Canada"`).
- **Reversed order** — the prompt promises reordering: `"United States, Washington, Redmond"` → Redmond, WA, US.
- **Multi-location** via `;`, `/`, `or`, `&`, newlines.
- **Remote scopes** — `remote` kind + `remote_scope` ∈ {us, eu, code, global}; verify the `kind='remote'` ⇒ city/region/country all `None` invariant (`llm_client.py:71-90`). Include `"Remote - EMEA"`, `"Remote (US only)"`, `"Fully remote, worldwide"`.
- **Building/site codes & parentheticals** to be stripped: `"Building 92, Redmond, WA (HQ)"`, `"NYC-7 New York, NY"`.
- **Region-only / country-only** kinds: `"California"` (region), `"Japan"` (country).
- **Accents preserved** (string passes through; `normalize_string` keeps diacritics): `"Zürich, Switzerland"`, `"São Paulo, Brazil"`.
- **Ambiguous / hard** cases → set `"gating": False` (reported, not gated): `"EMEA"`, `"Multiple locations"`, `"Various"`.
- **Low-confidence expectation** — at least one genuinely vague input to confirm the model returns confidence `< CONFIDENCE_FLOOR` (0.5, `tasks/normalize_location.py:43`); mark `"gating": False` and assert via the confidence report (§4c), not field match.

### 3c. Prod-sampled cases (`prod_sample.json`)

Pull a real sample from production using the **read-only** `mcp__postgres-prod__query`
MCP. Per the plan addendum there are **1,438 distinct non-null location strings**
(`docs/implementations/locationNormalization/PLAN.md:544`).

1. Query distinct strings with frequency, take a stratified sample (e.g. the
   **top ~40 by frequency** + **~30 random** from the long tail = ~70 cases):
   ```sql
   SELECT location, COUNT(*) AS n
   FROM job_listings
   WHERE location IS NOT NULL AND btrim(location) <> ''
   GROUP BY location
   ORDER BY n DESC
   LIMIT 40;
   -- second query: ORDER BY random() LIMIT 30 (long-tail coverage)
   ```
   (No timezone math here, so the `CLAUDE.md` Postgres-MCP timezone gotcha does
   not apply.)
2. **Hand-label** `expected` for each by geographic judgment. For genuinely
   ambiguous strings, set `"gating": False` so they're reported but don't gate.
   Do **not** label by running the current model and copying its output — that
   tests reproducibility, not correctness, and bakes in today's mistakes.
3. Store as `prod_sample.json` (list of the §3a case dicts). Record the pull date
   and the queries used in a top-of-file comment / README so it can be refreshed.

> Sample size guidance: ~70 prod + ~40 curated ≈ 110 calls per full run ≈ a few
> cents of Haiku. Keep it on this order; this is not the 44k backfill.

---

## 4. Scoring (`scoring.py`) — structured-field match

Pure functions, no I/O, unit-tested by `test_eval_scoring.py`.

### 4a. Field normalization before comparison
- `kind`, `remote_scope`: lowercase, strip; `None` stays `None`.
- `city`: `None`-safe, lowercase, collapse whitespace, strip (reuse the spirit of
  `normalize_string` in `services/location_normalization.py:72`, but field-local).
- `region`, `country`: uppercase, strip (the prompt promises short codes like
  `"CA"`, `"US"`). Treat common aliases as equal where obvious (`"USA"`→`"US"`)
  — keep a tiny explicit alias map, documented, not clever.
- The compared tuple per location: `(kind, city, region, country, remote_scope)`.
  **`canonical_name` and `confidence` are NOT in the match tuple** (chosen rule:
  structured fields only).

### 4b. Per-case verdict
- Build the multiset of normalized tuples for `produced` and `expected`.
- **PASS** iff the two multisets are equal (order-independent). This makes
  multi-location order irrelevant to pass/fail.
- **Additionally** (non-gating, reported): does `produced[0]` (the LLM's first
  location → becomes `is_primary` in `persist_llm_result`,
  `services/location_normalization.py:282-287`) match `expected[0]`? Report
  "primary mismatch" as a soft warning.
- On `LocationLLMError` (`llm_client.py:38`) for a gating case → **FAIL** with the
  exception message as the reason. On `MissingAnthropicKeyError` (`llm_client.py:42`)
  → abort the whole run with a clear message (key not set), not a per-case fail.

### 4c. Confidence reporting (non-gating)
For every produced location, surface its `confidence`. Flag any case whose
`max(confidence)` is below `CONFIDENCE_FLOOR = 0.5` (`tasks/normalize_location.py:43`)
— those would be dropped as `failed` by the real task, so it's useful signal even
when fields match. Cases explicitly designed to be low-confidence (§3b) assert
*on this flag* rather than on fields.

### 4d. Run summary
- Gating accuracy = `gating_pass / gating_total` (the headline number).
- Counts: total cases, gating vs informational, pass/fail, primary mismatches,
  below-confidence-floor, `LocationLLMError`s, API errors.
- Total LLM calls and a rough cost line.
- Wall-clock runtime.

---

## 5. Runner CLI (`eval_locations.py`)

`async` entrypoint (the client is async). Mirror the project's async style; you
may reuse `asyncio.run(...)`.

**Imports** (use package-relative imports so it's invocation-root-agnostic):
```python
from ..services.llm_client import (
    normalize_location_via_llm, CanonicalLocation,
    MissingAnthropicKeyError, LocationLLMError,
)
from ..config import settings
from .golden_set import CURATED_CASES
from .scoring import score_case, summarize, normalize_fields
```

**Flags:**
- `--set {curated,prod,all}` (default `all`).
- `--json PATH` — write the full structured report to JSON (for baseline diffing).
- `--baseline PATH` — compare this run's per-case verdicts to a saved JSON; print
  **only regressions** (cases that passed in baseline and now fail). Exit non-zero
  if any regression.
- `--repeat N` (default 1) — run each case N times; report flakiness (mitigates
  LLM nondeterminism). With N>1, gate on majority verdict.
- `--threshold FLOAT` (default e.g. `0.90`) — minimum gating accuracy; exit
  non-zero if below.
- `--verbose` — print every case, not just failures.

**Concurrency:** run cases with bounded concurrency (e.g. `asyncio.Semaphore(5)`)
so ~110 calls finish quickly without hammering the API. The client is built with
`max_retries=0, timeout=10.0` (`llm_client.py:195`); wrap each call so one
transient `anthropic.APIError`/`APITimeoutError` is retried a couple times with
backoff **inside the harness** (the production retry path is Procrastinate, absent
here) and otherwise counted as an API error in the summary.

**Output:** a readable table (raw → expected vs produced, verdict, confidence) for
failures by default, full table with `--verbose`, then the §4d summary block.

**Exit codes:** `0` = gating accuracy ≥ threshold and no `--baseline` regressions;
`1` = below threshold or regressions; `2` = setup error (e.g. missing key).

---

## 6. How to run (verify these commands work, then put them in the docs)

The key is already configured locally in **`.env.local` at the repo root**
(the user added `ANTHROPIC_API_KEY` there). `Settings()` loads `(".env",
".env.local")` **relative to the current working directory** (`config.py:65`), so
**run from the repo root** so that file is found:

```bash
# from repo root
source .venv/bin/activate
PYTHONPATH=. python -m src.backend.api.eval.eval_locations --set all
```

Alternatives the docs should mention:
- Export the key instead of relying on `.env.local`:
  `export ANTHROPIC_API_KEY=sk-ant-...` then run as above.
- Save a baseline, then later check for regressions:
  ```bash
  PYTHONPATH=. python -m src.backend.api.eval.eval_locations --json eval-baseline.json
  # ...after a prompt/model change...
  PYTHONPATH=. python -m src.backend.api.eval.eval_locations --baseline eval-baseline.json
  ```

The **pure scorer** test runs in normal CI with the rest of the backend suite
(it mocks nothing external):
```bash
cd src/backend && pytest api/tests/test_eval_scoring.py
```

> The eval module uses package-relative imports, so it also runs from
> `src/backend` as `python -m api.eval.eval_locations` — but then `.env.local`
> at the repo root is NOT auto-loaded; you'd have to `export ANTHROPIC_API_KEY`.
> Prefer the repo-root invocation above and document that as the canonical one.

---

## 7. Doc updates (REQUIRED — how to run + when to run)

The user explicitly asked that the docs explain **how** and **when** to run this.
Make these edits as part of the deliverable:

1. **`src/backend/api/eval/README.md`** (new) — the canonical reference:
   - One-paragraph purpose (quality regression guard for Tier-2 Haiku).
   - **How to run** — the exact commands from §6 (repo-root invocation, key in
     `.env.local`, the `--baseline` workflow, the scorer pytest).
   - **When to run** (the trigger list below).
   - How to refresh `prod_sample.json` (the §3c queries + relabel step).
   - Expected cost (~a few cents/run) and that it is **never** part of CI.

2. **`src/backend/CLAUDE.md`** — add a short **"Evals"** subsection (near
   "Testing" / "Key Files") that points to `api/eval/README.md`, states the
   harness needs `ANTHROPIC_API_KEY` and real spend, and lists the canonical
   run command. Keep it brief; link, don't duplicate.

3. **`docs/implementations/locationNormalization/PLAN.md`** — add a line under
   "End-to-End Verification" (around `PLAN.md:481`) noting the golden-set eval
   exists and pointing to this plan + the README.

4. **Memory** (write to the user's memory dir, type `project` or `reference`):
   a one-line pointer that the location-normalization quality eval lives at
   `src/backend/api/eval/` and when to run it — so future sessions know it exists.
   Add the matching line to `MEMORY.md`.

### "When to run" — put this exact trigger list in the README and CLAUDE.md
**The governing rule: run the golden-set eval (and compare to a saved baseline)
before merging ANY change to the location-normalization logic** — if a diff
touches how a raw location string becomes structured locations, run it. The
location logic lives in these modules (this is the concrete enumeration of "any
changes to the location logic", not an exhaustive cap — treat new files in the
same area the same way):
- `src/backend/api/services/llm_client.py` — Tier-2 Haiku: `SYSTEM_PROMPT`,
  `FEW_SHOT_GUIDE`, `HAIKU_MODEL`, `MAX_TOKENS`, `_LOCATIONS_SCHEMA`, or the
  `CanonicalLocation` validators.
- `src/backend/api/services/location_normalization.py` — Tier-1
  `normalize_string` / `lookup_alias` and the pipeline writers.
- `src/backend/api/tasks/normalize_location.py` — the orchestration glue and
  `CONFIDENCE_FLOOR`.
- `src/backend/api/tasks/scan_unnormalized.py` — the safety-net that drives
  re-normalization.
- `src/backend/api/services/location_admin.py` + `routers/admin.py` location
  endpoints — manual overrides / re-normalize-all that write the cache.
- The Anthropic SDK pin in `src/backend/api/requirements.txt` (model/SDK bump).
- Any new module added to the location-normalization feature.

Also run it:
- **Before a `re-normalize-all` backfill** (admin `POST /api/admin/locations/re-normalize-all`)
  that will spend real Hauku budget across the corpus — confirm quality first.
- **As a periodic spot check** when in doubt about model drift.
- **The first time `ANTHROPIC_API_KEY` is set in Railway prod** — run it locally
  against the same key/model to confirm the structured-outputs path works end-to-end.

---

## 8. Acceptance criteria (definition of done for the implementing agent)

- [ ] `src/backend/api/eval/` package created with all files from §2.
- [ ] `golden_set.py` has ≥30 curated cases spanning every §3b category; none
      duplicate the four `FEW_SHOT_GUIDE` inputs verbatim.
- [ ] `prod_sample.json` has ~60–80 hand-labeled cases pulled via the §3c
      queries, with the pull date + queries recorded.
- [ ] `scoring.py` is pure and covered by `test_eval_scoring.py` (field
      normalization, multiset match, primary-mismatch, confidence-floor flag,
      `USA→US` alias) — passes in normal `pytest`.
- [ ] `eval_locations.py` runs from repo root via the §6 command, prints a
      readable report + summary, supports `--set/--json/--baseline/--repeat/--threshold/--verbose`,
      and returns the §5 exit codes.
- [ ] Aborts cleanly with a clear message when `ANTHROPIC_API_KEY` is unset
      (catch `MissingAnthropicKeyError`).
- [ ] A real run on `--set all` completes and reports gating accuracy (record the
      first number as the initial baseline in the README).
- [ ] Docs updated per §7 (README, backend CLAUDE.md, PLAN.md line, memory).
- [ ] No change to production code paths — this is additive tooling only.

---

## 9. File reference index

| Path | Role for this plan |
|---|---|
| `src/backend/api/services/llm_client.py` | Eval target: `normalize_location_via_llm` (`:179`), `CanonicalLocation` (`:46`), errors (`:38`,`:42`), prompt (`:97`,`:117`), model (`:32`), schema (`:139`) |
| `src/backend/api/services/location_normalization.py` | `normalize_string` (`:72`) — comparison-normalization reference; primary-position writer (`:282`) |
| `src/backend/api/tasks/normalize_location.py` | `CONFIDENCE_FLOOR = 0.5` (`:43`) for the confidence report |
| `src/backend/api/config.py` | `anthropic_api_key` (`:51`), `env_file` load order (`:65`) |
| `src/backend/api/tests/test_llm_client.py` | Mock seam reference — what the unit tests do (and why they can't catch quality drift) |
| `src/backend/api/requirements.txt` | `anthropic>=0.107.0,<1.0.0` SDK pin |
| `docs/implementations/locationNormalization/PLAN.md` | Prod facts: 1,438 distinct strings (`:544`), no-key degradation (`:578`) |
| `src/backend/CLAUDE.md` | Backend test conventions; add "Evals" subsection here |
