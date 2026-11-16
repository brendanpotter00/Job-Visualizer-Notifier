# Incident: Workday dark, Cloudflare challenges Railway's egress IP

**Date:** 2026-11-13 20:00Z (first partial loss), 2026-11-16 ~07:00Z (total
loss), 2026-11-16 20:30Z (root cause confirmed)
**Severity:** High. Not Urgent: no rows were falsely closed and the guards held.
**Impact:** All 16 Workday companies (Adobe, Blue Origin, Capital One, Cisco,
CrowdStrike, Disney, Expedia, GM, Intel, NVIDIA, PayPal, Salesforce, Slack,
Snap, Turo, Zoom) scraped 0 jobs from 07:00Z on 11-16. Capital One, Expedia
and Salesforce were already dark from 11-15 22:30Z. The ~10.6k OPEN Workday
rows went **stale, not falsely closed**: closures over the window stayed
normal (62 closed vs 112 new since 11-15 22:00Z). The health-watch texted
about Workday coverage.

## Root cause

Workday's career sites sit behind Cloudflare. Cloudflare started answering
every CXS `POST /wday/cxs/.../jobs` from Railway with:

```
HTTP 429
cf-mitigated: challenge
content-type: text/html  (Workday-branded challenge page, ~28 KB)
cf-ray: …-IAD
```

`cf-mitigated: challenge` means Cloudflare's bot management sent a challenge.
It is **not** a rate limit. The origin never saw the request. The same POST
with the same `User-Agent` from a residential IP returns 200. The trigger is
the reputation of Railway's datacenter egress IP, not our request rate.

The rollout was progressive across tenants, so it looked like a slide rather
than a cliff:

| UTC | Workday runs with errors | jobs seen / hour |
|---|---|---|
| 11-13 ≤19:00 | ~0 | ~21.2k |
| 11-13 20:00 → 11-14 18:00 | partial (27→153/hr) | 3.9k–20k |
| 11-14 19:00 → 11-15 22:00 | 0 (recovered) | ~21.2k |
| 11-15 23:00 → 11-16 06:00 | 3 tenants down | ~13.7k |
| 11-16 07:00 | 13 more tenants down | 6.8k |
| 11-16 08:00 → now | all 16 | 0 |

## Why the first two fixes didn't work

- **#365 (fix 429 retry storm)** treated the 429 as a rate limit. It added
  in-place retries with backoff, a per-pod cooldown, no Procrastinate re-runs,
  and a fan-out stagger. That cut the noise, but a challenge never clears on
  retry from the same IP.
- **#366 (log non-2xx responses)** added the diagnostics that proved the cause.
  Within minutes of deploy every failure logged `blocker=cloudflare` with
  `cf-mitigated: challenge`.

The PR description of #365 already flagged the open question ("whether the
429s come from our request rate or from Workday blocking Railway's IP
range"). We should have answered that before shipping a rate-limit fix.

## Fix

`docs/implementations/workdayResidentialProxy/PLAN.md`:

1. **Egress through a rotating residential proxy.** A new `WORKDAY_PROXY_URL`
   setting (a SecretStr, never logged) is passed to the Workday httpx client.
   There is no silent fallback to direct egress, because direct egress is
   known-blocked.
2. **Treat a challenge as its own error, not as a 429.** A new
   `WorkdayBlockedError` is raised when Cloudflare sends a challenge. It never
   trips the pod cooldown. It retries in place only when a rotating proxy is
   set (each retry gets a fresh exit IP). Procrastinate never re-runs it.
3. **Workday cadence 30 min → 2h.** This cuts proxy bandwidth from ~7–15 GB/mo
   to ~2–4 GB/mo. The health-watch's 6h staleness window is still 3 ticks.

Brendan sets `WORKDAY_PROXY_URL` on Railway. Agents never handle the
credentials.

## Prevention

- **Classify before you fix.** For any upstream 4xx/5xx wave, check the
  `blocker=` field (#366) first. `cloudflare` means an IP/bot problem, not a
  rate problem, and needs an egress fix, not backoff.
- **Direct datacenter egress is a known risk** for every scraped source
  (Meta was already flagged in `config.py`). Workday is the first to go dark
  from it. If another ATS starts returning `cf-mitigated`, route it through
  the same proxy pattern rather than adding retries.
- **A challenge fails fast.** Without a proxy it is one request per company
  per tick. That keeps a blocked source from adding load or log noise while
  the health-watch alarm stays loud.

## Follow-ups

- If the residential proxy starts getting challenged too (cheap pools carry
  flagged IPs), switch to a higher-quality pool or static ISP IPs before
  considering anything else. Never impersonate a browser (repo rule).
