# User Metrics

What onesecondswe optimizes, how each number is defined, and where it comes from.
It serves the Vision in [STRATEGY.md](STRATEGY.md): get a candidate to a real, fresh opening fast, and be worth coming back to while they search.

The model is Chris Raroque's: fix the leaky bucket before spending on growth, and make week-1 retention the north star (his target is 30-40%).
One difference matters here: people leave a job board when they get hired, so retention is measured while someone is searching, and coming back after a break counts for a lot.

## North Star

Both are measured per signup cohort, for signed-up users only.

| Metric | Definition | Target | Baseline |
|---|---|---|---|
| **3-day+ return** | Share of a cohort with at least one visit on day 3-30 after signing up | - | 41% (Aug cohort), 43% (Jul) |
| **7-day+ return** | Share of a cohort with at least one visit on day 7-30 after signing up | 30-40% | 23% (Aug), 27% (Jul) |

A visit the same day or the next two days does not count toward 3-day+, so a single curious session never looks like retention.

## Supporting metrics

| Metric | Definition | Baseline |
|---|---|---|
| **Weeks returned** | Of weeks 1-8 after signup, how many had at least one visit | 0.98 weeks on average; 69% came back in no week, 6% in 6+ weeks |
| **Comeback after a 2-week gap** | Of users who went 14+ days without a visit, the share who visited again afterwards | 19% (60 of 318) |
| **Signup conversion** | `user_signed_up` ÷ `signup_funnel_landing` over 30 days | ~1.3% (5 of 382) |
| **Apply clicks per session** | Click-throughs to a job's application page ÷ sessions, where a session is a distinct PostHog session id seen that week on a visit or an apply click | ~0.05 (rough; see below) |

## Notification quality (once alerts ship)

| Metric | Definition | Guardrail |
|---|---|---|
| **Clicks per email** | Job click-throughs ÷ emails delivered | Higher is better; it measures whether what we send is worth opening |
| **Unsubscribe rate** | Unsubscribes ÷ emails delivered | Should fall as matching improves |
| **Spam-complaint rate** | Complaints ÷ emails delivered | Under 0.3%, Gmail's limit for bulk senders |

## How each is measured

- **Return metrics** come from Postgres prod: `users.created_at` for the cohort, `user_visits.visited_at` for visits.
- A visit is one full page load by a signed-in user (`useRecordVisit` → `POST /api/users/visit`); in-app route changes do not count.
- `user_visits` starts on 2026-06-24, so cohorts start with signups on 2026-06-25.
- A cohort is reported only once it is 31+ days old (8+ weeks for weeks returned), so young cohorts never look worse than they are.
- Accounts with `users.is_internal = true` (the owner's) are excluded. The test account `nonadmin@nonadmin.com` is counted, so it can be used to test in prod.
- The same definitions are live as views: `metrics.signup_retention`, `metrics.north_star_weekly`, `metrics.apply_clicks_weekly`.
- **Signup conversion** is the "Conversion rate %" tile on the PostHog [Signup Conversion](https://us.posthog.com/project/483508/dashboard/1768649) dashboard.
- **Apply clicks per session**: the ~0.05 baseline is a rough estimate from before click logging, autocapture clicks on apply or ATS links (51) over sessions (1,128) in the last 30 days.
  It is now exact, for signed-in users only: each Apply press writes a `job_apply_clicks` row (with the job's age at click time) and a PostHog `job_apply_clicked` event, read by `metrics.apply_clicks_weekly`. There is no backfill.

7-day+ return, per cohort:

```sql
WITH u AS (
  SELECT id, created_at::timestamptz AS c FROM users
  WHERE NOT is_internal
    AND created_at::timestamptz >= '2026-06-25'
    AND created_at::timestamptz < now() - interval '31 days'
)
SELECT date_trunc('week', u.c) AS cohort,
       count(*) AS signups,
       round(100.0 * count(*) FILTER (WHERE EXISTS (
         SELECT 1 FROM user_visits v
         WHERE v.user_id = u.id
           AND v.visited_at >= u.c + interval '7 days'
           AND v.visited_at <  u.c + interval '31 days')) / count(*), 1) AS pct_back_day7plus
FROM u GROUP BY 1 ORDER BY 1;
```

For 3-day+ return, change `7 days` to `3 days`.

## Baseline by monthly cohort (2026-11-22)

| Cohort | Signups | 3-day+ | 7-day+ |
|---|---:|---:|---:|
| Jun (from the 25th) | 39 | 38.5% | 28.2% |
| Jul | 168 | 42.9% | 27.4% |
| Aug | 95 | 41.1% | 23.2% |
| Sep | 9 | 33.3% | 11.1% |
| Oct (not yet mature) | 11 | 54.5% | 45.5% |
| Nov (not yet mature) | 4 | 0% | 0% |

Cohorts since September are too small to read a trend from; weekly cohorts only become meaningful again once signups pick up.
