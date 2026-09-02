# Accepted security & spend risks

A running log of risks we **know about and have decided to live with**, and the
handful we know about and have **not** closed yet. The point of the file is that
"we already thought about that" stops being folklore: if something here is ever
exploited, the question is whether the decision was wrong, not whether anyone saw
it coming.

**What belongs here:** a risk that is real, reachable, and consciously not fixed —
because the cost of fixing exceeds the exposure, because it is bounded by
something else, or because it is scheduled. **What does not:** a bug. If it should
just be fixed, fix it.

**How to use it.** Add a row when you accept a risk, not when you discover one.
Every entry needs an owner-visible *trigger* — the condition under which the
acceptance stops being valid and it becomes work. A risk with no trigger is not
accepted, it is forgotten.

**Status vocabulary**

| Status | Means |
|---|---|
| **Accepted** | Understood, deliberately not fixed. The trigger says when to revisit. |
| **Open** | Known, not yet accepted or fixed. Needs a decision. |
| **Mitigated** | Reduced to a residual we accept. The residual is what is described. |
| **Closed** | Fixed. Kept for the history; date the fix. |

---

## Register

| # | Risk | Status | Trigger to revisit |
|---|---|---|---|
| [1](#1) | Company-name search has no spend cap | **Open** | Before `COMPANY_NAME_SEARCH_ENABLED` goes on in prod |
| [2](#2) | A name search can auto-track another company's board | **Mitigated** | Any report of a wrong company being tracked |
| [3](#3) | A user can spend one-time discovery on a page of their choosing | **Accepted** | Monthly discovery cost exceeds the budget |
| [4](#4) | In-memory rate limiters reset on every deploy | **Accepted** | We deploy often enough that a burst survives a limiter |
| [5](#5) | User-controlled outbound fetch (SSRF surface) | **Mitigated** | Any new outbound fetch that skips `url_guard` |
| [6](#6) | ATS client responses have no byte cap | **Open** | A memory incident on the API container |

---

<a id="1"></a>
## 1 — Company-name search has no spend cap

**Status: Open.** Must be decided before the flag is turned on in production.

`POST /api/companies/search-by-name` spends real money on every call: one
Browserbase Search call (~$0.007; the plan includes 1,000 free per month) plus up
to five outbound ATS probes. The only bound on it is
`enforce_resolve_rate_limit` — **10 requests per 60 seconds, per authenticated
user, held in memory**.

**The 20-adds-per-month cap does not bound this, and that is the whole point of
the entry.** That cap lives on `POST /api/users/companies` and is counted off the
append-only `company_add_attempts` audit. Search is a different route, in a
different file, and never touches that counter. Searches and adds are not 1:1 even
in ordinary UI use:

| What a signed-in user does | Searches spent | Adds consumed |
|---|---|---|
| Types a name, one confident board → auto-added | 1 | 1 |
| Types a name, sees the candidate list, picks nothing | 1 | **0** |
| Types a name with no board behind it, ignores the fallback | 1 | **0** |
| Types fifty company names browsing around | 50 | **0** |

So this is not only an abuse case. Someone idly exploring the box spends the
credits and never touches their twenty.

**Worst case, measured against the limiter:** 10/60s is 600 searches/hour, so a
single account exhausts the 1,000 free monthly searches in **~100 minutes** and
then bills. A script with a valid bearer token needs no UI. And because the
limiter is in-process memory, a Railway deploy resets it.

**Why it is not closed yet.** The feature ships behind
`COMPANY_NAME_SEARCH_ENABLED`, default **off**, so today the exposure is zero. The
cap is a product decision (what is a reasonable number of searches per person per
month?) rather than a technical one.

**What closing it looks like**, in the order that buys the most safety per unit of
work:

1. **A global monthly search budget** — a hard stop at some fraction of the free
   tier, so no combination of users can produce a surprise bill. This alone
   removes the financial risk.
2. **A per-user monthly search quota**, mirroring `services/add_quota.py` — the
   same shape, counted off its own audit table. Generous for a human, useless for
   a script.

---

<a id="2"></a>
## 2 — A name search can auto-track another company's board

**Status: Mitigated.** The residual is real and is the reason the UI looks the way
it does.

Searching a company name can return a **live, correct-looking board that belongs
to somebody else**. Measured 2026-09-01: searching `Databricks` returned
Guidehouse's Workday board at rank 1 with **794 real jobs**. It resolves, it
probes green, and it returns genuine listings — *every automated check we own says
yes*. There is no server-side signal that distinguishes it from the right answer.

**Mitigations, in order of how much they actually do:**

- **The user reads the board's name.** `CompanyCandidateList` renders the board
  token and its live job count for every candidate, at full size, never behind a
  link or a tooltip. "guidehouse · 794 open jobs" under a search for Databricks is
  instantly wrong to a person and invisible to every check we own. This is the
  real mitigation; everything below only decides when we are allowed to skip it.
- **The name gate.** A candidate is auto-added only when the board token *names*
  the company: exact match, or a prefix at a word boundary, with a four-character
  floor. Substring and edit-distance were both tried and both let a real
  wrong-company board through (`poki` for "Poke", `river` for "Hudson River
  Trading", `meta` for "Metabase").
- **Generic career-site slugs are excluded.** `career_site_slug` is routinely an
  ordinary English word on live Workday tenants (`External`, `Global`,
  `Careers`), so a slug may never establish identity — only a board token may.
- **A non-empty probe.** A board with zero jobs is never auto-added, however well
  its token matches.

**Residual risk we accept:** a board whose token genuinely leads with the typed
name but belongs to a different company (`Sierra Space` → a board token `sierra`)
is still auto-added. The gate cannot separate that from `Cisco Systems` → `cisco`
without knowing which company the user meant, which is the thing they have not
told us. Blast radius is one user's own private company row, which they can
delete.

---

<a id="3"></a>
## 3 — A user can spend one-time discovery on a page of their choosing

**Status: Accepted.** This is the feature working as designed.

Submitting a URL with no recognised ATS behind it starts a one-time discovery: a
real browser session plus a model call, ~4–8¢, on a page the user chose. That is
the product.

**What bounds it:** the 20-adds-per-UTC-month cap (`services/add_quota.py`),
counted off `company_add_attempts` so that *attempts* count and deleting a company
does not refund a slot; a 10/60s burst limiter on the add route; and the
`CUSTOM_COMPANY_DISCOVERY_ENABLED` flag. Worst case per user per month is
therefore bounded and small.

**Known sharp edge:** the field helper says "not LinkedIn or Indeed", and *nothing
enforces it*. `_NEVER_MATCH_DOMAINS` is a denylist consulted on a different rung
and misses `dice.com`, `monster.com`, `hiring.cafe` and friends. An aggregator URL
resolves, finds no board, reaches `no_ats_detected`, and that is exactly the
branch that spends a discovery. It costs the user one of their twenty, so it is
bounded — but it is bounded by the quota, not by correctness.

---

<a id="4"></a>
## 4 — In-memory rate limiters reset on every deploy

**Status: Accepted.**

Every limiter (`services/rate_limit.py`) keeps its window in process memory: the
resolve/search limiter, the add limiter, the rename limiter. A deploy restarts the
container and every window empties, so a caller who has just been throttled gets a
fresh allowance.

**Why accepted:** these are burst smoothers, not the spend guard. The real spend
guard for adds is the monthly cap, which is counted in Postgres and survives
anything. The gap matters for risk **1**, where there is no database-backed cap
behind the limiter — which is why 1 is Open and this is not.

---

<a id="5"></a>
## 5 — User-controlled outbound fetch (SSRF surface)

**Status: Mitigated.**

Resolution, discovery and name search all fetch URLs that a user (or a third-party
search engine) supplied. This is the largest deliberate SSRF surface in the app.

**Mitigations:** `services/url_guard.py` is the single choke point — https only, no
userinfo or non-standard ports, public-DNS resolution with rejection of RFC1918,
loopback, link-local (including the `169.254` metadata address), ULA and
`0.0.0.0/8`, re-validated on **every redirect hop** rather than once. ATS API calls
are pinned to each provider's fixed host by `assert_ats_api_host`, built from the
client's own constants so a client that re-points cannot leave a stale assertion
behind. Response bodies in the discovery path are read under a byte cap.

**Specifically for name search** (verified 2026-09-02): URLs that come back from
Browserbase are **never fetched as given**. They go through the pure, IO-free
`resolve_ats_url`, and only a URL that resolves to a known board is probed — at
that provider's own API host, re-asserted. The `careersUrl` we hand back to the
client is *not* validated at that moment, but it is never fetched by us, is
rendered as text rather than a link, and is re-guarded by `url_guard` if the user
submits it to the add endpoint.

**Residual:** a single `/resolve` call can now issue up to ~50 outbound requests
worst case (the L2 walk-up raised the sniff target cap from 4 to 8), all to one
host, all inside one user request. It is bounded by the 25-second budget threaded
through every hop, but it is an amplification factor worth knowing about.

---

<a id="6"></a>
## 6 — ATS client responses have no byte cap

**Status: Open.** Pre-existing; surfaced during the name-search review.

`url_guard.guarded_get` caps response bodies. The six ATS clients
(`greenhouse_client.py` and siblings) call `fetch_jobs` directly and **do not** —
verified 2026-09-02: no `max_bytes` anywhere in `services/*_client.py`. A hostile
or merely enormous board response is read fully into memory.

Name search multiplies the exposure: it probes up to **five** candidates
concurrently inside one request, so peak memory for a single call is now ~5× what
the single-probe `/resolve` path could reach.

**Why it is not urgent:** the probed hosts are the six real ATS providers, pinned
by `assert_ats_api_host`, so this is an availability concern (a provider serving
something enormous) rather than an attacker-controlled one. **Why it is not
closed:** it belongs in the shared client layer, not in this feature.
