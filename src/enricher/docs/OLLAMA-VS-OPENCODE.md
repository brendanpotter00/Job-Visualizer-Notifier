# Local transport comparison — ollama vs opencode (same Qwen3:32B)

**Date:** 2026-07-12 · **Harness:** `cli eval-run --engine {ollama,opencode} --judge off --human-only --batch 1`
(after the row-drop fix, PR #10) · **Ground truth:** 21 human-corrected golden rows · **Status:** ADVISORY
(n=21 < the gate's 50-row floor).

Both engines run the **same model (`qwen3:32b`) and the same prompt** — the only variable is the transport:
`ollama` talks HTTP to `/api/chat`; `opencode` shells out to the OpenCode CLI harness. This isolates two
questions: does the local row-drop fix hold through **both** transports, and does the transport choice change
quality or latency? (Companion to `ENGINE-COMPARISON.md`, which pits Claude vs local Qwen.)

## TL;DR

**Accuracy is a dead tie; `ollama` wins on speed.** After the fix both engines drop **0/21** and land identical
accuracy (category 16/21, level 15/21 — they agree on 19/21 categories, unsurprising for the same model+prompt).
`ollama` is **~3.2× faster** (92s vs 292s median/row); `opencode`'s CLI harness adds large per-call overhead for
**zero** accuracy benefit. **Use `ollama` for local inference** unless you specifically want OpenCode's agent
tooling in the loop.

| Metric | ollama | opencode |
|---|---|---|
| drops | 0/21 | 0/21 |
| category exact | 16/21 (76%) | 16/21 (76%) |
| level exact | 15/21 (71%) | 15/21 (71%) |
| level filter-consistent | 15/21 (71%) | 15/21 (71%) |
| classify latency mean/median (s) | 108 / 92 | 291 / 292 |

Engine agreement: category **19/21**, level **17/21**. Both dropped **0** rows — the fix is transport-agnostic
(both call the identical shared `ChunkEngine._call_with_repair`; only `_call` differs).

## Per-row rationale (human label | ollama cat/level + reasoning | opencode cat/level + reasoning)

### `ashby_api/60226f73-954c-421c-b609-c377255b062e` — Forward Deployed Engineering Manager
- **human:** software_engineering/manager
- **ollama** [✓✓]: software_engineering/manager — Category is software_engineering because it's an Engineering Manager role for a software team. Level is manager due to explicit 'Engineering Manager' in the title and management responsibilities in the description (customer relationship, team collaboration, technical support). Location is San Francisco, CA, USA as indicated in the 'Why Join' section mentioning SF.
- **opencode** [✓✓]: software_engineering/manager — Title explicitly states 'Engineering Manager' (category=software_engineering, level=manager). Responsibilities include managing customer relationships, onboarding, and technical support for a software platform. Location resolved to San Francisco based on company description.

### `ashby_api/658fb613-3dcc-4932-9927-dadbf83f95cd` — Ex-Founder
- **human:** software_engineering/mid
- **ollama** [✗cat✓]: growth/mid — The role emphasizes growth hacking, scaling userbases, and product-building for a voice assistant platform, aligning with the 'growth' category. No explicit seniority signals (title/years) exist, so level defaults to 'mid' per the explicit-signal-or-mid rule. Tags reflect technical stack (TypeScript/React/Python) and growth/product focus.
- **opencode** [✗cat✓]: product_manager/mid — Role requires product direction ownership (building new features/product lines or scaling userbase) aligning with product_manager. No explicit level signals in title/body - defaults to mid despite founder experience requirement (no stated years or seniority terms like 'Senior').

### `ashby_api/7724fbe3-6a27-4418-9705-2dcc40751a16` — Software Engineer (Agent Platform)
- **human:** software_engineering/mid
- **ollama** [✓✓]: software_engineering/mid — Category is software_engineering due to building developer tools and AI-driven frameworks. Level is mid by default (explicit-signal-or-mid rule) despite high-agency language in description; no explicit seniority/YOE signals in title or requirements.
- **opencode** [✓✓]: software_engineering/mid — Category: 'Software Engineer' building developer tools and AI agents aligns with software_engineering. Level: No seniority qualifiers in title/body, no YOE stated, so default to mid per explicit-signal-or-mid rule. Title sounds senior but lacks concrete signals like 'Senior' or 5+ YOE requirements.

### `ashby_api/84702c3a-3ef0-4ae7-8561-e6be5855dee9` — Founding Marketer
- **human:** growth/mid
- **ollama** [✓✓]: growth/mid — The role is a founding marketer position focused on product launches, content creation, and growth strategies, aligning with the 'growth' category. The level defaults to 'mid' due to no explicit seniority signals or years-of-experience requirements in the title or description. The location 'Weave HQ' is unresolved without additional context, lowering confidence.
- **opencode** [✓✓]: growth/mid — Category is 'growth' due to focus on product launches, content creation, and growth strategies typical of a product marketer. Level defaults to 'mid' as no explicit seniority or years-of-experience signals are present. Location 'Weave HQ' resolved to Lehi, Utah (known from prior context) with moderate confidence.

### `ashby_api/8a4dae00-8b1a-4440-9c9f-38ca3ce135f5` — General Application
- **human:** software_engineering/mid
- **ollama** [✓✓]: software_engineering/mid — The job description emphasizes product development with technical principles and high-quality coding, aligning with software_engineering. The title lacks seniority indicators, and no years-of-experience are specified, defaulting to mid level per the explicit-signal-or-mid rule.
- **opencode** [✓✓]: software_engineering/mid — Company emphasizes creating products grounded in technical principles with future-focused coding, small teams, and practical tooling — fits software_engineering category. Title lacks explicit level signals (no 'Senior'/'New Grad'), and description provides no years-of-experience requirements, so default to mid level under explicit-signal-or-mid rule.

### `ashby_api/a438f51d-cbca-4751-88c3-5de326833bba` — Senior Software Engineer - Internal Observability
- **human:** software_engineering/senior
- **ollama** [✓✓]: software_engineering/senior — Category: Title 'Senior Software Engineer' and description focus on building telemetry pipelines, distributed systems, and AI-driven observability align with software_engineering. Level: 'Senior' in title and '7+ years of experience' requirement explicitly qualify as senior tier.
- **opencode** [✓✓]: software_engineering/senior — Title explicitly states "Senior Software Engineer" with 7+ years experience requirement. Responsibilities focus on building telemetry pipelines and AI-driven observability systems (software engineering core deliverable). Tags derived from telemetry focus, distributed systems work, and programming languages mentioned.

### `ashby_api/b86c907c-5054-401a-bf42-3f61eef6393f` — Founding Support Engineer
- **human:** business_ops/mid
- **ollama** [✓✓]: business_ops/mid — The role is a Support Engineer focused on customer issues and technical support, which falls under business_ops. The title lacks explicit seniority signals and no years-of-experience requirements are stated, so level defaults to mid. Key signals: 'first point of contact for customers', 'diagnose and reproduce', and 'own the post-incident experience' indicate support/customer success function rather than software development.
- **opencode** [✓✓]: business_ops/mid — Category selected as business_ops since this is a customer-facing support role for engineering products. Level defaults to mid per the explicit-signal-or-mid rule - while 'founding' implies significance, there are no explicit seniority indicators in the title or stated YOE requirements. Location normalized to Lehi, UT based on prior correction in taxonomy examples where 'Weave HQ' resolves to Lehi with 0.7 confidence.

### `ashby_api/bcbf0fb9-2405-497b-bbc9-e09d8f7a4963` — Software Engineer (Core Infrastructure)
- **human:** software_engineering/mid
- **ollama** [✓✓]: software_engineering/mid — Category is software_engineering due to focus on building distributed systems infrastructure with Go/Kubernetes. Level is mid because title lacks explicit seniority markers and no years-of-experience requirements are stated (explicit-signal-or-mid rule). Startup language about 'high agency' and 'ownership' does not override this.
- **opencode** [✓✓]: software_engineering/mid — Title 'Software Engineer' clearly maps to software_engineering category. No explicit level/years specified, so default to mid per explicit-signal-or-mid rule. Description emphasizes distributed systems and high agency but lacks concrete seniority signals (0.6 confidence due to startup intensity language).

### `greenhouse_api/4884398101` — Information Security Engineer
- **human:** software_engineering/mid
- **ollama** [✓✓]: software_engineering/mid — Category is software_engineering because the role centers on building/maintaining security infrastructure (EDR, SIEM, SOAR, automation workflows) — a security engineer's core deliverable is software/systems engineering. Level is mid due to explicit '3+ years of hands-on experience in enterprise IT' requirement, which maps to the mid tier's ~2–5 years range. Title lacks seniority qualifiers like 'Senior' but experience requirement overrides that.
- **opencode** [✓✓]: software_engineering/mid — Title 'Information Security Engineer' with responsibilities around building/maintaining SOC infrastructure (EDR, SIEM, SOAR, automation) aligns with software_engineering per taxonomy's 'builds pipelines/security systems' rule. Requires 3+ years of hands-on SOC experience and 'enterprise IT environment' - mid level by experience requirement. Mention of automation, AI tooling, and security controls supports tags.

### `greenhouse_api/5182374007` — Facilities Infrastructure Engineer (Data Center Infrastructure)
- **human:** hardware_engineer/entry
- **ollama** [✓✗lvl]: hardware_engineer/mid — Category: hardware_engineer because the role focuses on physical infrastructure (MEP engineering, HVAC, electrical systems) for data centers. Level: mid as the title lacks explicit seniority indicators and no years-of-experience requirements are specified, defaulting to mid per the explicit-signal-or-mid rule.
- **opencode** [✓✗lvl]: hardware_engineer/mid — Category: Role involves designing/maintaining physical data center infrastructure (HVAC, electrical systems, MEP engineering) aligning with hardware_engineer. Level: Title lacks explicit seniority signals (no 'Senior/Staff/Intern') and no stated YOE, so default to mid per explicit-signal-or-mid rule. Tags reflect infrastructure focus and technical domains.

### `greenhouse_api/7851742` — Escalation Manager, Event Response Team
- **human:** business_ops/manager
- **ollama** [✓✗lvl]: business_ops/mid — The role focuses on operational incident management, cross-functional coordination, and safety-critical decision-making, aligning with `business_ops`. The title lacks explicit seniority signals (e.g., 'Senior' or years-of-experience requirements), so `level=mid` per the explicit-signal-or-mid rule. The 'Manager' in the title refers to incident leadership, not people management, which would require `level=manager`.
- **opencode** [✓✗lvl]: business_ops/senior — Category: The role focuses on operational safety leadership and incident management, which aligns with `business_ops` operations management. Level: Title contains 'Manager' with clear senior responsibility for safety decisions and cross-functional coordination, but lacks explicit 'Senior'/'Staff' tier markers in title – defaulting to 'senior' based on decision weight. Confidence reflects clear category signal but cautious tier assignment.

### `greenhouse_api/7917304` — Strategic Account Executive 4 - ISV
- **human:** business_ops/senior
- **ollama** [✓✓]: business_ops/senior — The role is a Strategic Account Executive focused on sales and revenue growth for ISV customers, which falls under `business_ops`. The level is `senior` due to the explicit requirement of 8+ years of sales experience (exceeding the ~5+ years threshold for senior tier).
- **opencode** [✓✓]: business_ops/senior — Category: Sales/account management responsibilities for ISV customers under 'business_ops'. Level: Requires 8+ years of sales experience with 3+ years in major account sales, meeting 'senior' tier's ~5+ years requirement.

### `greenhouse_api/7948401` — Service Technician, Service Operations, Labs
- **human:** business_ops/entry
- **ollama** [✗cat✗lvl]: hardware_engineer/mid — Category: Role focuses on hardware maintenance/repair of robots and electric bicycles (physical systems) -> hardware_engineer. Level: '1+ year of service work experience' requirement and 'standard/intermediate' tasks with no explicit seniority in title -> mid (default for no explicit signals).
- **opencode** [✗cat✓]: hardware_engineer/entry — Category: hardware_engineer because the role involves physical hardware maintenance (robots, electric bicycles, control units). Level: entry due to '1+ year of service work experience' requirement and progression path from basic to complex repairs under senior guidance.

### `greenhouse_api/7968269` — Principal, Marketing Architecture & Strategy
- **human:** business_ops/senior_plus
- **ollama** [✗cat✓]: product_manager/senior_plus — The role owns strategic marketing technology vision and bridges marketing with technical execution, aligning with `product_manager`. The 'Principal' title and senior leadership responsibilities (shaping architecture, influencing cross-functional teams) map to `senior_plus`.
- **opencode** [✗cat✓]: growth/senior_plus — Title 'Principal' signals senior_plus level. Role owns marketing technology architecture strategy, bridges marketing/technical teams, and drives innovation – all align with 'growth' category (marketing & strategy leadership). Responsibilities emphasize cross-functional technical leadership and system design for marketing, not product engineering or data science.

### `greenhouse_api/7980740` — Product Manager L3
- **human:** product_manager/senior_plus
- **ollama** [✓✗lvl]: product_manager/senior — The title 'Product Manager L3' and the description's mention of 'Staff Product Manager' indicate a senior-level role focused on product direction and roadmap. The 'L3' in the title aligns with seniority, and the responsibilities involve cross-functional execution and strategic planning, typical of a senior product manager. The remote location is specified as British Columbia, Canada.
- **opencode** [✓✗lvl]: product_manager/mid — The title 'Product Manager' directly maps to the product_manager category. The 'L3' designation in the title is not an explicit seniority signal per the rubric's level taxonomy. With no stated years of experience or seniority keywords like 'Senior' or 'Staff', the default 'mid' level applies. Responsibilities involve cross-functional execution and platform orchestration rather than people management, which would trigger the 'manager' level.

### `greenhouse_api/8007449` — Senior/Staff Applied Research Software Engineer
- **human:** software_engineering/senior
- **ollama** [✓✗lvl]: software_engineering/senior_plus — The role is a Senior/Staff Applied Research Software Engineer, building software solutions and prototypes with AI/ML, aligning with software_engineering. The title explicitly includes 'Staff', which maps to 'senior_plus' level per the taxonomy.
- **opencode** [✓✗lvl]: software_engineering/senior_plus — Title includes 'Senior/Staff' which maps to 'senior_plus' level. Responsibilities focus on full-stack development, prototyping, and AI/Machine Learning, aligning with software_engineering category. Remote location specified as India.

### `greenhouse_api/8024642` — Sr. Global Event Manager, Event Content Strategy and Production
- **human:** growth/senior
- **ollama** [✗cat✓]: business_ops/senior — Category: Business operations covers event management/production roles outside software/data science. Level: 'Sr.' in title explicitly indicates senior tier. Tags derived from content strategy, production readiness, and cross-functional partnership responsibilities.
- **opencode** [✗cat✓]: business_ops/senior — Category: business_ops (event management/operations falls under business operations). Level: senior (explicit 'Sr.' in title with leadership responsibilities over flagship events). Key signals: 'Sr. Global Event Manager', 'lead event content strategy', 'high-visibility programs', 'executive stakeholders'.

### `microsoft_scraper/1970393556641257` — Member of Technical Staff - AI Product - Backend Engineer
- **human:** software_engineering/mid
- **ollama** [✓✓]: software_engineering/mid — Category is software_engineering due to backend development responsibilities for Copilot APIs and mobile integration. Level is mid as the title lacks explicit seniority terms, and the 4+ year experience requirement aligns with mid-tier (2-5 years).
- **opencode** [✓✓]: software_engineering/mid — Category: core software development building APIs for Copilot iOS/Android apps. Level: 4+ years experience required (mid-tier) with no explicit seniority marker like 'Senior' in title. Title 'Member of Technical Staff' aligns with mid-level engineering ladder at Microsoft.

### `microsoft_scraper/1970393556868374` — Principal Quantum Engineer
- **human:** hardware_engineer/senior_plus
- **ollama** [✗cat✓]: software_engineering/senior_plus — The 'Principal Quantum Engineer' title and responsibilities (technical leadership, simulation pipeline development, cross-organization influence) align with `senior_plus` in `software_engineering` due to the focus on building quantum computing systems and infrastructure. The explicit 'Principal' in the title and the system-building mandate (not pure research) justify the category and level.
- **opencode** [✗cat✓]: software_engineering/senior_plus — Category: Software engineering (building scalable quantum systems and simulation pipelines). Level: Senior_plus (Principal-level role with technical leadership, cross-organization influence, and ownership of simulation roadmaps). Title includes 'Principal', and responsibilities emphasize architecture, strategic guidance, and high-throughput HPC tooling.

### `microsoft_scraper/1970393556874926` — Software Engineer II & Senior Software Engineer
- **human:** software_engineering/mid
- **ollama** [✓✓]: software_engineering/mid — The title explicitly states 'Software Engineer II', which maps to 'mid' level per the taxonomy. Responsibilities focus on building backend services/data pipelines for security infrastructure, clearly aligning with 'software_engineering' category. The 'II' in the title overrides any ambiguity from the dual 'Senior' label in the same title.
- **opencode** [✓✗lvl]: software_engineering/senior — Title explicitly says Senior Software Engineer (level senior). Responsibilities emphasize building backend services, data pipelines, and security infrastructure — core software engineering. Tags derived from "device/security signals","data pipelines","distributed systems". Location normalized from raw 'Redmond, Washington' with high confidence.

### `microsoft_scraper/1970393556874927` — Software Engineer II & Senior Software Engineer
- **human:** software_engineering/mid
- **ollama** [✓✗lvl]: software_engineering/senior — The role is clearly a software engineering position focused on building macOS security systems. The title explicitly includes 'Senior Software Engineer', which takes precedence over the 'II' designation and 2+ years experience requirement per the taxonomy's tie-breaker, setting the level to senior.
- **opencode** [✓✗lvl]: software_engineering/senior — The title explicitly states 'Senior Software Engineer', which directly maps to the 'senior' level. The category is 'software_engineering' due to the focus on building macOS security agent software with responsibilities for threat detection, system integration, and performance optimization. Tags emphasize backend systems development and security monitoring.

---

### Reproduce
```sh
ENGINE_TIMEOUT_SECONDS=600 uv run python -m job_enricher.cli eval-run --engine ollama   --judge off --human-only --batch 1
ENGINE_TIMEOUT_SECONDS=600 uv run python -m job_enricher.cli eval-run --engine opencode --judge off --human-only --batch 1
```
Predictions (with per-item latency + reasoning) are written to `golden/scorecards/predictions.<engine>.judge_off.json`.
