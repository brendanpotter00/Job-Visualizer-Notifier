# e2e — regression gates

Runs **before** any agent says "ready to test" (see root `CLAUDE.md` and
`.claude/skills/e2e-gate/SKILL.md`). Each subdirectory under `e2e/` is a **section** — one
feature area's end-to-end gate. `e2e/shared/` is feature-agnostic infrastructure every
section reuses: the stack (backend/frontend/DB), auth (mint a real token against a patched
JWKS seam), DB helpers, and the Playwright base config.

```
e2e/run.sh <section> [--fast] [--case AC-06] [--refresh-db]
```

## Sections

| Section | What it gates | Runtime (full / `--fast`) | Cost |
|---|---|---|---|
| `add-companies` | Add Companies (E7): careers-URL resolve, ATS add, one-time discovery, delete/purge, flags, ownership isolation, idempotency, the published-board-match suggestion | ~8 min full (measured; see PLAN.md report) / ~1 min `--fast` | a few live discovery calls to Claude Haiku on the full run; $0 on `--fast` |
| `company-name-search` | **Type a company name, get its job board** — the intent test over `POST /api/companies/search-by-name`, against a curated case list. See `company-name-search/README.md` | ~60 s full (measured) | **~38–39 live Browserbase Search calls ≈ $0.27 per run** (measured 2026-09-05: 39 calls, $0.273). Prints the count; `--max-searches` caps it; `--validate-only` and `--replay` are **$0** and skip the backend and the key entirely |
| `live-view` | **The discovery live view stays on screen** — five scripted sessions against a real browser, a real cross-origin iframe and a real poll, asserting the frame never blinks while the session is open and really goes when it ends. See `live-view/README.md` | ~3.5 min (measured) | **$0.** Opens no browser session. `--live` opts into exactly one real Browserbase discovery (~1 billed minute) |

Adding a section = one directory under `e2e/` (its own `PLAN.md`, `CASES.md`, `api/`, `ui/`),
one file under `.claude/skills/e2e-gate/sections/`, one row above. See
`add-companies/PLAN.md` §1 for the three-rule convention.

## Which runner owns what

There are **two** front doors to this repo's end-to-end coverage, and they are not
alternatives — they own different things. `e2e/run.sh` is the gate; the
`verify-onesecondswe` skill is the $0 driving surface that a person or an agent reaches
for to *see a feature work*.

| Runner | Owns | Cost |
|---|---|---|
| `e2e/run.sh add-companies` | The Add Companies regression gate — AC-01..AC-12: resolve, add, discovery, delete/purge, flags, ownership, idempotency | $0; ~3 live Haiku calls on a full run, none on `--fast` |
| `e2e/run.sh company-name-search` | The name-search **intent** test against the live web — is the answer still right *today* | **~$0.27** |
| `e2e/run.sh company-name-search --replay <f>` / `--validate-only` | The same judge over recorded bodies / the case-file rules | **$0** (no backend, no key) |
| `e2e/run.sh live-view` | Live-view **continuity** — LV-01..LV-05, is the frame on screen from first paint until the session really ends, and which closer fired | $0 (`--live`: one billed browser-minute) |
| `verify-onesecondswe` skill | Driving the app the way a user does through `window.__webmcp__`, plus the two surfaces the shim cannot reach: `@live-view` (URL **integrity** + liveness) and `@name-search` (the typed name reaches the endpoint **verbatim**) | **$0**, except `helpers/name_search.sh --live` which delegates straight back to `e2e/run.sh` |

The skill does not re-implement any judging. `helpers/name_search.sh` shells out to this
section's `intent_test.py`, and `helpers/name_search.sh --live` `exec`s `e2e/run.sh`. One
judge, one case file, two entry points.

**Deliberately still separate:** the `add-companies` gate (AC-01..AC-12) is not folded into
the skill — it is a twelve-case regression gate with its own boards, pre-flight and
BLOCKED semantics, and `features/add-companies.md` points at it rather than duplicating it.

## Non-negotiables (every section)

- Its own backend/frontend/DB — never the owner's `:8000`/`:8100`/`:3000` stack.
- `CAPTURE_USE_BROWSERBASE=false`, asserted at boot. Browser hours are the expensive
  line and no section may ever bill one.
- A blank Browserbase key, asserted at boot — with TWO deliberate exceptions.
  `company-name-search` tests the feature whose first step *is* a paid Browserbase
  Search call, so it requires the key and asserts its presence instead. It still
  refuses to boot with `CAPTURE_USE_BROWSERBASE=true`, so it can bill searches
  ($0.007 each, counted and printed) and can never bill a browser hour. It carries
  its own guards in `company-name-search/stack_app.py` rather than weakening
  `e2e/shared/stack/e2e_app.py`, which protects the far more frequently run gate.
  The second exception is `live-view --live`, and it is the only thing in this repo
  that deliberately bills a BROWSER session. It has to: a hosted live view exists
  only on a Browserbase capture, so a stack that cannot open one cannot observe the
  feature at all, and the root cause of the bug it was built for was the third-party
  frame's own behaviour. It is opt-in, never part of the default run, opens exactly
  one session (~1 billed minute), and carries inverted guards in
  `live-view/stack_app.py`. `e2e/run.sh live-view` with no flag opens nothing.
- Re-runnable back to back with no manual reset.
- A third-party outage reads as **BLOCKED**, never as a code regression (PASS/FAIL/BLOCKED,
  never a silent pass-or-fail binary).
