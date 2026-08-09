# Custom Company Sources — the plan, in one read

**Status:** proposed, awaiting owner approval. Supersedes the ATS-only scope in `PLAN.md`.
**Evidence:** 11 careers sites tested end-to-end overnight 2026-08-08/09, plus a ~40-firm survey. $0 spent, ~22 of 60 free Browserbase minutes used.

---

## The goal

> A user pastes a careers URL (or types a company name). We check it **every 24 hours** and show them the jobs — for them only.

The bar you set: **it has to work on nearly every board you throw at it.**

---

## Did it pass?

Your named hard cases, all verified by actually harvesting them:

| Target | Result | Harvested / true total |
|---|---|---|
| **Amazon** | ✅ verified | **22,191 / 22,191** |
| **Meta** | ✅ verified | **821 / 821** |
| **Duolingo** | ✅ verified | 65 / 65 — *already works in shipped code* |
| **Cisco** | ✅ verified | 1,071 / 1,071 |
| **Intel** | ✅ verified | 663 / 663 |
| **Urban Edge** (CRE, zero jobs) | ✅ verified **zero** | 0 / 0, board proven live |
| **Rockefeller Group** (CRE, few) | ✅ verified | 4 / 4 |
| **Monroe County Hospital** | ✅ verified | 12 / 12 |
| Y Combinator | ⚠️ unverified | 5,411 — YC's only published total is the string `"thousands"` |
| Blackburn's Fabrication | ⚠️ unverified | 3 — page publishes no count |
| Habitat Cincinnati | ⚠️ unverified | 7 — page publishes no count |

**7 verified · 3 unverified · 0 failed · 0 needed a browser at replay.**

The three misses fail for one reason: **the source publishes no total.** That's an epistemics limit, not an engineering one. We can harvest them — we just can't *prove* the harvest is complete, so we never let them close a job.

---

## The one idea that makes this work

Every naive version of this product ships a scraper that looks healthy and is quietly wrong.

```
Amazon      says "hits: 10000"      →  really 22,191   (55% missing, 3 stable runs, zero errors)
Target      says "total: 2000"      →  really 11,960   (83% missing — and the boundary probe PASSES)
Y Combinator says "nbPages: 1"      →  really 6,136    (took 1,000, every signal read "done")
Kroger      offset param ignored    →  200 of 14,760   (silently re-served page 1 forever)
```

> **A source's own declared total cannot be trusted. It is frequently the lie.**

So the system is built around one rule:

**Never trust a count unless a second, mechanically unrelated measurement agrees with it.**

For Amazon that second measurement is its own facet breakdown — six unrelated facets each summing to exactly 22,191 while `hits` insisted on 10,000. And the same trick that *detects* the cap also *fixes* it: partition the query by facet, sweep each partition under the cap, sum.

**Strongest evidence from the whole run:** over 37 minutes, Amazon's job-id set moved **+4 / −2** while the facet oracle independently moved **22,191 → 22,193**. Two unrelated measurements agreeing on the same net **+2**. That means the *diff* — what opened, what closed — is trustworthy. That diff is the actual product.

---

## Architecture

```
   type a NAME ──→ slug-variant probe (0.6s, $0) ──→ picker, never auto-accept
   paste a URL ──→ url_guard (SSRF)
                        │
     ┌──────────────────▼───────────────────────────────────┐
     │  RESOLUTION LADDER — cheapest rung that works wins    │
     │                                                       │
     │  T1  known ATS        already shipped · Duolingo,     │
     │                       Cisco, Intel land here          │
     │  T2  ATS expansion    6 → 50+ providers, from         │
     │                       published fingerprint tables    │
     │  T3  HTTP recipe      agent discovers ONCE, stores a  │
     │                       deterministic recipe · Amazon,  │
     │                       Meta, the long tail             │
     │  T4  browser recipe   SPAs that need rendering (~12%) │
     │  T5  REFUSE           explicit, surfaced, not a       │
     │                       recipe that fails nightly       │
     └──────────────────┬────────────────────────────────────┘
                        ▼
     ┌──── VERIFICATION GATE — 13 ordered checks ────────────┐
     │  independent oracle · cap detection · page-advance    │
     │  fatal in BOTH directions · zero-proof chain          │
     └──────────────────┬────────────────────────────────────┘
                        ▼
     VERIFIED ────→ upsert · last_seen · miss++ · MAY CLOSE JOBS
     UNVERIFIED ──→ upsert · last_seen · ███ NEVER CLOSES ███
     FAILED ──────→ raise · writes nothing · quarantine
```

**The first harvest must be VERIFIED or the company is never created.** Failures are loud at add time, which is the only way to meet your bar honestly.

---

## Concepts we're relying on

| Concept | Why |
|---|---|
| **Discover once, replay forever** | Literature: naive LLM-on-HTML scores F1 0.10 with 91% hallucination; "induce a selector once, then execute deterministically" is the *only* method above 31% recall. Our 3-of-11 first attempt was the predicted outcome, not incompetence. |
| **ATS fingerprinting at scale** | This is how the problem is actually solved in industry. Public tables list **50+ ATS platforms and 63,000 tenants**; hiring.cafe reached ~116k companies this way. We hand-wrote 6. |
| **Independent oracle** | The declared total is untrustworthy. Facet sums, response headers (`X-WP-Total`), sitemap counts, second requests. |
| **Provenance, not silence** | `oracle: none` is a permanent visible state on the company — never a silent default. |
| **Zero-proof chain** | A company with 0 jobs must *prove* it. See below. |
| **Refuse as a product state** | Tesla-class sites get an honest "we can't track this," not a nightly failure. |

---

## Why "zero jobs" nearly broke us

Your instinct here was the sharpest test in the set.

**Marcus & Millichap's Lever board returns `200 []` with a polished empty state reading "No job postings currently open." The company has 204 open roles on Workday.**

A naive check calls that a healthy, verified zero — and closes 204 jobs. Four signals are required:

```
1. liveness         real board 200 []   ·  bogus id → 404 RESOURCE_NOT_FOUND
2. empty state      "We're not actively hiring at the moment"
3. brand present    "Urban Edge Properties" on the board   → catches domain takeover
4. canonical link   careers page still points at this board → catches ABANDONED board
                                                               ↑ the only one that
                                                                 catches M&M
```

---

## Cost

| | per company / month |
|---|---|
| HTTP tiers (most companies) | **$0** |
| One-time discovery (local browser, ~10–30s) | **$0** |
| Browser at replay (~12% of companies) | **$0.06** |
| Browserbase subscription floor | **$20/mo** (only if T4 ships) |

You were right that daily cadence makes browser-at-replay affordable. It turns out we need it far less than expected.

---

## Honest coverage

- **Your named list: 7/10 verified.**
- Broader 25-employer sample: ~64% today → **~84%** with the full ladder.
- **Realistic forecast for arbitrary input: 60–70%**, and I won't promise better until real numbers land.
- Of 9 tech employers tested, **0** were hard. Of 16 non-tech, **6** were. Small non-tech employers are where this thins out — many have no machine-readable board at all.

**You cannot get to "every board." You can get to "never silently wrong."** A system that verifies 70% and cleanly refuses the rest is shippable. One claiming 95% that serves 200 of Kroger's 14,760 jobs is not.

---

## Top risks

1. **A vendor we haven't characterized ships an undetected cap.** Mitigation: `oracle: none` blocks closure; per-vendor oracles are added as we meet them.
2. **Per-user leakage.** Three confirmed leak paths exist in current code — `/api/jobs` has no auth dependency at all, and auto-enroll has **no user scoping**, so one inserted row auto-enrolls every user. Fixed in Phase 1.
3. **Browser in the API container.** Two prior incidents (OOM, pthread exhaustion). Browser tiers run on a separate Railway service or not at all.

---

## Decisions I need from you

1. **Do permanently-unverifiable companies ship?** (YC, Blackburn's, Habitat.) My recommendation: yes — visible, jobs shown, badge says "can't confirm completeness," **nothing ever closes**. Alternative: refuse them.
2. **Name input in Phase 2 or later?** Cheap and covers ~92%, but it's the most likely way to track the *wrong* company. Recommendation: Phase 2 with a mandatory picker, no auto-accept.
3. **Separate Railway service for browser tiers?** ~$5–20/mo. Recommendation: yes — the OOM incident took 49 hours to manifest and left no logs.
4. **Close after 2 missed runs (~48h)?** Recommendation: keep 2, add a 36-hour wall-clock floor so a manual re-run can't accelerate closure.

---

**Implementation detail:** `BUILD-PLAN.md` (same directory).
