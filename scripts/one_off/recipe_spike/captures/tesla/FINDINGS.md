# Tesla — scrape-recipe discovery findings

**Target:** tesla · **Entry URL:** `https://www.tesla.com/careers/search/` (no redirect; it is the real listing URL)
**Date:** 2026-08-05 · **Discovery cost:** $0 (local Playwright + httpx only)

---

## VERDICT: NO RECIPE

**Tesla's careers app is behind Akamai Bot Manager, which 403s every HTTP client and every
Playwright-bundled Chromium — the complete jobs payload is only obtainable from a real Google
Chrome binary running *headed* with synthetic mouse movement, which `replay.py`'s executor
cannot do and a cron worker should not do.**

No `recipes/tesla.json` was written. The absence of a recipe is the result.

The data itself was fully located and decoded (see "Where the jobs actually live") — this is a
*reachability* failure, not a discovery failure.

---

## What blocks it

**Akamai Bot Manager**, identified positively, not guessed:

| Evidence | Source |
| --- | --- |
| `<TITLE>Access Denied</TITLE>` + `Reference #18.8617dd17.…` + `https://errors.edgesuite.net/…` | every 403 body; `edgesuite.net` is Akamai's edge network |
| `_abck`, `bm_sz`, `bm_so`, `bm_lso`, `bm_s`, `bm_sc` cookies issued on the first headed load | `probe4_headed.py` |
| Obfuscated sensor endpoint POSTed twice on load: `https://www.tesla.com/ihmpYM/U2mW/q_tOa/…` → `201`, 18 bytes | `probe4_headed.py` |
| `_abck` cookie flips to its validated `~0~` form only after human-like input | `probe6_stealth.py` (`abck_valid=True`) vs `probe5_reload.py` (`abck_valid=False` ×3) |

The gate is a **client-fingerprint + behavioral-sensor** check, not IP reputation and not
rate limiting: the *same machine, same IP, same second* is refused as httpx and served as
headed Chrome.

---

## Everything tried, in order

| # | Probe | What was sent | What came back |
| --- | --- | --- | --- |
| 0 | `capture.py --wait networkidle --scroll 2` | Playwright **bundled Chromium, headless**, UA Chrome/120, 1920×1080 | `page_title: "Access Denied"`, **1 total response**, 0 XHR, 0 JSON islands |
| 1 | `probe.py` | httpx GET `/careers/search/` and `/cua-api/apps/careers/state`, Chrome UA | **403** / 390 b and **403** / 409 b |
| 2 | `probe2.py` | httpx with 3 header profiles: full Chrome set, bare httpx default, Firefox UA | **403** on all three, byte-identical bodies — header shaping changes nothing |
| 3 | `curl` | `--http2` with Chrome headers, and `--http1.1` bare | **403** both. `curl` is refused even on `/robots.txt` where httpx is allowed — the discriminator is below the header layer (TLS/JA3 + HTTP/2 fingerprint) |
| 4 | `probe3_chrome.py` | **Real Chrome** (`channel="chrome"`), **headless**, fresh profile | `Access Denied`; in-page fetch → **403**; **zero cookies issued** |
| 5 | `probe4_headed.py` | Real Chrome, **headed**, fresh profile, no input simulation | `Access Denied`, but Akamai *did* issue `bm_*`/`_abck` and fired 2 sensor POSTs (`201`) |
| 6 | `probe5_reload.py` | Real Chrome, headed, **persistent profile**, 3 reloads to let the sensor validate | `Access Denied` ×3, `_abck` never reached `~0~`. Reloading alone does not earn trust |
| 7 | `probe6_stealth.py` | Real Chrome, headed, persistent profile, `--disable-blink-features=AutomationControlled`, **6 randomized `mouse.move()` with step interpolation + a scroll** | ✅ **PASS on attempt 0.** `navigator.webdriver=false`, `_abck` validated (`~0~`), `/cua-api/apps/careers/state` → **200 / 1,454,472 bytes / 7,597 listings** |
| 8 | `probe7_transplant.py` | **Cookie transplant**: validated `_abck`+`bm_*` from the trusted Chrome session replayed through httpx with that session's UA and Referer | **403.** Valid cookies do *not* transfer — Akamai binds the session to the TLS/HTTP2 fingerprint that earned it. Kills every "warm once, then httpx forever" design |
| 9 | `probe8_headless_chrome.py` | Real Chrome **headless**, (A) fresh profile, (B) the already-trusted profile from #7 | (A) **403**. (B) page loaded off the pre-warmed cookie but the next in-page fetch was **403** — borrowed trust is not renewed in headless |
| 10 | `probe9_scope.py` | httpx across 7 paths/hosts to scope the block | `/robots.txt` **200**; `/`, `/careers`, job detail, `/cua-api/…` all **403**. The block covers the whole app |
| 11 | `probe11_alt_hosts.py` | Hunt for a less-defended origin serving the same payload | ✅ `www.tesla.cn/cua-api/apps/careers/state` → **200 to plain httpx**. ❌ but see "The tesla.cn trap" |
| 12 | `probe12_matrix.py` | Bundled Playwright Chromium, **headed** *and* headless | **`Access Denied` in BOTH.** Decisive: it is not headlessness alone — Akamai rejects the Playwright Chromium *build* even with a visible window |
| 13 | `probe13_semantics.py` | Re-visit with the trusted profile but **no mouse movement** | **`Access Denied`.** Confirms the behavioral sensor, not the profile, carries the session |
| 14 | `probe14_total.py` / `probe15_verify.py` | Headed Chrome + mouse movement, to read the site's own claimed total and validate the payload | ✅ passed; see "Completeness cross-check" |

---

## HTTP layer only, or also a real browser?

**The decision-relevant answer: the block defeats a real *local* browser too, unless that
browser is genuine Chrome, headed, and generating input events.** Full matrix, same machine
and IP throughout:

| Client | Headed? | Result |
| --- | --- | --- |
| httpx (any header profile) | — | ❌ 403 |
| httpx + valid transplanted Akamai cookies | — | ❌ 403 |
| curl (HTTP/1.1 and HTTP/2) | — | ❌ 403 |
| **Playwright bundled Chromium** — *exactly what `replay.run_browser_dom` launches* | headless | ❌ 403 |
| Playwright bundled Chromium | **headed** | ❌ 403 |
| Real Google Chrome (`channel="chrome"`) | headless | ❌ 403 |
| Real Google Chrome, pre-warmed profile | headless | ⚠️ initial load only, next request 403 |
| Real Google Chrome, no input simulation | headed | ❌ 403 |
| **Real Google Chrome + randomized mouse movement** | **headed** | ✅ **200, 7,597 listings** |

So this is **not** the clean "a browser fixes it" case that would justify flipping the recipe
to `browser_dom`. Doing so today would produce a recipe that `replay.py` fails on every run —
the executor's bundled headless Chromium is on the wrong side of the line. Two independent
upgrades would be needed *together*: a real Chrome binary **and** headed operation with
synthetic input. A cloud browser with residential IPs is also not obviously sufficient — the
IP was never the problem here.

---

## Is Tesla unreachable in principle?

**No — but it is decisively out of budget for a one-time discovery pass, and a poor fit for
unattended replay.**

- **In principle: reachable.** It fell to an ordinary technique — real Chrome, a window, eight
  randomized mouse moves — on the *first* attempt. No CAPTCHA, no login, no proof-of-work.
- **The blocker is not the IP.** Success and failure alternated on one machine purely by
  client identity and input behavior. Residential proxies would not have changed a single row
  in the matrix. Spending money here buys nothing.
- **But the maintenance shape is bad.** A recipe needing a headed real-Chrome session with
  humanized input is not a *deterministic replay* — it is an arms race with a sensor Akamai
  tunes continuously. Probe 13 is the tell: the same trusted profile that worked minutes
  earlier was refused as soon as the mouse stopped moving. That fails intermittently, for
  reasons the logs will not explain.
- **Recommendation:** deprioritize rather than declare impossible. If it ever becomes
  business-critical, the cost is a dedicated headed-Chrome-under-Xvfb runner with an input
  simulator and a re-warm loop — a standing service, not a recipe. Revisit only with that
  budget explicitly approved.

---

## Where the jobs actually live

Located and fully decoded — the data was never the hard part.

    GET https://www.tesla.com/cua-api/apps/careers/state
    → 200, application/json, 1,454,472 bytes, ONE request, NO pagination

Top-level keys: `lookup`, `departments`, `geo`, `listings`. `listings` is a 7,597-element
array of aggressively abbreviated records:

    {"id":"224501","t":"AI Engineer, Manipulation, Optimus","dp":"3","f":"74","l":"401022","y":1,"sp":1,"pu":null}

| Key | Meaning | Non-null coverage |
| --- | --- | --- |
| `id` | requisition id — all 7,597 distinct | 7597/7597 |
| `t` | job title | 7597/7597 |
| `dp` | department id → `lookup.departments` | 7597/7597 |
| `f` | sub-department id; **no name lookup ships in this payload** | 7597/7597 |
| `l` | location id → `lookup.locations` (`"401022"` = "Palo Alto, California") | 7597/7597 |
| `y` | employment type → `lookup.types` | 7597/7597 |
| `sp` | undecoded (small int; likely sort priority) | 7597/7597 |
| `pu` | an ISO date, semantics unconfirmed (looks like posting expiry) | **44/7597** |

**No posted-at / created-at field exists anywhere in the payload.** Job-age analytics would
require a per-job detail fetch — 7,597 more requests through the same wall.

**Job URLs:** `https://www.tesla.com/careers/search/job/{id}` resolves with the bare id
(verified). The slugged form the UI links is not required — which matters, because the payload
ships no slug and slugifying the title would be a guess.

**Pagination: none.** One request is the whole board. `robots.txt` states `Crawl-delay: 10` and
does **not** disallow `/careers/` or `/cua-api/` (`Disallow: /search/` is root-anchored).

A candidate recipe expressing all of this is preserved at `tesla-candidate-browser_dom.json` —
**correct about the data, unrunnable by `replay.py`.**

### Completeness cross-check

- Tesla's UI reported **"4830 Results"** under its default `United States of America` filter.
- Filtering the 7,597 `listings` by US location ids from the `geo` tree yields **exactly 4,830**.

The payload is the complete superset (55 countries) and the site's own counter corroborates it
to the unit. Global total: **7,597**.

### The tesla.cn trap

`https://www.tesla.cn/cua-api/apps/careers/state` returns **200 to plain httpx** — no Akamai
challenge, same JSON shape. It is a trap:

- It contains **28 listings**, all `China Mainland`.
- **Zero** of its 28 ids appear in the global 7,597 set — a disjoint China-only board, not a subset.
- Coverage of the intended target: **0.0%**.

Shipping it as `recipes/tesla.json` would have produced a green `OK 28 jobs` replay while
missing 7,597 jobs — precisely the shape of the 3,582-job false-closure incident this spike
exists to prevent. Rejected on those grounds. **Any future Tesla attempt must cross-check
against the site's own counter before being believed.**

---

## SCHEMA GAP

None of these are why Tesla failed — the anti-bot wall is. Even a perfect schema would still
403. Fix only if Tesla is revived:

1. **No way to request a real-Chrome / headed browser.** `replay.run_browser_dom` hard-codes
   `pw.chromium.launch(headless=True, …)`; the schema cannot express `channel: "chrome"`,
   `headless: false`, or input simulation.
2. **No lookup-table joins.** `fields` maps dotted paths within a single record, but Tesla's
   rows carry `l`/`dp`/`y` as ids resolved against sibling `lookup.*` dictionaries. A recipe
   can emit `location_id: "401022"` but never `location: "Palo Alto, California"`. Compact
   rows + a sidecar lookup table is a common enough pattern to warrant a `lookups` block.
3. **No UI-scraped completeness oracle.** `expected_min_jobs` is a static floor and
   `total_path` only reads a total the *payload* publishes. The near-miss here — a valid
   endpoint serving a disjoint 0.4% of the board — would pass any floor set below 28. An
   assertion against a number scraped from the site's own UI would have caught the tesla.cn
   trap mechanically instead of relying on the agent noticing.

---

## Measurements

| Metric | Value |
| --- | --- |
| `capture.py` wall time | 6.6 s (empty report — the 403 page) |
| Total discovery wall time | ~35 min across 16 probes |
| Requests to tesla.com | ~40 navigations/API calls over ~10 page loads; well inside `Crawl-delay: 10` |
| Replay time | n/a — no recipe |
| Jobs achieved by a replayable recipe | **0** |
| Jobs located but not replayably reachable | **7,597** |
| Site-claimed total | **4,830** US (matched exactly) / 7,597 global |
| Dollars | **$0.00** |

## Artifacts

Kept: `probe*.py` (16 probes, re-runnable), `page.html` (the 403 body), `report.json` (the
empty capture), `tesla-candidate-browser_dom.json`, `state_cn.json`, `state_via_browser.json`,
`careers_page_text.txt`.

Deleted after write-up: `chrome_profile*/` (~32 MB) and all `*cookies*.json` — harvested Akamai
session cookies are credentials and were not left on disk.
