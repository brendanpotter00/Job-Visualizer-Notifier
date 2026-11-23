# Monetization Plan

How onesecondswe makes money, in the order it gets built.
It follows [STRATEGY.md](STRATEGY.md): the board and a daily digest are free, and a candidate pays for speed and for matches worth applying to.

The goal is interviews, not email.
A paid alert earns its price because the jobs in it are ones the candidate could get an interview for, never because it sends a lot.

## The order

1. **Onboarding sets saved filters.** A new user answers a few questions after signing in, so they never face an empty page.
2. **Free daily digest.** Users with saved filters who are active get at most one email a day, only on days with good matches.
3. **Paid instant alerts.** A high-confidence match reaches the candidate within the hour it goes up. This needs a correct, fast enrichment pipeline that lives in this repo.
4. **Paid personal rubric.** A rubric built from the candidate's résumé, which they can edit, decides which jobs are worth sending.

Each phase needs the one before it.
The digest needs saved filters, instant alerts need the digest's sending and a fast, correct enricher, and the rubric needs instant alerts.

## 1. Onboarding sets saved filters

Today a new user signs in and lands on a board with nothing set, and has to find the filters on their own.
36 of 368 users have saved filters.

- After the first sign-in, ask a few questions, one at a time: what kind of role, what level, where, and any keywords to include or skip.
- The answers are written to the user's saved filters and keyword list, so the board opens already narrowed to them.
- The questions use the facets the board already has (category, subcategory, level, location), so onboarding adds no new data.
- It can be skipped, and every answer can be changed later on the board.
- Once phase 2 ships, the last step offers the daily digest.

Done when a new user finishes signing in with saved filters set and never opens a settings page to do it.
Measure: the share of new signups who have saved filters.

## 2. Free daily digest

- **Who gets it:** users with saved filters who are active. What "active" means is still open (see Open decisions).
- **When it sends:** at most once a day, and only when enough new jobs clear the match bar. A day with nothing good sends nothing.
- **What's in it:** new jobs that match the user's saved filters, newest first, each sent to a user once.

What it needs:

- **Email sending.** The backend sends no email today, so this needs a provider, domain authentication, one-click unsubscribe, and bounce and complaint handling.
- **A sent record.** Track which job went to which user, so nobody gets the same job twice.
- **The board's matcher.** Match with the same filter code as `GET /api/jobs/search`, so an email never shows a job the board wouldn't.
- **Keyword fixes first.** Keywords match as substrings today, so "ai" matches "maintain" and "email".

Measure: clicks per email, unsubscribe rate, and spam-complaint rate under 0.3% ([USER-METRICS.md](USER-METRICS.md)).

What the current filters would send (prod, last 30 days, the 10 most active users with saved filters):

- 0 to 13 matching jobs a day, about 5 for the typical user, arriving in about 3 separate hours a day.
- 66% of software engineering jobs are first seen between noon and 6pm Pacific.
- Broad filters are noisy. For one NYC software-engineering filter, about half the matches had senior, staff, lead or manager titles, and about 14% weren't software jobs.

That noise is fine for a free digest and not good enough to charge for, which is what phases 3 and 4 fix.

## 3. Paid instant alerts

What the candidate pays for: an alert within the hour a high-confidence match goes up.
Pro becomes instant alerts.

### 3a. Move the enrichment pipeline into this repo

The enricher now lives in this repo at `src/enricher/` (moved with its git history) and runs on the server laptop.
It pulls new jobs from this backend continuously (a new tick about a minute after the last one ends), classifies and judges them, and writes the results back.

- Move its code into this repo, keeping its git history.
- It keeps running on the server laptop, now deployed from a checkout of this repo.
- The pull contract (`/api/internal/enrichment/*`) doesn't change.
- AGENTS.md says where it lives and where it runs, so an agent working here sees the whole system, including the parts that run elsewhere.

### 3b. Make enrichment correct

Category and level decide what a candidate is alerted about, so a wrong label is a wrong alert.

- Fix the known enrichment bugs (tracked in ClickUp under this phase).
- Check accuracy against the human-labelled gold set before anyone is charged.

### 3c. Make enrichment fast

Filters on category or level only match jobs that have been enriched, so the enricher sets how fast an alert can be.
Today (prod, jobs first seen in the last 14 days):

- None of the 5,888 enriched jobs were enriched within an hour; the median wait was 9.5 hours.
- About 35% of last week's new jobs weren't enriched at all.
- About 610 new jobs arrive a day and about 450 get enriched.

These come from `job_enrichment.enriched_at`. A re-run may overwrite that time, so confirm the lag before setting the target.

Target: every new job enriched within the hour it is first seen, with capacity above the daily intake.
Instant alerts don't go on sale until this holds.

### 3d. Deliver instant alerts

- Each scrape's new matches go out together as one alert, not one alert per job.
- Each user has a daily cap, quiet hours and a frequency setting.
- Only matches that clear a high-confidence bar are sent instantly; the rest wait for the daily digest.
- Email comes first. Push channels are an open decision.

Measure: the time from a job going up to its alert, clicks per alert, and unsubscribe rate.

## 4. Paid personal rubric

The digest and instant alerts send only jobs a candidate could get an interview for.

A candidate uploads a résumé, and a rubric is generated from it. The rubric scores each new job on:

- **Skill overlap:** whether their experience covers what the job asks for.
- **Done this job before:** whether they've held this kind of role.
- **Industry experience:** a software engineer who worked at Boeing has hard-tech and aviation experience, and one who worked at PayPal has fintech experience that Robinhood would value. A match on both role and industry scores best.

The candidate can edit the rubric and add what a résumé can't show:

- **Preferences**, such as where they want to work.
- **No-go rules**, such as skipping any job that asks for 5+ years of experience.
- **Always-notify companies**, which alert whenever they post a match.

Only jobs over a confidence threshold go out, in both the digest and instant alerts.

- **Cost:** model spend per candidate is planned on purpose, with a named cap (STRATEGY.md). Saved filters narrow the jobs first, and only what's left gets scored.
- **Privacy:** a résumé is candidate data. It is never sold, and the candidate can delete it.
- **Pricing:** it's paid; whether it's part of Pro or its own tier is open.

Measure: apply clicks per alert, and whether candidates report getting interviews.

## Not in this plan

- **The MCP server.** It isn't part of making money; it may ship later as a free or cheap extra.
  `/pricing` sells Pro as "Unlimited MCP access" today, but no MCP server exists in prod, and STRATEGY.md says "nothing is sold before it exists."
  Pro's copy moves to instant alerts only once they exist.
- **Anything employers pay for.** No paid listings, no boosted ranking, and no B2B data product (STRATEGY.md).

## Open decisions

- **What "active" means for the digest.** For example, a visit in the last 7, 14 or 30 days. Today 6 of the 36 users with saved filters visited in the last 30 days, and 13 in the last 60.
- **The match bar.** How many new jobs, at what confidence, before a digest sends, and what counts as high confidence for an instant alert.
- **Price and tiers** for instant alerts and for the rubric.
- **Alert channels** beyond email (web push, Telegram, SMS).
- **How to learn about interviews**, which candidates would have to tell us.
- **The model-spend cap** for enrichment and for rubric scoring.

## Starting numbers

All from prod on 2026-11-22.

| Number | Value |
|---|---|
| Users | 368 |
| Users with saved filters | 36 |
| Of those, visited in the last 30 days | 6 |
| New jobs per day | ~610 |
| Jobs enriched per day | ~450 |
| Enriched within an hour of first seen | 0% |
| Median time to enrichment | 9.5 hours |
| Matches a day for the typical active filter | ~5, in ~3 separate hours |
