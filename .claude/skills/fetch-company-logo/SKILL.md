---
name: fetch-company-logo
description: |
  Fetch and generate the three opaque brand-logo variants — symbol icon, text
  wordmark, and combined lockup — for companies in companies.ts using parallel
  per-company sub-agents, and write them as PNGs into
  src/frontend/public/logos/{icons,wordmarks,lockups}/<id>.png. Each per-company
  agent finds high-quality vector art from free sources, picks the most on-brand
  background (brand color / white / black) with legible contrast, composites via
  the bundled Pillow/cairosvg scripts, and visually verifies the result. Use when
  adding new companies, backfilling a missing logo, or regenerating the set.
trigger_phrases:
  - generate company logos
  - fetch logos for the companies
  - add logos for the new company
  - backfill the missing logo
  - regenerate the logo set
  - get all three logos
  - fetch company logo skill
  - fetch the company logo
required_tools:
  - Bash
  - Read
  - WebFetch
  - WebSearch
mode: read-write
---

# Fetch Company Logo

Generate, per company, **three opaque PNG logo variants** and place them in the
repo's public asset dirs:

| Variant     | Dir                                   | Shape                         | Used for (intended)        |
|-------------|---------------------------------------|-------------------------------|----------------------------|
| **Symbol**  | `src/frontend/public/logos/icons/`    | square `128×128`              | job-card icon (24px)       |
| **Wordmark**| `src/frontend/public/logos/wordmarks/`| banner, height `128`, var. w. | curated-card heading (32px)|
| **Lockup**  | `src/frontend/public/logos/lockups/`  | banner, height `128`, var. w. | wide brand banner          |

All three are **opaque** (no transparency — a solid brand background), keyed by
the company **`id`** from `companies.ts` (e.g. `stripe.png`, `happyrobot.ai.png`,
`apex-technology-inc.png`). Background is chosen **per brand** (its signature
color, or white/black) for the most on-brand, legible result.

> Source of truth for the company list is `src/frontend/src/config/companies.ts`.
> `src/frontend/src/__tests__/config/companyLogoAssets.test.ts` is a CI gate that
> fails if any company is missing `icons/<id>.png` or `wordmarks/<id>.png`.
> **`lockups/` is a new variant** — see *Wiring* at the bottom before relying on it.

## Why this approach (the short version)

- **Sub-agent per company** because each logo needs judgment: find the *right*
  brand's art, pick a background, choose a contrast treatment, and **look at the
  result** to confirm it's correct. One agent owns one company end-to-end.
- **A single shared compositor guarantees uniformity** — every output is the same
  size/shape/opacity regardless of source. Agents only decide *what art* and
  *what background*; the scripts make it consistent.
- **Free, keyless sources only** (Clearbit's logo API is dead). Prefer crisp
  full-color **SVG**; rasterize locally.

## Prerequisites (one-time)

```bash
brew install cairo                                  # native lib cairosvg needs
python3 -m venv /tmp/logo-venv
/tmp/logo-venv/bin/pip install -r .claude/skills/fetch-company-logo/scripts/requirements.txt
```
Use `/tmp/logo-venv/bin/python` to run every script below. Keep a scratch work dir
for raw downloads + transparent masters (NOT committed), e.g. `/tmp/logo-work/`.

## Pipeline

### 0. Get the company list
```bash
/tmp/logo-venv/bin/python .claude/skills/fetch-company-logo/scripts/list_companies.py --json
```
This is the exact id/name set the CI gate enumerates. For "add one company", just
target that id.

### 1. Harvest — one sub-agent per company (parallel)
Spawn an agent per company. Give each: `id`, `name`, best-guess domain, the script
paths, and the scratch + output paths. Each agent:
1. Confirms the **real brand identity** (web check for ambiguous names — e.g.
   `apex-technology-inc` = Apex Space, `poke` = The Interaction Company, `fal` = fal.ai).
2. Finds the **symbol mark** and the **wordmark** as crisp, full-color art,
   preferring transparent **SVG**. Source priority:
   1. SVGPorn — `https://raw.githubusercontent.com/gilbarbara/logos/main/logos/<slug>.svg` (and `<slug>-icon.svg`)
   2. VectorLogoZone — `https://www.vectorlogo.zone/logos/<slug>/<slug>-icon.svg` (and `-ar21.svg` for wordmark)
   3. Wikimedia Commons raw `.svg` (web-search the File: page, then the `upload.wikimedia.org` raw link)
   4. The company's own site / press-kit / brand page; official GitHub asset repos
   5. Simple Icons — `https://cdn.simpleicons.org/<slug>` (MONOCHROME, last resort; flag it)
3. Normalizes each to a transparent master:
   ```bash
   .../python scripts/normalize.py /tmp/logo-work/raw/<id>/symbol.svg   /tmp/logo-work/masters/<id>/symbol.png
   .../python scripts/normalize.py /tmp/logo-work/raw/<id>/wordmark.svg /tmp/logo-work/masters/<id>/wordmark.png
   ```
   (add `--remove-white` only if a raster source has a solid white background.)

### 2. Pick background + contrast (auto-best per brand)
For each company the agent chooses a **background hex** and a **knockout**:
- **Brand color** + `--knockout white` (or `black` on light colors) for a
  single-color mark whose color would clash with its own tile (Stripe purple+white,
  Reddit orange+white, Anthropic terracotta+white).
- **Neutral** (`#FFFFFF` or `#000000`) + `--knockout none` for **multi-color**
  logos so they keep their colors (Google/Figma/Airtable on white; Netflix red-N,
  Robinhood lime on black).
- Use the brand's *conventional* tile when known (Netflix/Apple/OpenAI/Vercel = black;
  Google/Microsoft = white).
- Tip: `scripts/` has no color sampler, but the agent can read the master and eyeball
  the dominant hue, or web-check the brand's hex.

### 3. Produce the three opaque variants
```bash
PY=/tmp/logo-venv/bin/python
S=.claude/skills/fetch-company-logo/scripts
OUT=src/frontend/public/logos
M=/tmp/logo-work/masters/<id>
# symbol icon (square)
$PY $S/tile.py $M/symbol.png   $OUT/icons/<id>.png     --bg "#BG" --knockout <ko> --shape square --size 128
# wordmark (banner)
$PY $S/tile.py $M/wordmark.png $OUT/wordmarks/<id>.png --bg "#BG" --knockout <ko> --shape banner --size 128
# lockup (symbol + wordmark composed)  — or run an official combined lockup through tile.py --shape banner
$PY $S/compose_lockup.py $M/symbol.png $M/wordmark.png $OUT/lockups/<id>.png --bg "#BG" --knockout <ko> --height 128
```
If a brand has **no separate symbol**, reuse the wordmark for the icon slot (note it).

### 4. Verify — visually + mechanically
- **The agent Reads each final PNG** and confirms: correct brand, legible (strong
  contrast — not washed out), centered/not clipped, on-brand background.
- Mechanical gate over the whole set:
  ```bash
  /tmp/logo-venv/bin/python .claude/skills/fetch-company-logo/scripts/verify_assets.py
  ```
  Checks presence (mirrors the CI gate), opacity, dimensions, and that the logo is
  actually visible against the background (not blank/flat).

### 5. Gap-fill loop (conservative)
Run an independent skeptic agent per company (or just per flagged company) that
opens both/all variants and flags: wrong brand, illegible/low-contrast, garbled,
mis-cropped, monochrome-where-color-exists. Then re-dispatch fix agents that
**replace only if clearly better** — never regress a correct logo. Repeat until clean.

### 6. QA contact sheets
```bash
for v in icons wordmarks lockups; do
  /tmp/logo-venv/bin/python .claude/skills/fetch-company-logo/scripts/montage.py \
    src/frontend/public/logos/$v /tmp/logo-work/$v-grid.png --title "$v"
done
```
Read the grids and eyeball the full set; fix stragglers.

## Orchestration

### Option A — Workflow tool (preferred for the full set; "ultracode")
Author a workflow: a loader agent runs `list_companies.py`, then `parallel(...)` fans
out one agent per company (each does steps 1–4 for its id), then a verify/gap-fill
phase. Sketch:

```js
export const meta = { name: 'company-logo-tiles', description: '3 opaque logo variants per company',
  phases: [{title:'Load'},{title:'Harvest'},{title:'Verify'}] }
const companies = (await agent('run list_companies.py --json and return {companies:[{id,name}]}',
  { schema: LIST_SCHEMA, phase:'Load' })).companies
const out = await parallel(companies.map(c => () =>
  agent(perCompanyPrompt(c), { schema: RESULT_SCHEMA, label: c.id, phase:'Harvest', model:'sonnet' })))
// then: mechanical verify_assets.py + a parallel skeptic pass, gap-fill the flagged ids
```

### Option B — Agent tool fan-out
Launch the per-company agents in batches with the Agent tool (one message, multiple
tool calls). Same prompt; collect results; verify; gap-fill.

### Per-company agent prompt (template)
```
Produce the 3 OPAQUE logo variants for ONE company. Output is structured DATA.
COMPANY: <name> (id: <id>), domain: <domain>.
Scratch masters dir: /tmp/logo-work/masters/<id>/   Raw dir: /tmp/logo-work/raw/<id>/
Final outputs:
  src/frontend/public/logos/icons/<id>.png      (square 128, symbol)
  src/frontend/public/logos/wordmarks/<id>.png  (banner h=128, wordmark)
  src/frontend/public/logos/lockups/<id>.png    (banner h=128, icon+name)
1) Confirm the brand identity (web-check ambiguous names).
2) Find the SYMBOL and WORDMARK as full-color SVG (SVGPorn, VectorLogoZone, Wikimedia,
   brand site/press kit; Simple Icons = monochrome last resort). Save to raw dir;
   normalize.py each -> masters dir (transparent).
3) Pick a BACKGROUND hex + knockout (white/black/none): single-color mark -> brand
   color + white/black knockout; multi-color logo -> neutral bg + knockout none.
4) Run tile.py (icon square, wordmark banner) and compose_lockup.py (lockup).
5) READ all three final PNGs; confirm correct brand, legible, centered, on-brand bg.
   Fix bg/knockout/source and re-run if any is wrong.
Return: id, bg_hex, knockout, and notes per variant.
```

## Bundled scripts (`.claude/skills/fetch-company-logo/scripts/`)

- **`list_companies.py`** — extract `{id,name}` for every company from `companies.ts`.
- **`normalize.py`** — any source (SVG/PNG/JPG/ICO) → clean **transparent master** (autocropped, longest side `--max`). `--remove-white` for solid-white raster bgs.
- **`tile.py`** — transparent master → **opaque** PNG. `--shape square` (icon) or `--shape banner` (wordmark); `--bg "#hex"`; `--knockout white|black|none`; `--size`.
- **`compose_lockup.py`** — symbol + wordmark masters → opaque **lockup** banner.
- **`verify_assets.py`** — mechanical QA over the 3 variant dirs (presence, opacity, dims, non-blank/visible).
- **`montage.py`** — labeled QA contact sheet for human review.
- **`requirements.txt`** — Pillow + cairosvg.

## Hard-won lessons (do not relearn these)

- **Clearbit Logo API is dead.** Use SVGPorn / VectorLogoZone / Wikimedia / brand sites; Simple Icons only as a monochrome fallback.
- **Prefer SVG**, rasterize locally; favicon/app-tile PNGs are low-res and often a colored rounded square, not the real mark.
- **The image viewer composites transparency onto white.** When verifying, do NOT treat a white-looking background as a defect on a *transparent* source — confirm transparency by pixels, not by eye. (Here the finals are opaque anyway, so this bites the *masters* check, not the tiles.)
- **A logo in its own brand color disappears on a same-color tile** — that's why single-color marks get `--knockout white/black`, and multi-color logos go on a neutral bg with `--knockout none`.
- **Light/white logos are invisible on white backgrounds.** If you keep a logo's own colors, make sure they contrast with the chosen bg (or knockout).
- **Gap-fill conservatively** — confirm the real brand and only replace a file if clearly better; QA passes produce false positives, so never auto-regress a correct logo.
- **Ambiguous ids**: `apex-technology-inc`=Apex Space, `poke`=The Interaction Company (board slug `interaction`), `hrt`=Hudson River Trading, `drw`=DRW, `fal`=fal.ai, `xai`=Elon's xAI (x.ai). Resolve identity before fetching.
- After generating, clean up stray files: every file in each variant dir must map to a real company id (sub-agents occasionally create an extra). `verify_assets.py` reports extras.

## Wiring (only if you want the app to USE the new variants)

The repo currently ships **opaque** `icons/` + **transparent** `wordmarks/`, exposed via
`getCompanyLogoUrl` / `getCompanyWordmarkUrl` in `companies.ts` and rendered by
`components/shared/CompanyLogo/{CompanyLogo,CompanyWordmark}.tsx`. To use this skill's output:
1. Regenerating `wordmarks/` as **opaque** banners changes their look on the curated
   cards (a colored bar instead of transparent) — confirm that's desired.
2. To use **lockups/**, add `getCompanyLockupUrl(id)` (→ `/logos/lockups/${id}.png`),
   a consuming component, and extend `companyLogoAssets.test.ts` to also require
   `lockups/${c.id}.png` so coverage is CI-gated like the other two.
3. Run `verify_assets.py` and `npm test` before committing.
