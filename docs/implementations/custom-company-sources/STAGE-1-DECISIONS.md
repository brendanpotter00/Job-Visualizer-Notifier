# Stage 1 — implementation decisions

The prover fix from [PATH-TO-90-PERCENT.md](PATH-TO-90-PERCENT.md) §6, as built.
Every judgement below is one the plan did not spell out, plus the places the plan
turned out to be wrong when it met the live boards. **All numbers here were measured
on 2026-08-30 with plain `httpx` against the real boards**, not carried over from the
plan.

---

## The verdict, first

| board | before | after |
|---|---|---|
| JPMorgan | reject — "same page, 30 vs 30 chars" | **PROVED** (og:title) |
| Micron | reject — "same page, 0 vs 0 chars" | **PROVED** (og:title) |
| careers.oracle.com | reject — "same page, 6 vs 6 chars" | **PROVED** (og:title) |
| Meta | reject — "HTTP 400" | **PROVED** (UA retry, then og:title) |
| SpaceX | reject — "HTTP 0" | **PROVED** (cross-host 301 followed) |
| Databricks | reject — "HTTP 0" | **PROVED** (cross-host 301 followed) |
| IBM | reject — "same page, 0 vs 0 chars" | **UNPROVEN** — 202/empty from a WAF |
| Atlassian | reject — "same page, 18,086 vs 18,086" | reject (unchanged) |
| Kakao | reject — "same page, 60 vs 60" | reject (unchanged) |
| YC/Raindrop | **already PROVED** on the pair sampled today | PROVED |
| **Nintendo** | reject — "same page, 842 vs 842" | **reject** ✅ |
| **Walmart** | reject — "same page, 1,606 vs 1,606" | **reject** ✅ |

Six flipped to proved, one to unproven, two unchanged, and both load-bearing
rejections held.

---

## 1. Cross-host redirects — an SSRF decision, and exactly what was dropped

`guarded_sync_client(allow_cross_host=True)` is a new **opt-in** keyword.
It drops **one check and only one**: the same-host pin between redirect hops.

Still enforced on every hop, unchanged:

- `url_guard.validate_public_url` runs **before the socket opens** — https-only, no
  userinfo, standard port, real DNS, and a public answer (RFC1918, loopback,
  link-local `169.254/16` incl. metadata, ULA, CGNAT, 6to4, NAT64, IPv4-mapped all
  refused);
- the request is **IP-pinned** to the address that validation resolved, with the
  hostname preserved for `Host` and TLS SNI/cert verification;
- `verify=True`, and the 5-hop ceiling.

**Nothing was disabled to make a board pass.** The default is `False`, so the nightly
replay is byte-identical to before, and `test_only_the_discovery_link_probe_opts_into_cross_host`
greps the whole `api/` tree and fails if a second caller ever opts in.

Why it is defensible here specifically: the probe fetches one page twice and compares
them. It has no scrape to relay and stores no bytes. The host-pin's stated purpose —
"a vanity board must not silently relay a nightly scrape to another host" — has no
analogue on this path. What it *did* do was report `boards.greenhouse.io →
job-boards.greenhouse.io` and `databricks.com → www.databricks.com` as `HTTP 0`.

New tests: cross-host followed; **cross-host to `169.254.169.254` still refused and
never issued**; the second hop is IP-pinned like the first; the hop cap still fires.

## 2. User-Agent — the plan's instruction would have cost a board

The plan says *"do not send a browser User-Agent from the probe"*. Implemented as
written, that trades one board for another. Measured over 22 live job pages, four UA
variants each:

| UA | Meta | Goldman | Jane Street | Roblox |
|---|---|---|---|---|
| Chrome (today's) | **400** | 200 | 200/404 | 200 |
| no `User-Agent` header | 200 | **403** | **403** | 200 |
| httpx default | 200 | 200 | 200 | **read timeout** |
| an honest bot UA | 200 | 200 | 200 | **read timeout** |

`careers.roblox.com` tarpits *any* non-browser UA — reproduced three times each, with
4 s between attempts.

**Decision: keep the browser UA first and retry ONCE under
`onesecondswe-link-check/1.0 (+https://onesecondswe.dev)` when the board answers with a
status that is about our client** (`400/401/403/405/406/409/415/429`). Meta gets its
retry; Roblox, Goldman and Jane Street never reach it. An honest self-identifying UA
was chosen over httpx's default because they scored identically and this one lets a
board operator see who we are.

**The wall clock is unchanged.** A timeout is never retried and a 404/410 is never
retried, so the pathological all-timeout case is still 8 × 10 s, not 16 × 10 s. A
refusal answers in milliseconds.

## 3. Unproven vs wrong — and the narrow line between them

Three states now, not two: `LinkProof(proved, blocked, why)`.

| the board's answer | verdict |
|---|---|
| 404 / 410 | **wrong** — it answered the question we asked |
| two pages that compare equal | **wrong** |
| 4xx-about-our-client, 5xx, status 0 | **blocked** |
| 2xx with an **empty body** | **blocked** (IBM: `202`, zero bytes, four UAs) |

**Blocked is an empty body, not "empty after stripping", and this is the load-bearing
choice.** A `<script>`-only SPA shell is thousands of bytes of real answer, and
Goldman's dead `{roleId}` differs from a working link by **23** of them. Widening
blocked to mean "we could read nothing out of it" would move Goldman from *disproved*
to *unproven* — and the ladder keeps an unproven candidate — so the 404 this whole rule
exists to stop would ship again. Pinned by
`test_an_spa_shell_is_a_real_answer_and_stays_a_hard_no`.

### What the ladder does with "blocked"

It keeps the candidate **only if the BOARD's own evidence produced it** (a template
derived from its rendered anchors, its own scripts, or `repair_url_template`'s swap).
The model's bare guess still degrades to `listing-page#{id}`.

The split is the same one JOB-LINK-RULE already draws, one notch further along: *"a
path the board's own HTML shows it uses, and the board won't let us check"* ships;
*"a path a model made up, and we can't check"* does not. Jane Street's `/jobs/{id}` is
the second case with a board that answers — and it 404s, which is a hard no anyway.

> **Bug found by writing the test.** `repair_url_template` returns the selection
> *unchanged* when it has nothing to swap, so on most boards `repaired == spec`.
> Adding `repaired` to the evidenced set unconditionally let the model's guess back in
> through the evidence door, and the first version of the code did exactly that. Now
> compared, not just added — `test_ac21b_a_waf_does_not_promote_the_models_bare_guess`.

## 4. `<title>` / `og:title` — what the plan got right, and the three boards it got wrong

`_declared_title(body)` reads `og:title` / `twitter:title` first, then `<title>`.
**og first** because a board leaves `<title>` generic far more often: JPMorgan's is
*"JPMC Candidate Experience page"* on every job and Oracle's is *"Oracle"*, while both
carry the real title in `og:title`. `<title>` still earns its place — Micron's is
empty, and it is all YC/Raindrop has.

The signal is invisible to `_page_text` **structurally**, not incidentally: an
`og:title` lives in an *attribute*, and `_TAG_RE.sub(" ", …)` deletes attributes with
their tags. That is why five correct boards read as "same page".

Two pages that **declare different titles** prove the link. **Equal declared titles are
never a veto** — SpaceX serves `og:title = "Accountant, Revenue"` on three genuinely
different Greenhouse job pages (one's `<title>` is the literal string `page_title`), and
Oracle can have two open reqs with one title. Equal means *no evidence*, and the length
comparison still decides.

### The plan is wrong on three of the five boards it names

> *"that alone flips JPMorgan, IBM, Micron, Oracle and Kakao"*

Measured:

- **JPMorgan, Micron, Oracle** — correct, flipped by exactly this.
- **IBM** — the title rule does nothing. IBM's WAF sends **zero bytes**; there is no
  title because there is no document. It is fixed by change 3, not change 4.
- **Kakao** — **not flipped, and it should not be.** `careers.kakao.com/jobs/<id>`
  serves 53 chars and `<title>카카오 영입` ("Kakao recruitment") on every job. That is
  byte-for-byte the same shape as Goldman's dead `{roleId}` (23 chars,
  *"Careers | Goldman Sachs"*) and Nintendo's embed (842 chars, *"Careers at Nintendo -
  Join Our Team"*). There is no rule that keeps Kakao without resurrecting Goldman's
  404. Kakao stays refused, and that is the honest floor of a prover that does not
  render.
- **Atlassian** is also listed in the plan's failure table and also does not move: its
  iCIMS page renders the job in an iframe and declares **no title at all**. It never
  reaches the prover in the shipped ladder anyway — its link is *published*, rung 1.

### The one thing this makes riskier, stated plainly

A wrong template whose substituted field routes to *some* per-value page — Spotify's
`…/job-categories/{main_category.slug}` in `ID-IN-HREF-POC.md` — now has a second way
to pass, because two category pages declare two different titles. That template was
previously rejected by luck (3,845 vs 3,917 chars, under the 2% bar), and the POC says
so: *"That is luck, not a guard: category pages of very different sizes would have
passed."* The prover was never the guard for that class; `ID-IN-HREF-POC` recommendation
#3 (require **coverage** before storing a derived template — Toss ships on 1 vote in 20)
is, and it is out of Stage 1's scope. Recorded here rather than fixed here.

## 5. The 200-char / 2% floor — changed to 120, and here is the arithmetic

YC/Raindrop failed at 7,088 vs 6,936: a **152**-char difference against a 2% bar of
**141**. The fraction said "different" and the flat 200 overruled it — on a 7 KB page
the absolute bound is the *stricter* of the two, which is the opposite of the job the
code comment gives it.

`_MIN_PAGE_DELTA_CHARS: 200 → 120`, fraction unchanged at 2%. The corpus places it:

| | smallest delta |
|---|---|
| every **wrong** template measured (Goldman 23/23, Walmart 1,606/1,606, Kakao 53/53, Nintendo 842/842, Atlassian 18,076/18,076, JPMorgan 30/30, Micron 0/0) | **0** |
| smallest **correct** link measured (Roblox) | **50** (0.8%) |

Any threshold in (0, 50) separates the corpus perfectly; 120 keeps a wide margin over
both, and over the per-request nonce/CSRF/timestamp noise the bound exists for.

**Honest caveat:** this change bought nothing on the live re-run. The YC job pair
available today differs by 1,826 chars, so the old floor proved it too. The fix is
justified against the plan's own recorded numbers (asserted directly in
`test_the_absolute_delta_floor_no_longer_overrules_the_fraction`), not by a board that
needed it on the day.

## 6. TRAP 1 — the plan's fifth bullet, skipped

> *"Honour `JOB-LINK-RULE` branch 1 in the probe path: never fetch a link the board
> itself published."*

**Not implemented, deliberately, and no narrow version was found worth arguing for.**

The probe path already honours branch 1: `_resolve_job_link` returns at rung 1 for a
published spec and fetches nothing. What the bullet would actually change is the guard
commit `34a1b5d` added — the one that decides whether a spec *counts* as published.
Nintendo's Greenhouse embed publishes `https://careers.nintendo.com/?gh_jid=<id>`:
distinct per job, link-shaped, HTTP 200, and it serves **the listing page** to every
one of them (842 identical chars, `og:title` = *"Careers at Nintendo - Join Our Team"*,
re-measured 2026-08-30). Blind trust in published links puts that back, plus every
Greenhouse-embed board shaped like it.

The one thing that *did* change on the published side is a consequence, not a decision:
`roblox.json` moves from `proves: false` to `proves: true`, because the new prover
agrees with reality about a link that was always correct. Its fixture's own docstring
predicted it. **Atlassian does not move** and is now the whole of the argument for
"branch 1 fetches nothing" — no title, no length difference, indistinguishable over
plain HTTP from Goldman's dead shell, and the board the brief names as
must-not-regress.

## 7. Smaller calls

- **`_prove_job_link` returns a `LinkProof` dataclass**, not `str | None`. Three
  outcomes cannot ride on one optional string. Call sites updated:
  `_resolve_job_link`, `test_recipe_corpus_regression.py`, and the one-off
  `scripts/one_off/e7_recipe_verifier/verify_recipe.py`.
- **The corpus fixtures gained `og_title` and `title_tag` per page**, measured
  2026-08-30 (`titles_measured_at`) beside the 2026-08-29 status/length measurement.
  `_measured_probe` emits them into the reconstructed `<head>`, so the corpus exercises
  the new rule with real strings — Goldman's identical *"Careers | Goldman Sachs"*,
  Walmart's nothing, SpaceX's identical-but-correct. `status`/`chars`/`carries_*` were
  not touched.
- **The retry keeps one client, not two.** httpx merges request headers over client
  headers, so the retry is a second request on the same connection pool.
- **No change to `_link_samples`.** Sampling two records with distinct URLs is
  orthogonal to everything above, and `ID-IN-HREF-POC`'s coverage recommendation
  belongs with the derivation, not the proof.
- **Invariants untouched**: `MISSED_RUN_THRESHOLD = 2`, `SAFETY_GUARD_RATIO = 0.1`,
  RAISES-never-empty, the AST-enforced agent-free replay boundary (nothing new is
  imported into the replay closure — `guarded_client` gained a keyword, not an import),
  single Alembic head (no migration), and every composed URL still goes through
  `guarded_sync_client`.
