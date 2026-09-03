# Row sharing — why a second user gets a second board, and what it would take not to

**The question.** Two users add `lifeatspotify.com/jobs`. Today they get **two `companies` rows, two scrapers, two copies of every job**. Should the second user instead just become an *owner* of the first one?

**The answer.** Yes — that is the right design. It is **deliberately not built**, and **one specific thing blocks it**: the `provider_config.discovery` blob we return to the owner contains the *first* user's browser session URL, their captured request log and a raw job sample. Under sharing that goes to everybody. **Fix the projection first.**

> The cost/benefit analysis behind this — the four candidate mechanisms, the measured Spotify pair, the `canonical_source_key` analysis, and what a duplicate actually costs — is **`ENRICHMENT-TRADEOFFS.md` §9.3**. This document does not restate it. It records what the code does today, what blocks the change, and what P1 is.

---

## What happens today, and the line that makes it true

Every insert path does **one `INSERT INTO companies` immediately followed by one `INSERT INTO user_companies`, in a single transaction**. Nothing anywhere links a second user to an existing row.

| Path | Where | Shape |
|---|---|---|
| ATS board | `custom_companies_service.py:400-421` | `INSERT companies` → `INSERT user_companies` → `INSERT company_scripts` → audit row |
| Discovered board (the 202 placeholder) | `custom_companies_service.py:557-578` | `INSERT companies` → `INSERT user_companies` → audit row |
| Discovery accepts | `_promote_to_tracked` | **UPDATEs** the placeholder — it promotes, it never creates |

The reason a second user's lookup **structurally cannot find** the first user's row is that **the user id is inside the idempotency key**:

```sql
-- db_models.py:762-764
UNIQUE (user_id, canonical_source_key)

-- custom_companies_service.py:46-64  · find_owned_company_by_source_key
WHERE uc.user_id = %s AND uc.canonical_source_key = %s
```

`canonical_source_key` is `"{ats}:{token}"` (or `"discovered:{final_url}"`). It is a **per-user** key, not a board key. `db_models.py:737-741` states the consequence in the model itself: *"two different users who add the same board get two DISTINCT company rows (and two `custom:<id>` source_ids), but one user re-adding it resolves to their existing row."*

The door was left open on purpose: `remove_owned_company` already counts remaining owners and returns `'unlinked'` without purging when any remain. **Sharing needs no new delete logic.**

---

## What a duplicate costs

| Cost | Per duplicate board | Notes |
|---|---|---|
| Browser capture at add | **one Chromium session, 33–95 s** | measured: Spotify 33 s, Atlassian 33 s, Microsoft 95 s |
| LLM spend at add | one request-selection call | one Haiku call |
| Recurring browser time | **zero** | every board so far replays as `http_json` / `ats_client` |
| Recurring harvest | **one extra board on the 24 h cadence, forever** | the real recurring cost |
| Enrichment queue | **the whole job set, once** | 85 rows for Spotify; 2,055 for Microsoft |
| Custom enrichment budget | ~1.9 days of the *entire* custom slice | at 10 % of a 40-job tick |
| GPU wall-clock | ~6.0 h | 153 s classify + 100 s judge per title-only row |

⚠️ **And duplicates go to the FRONT of the queue, not the back.** The claim orders `first_seen_at DESC` inside each tier and again inside each company's recency rank (`routers/internal_enrichment.py:162`, `:206-211`). A newly-added board's rows are by construction the **newest rows in the table**, so a duplicate does not wait behind the backlog — it *is* the head of it.

---

## ⚠️ The blocker: `provider_config.discovery` leaks the first user's session

`GET /api/users/companies` hands the owner the discovery blob verbatim (`routers/user_companies.py:111` → `services/discovery/progress.py:730-740`). It contains:

| Field | What it is | Under sharing |
|---|---|---|
| `live_view_url` | the **first user's Browserbase live-view session URL** | ✕ never |
| `network` | their **full captured request log** — every XHR the capture browser saw on their paste | ✕ never |
| `job_preview` | a raw sample of rows from that capture | ✕ never |
| `steps`, `outcome`, `updated_at` | the 5-rung checklist | ~ first owner's run only |

Two more surfaces must stay closed:

- **Never expose the owner list.** "Who else tracks this board" is not a fact any owner is entitled to.
- **Never expose `company_add_attempts`.** It carries `user_id` and the **raw submitted URL** — which is often a filtered, personal query string.

**What legitimately becomes a shared fact:** `open_job_count`, `health_state`, `last_success_at`, `tracking_started_at`. B learns somebody tracked it, never who.

**→ The projection must be fixed before sharing can ship.** This is the gating item, not a follow-up.

---

## The decision that has to be made consciously

A joining user **inherits the entire job history**, including `first_seen_at` values from before they arrived.

| Question the page asks | Inherited history is… |
|---|---|
| "What has this company's hiring looked like?" | ✅ **correct** — more history is strictly better |
| "What's new since I started watching?" | ✕ **wrong** — the first month is somebody else's |

The trend page already draws this distinction with `tracking_started_at` (`db_models.py:704-706` — set on the first VERIFIED harvest, used to shade the pre-tracking seed bucket). Under sharing that column is **per-company and would need a per-owner equivalent** — `user_companies.created_at` already exists and is exactly that timestamp. **Decide it deliberately; do not let it fall out of the join.**

---

## Why sharing is safe for the close guarantees — and fan-out is not

Closes are decided in exactly two places, both scoped **per `source_id`**:

- the harvest verification gate (only a VERIFIED run may close), and
- `job_freshness` / `consecutive_misses`,

and there is **exactly one scraper writing each `source_id`**.

> **Sharing adds OWNERS. It never adds WRITERS.** The number of processes that can close a job under `custom:<id>` stays at one, whether the board has one owner or fifty. Nothing in the close path reads `user_companies` at all.

That is the whole argument against the rejected **"canonical identity table"** alternative (`ENRICHMENT-TRADEOFFS.md` §9.3, option 2): it scrapes once per *identity* and fans rows out into per-user company namespaces — **adding a writer per namespace**. It also buys back only the 33 seconds of browser time while leaving every duplicate row in the enrichment queue, which is the expensive half. Prefer sharing.

---

## What P1 actually is

**Ordering, and it is not negotiable:**

| # | Step | Why in this order |
|---|---|---|
| 0 | **Fix the `provider_config` projection** | the blocker above; nothing else may ship first |
| 1 | **Resolve-and-link** (option 3) — a pasted URL resolves to a **public** board and we return a link, creating nothing | cost of being wrong: **none** (the user clicks "track it anyway"). No schema change, no privacy question, no deletion question. **Always, and first.** |
| 2 | **Shared row, many owners** (option 1) — behind the confidence bar below | cost of being wrong: **high** — one shared job history, corrupted for everyone, no undo |
| ✕ | **Merge-on-detect** (option 4) | **never.** Merges at 3am, unobserved, with no un-merge and no audit of which rows came from which board |

**The confidence bar, already agreed — two INDEPENDENT signals, both required:**

1. **Identical normalized captured endpoint** — the URL marked `"state": "chosen"` in `provider_config.discovery.network.requests[]`. It is what the board *is*, it is proven by replay rather than guessed, and it survives a front-end host move. It is a **key, not an oracle** (§9.3: it fails on the Spotify pair, on multi-tenant feed hosts, on a `/v1/`→`/v2/` bump, and on ATS-resolved boards which have no captured endpoint at all).
2. **A live probe showing ≥70 % job-id overlap** between the two boards.

One signal alone is not enough — that is the entire lesson of the measured Spotify pair, where every URL-derived signal disagreed and the **titles overlapped 86 %**.

**Not part of P1:** normalizing away query strings. The Jane Street row (`?type=experienced-candidates&location=new-york`) is a *filtered* board; merging it into the full board makes the full board's gate start closing jobs the filtered board never claimed to see. **Query-stripping here is a correctness bug, not a normalization improvement.**

---

## See also

- **`ENRICHMENT-TRADEOFFS.md` §9.3** — the analysis this document rests on: the four mechanisms, the Spotify measurement, the cost table
- `OVERVIEW.md` — the architecture and the close guarantees
- `STACK-ORCHESTRATION.md` — the build log
