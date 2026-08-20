# Business & Marketing Context — onesecondswe

Captured verbatim-in-spirit from Brendan, 2026-08-09, during the Epic 11 landing-page
review sessions. This is the business context you CANNOT derive from the code or git
history. Future agents doing marketing, copy, SEO/AEO, or landing work: read this first,
alongside `docs/seo/positioning-brief.md` (the claims inventory + do-not-say list — every
shipped claim must trace there).

## Core positioning: candidate-centric, by business-model choice

The product is **for the candidate, period**. The way incumbents make money is the thing
we refuse to do: LinkedIn (and boards like it) let companies pay to **repost** jobs —
resetting posting dates on old roles so stale listings look fresh. Brendan is explicitly
not letting companies do that here. No repost mechanism exists and none will be sold.

- This is **context, not necessarily copy** — the landing page doesn't have to say
  "candidate-centric"; the anti-repost stance and honest timestamps ARE the expression
  of it.
- Related standing rule from the brief: "we hate LinkedIn" is internal context, never
  published copy; no unverifiable "ghost jobs" claims.

## The core belief (the why behind the product)

**Applying early is what gets you seen.** Recruiters review applications on a rolling
basis; if you apply in the first hours with a good resume, a human actually reads it and
you get the interview. Everything the product does — scraping career pages directly,
~45-minute median surfacing, honest first-seen timestamps — exists so the candidate is
early, every time.

## Product identity / north star

**"Datadog for the job market."** Monitoring and observability for hiring activity, not
a listings directory. The long-term ambition (explicitly NOT solved, NOT implemented,
NOT for the current landing page):

- Monitor talent movement — e.g., when people at Anthropic/OpenAI leave, and especially
  when they leave to found startups or join very early-stage companies, so users could
  discover those companies at inception.
- Layer in VC-backed data on top companies (funding stage, backers) as a signal.

Brendan's own scoping: "way down the line… I wouldn't necessarily put that on my
hypothetical landing page right now." Treat these as vision context for tone ("the job
market, monitored") — not as feature claims.

## Feature set — current, in-progress, and roadmap (as of 2026-08-09)

**Live today (fair game for landing sections, claims must trace to the brief):**
- Direct career-page scraping of 130+ curated companies; ~45-min median post→on-site.
- Honest first-seen timestamps (no repost laundering).
- **AI-powered labeling** — enrichment pipeline labels roles (category, level, location
  normalization). Brendan: this "should probably be somewhere in one of the sections"
  of the landing page — pending copy treatment, not yet placed.
- Saved filters, curated company directory, feature voting.

**In progress right now (interesting, buildable into copy once shipped):**
- **Custom jobs / bring-your-own-company**: user types any company (e.g. Cisco, Intel)
  and the system spins up a scraper that watches that company's careers site every 24h
  for them. Personal watchtower model — very "Datadog for jobs."

**Not implemented yet (do NOT imply on landing):**
- Notifications, payments/monetization, saved jobs. These are near-term roadmap and may
  be "scoped out" as teased sections later, but nothing on the landing page should
  promise them today.

**Owner-decision exception (2026-08-20) — the labeled Coming-soon tier:** unshipped
features MAY appear on the landing page, but ONLY inside a clearly-labeled, grayed-out
"Coming soon" tier that is visually disabled and named as such. Outside that tier the rule
above is unchanged: nothing unshipped may read as present-tense anywhere else on the page.
Copy inside the tier stays future-tense or capability-neutral, and each entry carries an
evidence breadcrumb to its epic. Live today: the feature matrix tier (MCP / AI-assistant
access, AI notifications, track any company).

## How this constrains marketing copy

1. Candidate-first framing always; the villain is noise/staleness (reposts, stale
   listings), expressed via the anti-noise hero line ("No reposts. No stale listings.
   No noise.") — Brendan's favorite.
2. Never sell to employers on the landing page; there is no employer product.
3. Freshness claims stay quantified and honest (~45-min median, first-seen timestamps).
4. Vision language ("monitor the job market") is fine as flavor; specific vision
   features (talent movement, VC data) stay unmentioned until real.
5. Every concrete claim traces to `docs/seo/positioning-brief.md` §claims-inventory.

## Pointers

- Positioning brief + claims inventory + interview appendix: `docs/seo/positioning-brief.md`
- Landing prototypes plan + review-round log: `docs/implementations/landingPagePrototypes/PLAN.md`
- Epic: ClickUp Epic 11 "Landing page & SEO/AEO" (`wdwb1cbnc7`)
