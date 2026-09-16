# Phase 0 — the v6→v7 classify-prompt cost (`ENR-LAT-1`)

**Status: part (A) MEASURED. Part (B) NOT RUN — it needs local ollama and a
paused worker, and is deliberately left for a human.**

This step measures the ONE thing nobody else owns and that D3 exists because of:
**what v7 costs the live classify lane.** The seconds-per-row measurement for the
*subcategory-only* prompt is NOT here — that is `P0-5`'s, run through `BF-9`'s
`--dry-run` harness. Three workstreams measuring the same thing is how the drafts
got into trouble.

---

## ⚠ `SKILL_MD_V6_GIT_SHA` — record this or the A/B is unrecoverable

```
SKILL_MD_V6_GIT_SHA = 8ff1eb1401bf19b9d879678262c389e4f45b8cc1
```

The git **blob** SHA of `.claude/skills/taxonomy/SKILL.md` immediately before
`ENR-TAX-2`'s first byte. **Verified against `origin/main` at the start of PR-C**
(`git rev-parse origin/main:.claude/skills/taxonomy/SKILL.md`), before any v7 edit.

`taxonomy_version()` has already moved, so **the v6 arm is only reproducible from
this SHA**:

```sh
git show 8ff1eb1401bf19b9d879678262c389e4f45b8cc1 > /tmp/SKILL-v6.md
```

This is Open Risk #1 in the build plan. Without it there is no v6 baseline.

---

## (A) CHARACTER COST — measured against the committed files

Re-asserted against the committed v7 files rather than re-derived. Measured
2026-08-20 with:

```sh
uv run python -c "
from job_enricher import taxonomy as tax
from job_enricher.engines.prompts import build_classify_prompt, build_judge_prompt
job = {'job_listing_id':'1','source_id':'gh','title':'Software Engineer',
       'company':'Acme','raw_location':'SF','clean_description':'x'*3000}
print(len(tax.read_skill()), len(build_classify_prompt([job])))
"
```

| Quantity | Predicted | **Actual** | Divergence |
|---|---|---|---|
| v6 SKILL.md (chars) | 24,479 | **24,479** | 0.0% |
| v6 SKILL.md (bytes / lines) | 24,619 / 157 | **24,619 / 158** | — |
| v7 SKILL.md (chars) | ~28,785 | **28,285** | **−1.7%** |
| compact §1b (chars / lines) | 3,006 / 30 | **2,228 / 33** | −25.9% (smaller) |
| SUBCATEGORIES.md (chars) | ~6,906 | **8,229** | ⚠ **+19.2%** |
| classify scaffold (chars) | 1,729 | **2,196** | +27% (v7 adds the two contract lines + the two rules sentences) |
| judge scaffold (chars) | 2,246 | **2,636** | +17% (the subcategory-change policy block) |
| one-row job block, 3,000-char description | 3,205 | **3,138** | −2.1% |
| **v7 batch=1 classify prompt** | **~33,719** | **33,619** | **−0.3%** |
| v7 batch=1 judge prompt | — | **34,124** | — |

**The >5% divergence rule:** the plan says a >5% divergence on the classify
prompt means §1b grew during review and should be trimmed before the latency arm
runs. **The classify prompt came in at −0.3% — no trim needed.**

⚠ **The one genuine divergence is `SUBCATEGORIES.md` at +19.2%** (8,229 vs
~6,906). It is **not on the classify path** — it never reaches
`build_classify_prompt` or `build_judge_prompt`, and `ENR-PAR-1` assertion 4
proves that. It raises only the **subcategory-only lane's** per-prompt floor:
measured, a batch of 10 rows renders a 10,580-char prompt, of which the rubric is
~78%. Feed that into `P0-5`'s batch sweep — the rubric amortizes over the batch,
so it is an argument for a larger `backfill:batch_size`, bounded by
`BACKFILL_BREAKER_ECHO_RATIO`.

**What D3 buys, restated with the actual numbers:** the detailed rubric is 8,229
chars. Had it stayed inline, EVERY classify and EVERY judge call would carry it.
At ~38 classify + ~17 judge calls per tick that is ≈ 452,000 chars ≈ 113k tokens
per tick that the split removes.

`_CLASSIFY_PROMPT_MAX_CHARS` is set from this measurement — 33,619 rounded up to
the next 500 = **34,000** — in `tests/test_engines.py`. ⚠ A failure of that
assertion means someone moved detail back into §1b; the fix is to move it to
`SUBCATEGORIES.md`, **not** to raise the constant.

---

## (B) LATENCY, AND THE ABORT CEILING — ⚠ NOT RUN

**This arm requires local ollama and a PAUSED launchd worker. It has not been
run; the numbers below are blank on purpose.**

### The exact commands

```sh
# 0. PAUSE THE WORKER, or state plainly that the numbers are contended.
#    The launchd tick fires every 60s and a tick runs ~6,700s, so a contended
#    run inflates the two arms UNEQUALLY.
launchctl unload ~/Library/LaunchAgents/com.bp.job-enricher.plist

# 1. Materialize the v6 rubric from the recorded blob SHA.
git show 8ff1eb1401bf19b9d879678262c389e4f45b8cc1 > /tmp/SKILL-v6.md

# 2. Build BOTH prompts over the SAME 20 real rows, at batch=1, and time each
#    against local ollama qwen3:32b.
#    ⚠ Call prompts.reset_taxonomy_cache() BETWEEN ARMS. `_taxonomy_text` is
#    lru_cache(maxsize=1); a same-process rerun would otherwise score the v6 text
#    twice and report a delta of ZERO.
uv run python - <<'PY'
import statistics, time
from pathlib import Path
from job_enricher import taxonomy as tax
from job_enricher.engines import build_engine
from job_enricher.engines.prompts import build_classify_prompt, reset_taxonomy_cache

rows = ...            # the SAME 20 real prod rows for both arms
engine = build_engine("ollama", model="qwen3:32b")

def arm(skill_path):
    tax.SKILL_PATH = Path(skill_path)
    reset_taxonomy_cache()                       # ⚠ NOT OPTIONAL
    lat = []
    for row in rows:
        t0 = time.time()
        engine._call(build_classify_prompt([row]))
        lat.append(time.time() - t0)
    lat.sort()
    return statistics.median(lat), lat[int(0.95 * len(lat)) - 1]

print("v6", arm("/tmp/SKILL-v6.md"))
print("v7", arm(".claude/skills/taxonomy/SKILL.md"))
PY

# 3. RESUME THE WORKER.
launchctl load ~/Library/LaunchAgents/com.bp.job-enricher.plist
```

### The four numbers to record

| Arm | p50 (s) | p95 (s) |
|---|---|---|
| v6 | _not run_ | _not run_ |
| v7 | _not run_ | _not run_ |

**Contention state: _not run_** (state "paused worker" or "contended" explicitly —
a number without this is not usable).

### `CLASSIFY_LATENCY_CEILING_PCT` — ⚠ NOT SET

**It cannot be invented.** It is a function of the v6 p50/p95 baseline this step
measures and of the lane's measured throughput:

* the lane does **485 classifications/day** against **495–552 arriving**;
* so the lane is already at or slightly under break-even, and every 1% of added
  latency costs ≈ **4.85 classifications/day** (485 × 0.01, to first order for a
  serial, latency-bound lane).

**Write the arithmetic down next to the number.** The proposed starting point is
**10%** (≈ 48.5 classifications/day) against a `PARAM_CLASSIFY_PROMPT_BUDGET` of
12% on characters — but neither is authoritative until the measured p50 exists.

### ⚠ The three PRE-AUTHORIZED mitigations, in order

Named in advance so the ceiling is actionable instead of a number that gets
waived at 11pm. If the measured p50 delta exceeds the ceiling:

1. **Trim the compact §1b table's glosses.** The 15 rows are ~1,100 of its 2,228
   chars.
2. **Drop the three inline rails to one** — keep `full_stack` exclusivity, the
   only rule whose violation **silently widens a filter** (a
   `[full_stack, backend]` row appears under both, and no downstream code can
   reconstruct the intent).
3. **Remove §1b from `build_judge_prompt` only.** The judge re-derives from §1
   anyway and can be handed subcategories as a pass/fail rather than a
   re-derivation.
