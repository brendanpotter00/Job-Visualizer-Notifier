---
name: taxonomy
description: The single source of truth for classifying a job posting into a category, a leveling tier, and normalized tags. Read in full by every classify agent and every judge agent before producing or checking a label. Editing this file changes the taxonomy version hash recorded on each enrichment.
version: v7
---

# Job enrichment taxonomy

You are labeling a single job posting from its **title**, **cleaned description**, **company**, and **raw location**. Produce exactly one `category`, exactly one `level` (the most specific true tier), an ordered `subcategories` array (0-2, software_engineering only), a `level_includes` filter-expansion set, and up to ~8 normalized `tags`. Also normalize the `location`. Never invent values outside the enums below. When nothing fits, pick the closest enum value and lower your `confidence` — do not emit a new label.

**Title-only postings (empty cleaned description).** Some sources don't capture a description; you'll receive a blank `clean_description`. Do NOT refuse — classify from the **title**, **company**, and **raw location** alone (a title like "Senior Backend Engineer" or "Data Scientist Intern" already carries category + level). Set `confidence <= 0.5` to reflect the reduced signal; the pipeline also clamps these rows low in code and routes them through the judge. Never guess `tags` you can't support from the title — emit only what the title/company clearly imply.

The output contract (what the classify agent returns per job) is:

```json
{
  "job_listing_id": "…",
  "category": "software_engineering",
  "subcategories": ["backend"],
  "level": "senior",
  "level_includes": ["senior"],
  "tags": ["backend", "distributed-systems", "go"],
  "locations": [ /* byte-compatible with JVN _LOCATIONS_SCHEMA — see section 5 */ ],
  "confidence": 0.0-1.0,
  "subcategory_confidence": 0.0-1.0,
  "reasoning": "one or two sentences citing the decisive title/description signal"
}
```

---

## 1. Category (exactly one primary)

Pick the **primary** function of the role — what the person is hired to *do day to day*, not the team they sit on or the domain of the product.

| slug | one-line decision rule |
|---|---|
| `software_engineering` | The big catch-all for **anyone whose core deliverable is building software systems**. "Software Engineer", "SWE", "Backend/Frontend/Full-stack/Platform/Infra/Mobile/Site Reliability Engineer", **"Member of Technical Staff"/MTS** (the default for that house title — see the MTS tie-breaker), **plus data engineers, ML/AI engineers, analytics engineers, and data-platform/pipeline engineers** — roles that *build* pipelines, services, and ML serving infrastructure. "Engineering Manager" of a software team (see level=manager). Sub-specialties are captured in `subcategories` (see section 1b) — they never change this verdict. |
| `hardware_engineer` | Engineering centered on **physical hardware**: electrical, firmware / embedded-hardware, ASIC/FPGA/RTL, PCB, RF, mechanical, hardware systems integration, hardware test/validation. "Hardware Engineer", "Electrical Engineer", "Firmware Engineer", "Embedded (HW) Engineer", "Mechanical Engineer", "ASIC/FPGA Engineer". |
| `product_manager` | Owns **product direction / roadmap / requirements** — the *what & why*. "Product Manager", "PM", "Group/Principal/Technical Product Manager", "Product Owner". A **growth PM** lives here, not in `growth`. **Program / project / delivery coordination that does NOT own product direction is `business_ops`, not this.** |
| `data_scientist` | **Analysis / modeling / research-centric** roles: statistical modeling, experimentation, ML research, causal/inference work. "Data Scientist", "Applied Scientist", "Research Scientist", "ML Scientist", "Quantitative Researcher". A *scientist* whose deliverable is models / experiments / research. A data or ML **engineer** who builds pipelines / serving systems -> `software_engineering`; a non-coding analyst / BI role -> `business_ops`. |
| `growth` | **Marketing & growth functions:** growth / performance / paid marketing, demand generation, lifecycle / CRM / email, SEO / content, brand, and **product marketing (PMM)**. |
| `business_ops` | Everything else a company hires for: **sales / AE / BD, partnerships, operations, finance, legal, people/HR, recruiting, customer success / support**, **program / project / delivery management** (Technical Program Manager / TPM, Program Manager, Project Manager, Delivery Manager, Scrum Master, PMO — coordination, schedule & cross-team execution, *not* product direction), solutions/sales engineering (unless the core work is writing product code), rotational/MBA/general-early-career programs — **and data-analyst / BI / analytics roles whose work is querying-and-reporting, not writing production code**. |

**Room to grow:** if a role genuinely fits none of the six, choose the closest and set `confidence <= 0.55` with a `reasoning` note. Never mint a seventh TOP-LEVEL category — never emit a value outside the six enum slugs.

### Category tie-breakers (the ones that actually bite)
- **software_engineering vs data_scientist — scientist vs engineer:** the split is *what the person is hired to produce*. A **scientist** — models, experiments, analyses, research, novel techniques ("Data Scientist", "Applied Scientist", "ML/Research Scientist", "Quantitative Researcher") -> `data_scientist`. An **engineer** — pipelines, warehouses, serving/ranking infrastructure, MLOps, production systems ("Data Engineer", "ML Engineer", "Analytics Engineer", "Data Platform Engineer") -> `software_engineering`. Read the responsibilities, not just the title: an "ML Engineer" whose mandate is genuinely model research leans `data_scientist`, and lower confidence on real blends.
- **software_engineering vs hardware_engineer:** writes software (services, pipelines, models, ML serving) -> `software_engineering`. Designs / builds / validates **physical hardware** — electrical, firmware / embedded bring-up, ASIC/FPGA/RTL, PCB, RF, mechanical -> `hardware_engineer`. Firmware that is hardware bring-up / embedded device control leans `hardware_engineer`; general application/backend/platform software is `software_engineering`. Read the primary deliverable, not the domain.
- **The three-way data split (scientist / engineer / analyst):** a data **scientist** who models, experiments, and researches -> `data_scientist`. A data / analytics *engineer* who **builds the pipelines / warehouse in code** -> `software_engineering`. A **data analyst / BI analyst** whose day-to-day is querying, dashboards, and reporting with **no modeling and no production code** -> `business_ops`.
- **product_manager vs business_ops (program/project management):** product owns the *what & why* (direction, roadmap, requirements) -> `product_manager`. Program / project / TPM / Scrum Master owns the *how & when* (delivery, coordination, schedule, cross-team execution) -> `business_ops`. There is **no** separate TOP-LEVEL project_manager category — a coordination-only role that does not own product direction is `business_ops`.
- **growth vs product_manager:** a growth / performance **marketer** -> `growth`. A growth **PM** who owns a product surface's roadmap -> `product_manager`.
- **growth vs business_ops:** demand gen, paid / performance marketing, lifecycle / CRM, SEO / content, brand, product marketing (PMM) -> `growth`. Sales / AE / BD, partnerships, and revenue operations -> `business_ops`.
- **Solutions / Sales / Forward-Deployed Engineer:** `business_ops` **unless** the core deliverable is committed product code -> then `software_engineering`. (There is no top-level forward-deployed category — when the core deliverable IS committed product code, the row is `software_engineering` with `subcategories=["forward_deployed"]`.)
- **"Member of Technical Staff" / MTS — read the qualifier, not the wrapper.** MTS is a company-wide *house title for an IC*, not a function: the AI labs (xAI, Perplexity, Cohere, Fireworks, Modal, OpenEvidence, Poke) plus Microsoft, Salesforce, PayPal, Vercel and Netflix post most of their roles under it. It **defaults to `software_engineering`** — the overwhelming majority of the MTS rows prod has labelled are exactly that — but whatever follows the wrapper decides: "MTS (TPM, Inference)" whose body is launch coordination -> `business_ops`; "MTS, Research" whose deliverable is foundational research -> `data_scientist`; "MTS (Search Quality Analyst)" whose deliverable is metric design, evals and A/B analysis -> `data_scientist`. **The qualifier can mislead in the other direction too, so read the body:** Poke's "MTS - Research" is one generalist engineering req (scale/infra, product, devtools, TypeScript) and is `software_engineering`. Graded acronyms are the same title with a tier attached — A/S/L/P MTS = Associate/Senior/Lead/Principal Member of Technical Staff (see the leveling rule).
- **Engineering Manager:** the category is the discipline managed. A software team's manager -> `software_engineering` + `level = manager`; a **hardware / firmware / electrical** team's manager -> `hardware_engineer` + `manager`; a delivery / program manager who coordinates rather than owns product -> `business_ops`.
- **Rotational / MBA / "Early Career Program" (non-technical):** `business_ops`. A "People Operations / Total Rewards Early Career Rotation" is `business_ops` + `new_grad`, **not** `software_engineering` — the word "Program"/"Engineering-adjacent company" does not make it an engineering role.

## 1b. Subcategories (software_engineering ONLY, 0-2, most specific first)

Reached **ONLY** after section 1 has already returned `software_engineering`. **The arrow never runs backwards:** nothing here can pull a row INTO `software_engineering`, and emitting one on any other category is a measured error.

**`[]` is a legitimate and common answer.** Most postings say nothing about what kind of engineering the role is; `[]` is far better than a guess. Index 0 is the primary.

| slug | the role's core deliverable |
|---|---|
| `ai_engineering` | Product features on a model it did NOT train — the model is a dependency. |
| `backend` | Server-side code consumed by the product's own users or client apps. |
| `data_engineering` | The movement and shaping of data — pipelines, warehouses, streaming. |
| `devops_sre` | Keeping other teams shipping and running — CI/CD, on-call, reliability. |
| `embedded_systems` | Code compiled against hardware or a kernel — firmware, drivers, RTOS. |
| `forward_deployed` | Production code inside a NAMED customer's environment. |
| `frontend` | Owns UI and does NOT also own the server. |
| `full_stack` | Explicitly owns BOTH halves. |
| `growth_engineering` | Ships code whose success metric is signups, activation, retention, revenue. |
| `infrastructure_platform` | Consumers are other engineers or services. Largest bucket, NOT a catch-all. |
| `ml_engineering` | Changes weights, or builds what produces and serves them; success is a model metric. |
| `mobile` | The deliverable is an app binary. |
| `product_engineering` | Owns a user-facing surface end-to-end — decides WHAT ships, not just how. |
| `qa_testing` | Test coverage or test infrastructure itself. |
| `quantitative` | Correctness measured in money and microseconds. |
| `robotics_autonomy` | Senses, plans, actuates in the physical world. |
| `security` | The subject matter is security AND the deliverable is code. |

Five rails:
- **`full_stack` is exclusive** — never emit it alongside `frontend` or `backend`.
- **Never route on an AI mention** — "AI-first"/"AI/ML org" says nothing about what the person ships.
- **`ai_engineering` vs `ml_engineering`: do you change the weights?** Yes -> `ml_engineering`; consuming someone else's model -> `ai_engineering`.
- **`growth_engineering` routes on the METRIC, not the layer** — and only after section 1 already said `software_engineering`. Campaigns/channels are category `growth` and never reach this table.
- **`product_engineering` is not ownership boilerplate** — "high agency"/"wear many hats"/"0->1" is not the signal; a named user-facing surface plus say over WHAT ships is.

The full per-slug rubric, tie-breakers and worked examples live in `SUBCATEGORIES.md` — the subcategory-only lane loads it; you do not need it here.

---

## 2. Level (exactly one; most specific true tier)

Emit the **single most specific tier that is true**, plus `level_includes` (the set a UI filter on that tier should match — see section 3 hierarchy).

| slug | rank | matches |
|---|---|---|
| `intern` | 0 | An **internship or co-op** — a temporary role for someone **still completing a degree** (current undergrad / grad / PhD student, a campus "Summer/Fall 20XX" intern program, a co-op term). Signals: "Intern", "Internship", "Co-op", "PhD Intern", "current students", "pursuing a degree". The person **returns to school afterward** — contrast `new_grad` (below), a **full-time** role for someone who has just *completed* a degree. **Standalone tier — NOT a subset of any other level** (`level_includes = ["intern"]`). |
| `new_grad` | 1 | Explicitly targets **recent college grads** for a **full-time** role: "New Grad", "New Graduate 2026", "University Grad", "Campus", "Early Career" tied to a graduation year / degree-completion window, new-grad rotational programs. Degree **completed**, starting full-time. **Strict subset of `entry`.** |
| `entry` | 2 | Junior / 0–2 yrs / "Engineer I" / "Associate" / open to early-career **without** requiring recent-grad status. |
| `mid` | 3 | "Engineer II", ~2–5 yrs, "Software Engineer" with no seniority qualifier and >2 yrs implied. **The default tier whenever a posting carries no explicit level or years-of-experience signal** (see the explicit-signal-or-mid tie-breaker). |
| `senior` | 4 | "Senior", "Sr.", "Engineer III", ~5+ yrs, lead-ish but individual contributor. |
| `senior_plus` | 5 | "Staff", "Principal", "Distinguished", "Senior Staff", "Fellow", "Architect" at staff+ scope. IC above senior. **The "Staff" in "Member of Technical Staff" is not this word** — see the MTS tie-breaker. |
| `manager` | 6 | People-management is the core of the role: "Manager", "Director", "Head of", "VP", "Eng Manager". Orthogonal to IC seniority — a "Senior Engineering Manager" is `manager`. |

### Leveling tie-breakers
- **Years-of-experience overrides the title's default tier.** When the title carries **no** seniority qualifier, let the description's experience requirement set the level: a role whose description asks for **~5+ years** is `senior` (not the `mid` default), and **~8+ years / "Staff"/"Principal"/"Architect" scope** is `senior_plus` — even when the title is a bare "Software Engineer"/"Analyst"/"Manager of X"-type string. **Title seniority words still win when present:** an explicit "Senior"/"Staff"/"Principal" in the title sets the tier regardless of a lower stated YOE.
- **Reading a YOE number: bracket on N, and count a "Preferred" one.** "N+ years" is bracketed by its **lower bound N** — the "+" is open-ended and never promotes a tier on its own, so "4+ years" is `mid` (the 2–5 band) and "5+ years" is `senior`. A YOE that appears only under a **"Preferred" / "Nice to have" / "Bonus"** heading still counts as an explicit signal — it is the band the company is advertising — but treat it as the weaker form: take the tier it implies and set `confidence <= 0.7`. A posting whose ONLY experience hint is a preferred one is never evidence for `senior_plus`.
- **No explicit signal -> default `mid`, never `senior` (the explicit-signal-or-mid rule; encodes a real production correction).** The ONLY seniority signals are explicit ones: a level word in the title or body ("Senior", "Staff", "Principal", "Junior", "New Grad", "Intern"), a stated years-of-experience requirement ("5+ years" -> senior territory; "2–4 years" -> mid; "0–1 years" -> entry), or people-management scope ("manage a team" -> manager). When a posting has NONE of these, emit `mid` with `confidence <= 0.6`. **Difficulty / intensity / agency language is NOT a seniority signal:** "own everything end-to-end", "extremely hard problems", "high agency", "extreme ownership", "wear many hats", cracked-engineer / missionary startup tone — startup postings are written to sound maximally hard by nature, and none of that justifies `senior` on its own. The judge applies the same standard: never bump `mid` -> `senior` (and never block a `senior` -> `mid` revision) based on difficulty/vibes alone.
- **"Member of Technical Staff" is NOT a seniority signal (encodes a real production error).** The wrapper says nothing about tier, so a bare "Member of Technical Staff" with no level word and no stated years-of-experience is **`mid`** under the explicit-signal-or-mid rule — however senior the posting sounds. A judge once justified a bump with *"Title 'Member of Technical Staff' explicitly signals staff-level IC scope"*; it does not. Prod carries that one title labelled `entry`, `mid`, `senior` **and** `senior_plus` across four postings at a single company — only the stated YOE ever separated them. What *does* set the tier: a stated YOE requirement, a level word attached to the wrapper ("Senior/Lead/Principal Member of Technical Staff"), or the graded acronym — **`AMTS` -> `entry`, `MTS` -> no signal (default `mid`), `SMTS` -> `senior`, `LMTS`/`PMTS` -> `senior_plus`** (Lead / Principal IC above senior). **"Lead" means `senior_plus` ONLY inside this acronym ladder**, where it is the rung above SMTS; a bare "Lead Engineer" elsewhere is still `senior` per the `senior` row above.
- **`intern` vs `new_grad` — keep internships out of the new-grad filter:** if the role is an **internship or co-op with the degree still in progress** (current students, PhD candidates, a campus "Summer/Fall 20XX" intern program, a co-op term; signalled by "Intern", "Internship", "Co-op", "PhD Intern"), it is **`intern`** — its own standalone tier, `level_includes = ["intern"]`, and it does **NOT** surface under `entry` or `new_grad`. `new_grad` is reserved for **full-time** roles targeting someone who has *just finished* a degree. For a "Summer/Fall 20XX" posting, read whether the person is still enrolled and returns to school (**`intern`**) or is starting full-time after graduation (**`new_grad`**). When the title literally says "Intern"/"Co-op", route to `intern` even if a class year is present.
- **`new_grad` vs `entry` — the important distinction the whole system exists for:**
  - Role open to recent grads **and** experienced early-career people, no graduation-year gate -> **`entry`**.
  - Role that *specifically* targets recent college grads for a **full-time** position — "New Grad", a class year ("2026"), "university program", campus recruiting, degree-just-completed -> **`new_grad`** (and `level_includes` = `["new_grad", "entry"]`). If it is an **internship/co-op** rather than a full-time role, it is `intern` instead (see above).
  - When genuinely unsure between the two, prefer **`entry`** and lower confidence (entry is the safer superset for filtering).
- **Manager beats IC seniority:** if the person manages people, `level = manager` regardless of "Senior"/"Principal" in the title.
- **Staff/Principal IC -> `senior_plus`, not `manager`** (Principal Engineer ICs lead technically without direct reports; Principal *Product Manager* is `senior_plus` too — it's an IC tier).
- **Bilingual / dual-language titles** ("Développeur logiciel Sénior / Senior Software Developer"): read either language; "Sénior/Senior" -> `senior`.

---

## 3. The `new_grad ⊂ entry` hierarchy (filter contract)

This is the one hierarchy the product depends on. It is enforced in two places: the `level_includes` set you emit, and the JVN filter expansion.

- Emit `level` = the most specific true tier.
- Emit `level_includes`:
  - `new_grad` -> `["new_grad", "entry"]`  (a new-grad role also shows under the "entry" filter)
  - `intern` -> `["intern"]`  (standalone — an internship is its own filter and does **not** surface under `entry` or `new_grad`)
  - every other tier -> just itself, e.g. `senior` -> `["senior"]`
- **Filter contract (JVN side, for reference):** clicking **"entry"** returns `level ∈ {entry, new_grad}`. Clicking **"new_grad"** returns `level = new_grad` only. So: new-grad jobs surface for someone browsing entry-level, but someone specifically filtering "new grad" does **not** get flooded with general early-career roles.

The eval scorer measures this two ways: `exact` (did you get `new_grad` vs `entry` right) **and** `filter_consistent` (predicting `entry` for a true `new_grad` is a HIT for the entry filter but a MISS for the new_grad filter). Both are reported.

---

## 4. Tags (<= ~8, normalized)

Lowercase, hyphenated, deduplicated skill / tech / function tags: languages (`python`, `go`, `rust`), domains (`distributed-systems`, `ranking`, `payments`, `robotics`), functions (`backend`, `frontend`, `mlops`, `experimentation`), and seniority-neutral descriptors. No sentence fragments, no company names, no the category slug itself. Prefer widely-used canonical forms (`ml` not `machine-learning`, `k8s` -> `kubernetes`). A subcategory slug (section 1b) belongs in `subcategories`, not duplicated as the sole tag.

---

## 5. Location normalization

Normalize the raw location into `locations[]` **byte-compatible with JVN's `_LOCATIONS_SCHEMA`** (the classify agent is given that schema at runtime — follow it exactly; do not improvise field names). The schema element is:
`{canonical_name, kind ∈ {city,region,country,remote}, city, region, country, remote_scope, confidence}` (all fields required; nullable ones emitted as null).

Rules:
- Multiple locations -> multiple entries. "Remote (US)" -> a remote entry with the country/region scope.
- **Ambiguous HQ / company tokens** (e.g. `"Weave HQ"`, `"Costa Mesa, CA (HQ)"`, bare `"HQ"`): resolve the actual city. When the description or your own knowledge doesn't settle it, you MAY use **WebSearch** for "<company> headquarters location" and take the resolved city — but emit it with `confidence <= 0.7` so the **judge verifies it** before write-back. (Real failure this prevents: "Weave HQ" was previously mapped to "Remote (Global)"; Weave is headquartered in Lehi, Utah.)
- `"Costa Mesa, CA (HQ)"` -> `Costa Mesa, CA, USA` (the "(HQ)" is a qualifier, not the city).
- Never drop a real city because it carries an "(HQ)" suffix.

---

## 6. Worked few-shots (from real postings)

1. **"2026 Total Rewards/People Operations Specialist - Early Career Rotation Program"** @ Anduril, loc "Costa Mesa, CA (HQ)", dept People ->
   `category=business_ops`, `level=new_grad`, `level_includes=[new_grad,entry]`, `tags=[people-ops,total-rewards,rotational]`, location `Costa Mesa, CA, USA`. **Trap:** defense/eng company + "Program" != software_engineering; it's a People/HR role.
2. **"Développeur logiciel Sénior — Diagnostics / Senior Software Developer"** @ Unity, loc "CAN-Montreal", dept Engineering ->
   `category=software_engineering`, `subcategories=[backend]`, `level=senior`, `tags=[backend,telemetry,observability]`, location `Montreal, QC, Canada`.
3. **"Data Engineer, Quality Intelligence"** @ Anduril, "Costa Mesa, CA (HQ)", dept Hardware Eng : Quality ->
   `category=software_engineering` (**data engineers fold into software_engineering — the person builds ETL / pipelines in code**), `subcategories=[data_engineering]`, `level=mid`, `tags=[etl,data-pipelines,quality]`, location `Costa Mesa, CA, USA`.
4. **"Principal Machine Learning Engineer, Ads & Promos Delivery"** @ DoorDash, "Sunnyvale", dept Ads Engineering, desc = "design and build next-generation AI-first ranking systems … sequence modeling, deep learning, LLMs" ->
   `category=data_scientist` (**the mandate is *designing the models/ranking* — read the responsibilities, not the "Engineer" title**), `subcategories=[]` (**the arrow never runs backwards — a subcategory can never pull a row into software_engineering**), `level=senior_plus` (Principal IC), `tags=[ranking,ml,llm,ads]`, location `Sunnyvale, CA, USA`. **Blend — set confidence ~ 0.7;** if the responsibilities had emphasized serving infra/MLOps it would be `software_engineering`.
5. **"Principal Product Manager, uAds"** @ Unity, "USA-San Francisco", dept Product Management ->
   `category=product_manager`, `level=senior_plus`, `tags=[ads,platform,strategy]`, location `San Francisco, CA, USA`.
6. **"Engineering Manager, Data"** @ DoorDash, "Seattle", dept Data, desc = "lead the growing team of Data engineers … data warehouse architecture … pipelines" ->
   `category=software_engineering` (**the team writes pipeline / warehouse code — data engineering is software_engineering**), `subcategories=[data_engineering]`, `level=manager`, `tags=[data-platform,warehouse,leadership]`, location `Seattle, WA, USA`.
7. **"Senior Sales Specialist - Robotics"** @ Unity, "USA-San Francisco", dept Business Development & Sales ->
   `category=business_ops`, `level=senior`, `tags=[sales,robotics,business-development]`, location `San Francisco, CA, USA`. **Trap:** "Robotics" domain != engineering; the job is selling.
8. **"Senior Firmware Engineer, Flight Controls"** @ Anduril, "Costa Mesa, CA (HQ)", dept Hardware Engineering, desc = "bring-up and validation of embedded firmware on custom avionics boards, register-level drivers, board bring-up" ->
   `category=hardware_engineer` (**embedded / firmware bring-up on physical boards, not application software**), `subcategories=[]` (**the `embedded_systems` slug does NOT pull a hardware row into software_engineering**), `level=senior`, `tags=[firmware,embedded,avionics]`, location `Costa Mesa, CA, USA`.
9. **"Technical Program Manager, Platform Delivery"** @ DoorDash, "Sunnyvale", dept Program Management, desc = "drive cross-team schedules, dependencies, and launch readiness" ->
   `category=business_ops` (**program / delivery coordination — owns schedule & cross-team execution, not product direction; there is no project_manager category, so coordination-only roles are `business_ops`**), `level=senior`, `tags=[program-management,cross-functional,delivery]`, location `Sunnyvale, CA, USA`.
10. **"Senior Growth Marketer, Performance & Lifecycle"** @ Unity, "USA-San Francisco", dept Marketing, desc = "own paid acquisition, lifecycle / CRM, and conversion funnels" ->
    `category=growth` (**performance / lifecycle marketing — a marketer, not a PM**), `level=senior`, `tags=[growth,performance-marketing,lifecycle]`, location `San Francisco, CA, USA`.
11. **"Data Scientist II, Experimentation"** @ Pinterest, "San Francisco, CA", dept Data Science, desc = "design and analyze A/B experiments, build causal-inference models, partner with product teams on metric definitions" ->
    `category=data_scientist` (**experimentation / causal inference — analysis and modeling, not pipeline building**), `level=mid` ("II"), `tags=[experimentation,causal-inference,ab-testing]`, location `San Francisco, CA, USA`.
12. **"Applied Scientist III"** @ Amazon, "Seattle, WA", desc = "develop novel ML models and algorithms, publish research, prototype and evaluate new modeling techniques" ->
    `category=data_scientist` (**an applied *scientist* — model development and research is the deliverable**), `level=senior` ("III"), `tags=[ml,research,modeling]`, location `Seattle, WA, USA`. **Contrast with few-shot 3:** a Data *Engineer* who builds the pipelines that feed these models is `software_engineering`.
13. **"Software Engineer (Core Infrastructure)"** @ Browserbase (startup), "San Francisco, CA", desc = "you'll own everything you ship end-to-end … tackle extremely hard problems in browser infrastructure at scale … high agency, move fast" — **no level word anywhere, no years-of-experience requirement** ->
    `category=software_engineering`, `subcategories=[infrastructure_platform, backend]` (**two slugs, primary first**), `level=mid` (**explicit-signal-or-mid rule: hard-sounding, high-agency startup language is NOT a seniority cue**), `confidence <= 0.6`, `tags=[infrastructure,browsers,platform,backend]`, location `San Francisco, CA, USA`. **Trap:** this posting *sounds* senior — it was previously mislabeled `senior` for exactly that reason and human-corrected to `mid`. Intensity/ownership/mission language never sets the tier; only explicit level words, stated YOE, or management scope do. **Contrast (same company, same intense tone):** Browserbase's "Design Engineer" and "Product Designer" postings state "5+ years of product design experience" — an explicit YOE requirement, so they are `senior` under the YOE-override rule even with no level word in the title. The rule is explicit-signal-or-mid, not always-mid.
14. **"Software Engineer Intern (AI/ML) - 2026"** @ Snowflake, "Berlin", desc = "for students currently pursuing a BS/MS in Computer Science; a 12-week summer internship" ->
    `category=software_engineering`, `subcategories=[]` (**the title names an AI/ML org but says nothing about what the intern SHIPS — never route on an AI mention**), `level=intern`, `level_includes=[intern]`, `tags=[ml,ai,backend]`, location `Berlin, Germany`. **The degree is still in progress, so it is `intern`, not `new_grad`** — and `level_includes` is `["intern"]` (standalone), so the role never floods the new-grad or entry filters. **Contrast few-shot 1:** a *full-time* early-career rotation for a just-graduated hire is `new_grad`. Keep leveling out of `tags` — no "internship"/"summer" tag; the `intern` level already carries that.

15. **"Member of Technical Staff (TPM, Inference)"** @ Perplexity, "San Francisco", desc = "looking for a **technical program manager** to be the connective tissue between our model providers, engineering, and product teams … coordinating onboarding, launch readiness and rollout … rituals, dashboards, launch checklists … **6+ years** of combined technical program management or product management experience" ->
    `category=business_ops` (**the MTS wrapper is a house title, not a function — the "TPM" qualifier plus a body of coordination and launch work puts it in program management**), `level=senior` (**6+ years stated; the wrapper itself carries no tier**), `tags=[program-management,inference,cross-functional]`, location `San Francisco, CA, USA`. **Contrast, same company:** "Member of Technical Staff (Machine Learning Engineer, Ranking Quality — Search)" builds ranking infrastructure (feature computation, low-latency serving, cascades, monitoring) and states "Minimum 5 years" -> `software_engineering` / `senior`.
16. **"Member of Technical Staff"** @ OpenEvidence, "San Francisco", desc = "a brilliant builder … smart, ambitious, scrappy, autonomous … get your hands dirty, bruised, and bloody making something from nothing … spikes in Machine learning / Applied AI / Fullstack / Frontend / Infrastructure" — **no level word, no years-of-experience anywhere** ->
    `category=software_engineering`, `level=mid` (**explicit-signal-or-mid — the wrapper is not a tier and maximum-intensity startup prose is not a seniority cue**), `confidence <= 0.6`, `tags=[fullstack,applied-ai,frontend,infrastructure,healthcare]`, location `San Francisco, CA, USA`. **Contrast:** Fireworks' identically-titled "Member of Technical Staff" states "four (4) years of experience", which is still `mid`; its "Cloud Infrastructure" posting states "5+ years" and is `senior`. Same title, three different tiers, decided only by the stated YOE.

### Quick canonical mappings
"SWE Intern"/"PhD Intern"/"Summer Intern 2026"/"Co-op" (degree in progress) -> swe/intern · "Staff SWE" -> swe/senior_plus · "New Grad SWE 2026" (full-time) -> swe/new_grad · "Software Engineer II" -> swe/mid · bare "Software Engineer" (no level word, no YOE stated — however hard the posting sounds) -> swe/mid · "Engineering Manager" -> swe/manager · "Data Engineer"/"Analytics Engineer"/"ML Engineer" -> software_engineering · "Data Scientist"/"Applied Scientist"/"ML Research Scientist"/"Research Scientist"/"Quantitative Researcher" -> data_scientist · "Firmware/Electrical/ASIC/Embedded/Mechanical Engineer" -> hardware_engineer · "Technical Program Manager"/"Program Manager"/"Scrum Master" -> business_ops · "Growth/Performance Marketer"/"PMM"/"Demand Gen" -> growth · "Data Analyst"/"BI Analyst" (no production code) -> business_ops · "Solutions/Sales Engineer" -> business_ops (unless core coding) · "MBA Rotational" -> business_ops/entry · bare "Member of Technical Staff"/"MTS" (no level word, no YOE) -> software_engineering/mid · "Senior MTS"/"SMTS" -> senior · "Lead MTS"/"LMTS"/"Principal MTS"/"PMTS" -> senior_plus · "AMTS" -> entry · "MTS (TPM, …)" -> business_ops · "MTS, Research" (foundational research) -> data_scientist.
Subcategories (software_engineering only): "Backend/Server Engineer" -> [backend] · "Data Engineer"/"Analytics Engineer" -> [data_engineering] · "ML Engineer"/"MLOps" -> [ml_engineering] · "Platform/Infrastructure/Cloud Engineer" -> [infrastructure_platform] · "SRE"/"DevOps" -> [devops_sre] · bare "Software Engineer" with no specialty signal -> [].

---

## 7. Confidence discipline
Set `confidence` to reflect genuine ambiguity — it drives real behavior. Under the default `judge:scope=low_confidence`, the judge re-checks any row whose `confidence` is below the ceiling (0.85), so an honest low score is what routes an uncertain label to review; it is also measured against real errors in the eval calibration check. Be honest: category blends (ML-eng vs data-scientist), new_grad-vs-entry edges, intern-vs-new_grad edges (a "Summer 20XX" program that could be either), and web-resolved locations should carry `confidence <= 0.7`; title-only labels `<= 0.5`.
Subcategory uncertainty goes in `subcategory_confidence` and **NEVER** in `confidence` — `confidence` stays category+level only, because the 0.85 judge-routing ceiling and the committed calibration baseline are keyed to it. Emit `subcategory_confidence: null` when `subcategories` is `[]`.
