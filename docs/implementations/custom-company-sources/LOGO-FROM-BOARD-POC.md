# Can we get a company logo from the job board page? — measured

**Verdict: half right, and right for the wrong reason.** A usable company logo comes out of
**25 of 26 boards measured** — but on **every one of the 15 vendor-hosted boards the
`<link rel="icon">` / `apple-touch-icon` / `/favicon.ico` is the ATS VENDOR's own mark, not
the company's**. Byte-identical across tenants; proven by hash. The company's logo on those
boards lives in `og:image` / `twitter:image` (and, on Ashby, in a JSON blob in the document).
On company-hosted boards it is exactly inverted: the favicon **is** the company (10 of 11
usable at ≥128 px) and `og:image` is a marketing card **7 times out of 10**. So the original
claim — "the document already has `rel=icon`, `apple-touch-icon`, `og:image`, a manifest" —
names the right *place* but the wrong *tag for the wrong host*, and would have shipped an
Ashby "A" as Crusoe's logo.

**Quality: good enough to be a default, not good enough to replace `fetch-company-logo`.**
6 of 15 vendor boards and 10 of 11 company-hosted boards clear the repo's real bar
(128×128 square). The rest are 2:1–2.9:1 lockups or under 128 px.

---

## What was measured

26 boards — **15 vendor-hosted, 11 company-hosted** — plus 4 extra Ashby tenants for the
theme-asset survey. Plain `httpx`, one normal
Chrome User-Agent, redirects followed. Every candidate was **downloaded** and opened with
Pillow — every dimension, byte count and sha256 below is real, none is inferred from a
`sizes=` attribute. Measured 2026-08-30 from a residential US IP.

Candidates extracted per board: `link rel=icon`, `rel="shortcut icon"`, `apple-touch-icon`,
`apple-touch-icon-precomposed`, `mask-icon`, `og:image`, `twitter:image`,
`msapplication-TileImage`, every icon in the linked web manifest, `/favicon.ico` at the final
origin, and any header `<img>` whose class/alt/src matches `logo|brand|wordmark|masthead`.

Two boards could not be measured: `nike.wd1.myworkdayjobs.com/nike[external]` and
`jobs.lever.co/netflix` both 404 (wrong slug, not a board property). `jobs.ashbyhq.com/PostHog`
returns the 7,319-byte SPA shell — that Ashby board is gone; it is kept in the table because
it is the honest worst case.

---

## The vendor-hash comparison — stated plainly

**The favicon on a vendor-hosted board is the vendor's logo. This is not a tendency, it is
byte-identity.** Fetched from different tenants, hashed, compared:

| Vendor | Asset | sha256 | Bytes | Real dims | Identical across |
|---|---|---|---|---|---|
| **Ashby** | `favicon.png` | `d3b538025d8270a6…` | 2,264 | 192×192 | **7 / 7** boards |
| **Ashby** | `favicon.svg` | `034bac8ae7e0d13d…` | 670 | 192×192 | **7 / 7** boards |
| **Ashby** | `apple-touch-icon.png` | `28a62f7db7f64122…` | 3,440 | 180×180 | **7 / 7** boards |
| **Greenhouse** | `favicon.ico` | `db928f695ac699a6…` | 4,286 | 32×32 | **2 / 2** boards |
| **Lever** | `favicon.ico` | `71795082e9774d58…` | 32,038 | 64×64 (ICO 16/32/48/64) | **2 / 2** boards |
| **Workday** | `favicon.ico` | `71250bbcaa93c5cf…` | 1,150 | 16×16 | **4 / 4** tenants, **4 different hosts** |

Ashby does not even bother with a per-tenant URL — all seven boards point at the *same*
`cdn.ashbyprd.com/cdn_assets/c2eda05…/favicon.png`. I opened the images: purple tile with a
white **A** (Ashby), a green **g** (Greenhouse), a teal **L** (Lever), an orange **w**
(Workday). The Workday row is the strongest form of the proof — `adobe.wd5`, `intel.wd1`,
`target.wd5` and `salesforce.wd12` are four separate origins serving the same 1,150 bytes.

**Brendan was right to push back.** Had this shipped off `rel=icon`, every Ashby company
would have carried an Ashby "A", every Lever company a Lever "L", and — because those bytes
are identical — every one of them the *same* tile.

---

## The inversion nobody would have guessed

`og:image` behaves in exactly the opposite way on the two host types.

| | favicon / apple-touch-icon | `og:image` / `twitter:image` |
|---|---|---|
| **Vendor-hosted** (15) | vendor's mark, **0/15** usable | company's brand asset, **13/13** present are the company's |
| **Company-hosted** (11) | company's mark, **10/11** usable | a marketing/social card **7/10** of the time |

The reason is structural, not luck. An ATS renders the OG card from the tenant's uploaded
brand asset — that is the only company-specific image it holds. A company's own careers page
sets `og:image` to whatever the marketing team wants shared on LinkedIn, which is a photo
collage far more often than a logo.

Company-hosted `og:image` failures I opened and confirmed are **not** logos: Atlassian (a
photo/illustration collage, 811×812), Spotify ("Join the band" photo, 2400×1260), Amazon
("Impact the future, today.", 1200×627), Stripe (collage, 2400×1260), Databricks ("Careers at
Databricks" card), Figma ("Figma Careers" card), Robinhood (a phone photo). The three that
*are* logos: Jane Street (wordmark on brand blue), SpaceX (wordmark on black), Rockstar (its
own 180×180 favicon reused).

---

## Results — vendor-hosted boards

"Best candidate" = the highest-quality image on the page that is actually the **company's**
mark. "Usable" = clears `icons/` (128×128 square, see [the bar](#the-bar-we-are-measured-against)).

| Board | Vendor | Best candidate | Source tag | Real dims | Format | Whose logo | Usable |
|---|---|---|---|---|---|---|---|
| **Crusoe** | Ashby | `org-theme-logo` | **JSON in doc only** | 150×150 | JPEG, opaque | **Company** | ⚠️ 150 px JPEG, no alpha |
| Crusoe | Ashby | `favicon.png` | `rel=icon` | 192×192 | PNG | **Ashby** | ❌ |
| Crusoe | Ashby | `og:image` | `og:image` | 1500×882 | JPEG | Company (social card) | ⚠️ 1.7:1 card |
| **Sierra** | Ashby | `org-theme-logo` | `og:image` | 1740×1740 | PNG, alpha | Company | ✅ |
| **Plaid** | Ashby | `org-theme-logo` | `twitter:image` | 241×240 | PNG, alpha | Company | ✅ |
| **Saronic** | Ashby | `org-theme-logo` | JSON in doc | **SVG** | SVG | Company | ✅ (is a wordmark) |
| **Thinking Machines** | Ashby | `org-theme-wordmark` | JSON in doc | **SVG** | SVG | Company | ⚠️ wordmark only, no symbol |
| **fal.ai** | Ashby | `org-theme-logo` | `og:image` | 905×320 | PNG, alpha | Company | ⚠️ 2.83:1 lockup |
| **PostHog** | Ashby | — none — | — | — | — | **Ashby only** | ❌ dead board, shell only |
| **Anthropic** | Greenhouse | board logo | `og:image` + `<img alt="Anthropic Logo">` | 2000×2001 | PNG, alpha | Company | ✅ |
| **Discord** | Greenhouse | board logo | `og:image` + `<img alt="Discord Logo">` | 1080×1080 | PNG, alpha | Company | ✅ |
| **Palantir** | Lever | `lever-client-logos` | `og:image` | 2501×1313 | PNG, alpha | Company | ⚠️ 1.9:1 lockup |
| **Voleon** | Lever | `lever-client-logos` | `og:image` | 3837×1781 | PNG, opaque | Company | ⚠️ 2.15:1 lockup |
| **Adobe** | Workday | `/{tenant}/assets/logo` | `og:image` | 100×100 | PNG, alpha | Company | ❌ under 128 |
| **Intel** | Workday | `/{tenant}/assets/logo` | `og:image` | 1200×630 | PNG, opaque | Company | ⚠️ padded 1.9:1 |
| **Target** | Workday | `/{tenant}/assets/logo` | `og:image` | 2500×2500 | PNG, alpha | Company | ✅ |
| **Salesforce** | Workday | `/{tenant}/assets/logo` | `og:image` | 85×85 | PNG (served `text/plain`) | Company | ❌ under 128 |

**Clears the 128×128 square bar: 6 of 15** (Sierra, Plaid, Anthropic, Discord, Target, and
Crusoe marginally at 150 px). Another 6 give a wide lockup; 2 are under 128 px; 1 (PostHog)
gives nothing.

### The Ashby finding that changes the shape of the answer

**The company's logo *is* in the served Ashby document — just not in any standard tag.** The
page bootstrap JSON carries `logoWordmarkImageUrl` and up to three
`app.ashbyhq.com/api/images/org-theme-{logo,wordmark,social}/…` URLs. Surveyed across 10
Ashby tenants:

| Tenant | `org-theme-logo` | `org-theme-wordmark` |
|---|---|---|
| Crusoe | 150×150 JPEG (1.00) | 1500×882 JPEG (1.70) |
| Sierra | 1740×1740 PNG α (1.00) | 2584×1120 PNG α (2.31) |
| Plaid | 241×240 PNG α (1.00) | 1000×588 PNG α (1.70) |
| Saronic | **SVG** | **SVG** |
| Thinking Machines | — absent — | **SVG** |
| fal.ai | 905×320 PNG α (2.83) | same bytes as logo |
| Exa | 1000×1000 PNG α (1.00) | 832×300 PNG α (2.77) |
| Merge | 512×512 PNG α (1.00) | 4774×1656 PNG α (2.88) |
| Krea | 2048×2048 PNG α (1.00) | — absent — |
| Salient | 200×200 JPEG (1.00) | — absent — |

I rendered all 17 of these and confirmed by eye: **every one is the correct company's real
mark**, correctly coloured, not clipped. `org-theme-logo` is present on 9 of 10 and square
on 7 of those 9.

**Ashby is the only vendor that hands over a symbol AND a wordmark separately** — which maps
one-to-one onto the repo's `icons/` and `wordmarks/` slots, the two the CI gate requires.

---

## Results — company-hosted boards

| Board | Best candidate | Source tag | Real dims | Format | Whose logo | Usable |
|---|---|---|---|---|---|---|
| **Jane Street** | `logo-icon…svg` | `rel="shortcut icon"` | SVG, viewBox 32 (2,388 B) | SVG | Company | ✅ best-in-class |
| **Goldman Sachs** | `gs-chrome-512x512.png` | **manifest only** | 512×512 | PNG, alpha | Company | ✅ — see caveat |
| **Atlassian** | `apple-touch-icon.png` | `apple-touch-icon` | 180×180 | PNG, alpha | Company | ✅ (`og:image` is a collage) |
| **SpaceX** | `share.jpg` | **`og:image` only** | 800×800 | JPEG, opaque | Company | ✅ — declared favicon 404s |
| **Spotify** | `icon-512x512.png` | `apple-touch-icon` | 512×512 | PNG, alpha | Company | ✅ |
| **Rockstar Games** | `favicon-180x180.png` | `rel=icon` (= `og:image`) | 180×180 | PNG, alpha | Company | ✅ |
| **Amazon** | `favicon…ico` | `rel="shortcut icon"` | 48×48 (ICO 16/24/32/48) | ICO | Company | ❌ under 128 |
| **Stripe** | `favicon.svg` | `rel=icon` | SVG, viewBox 512 (412 B) | SVG | Company | ✅ |
| **Databricks** | `icon-512x512.png` | `apple-touch-icon` | 512×512 | PNG, alpha | Company | ✅ |
| **Robinhood** | `RH-Favicon---Neon.jpg` | `rel=icon` | 500×500 | WEBP, opaque | Company | ✅ |
| **Figma** | `icon-512.png` | manifest / `rel=icon` | 512×512 | PNG, alpha | Company | ✅ |

**10 of 11 clear the bar.** Only Amazon fails, and only on size — its largest declared icon
anywhere on the page is 48×48.

Databricks, Robinhood and Figma were entered as **Greenhouse** URLs
(`job-boards.greenhouse.io/{slug}`) and **redirected to the company's own careers site**.
That redirect is what saved them: it moved them from the vendor column, where the favicon is
Greenhouse's, into the company column. Worth knowing — a board's host type is decided by the
*final* URL, not the pasted one.

---

## How the two host types split across the boards we actually onboard

It does **not** work only for company-hosted boards — but the two host types need different
code, so the split decides how much of each is worth building. From `TESTABLE-BOARDS.md`'s
own numbers (70 URLs measured):

| Population | Count | Host type | Logo channel needed |
|---|---|---|---|
| Tracked via discovery | **17** (63%) | all **company-hosted** — an ATS URL never reaches discovery | generic: largest declared icon |
| ATS fast path | **10** (37%) | all **vendor-hosted** — 7 Workday, 1 Lever, 2 Greenhouse | per-vendor: `og:image` / `assets/logo` |
| Refused | 43 | n/a | no company to give a logo to |

So of the **27 URLs that actually become a tracked company, 63% are company-hosted** — where
the generic "largest declared icon" rule hits 10 of 11 in this sample — and **37% are
vendor-hosted**, where the generic rule hits **zero** and a per-vendor rule is mandatory.

Note the ATS fast path in that doc contains **no Ashby board**, yet Ashby is the vendor with
the richest logo data (a separate square symbol *and* a wordmark). The per-vendor work is
cheap and pays off unevenly: Workday covers 7 of the 10 fast-path URLs, Ashby covers the
best-quality output.

---

## The bar we are measured against

Measured directly off `src/frontend/public/logos/`, not assumed:

| Dir | Files | Dimensions | Transparency | Bytes (min/median/max) |
|---|---|---|---|---|
| `icons/` | 135 | **all exactly 128×128** | 134 of 135 fully **opaque** | 808 / 3,490 / 9,695 |
| `wordmarks/` | 135 | **all height 128**, variable width | 130 of 135 transparent | 2,392 / 20,022 / 85,959 |
| `lockups/` | 3 | all height 128 | 3 opaque | 15,863 / 19,300 / 24,242 |

`.claude/skills/fetch-company-logo/SKILL.md` says how they get there: find crisp **full-colour
SVG** (SVGPorn → VectorLogoZone → Wikimedia → the brand's own press kit), rasterize locally,
pick a per-brand background hex plus a knockout, composite to an opaque tile, then **an agent
opens the PNG and confirms the brand is right and legible**. `verify_assets.py` and
`companyLogoAssets.test.ts` gate the result in CI.

The skill's own hard-won lesson is the exact thing this POC set out to test:

> **Prefer SVG**, rasterize locally; favicon/app-tile PNGs are low-res and often a coloured
> rounded square, not the real mark.

That warning is confirmed and needs one amendment: on a **vendor** board the favicon is not
merely low-res, it is the **wrong company**.

**Today a user-added board gets no logo at all.** `CompanyLogo.tsx` takes
`hasBrandArt={false}` for runtime `u-<base36>` ids and renders a neutral building glyph —
deliberately, so the tile never shows a letter derived from `www.janestreet.com`. Anything
this POC yields is an improvement on a grey glyph; it does not have to beat the curated
pipeline to be worth shipping.

---

## Recommendation

**Do not read `rel=icon` first. Branch on host type, which we already know** — the ATS
resolver has classified the board as ashby/greenhouse/lever/workday/eightfold or as a
discovery board before any of this runs.

**1 — Vendor-hosted: use the vendor's own channel.** All of these are in the document we
already fetch; each costs one image GET and nothing else.

| Vendor | Where the company logo is |
|---|---|
| Ashby | `org-theme-logo` URL in the bootstrap JSON → `icons/`; `org-theme-wordmark` → `wordmarks/` |
| Greenhouse | `og:image`, same bytes as `<img alt="<Company> Logo">` in the header |
| Lever | `og:image` on `lever-client-logos.s3…` (a wide lockup — treat as `wordmarks/`) |
| Workday | `https://{tenant}.wd{n}.myworkdayjobs.com/{site}/assets/logo` (also served as `og:image`) |

**2 — Company-hosted: largest declared icon wins.** Prefer `rel=icon` **SVG** → manifest icon
→ largest `apple-touch-icon` → largest `rel=icon` PNG. Only consider `og:image` if nothing
else exists **and** it passes the shape check — it is a marketing card 7 times in 10.

**3 — Never guess `/favicon.ico`.** Six of six hosts I probed returned **HTML**, and
`jobs.ashbyhq.com/favicon.ico` returned it with **HTTP 200** (7,319 B, magic bytes `<!DO`).
Status code and `Content-Type` are both insufficient — validate magic bytes / decode with
Pillow before believing anything.

**4 — Gate on shape, then fall back.** Reject and keep the existing neutral glyph when: the
bytes do not decode as an image; the short side is under 128 px; or the aspect ratio is
outside ~0.8–1.25 and no wordmark slot is being filled. On this sample that rejects Adobe
(100×100), Salesforce (85×85), Amazon (48×48) and PostHog (nothing), and routes fal.ai,
Palantir, Voleon, Intel, Crusoe's card and Thinking Machines to the wordmark slot instead of
the icon slot.

**5 — Flag it for review, don't call it done.** Store a `logo_source` ("board-derived") so
`fetch-company-logo` can upgrade a company later. A board-derived asset is a good default; it
is not the curated three-variant set and should not pretend to be.

---

## Concerns worth flagging

**Hotlinking is not an option — cache the bytes.** Every candidate lives on a third-party CDN
(`cdn.ashbyprd.com`, `app.ashbyhq.com/api/images`, `s8-recruiting.cdn.greenhouse.io`,
`lever-client-logos.s3…`, `images.ctfassets.net`, `v.fastcdn.co`). Hotlinking leaks our
users' IPs to those hosts, and the URLs are unstable by construction: Ashby's are per-upload
UUIDs, Greenhouse's carry a `?1744052732` cache-buster. Download once, re-host.

**Some hosts refuse a server-side fetch outright.** Goldman Sachs' four declared
`<link rel=icon>` hrefs all return **HTTP 403** from `images.ctfassets.net` — and adding a
`Referer: https://higher.gs.com/` **does not fix it** (still 403). GS is only usable because
its *manifest* icons sit on a different Contentful space that does serve us. Any design that
assumes "the document lists it, therefore we can fetch it" is wrong.

**"No extra request needed" is false, and was false in the original claim.** The document
gives you a *URL*; you still make one image GET, and on GS and Figma you must also GET the
manifest first. It is 1–2 extra requests, not zero. Cheap, but not free.

**Transparency and background cut both ways.** The `icons/` slot wants an **opaque** tile
composited over a chosen brand colour, so the pipeline needs a *transparent* master. Most
board assets are transparent PNG or SVG (good), but several are JPEG with a baked background:
Crusoe 150×150 on white, Salient 200×200 on white, SpaceX 800×800 on **black**. `normalize.py`
has `--remove-white` and **no `--remove-black`** — SpaceX's wordmark would need handling that
does not exist yet.

**Non-square is the real failure mode, not fetching.** Six of the fifteen vendor boards yield
a 1.9:1–2.9:1 lockup. `CompanyLogo` renders with `objectFit: contain`, so a 2.9:1 lockup in a
128 tile letterboxes to about 128×44 of actual art — and the **job card renders that tile at
24 px**, leaving roughly 24×8 px of legible logo. It will look broken, not merely imperfect.
This is why step 4 above routes wide art to the wordmark slot rather than shrinking it.

**Trademark posture is unchanged, provenance is better.** These are trademarks used to
identify the company they belong to — the same nominative use as the 135 logos already
committed to this repo. If anything the provenance is stronger: the company published the
asset on its own careers page. What is genuinely new is the **vendor** logos — serving
Ashby's "A" as a company's mark would be a false designation of origin, which is the one
outcome this document exists to prevent.

**Live boards drift.** Same caveat as `TESTABLE-BOARDS.md`. `jobs.ashbyhq.com/PostHog` is
already a dead shell and `jobs.lever.co/netflix` 404s. Whatever is stored must be
re-fetchable and replaceable.

---

## How this was measured, and what it does not cover

A throwaway `httpx` + BeautifulSoup + Pillow probe (kept in `/tmp`, not committed) fetched
each document once, extracted candidates, downloaded every candidate, and recorded status,
`Content-Type`, byte count, sha256, decoded format, real pixel dimensions and alpha presence.
SVGs were rasterized with `cairosvg` for viewing. Judgement calls in the "whose logo" column
came from **rendering two labelled contact sheets (41 + 17 images) and looking at them** — not
from filenames or heuristics.

**Gaps:**

- **No JavaScript.** Documents were fetched with plain `httpx`, so anything a SPA injects
  after hydration was not seen. The real pipeline captures with headless Chromium and would
  see *more*, never less — so these numbers are a floor.
- **Residential US IP.** Production fetches from Railway. The GS 403 and any geo/datacenter
  gate could behave differently there, in either direction.
- **Eightfold and Gem boards were not tested.** Both are supported ATS providers in this repo.
  Given four out of four vendors behaved identically, expect the same, but it is unmeasured.
- **Two boards 404'd** on slug errors (Nike Workday, Netflix Lever) and are excluded from the
  counts, not counted as failures.
- **Nothing was written.** No logo was generated, no file added to `public/logos/`, no
  database touched.
