# Stage 2 — implementation decisions

The decision log for `PATH-TO-90-PERCENT.md` §6 "Stage 2". Every judgement that the plan
did not spell out, what it cost, and — where the plan turned out to be wrong — what the
measurement actually said.

Kept as a sibling doc rather than appended to `PATH-TO-90-PERCENT.md` for one boring
reason: Stage 1 was being written into that same file at the same time, in the same
worktree. `PATH-TO-90-PERCENT.md` carries a pointer to this one.

Everything below was measured on **2026-08-30**.

---

## 1. `transform.kind = "regex_capture"` — deriving a title from a URL slug

### The shape

```json
{"op": "transform", "field": "title", "kind": "regex_capture",
 "from": "url", "pattern": "/([^/?#]+)/\\d+/?$", "unslug": true}
```

| decision | why |
|---|---|
| **`from` names a canonical field, not a raw path** (`recipe_schema.CAPTURE_SOURCE_FIELDS`) | Shaping runs on MAPPED rows, after `map_records` flattened them. A raw-record path (`job.absolute_url`) would render empty on every row, forever, silently. Naming the closed set makes that a write-time refusal. |
| **A miss yields ABSENT, never the source value** | Both boards this exists for map `title` to the job's own URL — that is the only way the row survives `map_records`. "Leave it alone on a miss" would ship a URL as a job title on exactly the rows nobody checks: the Bloomberg defect, reintroduced. |
| **`unslug` title-cases ONLY a slug with no case of its own** | Bloomberg's `Senior-Data-Management-Professional` already spells its capitalisation; `.title()` would rewrite `iOS` and `ML`. Citadel's `commodities-portfolio-manager` has none to preserve. One rule, both boards. |
| **Percent-decode, and `-`/`_`/`+` all become spaces** | `+` is a space in a query-string slug. `unquote_plus` is deliberately **not** used: a literal `+` in a path segment is a plus sign, and one rule that reads both beats a decode that is right for one shape and silently wrong for the other. |
| **The pattern is DERIVED by code, never written by the model** | Same rule the oracle, the headers and the in-band error keys already follow. `request_selector.derive_title_from_url` picks from a two-entry family and **proves** it against the captured records — through `recipe_runner._regex_capture_value`, the very function the nightly replay uses, so it cannot be proven under one meaning and replayed under another. |
| **The proof bar is 100 % of the sample, not a majority** | See §1.2: an unmatched required field is now a FAILED run, so a nine-in-ten pattern takes the board down every night instead of mis-titling one row. |

### 1.1 The regex bound — what it actually buys, stated honestly

The pattern lands in `company_scripts.script` JSONB, which drifts and is re-validated on
every nightly read. Python's `re` has **no timeout and no step budget**, so a
catastrophically-backtracking pattern is a worker pinned for hours with no way to
interrupt it. Two candidate designs were considered:

* **no regex at all** — a fixed "last non-numeric path segment" primitive. Zero ReDoS
  surface, and it would have covered both measured boards. Rejected because the plan
  explicitly asks for a regex/split field spec and for a backtracking bound on *a
  pattern a model wrote* — i.e. the pattern is meant to be part of the recipe.
* **an arbitrary regex with a timeout** — impossible in CPython without a subprocess per
  row.

What shipped is a **checkable subset** (`recipe_schema.validate_capture_pattern`),
which is the same answer the op vocabulary already gives: admit a closed language,
reject everything else by name. Forbidden: a quantifier applied to a group, backrefs,
lookaround, any `(?…)` other than `(?:`, unbounded `{n,}`, `{n,m}` past 64, more than 3
quantifiers, more than 200 characters.

**This is a bound, not a proof of linearity, and pretending otherwise would be the
dishonest version.** Adjacent quantified atoms over overlapping classes
(`[^/]*[^/]*x`) still backtrack polynomially. With the subject capped at 512 chars
(`recipe_runner.CAPTURE_SUBJECT_MAX_CHARS`) the residual worst case is O(n³) ≈ 1.3e8
engine steps for a *deliberately adversarial* pattern, and linear for every realistic
one. What is closed is the **exponential** cliff — every classic catastrophic form
(`(a+)+`, `(a|a)*`, `(a*)*`) needs a quantifier over a group. Reaching the polynomial
residue requires the ability to write the recipe row, which is a bigger problem already.

**A harmless group quantifier is refused too** (`(?:detail/)?` cannot backtrack). The
rule is structural — "is there a quantifier after a `)`" — because a rule that has to
reason about whether *this particular* group is ambiguous is a rule that will one day
get it wrong. Nothing needs the shape.

### 1.2 The decision the plan did not ask for: what happens to a row the pattern misses

The plan says the field must "degrade to absent, never to a wrong value". Absent is
easy for an optional field. For `title` it is not, because `recipe_rows` does
`str(row["title"])` — `None` becomes the literal string `"None"` on the job card.

Three quiet options, all rejected:

| option | what it costs |
|---|---|
| leave the source value | a job list full of URLs — the defect this primitive fixes, on the rows nobody checks |
| drop the row | a SHORTER sweep that still reports `terminated_cleanly` with no cap → `self_consistent` VERIFIES it → the missing jobs get closed. Invariant #2, lost to a silent partial |
| write `None` | `"None"` as the title on every affected job |

So `recipe_runner._assert_shaping_kept_required_fields` **RAISES** when a shaping step
empties `id` or `title` on any row. That is a FAILED run: harvests nothing, closes
nothing, not a miss, retried by Procrastinate.

**Deliberate asymmetry with `map_records`, which drops.** `map_records` drops a record
the *board* published without a title — an ordinary thing for a board to do. A
`regex_capture` that stops matching is *us* discovering the recipe no longer describes
the board. Different fact, different answer.

The guard is scoped to recipes that actually shape `id`/`title`, so every existing board
— including every `parse_date` step already stored — pays one set comparison.

**Consequence worth knowing:** `len(rows)` is now invariant across shaping. It is either
all of them or an exception. That is what lets every completeness gate keep meaning what
it meant (see §4).

---

## 2. `fetch.body_encoding: "json" | "form"`

| decision | why |
|---|---|
| **Absent means `json`, and the JSON branch is byte-for-byte unchanged** | Every stored recipe keeps its exact current meaning. Discovery writes the key **only** when it is `form`, so the diff between two nightly recipes stays readable. |
| **Rejected on a GET** | A GET has no body to encode; the key can only be a mislabel, and silently ignoring it is how an author comes to believe a request is form-encoded when it is not. |
| **A form body must be FLAT scalars** | Not a simplification — it is the wire format. And the half that actually bites: `merge_body_params` sets the pagination cursor at whatever depth it finds the name, so a nested form body would page correctly *in the recipe* and not at all *on the wire*. Every page would be page one. |
| **Booleans rejected** | `True` urlencodes to the Python spelling `True`, which no board reads. |
| **`form` — and only `form` — overrides the captured `content-type`** | Form bytes under `application/json` is a 400 everywhere, and the recipe's own `body_encoding` is the authoritative statement about what is on the wire. The JSON branch is left alone so no stored board changes. |
| **`browser_fetch` gets it too** | It is the tier that needs it most — see §2.1. `build_subprocess_plan` forwards it; `_FETCH_JS` switches on it and sets the content-type in-page. |
| **Discovery reads the encoding off the captured `content-type` REQUEST header** | Never sniffed from the body: almost any string parses as a degenerate form (`"hello"` is one blank-valued field), so sniffing turns a body we cannot read into one we *misread*. |
| **A repeated form field name is a refusal** | A dict cannot round-trip it and the second value would be dropped silently. |

### 2.1 The plan is half wrong about Meta, and here are the numbers

The plan implies form encoding recovers Meta. Measured, same session, one key changed:

| how | result |
|---|---|
| plain `httpx`, form body, captured headers **and** cookies | **HTTP 400** |
| plain `httpx`, form body, no cookies | **HTTP 400** |
| plain `httpx`, JSON body, with cookies | **HTTP 400** |
| `run_browser_fetch` (our Chromium, on `metacareers.com/jobsearch/`), `body_encoding: "form"` | **200 — 876 rows in 5.4 s** |
| the same, default `json` | **HTTP 400** |

So Meta is a **`browser_fetch`** board, not an `http_json` one: form encoding removes
*our* blocker; it does not make the endpoint answer `httpx`. The browser half of this
gap is not a nice-to-have, it is the whole of it.

The board's own browser fetch returned **876**, not the plan's 877 — the plan's number
came from a payload that includes a featured job the array also carries.

### 2.2 The e2e AC-16 case is left alone, on purpose

`test_ac16_the_honest_end_state_is_named` says Meta refuses because `fetch.body` must be
an object "so no recipe can be synthesised". That reason is now stale in general — but
the case still passes **honestly**, because its fixture carries `request_headers={}`, so
the recorded request never declares its content-type and the JSON parse is still what
refuses. Rewriting it would have meant changing a fixture Stage 1 was editing in the same
file. The corrected picture is recorded in the new **AC-23**, which carries the live
content-type and shows the board synthesising.

---

## 3. `extract_embedded_island` with `source: "rsc_flight"`

| decision | why |
|---|---|
| **The whole parse runs on BYTES** | A flight row `T<hexlen>,<blob>` counts **UTF-8 bytes**, and the blobs are job descriptions full of typographic quotes. Framing on characters lands mid-blob, the parser loses sync with the row grammar, and the row holding the jobs is never seen: measured on Klarna, **0 job arrays char-framed vs all 81 byte-framed**. This is the single detail that decides whether the primitive works. |
| **`select`, not `select_one`** | The stream is split across ~174 `<script>` tags; one node parses to nothing. |
| **Text rows are FRAMED but not returned** | They are the `$<id>`-referenced description blobs — the element-tree half of RSC the plan says to skip. Their length still has to be honoured or every row after them is lost. |
| **Never raises; an unparseable stream yields `{}`** | One place decides a board is unreadable, and it is the caller's `records_path` dig — not a parser three frames down. |
| **Rejected on any transport but `http_html`** | `http_json` feeds its extraction a parsed JSON body and the browser child returns raw JSON bodies. On either, this source names a document that never arrives, and the 3am failure would name a selector instead of the real problem. |
| **Bounds: 4,000 chunks / 8 M chars / 2,000 rows** | Klarna is 174 / 473,102 / 32, so each is ~an order of magnitude of headroom. The response body is whatever the board served; these bound the parse, not the fetch. |
| **The element-tree walker is NOT built** | The plan says skip it, and Roblox — the only board that would need it — publishes a static CloudFront `jobs.json` that is a better source. A `records_path` into an element tree simply fails to resolve, which is a loud FAILED run and never a wrong answer. |

### 3.1 Discovery could not emit it, so `sources.rsc_candidate` was added

`island_candidates` reads islands the **capture child** found, and a child looking for
`<script type="application/json">` finds nothing on an App-Router page — there is no
island, there is a stream. So the class was invisible and the primitive would have been
dead on arrival, exactly like `http_html`/`extract_css` were for weeks.

`sources.rsc_candidate` parses the served document's stream with the **same**
`recipe_runner.parse_rsc_flight` the nightly replay uses (so a candidate that exists here
is one the runner can reproduce), scores its arrays with the existing
`_walk_record_arrays`, and offers the best one. It competes with the JSON islands on job
score rather than being appended after them, and it is gated on `"__next_f" in markup`,
so a page without a flight stream produces exactly the candidates it produced before.

---

## 4. The completeness verification the plan demanded — what was actually checked

Bloomberg is the cautionary case: an earlier agent proved that fixing its anchor
grouping alone would store **12 of 380** as a clean sweep and close 368 live jobs.
Re-measured live: `SearchJobs` page one publishes exactly **12** distinct `JobDetail`
anchors; the sitemap publishes **380**.

Three checks, in order of how much each proves (all in `e2e/.../test_stage2_primitives.py`,
class `TestAC22DoesNotWeakenCompleteness`):

1. **The board still produces no candidate at all.** Avature puts the requisition id in
   the *last* path segment, so `_anchor_rows` groups on `/careers/JobDetail/<slug>/` —
   twelve groups of one, all under `_MIN_HTML_RECORDS`. Stage 2 changed nothing here.
   *(Recorded so that a later change to the anchor grouping cannot quietly unstop it —
   and it is worth being blunt: if someone "fixes" that grouping without also giving the
   board a claim to be measured against, the 12-of-380 close is back. That hazard is
   pre-existing and Stage 2 neither creates nor removes it.)*
2. **The transform is structurally incapable of shortening a sweep.** `len(rows)` is
   invariant across shaping — all of them or an exception (§1.2). Completeness is judged
   on counts, so this is the property the gates actually depend on.
3. **A board where the derivation fires AND the read is a sliver is still refused.**
   Driven through the real `discover()`: a links-only feed returning Bloomberg's real 12
   page-one jobs and declaring its real 380. The derivation fires (asserted), and the
   coverage floor refuses at 12/380 = 3.2 % < `_COVERAGE_REFUSAL_RATIO` = 0.10, naming
   380 in the message. The control — the same bytes with the total set to 12 — stores,
   *with* the derived titles, which is what makes the refusal mean something.

Nothing in this stage touches `_reachable_records`, `_feed_reach`, `_Coverage`,
`MISSED_RUN_THRESHOLD` or `SAFETY_GUARD_RATIO`.

---

## 5. Where the plan turned out to be wrong

1. **"Fixes Bloomberg and Citadel outright" overstates it.** The primitive makes their
   recipes *expressible and replayable* — proved live at 380/380 and 56/56 — but **our
   own deterministic discovery still cannot author them**, because the recipes read the
   board's **sitemap**, and `sources.EvidenceSource` deliberately keeps the sitemap out
   of the record path ("what keeps the sitemap out of the record path without needing a
   rule about sitemaps"). Making the sitemap a records source is a separate,
   larger decision with its own transport story; it is not in Stage 2's three named gaps.
   What Stage 2 delivers for those two boards is the **vocabulary Stage 3's agent needs**
   — which is what §7 of the plan actually claims ("the thing standing between 81 % and
   89 % is a regex in a field spec").
2. **Meta: see §2.1.** Form encoding alone does not recover it on `http_json`; the
   browser tier is the one that reads it.
3. **A sitemap-sourced recipe needs a way to select only job URLs.** `extract_css` has
   no filter, and Bloomberg's sitemap carries 40 non-job pages beside the 380 jobs. The
   live proof uses soupsieve's `:-soup-contains("/careers/JobDetail/")`, which bs4 already
   supports and the runner already runs — but nothing in the plan noticed that a
   URL-list source needs it. Without it the run fails **loudly** (the 40 nav pages have
   no slug, so the shaping guard raises), which is the right failure but not a readable
   board.
4. **Klarna's board is not on `klarna.com`.** It is `jobs.deel.com/klarna`, and
   `jobs.deel.com/job-boards/klarna` **308s** to it — which the runner does not follow
   (correctly; the guarded client does not follow redirects). A recipe must carry the
   canonical URL.
5. **Klarna's row is `9.3.jobPostings`, and the plan's `row9.3.jobPostings` spelling is
   the same thing** — but only under byte framing. A character-framed parser finds no
   row 9 at all.

---

## 6. Things deliberately not done

* **No element-tree RSC walker** (plan says skip; Roblox has a better source).
* **No sitemap-as-records-source** (§5.1) — out of scope and a real decision, not an
  oversight.
* **`_anchor_rows` was NOT relaxed to keep text-less anchors.** It was tempting (it
  would create an in-pipeline "URLs but no titles" source) and it is exactly wrong for
  Bloomberg: its listing route is the 12-of-380 hazard, and making it readable is the
  failure mode §4 exists to prevent.
* **AC-16 not rewritten** (§2.2).
