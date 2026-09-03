# onesecondswe — Positioning Brief (Epic 11.1)

> **Status: DRAFT — pending Brendan's sign-off.** This is the source of truth for every
> user-facing claim on the landing page and all later SEO/AEO surfaces (11.2/11.3).
> Per the epic: **if a claim is not in this brief, it does not ship.**
> Interview conducted 2026-08-09 (verbatim Q→A in the appendix). Research findings
> (SEO / AEO / teardowns) are folded into §8–§10.

## 1. Product truth

onesecondswe (https://onesecondswe.dev) scrapes 133 companies' career pages directly
(Greenhouse, Ashby, Lever, Gem, Eightfold, Workday boards, plus custom Google/Apple/Microsoft
scrapers) and timestamps every listing the moment it first appears on the company's own board.

Evidence base (prod, 2026-07-25 → 2026-08-09):
- Median gap from a company posting a job to it appearing on onesecondswe: **0.76 hours (~45 min)**.
- **133 companies**, all with at least one OPEN listing; ~29.5k OPEN listings.
- New OPEN listings: **~2,700 in a good week**; weekend days can dip under 100.
- Freshness = `first_seen_at` (when WE first saw it) — never the ATS "posted" date, which
  reposts routinely fake.

## 2. Audience

**Tech professionals broadly; software engineers are the flagship.** (Q1, Q1b)
Headline voice targets SWEs (matches the name and most job volume); a supporting line makes
clear PM, data science, hardware, and growth roles are tracked too. First viewport must win
over a job-seeking engineer.

## 3. Positioning themes (Q1, ranked by resonance — Q2)

1. **Anti-noise / anti-LinkedIn** (the hook): "reposted jobs", "stale listings", "ghost
   feeds" are the buzzwords job seekers viscerally recognize. LinkedIn reposts are usually
   just old jobs re-surfaced.
2. **Straight to the source of truth** (the mechanism): the company career page, scraped
   directly — no middleman feed.
3. **Apply early, get seen** (the true thesis — supporting beat, not the hook): recruiters
   review on a rolling basis; early applications get human eyes. Q2: "I think applying early
   is the strongest… but I don't think that will resonate" as the opener.
4. **Curated companies** (trust): 133 hand-picked companies, not scraped spam.

## 4. Hero variants (Q2 — ship BOTH across prototypes, converge after review)

**Variant A — source-led (mechanism):**
- A1: "Jobs straight from the source. Minutes after they're posted."
- A2: "Every listing, straight from the company's careers page — usually within the hour."
- A3: "Fresh software engineering jobs, straight from 130+ company career pages."

**Variant B — anti-noise (contrast):**
- B1: "No reposts. No stale listings. No noise."
- B2: "Stop applying to jobs that were posted 47 days ago."
- B3: "That job was posted 45 minutes ago. You're already looking at it."

**Supporting beat (both variants, below the fold or subheadline):**
"Recruiters review applications on a rolling basis. Apply in the first hours and a human
actually reads your resume. onesecondswe exists so you're early — every time."

## 5. Claims inventory (Q4 — all four approved)

| id | Rendered copy (calibrate wording, not facts) | Evidence | Source |
|---|---|---|---|
| `straight_from_source` | "Scraped directly from company career pages — the source of truth" | Architecture: per-ATS scrapers against company boards | Q1, repo |
| `minutes_after_posting` | "Most jobs appear here within the hour they're posted" | Median posted→first_seen 0.76h (prod, 63k listings) | Q4, epic prod data |
| `no_reposts` | "Freshness you can trust: we timestamp when a job first appears on the company's board — reposts can't fake it" | `first_seen_at` design; postedOn explicitly rejected as recency signal | Q4, codebase |
| `curated_companies` | "130+ curated companies" (derive count from COMPANIES.length; never hardcode 133) | 133 companies, all active | Q4, prod |
| `thousands_weekly` | "Thousands of new listings every week" (always-true phrasing; weekends dip) | ~2.7k/7d good weeks | Q4, prod |
| `apply_early_rolling` | "Recruiters review on a rolling basis — early applications get human eyes" | Q1 verbatim; supporting beat per Q2 | Q1/Q2 |

## 6. Do-not-say list

- **"No ghost jobs"** — we cannot verify a company's hiring intent; grepjob claims it, we
  don't. Our honest version is `no_reposts` (real posting dates). (Q4 framing)
- Hard numbers that rot: "133 companies" (use "130+"), "45 minutes" as a promise (use
  "usually within the hour" / "median ~45 min" with a measured-across framing).
- "Every tech job" / completeness claims — we track 133 companies, not the market.
- Anything implying endorsement by the scraped companies (logos = "companies we track",
  never "trusted by").
- LinkedIn-bashing by name in shipped copy — the *category* critique (reposts, stale feeds)
  is the public voice; "we hate LinkedIn" is internal context (Q1: "the context does not
  have to be in the actual content").

## 7. Voice, tone, CTA

- Terse, plain, engineer-to-engineer; monochrome black-on-white Helvetica everywhere (Q5).
  Data-forward proof, but **live/event-shaped**, not vanity metrics (Q7): "SpaceX posted 25
  jobs in the past hour", "1,000 jobs tracked in the past 24 hours" — never static
  "trusted by 10,000 users" energy.
- Primary CTA: **"Browse jobs"** → the live board (Q3). Secondary: "Create free account"
  (unlocks full board beyond the 12-job preview, saved filters, defaults).

## 8. Curated "top companies" (Q6 — hand-picked; **Brendan edits this list**)

Draft `TOP_COMPANY_IDS` (24; ids verified in `config/companies.ts`):
`apple`, `google`, `microsoft`, `netflix`, `spacex`, `openai`, `anthropic`, `stripe`,
`databricks`, `palantir`, `robinhood`, `reddit`, `discord`, `airbnb`, `pinterest`,
`spotify`, `roblox`, `cloudflare`, `waymo`, `xai`, `doordashusa`, `instacart`,
`snowflake`, `dropbox`.
Used by: fresh-jobs ticker (headline rail) and live-activity stats. The broader logo wall
draws from the full registry. Real-data rule for later promotion: curated-first, backfill
freshest, honest age labels (weekend volume can drop below 20 fresh junior-SWE roles).

## 9. SEO targets (researched 2026-08-09)

**The wedge: nobody quantifies freshness.** grepjob says "scraped hourly"; LinkedIn/Indeed
say nothing. The measured **~45-min median** belongs in the H1/title — it's the claim
competitors can't copy without measuring.

**Prototype constraints (apply NOW, in all 4 tabs):**
- Exactly one `<h1>` per prototype: query phrase + differentiator + a number — reference
  shape: "Software engineer jobs, ~45 minutes after companies post them".
- All copy is real DOM text; canvas layers are decorative (`aria-hidden`); CWV discipline:
  LCP element = the HTML headline (never the canvas), canvas dimensions reserved (CLS),
  3D bundle deferred behind interaction/IO, static poster path on mobile/low-end.
- A crawlable **sample-listings block** (title · company · location · posted-ago as text) —
  grepjob/hiringcafe server-render 20–40 real jobs on the homepage; our jobs-forward tab
  does this natively, the others carry at least the fresh-jobs rail as DOM text.
- **FAQ section, 5–8 real questions as DOM content** (FAQ rich results are dead; the
  content still wins long-tail + AI surfaces). Draft Qs from claims inventory (§10).
- Internal link stubs with query-shaped anchors ("SpaceX software engineer jobs",
  "new grad software engineer jobs 2026"), incl. a footer "popular searches" block —
  targets may 404 for now (they're the 11.3 surface); prototypes render the pattern.
- Winning title shapes (for 11.2, drafted now): keyword-first + number + freshness cue +
  brand suffix, ≤60 chars load-bearing. Homepage: `Software Engineer Jobs, Minutes After
  They're Posted | onesecondswe`. Per-company: `SpaceX Software Engineer Jobs — Live From
  SpaceX's Careers Page | onesecondswe`. Category: `New Grad Software Engineer Jobs 2026 —
  Fresh From 130+ Career Pages`.
- Query families: "{company} software engineer jobs" (the curated-board beats-LinkedIn
  surface), "new grad software engineer jobs {year}", "software engineering internships
  {year}", "remote software engineer jobs", "jobs posted today software engineer".

**Later phases (11.2/11.3, noted not built):** SSR/prerender is a prerequisite (empty-shell
HTML makes everything else moot); landing schema = Organization + WebSite ONLY (JobPosting
JSON-LD is per-job-page only per Google docs — never on a landing/list page); Google for
Jobs: eligible but limited upside (canonicalizes to employer; `directApply: false`); robots
+ sitemap split by page type; per-company/category pages are the real SEO surface;
expired jobs → 410/301.

## 10. AEO targets (researched 2026-08-09; last30days + web)

**P0 — crawlability is the whole game.** GPTBot / ClaudeBot / OAI-SearchBot /
PerplexityBot do NOT execute JavaScript; only Googlebot renders. As a pure SPA,
onesecondswe is invisible to every answer engine except AI Overviews today. →
Prerender/SSG of the landing surface (11.2) is the highest-leverage fix on the roadmap;
robots.txt must ALLOW the retrieval bots (GPTBot, OAI-SearchBot, ChatGPT-User, ClaudeBot,
Claude-SearchBot, Claude-User, PerplexityBot, Google-Extended, Bingbot — Bing feeds
ChatGPT Search). Prototypes: keep every claim as plain DOM text (already required by §9).

**P1 — quotable claim block** (Princeton GEO: statistics +41% citation visibility,
quotations +28%): 3–5 standalone subject-verb-number sentences near the top, each liftable
without context:
- "onesecondswe surfaces new software engineering jobs a median of 45 minutes after
  companies post them on their own career pages."
- "onesecondswe scrapes 130+ curated tech companies' career pages directly — no aggregator
  feeds, no reposts."
- "Every posting date on onesecondswe is the moment we first saw the job on the company's
  board, so 'posted 2 hours ago' means exactly that."
- "Thousands of new software engineering jobs are added every week, free."

**P2 — FAQ: visible text now, FAQPage JSON-LD at 11.2** (rich results dead in Google, but
the schema is still parsed by Bing/Perplexity/RAG crawlers). Adopted Q&As (answer-first,
50–120 words): "Where can I find tech jobs the day they're posted?" · "How fast do new
jobs show up on onesecondswe?" · "Why do job postings on LinkedIn look new but are
actually old?" · "How does onesecondswe know a job's real posting date?" · "How many
companies and jobs does onesecondswe cover?" · "Is onesecondswe free?" (Full text lives in
the prototypes' content config, claims-traceable.)

**P3 — entity + category co-occurrence**, high on the page and repeated in title/meta/
schema: "onesecondswe is a free job board for software engineers that shows jobs the day
they're posted."

**P4 — comparison framing** (a top retrieved surface type; factual and defensible only):
"Unlike LinkedIn and Indeed, which syndicate and re-list jobs with reset dates,
onesecondswe reads company career pages directly and never reposts."

**llms.txt verdict: hygiene, not leverage.** ~10% adoption, 408 fetches across 500M+ AI
bot visits, Google confirmed non-support. Ship a minimal one at 11.2 for agent hygiene;
never prioritize it over P0–P4.

**Off-page moves (later, in order):** authentic Reddit answers in r/cscareerquestions-
class threads (Reddit ≈ #1 cited domain for commercial AI queries) · get into "best job
boards for software engineers" listicles + AlternativeTo · Show HN ("133 career pages,
45-min median, no reposts") · publish an original job-posting-freshness report from
first-seen data (the stat only onesecondswe has — and the eventual Wikipedia-adjacent
path) · optional YouTube (0.737 correlation, strongest single factor).

## 11. Teardown learnings (cursor · browserbase · grepjob · linear · vercel · resend)

**Copy calibration (headline corpus):** every reference headline is ≤9 words (Vercel:
"Agentic Infrastructure" — 2). Shapes that work: noun phrase ("The X for Y"), imperative,
or "X is your Y for Z". Subheadlines are 9–19-word **fragment stacks**, not sentences
(grepjob: "No ghost jobs, reposts, or sponsored listings. Filters that actually work.").
H1 claims; the sub carries specifics. → Our variants in §4 comply; prefer the shorter ones.

**CTA refinement:** the mode is ≤2 CTAs and every extra maps to a distinct buyer. We have
one audience and one action → **hero shows a single "Browse jobs" button**; "Create free
account" lives in the nav/footer, not the hero. (Refines §7.)

**Structure:** steal Linear's ~8-section skeleton (hero → proof → how-it-works → wall →
closing proof + CTA → footer), not cursor's 17. **Proof closes the page** — end on a
fragment stack: "130+ companies. ~45 min median. Zero reposts." before the footer CTA.

**Proof mechanics that fit a solo job board:** (a) **un-rounded live numbers**
(browserbase's "36,925,870" works because it's obviously real) — pairs perfectly with Q7's
event-shaped stats; (b) **logo+stat fused sentences** (vercel: "Notion powers millions of
agent conversations daily") → "SpaceX posted 25 jobs in the past hour" is exactly this
shape. No testimonials, no free-floating logo marquee as primary proof.

**Jobs-forward specifics (grepjob is precedent + cautionary tale):** its structure converts
but its hero has NO product CTA (only sign-in/mailto) — ours scrolls to the board; the
**posted-ago timestamp should be the visually loudest field on each card** (grepjob buries
it); show ~8–10 listings then "Browse all N jobs →"; dedupe visible companies (grepjob
shows Applied Intuition ×3 — reads scrapy); render only fields present on EVERY card;
collapse filters to search + one filter button.

**3D discipline (resend cube + browserbase quarantine + vercel fallback):** ONE
meaning-bearing 3D moment, hero-only, nothing below the fold moves; text/CTA on a layer the
physics can never occlude; falling logos render **grayscale/monochrome** to hold the
black-on-white aesthetic (133 brand colors = the opposite of the cube's discipline —
decision for Brendan at review: grayscale default vs brand-color toggle); fall once
(~2–3 s), settle, idle — the settled pile IS the logo wall, don't repeat a grid below;
static pre-settled fallback for reduced-motion/no-WebGL/mobile-low-end.

**Particles rule:** particles must encode data — one dot per job caught today, captioned
"Every dot is a job posted today." Monochrome gray, ≤10% visual weight; pair with a 2–4
word headline. Particles tab = clean tab's skeleton + the data layer (honest A/B pair).

## Appendix — Interview Q→A log (2026-08-09, verbatim where quoted)

**Q1 (audience):** "It should target tech professionals, people who work in tech… the idea
is we hate LinkedIn… Reposted jobs are usually just jobs that have been posted for a long
time. So we're going straight to the source of truth, the career webpage, and also if you
apply early and quick, it's likely you're gonna hear back. A human is gonna see your resume
because recruiters review things on a rolling basis… cutting through the noise, going
straight to the source, having curated companies, and applying early." (Also: "I'm gonna
give you these answers… the context does not have to be in the actual content.")

**Q1b (SWE vs broad):** SWE flagship, broad support.

**Q2 (hero lead):** "I like either two or three here… I think applying early is the
strongest. I think it's like the main, the real reason why I built this… but I don't think
that will resonate with people… people resonate with the reposted job, stale job, ghost
listing… these are like buzzwords that people will actually resonate with. So I would say
two or three probably works the best. We can have two different taglines there and we can
kind of converge on one."

**Q3 (CTA):** Browse jobs now (primary); account secondary.

**Q4 (claims):** approved all four — minutes-after-posting, 130+ curated companies,
no-reposts/real posting dates, thousands weekly.

**Q5 (visual):** Stay monochrome light across all prototypes.

**Q6 (top companies):** Hand-picked household names; Brendan edits the draft list.

**Q7 (above-fold proof):** "I like all these concepts. Stacked counter, I like the concept,
but I don't like the exact stats that we're doing. Like it might be like, I don't know,
SpaceX posted 25 jobs in the past hour or… we've tracked, you know, a thousand jobs in the
past 24 hours, stuff like that, but in general, all these are good."
