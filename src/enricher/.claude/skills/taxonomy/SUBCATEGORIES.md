---
name: taxonomy-subcategories
description: The FULL per-slug rubric, tie-breakers and worked examples for software_engineering subcategories. Loaded ONLY by the subcategory-only backfill lane (build_subcategory_prompt) and the eval pre-labeller. NEVER loaded by the classify prompt, the judge prompt, classifier.md or judge.md — those get the compact section 1b inside SKILL.md instead. Kept in lockstep with SKILL.md's version.
version: v7
---

# Software-engineering subcategories — the full rubric

**Everything here is downstream of an already-made `software_engineering` verdict.**
Section 1 of SKILL.md has already returned `software_engineering`. **The arrow
never runs backwards:** nothing on this page can pull a row INTO
`software_engineering`, and emitting a subcategory on any other category is a
measured error, not a judgement call.

Emit **0-2 slugs, most specific first** (index 0 is the primary). **`[]` is a
legitimate and common answer** — roughly two in five SWE postings say nothing
about what kind of engineering the role actually is, and `[]` is far better than
a guess.

---

## The 17 slugs

| slug | the role's core deliverable |
|---|---|
| `ai_engineering` | Builds product features on top of a model it **did not train** — the model is a **dependency**, like a database. Prompting, RAG, agents, evals, LLM plumbing. |
| `backend` | Server-side code consumed by **the product's own users or client apps**: APIs, services, business logic, the request path. |
| `data_engineering` | The deliverable is **the movement and shaping of data** — pipelines, ETL/ELT, warehouses, streaming, data models. |
| `devops_sre` | The mandate is **keeping other teams shipping and running**: CI/CD, on-call, reliability, observability, incident response. |
| `embedded_systems` | Code compiled **against hardware or a kernel** — firmware, drivers, RTOS, bare metal, kernel/systems-level work. |
| `forward_deployed` | Writes **production code inside a NAMED customer's environment**. The customer is specific, and the deliverable is committed code, not a deck. |
| `frontend` | **Owns UI and does not also own the server**: web/desktop client code, design systems, browser rendering. |
| `full_stack` | **Explicitly owns BOTH** halves. **EXCLUSIVE** — see the tie-breakers. |
| `growth_engineering` | Ships **production code whose success metric is acquisition, activation, retention or monetization** — experimentation platforms *used to run experiments*, onboarding/signup funnels, referral and invite systems, paywalls and pricing surfaces, lifecycle-messaging infrastructure. |
| `infrastructure_platform` | The **consumers are other engineers or services**: internal platforms, developer tooling, cloud/distributed infrastructure, storage/compute primitives. The largest bucket — **but NOT a catch-all.** |
| `ml_engineering` | **Changes weights**, or builds the systems that **produce and serve** them. Success is measured by **a model metric**. |
| `mobile` | The deliverable is **an app binary** — iOS, Android, React Native, mobile SDKs. |
| `product_engineering` | Owns a **named user-facing surface end-to-end** and has say over **what** gets built, not just how — works from a problem statement rather than a spec, makes scope and UX calls alongside (or in place of) a PM/designer. |
| `qa_testing` | The subject matter is **test coverage or test infrastructure itself** — automation frameworks, QA engineering, test platforms. |
| `quantitative` | Correctness is measured in **money and microseconds** — trading systems, market data, execution, low-latency financial infrastructure. |
| `robotics_autonomy` | **Senses, plans, actuates** in the **physical world** — perception, motion planning, control, autonomy stacks, SLAM. |
| `security` | The **subject matter is security AND the deliverable is code** — appsec engineering, cryptography, security platforms, detection engineering. |

---

## The fourteen tie-breakers

1. **`infrastructure_platform` vs `devops_sre` — "build it or keep it running?"**
   Building the platform other engineers deploy onto → `infrastructure_platform`.
   Being accountable for it staying up (on-call, SLOs, incident response) →
   `devops_sre`.

2. **`robotics_autonomy` vs `embedded_systems` — "the problem you solve vs the
   layer you run at."** Perception/planning/control **is** the problem →
   `robotics_autonomy`, even when it runs on a microcontroller. Firmware,
   drivers and bring-up **are** the deliverable → `embedded_systems`, even on a
   robot.

3. **`backend` vs `infrastructure_platform` — "who consumes your code?"**
   *Product's users / client apps* → `backend`. *Other engineers or services* →
   `infrastructure_platform`.
   * "Software Engineer, Payments API" → **`backend`**
   * "SDE, AWS OpenSearch" → **`infrastructure_platform`**

4. **`data_engineering` vs `backend` — "pipeline or request-serving?"**
   A batch/stream job whose output is a table → `data_engineering`. A service
   answering requests → `backend`. A row that does both, primary first.

5. ⚠ **`qa_testing` vs `embedded_systems` — "validation" is a TRAP.**
   `qa_testing` means **software testing** — test frameworks, automation, QA
   platforms. Hardware/silicon *validation* is engineering against hardware.
   * "Silicon Validation Software Engineer — GPU IP" → **`embedded_systems`**,
     not `qa_testing`.

6. **`full_stack` only on an EXPLICIT signal — never defaulted.** Emit it only
   when the posting says the role owns both client and server. It is
   **exclusive**: never emit it beside `frontend` or `backend`. A row that says
   only "you'll touch the whole stack sometimes" is `backend` or `frontend` or
   `[]`, whichever the evidence supports.

7. **`ai_engineering` vs `ml_engineering` — "do you change the weights?"**
   Training, fine-tuning, building the training/serving stack, optimising a model
   metric → `ml_engineering`. Consuming somebody else's model through an API,
   prompting, RAG, agents, evals → `ai_engineering`.

8. ⚠ **NEVER route on an AI mention.** "AI-first company", "AI/ML org", "using
   AI to…" in a title or boilerplate says **nothing** about what the person
   ships. Route on the deliverable or emit `[]`.

9. **`quantitative` keys on the DOMAIN, not the word "quant".** Trading,
   market data, execution, exchange connectivity, latency-critical financial
   systems → `quantitative`. A "Quantitative UX Researcher" is not this (and is
   not `software_engineering` at all).

10. **Tags precedence.** When the title is silent, the enrichment's own `tags`
    are the next-best signal — but they are weaker evidence than the title, so
    a tags-only match should carry lower confidence. When title and tags
    disagree, the **title wins**.

11. ⚠ **`growth_engineering` vs the `growth` CATEGORY — "code, or a campaign?"**
    There is a TOP-LEVEL `growth` category for marketing, demand gen, paid /
    performance, lifecycle / CRM, SEO / content and PMM. **A row whose
    deliverable is a campaign or a channel is category `growth` and never
    reaches this page at all** — the arrow never runs backwards, so nothing here
    can pull it into `software_engineering`. `growth_engineering` exists only
    for a row section 1 has ALREADY called `software_engineering`: the person
    **commits production code**, and the number that judges the code is a growth
    number.
    * "Growth Marketing Manager", "Lifecycle Marketing Lead", "SEO Manager" →
      category **`growth`**, no subcategory.
    * "Growth Engineer — own our signup funnel and its conversion rate" →
      `software_engineering` + **`["growth_engineering"]`**.
    * A "Growth Engineer" who actually runs ad accounts, builds email sends
      inside a CRM and writes no committed code → category **`growth`**.

    This is the **same trap** as *Solutions / Sales Engineer → `business_ops`*
    (SKILL.md section 1): a title with "Engineer" in it does not make the row
    `software_engineering`. Decide the CATEGORY on the deliverable first; only
    then does this slug become reachable.

12. **`growth_engineering` vs `frontend` / `full_stack` — the METRIC, not the
    layer.** Growth engineers write client code and server code; so does
    everybody else, so the layer decides nothing. The signal is whether the
    posting hands the role **a growth metric to move**: signup or checkout
    conversion, activation, onboarding completion, retention / churn, referral
    K-factor, trial-to-paid, LTV, "run A/B tests" as the job.
    * "Frontend Engineer, Onboarding" (build the screens, no metric mandate) →
      **`frontend`**.
    * "Full Stack Engineer, Growth — raise trial-to-paid conversion" →
      **`["growth_engineering", "full_stack"]`**.
    * A bare "Growth Engineer" with no metric named and no channel named is
      still `growth_engineering` — the title IS the explicit signal.

13. **`growth_engineering` vs `infrastructure_platform` — "run the experiments
    or build the experiment platform?"** The same "who consumes your code?" cut
    as tie-breaker 3. Building the A/B framework **other teams deploy onto**,
    consumers are engineers → `infrastructure_platform`. **Running** experiments
    on the product to move a growth number → `growth_engineering`.

14. ⚠ **`product_engineering` vs `full_stack` — LAYERS vs the DECISION.**
    `full_stack` answers **"which layers do you own?"** — a structural fact
    about the code surface, and it needs an explicit both-halves signal
    (tie-breaker 6). `product_engineering` answers **"who decides what gets
    built?"** — the role owns a **named user-facing surface** and has real say
    over scope and UX, working from a problem statement rather than a ticket,
    typically beside a PM/designer as a peer or with no PM at all.

    Four rules that make the cut decidable:
    * **An explicit "full stack" in the title IS `full_stack`.** Explicit
      signals win, exactly as in leveling. Do not talk yourself out of it.
    * **They can co-occur** (0-2 slots allow it). Primary is whichever the
      **title** names; when the title names both, `product_engineering` leads —
      it is the narrower claim.
    * ⚠ **Ownership boilerplate is NOT the signal.** "high agency", "extreme
      ownership", "wear many hats", "0→1", "end-to-end", "move fast", "thrive in
      ambiguity", "talk to users" — **startup postings are written that way by
      default**, the same way they are written to sound maximally senior (SKILL.md's
      explicit-signal-or-`mid` rule). Without a named surface AND say over what
      ships, the answer is `full_stack`, `backend`, `frontend` or `[]`.
    * **`product_engineering` is not a catch-all**, any more than
      `infrastructure_platform` is. A bare "Software Engineer" at a product
      company is `[]`.

    Worked:

    * "Full Stack Engineer (React + Rails)" → **`["full_stack"]`**. Layers only.
    * "Product Engineer — own Billing end-to-end, you decide what we ship" →
      **`["product_engineering"]`**.
    * "Full Stack Product Engineer, Search" → **`["product_engineering",
      "full_stack"]`**. Title names both; the narrower claim leads.
    * "Software Engineer — high ownership, wear many hats, ship fast" → **`[]`**.

---

## Worked examples

1. **"Software Engineer, Payments API"** → `["backend"]`. The consumers are the
   product's own clients.
2. **"SDE II, AWS OpenSearch"** → `["infrastructure_platform"]`. The consumers
   are other engineers and services.
3. **"Software Engineer (Core Infrastructure)"** → `["infrastructure_platform",
   "backend"]`. Two slugs, primary first.
4. **"Silicon Validation Software Engineer — GPU IP"** →
   `["embedded_systems"]`. "Validation" is not `qa_testing` here.
5. **"Senior Site Reliability Engineer, Checkout"** → `["devops_sre"]`. The
   mandate is keeping it up, not building it.
6. **"Machine Learning Engineer, Ranking Platform"** → `["ml_engineering"]`.
   Success is a model metric and the role owns training/serving.
7. **"Software Engineer, LLM Applications"** → `["ai_engineering"]`. The model
   is a dependency; the deliverable is the product feature around it.
8. **"Software Engineer Intern (AI/ML)"** → `[]`. The title names an AI/ML org
   but says nothing about what the intern SHIPS. **Never route on an AI mention.**
9. **"Growth Engineer, Activation"** → `["growth_engineering"]`. Committed code,
   judged by an activation number.
10. **"Growth Marketing Manager, Paid Acquisition"** → category **`growth`**, no
    subcategory. The deliverable is a channel, not code — it never reaches this
    page.
11. **"Full Stack Engineer, Growth — raise trial-to-paid conversion"** →
    `["growth_engineering", "full_stack"]`. The metric is the primary claim; the
    layers are secondary.
12. **"Software Engineer, Experimentation Platform"** →
    `["infrastructure_platform"]`. The consumers are other engineering teams, not
    the funnel.
13. **"Product Engineer — own Billing end-to-end, you decide what we ship"** →
    `["product_engineering"]`. A named surface plus authority over scope.
14. **"Full Stack Product Engineer, Search"** → `["product_engineering",
    "full_stack"]`. Both are explicit; the narrower claim leads.
15. **"Software Engineer — high agency, wear many hats, thrive in ambiguity"** →
    `[]`. **Ownership boilerplate is not a product-engineering signal**, the same
    way intensity language is not a seniority signal.

---

## Quick canonical mappings

"Backend/Server Engineer" → `backend` · "Frontend/Web/UI Engineer" → `frontend` ·
"Full Stack Engineer" (explicit) → `full_stack` (alone) · "Data
Engineer"/"Analytics Engineer" → `data_engineering` · "ML Engineer"/"MLOps" →
`ml_engineering` · "LLM/GenAI/Applied AI Engineer" → `ai_engineering` ·
"Platform/Infrastructure/Cloud Engineer" → `infrastructure_platform` ·
"SRE"/"DevOps"/"Production Engineer" → `devops_sre` · "iOS/Android/Mobile
Engineer" → `mobile` · "Firmware/Kernel/Driver/Embedded SW Engineer" →
`embedded_systems` · "Robotics/Perception/Autonomy/Controls Engineer" →
`robotics_autonomy` · "Security/AppSec/Cryptography Engineer" → `security` ·
"QA/Test Automation/SDET" → `qa_testing` · "Quant Dev"/"Trading Systems
Engineer"/"Low-Latency Engineer" → `quantitative` · "Forward Deployed Engineer"
(named customer, ships code) → `forward_deployed` · "Growth Engineer"/"Growth
Software Engineer"/"Engineer, Acquisition|Activation|Monetization|Funnel" →
`growth_engineering` · "Product Engineer"/"Engineer, Product" (named surface,
owns what ships) → `product_engineering` · bare **"Software Engineer"**
with no specialty signal → **`[]`**.

Two mappings that deliberately do NOT land here: "Growth Marketing/Performance
Marketing/Lifecycle/SEO Manager" → category **`growth`**, and "Growth PM" →
category **`product_manager`**. Neither writes the code, so neither reaches this
page.
