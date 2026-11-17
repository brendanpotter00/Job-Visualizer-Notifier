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
with the same `User-Agent` from a residential IP returns 200, so we first
blamed Railway's datacenter IP. That was half right: Cloudflare scores the
client's TLS fingerprint and the IP together, and the fingerprint was the
part we could fix. See "Second cause" and "Resolution" below.

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

## First fix (#368, later removed)

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

Brendan set `WORKDAY_PROXY_URL` on Railway. It did not fix the problem on
its own (next section).

## Second cause: Python's TLS fingerprint (2026-11-17)

The proxy alone didn't fix it. After #368 went live, Workday runs through the
DataImpulse proxy still got `429 cf-mitigated: challenge` for 13–16 of 16
companies per tick (04:00Z–12:00Z on 11-17).

Cloudflare scores the client and the IP together. Same POST, same headers:

| Client | From home IP | Through the proxy |
|---|---|---|
| curl | 200 | 15/15 |
| stock httpx | 200 | 6/15 |
| httpx + OpenSSL `DEFAULT` ciphers | 200 | 15/15 |

Python's `ssl` module ships its own short cipher list, so a stock httpx
client has a rare TLS fingerprint. On a clean home IP that passes. On shared
residential exit IPs it tips the bot score into a challenge. The same split
held on the `python:3.13-slim` prod image (OpenSSL 3.5.7): with `DEFAULT`
ciphers, 20/20 paginated pages across NVIDIA, Zoom, Snap and Intel; stock
httpx was challenged on 3 of 4 on the first page. The proxy pool itself was
fine: curl through it got 12/12, both worldwide and US-only.

Fix: the Workday client uses httpx's verifying TLS context with
`set_ciphers("DEFAULT")` (`_tls_context()` in `workday_client.py`). Certificate
and hostname checks are unchanged, and the User-Agent still names us. This is
not browser impersonation.

## Resolution: the proxy is not needed (2026-11-17)

With the cipher fix live, we unset `WORKDAY_PROXY_URL` and let the 18:00Z
tick run direct from Railway. All 16 companies scraped: 10,627 jobs, 0
errors, every request logged `egress=direct`, and no Cloudflare challenges.
The proxy before that tick hit the same 16/16. So the TLS fingerprint was
the cause we could act on, and Railway's IP is fine with it fixed.

The proxy code (`WORKDAY_PROXY_URL`, the proxied client, the fresh-IP
challenge retries) was removed. A challenge now raises `WorkdayBlockedError`
after one request. The cadence went back to `*/30`.

## Prevention

- **Classify before you fix.** For any upstream 4xx/5xx wave, check the
  `blocker=` field (#366) first. `cloudflare` means an IP/bot problem, not a
  rate problem, and needs an egress fix, not backoff.
- **Check the client before blaming the IP.** If another ATS starts
  returning `cf-mitigated`, compare curl and httpx from the same IP first.
  Python's stock TLS fingerprint was enough to get challenged here. A paid
  proxy is the last resort, not the first.
- **A challenge fails fast.** It is one request per company per tick. That keeps a blocked source from adding load or log noise while
  the health-watch alarm stays loud.

## Follow-ups

- If challenges come back, test the client and the IP separately before
  changing anything (curl vs httpx, Railway vs home, interleaved, 15+ tries:
  single tries are noise). Only if the IP itself is the problem, bring back a
  residential proxy (#368 has the code). Never impersonate a browser (repo
  rule).
- Brendan can cancel the DataImpulse plan.
