---
name: add-company
description: |
  Add (track) a new company end-to-end in this repo: the frontend
  companies.ts entry + COMPANY_IDS enum member, a single-head-safe backend
  Alembic seed migration for the companies table, a changelog.ts announcement,
  and brand logos via the fetch-company-logo skill. This is the single source
  of truth for onboarding a company — a zero-context agent should be able to
  follow it without reading anything else. Use when asked to add, track, or
  onboard a company / a new job board.
trigger_phrases:
  - add a company
  - add a new company
  - track a new company
  - onboard a company
  - add a company to the backend table
  - add a company to the tracked companies
  - start tracking a company's job board
required_tools:
  - Bash
  - Read
  - Edit
  - Write
  - WebFetch
  - WebSearch
mode: read-write
---

# Add a Company

Onboarding one company means **four edits plus logos**, all keyed by a single
lowercase `id` (the slug, e.g. `reducto`, `spacex`, `happyrobot.ai`):

| # | What | File |
|---|------|------|
| 1 | Frontend config entry + enum member | `src/frontend/src/config/companies.ts` |
| 2 | Backend seed migration (one `companies` row) | `src/backend/alembic/versions/<ts>_<rev>_seed_<id>_company.py` |
| 3 | Changelog announcement (top entry) | `src/frontend/src/config/changelog.ts` |
| 4 | Brand logos (icon + wordmark) | `src/frontend/public/logos/{icons,wordmarks}/<id>.png` |
| 5 | *(optional)* curated blurb | `src/backend/api/data/company_profiles.json` |

> **Canonical reference commits** — copy these patterns exactly:
> `246b24e` *Add Reducto (Ashby) company + changelog entry (#157)* (single company),
> `80494df` *Add Sierra (Ashby) company and changelog entry (#135)*,
> `c41d8b7` *Add 8 quant trading firms (#146)* (multiple at once).

Every company added this way flows through the backend `/api/jobs` endpoint: a
backend Procrastinate worker fetches its jobs on a ~30-min cron once the
`companies` row exists. (The only exceptions are Google/Apple/Microsoft, which
use `ats='script'` Python scrapers — **not** added with this skill.)

## Inputs you need first

- **`id`** — lowercase slug, unique, used as the PK and every filename. Keep it
  stable; it's hard to change later.
- **display name** — e.g. `Reducto`.
- **jobs URL** — the human careers page (e.g. `https://reducto.ai/careers`).
- **`sourceAts`** — one of `greenhouse | ashby | lever | gem | eightfold | workday`.
- **`board_token`** — the ATS board slug. **Often equals `id`, but verify live**
  (step 0). For eightfold/workday you also need a `provider_config` blob.
- *(optional)* a one-line recruiter LinkedIn search URL; a curated blurb +
  accomplishment.

The helper scripts in `scripts/` are **stdlib-only** — run them with plain
`python3` (no venv needed).

---

## Step 0 — Verify the board_token is live (do this before writing anything)

`board_token` is the most common mistake. Confirm the board returns jobs:

| ATS | Live check (expect JSON with postings) |
|-----|----------------------------------------|
| greenhouse | `https://boards-api.greenhouse.io/v1/boards/<token>/jobs` |
| ashby | `https://api.ashbyhq.com/posting-api/job-board/<token>` — **case-sensitive, lowercase** |
| lever | `https://api.lever.co/v0/postings/<token>?mode=json` |
| gem | `https://api.gem.com/job_board/v0/<token>/job_posts/` |
| eightfold | the careers API on the tenant host (see provider_config below); host must be on the SSRF allowlist |
| workday | the careers site under `<base_url>/<tenant_slug>/<career_site_slug>` |

The token can differ from `id` (e.g. Greenhouse `optiver` → `optiverprivate`,
`drw` → `drweng`). If unsure which client/endpoint applies, read the matching
`src/backend/api/services/<ats>_client.py`. Use WebFetch to hit the URL.

---

## Step 1 — Frontend: `companies.ts`

Add a `createBackendScraperCompany(...)` call in the section for that ATS, and a
`COMPANY_IDS` enum member (keep it **alphabetical**):

```ts
// in COMPANIES[], in the <ats> group:
createBackendScraperCompany('reducto', 'Reducto', 'https://reducto.ai/careers', {
  sourceAts: 'ashby',
}),

// in `export const enum COMPANY_IDS { ... }` (alphabetical):
Reducto = 'reducto',
```

Omitting `sourceAts` drops the company into "Custom Web Scrapers" — only correct
for script-scraped companies, which this skill does not handle.

---

## Step 2 — Backend: the seed migration (single-head discipline)

The `companies` row is added by a **hand-written Alembic data migration** in
`src/backend/alembic/versions/` (the documented exception to the
autogenerate-only rule). It is applied on backend boot by `main.py`'s lifespan
hook.

> ⚠️ **The #1 hazard.** The migration's `down_revision` MUST be the current
> single head. Chaining off the wrong revision creates a **multi-head**, and the
> backend **crash-loops on boot** (a real prod incident in this repo). The
> helper below removes the guesswork — note migrations mix `'` and `"` quotes,
> so eyeballing the head is error-prone.

Scaffold it (auto-chains off the current head):

```bash
# Greenhouse / Ashby / Lever / Gem:
python3 .claude/skills/add-company/scripts/scaffold_migration.py \
  --id reducto --display-name Reducto --ats ashby --board-token reducto

# Eightfold (provider_config required; tenant_host must be on the SSRF allowlist
# in src/backend/api/services/eightfold_client.py):
python3 .claude/skills/add-company/scripts/scaffold_migration.py \
  --id netflix --display-name Netflix --ats eightfold --board-token netflix \
  --provider-config '{"tenant_host":"explore.jobs.netflix.net","domain":"netflix.com"}'

# Workday (provider_config required; default_facets optional):
python3 .claude/skills/add-company/scripts/scaffold_migration.py \
  --id nvidia --display-name NVIDIA --ats workday --board-token nvidia \
  --provider-config '{"base_url":"https://nvidia.wd5.myworkdayjobs.com","tenant_slug":"nvidia","career_site_slug":"NVIDIAExternalCareerSite"}'
```

Add `--dry-run` to preview without writing. After writing, **confirm a single
head**:

```bash
python3 .claude/skills/add-company/scripts/current_head.py   # exits non-zero on multi-head
```

The generated migration uses `INSERT ... ON CONFLICT (id) DO NOTHING` (idempotent
/ safe on partial prior runs) and a `downgrade()` that deletes the row. Single
-company seeds land **after** the frozen per-ATS seed migrations, so the per-ATS
counts asserted in `test_migration_companies.py` are unaffected.

**Merge hazard (carry into the PR):** if `main` gains another migration before
this merges, you'll have two heads that GitHub can't see and the backend will
crash-loop. Simulate the merge and re-run `current_head.py` before merging; if it
reports two heads, re-chain this migration's `down_revision` onto the new head.

---

## Step 3 — Changelog announcement (`changelog.ts`)

Add a **new top entry** to the `CHANGELOG` array. The `description` should say
what the company does **and a recent achievement or the reason for tracking it**
(e.g. Sierra's entry cites its "$950M / $15.8B raise"; Reducto's explains its
OCR/document-ingestion product). This is what users see, and adds are
user-visible because new companies **auto-enroll** existing users (#136).

```ts
{
  id: 'add-reducto',
  title: 'Added Reducto',
  description:
    'Reducto — a document-ingestion / OCR API startup that turns complex PDFs into LLM-ready structured data — is now tracked via its Ashby job board. <recent raise / launch / why it matters>.',
  tags: ['new-companies'],
  date: '<today, YYYY-MM-DD>',
  link: { to: ROUTES.ACCOUNT, label: 'Add Reducto to your company preferences' },
},
```

`ROUTES` is already imported in `changelog.ts`. Use the real current date.

---

## Step 4 — Logos (delegate to `fetch-company-logo`)

The CI gate `src/frontend/src/__tests__/config/companyLogoAssets.test.ts` fails
if either `icons/<id>.png` or `wordmarks/<id>.png` is missing. **Invoke the
`fetch-company-logo` skill** for this `id` to generate them — it finds on-brand
vector art, composites opaque tiles, and visually verifies. Do not hand-roll
logos; use that skill.

---

## Step 5 — Curated blurb *(optional)*

For a richer Curated Companies card, add the `id` to
`src/backend/api/data/company_profiles.json`:

```json
"reducto": { "blurb": "<1-2 sentences>", "accomplishment": "<recent milestone>" }
```

`companies_seed.py` upserts `blurb`/`accomplishment` onto the row on every boot.
Optional — the curated page falls back gracefully if absent (Reducto #157 shipped
without one).

---

## Step 6 — Verify

```bash
python3 .claude/skills/add-company/scripts/current_head.py          # exactly one head
npm run type-check                                                  # zero TS errors
npm test                                                            # incl. companyLogoAssets + config tests
# backend (optional, if env is set up): pytest test_migration_companies.py
```

Checklist before declaring done:
- [ ] `companies.ts` entry + `COMPANY_IDS` member (alphabetical), `sourceAts` set
- [ ] seed migration present, `down_revision` == current head, **single head**
- [ ] `changelog.ts` top entry (recent achievement / reason, today's date)
- [ ] `icons/<id>.png` + `wordmarks/<id>.png` committed (logo skill)
- [ ] `npm run type-check` + `npm test` green

---

## Per-ATS reference

| ATS | `ats` column | `provider_config` | board_token notes |
|-----|--------------|-------------------|-------------------|
| greenhouse | `greenhouse` | — | often `id`; can differ (optiver→optiverprivate) |
| ashby | `ashby` | — | lowercase, case-sensitive |
| lever | `lever` | — | company slug |
| gem | `gem` | — | company slug |
| eightfold | `eightfold` | `{tenant_host, domain}` | tenant_host on SSRF allowlist (`eightfold_client.py`) |
| workday | `workday` | `{base_url, tenant_slug, career_site_slug, default_facets?}` | slug under base_url |

## Bundled scripts (`.claude/skills/add-company/scripts/`)

- **`current_head.py`** — prints the single current Alembic head (handles both
  quote styles); exits non-zero on 0 or >1 heads. Use it to set `down_revision`
  and to confirm the chain stays single-headed.
- **`scaffold_migration.py`** — writes a Reducto-template seed migration chained
  off the current head; `--provider-config` switches to the JSONB-cast variant
  for eightfold/workday; `--dry-run` previews; refuses to duplicate an existing
  `*_seed_<id>_company.py`.

## Hard-won lessons (do not relearn these)

- **Single head or bust.** Always set `down_revision` to `current_head.py`'s
  output and re-check after writing *and* before merging. Multi-head =
  crash-loop on boot.
- **Verify `board_token` live first** (step 0). A wrong/cased token = a company
  that silently fetches zero jobs.
- **`id` is forever.** It's the PK, every filename, and the logo key. Choose it
  carefully; renaming later touches the DB, frontend, and assets.
- **Logos are CI-gated** — generate them with `fetch-company-logo` or `npm test`
  fails.
- **Don't hand-edit frozen per-ATS seed migrations** or add files under
  `scripts/shared/migrations/` (frozen). New companies = a *new* migration in
  `src/backend/alembic/versions/` only.
