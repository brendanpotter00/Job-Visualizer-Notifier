# Taxonomy parity: the artifact is in-tree now

This directory used to hold a **vendored copy** of JVN's
`src/backend/taxonomy.json` (`jvn_facets.json` + a `.sha256`), because the
enricher lived in its own repo. It now lives in the JVN monorepo at
`src/enricher/`, so the copy is gone.

- **Half (a), offline, PR-blocking:** `tests/test_taxonomy_parity.py` reads
  `<JVN>/src/backend/taxonomy.json` directly (`cli.JVN_TAXONOMY_ARTIFACT`).
  A missing file is a test **failure**, never a skip.
- **Half (b), live:** `cli parity-check --base-url <JVN>` (scheduled by
  `scripts/check_taxonomy_parity.sh`) compares the deployed `/api/jobs/facets`.

**Never re-derive the slug list in the enricher.** The backend generates the
artifact with `src/backend/tools/generate_taxonomy_artifact.py`, and its own
`api/tests/test_taxonomy_artifact.py` guards it. To change a slug, change the
backend, regenerate, and keep `job_enricher.taxonomy` in step in the same PR.

`cli parity-check --write-snapshot` is retired: it exits 2 and names the
generator.

This directory stays only so old links resolve.
