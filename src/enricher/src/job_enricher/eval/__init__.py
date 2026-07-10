"""Evaluation harness: pure scorer + golden-set builder + scorecard/gate runner.

Runnable in three places against the SAME scoring.py:
  - here (job-enricher): `cli eval` over golden/seed
  - the personal dir / this session: import job_enricher.eval.scoring directly
  - JVN: a thin pytest that imports the same pure functions (vendored or path-added)
so the regression gate is identical everywhere.
"""
