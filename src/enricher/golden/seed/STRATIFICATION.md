# Golden seed stratification

Total rows: **313**  ·  Distinct companies: **92**  ·  `label_source`: **256 draft / 57 human**

> ⚠ **Rewritten for v7, 2026-08-20.** The previous version stated **252** rows where
> the seed then had **273**, and its Category × Level matrix listed `data_engineer`
> (39) and `business` (56) — **neither of which is a v6 or v7 category slug.** Both
> figures had been stale long enough for the file's own note to half-admit it.
>
> ⚠ **Re-measured again after #21** (the MTS work) added **12** rows: 273 -> 285,
> of which 9 are software_engineering. Every table below is re-derived from
> `golden/seed/golden.json`; `tests/test_docs_drift.py` is what caught the drift.
>
> ⚠ **Re-measured after the Forward Deployed Engineer correction** added **28** real
> prod postings (hard_case `forward_deployed`, all human-reviewed): 285 -> 313. It also
> relabelled 4 existing draft FDE rows business_ops -> software_engineering, fixed one
> FDE row's level, and promoted all 8 touched FDE rows to `human` — the human pool
> went 21 -> 57, past `GATE_MIN_N = 50`, but 36 of the 57 are forward-deployed rows, so
> the category gate is now FDE-heavy. Review record:
> `golden/review/forward-deployed-labels.md`.

## Category × Level matrix

| category | intern | new_grad | entry | mid | senior | senior_plus | manager | **total** |
|---|---|---|---|---|---|---|---|---|
| software_engineering | 3 | 8 | 2 | 69 | 21 | 31 | 22 | **156** |
| business_ops | 1 | 4 | 1 | 26 | 20 | 4 | 13 | **69** |
| data_scientist | 5 | 2 | 1 | 17 | 13 | 10 | 2 | **50** |
| product_manager | 4 | 0 | 0 | 9 | 4 | 11 | 6 | **34** |
| growth | 0 | 0 | 0 | 1 | 1 | 0 | 0 | **2** |
| hardware_engineer | 0 | 0 | 1 | 0 | 0 | 1 | 0 | **2** |
| **total** | 13 | 14 | 5 | 122 | 59 | 57 | 43 | **313** |

## Human / draft split per category

| category | human | draft | total |
|---|---:|---:|---:|
| software_engineering | 36 | 120 | 156 |
| business_ops | 16 | 53 | 69 |
| data_scientist | 0 | 50 | 50 |
| product_manager | 1 | 33 | 34 |
| growth | **2** | **0** | 2 |
| hardware_engineer | **2** | **0** | 2 |
| **total** | **57** | **256** | **313** |

⚠ **`growth` and `hardware_engineer` cannot be strengthened from this seed** — 2
rows each, both already human, **zero draft rows to draw more from**. Each
therefore carries a full 1/6 of a GATED facet off two rows, where one flip moves
the macro by 0.083, four times the gate epsilon. That is why
`category_f1_macro_supported` (min_support=5) exists. See `docs/EVAL-GOLD-POOL.md`.

## Subcategory stratification (the 156 SWE rows)

Subcategory gold now holds **25** rows — `load_truth(facet='subcategory')` — every one
of them a human-reviewed forward-deployed row from the FDE correction, so the pool is
**`forward_deployed`-only** and far below `GATE_MIN_N = 50`; it measures that slug and
nothing else. The table below is what the **title rule layer** types today
(`PARAM_REGEX_COVERAGE = 118/156 = 0.756`, so tier A of the review pass is **38
rows**). It is the closest thing to a support estimate for every other slug until `EV-9b` runs.

| subcategory | rule-typed titles | gold (human) | gold (human_audited) | gold (prelabel_agreed) |
|---|---:|---:|---:|---:|
| `data_engineering` | 33 | 0 | 0 | 0 |
| `forward_deployed` | 28 | 25 | 0 | 0 |
| `ml_engineering` | 23 | 0 | 0 | 0 |
| `backend` | 12 | 0 | 0 | 0 |
| `infrastructure_platform` | 11 | 0 | 0 | 0 |
| `ai_engineering` | 7 | 0 | 0 | 0 |
| `devops_sre` | 5 | 0 | 0 | 0 |
| `frontend` | 4 | 0 | 0 | 0 |
| `full_stack` | 4 | 0 | 0 | 0 |
| `robotics_autonomy` | 3 | 0 | 0 | 0 |
| `embedded_systems` | 2 | 0 | 0 | 0 |
| `mobile` | 2 | 0 | 0 | 0 |
| `security` | 2 | 0 | 0 | 0 |
| `growth_engineering` | 1 | 0 | 0 | 0 |
| `product_engineering` | 1 | 0 | 0 | 0 |
| `qa_testing` | 1 | 0 | 0 | 0 |
| `quantitative` | **0** | 0 | 0 | 0 |

⚠ **A subcategory eval lives or dies on whether the rare slugs have any
support.** `quantitative` matches **zero** titles in this sample; the two newest
slugs, `growth_engineering` and `product_engineering`, match **one each** (the
same row — "Software Engineer, Product Growth"). `quantitative`,
`forward_deployed`, `growth_engineering` and `product_engineering` all have
**zero tag coverage** by design. The eval can say nothing about those slugs until
the seed grows — report that rather than a macro-F1 that quietly omits them.

The 157 non-SWE rows are stamped `subcategories: []` with
`gold_subcategory_provenance: 'contract'` (free, no model calls). ⚠ They make
`subcategory_leak_rate` measurable and are **NEVER** admitted to the gate pool —
admitting them would clear `GATE_MIN_N = 50` three times over on a pool carrying
zero information about the subcategory taxonomy.

## Per-level

| level | rows |
|---|---:|
| `intern` | 13 |
| `new_grad` | 14 |
| `entry` | 5 |
| `mid` | 122 |
| `senior` | 59 |
| `senior_plus` | 57 |
| `manager` | 43 |

`intern` is a standalone tier (`level_includes = ["intern"]`), carved out of
`new_grad` in taxonomy v5 — internships and co-ops with the degree still in
progress.

## Per-hard_case

| hard_case | rows |
|---|---:|
| `none` | 179 |
| `ml_vs_ds` | 35 |
| `forward_deployed` | 28 |
| `hq_ambiguous` | 14 |
| `sales_eng` | 14 |
| `de_vs_ds` | 10 |
| `eng_manager` | 10 |
| `mts_title` | 8 |
| `bilingual` | 6 |
| `early_career_trap` | 5 |
| `mts_not_swe` | 3 |
| `mts_graded` | 1 |

## Distinct companies (rows each)

- snowflake: 20
- openai: 16
- uber: 16
- amazon: 13
- harvey: 12
- spotify: 9
- plaid: 8
- ramp: 8
- tiktok: 8
- gigaml: 7
- palantir: 7
- clickup: 6
- google: 6
- meta: 6
- andurilindustries: 5
- databricks: 5
- elevenlabs: 5
- microsoft: 5
- notion: 5
- perplexity: 5
- twilio: 5
- unity3d: 5
- waymo: 5
- zoox: 5
- cohere: 4
- decagon: 4
- doordashusa: 4
- fireworksai: 4
- apple: 3
- block: 3
- cloudflare: 3
- cursor: 3
- eliseai: 3
- pinterest: 3
- roblox: 3
- salesforce: 3
- scaleai: 3
- sierra: 3
- workweave: 3
- xai: 3
- apex-technology-inc: 2
- appliedintuition: 2
- base-power: 2
- baseten: 2
- braintrust: 2
- browserbase: 2
- cognition: 2
- exa: 2
- figma: 2
- figureai: 2
- happyrobot.ai: 2
- imc: 2
- nominal: 2
- reddit: 2
- sesame: 2
- siftstack: 2
- sunday: 2
- airbnb: 1
- akunacapital: 1
- anthropic: 1
- belvederetrading: 1
- brex: 1
- cisco: 1
- clear: 1
- crunchyroll: 1
- flowengineering: 1
- generalintelligencecompany: 1
- gleanwork: 1
- gradial: 1
- hrt: 1
- instacart: 1
- jumptrading: 1
- krea: 1
- mintlify: 1
- mistral-ai: 1
- nuro: 1
- openevidence: 1
- poke: 1
- posthog: 1
- pylon-labs: 1
- reducto: 1
- salient: 1
- saronic: 1
- sentry: 1
- spacex: 1
- stripe: 1
- togetherai: 1
- typesafe-ai: 1
- vercel: 1
- vizcom: 1
- wafer: 1
- wispr-flow: 1
