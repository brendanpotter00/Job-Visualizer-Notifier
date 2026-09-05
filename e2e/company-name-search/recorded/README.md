# recorded/ — a real paid run, kept so the judge can be re-run for $0

`20260905T021303Z.json` is the `--json` record of an actual `e2e/run.sh company-name-search`
run. It is not a hand-written fixture: every `attempts[].body` is the response the real
`POST /api/companies/search-by-name` gave to the real Browserbase Search on that day.

| | |
|---|---|
| Recorded | 2026-09-05 (run id `20260905T021303Z`) |
| Cost then | 39 Browserbase Search calls ≈ **$0.273** |
| Cost to replay | **$0.00** — no network, no key, no backend |
| Result | `21/21 passing` + `citadel` on its own `known` line |
| Cases | 22 (21 graded, 1 `known_limitation`) |

## What it is for

```bash
.venv/bin/python e2e/company-name-search/intent_test.py --replay \
    e2e/company-name-search/recorded/20260905T021303Z.json
```

`--replay` re-judges stored bodies through the **same `judge()`** a live run uses, so
`truth` provenance, the job-list shape rule (recorded truth *and* returned answers), the
`vacuous` rule and `known_limitation` are all enforced without spending anything. That
makes it the right first check for **every assertion change**: tighten a rule, replay, and
see which recorded answers stop passing — $0 instead of another $0.27.

It is also what lets the `verify-onesecondswe` skill carry this feature at $0
(`.claude/skills/verify-onesecondswe/helpers/name_search.sh`).

## What it is NOT

**It is not evidence the feature still works.** It is the answer the live web gave on
2026-09-05. Boards move — Poke's went from live to HTTP 404 in 24 hours — and Browserbase
Search results vary between calls. A green replay proves the judge and the plumbing are
intact; only `e2e/run.sh company-name-search` (~$0.27) proves the feature.

## Re-record it when `cases.toml` gains a case

`--replay` silently skips a case with no stored body, so the pass line would shrink with
no explanation. After adding cases:

```bash
e2e/run.sh company-name-search            # the paid run, writes artifacts/<run>/results.json
cp e2e/company-name-search/artifacts/<run>/results.json \
   e2e/company-name-search/recorded/<run>.json
```

Then update the path in `helpers/name_search.sh` and `helpers/name_search.spec.ts`, and
delete the old file — two recordings invite replaying the stale one.

**Only commit a run you would have shipped on.** A recording of a red run becomes a
fixture that teaches the suite its failures are normal. And check it carries no secret
before committing: bodies only, never headers — the current file greps clean for
`eyJ`/`Bearer`/`BROWSERBASE`/`api_key`/`token`.
