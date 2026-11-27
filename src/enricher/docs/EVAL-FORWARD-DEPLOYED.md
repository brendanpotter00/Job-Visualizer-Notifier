# EVAL — the Forward Deployed Engineer correction

**Measured 2026-11-27 on the `claude-code` engine** (Haiku classify, Sonnet judge,
`--batch 3`), the full 313-row golden seed, before vs after. Prod runs `ollama` /
`qwen3:32b`, which is not on the machine this was measured on;
`RUNBOOK-forward-deployed-reenrich.md` step 0 repeats the A/B on the prod engine.

| arm | rubric | taxonomy version | prediction tag |
|---|---|---|---|
| **before** | `main`'s SKILL.md + SUBCATEGORIES.md | `v7+4b00f6e98dc6` | `before` |
| **after** | this PR's committed rubric | `v7+1657ea163343` | `after2` |

Both arms ran the same seed (this PR's, so the new FDE rows are in both). **Pools:**
the *human* pool (57 rows, `label_source=human`) is what the gate scores; *all rows*
adds 256 `draft` rows, whose labels are an earlier judge-bootstrapped run's output, so
they measure **agreement with that run, not accuracy** (advisory). 36 of the 57 human
rows are this PR's forward-deployed rows and the human pool has no `data_scientist`
row, so the gate is FDE-heavy; the draft pool is where a regression elsewhere would show.

## Headline

* **Category: up across the board, one row the other way.** Human pool accuracy
  0.772 → 0.912 classify only, 0.825 → 0.947 with the judge; Software Engineering F1
  0.866 → 0.958, Business Ops F1 0.684 → 0.914. The one category regression is a
  single row: Wispr Flow's "Ex-Founder" posting (gold SWE) read as PM classify-only,
  which moves `product_manager` F1 1.000 → 0.667 on the human pool (1 row of support)
  and 0.985 → 0.971 on all rows. With the judge on it is back to 1.000. Every other
  class held or improved in both pools and both lanes.
* **Subcategory:** `forward_deployed` recall 0.76 → 0.88 (0.72 → 0.88 judged),
  precision 1.00 in both arms; subcategory primary accuracy 0.68 → 0.84.
* **The gate flags location** (0.500 → 0.375 on the 8 human rows that carry location
  gold, i.e. one row). That is a display-string artifact: see *The location flag*.
  Measured the way JVN stores a location, the human pool is 8/8 → 7/8 and every
  replicate of either rubric scores 7–8/8.

## Gate (classify only, human pool, `regression_gate` ε = 0.02)

```
$ cli eval --engine claude-code --tag after2 --judge off --gate --gate-group category \
    --baseline golden/scorecards/scorecard.before.claude-code.judge_off.json
eval --gate: pool=human n=57 groups=category allow_draft=False
eval --gate: REGRESSION
  - location_primary_accuracy: 0.3750 < baseline 0.5000 - 0.02
```

## Classify only (judge off) — the gated lane

#### human gold (gated) — n=57

| metric | before | after | Δ |
|---|---:|---:|---:|
| category_accuracy | 0.772 | 0.912 | +0.140 |
| category_f1_macro | 0.610 | 0.641 | +0.031 |
| category_f1_macro_supported | 0.775 | 0.936 | +0.161 |
| level_exact_accuracy | 0.825 | 0.860 | +0.035 |
| level_filter_consistent_accuracy | 0.825 | 0.860 | +0.035 |
| tags_f1 | 0.382 | 0.387 | +0.005 |
| tags_jaccard | 0.249 | 0.250 | +0.001 |
| location_primary_accuracy | 0.500 | 0.375 | -0.125 |
| subcategory_primary_accuracy | 0.680 | 0.840 | +0.160 |
| subcategory_leak_rate | 0.048 | 0.048 | +0.000 |

| category | support | P before | P after | R before | R after | F1 before | F1 after | ΔF1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| business_ops | 16 | 0.591 | 0.842 | 0.812 | 1.000 | 0.684 | 0.914 | +0.230 |
| data_scientist | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | +0.000 |
| growth | 2 | 0.500 | 1.000 | 0.500 | 0.500 | 0.500 | 0.667 | +0.167 |
| hardware_engineer | 2 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | +0.000 |
| product_manager | 1 | 1.000 | 0.500 | 1.000 | 1.000 | 1.000 | 0.667 | -0.333 |
| software_engineering | 36 | 0.935 | 0.971 | 0.806 | 0.944 | 0.866 | 0.958 | +0.092 |

`forward_deployed` subcategory over the 25 human-labelled SWE rows: recall 0.760 -> 0.880, precision 1.000 -> 1.000

#### all rows (human + draft, advisory) — n=313

| metric | before | after | Δ |
|---|---:|---:|---:|
| category_accuracy | 0.866 | 0.907 | +0.041 |
| category_f1_macro | 0.624 | 0.647 | +0.023 |
| category_f1_macro_supported | 0.624 | 0.776 | +0.152 |
| level_exact_accuracy | 0.802 | 0.802 | +0.000 |
| level_filter_consistent_accuracy | 0.802 | 0.805 | +0.003 |
| tags_f1 | 0.229 | 0.230 | +0.001 |
| tags_jaccard | 0.140 | 0.140 | +0.000 |
| location_primary_accuracy | 0.708 | 0.682 | -0.027 |
| subcategory_primary_accuracy | 0.680 | 0.840 | +0.160 |
| subcategory_leak_rate | 0.076 | 0.070 | -0.006 |

| category | support | P before | P after | R before | R after | F1 before | F1 after | ΔF1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| business_ops | 69 | 0.836 | 0.923 | 0.812 | 0.870 | 0.824 | 0.896 | +0.072 |
| data_scientist | 50 | 0.911 | 0.955 | 0.820 | 0.840 | 0.863 | 0.894 | +0.030 |
| growth | 2 | 0.100 | 0.111 | 0.500 | 0.500 | 0.167 | 0.182 | +0.015 |
| hardware_engineer | 2 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | +0.000 |
| product_manager | 34 | 1.000 | 0.971 | 0.971 | 0.971 | 0.985 | 0.971 | -0.014 |
| software_engineering | 156 | 0.915 | 0.931 | 0.897 | 0.949 | 0.906 | 0.940 | +0.034 |

`forward_deployed` subcategory over the 25 human-labelled SWE rows: recall 0.760 -> 0.880, precision 1.000 -> 1.000

#### Rows whose category correctness changed

| row | gold | before | after | label |
|---|---|---|---|---|
| uber — Staff Machine Learning Engineer – Ranking & Recommendations (Generativ | software_engineering | data_scientist | software_engineering | draft FIXED |
| spotify — Senior Staff Machine Learning Engineer - Agentic Systems | software_engineering | data_scientist | software_engineering | draft FIXED |
| zoox — Part-Time Student Worker – Firmware Engineer (FW Thermal/Body) | software_engineering | hardware_engineer | software_engineering | draft FIXED |
| unity3d — Senior Machine Learning Engineer, Vector Core Modeling | data_scientist | software_engineering | data_scientist | draft FIXED |
| figureai — Humanoid Robot Operator - Commercial Launch Team | business_ops | hardware_engineer | business_ops | draft FIXED |
| spacex — Starlink Growth Lead, Kansas | business_ops | business_ops | growth | draft REGRESSED |
| ramp — Senior Lead, Tech and Product Communications | business_ops | growth | business_ops | draft FIXED |
| workweave — Forward Deployed Engineering Manager | software_engineering | business_ops | software_engineering | human FIXED |
| wispr-flow — Ex-Founder | software_engineering | software_engineering | product_manager | human REGRESSED |
| workweave — Founding Support Engineer | business_ops | software_engineering | business_ops | human FIXED |
| doordashusa — Service Technician, Service Operations, Labs | business_ops | hardware_engineer | business_ops | human FIXED |
| twilio — Principal, Marketing Architecture & Strategy | business_ops | growth | business_ops | human FIXED |
| braintrust — Forward Deployed Engineer | software_engineering | business_ops | software_engineering | human FIXED |
| cognition — Forward Deployed Engineer - Doha | software_engineering | business_ops | software_engineering | human FIXED |
| exa — Forward Deployed Engineer, NYC | software_engineering | business_ops | software_engineering | human FIXED |
| google — Forward Deployed Engineer, DeepMind | software_engineering | business_ops | software_engineering | human FIXED |
| flowengineering — Forward Deployed Engineer | software_engineering | business_ops | software_engineering | human FIXED |

## Classify + judge (judge on every row)

Prod judges only rows below `judge:confidence_ceiling` (0.85); this run judges every
row, the stricter case. The judge no longer overturns Cloudflare's FDE (the reason the
rubric was tightened — see the last section); the two human SWE rows it still misses
are Workweave's "Forward Deployed Engineering Manager" and IMC's "Information Security
Engineer" (the latter missed in both arms).

#### human gold (gated) — n=57

| metric | before | after | Δ |
|---|---:|---:|---:|
| category_accuracy | 0.825 | 0.947 | +0.123 |
| category_f1_macro | 0.665 | 0.910 | +0.246 |
| category_f1_macro_supported | 0.828 | 0.943 | +0.115 |
| level_exact_accuracy | 0.877 | 0.842 | -0.035 |
| level_filter_consistent_accuracy | 0.877 | 0.842 | -0.035 |
| tags_f1 | 0.402 | 0.403 | +0.001 |
| tags_jaccard | 0.266 | 0.263 | -0.004 |
| location_primary_accuracy | 0.500 | 0.375 | -0.125 |
| subcategory_primary_accuracy | 0.640 | 0.880 | +0.240 |
| subcategory_leak_rate | 0.000 | 0.000 | +0.000 |

| category | support | P before | P after | R before | R after | F1 before | F1 after | ΔF1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| business_ops | 16 | 0.640 | 0.842 | 1.000 | 1.000 | 0.780 | 0.914 | +0.134 |
| data_scientist | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | +0.000 |
| growth | 2 | 1.000 | 1.000 | 0.500 | 0.500 | 0.667 | 0.667 | +0.000 |
| hardware_engineer | 2 | 1.000 | 1.000 | 0.500 | 1.000 | 0.667 | 1.000 | +0.333 |
| product_manager | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | +0.000 |
| software_engineering | 36 | 1.000 | 1.000 | 0.778 | 0.944 | 0.875 | 0.971 | +0.096 |

`forward_deployed` subcategory over the 25 human-labelled SWE rows: recall 0.720 -> 0.880, precision 1.000 -> 1.000

#### all rows (human + draft, advisory) — n=313

| metric | before | after | Δ |
|---|---:|---:|---:|
| category_accuracy | 0.869 | 0.907 | +0.038 |
| category_f1_macro | 0.679 | 0.742 | +0.063 |
| category_f1_macro_supported | 0.679 | 0.742 | +0.063 |
| level_exact_accuracy | 0.821 | 0.808 | -0.013 |
| level_filter_consistent_accuracy | 0.821 | 0.811 | -0.010 |
| tags_f1 | 0.231 | 0.234 | +0.003 |
| tags_jaccard | 0.141 | 0.141 | +0.001 |
| location_primary_accuracy | 0.716 | 0.686 | -0.030 |
| subcategory_primary_accuracy | 0.640 | 0.880 | +0.240 |
| subcategory_leak_rate | 0.076 | 0.057 | -0.019 |

| category | support | P before | P after | R before | R after | F1 before | F1 after | ΔF1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| business_ops | 69 | 0.819 | 0.923 | 0.855 | 0.870 | 0.837 | 0.896 | +0.059 |
| data_scientist | 50 | 0.929 | 0.953 | 0.780 | 0.820 | 0.848 | 0.882 | +0.034 |
| growth | 2 | 0.100 | 0.111 | 0.500 | 0.500 | 0.167 | 0.182 | +0.015 |
| hardware_engineer | 2 | 0.250 | 0.400 | 0.500 | 1.000 | 0.333 | 0.571 | +0.238 |
| product_manager | 34 | 1.000 | 1.000 | 0.971 | 0.971 | 0.985 | 0.985 | +0.000 |
| software_engineering | 156 | 0.914 | 0.930 | 0.891 | 0.942 | 0.903 | 0.936 | +0.034 |

`forward_deployed` subcategory over the 25 human-labelled SWE rows: recall 0.720 -> 0.880, precision 1.000 -> 1.000

#### Rows whose category correctness changed

| row | gold | before | after | label |
|---|---|---|---|---|
| apex-technology-inc — Cybersecurity Engineer/Architect | software_engineering | business_ops | software_engineering | draft FIXED |
| uber — Staff Machine Learning Engineer - Causal Inference | software_engineering | software_engineering | data_scientist | draft REGRESSED |
| spotify — Senior Staff Machine Learning Engineer - Agentic Systems | software_engineering | data_scientist | software_engineering | draft FIXED |
| unity3d — Junior Test Engineer | software_engineering | business_ops | software_engineering | draft FIXED |
| plaid — Senior Machine Learning Engineer (Research Scientist) - DFAI | data_scientist | software_engineering | data_scientist | draft FIXED |
| pinterest — Sr. Machine Learning Engineer, Responsible AI– Applied Research Scienc | data_scientist | data_scientist | software_engineering | draft REGRESSED |
| meta — Research Engineer, Monetization AI | data_scientist | software_engineering | data_scientist | draft FIXED |
| meta — AI Research Engineer - Social Products (Technical Leadership) | data_scientist | software_engineering | data_scientist | draft FIXED |
| spacex — Starlink Growth Lead, Kansas | business_ops | growth | business_ops | draft FIXED |
| microsoft — Principal Quantum Engineer | hardware_engineer | data_scientist | hardware_engineer | human FIXED |
| braintrust — Forward Deployed Engineer | software_engineering | business_ops | software_engineering | human FIXED |
| cognition — Forward Deployed Engineer - Doha | software_engineering | business_ops | software_engineering | human FIXED |
| exa — Forward Deployed Engineer, NYC | software_engineering | business_ops | software_engineering | human FIXED |
| cloudflare — Forward Deployed Engineer, Professional Services | software_engineering | business_ops | software_engineering | human FIXED |
| google — Forward Deployed Engineer, DeepMind | software_engineering | business_ops | software_engineering | human FIXED |
| flowengineering — Forward Deployed Engineer | software_engineering | business_ops | software_engineering | human FIXED |

## The location flag

The enricher's scorer compares the primary location's **`canonical_name` string**. JVN
does not store that string: `persist_llm_result` runs `location_canonicalize.canonicalize`
first, which canonicalizes the structured codes and **recomputes the city label**, so
"New York, NY" and "New York, NY, USA" both land as `New York, NY, US`, and
"Munich, Germany" and "Munich, Bavaria, Germany" both as `Munich, DE`. The one human
row the gate counts against the after arm is OpenAI's Munich FDE ("Munich, Bavaria,
Germany" → "Munich, Germany"): the same stored location. The rubric diff has no
location text.

Scored both ways, including three extra classify-only replicates per arm of the 11
human rows involved (the 8 location rows plus the 3 `forward_deployed` misses; each
replicate is its own batch, so neighbours differ from the full run):

| run | pool | n | raw string (the gate's metric) | as JVN stores it |
|---|---|---:|---:|---:|
| before | human | 8 | 0.500 (4/8) | 1.000 (8/8) |
| before | all rows | 264 | 0.708 (187/264) | 0.909 (240/264) |
| after | human | 8 | 0.375 (3/8) | 0.875 (7/8) |
| after | all rows | 264 | 0.682 (180/264) | 0.886 (234/264) |
| before, judge on | human | 8 | 0.500 (4/8) | 1.000 (8/8) |
| before, judge on | all rows | 264 | 0.716 (189/264) | 0.917 (242/264) |
| after, judge on | human | 8 | 0.375 (3/8) | 0.875 (7/8) |
| after, judge on | all rows | 264 | 0.686 (181/264) | 0.890 (235/264) |
| before replicate 1 | human | 8 | 0.500 (4/8) | 1.000 (8/8) |
| before replicate 2 | human | 8 | 0.375 (3/8) | 0.875 (7/8) |
| before replicate 3 | human | 8 | 0.375 (3/8) | 1.000 (8/8) |
| after replicate 1 | human | 8 | 0.375 (3/8) | 1.000 (8/8) |
| after replicate 2 | human | 8 | 0.250 (2/8) | 1.000 (8/8) |
| after replicate 3 | human | 8 | 0.125 (1/8) | 0.875 (7/8) |

On all rows the after arm is still a few rows lower as JVN stores it (240 → 234 of
264). Those rows are scattered judgement calls — "New York" vs "New York City" (which
moves both ways), a city vs its region, "Korea" as a country or as Seoul, a remote
scope — plus two real misses where "Canada" came back as the US (Figma, Airbnb). None
is a forward-deployed row. A same-rubric replicate of one 78-row shard moved 1 row
this way and 3 rows on the raw string, so this is at or slightly past the noise band;
a small effect from the longer prompt cannot be ruled out, and is worth watching in
the prod-engine A/B (runbook step 0).

## Noise band

A second run of the **before** rubric on one 78-row shard, same code, same batch size:

| metric (78 rows) | run 1 | run 2 |
|---|---:|---:|
| category_accuracy | 0.923 | 0.936 |
| level_exact_accuracy | 0.667 | 0.718 |
| location_primary_accuracy | 0.705 | 0.667 |
| category_f1_macro_supported | 0.951 | 0.956 |

1 category and 9 levels flipped. The human-pool level moves above are inside it: judge
off 5 fixed / 3 regressed, judge on 1 fixed / 3 regressed, and the same three
regressions in both (a Waymo escalation manager, a Twilio PM, an OpenAI
strategy-and-operations role), none of them a forward-deployed engineer.

## The intermediate rubric

A first version (`v7+e555d3cfe62e`) scored within noise of these numbers classify-only,
but with the judge on it overturned Cloudflare's FDE back to `business_ops` by applying
the Solutions-Engineer "committed product code" test. The committed rubric adds one
sentence: that test is for Solutions / Sales Engineers, never an FDE title. The tables
above are the committed rubric.

## Reproduce

From `src/enricher`, in a dev checkout, once per arm (the before arm with `main`'s two
rubric files checked out over this PR's):

```bash
uv run python -m job_enricher.cli eval-run --engine claude-code --batch 3 --tag <before|after2>
uv run python -m job_enricher.cli eval --engine claude-code --tag <before|after2> --judge off
```

`eval-run` writes `golden/scorecards/predictions.<tag>.claude-code[.judge_off].json`
(gitignored). It is hours of subscription calls; this run split the seed into 4 shards
(re-running one shard's 15 rows whose classify calls failed during a network outage,
and the judge chunks that failed on rate limits, through the same code path).
