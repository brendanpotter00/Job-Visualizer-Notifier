# START HERE — Custom Company Sources (E7) handoff

**If you are an agent picking this up on a new machine: read this file completely
before doing anything else, then read the three files in §7 in the order given.**

Everything needed to continue is on this branch. Pull it and you have the code,
the plan, the spike evidence, and the decision history.

- Branch: `feat/custom-company-sources-spike`
- PR: [#243](https://github.com/brendanpotter00/Job-Visualizer-Notifier/pull/243)
- Owner: Brendan (`brendanpotter00@gmail.com`)
- Last session: 2026-08-05
- ClickUp epic: [E7 `wdwb1cbnc2`](https://app.clickup.com/t/wdwb1cbnc2) ·
  subtasks 7.1 `wdwb1cbnc3` · 7.2 `wdwb1cbnc4` · 7.3 `wdwb1cbnc5` · 7.4 `wdwb1cbnc6`

---

## 1. What the feature is

A signed-in user pastes a **careers-page URL**. The company is scraped on the
existing 30-minute cadence and shows up in the views that already exist — the
hiring-trend graph, the job list, the company selector — **for that user only**,
plus a small "My Companies" page. Owner's original framing is the voice-note
write-up quoted throughout the ClickUp epic.

Two paths, and **conflating them is how this fails**:

| | input | approach | AI? |
|---|---|---|---|
| **A — fast path** | a URL that resolves to a known ATS (Greenhouse, Ashby, Lever, Gem, Workday, Eightfold) | string parsing + redirect-following + a live probe | **never** |
| **B — hard path** | an arbitrary careers site with no public ATS API | an agent explores **once** at add-time and emits a deterministic **recipe**; the cron replays that recipe forever | one-time only |

The economics that make B viable: a per-run agent costs ~36 browser-hours per
company per month; one-time discovery costs ~10 seconds, once, ever.

---

## 2. Decisions that are LOCKED — do not silently revisit

These came from the owner during a live plan review. **Several contradict the
ClickUp tickets, which were written earlier.** Where they disagree, these win.

| # | Decision | Note |
|---|---|---|
| D1 | **No approval flow anywhere.** Adding a company takes effect immediately, scoped to the adding user. | The tickets describe an admin approval queue. **It is cancelled.** 7.4's `company_requests` pending-queue becomes `company_add_attempts`, a pure audit log that gates nothing. |
| D2 | **Admin observability dashboard instead of a gate** — every add *and attempted add* (including failures and unsupported URLs), per-user counts, costs, most-attempted unsupported domains, plus a **Promote to public** action. | The owner reviews after the fact and promotes what deserves to be shared. |
| D3 | **Global scrape, private visibility.** One `companies` row per company, scraped once; `companies.visibility` (`'public'|'user'`) + a `user_companies` ownership table. User-scoped rows are hidden from the public directory and from auto-enroll; `/api/jobs` serves them only to their owner. | |
| D4 | **My Companies page = list + simple health badge** (checking / active / needs attention), last-updated, open-job count. No run logs, recipes, or error internals shown to users. | Full diagnostics stay admin-only. |
| D5 | **v1 input is a URL only.** No company-name search. | Deliberately deferred. |
| D6 | **Everything behind a feature flag defaulting off.** Rollback = flip the flag or `enabled=false`, never a code revert. | |
| D7 | **Quotas are the only abuse control** (no gate): start at 5 custom companies/user, a sliding-window add cooldown keyed on `user_id`, and a global cap. | |
| D8 | **Budget $0 — free tiers only.** No paid Browserbase plan or any other spend without the owner deciding. | Superseded an earlier "$25 spike cap". |
| D9 | **Spike first, then build.** | Deviated from the epic's 7.1-first order. Spike is now done — see §4. |
| D10 | **Intel and Cisco are first-class acceptance targets.** | Owner-named. Both **pass today** — see §4. |

### The one thing most likely to be gotten wrong

**A runtime *browser* is not runtime *AI*.** These are independent:

- **AI/agent** = works out *how* a site serves its jobs. Runs **once**, at
  add-time. Never on the cadence. This is non-negotiable.
- **A browser** = a runtime tool for JS-heavy sites. Would be fine and free if
  needed — this repo already runs deterministic Playwright hourly for
  Google/Apple/Microsoft at zero marginal cost.

The spike found **no target needed a runtime browser at all**, so the
recommendation is to **not implement `browser_dom`** (§4).

---

## 3. Where things stand

| | status |
|---|---|
| 7.2 spike | ✅ **done — GO.** `docs/spikes/2026-08-browser-agent-discovery.md` |
| PR 1 — backend foundation | ✅ **done, in PR #243**, reviewed and fixed |
| PR 2 — recipe runtime | ⬜ **not started** — next up. Spec: `PLAN.md` §PR 2 |
| PR 3 — ownership + UX + admin dashboard | ⬜ not started. Spec: `PLAN.md` §PR 3 |

Commits on this branch (oldest first):

```
d188289  spike(recipes): harness for one-time discovery to deterministic scrape recipe
a2bbb78  spike(recipes): six targets discovered, all http_json/http_html - no runtime browser
a2fcd3c  docs(spike): GO verdict - one-time discovery yields deterministic recipes, $0
ed544b0  feat(companies): SSRF url_guard + ATS link resolver + resolve endpoint
5d7f06d  fix(companies): close review findings on url_guard and ATS discovery
```

### What PR 1 shipped

A three-layer resolution ladder, because **the careers URL a user actually
pastes is usually not a recognisable ATS URL**:

```
L0  resolve_ats_url()      pure, IO-free, urllib.parse only
L1  follow_to_ats()        follows redirects, url_guard-checks EVERY hop, feeds each back into L0
L2  sniff_embedded_ats()   fetches the landing page + a small candidate sub-path list,
                           regex-scans for known ATS URLs, feeds hits back into L0
```

Plus `services/url_guard.py`, the SSRF boundary — the first surface in this
product where user input becomes an outbound request from a backend sitting next
to production Postgres. Files: `src/backend/api/services/{url_guard,
ats_link_resolver,ats_discovery}.py`, `POST /api/companies/resolve`, 222 tests.

---

## 4. Findings that should change how you build the rest

1. **Don't implement `browser_dom`.** Zero of six working spike targets needed a
   runtime browser — including Meta, whose entire 801-job catalogue comes from
   **one forgeable HTTP POST** (the `lsd` token must be *present* but its value
   isn't validated for logged-out traffic; the real gate is Chrome-plausible
   headers). The sibling `job-watcher` repo drives Playwright for that same data
   only because it never tried forging the request. Ship `http_json` +
   `http_html` only. This also moots 7.3's "where does execution run" question:
   **the Railway worker is fine**, Playwright never enters the hot path.
2. **Both owner-named acceptance targets are Workday underneath**, and neither
   is resolvable by string parsing:
   - `jobs.intel.com` → `corpredirect.intel.com` → `intel.wd1.myworkdayjobs.com`
     — Workday after two redirects. **681 jobs**, verified live.
   - `jobs.cisco.com` → `careers.cisco.com`, a **Phenom** front end whose apply
     links point at Workday. Found by L2 sniffing. **1,071 jobs**, verified live.
3. **`total_path` is the most important thing the spike added.** Assert the
   harvest against the source's *own declared total*. `expected_min_jobs` only
   catches a collapse to near-zero; `total_path` catches a **partial** scrape —
   the 2026-03-29 false-closure shape. Require it wherever a source publishes one.
   The near-miss that proved it: `tesla.cn` serves plain HTTP a clean 200 with 28
   China-only jobs sharing **zero ids** with the real 7,597-job board. A recipe
   built on it would have replayed green forever while missing 99.6% of the company.
4. **Silent scope changes are as dangerous as silent emptiness.** A real harness
   bug: paginating a *filtered* board with httpx `params=` replaces the whole
   query string, turning a 76-job filtered search into the 10,000-job global one
   — passing every check while scraping the wrong thing. Merge cursors into the URL.
5. **Phenom is worth a 7th first-class ATS client eventually** — it's a platform
   with a tenant-generic API (`POST /widgets`, `ddoKey=refineSearch`, verified
   returning `totalHits=1060` for Cisco) and it ships a completeness oracle. But
   **not on the critical path**, because Cisco resolves to Workday. Let the
   admin dashboard's unsupported-domain panel decide when it earns its own client.
6. **Recommended scope call (from the plan, owner not yet asked to ratify):**
   ship the ATS path and park non-ATS URLs as `unsupported`; **do not**
   productionise agent discovery in PR 3. Reasoning in `PLAN.md` §1.1. Ship the
   instrument (the unsupported-domain panel) before the engine.

---

## 5. Environment setup on a new machine

### Repo and branch
```bash
git clone https://github.com/brendanpotter00/Job-Visualizer-Notifier.git
cd Job-Visualizer-Notifier
git checkout feat/custom-company-sources-spike
```

### ⚠️ The dev-database trap that will waste your afternoon

Running the backend suite may produce **~125 failures and/or 1,300+ errors that
have nothing to do with your changes.** Two distinct causes:

1. **Alembic revision not found.** The shared `jobscraper` dev DB may be stamped
   with a migration that exists only on another local branch (on the owner's
   machine, `a3c32c2aa4d3` from the unmerged `fix/job-freshness-sidecar-unit23`).
   Alembic then can't locate the DB's own revision and every DB-fixture test errors.
2. **Procrastinate tables live in `public`** and are shared across the per-test
   schemas, so job counts leak between tests (`assert 10 == 5`).

**Workaround used last session** — give this branch its own database:

```bash
docker compose up -d postgres     # or reuse the running jobscraper-postgres container
docker exec jobscraper-postgres psql -U postgres -c "CREATE DATABASE jobscraper_wt2;"

# install Procrastinate's schema (it is NOT created by alembic or create_all)
cd src/backend
DATABASE_URL="postgresql://postgres:postgres@localhost:5432/jobscraper_wt2" PYTHONPATH=.:../.. \
  ../../.venv/bin/python -c "
import asyncio
from api.tasks.procrastinate_app import procrastinate_app, ensure_schema_async
async def main():
    async with procrastinate_app.open_async():
        await ensure_schema_async(procrastinate_app)
asyncio.run(main())"
```

**Establish your own baseline before blaming your code.** Last session's baseline
on a pristine tree was **125 failed / 1043 passed**; with PR 1 it was
**125 failed / 1265 passed** — same failures, +222 tests. If your failure count
matches the baseline, you did not break anything. To prove it, temporarily move
your new files aside and re-run; that is exactly how PR 1 was cleared.

Do **not** drop and recreate the procrastinate tables piecemeal — `DROP TABLE
CASCADE` leaves the enum types behind and the schema install is not idempotent.
Drop the whole database and recreate.

### Commands
```bash
# backend tests (from src/backend)
TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:5432/jobscraper_wt2" \
  ../../.venv/bin/python -m pytest api/tests -q
../../.venv/bin/python -m mypy                 # must stay clean, 74 files
# alembic must be run from the REPO ROOT (alembic.ini lives there), not src/backend
cd <repo root> && .venv/bin/python -m alembic heads    # must be a single head

npm run type-check                              # frontend, must be clean
```

- Python venv: `.venv` at the repo root (Python 3.13). The system `python3` is
  3.8 and cannot install current Playwright — always use the repo venv.
- The spike harness has its **own** venv at
  `scripts/one_off/recipe_spike/.venv` (gitignored). Recreate with the commands
  in `scripts/one_off/recipe_spike/README.md`. Keep it separate; do not pollute
  the repo venv.
- Node: the frontend's vitest hangs silently on Node < 22.12.0. Use nvm 22.14.0.

### Credentials / external services
- **No Browserbase credentials exist.** The cloud comparison arm
  (`capture_browserbase.py`, `BROWSERBASE_SETUP.md`) is written but never ran. It
  needs `BROWSERBASE_API_KEY` + `BROWSERBASE_PROJECT_ID` in `.env.local` (free
  tier). **Recommendation: skip it** — see §6.
- Read-only prod Postgres is available via the `mcp__postgres-prod__query` MCP
  and was used to verify resolver output against live rows.

---

## 6. Explicitly unfinished — do not assume these are done

1. **Spike replay rounds 2 and 3 never ran.** Durability is proven over *hours*,
   not the planned 48. Max drift observed was 0.03% (one TikTok job genuinely
   closed). To finish:
   ```bash
   ./scripts/one_off/recipe_spike/replay_round.sh replay-2   # ~24h after round 1
   ./scripts/one_off/recipe_spike/replay_round.sh replay-3   # ~48h
   ./scripts/one_off/recipe_spike/drift.py                   # per-target verdict
   ```
   These were deliberately *not* scheduled: Claude Code's `CronCreate` jobs are
   session-only and would have silently never fired. Round 1 results are in
   `scripts/one_off/recipe_spike/results/`.
2. **The Browserbase cloud-vs-local comparison never ran** (no credentials). Its
   value dropped sharply once the spike showed six targets need no browser, and
   Tesla proved the IP was never the discriminator anyway. The narrow remaining
   question — do Railway's datacenter IPs get blocked? — is answered far more
   cheaply by running `replay.py` once from Railway.
3. **PR 2 and PR 3 are unwritten.** Full specs in `PLAN.md`.
4. **The owner has not ratified the §4.6 scope recommendation** (ATS-only, park
   non-ATS as unsupported). Confirm before building PR 3's discovery half.
5. **Tesla is a documented NO** and always will be without a standing
   headed-Chrome service. Not a bug to fix.

---

## 7. Reading order

1. **This file.**
2. **`docs/implementations/custom-company-sources/PLAN.md`** (~1,440 lines) — the
   authoritative build spec. §0 owner decisions, §1 cross-cutting decisions
   (incl. the verified Workday matcher rule and the scope recommendation), then
   one section per PR with exact files, contracts, migrations, tests, acceptance
   criteria, rollback, and an ordered task list.
3. **`docs/spikes/2026-08-browser-agent-discovery.md`** — the GO verdict, measured
   per-target results, the **frozen recipe schema v1**, and the known gaps
   deliberately deferred. PR 2 implements this contract.
4. **`docs/implementations/custom-company-sources/SESSION-LOG.md`** — what
   actually happened, in order, including things that were tried and rejected.
   Read it if you want to know *why* something is the way it is.

Supporting evidence, read on demand:
- `scripts/one_off/recipe_spike/README.md` — how the harness works and the
  discovery/replay separation rule.
- `scripts/one_off/recipe_spike/captures/<target>/FINDINGS.md` — per-target
  evidence for amazon, janestreet, meta, spotify, tesla, tiktok. Tesla's is the
  most instructive: 16 probes, a positive ID of Akamai Bot Manager, and the
  `tesla.cn` near-miss.
- `scripts/one_off/recipe_spike/recipe_schema.py` — the **authoritative** schema
  definition. Do not invent a new one.
- `scripts/one_off/recipe_spike/replay.py` — the reference implementation PR 2's
  `recipe_runner.py` should be a hardened port of.
- `scripts/one_off/recipe_spike/test_invariants.py` — offline proofs of the
  safety contract; worth porting to production tests.

Repo context that matters: root `CLAUDE.md`, `src/backend/CLAUDE.md`,
`scripts/CLAUDE.md`, `.claude/skills/add-company/SKILL.md`, and the incidents
`docs/incidents/2026-03-29-mass-job-closure.md` (the failure mode this whole
design defends against) and
`docs/incidents/2026-04-18-migration-filled-postgres-volume/` (why migrations are
autogenerate-only, single head, combined ALTER).

---

## 8. Suggested next action

Build **PR 2** to `PLAN.md` §PR 2. The single most important requirement:

> `run_recipe` **raises** — never returns `[]` — on non-2xx, malformed payloads,
> an unresolvable `records_path`, zero records, a count below
> `expected_min_jobs`, or a shortfall against `total_path`.

An empty list is indistinguishable from "this company stopped hiring", which
feeds the miss counter and closes every job. That is not hypothetical: 3,582
Apple jobs were closed in two runs on 2026-03-29. The regression test encoding
that incident is a required deliverable, not a nice-to-have.

The working loop the owner asked for, and which produced PR 1:

> plan agent → **human reviews and approves** → implementation agent → separate
> review agent → fix agent → verify independently → PR

It caught two Critical issues in PR 1 that the implementer missed, and the fix
agent then corrected two of the *reviewer's* own claims with evidence. Keep the
adversarial structure; don't collapse it into one agent.
