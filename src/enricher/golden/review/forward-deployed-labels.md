# Forward-deployed golden rows — label review (2026-11-25)

Real prod postings, fetched read-only from the public job-detail endpoint, labelled under the rule agreed for this PR:

- A **Forward Deployed / Deployed Engineer** title defaults to **Software Engineering + `forward_deployed`**, even when the role is customer-facing. The body vetoes only a **non-engineer hire** (domain experts, or selling/strategy with no hands-on building).
- **Look-alikes stay out of SWE**: Strategist, TPM / Program Lead, Engagement Manager, Recruiter, Product Analyst, Strategy & Ops.
- **FDE managers** follow the Engineering Manager rule (SWE + `manager`); **Forward Deployed Architect** is decided by the body.

`prod` is what the enricher wrote under the old rubric. Rows marked ⚠ are the borderline calls.

## New rows (28)

| # | Company | Title | prod | proposed | level | why |
|---|---|---|---|---|---|---|
| 1 | braintrust | Forward Deployed Engineer | Business Ops / senior | **SWE** + forward_deployed | mid | Post-sales FDE, but pair-programs with customer engineers and requires Python/TypeScript: an engineer role, so the default holds. '4+ years' brackets to mid (prod said senior). |
| 2 | cognition | Forward Deployed Engineer - Doha | Business Ops / mid | **SWE** + forward_deployed | mid | Deploys Devin/Windsurf into customer production environments and supports integrations; no YOE stated. |
| 3 | exa | Forward Deployed Engineer, NYC | Business Ops / mid | **SWE** + forward_deployed | mid | Takes customers from contract to production integration; 'when a feature is missing, you build it'. No YOE stated. |
| 4 | typesafe-ai | Forward Deployed Engineer | Business Ops / mid | **SWE** + forward_deployed | mid | 'Strong, hands-on engineers' who build with the product, prototype demos and write evaluation scripts; no YOE stated. |
| 5 | databricks | Sr. Forward Deployed Engineer - Public Sector | Business Ops / senior | **SWE** + forward_deployed | senior | Builds and productionizes data/AI systems for federal customers; 'Sr.' + 6+ years. |
| 6 | cloudflare | Forward Deployed Engineer, Professional Services | Business Ops / senior | **SWE** + forward_deployed | senior | Professional-services FDE, but asks for hands-on coding (Workers, Terraform IaC) in customer environments; body calls it a 'senior technical expert'. |
| 7 | salesforce | Forward Deployed Engineer | Business Ops / mid | **SWE** + forward_deployed | mid | Title-only (Workday stores no description): an FDE title with nothing to veto it -> SWE, mid by default. |
| 8 | cisco | Forward Deployed Engineer | Business Ops / mid | **SWE** + forward_deployed | mid | Title-only (Workday stores no description): FDE title, no veto -> SWE, mid by default. |
| 9 | google | Forward Deployed Engineer, Generative AI, Geo | Business Ops / mid | **SWE** + forward_deployed | mid | ⚠ Google gTech boilerplate, but the role is 'a specialized engineering role' doing white-glove deployment of geospatial AI systems and building tools. Borderline: pure gTech TSC would be business_ops. |
| 10 | google | Forward Deployed Engineer, DeepMind | Business Ops / mid | **SWE** + forward_deployed | mid | Collaborative engineering, joint benchmarking and evals with Gemini customers; short body, no YOE. |
| 11 | elevenlabs | Forward Deployed Engineer - Software Engineer - Singapore | Business Ops / mid | **SWE** + forward_deployed | mid | Title literally says 'Software Engineer'; no YOE. |
| 12 | flowengineering | Forward Deployed Engineer | Business Ops / mid | **SWE** + forward_deployed | mid | ⚠ Borderline: owns demos/POCs in the sales process, but requires 'strong software engineering fundamentals' (designing, testing, operating services). Not a non-engineer role, so the default holds. 3+ years -> mid. |
| 13 | nominal | Forward Deployed Engineer, AI - UK | Business Ops / senior | **SWE** + forward_deployed | mid | Embeds with hardware teams and builds agentic workflows on Nominal; '4+ years as a software engineer' -> mid (prod said senior). |
| 14 | salesforce | Summer 2027 Intern - Forward Deployed Engineer – Global Public Sector | Business Ops / intern | **SWE** + forward_deployed | intern | Title-only: 'Summer 2027 Intern - Forward Deployed Engineer' -> SWE intern. |
| 15 | exa | FDE Lead, NYC | Business Ops / manager | **SWE** + forward_deployed | manager | Leads a team of FDEs (player-coach, 'several years of programming experience'): FDE managers follow the Engineering Manager rule. |
| 16 | databricks | Senior Manager, AI Forward Deployed Engineering - London | Business Ops / manager | **SWE** + forward_deployed | manager | Manages the AI FDE team that builds and productionizes GenAI applications for customers. |
| 17 | cursor | Regional Director, Forward Deployed Engineering - Financial Services | Business Ops / manager | **SWE** + forward_deployed | manager | Directly manages FDEs 'who build and ship production software'; asks for professional Python/JS/TS experience. |
| 18 | harvey | Forward Deployed Finance Engineer, Real Estate | Business Ops / mid | **Business Ops** | mid | ⚠ BODY VETO: 'Forward Deployed Finance Engineers ... are former acquisitions and real estate credit professionals'; Python/SQL only 'a plus'. A domain-expert GTM role under an Engineer title. |
| 19 | cursor | Forward Deployed Strategist | Business Ops / senior | **Business Ops** | senior | Strategist: owns executive engagement and the configuration layer, 'partnering with FDEs on deeper production work'. 6+ years -> senior. |
| 20 | palantir | Deployment Strategist - US Government | Business Ops / mid | **Business Ops** | mid | Palantir Deployment Strategist: works alongside Engineers; strategist, not engineer. |
| 21 | palantir | Deployment Strategist, New Grad - Intel, US Government | Business Ops / new_grad | **Business Ops** | new_grad | Same strategist body as the US Government req; 'New Grad' in the title. |
| 22 | databricks | Senior Engagement Manager, Forward Deployed Engineering | Business Ops / senior | **Business Ops** | senior | Engagement manager inside the FDE org: sells PS&T programs and manages delivery; 'Senior' title. |
| 23 | baseten | Technical Program Manager, Forward Deployed Engineering | Business Ops / senior | **Business Ops** | senior | TPM for the FDE team: account cadences, cross-team programs, metrics. 5+ years -> senior. |
| 24 | elevenlabs | Technical Recruiter (FDE), LATAM | Business Ops / mid | **Business Ops** | mid | Recruiter hiring FDEs. |
| 25 | gradial | Forward Deployed Product Analyst | Business Ops / mid | **Business Ops** | mid | Product analyst: configures workflows, QA, documentation and playbooks for deployments; no production code. |
| 26 | notion | Forward Deployed Architect | Business Ops / senior | **Business Ops** | senior | Architect decided by body: designs Notion workspaces/workflows on the Services (Sales) team and hands deeper engineering to FDE. 5+ years -> senior. |
| 27 | mistral-ai | Senior AI Deployment Strategist | Business Ops / senior | **Business Ops** | senior | Deployment strategist spanning presales and postsales advisory; 'Senior' + 8+ years. |
| 28 | openai | Forward Deployment Strategy and Operations | Business Ops / senior | **Business Ops** | senior | Strategy & operations for the forward-deployed business: GTM strategy, revenue/staffing models. 'Senior operator'. |

## Corrections to existing draft rows (8)

| # | Company | Title | was | proposed | level | why |
|---|---|---|---|---|---|---|
| 1 | openai | Forward Deployed Software Engineer - Munich | Business Ops / mid | **SWE** + forward_deployed | mid | Was business_ops while the identical SF req (00207abc) was SWE. Same FDSE role -> SWE. |
| 2 | cohere | Forward Deployed Engineer, Agentic Platform (Korea) | Business Ops / mid | **SWE** + forward_deployed | senior | Was business_ops. Designs, builds and deploys LLM agents; 'looking for senior software engineers' -> senior. |
| 3 | sierra | Forward Deployed Infrastructure Engineer | Business Ops / mid | **SWE** + forward_deployed | mid | Was business_ops. Architects, deploys and operates Sierra's platform in customer environments; 4+ years -> mid. |
| 4 | palantir | Forward Deployed Enablement Engineer - Customer Success | Business Ops / mid | **SWE** + forward_deployed | mid | ⚠ Was business_ops. Borderline: support-heavy, but also develops tooling and infrastructure and debugs customers' technical issues; no non-engineer veto. |
| 5 | openai | Forward Deployed Engineer - Munich | SWE / senior | **SWE** + forward_deployed | mid | Level fix: was senior with no level word or YOE; same FDE template as the SF req (mid). |
| 6 | openai | Forward Deployed Software Engineer - SF | SWE / mid | **SWE** + forward_deployed | mid | Unchanged category/level; adds forward_deployed subcategory. |
| 7 | palantir | Forward Deployed Software Engineer, New Grad - Commercial | SWE / new_grad | **SWE** + forward_deployed | new_grad | Unchanged category/level; adds forward_deployed subcategory. |
| 8 | clear | Forward Deployed AI Engineer II | SWE / mid | **SWE** + forward_deployed | mid | Unchanged category/level ('II', 4+ years); adds forward_deployed subcategory. |

**Approved as listed in review on 2026-11-25** (no borderline call flipped). Every row above is now `label_source: human`, and every SWE row also carries `subcategories: ["forward_deployed"]` with `gold_subcategory_provenance: human`, so they count toward the regression gate. Tags were proposed for the new rows and kept as-is on the corrected rows; new rows carry `locations: null`, so they are not scored on location. Each row's deciding line is also stored on the row itself as `label_note`.
