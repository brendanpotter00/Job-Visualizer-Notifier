# Add Companies — case table

The contract `.claude/skills/e2e-gate/sections/add-companies.md` reads. See `PLAN.md` for
the full reasoning behind every case; this is the quick-reference + current status.

**Auth**: the primary approach (mint an RS256 token, patch `api.auth.jwt._get_jwks_client`)
worked on the first try — no fallback was needed. Verified live: `GET /api/users/companies`
with a minted token returns `{"companies":[]}` against the real `get_current_user` dependency
chain, with `jwt.decode` genuinely checking algorithm/audience/issuer/expiry/email.

**Non-coverage, stated plainly** (PLAN.md §2 "Trap 1"): this suite runs the frontend under
plain `vite dev` with a whole-`/api`-prefix proxy, not `vercel dev`. The Vercel serverless
proxies (`api/users.ts`, `api/companies.ts`, `api/jobs.ts`) are **not exercised** by this
suite. They are thin (forward + re-emit headers) and are a known gap, not an oversight.

## Case table

| ID | Board | Tier | `live` marker | Status | Notes |
|---|---|---|---|---|---|
| AC-01 | Microsoft | API + UI | fast (network, no LLM) | 🟢 GREEN | careers-host dedupe; **terminal** — the UI spec now asserts there is NO way past it |
| AC-02 | Amazon | API | fast (network, no LLM) | 🟢 GREEN | same mechanism as AC-01 |
| AC-03 | Cisco | API + UI | live (harvest wait, no LLM) | 🟢 GREEN | embedded Workday; posted_on coverage ~68% live (see below — plan claimed 100%) |
| AC-04 | Atlassian | API | live (LLM) | 🟢 GREEN | 239 jobs harvested at measurement time (plan estimated ~250). **Now lands VERIFIED `history_delta_ok`, not `UNVERIFIED no_oracle`** — the history-delta oracle; the case asserts the mechanism and that the first run still closes nothing. See `CLOSING-NO-ORACLE-BOARDS.md` |
| AC-05 | Jane Street | API | live (LLM) | 🟢 GREEN | 234 jobs harvested (plan estimated ~235). Same verdict change as AC-04 |
| AC-06 | Spotify (lifeatspotify.com) | API + UI | live (LLM) | 🟢 GREEN (was RED at plan time) | the §11.2 trigger fix landed mid-build; asserts intended behaviour either way — see PLAN.md note in `test_public_match.py` |
| AC-06a | seeded rows | API | fast, hermetic | 🟢 GREEN | no network, no LLM; exercises the real matcher directly |
| AC-07 | Cisco (reused) | API + UI | live (harvest wait) | 🟢 GREEN | full purge + `ownerlessCount` delta + fresh re-add |
| AC-08 | Cisco | UI only | live | 🟢 GREEN | the full human journey, 33-35s |
| AC-09 | flags | API | split — sources-off is fast, discovery-off is live (network, no LLM) | 🟢 GREEN | two short-lived flagged backends on :8202 |
| AC-10 | two users | API | fast (one Cisco add, no harvest wait) | 🟢 GREEN | 403 on jobs, 404 on delete, row survives |
| AC-11 | Atlassian (reused) | API | live (LLM) | 🟢 GREEN | idempotent re-add, zero extra spend |
| AC-12 | Microsoft + trackAnyway | API | live (LLM) | 🟢 GREEN | the server-side override still works and routes through real discovery, not a static clone. **The UI no longer offers it here** — see the escape-hatch note below |
| AC-13 | Spotify (lifeatspotify.com) | API + UI | fast (one resolve, no LLM) | 🟢 GREEN | the company-name dedupe: answers `already_public`/`matchKind='name'` with **no discovery job**, and keeps the correction |
| AC-13a | the real published fleet | API | fast, hermetic | 🟢 GREEN | no network; runs the real matcher against the e2e DB's clone of prod's ~133 public rows. Pins `dropbox`≠`box` and `figma`≠`gm` |
| AC-14 | per-user add limits | API | fast (no network — `.invalid` hosts, no LLM) | 🟢 GREEN | the 20/month cap and the 10/60s burst limiter, on the real endpoint with a replayed bearer token. Two short-lived backends on :8202 with their own limits (same trick as AC-09); the main stack runs uncapped because `company_add_attempts` is append-only and survives every sweep. **Rewritten with the one-press flow** — see "What a refused add costs" below |
| AC-15 | seeded harvest histories (Goldman + Walmart shapes) | API | fast, hermetic | ⚪ NEW — not yet in a suite run | the REFUSING half of verification, and the mirror of AC-04/AC-05. No network: seeds `company_harvests` rows and drives the real `compute_baseline` + `verify_harvest` against them. Pins that a 20-of-1,074 short read and a page-one-of-N board can never verify however long their history — and, as the control, that a whole-catalogue board with the SAME history does |
| AC-16 | Meta — the real `metacareers.com/graphql` response as a fixture | API | fast, hermetic | ⚪ NEW | **BOARD-FAILURE-TRIAGE.md category A.** Meta answers its jobs GraphQL POST with `content-type: text/html` over 186,957 B of pure JSON (877 records); the recorder's `"json" in content-type` test dropped it and discovery blamed the board for loading its jobs without any JSON request. Recorded went **0 → 4** on the live board. The case also pins the HONEST end state: Meta still refuses, because its POST body is form-encoded and a bare-`httpx` replay 400s — the triage doc's "recovers Meta outright" is wrong |
| AC-17 | Uber — the real `jobs.uber.com/en/jobs/` served document | API | fast, hermetic | ⚪ NEW | **BOARD-FAILURE-TRIAGE.md category B.** `_anchor_rows` grouped on `path.rsplit("/", 1)[0] + "/"`, so a board whose job hrefs end in a slash (`/en/jobs/300235/`) put every posting in its own group of one, every group fell under `_MIN_HTML_RECORDS = 8`, and no anchor candidate was produced. A/B'd live on that one character: **10 groups of 1 → one group of 10**. YC (no trailing slash) is the control. **Correction to the triage doc**: it names Citadel as the outright recovery, but that board now answers our host-pin fetch with a Cloudflare interstitial and renders no job links at all — Uber is the board with the evidence |
| AC-18 | IBM — the real `www-api.ibm.com/search/api/v2` payload, plus a Relay fixture | API | fast, hermetic | ⚪ NEW | **BOARD-FAILURE-TRIAGE.md category C.** `_walk_record_arrays` scored only an array's DIRECT elements, so Elasticsearch `hits.hits[]._source` (element score 1) and Relay `edges[].node` (score 0) were invisible — the whole response was dropped with the tracking pings. Parametrised over both dialects because it is an ATS family, not an employer. Also pins the three ways the unwrap must NOT fire (already job-shaped, one element, two dict-valued keys) and the honest end state: IBM is now VISIBLE but still refuses, because its request carries `size: 30` and no `from` |
| AC-19 | Oracle Fusion (JPMorgan `CX_1001`) — real page-1 bytes as a fixture | API | fast, hermetic | ⚪ NEW | **BOARD-FAILURE-TRIAGE.md categories G + H.** Clause (a): a second-round "none of these is jobs" is downstream of the failure WE fed the model, so the refusal must name the step that actually failed — the fan-out logged *6 of 6 answered yes* on this board while the user was told it publishes no jobs feed. Clause (b): the `finder=findReqs;…,limit=25,offset=N` composite is paginated, so the stored recipe carries `TotalJobsCount = 7,181` as a declared oracle instead of reading 25 rows. Hermetic on purpose — once (b) landed the live board SUCCEEDS, so a live case could no longer observe (a) at all || AC-20 | Nintendo — the real Greenhouse-embed records as a fixture | API | mostly fast, hermetic; one `live` two-fetch check | ⚪ NEW | **BOARD-FAILURE-TRIAGE.md category I, the highest-exposure item in the batch.** Rung 1 takes the board's published `field_map["url"]` verbatim and fetches nothing, and **13 of 19 corpus boards take rung 1**. Nintendo's embed publishes `https://careers.nintendo.com/?gh_jid=<id>` — distinct per job, 200, and it serves the LISTING page to every one of them. The guard is zero path segments; measured live, **10 of 10 publicly fetchable corpus boards still take rung 1** and only Nintendo moves. `_assert_two_job_links_resolve` in `test_discovery.py` now applies the path check to every stored row (AC-04, AC-05) — but NOT the title check the triage asked for: Atlassian's iCIMS link renders in an iframe and carries no title at all |


## One press, not two (AC-08 and AC-14 both changed)

Pressing **Add company** used to call `POST /api/companies/resolve`, render a preview card
("Found 1,213 open jobs on Workday" plus a Job board / How we found it / Final URL grid),
and wait for a second press on **Track this company**. The owner's objection: *"We don't
need this extra step. When we say add company, we add it simple. And it either succeeds or
fails."* He is right — `POST /api/users/companies` re-resolves the raw pasted URL from
scratch, so the middle step decided nothing the first press had not already decided.

The frontend no longer calls `/api/companies/resolve` at all. That endpoint still exists,
persists nothing, and keeps its own tests — it just has no caller.

**AC-08** now asserts paste → one press → `add-company-success`, and that
`add-company-button` / `resolve-headline` do not exist.

### What a refused add costs — the regression the preview used to hide

With the preview gone, every typo hits the add endpoint directly. Two things had to move
server-side, because the client-side gate that used to buy them is gone:

| The URL | Discovery? | Monthly slot? |
|---|---|---|
| we READ the page, no board we support (`no_ats_detected`) | **yes** — that is what it is for | **yes**, it spends a Chromium session + an LLM call |
| we could not READ it (`scheme_not_https`, `resolves_to_private_address`, `dns_resolution_failed`, a redirect loop, a timeout) | **no** | **no** — nothing recorded |

Before the change, `if discovery_enabled and result.final_url` was the whole gate, and
`final_url` falls back to the URL the user typed — so `https://192.168.1.1/careers` would
have inserted a provisional row and queued a capture run for an address the resolver had
just refused to fetch. (The capture re-runs the same guard, so nothing could leak; it still
burnt a queue job and a monthly slot and left the user watching a "Setting up…" row that
could only end `refused`.)

**AC-14's monthly-cap case was rewritten, not deleted.** It used to assert "three refused
`.invalid` adds still spend the month" — defensible while a URL only reached this endpoint
after a free resolve, and a fine for a typo once every URL lands here. It now asserts the
`.invalid` refusals cost **nothing**, then seeds three `company_add_attempts` rows
(`db.seed_add_attempts`, the mirror of the existing `clear_add_attempts`) to sit the user
at the cap and drive the real `monthly_limit_reached` refusal. Seeding is necessary because
after the change there is no cheap way to spend a slot through the API — every real one
costs a live board, a harvest, or an LLM call.

## The escape hatch: who still gets one, and why

Certainty decides. It is not a style choice, and the two halves are asserted separately.

| Match | Evidence | Way past the notice |
|---|---|---|
| ATS board token (AC-11-adjacent) | a resolved `(ats, boardToken)` pair | **none** — terminal |
| Careers host (AC-01, AC-02) | a host in our own declared table | **none** — terminal |
| Company name in the domain (AC-13) | a string read out of a web address | **kept**, worded as a correction |

The owner's objection, on the Amazon notice: *"There should not be an option to track it
separately anyway. This is an anti-pattern... Why would we let them track something that we
already track?"* He is right for the exact matches — a private duplicate re-scrapes the
same feed and hands the user a chart whose history starts today, with the full history one
click away in the notice itself. Offering a strictly worse option is not user agency.

It does NOT follow for the name match, and that is the load-bearing distinction. That rung
is a guess, so its failure mode is a false positive: somebody whose company merely shares a
string with one of ours. With no way out, a wrong guess **hard-blocks** them from adding a
legitimately different company, with no way to tell us we were wrong — a worse anti-pattern
than the one that was removed. So it keeps a button, worded *"This isn't the same company"*
rather than *"Track it separately anyway"*: correcting us, not opting into a duplicate.

**The server still honours `trackAnyway: true` on every rung** (AC-12 asserts it on the
careers-host path). Only the UI affordance was removed from the certain ones, so a bookmark
or a replayed request never 500s.

## AC-06 now reaches discovery through the correction

`lifeatspotify.com`'s FIRST answer is the name dedupe (that is the whole point of AC-13), so
AC-06 — which needs a really-discovered Spotify board to run the title-overlap matcher
against — gets one the way a user would: it asserts the `already_public` notice, then sends
`trackAnyway`. `boards.py`'s `SPOTIFY.path` changed from `discovery` to `already_public` to
match. The Unit-10 assertions themselves are untouched.

## The `--fast` / `live` split — a judgment call

PLAN.md §7 says "`--fast`: everything except AC-03/04/05/06" in one sentence, but its own
runtime table separately groups AC-09–12 as "cheap, hermetic, ~60s total" — those two
statements are inconsistent (AC-11/AC-12 spend a real LLM call and 30-90s each; they cannot
be part of a ~60s hermetic bucket). Resolved as: `--fast` excludes anything that **waits on
an async harvest or discovery to settle**, regardless of whether that wait itself costs an
LLM call — so AC-03 and AC-07 (Cisco, no LLM but a real harvest wait) are excluded from
`--fast` alongside AC-04/05/06/11/12 (LLM). AC-01/02/09/10 stay in `--fast`: they touch the
network (one HTTP resolve, no browser/LLM) but never wait on anything async.

## Known drift from the plan's own measurements

- **AC-03 posted_on coverage**: PLAN.md claimed "measured 1246/1246" (100%). Live
  measurement: 822 of 1214 (~68%). Confirmed via the backend log that this is not a parser
  bug (zero "unparseable postedOn" warnings) — Cisco's own Workday feed genuinely omits
  `postedOn` for a real subset of postings. The test asserts `> 0`, not `== total`, and
  prints the live ratio every run.
- **Job counts**: Atlassian 239 (plan: ~250), Jane Street 234 (plan: ~235) — within the
  loose sanity band; reported, not asserted exactly, per PLAN.md §5/§13.
- **AC-08's "non-zero count" assertion was substring-fragile, and it fired.** It was
  `expect(row).not.toContainText('0 open jobs')` — a plain substring test over the whole
  row's text — so on run `20260828T014754Z` Cisco's live count of **1,230** rendered as
  "1,230 open jobs", which contains "0 open jobs", and the case went RED with a message
  that read like a product regression. It would fire on any count ending in zero, roughly
  one run in ten. Now asserted positively (`/[1-9][\d,]* open jobs?/`), which says what the
  case means and still fails on a genuine zero. Nothing about the product changed.
- **AC-06's title-overlap numbers move.** PLAN.md quoted a static measurement (70 shared of
  79/80, ratio 0.875) taken against the dev DB at plan-writing time. The suite never
  hardcodes that — it asserts `shared >= 20` and `ratio >= 0.70` (the product's own
  thresholds), because Spotify's live public title set drifts run to run. Do not add a
  tighter tolerance around any specific ratio; the qualifying-verdict assertion is the
  correct one and already catches a real regression.

## A second polling trap, found live (not in PLAN.md)

`mark_last_success` (drives the "Successfully tracking" chip) and `suggest_published_board`
(drives the public-board-match banner) are two SEPARATE sequential writes inside the same
harvest task, not one atomic commit — measured ~0.5s apart in the backend log. `MyCompaniesList`
stops polling the instant the row settles to "Successfully tracking" (`pollIntervalFor` → 0),
which can be BEFORE the suggestion write lands. A bare `toBeVisible()` on the banner after
waiting for the chip text can therefore poll a DOM the app has already stopped refreshing, and
hang to its own timeout — this bit `checklist.spec.ts` on the first full run. Fixed with the
same reload-driven wait pattern PLAN.md's own "Polling trap" already prescribes for the chip,
applied one step further (`waitForVisibleWithReload` in `e2e/add-companies/ui/helpers.ts`).

## Cost and runtime (measured — final clean run 2026-08-27, artifacts/20260827T003612Z)

**The suite has run fully green, undisturbed, end to end**: `e2e/run.sh add-companies` →
**18/18 PASS, 0 FAIL, 0 BLOCKED, exit 0**, in **377s (6m17s)** — comfortably inside PLAN.md's
8-14 min budget. API tier: 15/15 in 274.7s. UI tier: 3/3 in ~92s. Zero ERROR/Exception/Traceback
lines in the backend log for this run.

### Re-runnability: proven, not assumed (2026-08-27)

One green run proves the suite can pass. It does not prove it can pass *twice* — which is the
only property that makes it usable as a gate. Two full runs, back to back, no manual reset
between them:

| Run | Artifacts | Result | Elapsed | Exit | Code under test |
|---|---|---|---|---|---|
| 1 | `20260827T004635Z` | **18 PASS / 0 FAIL / 0 BLOCKED** | 365s | 0 | pre-hardening |
| 2 | `20260827T005249Z` | **18 PASS / 0 FAIL / 0 BLOCKED** | 374s | 0 | pre-hardening |
| 3 | `20260827T010342Z` | **18 PASS / 0 FAIL / 0 BLOCKED** | 369s | 0 | **post-hardening (what ships)** |

Runs 1 and 2 are the back-to-back re-runnability pair, deliberately made against the code
exactly as it stood when it first went green — changing the suite between them would have
proved nothing about re-running the same thing twice. Run 3 then re-confirms the same 18/18
on the shipped code after the run-lock and verdict changes landed, so the hardening is not
taken on trust either. Three consecutive green full runs, no manual reset at any point.

The evidence that run 1 genuinely cleaned up after itself is run 2's own boot log:
`_scrub: found 0 visibility='user' companies to purge`. Nothing was left behind for the
provisioning scrub to paper over — cleanup happened through the product's own
`DELETE /api/users/companies` path, per §8.

Both re-run traps PLAN.md §8 names were checked and both hold:

- **`ownerlessCount` baseline.** AC-07 reads a baseline at test start and asserts the DELTA
  (`after == baseline_ownerless`), never the absolute value. Passed in both runs. **The
  baseline is 0 in `jobscraper_e2e`** — `_scrub.py` purges every inherited `visibility='user'`
  row at clone time, so the `u-6hkpc6fh0z` orphan that motivated the delta assertion never
  reached this database (it lived in `jobscraper_pr243`, and has since been collected by
  `api.tasks.reap_ownerless_companies`). **Keep the delta assertion anyway**: the reaper now
  purges ownerless rows hourly, so an absolute assertion would be racing a sweep that is
  allowed to change the number mid-run, and the delta is correct either way.
- **The Unit-10 dismissal flag lives in localStorage**, which a DB purge cannot reset. The
  Playwright fixture takes a `browser.newContext()` per test, which starts with empty origin
  storage by construction, so run 2 cannot inherit run 1's dismissal. `checklist.spec.ts`
  passed in both runs (43.5s, then 44.2s).

Stability across the two runs is high: AC-03 harvested 1213 Cisco jobs with 821 carrying
`posted_on` (68%) in BOTH runs — identical; AC-04 239 jobs both times; AC-05 234 both times.
Owner databases were byte-identical before and after: `jobscraper_pr243` at
`138 companies / 7 user / 6 user_companies / 59056 job_listings / 50 add_attempts`, and
`jobscraper` at `129 / 31370`. `pg_stat_activity` during a run shows the e2e stack connected
only to `jobscraper_e2e`.

Getting here took two earlier full runs that were NOT clean, both traced to causes outside the
suite's own design and fixed:
1. **Run 1** (14/15 API, 2/3 UI): one API failure (Jane Street/AC-05) was the implementing agent
   running an ad-hoc DB-cleanup command against the live backend while that test's discovery was
   still polling — self-inflicted, confirmed by an immediate clean isolated re-run (234 jobs,
   34.5s). One UI failure (AC-06's checklist spec) was a genuine second polling-trap bug in the
   TEST itself (documented above) — fixed.
2. **Run 2** (12/15 API, 3 errors + 1 fail): the e2e backend process received an external
   shutdown mid-run (`httpx.ConnectError: Connection refused`) from a stray process outside this
   run's own lifecycle — a second invocation racing on the shared pidfile at
   `e2e/shared/stack/.pids/`. **NOW FIXED — and the diagnosis above was confirmed exactly.**

### The concurrent-run bug, pinned and closed

The suspicion above was verified from the logs rather than left as a guess, because "probably a
stray process" is not something a gate can ship on:

| Run | Started | `uvicorn: Shutting down` in ITS backend.log | Verdict it published |
|---|---|---|---|
| `20260827T002919Z` | 19:29:19 | **19:33:41** | 12 PASS / 7 FAIL |
| `20260827T003341Z` | **19:33:41** | 19:35:47 | 6 PASS / 13 FAIL |

`002919Z`'s backend was shut down at the exact second `003341Z` started — `stack_up.sh` calls
`stack_down.sh` unconditionally, and both runs share one `.pids/` directory, so run two killed
run one's backend AND frontend mid-test. That is the `ECONNREFUSED` on both `:8201` and `:3201`
simultaneously, which no amount of backend load can explain.

`003341Z` died the same way from the other side: pytest started 19:33:55.1, AC-05 began at
+111.2s (19:35:46.3), the backend served its last `200 OK` at 19:35:47.0 and logged
`Shutting down` at 19:35:47.8 — i.e. `run.sh`'s own cleanup trap fired **while pytest was still
running**, which only happens on INT/TERM. All 13 "failures" were one killed process.

**Queue saturation was ruled out, not assumed away.** Peak `normalize_location` starts/sec was
**255/s in the red run vs 243/s in a green one**, and green runs have drained 9,281 and 9,287
jobs to completion. Volume does not discriminate; interference does.

Two fixes, both in `e2e/` (see `run.sh`):

- **A run lock** (`.pids/run.lock`, atomic `mkdir`). A second `run.sh` now REFUSES to start with
  a message naming the incumbent pid, instead of silently killing it. Verified: refusal exits 2,
  leaves the incumbent's lock untouched, runs no teardown at all, and writes no stub artifacts
  directory. A lock whose holder is genuinely dead is reclaimed loudly. Liveness uses `ps -p`,
  not `kill -0` — `kill -0` returns EPERM for another user's process, which bash cannot
  distinguish from "no such process", so it would defeat the guard in exactly the case it exists
  for.
- **An `ABORTED` verdict.** An interrupted run no longer publishes its teardown cascade as a
  list of case failures. `summary.md` says the run produced *no result* and must be re-run.
  A gate that reports its own abort as product regressions is precisely how it loses trust.

Also fixed: a run that collected ZERO cases used to print the BLOCKED wording, blaming a
third-party outage for what is almost always the stack failing to boot. It now says so, and
names the two logs to read.

**Anthropic calls**: 17 `POST /v1/messages` calls to `api.anthropic.com` logged in the first
clean run; **14** in each of the two consecutive green runs above — across 6 live
discovery/re-discovery runs (Microsoft/AC-12, Atlassian/AC-04, Jane Street/AC-05, Spotify/AC-06
API, Atlassian/AC-11, Spotify/AC-06 UI), i.e. 2-3 selection calls per board, within PLAN.md's
"1-2 selection rounds" estimate.

**Exact token counts still cannot be measured from inside this suite**: `services/capture/**`
(the only code that calls the Anthropic SDK) is out of scope for this suite to edit, and it logs
no `usage` block. httpx's request-line logging is the only signal visible across that boundary.

**A hard cost CEILING is derivable without touching that file**, from the selector's own
truncation constants in `services/capture/request_selector.py`, and is worth having because it
bounds the blast radius of a runaway gate:

| Term | Value | Source |
|---|---|---|
| model | `claude-haiku-4-5` | `HAIKU_MODEL` |
| price | $1.00 / 1M in, $5.00 / 1M out | Anthropic list price |
| output cap | 1,024 tok → **≤ $0.0051 / call** | `MAX_TOKENS` |
| input cap | 6 candidates × (2 × 700 chars + 220 URL + 30 × 60 params) ≈ 25 KB ≈ ~7K tok → **≤ $0.007 / call** | `_MAX_CANDIDATES`, `_SAMPLE_RECORDS`, `_SAMPLE_RECORD_CHARS`, `_URL_PROMPT_CHARS`, `_MAX_PARAMS_SHOWN`, `_PARAM_VALUE_CHARS` |
| **per full run** | 14 calls × ≤ ~$0.012 → **≤ ~$0.17** | measured call count |

For the EXACT figure, two read-only routes exist that need no code change: the Anthropic Console
usage/cost page filtered to the run window, or the Admin API usage report
(`GET /v1/organizations/usage_report/messages`, which needs an admin key). Adding real
`usage`-block logging inside `services/capture/**` remains the right long-term fix and belongs
to whoever owns that file — flagged as a follow-up, not done here.

**CAPTURE_USE_BROWSERBASE**: asserted `false` at boot (`e2e_app.py`'s `_assert_browserbase_off`,
which also refuses to start if `BROWSERBASE_API_KEY` is set) — every live discovery run in every
attempt of this suite used local headless Chromium, $0 Browserbase spend.
