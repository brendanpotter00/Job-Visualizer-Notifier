# E7 recipe verifier — the acceptance probe, as a standalone script

The measurement harness behind
`docs/implementations/custom-company-sources/PATH-TO-90-PERCENT.md`. Not production code
and not imported by anything — it is the **acceptance probe prototype**: give it a
candidate replay recipe and it tells you, with real numbers, whether that recipe would
actually work tonight.

It deliberately imports the REAL modules — `recipe_schema.validate_recipe`,
`recipe_runner.run_recipe`, `capture.discover._prove_job_link` — so a PASS here means the
same thing it means on the worker.

## verify_recipe.py — the six criteria

```bash
PYTHONPATH=. .venv/bin/python scripts/one_off/e7_recipe_verifier/verify_recipe.py \
    my_recipe.json --label acme --declared 1234
```

Accepts either a bare script or `{"script": {...}, "board_url": ..., "declared_total": ...}`.

| # | criterion | fails when |
|---|---|---|
| 1 | schema | `validate_recipe` raises |
| 2 | replay | `run_recipe` raises, or returns zero rows |
| 3 | plausible | rows are outside ±10% of the board's declared total |
| 4 | links | `_prove_job_link` cannot prove two real job URLs route |
| 5 | stable_ids | two sweeps disagree (symmetric difference > 0) |
| 6 | oracle | the oracle resolves to a number that contradicts the sweep |

Criterion 5 is the load-bearing one: `MISSED_RUN_THRESHOLD = 2`, so ids that churn close
and reopen every job on the board every run. `--quick` skips it while iterating.

It also runs the link proof a **second** time through a plain redirect-following client and
reports the result as `links_lenient`. `strict FAIL + lenient PASS` means our prover is the
problem, not the recipe — that split is the whole point of the criterion-4 finding.

## adjudicate_links.py — recipe wrong, or prover blind?

```bash
PYTHONPATH=. .venv/bin/python scripts/one_off/e7_recipe_verifier/adjudicate_links.py my_recipe.json
```

Replays the recipe, takes two real job URLs, renders both in Chromium, and returns
`RECIPE_WRONG` / `VERIFIER_TOO_STRICT` / `UNDECIDED`. `_prove_job_link` only ever sees
server-delivered bytes, so a client-rendered job page is byte-identical to a
client-rendered 404 shell — this is how you tell them apart. On the 27-board corpus it
found 10 correct recipes the strict prover had rejected.

## capture.py — local network capture (discovery only)

```bash
.venv/bin/python scripts/one_off/e7_recipe_verifier/capture.py <board_url> --out /tmp/cap [--scroll] [--click Next]
```

Loads the page in local headless Chromium, records every response, and prints a shortlist
of JSON responses ranked by job-array size with each POST body. Costs local CPU only.
**Discovery-time only — nothing here ever runs at replay.**

Requires `playwright` + a Chromium install (`playwright install chromium`).
