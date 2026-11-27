# EVAL — the two gold pools

**Status: BOTH RUNS ARE OUTSTANDING.** `EV-2b` (category) and `EV-9b`
(subcategory) each need a block of undivided human review time, and nothing in
the plan substitutes for it. The code, the CLI and the stop conditions are
built and tested; the runs are not performed.

---

## Why this exists

`regression_gate` refuses below `GATE_MIN_N = 50`, and today:

```
load_truth(human_only=True)        -> 21     (273 rows, 252 draft / 21 human)
load_truth(facet='subcategory')    -> 0
```

The only number obtainable is `--allow-draft`, which `report.py` returns 0 from
unconditionally and whose argparse help reads *"never gates, always exits 0"*.
⚠ **So the stop condition on the whole taxonomy change cannot fire under ANY
configuration.** These two runs are what removes that.

⚠ **The admin correction loop is NOT an alternative.** `merge_corrections`
matches only the 273 seeded rows, the triage queue pages `enriched_at DESC` over
~76k listings (a ~0.36% hit rate), and it produced 21 rows in a year. It is a
SUSTAINING mechanism. Any plan claiming it reaches n≥50 on its own is wrong.

---

## Measured composition, today

| category | human | draft | total |
|---|---:|---:|---:|
| software_engineering | 36 | 120 | 156 |
| business_ops | 16 | 53 | 69 |
| data_scientist | 0 | 50 | 50 |
| product_manager | 1 | 33 | 34 |
| growth | **2** | **0** | 2 |
| hardware_engineer | **2** | **0** | 2 |
| **total** | **57** | **256** | **313** |

⚠ Re-measured after the Forward Deployed Engineer correction added 28 real prod
postings and promoted 8 existing FDE rows, all human-reviewed
(`golden/review/forward-deployed-labels.md`). The human pool went 21 -> 57, so
P3's `load_truth(human_only=True) >= 55` now holds **by count** — but 36 of the
57 are forward-deployed rows and `data_scientist` still has **zero** human rows,
so this is not the stratified pool `EV-2b` was meant to build. (Before that, #21's
MTS rows added 12 `draft` rows and left the pool at 21.)

⚠ **`growth` and `hardware_engineer` CANNOT BE STRENGTHENED FROM THIS SEED.**
Two rows each, both already human, **zero draft rows available to draw more**.
On the human pool each therefore carries a full 1/6 of a GATED facet off two
rows, where one flip moves the macro by 0.083 — **four times the gate epsilon**.
That is exactly why `EV-5b`'s `category_f1_macro_supported` (min_support=5)
exists. Raising their support needs `cli build-golden-set`, which must **NOT**
be run mid-A/B: it changes the row set the paired test pairs on.

---

## EV-2b — the CATEGORY pool run (21 → ≥55)

### The draw, verified today

`PARAM_CAT_DRAW_N = 46`, seed `20260820`, stratified proportional to the draft
distribution with a floor of 5 per stratum. Simulated against the live seed:

```
software_engineering 21 · business_ops 10 · data_scientist 9 · product_manager 6   = 46
```

21 existing human + 46 = **67**, clearing `GATE_MIN_N = 50` with margin.
Shrink to 35 only if the measured review rate is worse than ~40 s/row.

### The run, in order

```bash
# 1. pre-label with an INDEPENDENT model
job-enricher prelabel --facet category \
    --engine claude-code --model opus \
    --under-test ollama:qwen3:32b \
    --draw 46 --seed 20260820

# 2. tier + audit-draw. corroborator = the seed's DRAFT label,
#    promote_agreements=false, audit_rate=1.0
job-enricher review-build --facet category

# 3. Brendan decides EVERY row
job-enricher review-render --facet category
open golden/review/category-review.html

# 4. fold the decisions in and write the audit verdict
job-enricher review-apply --facet category
```

⚠ **A MALFORMED DECISION IS A REFUSAL, NOT A NULL LABEL.** `review-apply`
shape-checks every `decision` (and every agreement `prelabel` when promotion is
on) **before it touches a single row**, and raises with the offending
`source_id/job_listing_id` if any is wrong: a list where the category facet
wants one slug, a non-string element, more than 2 subcategory slugs, an
out-of-taxonomy slug. Nothing is written when it raises — fix the file and
re-run, the command is idempotent. Legal shapes stay legal: `[]` ("evaluated,
none apply"), a bare `"backend"` string, and `null` (undecided).

⚠ **`audit_rate: 1.0` and `promote_agreements: false` are not conservatism, they
are the honest consequence of `corroborator_independent: false`.** The 252 draft
labels were produced by the original claude-code workflow (commit `3d6072d`,
classify haiku + judge sonnet), so a claude-code pre-labeller agreeing with them
is **same-FAMILY** evidence. Auditing a sample of same-family agreements
measures nothing, so every drawn row is decided by a human.

⚠ **`opencode` is NOT an independent choice either** — its default model is also
qwen3:32b. `claude-code/opus` is the recommendation.

### Stop condition — checkable, not aspirational

```bash
uv run python -c "from job_enricher.eval.golden import load_truth; print(len(load_truth(human_only=True)))"
```

* `len(load_truth(human_only=True)) >= 55` **AND**
* every drawn row has a non-null `decision`.

⚠ **55, not 50.** One later category-moving correction must not silently drop
the pool back under `GATE_MIN_N` and re-inert the gate.

### The byproduct that is actually the point

`golden/seed/category_audit.json`'s `error_rate` is **`PARAM_PRELABEL_ERROR_RATE`
— the FIRST measured prior for how often a claude-code/opus pre-label is wrong.**
There is no prior for it today. `EV-9b`'s `PARAM_AUDIT_MAX` is DERIVED from it:

```
PARAM_AUDIT_MAX = max(0.05, min(0.15, ceil(PARAM_PRELABEL_ERROR_RATE / 0.05) * 0.05))
```

(implemented as `eval.params.derive_audit_max`, which returns the conservative
floor 0.05 while the measurement does not exist). The draft's flat 0.10 had no
prior behind it.

### ⚠ THE MIXTURE CAVEAT — record it, do not skip it

The 21 pre-existing human rows came from JVN's **needs-human triage feed**
(`docs/ENGINE-COMPARISON.md`: "21 human-corrected rows pulled from prod JVN"),
i.e. **HARD rows**. The new draw is **random**. So **absolute accuracy on the
combined pool is NOT comparable to `baseline.json`'s n=252 draft number.**

The gate is a **DELTA gate on identical rows**; that is what makes the mixture
harmless. Reading the combined pool's absolute accuracy as "the model got worse"
is the mistake this paragraph exists to prevent.

### To fill in after the run

| field | value |
|---|---|
| draw seed / strata | `20260820` / see above |
| final composition per category | _TBD_ |
| measured `error_rate` (`PARAM_PRELABEL_ERROR_RATE`) | _TBD_ |
| review wall-clock | _TBD_ (~25-40 min at ~30 s/row) |
| `len(load_truth(human_only=True))` after apply | _TBD, must be ≥ 55_ |

---

## EV-9b — the SUBCATEGORY pool run (0 → ≥55)

### ⚠ Correct the scope every design track got wrong

The pre-label workload is **120, not 156**. Measured: 313 rows, 156
`software_engineering`, of which **36 are ALREADY `label_source='human'`** and
need no pre-label. (It was 124 of 135 before the Forward Deployed Engineer
correction added 17 human FDE rows and relabelled 4 more into SWE, and 115 of 126
before #21's MTS rows joined the seed. The 25 human FDE rows also already carry
`forward_deployed` subcategory gold with provenance `human`.)

### The run, in order

```bash
# 0. FREE, no model calls: stamp the 150 non-SWE rows contract/[] so
#    subcategory_leak_rate is measurable at all
uv run python -c "from job_enricher.eval.golden import stamp_contract_rows; print(stamp_contract_rows())"

# 1. pre-label — reads the LONG-FORM SUBCATEGORIES.md in full, unlike the
#    per-job classify prompt which reads only the compact section 1b.
#    That separation is precisely what D3 buys.
job-enricher prelabel --facet subcategory \
    --engine claude-code --model opus \
    --under-test ollama:qwen3:32b --seed 20260820

# 2. corroborator = subcategory_rules.rule_label, promote_agreements=true,
#    audit_rate=0.15, stratified by the rule's primary slug with a per-slug floor
job-enricher review-build --facet subcategory

# 3. human review of tiers A + B + the audit sample
job-enricher review-render --facet subcategory

# 4. threshold DERIVED from EV-2b's measured error rate
job-enricher review-apply --facet subcategory --threshold <PARAM_AUDIT_MAX>
```

### Tier A's size is measured

`PARAM_REGEX_COVERAGE`, re-measured over the 156 gold-SWE titles:

```
typed 118 / 156 = 0.756  ->  tier A (untypable, ALL to human) is 38 rows
```

The FDE correction's 21 new gold-SWE rows are almost all typed by the
`forward[\s-]deployed` pattern, so coverage ROSE and tier A grew by only 1.
Before that it was 98/135 = 0.726 (tier A = 37).

It was 94/126 = 0.746 (tier A = 32) before two unrelated things moved it: main's
MTS eval rows (#21) added 9 mostly-untypable house titles to the seed, and the
15 -> 17 slug widening typed exactly one more row. Coverage FELL and tier A grew
by 5 — budget the review pass from 37, not 32.

⚠ The design track's 85/126 was measured against a 7-pattern regex over 13
slugs and does not survive the move to 17 (`ai_engineering`, `quantitative`,
`growth_engineering` and `product_engineering` were added).

### Per-slug title coverage on the gold-SWE rows

| slug | titles typed |
|---|---:|
| data_engineering | 33 |
| ml_engineering | 23 |
| backend | 12 |
| infrastructure_platform | 10 |
| forward_deployed | 8 |
| ai_engineering | 5 |
| devops_sre | 5 |
| frontend | 4 |
| full_stack | 4 |
| robotics_autonomy | 3 |
| embedded_systems | 2 |
| mobile | 2 |
| security | 2 |
| growth_engineering | 1 |
| product_engineering | 1 |
| qa_testing | 1 |
| **quantitative** | **0** |

⚠ **A subcategory eval lives or dies on whether the rare slugs have any
support.** `quantitative` matches ZERO titles in this sample, and
`growth_engineering` / `product_engineering` match ONE each — the same row,
"Software Engineer, Product Growth". `forward_deployed`, `quantitative`,
`growth_engineering` and `product_engineering` all have ZERO tag coverage, so
the eval can say nothing about those four until the seed grows. Say that out
loud in the protocol rather than reporting a macro-F1 that quietly omits them.

### Stop condition

* `len(load_truth(facet='subcategory')) >= 55` **AND**
* `golden/seed/subcategory_audit.json.passed == true`

⚠ **If either fails, SAY SO PLAINLY.** `EV-12`'s G3 cannot run and the
subcategory gate stays **advisory** until a contingency is taken — review all
agreements (~45 more minutes), or ship on G2 + G4 + G5 + G6 only. **What must
NOT happen is quietly lowering `min_n`.**

### To fill in after the run

| field | value |
|---|---|
| `PARAM_AUDIT_MAX` used | _TBD_ |
| tier counts A / B / C | _TBD (A ≈ 32)_ |
| audit sample size | _TBD_ |
| measured audit `error_rate` / `passed` | _TBD_ |
| rows per slug by provenance tier | _TBD_ |
| `len(load_truth(facet='subcategory'))` | _TBD, must be ≥ 55_ |
