# Birth defects: making discovery ask reality before it stores a guess

**The root cause.** A synthesized recipe is stored on the strength of a guess. The model
answers, the answer passes a *schema* check, and nothing asks reality whether it was
right. Replay-time health checks cannot catch any of it — the baseline comes from the
first run and the first run is the wrong one. These are **birth defects, not drift**.

**The stopping rule this work is scoped by.** A probe earns its place if and only if its
failure mode can *silently pass the harvest gate*. Job-link and field-quality defects are
invisible to every gate → probe them. Pagination is already caught at replay by check 13a
→ discovery needs only the cheap request-shape check, not a mutate-and-diff probe.

**The failure taxonomy, applied everywhere.**
**Repair** (the probe found what the model missed) → **Degrade** (an optional field is
unverifiable: drop the field, keep the board) → **Refuse** (a required field fails, or
the board provably has more jobs than we can reach). An *inconclusive* probe degrades,
never refuses. A board we can read must not be thrown away to protect a footnote.

---

## 0. What was re-measured before any code was written

The review this work was scoped from named five failures. Every one was re-checked
against the live boards and against the recipes actually stored in `jobscraper_pr243` on
2026-08-30. Three of its claims did not survive.

| claim | measured | verdict |
|---|---|---|
| Jane Street's real link shape is in **the listing page's anchors** | `open-roles/` raw HTML: **0** job anchors. Rendered DOM after the full 24 s capture window: **0** job anchors, **0** occurrences of any job id, `document.body.innerText` = 2,842 chars of nav + marketing. The pasted page is a **chooser** ("Experienced Candidates" / "Students and New Grads"); it fetches all 233 roles as `jobs/main.json` and renders **none** of them. | **false** |
| Atlassian's `location` is `locations[0].city` → 100 % NULL | stored recipe maps `location: "locations"`; 213 of 234 rows carry a location, 97 distinct | **stale** |
| Atlassian's `description` is `overview` → identical on every job | stored recipe maps `description: "responsibilities"`; 197 of 233 payload records distinct. (Even `overview` is 159/233 distinct today.) | **stale** |
| Jane Street's job URL 404s | stored url is `…/open-roles/#{id}` — the honest `_board_page_link` fallback, already the *current* behaviour, not a 404 | **superseded** |
| Walmart: "there is no pagination", 10 jobs of 48,800 | `page_shape_refusal` exists, is pure, and is never called by discovery | **true** |

Two further measurements decided the design:

* **The host-pin body does not serve.** `route.fetch(max_redirects=0)` in
  `_capture_main._install_host_pin` returns the **server** document. Atlassian's raw
  document contains `careers/details/` **0 times**; its rendered DOM contains 233 job
  anchors. Any anchor harvest that reads the host-pin body reads the wrong bytes on
  exactly the client-rendered boards this feature exists for. → harvest from
  `page.content()`, once, after the observation window has already closed.
* **Haiku will not guess a path.** Given the Jane Street candidate plus the probe's
  evidence (`https://www.janestreet.com/jobs/{id}` → HTTP 404 on two real jobs) and the
  board's own same-host link corpus, `claude-haiku-4-5` returned `field_map.url: ""`
  on **3 of 3** trials. It correctly declines to invent a path. A link-only re-ask
  therefore buys nothing measurable — and costs a board, because an empty required
  field is a `RequestSelectionError` that burns the round. See §4.

---

## 1. Job-URL template derivation — the ceiling-raiser

`_prove_job_link` is **verification-only**: it can prove a link wrong but cannot find the
right one, so it degrades to `_board_page_link` (a `listing-page#{id}` fragment — safe,
honest, not a job link). `repair_url_template` cannot close the gap either: its condition
3 requires the current id to appear in **zero** captured board links, and Jane Street's
`{id}` is the *right id in the wrong path*, so it no-ops by construction. This is a new
derivation, not an extension of that one.

### 1a. What the capture now brings back

`_capture_main` calls `page.content()` **once**, after `_settle` has returned, and
extracts two small lists with a regex. The child stays dumb — it decides nothing, it
records — and the pipe stays small (hrefs, not a 4 MB document).

* `board_links` — every `href` in the rendered DOM, deduped, capped.
* `board_scripts` — every `<script src>` URL, deduped, capped. The child does **not**
  filter by host: only the parent knows the board's host and owns the SSRF guard, so
  the child supplies the list and the parent decides what it may read.

### 1b. Two derivations, both *proved* before use

**A — anchors ↔ ids (deterministic, no network).** For each same-host href and each
opaque-id-token field path in the records, if the rendered id equals a whole path
*segment* (or its pre-dot stem), generalize that href by replacing the segment with
`{field}`. Require several records to agree on the same generalized template. This is the
derivation the review asked for, and it fixes every board that links its own jobs —
Atlassian's `/company/careers/details/{id}` falls straight out of it.

**B — the board's own link template (one bounded fetch pass).** Jane Street renders no
job anchors anywhere, so A finds nothing. But its listing page loads
`/assets/pg/open_positions-*.js`, which contains, literally:

```js
`<a href="/join-jane-street/position/${t.id}/">`
```

So B fetches up to `_MAX_SCRIPT_FETCHES` same-host scripts **through the same
SSRF-guarded `ProbeFn` seam `_prove_job_link` already uses**, greps for `href="…"`
literals carrying exactly one `${…}` placeholder, and substitutes our id fields into the
path. Measured on Jane Street: 2 same-host scripts, 394 KB, 28 ms of body reads, and it
yields exactly three templates —
`/search/?query={}`, `/join-jane-street/closed-internship/{}-${a}-${s}/` (two
placeholders → rejected) and `/join-jane-street/position/{}/`.

B runs **only** when the spec is synthesised *and* A found nothing *and* the board
publishes no link field — i.e. the ~1 board in 6 that has nothing else to offer. It is
memoized for the whole discovery so a second selection round cannot re-fetch.

**Neither derivation is trusted.** Both feed `_resolve_job_link`'s rung 3 as additional
candidates and every one is put through the existing `_prove_job_link` (two real jobs,
compare the rendered pages) before it can be stored. Measured against the live board:

| candidate | `_prove_job_link` |
|---|---|
| `https://www.janestreet.com/join-jane-street/position/{id}/` | **PROVED** |
| `https://www.janestreet.com/search/?query={id}` | refused — "two different jobs served the same page (2255 vs 2255 chars)" |
| `https://www.janestreet.com/jobs/{id}` (the model's) | refused — "HTTP 404" |

The wrong derivations are rejected by the same gate that rejects the model's. That is the
whole safety story: derivation only ever *proposes*.

**Budget.** Ranked best-first, at most `_MAX_PROVE_ATTEMPTS` specs proved per round (2
fetches each) plus at most `_MAX_SCRIPT_FETCHES` script bodies once per discovery, and the
whole of `_resolve_job_link` runs under a wall-clock deadline so no arrangement of
timeouts can eat the task's 240 s.

**Explicitly out of scope:** the `http_html` transport. We capture HTML to derive a *link
template*, nothing more. Discovery still emits `http_json` / `browser_fetch` only.

---

## 2. Field-quality probe

`_prune_non_scalar_optionals` only drops a field that renders a **container**. Two
failures walk past it, and both are invisible to every replay-time gate:

1. **renders nothing at all.** A path that resolves to `None`/`""` on every sampled record
   has `useful == []`, so the `if useful and …` guard is vacuously false and the mapping is
   *kept*. That is a column of NULLs, forever, reported as a healthy board.
2. **renders the same thing on every job.** `_is_per_job_link_field` already knows this
   idea and applies it only to `url` (a logo renders a perfectly good absolute URL on
   every row). A **description** identical across every sampled record is company
   boilerplate: it identifies nothing and it is not per-job data.

Renamed to `_prune_unusable_optionals`; the sample widens from 5 to 20 records, which is
the *safe* direction for both new rules (more evidence makes "empty on all" and
"identical on all" harder to reach, not easier).

**Which fields the distinctness rule applies to, and why not the others.** This is the
part that has to be got right, because the rule deletes data:

| field | distinctness rule? | why |
|---|---|---|
| `description` | **yes** | prose that is byte-identical on 20 different jobs describes the *employer*, not the role. Atlassian's `overview` is the named case. |
| `location` | **no** | a single-office company legitimately has one location on every job. Dropping it would delete correct data from every such board. |
| `posted_at` | **no** | a board that published its whole catalogue on one day, or that publishes a batch date, is real. |
| `company_name` | **no** (and it is not in the canonical map) | it is *supposed* to be identical — that is the point of the field. |
| `url` | already covered | `_is_per_job_link_field`, unchanged. |
| `id`, `title` | n/a — **required** | an unusable required field RAISES in `_validate_field_map` / `_validate_url_field` and the board is REFUSED, per the taxonomy. |

Dropping an optional is a **degrade**: the board keeps being tracked. Every drop is
recorded on `RequestSelection.field_notes` so a retry (§4) can tell the model what it got
wrong — but a drop on its own never *causes* a retry, so it costs no tokens.

---

## 3. `page_shape_refusal` at synthesis — the cheap Walmart catch

`harvest_verification.page_shape_refusal` already detects "a page index is in the request
and there is no paginate step" (13a) and "an explicit page size, and the harvest came back
exactly that big" (13b). It is pure. **Discovery never calls it.** So Walmart's 10-of-48,800
recipe passes synthesis, passes acceptance (the replay reads the same 10 rows the browser
saw), and is stored.

`synthesize_recipe` now calls it on the assembled script and REFUSES — with one exception,
which is the difference between a rule and a nuisance: **the board's own declared total
overrides the request shape.** When `one_page_proven` holds (the board says N total and
handed us N), a `page=1` in the request means "page one is the whole board", and refusing
would throw away boards we read correctly today. Evidence beats shape.

---

## 4. Closing the retry gap

`_MAX_SELECTION_ROUNDS = 2` fires on acceptance failure as well as schema failure, but
the loop **drops the failed candidate and `break`s when none is left** — so a *single-feed*
board (Jane Street, Atlassian) gets no round two at all. That is exactly the case that
needs one. `select_request` also had no way to say *why* the last answer was rejected, so
round two on a multi-feed board was a blind re-roll.

* `select_request(candidates, *, feedback=...)` and `build_message_params(candidates,
  feedback=...)` append the evidence to the user turn.
* A failed candidate is dropped **only when another candidate remains**. A sole candidate
  is re-asked with the evidence attached.
* Feedback carries: the refusal that ended the round, the dropped-field notes from §2, and
  the job-link probe's verdict when one was reached.
* Total Haiku calls per discovery stay bounded by `_MAX_SELECTION_ROUNDS`. No new call
  sites.

**What this deliberately does NOT do: retry on an unprovable job link.** A link that
cannot be proved is already a *degrade* — the board is accepted with
`_board_page_link`. Re-asking there would have to be able to *lose* that fallback to be
worth anything, and it measurably buys nothing (§0: Haiku answered `url: ""` on 3/3
trials, which is a `RequestSelectionError` that burns the round and refuses a board we
can otherwise read perfectly). Degrade-never-refuse wins.

---

## 5. The `http_html` landmine

`validate_recipe` has a guard block for `browser_fetch` and none for `http_html`. An
`http_html` recipe carrying a `paginate_page` step would validate; `_run_http_html`
ignores pagination entirely and hardcodes `terminated_cleanly=True, pages_fetched=1`; the
verdict path would then read a page-one-only sweep as a clean one and mark it VERIFIED →
**closing every job past page one**. Discovery emits no `http_html` today, so it is not
live. The schema rule (reject `http_html` + any pagination step) is added anyway, with a
test, so nobody trips it later.

---

## 6. Making e2e able to see any of this

AC-04 (Atlassian) and AC-05 (Jane Street) already run **live** on every suite run and
assert the verdict, the oracle, the transport, `openJobCount > 0`, `posted_on` and
`first_seen_at` — **never a URL, a location, or a description.** Jane Street's dead link
shipped green through 48 passing cases.

Added to `_run_discovery_case`:

* **the job link is a job link** — every stored URL absolute and `https`, distinct per job,
  and never the `#{id}` listing-page fallback;
* **and it resolves** — two real job URLs fetched live, both `< 400`, and the two pages
  materially different (the same question `_prove_job_link` asks, asked from outside);
* **locations are populated** — at least 80 % of rows non-NULL (Atlassian's own board
  leaves ~9 % of postings without one);
* **descriptions are per-job** — more than one distinct `details->>'description'`.

---

## 7. Measured after the change — two live re-discoveries

Both boards re-discovered end to end from this branch: real Chromium capture, real
Haiku, real replay through `guarded_sync_client`, real job pages fetched afterwards.

### Jane Street — `https://www.janestreet.com/join-jane-street/open-roles/`

| | before | after |
|---|---|---|
| `field_map.url` | `https://www.janestreet.com/join-jane-street/open-roles/#{id}` | `https://www.janestreet.com/join-jane-street/position/{id}/` |
| a real job link | `…/open-roles/#4273643002` — the listing page, for all 233 jobs | `…/position/8631912002/` → **HTTP 200, 46,201 b, its own title on the page** |
| rows | 233 | 233 |
| location | `city`, 233/233, 4 distinct | unchanged (4 offices is *correct*, not a defect) |
| description | `overview`, 233/233 | unchanged, **227 distinct** |

The log, in order — this is the whole mechanism in four lines:

```
discovery selection rejected: records_path '.' does not resolve in the captured response
read 2 of the board's own script(s) for a link template; found 2
derived 2 job-url template(s) from the board's own code,
    best 'https://www.janestreet.com/join-jane-street/position/{id}/'
job link 'https://www.janestreet.com/join-jane-street/position/{id}/' proved against the live board
```

Note the FIRST line. Round one's answer was unusable, and Jane Street publishes exactly
one jobs feed — so round two is precisely the round §4 exists to buy, and it ran with the
rejection quoted back to the model.

Which source found it: **the board's own JS bundle, not its anchors.** The rendered DOM
carries 39 hrefs and none of them is a job. The anchor derivation was tried first,
returned nothing, and the code derivation was consulted for exactly that reason.

### Atlassian — `https://www.atlassian.com/company/careers/all-jobs`

| | measured after |
|---|---|
| `field_map.url` | `portalJobPost.portalUrl` — the board's OWN link, never fetched, never second-guessed |
| a real job link | `https://globalcareers-atlassian.icims.com/jobs/25583/…/job` → HTTP 200 |
| distinct URLs | 218 / 218 |
| location | `locations` → **199 / 218 populated, 95 distinct** |
| description | `responsibilities` → **217 / 218 populated, 196 distinct** |

Atlassian was **already healthy** on this branch's predecessor (§0) and is unchanged by
this work — which is the point of measuring it: the new field-quality rules must not
take anything away from a board that was right.

### One live measurement that changed the e2e design

Atlassian's three iCIMS job pages weigh **478,872 / 478,860 / 478,906 chars** and none
carries its own title — the posting renders inside an iframe. That is byte-for-byte the
shape of a dead SPA shell. So the e2e "two different jobs, two different pages" check is
asked **only of a URL we composed** (a spec containing a placeholder), never of one the
board published — the same split `_resolve_job_link` already makes, and without it this
suite would fail the healthiest board it tracks.
