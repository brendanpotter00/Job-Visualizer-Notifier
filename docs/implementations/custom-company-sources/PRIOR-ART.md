# Prior Art — has anyone already solved this?

> **Scope.** The generalised architecture, not the job-board framing: *a user supplies a URL;
> something expensive runs **once** to work out how the site serves its data; it emits a durable
> deterministic artifact; that artifact replays **cheaply, repeatedly, with no model in the loop**;
> when it breaks, something re-derives it.* Researched 2026-08-30. Every claim below carries a URL.
> Where a product's behaviour could not be established from docs, it says **COULD NOT DETERMINE** —
> that distinction is the point of the exercise and a guess would make this document worse than useless.

---

## 1. The verdict

**Half of it is solved, and the half that is solved is solved better than we think.**
The one-time-model / modelless-replay split is *shipping product*, not a novel idea:
**Oxylabs' Custom Parser + OxyCopilot** is the cleanest commercial instance and
**Crawl4AI's `generate_schema`** the cleanest open-source one — both emit a closed-vocabulary
selector config, both replay free, neither needs a browser. **Kadoa** is the closest full-system
analogue (generate once → detect drift → regenerate → validate). **Nobody found has solved
completeness.** Across every product, paper and engineering write-up read here, not one describes a
mechanism for proving a read was *not truncated* before acting on the absence of a record. The
industry has a name for the failure — "silent truncation" — a prescription ("alert on volume drop")
and no oracle. That is where our work is actually novel, and it is the only part worth defending.

---

## 2. Comparison table

`model cost` = when inference actually runs. `artifact` = what persists between runs.

| Product / project | Model cost | Artifact | Browser at replay? | Published hit rate | Price (unit) |
|---|---|---|---|---|---|
| **Oxylabs Custom Parser + OxyCopilot** | **one-time** — preset reused with no AI re-invoked ([docs](https://developers.oxylabs.io/scraping-solutions/web-scraper-api/features/custom-parser/getting-started)) | **config** — closed-vocabulary JSON (`xpath`, `css`, `element_text`, `_items`) ([repo](https://github.com/oxylabs/custom-parser-instructions)) | **No** — parses raw HTML | none published | parser free on all tiers; $0.30–$3.00 / 1k results ([pricing](https://oxylabs.io/products/scraper-api/web/pricings)) |
| **Crawl4AI `generate_schema`** | **one-time** — *"a one-time cost… reused for unlimited extractions without further LLM calls"* ([docs](https://docs.crawl4ai.com/extraction/no-llm-strategies/)) | **config** — JSON `{baseSelector, fields[]}` | **No** | none published | OSS, free (80k★) |
| **Kadoa** | **one-time + on-drift** — *"the same way on every run, not a fresh AI guess each time"* ([docs](https://docs.kadoa.com/docs/ui/getting-started)) | **generated code** — *"generates extraction code"* ([blog](https://www.kadoa.com/blog/autogenerate-self-healing-web-scrapers)); sandboxing **COULD NOT DETERMINE** | COULD NOT DETERMINE | cites a 3rd-party 98.4%, not their own ([blog](https://www.kadoa.com/blog/how-ai-is-changing-web-scraping-2026)) | credits, only on approved production runs ([docs](https://docs.kadoa.com/docs/usage)) |
| **Olostep Parsers** vs `llm_extract` | **both, priced apart** — parser 1–5 credits vs `llm_extract` 20 credits ([pricing](https://www.olostep.com/extract-structured-data-from-html)) | COULD NOT DETERMINE ([docs](https://docs.olostep.com/features/structured-content/parsers)) | COULD NOT DETERMINE | none | ~20× gap parser vs LLM — the cleanest documented price tell found |
| **Skyvern code caching** | **one-time + auto-regen on failure** ([docs](https://www.skyvern.com/docs/developers/features/code-caching)) | **generated Playwright code** | **Yes** | 3–5× faster, ≤70% cheaper on cache hit; no accuracy numbers | OSS (23k★) |
| **Stagehand action caching** | **one-time**, cache-miss → LLM ([docs](https://docs.stagehand.dev/v3/best-practices/caching)) | cached action keyed on instruction + a11y tree | **Yes** | none | OSS (24k★) + Browserbase minutes |
| **Browse AI robots** | **one-time** point-and-click training ([help](https://help.browse.ai/en/articles/10496382)) | recorded interaction sequence | **Yes** — cloud headless Chromium ([glossary](https://www.browse.ai/glossary/headless-browser)) | none | 10 rows = 1 credit; $19–$249/mo ([pricing](https://www.browse.ai/pricing)) |
| **Octoparse / ParseHub** | **none** — pre-LLM wrapper induction; auto-detect runs once at build ([help](https://helpcenter.octoparse.com/en/articles/6470911-what-is-auto-detect-and-how-to-use-it)) | **config** — typed workflow + XPath | Yes | none | $69–$299/mo; $189–$599/mo |
| **Import.io** | **one-time** — *"when you run your extractor in the future, it uses your training"* ([docs](https://docs.import.io/user-guide/terminology/)) | trained extractor (classic wrapper) | COULD NOT DETERMINE | none | sales-gated |
| **Minexa** | **one-time** — trained once via extension, reusable scraper generated ([post](https://www.minexa.ai/post/the-real-cost-of-ai-web-scraping-tools-at-scale-what-the-demos-don-t-show-you)) | generated code / `scraper_id` | COULD NOT DETERMINE | none | flat $60/mo (120k pages), $500/mo (2M) |
| **Apify** | **splits** — Website Content Crawler modelless (Readability heuristics); "build Actors with AI" = one-time codegen ([docs](https://docs.apify.com/platform/actors/development/quick-start/build-with-ai)) | **generated Actor code** | optional (HTTP mode exists) | "99.0% runs succeeded" = completion, **not** extraction accuracy | Compute Units from $0.25/CU; AI summarize is a **separate** +$2–3/1k add-on |
| **Zyte API** | **hybrid** — stock schemas = pre-trained ML, no per-request LLM; custom attributes = **LLM every request** ([docs](https://docs.zyte.com/zyte-api/usage/extract/custom-attributes.html)) | none for custom fields | optional | none | $0.13–$1.00/1k requests; custom attrs $0.001/req or per-token |
| **Nimble** | COULD NOT DETERMINE — Agent Builder is *"built, validated, and published — ready for every run after that"* ([blog](https://www.nimbleway.com/blog/introducing-nimble-skills-web-expert-agent-builder)), but Extract Template is only a 3× premium | COULD NOT DETERMINE | COULD NOT DETERMINE | none | $1/1k plain vs $3/1k template ([pricing](https://www.nimbleway.com/pricing)) |
| **Firecrawl** | **PER-RUN** — `json` format costs **+4 credits/page on top of the 1-credit scrape** ([docs](https://docs.firecrawl.dev/features/scrape)) | none — schema is a pass-through spec | effectively yes | none; docs admit *"results might differ across runs"* ([docs](https://docs.firecrawl.dev/features/extract)) | 5–10 credits/page for extract |
| **Diffbot** | **PER-RUN** — *"no rules or per-site configuration required"* ([docs](https://www.diffbot.com/docs/extract/)) | **none by design** | **Yes** — every call | 3rd-party F1 0.951 on article extraction ([benchmark](https://github.com/scrapinghub/article-extraction-benchmark)) | 1 credit/request; $299–$3,999/mo ([pricing](https://www.diffbot.com/plans/startup)) |
| **ScrapeGraphAI / Reworkd Harambe** | **PER-RUN** — no compile-once mode found ([repo](https://github.com/ScrapeGraphAI/Scrapegraph-ai), [repo](https://github.com/reworkd/harambe)) | none | yes | none found | — |
| **Bardeen** | COULD NOT DETERMINE — help centre dead as of Aug 2026; Browser Agents are explicitly goal-driven per run | "scraper template" w/ CSS selectors | runs in user's own browser | none | 1 credit **per row**; $10–$50/mo ([pricing](https://www.bardeen.ai/pricing)) |
| **rtrvr.ai** | COULD NOT DETERMINE — "reusable network scripts as tools" is on the **roadmap**, not shipped ([blog](https://rtrvr.ai/blog/vibe-hacking-rover-gemini-flash-lite)) | — | requests execute from page context | none | — |
| **Co-Scraper** (arXiv 2606.14821) | **one-time** — fine-tuned Qwen3-8B synthesises a site-level program, then *"execute the generated scraper in a Docker environment"* ([paper](https://arxiv.org/html/2606.14821v1)) | **generated Python**, sandboxed in Docker | No | **F1 94.78%, reuse success 90.39%** on SWDE | research |
| **AutoScraper** (EMNLP 2024) | **one-time** — XPath sequence validated across 3 seed pages ([paper](https://arxiv.org/abs/2404.12753)) | **config** — XPath sequence | No | **71.56% strict "Correct"** (GPT-4-Turbo, SWDE); F1 88.69 | research |
| **Our E7 stack** | **one-time** — $0.43/board Sonnet, $0.82 Opus ([PATH-TO-90-PERCENT.md](PATH-TO-90-PERCENT.md)) | **config** — closed-vocabulary JSONB primitives, import-guarded + AST-walked | **No** — plain `httpx` | **81%** (22/27 real job boards); 26% for the hand-built pipeline | $0 recurring |

**The pricing tell held up every time.** Firecrawl charges +4 credits/page for LLM extraction and
Olostep charges 20 credits vs 1–5 — both are per-run models admitting it in the invoice. Oxylabs
gives the parser away free and charges only for the fetch; Apify bills AI summarisation as a
*separate* add-on rather than folding it into the crawl. Where the model is in the hot path, someone
is metering it.

---

## 3. What the closest prior art does that we do not

Ordered by how much it should bother us.

**① Oxylabs ships opt-in self-healing on a config artifact — the exact thing we have deferred.**
Their Custom Parser *"automatically monitors and updates the parser whenever the HTML structure
changes"*, triggered on a performance drop
([feature page](https://oxylabs.io/features/custom-parser)). We detect breakage and mark a board
stale; we do not repair it without a fresh discovery run. They close that loop on the same artifact
shape we chose. (No quantified threshold is published — the *trigger* is undocumented, which is
exactly the part we would have to invent anyway.)

**② Skyvern turns cache-miss into automatic re-derivation, and we treat failure as terminal.**
When cached code *"hits something unexpected (a layout change, a new field, a missing element)"* it
falls back to the full agent and **regenerates the cache**
([docs](https://www.skyvern.com/docs/developers/features/code-caching)). Our replay failure path
raises and waits. Their loop is strictly better *provided* the fallback is affordable — theirs is a
browser + vision model, ours is a browser + Sonnet at $0.43. Same order of magnitude. We should
steal the control flow, not the runtime.

**③ Scrapling and Healenium repair a broken selector with no model at all.** Scrapling fingerprints
an element on first scrape — tag, text, attribute names/values, sibling tags, ancestor path — and
persists it in SQLite; when the selector fails it scores every element on the new page against the
stored fingerprint and returns the best match, explicitly *"without AI"*
([docs](https://scrapling.readthedocs.io/en/latest/parsing/adaptive.html)). Healenium does the same
for Selenium locators with a tree-comparison algorithm and a 0–1 confidence score
([healenium.io](https://healenium.io/)). **This is a whole tier of repair that costs nothing and we
have not considered it.** For our DOM-transport recipes it would recover a renamed class without any
discovery spend.

**④ Crawl4AI generates the schema from multiple HTML samples, not one.** Multi-sample generation
produces stable selectors (`a[href*="/m/"]`) instead of positional ones (`tr:nth-child(6)`)
([docs](https://docs.crawl4ai.com/extraction/no-llm-strategies/)); the single-sample brittleness is
a live open issue ([#1672](https://github.com/unclecode/crawl4ai/issues/1672)). AutoScraper does the
same thing more strictly: generate independently on **3 seed pages** and keep only the XPath sequence
that extracts correctly from *all three* ([paper](https://arxiv.org/abs/2404.12753)). Our discovery
captures once. Cross-page agreement is a free robustness check we are not making.

**⑤ Zyte separates "the fields everyone wants" from "the fields you want".** Stock schemas —
including `jobPosting` — run pre-trained deterministic ML with no per-request LLM; only custom
attributes pay per call ([docs](https://docs.zyte.com/zyte-api/usage/extract/custom-attributes.html)).
A general-purpose job-posting extractor already exists as a commodity. Worth knowing before we build
another one.

**⑥ Canary scrapes.** Scheduled runs against a small set of pages with *known, predictable* values,
through the identical browser/proxy/parser path as production, to catch a broken shared code path
before a full crawl finishes ([context.dev](https://www.context.dev/blog/scraper-monitoring-in-production)).
We verify per-board; we have no cross-fleet canary.

---

## 4. What we do that they do not — and why nobody else's approach transfers

**The completeness oracle has no equivalent anywhere.** This is the finding.

Our hard constraint is that `MISSED_RUN_THRESHOLD = 2` — a record absent from two consecutive runs is
deleted from a live product. So a scraper that silently returns page one deletes the rest of the
catalogue, and the gate exists to make that impossible: *a job is never closed by a run that could not
prove it saw the whole board* ([OVERVIEW.md](OVERVIEW.md)). Every passing recipe in the 27-board
measurement had **symmetric difference 0** across two independent full sweeps
([PATH-TO-90-PERCENT.md](PATH-TO-90-PERCENT.md)).

What the rest of the field has instead:

| | what they have | what is missing |
|---|---|---|
| **The problem is named** | *"Silent truncation: a page loads partially, the scraper extracts only the first block, and you still get 'valid' rows"* ([PromptCloud](https://www.promptcloud.com/blog/web-scraping-monitoring-challenges/)) | no detector |
| **The rule is stated** | *never infer mass deletion from a partial or failed crawl* ([Bright Data](https://brightdata.com/blog/web-data/fix-inaccurate-web-scraping-data)) | no way to tell the two apart |
| **The prescription is generic** | *"Expected volume checks: records per run, per category, per geo compared to baseline"* ([PromptCloud](https://www.promptcloud.com/blog/web-scraping-monitoring-challenges/)) | trailing-baseline only — a genuinely-shrunk board and a truncated read look identical |
| **Detection latency is measured, and it is terrible** | infrastructure failures caught in minutes; **field-level completeness failures discovered on average 3–5 days later** through downstream reporting ([PromptCloud](https://www.promptcloud.com/blog/web-scraping-monitoring-challenges/)) | — |
| **Caps are silent by construction** | Firecrawl `/crawl` defaults to a **10,000-page hard cap** ([issue #871](https://github.com/mendableai/firecrawl/issues/871)); Apify's `maxCrawlPages` yields fewer items with no expected-total comparison ([docs](https://docs.apify.com/academy/api-scraping/general-api-scraping/handling-pagination)) | exactly our `assert_cap_not_hit` failure mode, unguarded |
| **Kadoa validates values, not totals** | "completeness, plausibility, schema adherence" per value ([docs](https://docs.kadoa.com/docs/workflows/error-handling)) | a competitor benchmark found real missed-record failures ([Parsera — biased source](https://parsera.org/blog/Parsera-Kadoa-AI-Scraping-Tool-Comparison)) |
| **The research is silent** | Co-Scraper, AutoScraper, RoadRunner: *no discussion of pagination, completeness, or truncation* in any of them | — |

Three more things that appear to be genuinely ours:

- **An independent oracle, not a self-comparison.** We reconcile against the board's *own declared
  total*, a facet-sum, a header count or a sitemap — a second source that does not come from the same
  read. Everyone else compares this run to the last run, which cannot distinguish a shrinking board
  from a broken reader. Target's Workday declaring 2,000 while single-valued facets sum to 11,960 is
  the case that breaks every trailing-baseline detector.
- **Asymmetric consequences.** A run may be UNVERIFIED and still write rows; it just may never
  *close* one. No product found separates "this data is usable" from "this run is trustworthy enough
  to delete on". Kadoa's nearest equivalent is a value-level plausibility check.
- **A refusal path with judgement in it.** Walmart's board was reachable only via an LLM chat
  endpoint at 4,860 requests/run with a fabricated session id; the agent solved it and we refuse it
  ([PATH-TO-90-PERCENT.md](PATH-TO-90-PERCENT.md)). No product documents refusing a site it can
  technically scrape.

**Why this explains the transfer failure:** every product surveyed sells *data*, so a partial answer
is a degraded product. We sell *a hiring-trend line*, where a partial answer is a **wrong** product —
it deletes jobs and draws a false cliff. Nobody else's architecture has a reason to carry the cost of
proving completeness, so nobody built it, so there is nothing to copy.

---

## 5. Worth stealing from the wrapper-induction literature

This problem has a 25-year research history and it asked our exact questions. Two coincidences worth
noting: **Kushmerick monitored 27 sites; Lerman monitored 27 wrappers; we measured 27 boards.**

**① RAPTURE — verify a wrapper with cheap statistical features, no ground truth.**
Kushmerick's algorithm computes 9 string features per extracted field — digit / letter / upper /
lower / punctuation / **HTML-tag** density, length, word count, mean word length — models each as a
normal distribution estimated from previously-verified pages, and scores a new page's probability
under that distribution
([AAAI-99, full text](https://cdn.aaai.org/AAAI/1999/AAAI99-011.pdf); journal version
[*World Wide Web* 3(2):79–94](https://dl.acm.org/citation.cfm?id=598743)).

Measured on 27 sites, 15 queries each, every ~3 days for 6 months — **23,416 pages, 23 real changes**:

| detector | result |
|---|---|
| naive diff-against-last-good-output | 64% accuracy / F=78 — fails because *content* legitimately changes |
| full 9-feature RAPTURE | 82% accuracy / F=90 |
| **HTML-tag density alone** | **>99% accuracy — 3 mistakes in 23,416 predictions** |

**The single best thing in this document: HTML-tag density, one number, catches almost every silent
break.** A broken extractor snags stray markup. This is roughly ten lines of code, needs no model, no
oracle and no schema change, and it is orthogonal to everything in our gate — the gate proves we saw
*enough rows*; this proves the *rows are the right shape*. Note the caveat: this detects change on a
site we already extract from, not cold-start correctness, so it is not comparable to our 81%.

**② Lerman et al. — reinduction that does not bootstrap from the broken baseline.**
This is the direct answer to "how do you avoid re-learning from an already-broken read"
([JAIR 2003](https://arxiv.org/pdf/1106.4872)). The recovery sequence: mine a page template from the
*new* pages to locate data slots → scan for text matching the **old** content patterns (start/end
token-type sequences learned *before* the break) → group candidates by feature vector → **score groups
by overlap with the old training examples**, since data usually survives a layout change → feed the
winning group to STALKER as fresh labels. It bootstraps from content regularity learned pre-break,
cross-checked against structure common to the post-break pages. Never from the current extraction.

Verified on **27 wrappers over a year, 438 comparisons, 37 real changes**
([abstract](https://arxiv.org/abs/1106.4872)):

- verification **precision 0.73, recall 0.95** — deliberately recall-biased: catch every break, tolerate
  false alarms. **That is our "failures are loud, never silently wrong" posture, published in 2003.**
- reinduction **precision 0.90, recall 0.80** across 10 sources; fields correctly identified 277/338 (~83%)
- RAPTURE-style numeric-features-only, benchmarked on the same data, **missed 17 of the 37 changes** —
  so ① is a floor, not a ceiling

**③ Co-testing — two independently-derived extractors, disagreement is the signal.**
Muslea et al. train two rule "views" (forward and backward scan) on the same labels; where they
disagree on an unlabelled page is the most informative point
([IJCAI 2003](https://www.ijcai.org/Proceedings/03/Papers/062.pdf)). For us: derive the recipe *and*
an independent count path, and treat disagreement as UNVERIFIED. This is structurally what our
oracle already does — the literature says the idea generalises past counting to any field.

**④ Vertex (Yahoo, production, 250M+ records / 200+ sites) — repair by preserved features.**
Detect change by comparing preserved features — syntactic patterns, hyperlinks, annotations on
already-extracted items — between old and new DOM, then relocate those anchors
([ICDE 2011](https://ieeexplore.ieee.org/document/5767842/)). Same mechanism Scrapling reinvented in
2025. It is the modelless repair tier, at production scale, fifteen years ago.

**⑤ Expressiveness has a known ceiling, and it is around ours.** Kushmerick's HLRT wrapper class
correctly wrapped **48%** of a surveyed sample of real Internet sources
([IJCAI-97](https://homes.cs.washington.edu/~weld/papers/kushmerick-ijcai97.pdf)). Our closed
vocabulary is far more expressive than HLRT and hits 81% with an agent authoring it. The historical
lesson holds: **the vocabulary's expressiveness, not the learner, sets the ceiling** — which matches
our own finding that the gap from 81% to 89% is "a regex in a field spec, not an agent"
([PATH-TO-90-PERCENT.md](PATH-TO-90-PERCENT.md)).

**⑥ Executability as a metric.** AutoScraper introduced Correct / Precision-only / Recall-only /
Unexecutable / Over-estimate because single-page P/R/F1 does not capture *site-wide generalisation*
([paper](https://arxiv.org/abs/2404.12753)). It is the closest thing in the literature to how we
score, and it explicitly does **not** transfer to WebArena/Mind2Web, which measure agent task success
rather than reusable-extractor quality. Useful when we next report a number.

---

## 6. Where our numbers actually sit

| source | number | what it measures | comparable to us? |
|---|---|---|---|
| **Ours** | **81%** (22/27) | agent-authored recipe replays correctly on plain `httpx`, arbitrary real job boards, 6 criteria incl. symdiff-0 | — |
| **Ours** | **26%** (7/27) | hand-built deterministic pipeline, same corpus | — |
| Co-Scraper | 90.39% reuse / F1 94.78 | SWDE, unseen sites (2 per vertical + all of `university`) ([paper](https://arxiv.org/html/2606.14821v1)) | **no** — SWDE is same-template *detail pages*; no pagination, no completeness, no auth |
| AutoScraper | 71.56% strict Correct | SWDE, GPT-4-Turbo zero-shot ([paper](https://arxiv.org/abs/2404.12753)) | closest LLM-era analogue; stricter criterion, easier corpus |
| "Beyond BeautifulSoup" | LLM-script 1.00 simple HTML → 0.57 complex → 0.12 complex-auth; full agent 1.00 / 1.00 / 0.70 | 35 real sites, 5 difficulty tiers ([arXiv](https://arxiv.org/abs/2601.06301)) | **directionally confirms our 26% vs 81%** — codegen collapses where agents hold up |
| ExtractBench | 51% valid-JSON rate; best model 6.9% field-level pass | complex structured extraction ([arXiv](https://arxiv.org/pdf/2602.12247)) | different task; a useful reminder that hard extraction is still bad |
| Kushmerick HLRT | 48% of surveyed sources wrappable | 1997 expressiveness ceiling | historical |
| **HiringCafe** | **none published** | 3.59M jobs / 116,386 companies claimed, no hit rate anywhere | our nearest domain competitor publishes nothing |

**Nobody publishes a hit rate for auto-generating a working extractor for an arbitrary user-supplied
site.** Not one vendor, in any of the ~20 surveyed. Our 26%/81% on 27 real boards with a six-criterion
verifier is more rigorous than anything found in the market and comparable in rigour to the academic
work — on a harder corpus.

**Cost, for calibration.** The one public write-up of our exact architecture puts it plainly: *"call a
good model once per site to write CSS selectors, then run those selectors forever… one frontier-model
call per site per month costs less than one value-model call per page"* — roughly $58 vs $30,600 at
100k pages/month ([webscraping.ai](https://webscraping.ai/blog/llm-web-scraping)). Minexa (vendor,
incentivised) puts LLM-per-page at $285–$5,000/mo against $60 flat at 120k pages
([post](https://www.minexa.ai/post/the-real-cost-of-ai-web-scraping-tools-at-scale-what-the-demos-don-t-show-you)).
**No one publishes the one-time cost to derive an extractor for a new site.** Our $0.43/board Sonnet,
$0.82 Opus may be the only measured figure in public.

---

## 7. Config vs generated code, and the sandbox question

**The serious implementations that run on someone else's infrastructure emit config; the ones that
run in your own process emit code.**

| emits **config** (closed vocabulary) | emits **code** |
|---|---|
| Oxylabs Custom Parser (`xpath`/`css`/`element_text`/`_items`) | Kadoa (sandboxing **COULD NOT DETERMINE**) |
| Crawl4AI schema | Skyvern (Playwright, sandboxing undocumented) |
| Octoparse / ParseHub workflows | Apify Actors (their platform, their isolation) |
| AutoScraper XPath sequences | Minexa (Python) |
| **Us** | Co-Scraper — *"execute the generated scraper in a Docker environment"* ([paper](https://arxiv.org/html/2606.14821v1)) |

**Not one product documents how it sandboxes LLM-generated scraper code.** Kadoa says it generates
extraction code and never says where it runs. Co-Scraper, a research paper, is the only source found
that names its isolation at all — and Docker is below the 2026 bar: the consensus for untrusted or
model-generated code is Firecracker/Kata microVMs or gVisor, on the grounds that shared-kernel
containers are inadequate and **Python has no viable in-language sandbox**
([sandboxing survey](https://manveerc.substack.com/p/ai-agent-sandboxing-guide),
[Modal](https://modal.com/resources/run-untrusted-code-safely)).

**Conclusion for us: the closed vocabulary is the right call and the survey strengthens it.** We are
sandboxed by construction — an import guard plus an AST walk over a fixed primitive set — and we
avoid an entire category of problem that the code-generating products have either solved privately or
not solved at all. The cost is expressiveness, which is exactly the ceiling Kushmerick identified in
1997; the fix is to widen the vocabulary (a `paginate_cursor` primitive, a slug regex), never to open
the door to arbitrary execution.

---

## 8. Stop building these — someone did them better

1. **A bespoke "is this extractor broken?" heuristic.** Implement **HTML-tag density drift** first
   (RAPTURE, >99% on 23,416 pages). It is ten lines, needs no model, and is orthogonal to the
   completeness gate. Only build more if it misses.
2. **A from-scratch re-derivation design.** Lerman's reinduction is a published, measured recipe
   (P=0.90/R=0.80) that specifically avoids bootstrapping from the broken read. Port the shape.
3. **A modelless repair tier, invented fresh.** Scrapling's element fingerprint + similarity match
   and Healenium's tree-comparison scoring are both documented and free; Yahoo's Vertex proves the
   pattern at 250M records. Copy the fingerprint schema.
4. **Single-sample recipe authoring.** Crawl4AI has the open bug and AutoScraper has the fix:
   generate on ≥3 pages, keep only what works on all of them. Adopt the 3-seed rule.
5. **A generic job-posting field extractor.** Zyte's stock `jobPosting` schema is commodity
   pre-trained ML with no per-request LLM. If we ever need a fallback parser, buy it.
6. **A recurring-cost debate.** Settled in public and in our own measurements: modelless replay is
   ~100–500× cheaper than per-page inference. Stop re-litigating it.
7. **Chasing >93%.** Kushmerick's 48% HLRT ceiling and our own Stage-4 analysis agree that the last
   few percent are vocabulary and judgement, not model quality. Walmart is a correct refusal, not a gap.

**Keep building, because nobody else has it:** the completeness oracle, the independent-source
reconciliation, the never-wrong-close rule, and the refusal path. That is the whole moat.

---

## Sources

Primary sources are linked inline. The load-bearing ones:

- Oxylabs Custom Parser — https://developers.oxylabs.io/scraping-solutions/web-scraper-api/features/custom-parser/getting-started · https://github.com/oxylabs/custom-parser-instructions
- Crawl4AI schema generation — https://docs.crawl4ai.com/extraction/no-llm-strategies/
- Kadoa — https://docs.kadoa.com/docs/ui/getting-started · https://www.kadoa.com/blog/autogenerate-self-healing-web-scrapers
- Skyvern code caching — https://www.skyvern.com/docs/developers/features/code-caching
- Scrapling adaptive matching — https://scrapling.readthedocs.io/en/latest/parsing/adaptive.html
- Kushmerick, RAPTURE (AAAI-99) — https://cdn.aaai.org/AAAI/1999/AAAI99-011.pdf
- Lerman/Minton/Knoblock, Wrapper Maintenance (JAIR 2003) — https://arxiv.org/abs/1106.4872
- AutoScraper (EMNLP 2024) — https://arxiv.org/abs/2404.12753
- Co-Scraper (arXiv 2606.14821) — https://arxiv.org/html/2606.14821v1
- Beyond BeautifulSoup benchmark — https://arxiv.org/abs/2601.06301
- Cost of cached selectors vs per-page LLM — https://webscraping.ai/blog/llm-web-scraping
