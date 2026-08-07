# Session log — Custom Company Sources (E7)

A narrative record of the 2026-08-04/05 session that produced the spike and PR 1.
Read `HANDOFF.md` first; this file exists to answer *why* things are the way they
are, including what was tried and rejected.

Written from the working session itself, so it records reasoning and dead ends
that no commit message or plan document captures.

---

## Phase 0 — Research (parallel exploration)

The owner asked for a plan, not code, and specifically asked that subagents be
used to explore. Four things were read in parallel:

- **The ClickUp epic E7 + all four subtasks.** These were already detailed and
  largely still valid. They are cited throughout `PLAN.md`.
- **The JVN backend and frontend**, by two Explore agents.
- **The sibling repo `~/developer/personal/job-watcher`** — the owner's separate
  hourly job scraper, which already handles Meta and Amazon. Explicitly
  **reference only**: its logic was never ported into JVN.
- **Browserbase / Stagehand docs**, and a probe of the YC target.

### What mattered from the exploration

**Backend.** There is no provider registry: six parallel hardcoded module sets,
one per ATS (client service, fan-out task, fetch task, `tasks/__init__` import,
`_WORKER_QUEUES`, jobs_qa trigger, `SourceId`, and a frontend TS union). Adding a
seventh provider touches all eight places. But the seams exist: `companies.ats`
is plain TEXT, `provider_config` is JSONB, `ats='script'` is precedent for a
fan-out-exempt value, and `list_enabled_companies(conn, ats)` is generic. Both
the Procrastinate tasks and the standalone script scrapers converge on one shared
write path (`scripts/shared/database.py` + `incremental.py`), so anything reusing
it inherits the OPEN/CLOSED lifecycle and the `job_freshness` sidecar for free.

**Frontend.** The company list is compile-time static, with seven hard gates that
must become dynamic *additively*. A dedicated Plan agent designed the merge seam;
its key property is that `selectEffectiveCompanies` returns the static
`COMPANIES` array **by identity** when the user has no custom companies, so
anonymous and flag-off renders are provably unchanged. That identity-stability is
the regression guard — an accidental `[...COMPANIES]` there would cause app-wide
re-renders for every user.

**job-watcher.** Two things shaped the spike:
- Amazon is a plain public JSON endpoint with offset pagination.
- **Meta is only ever scraped by loading the page in Playwright and intercepting
  its own GraphQL responses** — job-watcher never forges the request. It also
  matches payloads by *shape* rather than operation name, because a rename once
  silently zeroed the adapter for 41 days.

That second point framed the entire spike: if Meta genuinely required a browser
every run, the feature's economics would be much worse. **It turned out to be
false** (see Phase 2).

---

## Phase 1 — Plan review, and four rounds of correction

The plan went to the owner as a lavish HTML artifact for annotation. Two rounds
of feedback materially changed the design.

**Round 1 — the approval queue was wrong.** The draft (following the tickets)
had an admin approval queue. The owner's correction:

> "no, we don't approve it to go into the main company pool. All we do is it gets
> added to that user's custom companies and is supplemented… I will manually take
> a look at what companies users are adding and I can move them into the main set
> if I wish."

This became **D1/D2**: no gate at all, plus an admin observability dashboard with
a promote action. `company_requests` became `company_add_attempts`, an audit log
that gates nothing.

**Round 2 — budget and a conceptual confusion.** The owner rejected the $25 spike
cap: free tiers only, decide about paying later. And asked a question that turned
out to be the most important one in the session:

> "I'm confused why does this not work? Browserbase is made to handle this,
> right? … Like we need AI to drive this?"

This exposed that the plan was conflating **a runtime browser** with **runtime
AI**. They are independent. AI runs once at discovery; a browser is just a
runtime tool, and this repo already runs deterministic Playwright hourly for
Google/Apple/Microsoft at zero marginal cost. A "Browser ≠ AI" section was added,
and the distinction is now called out in `HANDOFF.md` §2 as the thing most likely
to be misunderstood by whoever picks this up.

**A process note worth recording:** one review round was performed against a
*stale render* of the artifact — the owner's feedback referenced the approval row
that had already been removed. If you use lavish again, force a refresh between
rounds.

**Two infrastructure hiccups**, neither the owner's doing:
- The lavish page 500'd because another session ran `git worktree remove` on this
  worktree mid-review, deleting the artifact. The worktree was recreated and the
  artifact restored.
- An implementation agent later died on a transient API 529.

---

## Phase 2 — The spike (7.2)

Approved with "start the spike".

### Design

Two code paths that never meet: `capture.py` gathers evidence for an agent to
author a recipe; `replay.py` executes recipes with **no agent reachable** —
enforced by an import guard that fails if `anthropic`, `openai`, `stagehand`,
`browserbase`, or `langchain` is in `sys.modules`. Without that separation the
measurement would be worthless.

**Integrity choice: job-watcher's priors were deliberately withheld from the
discovery agents.** Each got only a URL and the harness. Amazon's endpoint and
Meta's behaviour were re-derived from scratch. This measures discovery, not recall.

Seven targets, six subagents in two waves (plus YC done by hand as the harness
smoke test).

### Results — all $0, everything local

| target | kind | jobs | vs source's own total |
|---|---|---:|---|
| meta | `http_json` | 801 | 801 exact |
| tiktok | `http_json` | 3799 | 3799 exact |
| janestreet | `http_json` | 225 | none published |
| spotify | `http_json` | 90 | 90 exact |
| amazon | `http_json` | 76 | 76 exact |
| ycombinator | `http_html` | 8 | 8 exact |
| tesla | **none** | — | 7,597 located, unreachable |

**Meta was the headline.** Its full catalogue comes from one POST that is
*forgeable from plain httpx*: the `lsd` token must be present but its value isn't
validated for logged-out traffic, and the real gate is Chrome-plausible headers.
A made-up token with zero cookies returns 200 and all 801 jobs. job-watcher's
browser is unnecessary. That single result is why the recommendation is **don't
build `browser_dom`**.

**Tesla failed, and the failure was more useful than most successes.** Akamai Bot
Manager, positively identified. The client matrix (all from one machine and IP)
showed httpx, curl, **and Playwright's bundled Chromium both headless and
headed** all get 403; only real Chrome, headed, with synthetic mouse movement got
through. So:
- `browser_dom` as we'd implement it would fail there anyway — this *strengthens*
  the don't-build recommendation rather than undermining it.
- The IP was never the discriminator, so a cloud browser wouldn't have helped —
  which is most of the reason the Browserbase arm is recommended skipped.
- Cookie transplant fails (Akamai binds the session to the TLS fingerprint), so
  "warm once, then replay cheaply" is dead for that class of site.

**The `tesla.cn` near-miss is the most instructive artifact in the repo.** It
serves plain httpx a clean 200 with the same JSON shape — 28 China-only jobs
sharing **zero ids** with the real 7,597-job board. A recipe built on it would
have replayed green forever, `OK 28 jobs`, while missing 99.6% of the company.
That is the 2026-03-29 false-closure shape reproduced exactly, caught only
because the agent cross-checked Tesla's own published count. **It is why
`total_path` exists in the frozen schema.**

### Harness bugs the targets forced out

Both were about *silent wrongness*, not crashes:

1. **GET pagination replaced the query string.** httpx `params=` overwrites the
   whole query, so paginating a filtered board dropped every filter and turned a
   76-job search into the 10,000-job global one — passing all checks while
   scraping the wrong thing. Now merged into the URL.
2. **`total_path` did not exist.** Three targets independently surfaced the gap.
   Added, with `check_completeness` raising on a shortfall.

`test_invariants.py` proves all ten safety claims offline (10/10). A transient
network blip during the very first replay incidentally demonstrated the core
contract working: the runner **raised** rather than returning an empty list.

---

## Phase 3 — Intel and Cisco

Mid-session the owner added:

> "You should also test your implementation with companies like Intel and Cisco."

Probing them immediately exposed two gaps the tickets missed:

- **`jobs.intel.com` 302s to `intel.wd1.myworkdayjobs.com`.** It is Workday — a
  board fully supported today — but only *after* a redirect. The 7.1 ticket
  specifies the resolver as pure and IO-free, so it would have told a user "not
  supported" for their own company's obvious careers URL. That is probably the
  most common real-world case. It forced the L1 redirect-following layer.
- **`jobs.cisco.com` → `careers.cisco.com`, which is Phenom People**, an ATS not
  supported at all. The planner then verified that Cisco's Phenom UI is only a
  front end: every apply link points at `cisco.wd5.myworkdayjobs.com`, and
  hitting Workday directly returns 1,060 jobs — the exact number Cisco's own UI
  reports. It forced the L2 embedded-board sniffing layer.

These two targets are much closer to what users will actually paste than the
spike's deliberately-hard set, and both being Workday underneath is the single
strongest argument for the ATS-first scope recommendation.

---

## Phase 4 — PR 1

The owner asked for a specific loop: plan agent → human review → implementation
agent → review agent → PR.

**Planning.** One agent produced the 1,440-line `PLAN.md`. It found four factual
errors in the briefing it was given, one of which would have broken production:
**there is no `/api/companies/:path(.*)` rewrite in `vercel.json`**, so
`POST /api/companies/resolve` would 404 in prod while working locally. It also
found `api/jobs.ts` doesn't forward `Authorization` (needed for PR 3), and three
internal contradictions in the tickets — including that 7.1's "byte-for-byte
`board_token`" assertion is *impossible* for Workday, since prod stores the
internal company id (`gm`, `slack`) rather than anything derivable from the URL.

**Implementation.** Completed all files, then died on an API 529 during final
verification. The work was intact on disk; verification was finished by hand.

**The 125-failure detour, and why it matters to you.** The suite showed 1,324
errors, then 125 failures. Neither was caused by PR 1:
- The shared dev DB was stamped `a3c32c2aa4d3`, a migration existing only on the
  owner's unmerged `fix/job-freshness-sidecar-unit23` branch, which this worktree
  cannot locate.
- Procrastinate's tables live in `public`, shared across per-test schemas.

Rather than argue this from inspection, PR 1 was **temporarily removed in full**
(files moved aside, modified files reverted) and the suite re-run: **the same 125
failed on a pristine tree.** Baseline 125/1043; with PR 1, 125/1265. That
experiment is the reason PR 1 could be cleared with confidence, and it is worth
repeating rather than trusting a hunch.

**Review.** A dedicated review agent attacked the SSRF guard and **found no
bypass** — decimal/octal/hex IP encodings, IPv4-mapped IPv6, IPv6 zone ids,
Cyrillic homoglyphs, NAT64, mixed public/private DNS answer sets, redirect chains
going private on hop 2. It did find two Critical issues on the same surface:

1. **The guard failed *open* into an HTTP 500** for trivially-typeable input, so
   the abuse case was precisely the one leaving no audit row. Two triggers:
   `urlsplit` on unbalanced brackets, and the stdlib `idna` *codec* waving through
   A-labels that httpx's `idna` *package* rejects. A remote host could 500 the
   endpoint at will via a `Location:` header.
2. **`max_bytes` was not a memory bound.** `aiter_bytes()` decodes each raw chunk
   before the loop sees it, so 500 MiB of zeros (509 KB compressed) produced a
   **single 67 MB allocation** against a 512 KB cap — four times per request, on
   the container with a prior OOM incident.

Plus four Important: blocking `getaddrinfo` stalling the shared event loop (and
therefore every ATS scrape task, since the worker runs in-process); no aggregate
deadline making `/resolve` a 36× request amplifier; Greenhouse
`/embed/job_board?for=acme` resolving to the literal token `"embed"` and silently
defeating the sniffer; and the sniffer missing locale-prefixed Workday links that
its own resolver tests assert are real.

**Fix.** All fixed with tests proven failing-beforehand (reverting the sources
produced 53 failures). Notably the fix agent **corrected two of the reviewer's own
claims with evidence**: the redirect-500 fires inside `http.stream()` rather than
`URL.join()` (httpx touches `URL.host` on any 3xx even with redirects disabled),
and `ip.is_global` does *not* cover 6to4 on Python 3.13 — so CGNAT and
`192.88.99.0/24` were both pinned explicitly rather than trusting the suggested
one-liner.

That mutual correction is the argument for keeping the adversarial multi-agent
structure instead of collapsing it into a single agent.

**Final state:** 222 tests on PR 1's files, suite 1043 → 1265 passing, failures
unchanged at 125, mypy clean, single Alembic head, live Intel 681 / Cisco 1071.

---

## Things deliberately not done

- **Replay rounds 2 and 3** (the 48-hour durability window). `CronCreate` was
  considered and rejected: its jobs are session-only and only fire while the REPL
  is idle, so they would have silently never run. A launchd agent was not
  installed without asking. Left as a documented one-line command.
- **The Browserbase arm.** Prepped, never run — no credentials, and its value
  collapsed once six targets needed no browser and Tesla showed the IP was never
  the discriminator.
- **Committing harvested cookies.** Tesla's probes left 32 MB of Chrome profile
  data and four cookie dumps on disk; they were gitignored and deleted, not
  committed. A secret scan of the committed tree found only cookie *names* in
  prose.
- **Porting anything from job-watcher.** Reference only, as instructed.
