"""Evaluation harness: pure scorer + golden-set builder + scorecard/gate runner.

Two facets, TWO POOLS, two denominators:
  - CATEGORY / level / tags / location — gated on `label_source == 'human'`.
  - SUBCATEGORY — gated on `gold_subcategory_provenance`, a SEPARATE column with
    a DISJOINT vocabulary (`human | human_audited | prelabel_agreed | contract`),
    scored ONLY under a `software_engineering` gold parent, with its own min-n.

⚠ CORRECTION, 2026-08-20. This docstring used to claim the scorer runs in THREE
places against the same scoring.py — naming JVN as the third — and that the
regression gate is therefore the same in all of them. THAT CLAIM IS FALSE and
was verified false: `JVN/src/backend/api/eval/scoring.py` is an unrelated
location-normalization scorer, and NOTHING in JVN imports
`job_enricher.eval.scoring`. There is ONE gate, and it runs here.

It matters because a plan assuming JVN independently re-verifies the gate is
building on a mechanism that does not exist — no second opinion, no cross-repo
cross-check, no safety net if this scorer is wrong.

Runnable in two places against the same `scoring.py`:
  - here (job-enricher): `cli eval` over golden/seed
  - any Python session: import `job_enricher.eval.scoring` directly
"""
