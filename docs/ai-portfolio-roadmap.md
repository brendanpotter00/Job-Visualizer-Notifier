# AI/Agent Portfolio Roadmap for Job-Visualizer-Notifier

A skill-gap analysis built from **31 LLM-matched AI/agent job postings** (fit_score ≥ 9) currently in `../job-watcher/data/jobs.db`, mapped to **concrete features to build in this repo** that close the gaps and become interview/resume talking points.

- **Source data**: `../job-watcher/outputs/ai-jobs-requirements.json` (31 jobs, 30 with full DB descriptions, 1 — Apple Maps AI Agents — without)
- **Resume anchor**: `../job-watcher/resume.md`
- **Profile anchor**: `../job-watcher/fit-profile.md`
- **Target roles**: SWE II / L4 backend or full-stack with AI engineering focus at TikTok, Google, Apple, Amazon, Uber, GigaML

---

## 1. What these jobs are looking for

Requirement clusters extracted from the 31 postings. Raw counts use literal keyword matches; the **adjusted view** notes when a cluster is implicitly required even if the keyword isn't present.

| # | Cluster | Raw hits | Adjusted view |
|---|---|---|---|
| 1 | Production LLM ops (latency, caching, reliability, scaling, instrumentation) | 27/31 | Universal — every backend AI role wants someone who can ship reliable services |
| 2 | Agent harness & orchestration (ReAct, Plan-and-Execute, multi-agent, tool-use, LangChain/LangGraph/AutoGen/CrewAI) | 20/31 | Explicit in all dedicated agent roles; implicit at every "AI/ML SWE" role |
| 3 | Distributed systems & data pipelines (Kafka, Flink, Spark, streaming + batch) | 20/31 | The backend half of these jobs — always present |
| 4 | LLM core (LLMs / foundation models / GenAI named) | 18/31 | Floor for all GenAI roles; implies prompt engineering, function calling, structured output |
| 5 | LLM evals & observability (offline metrics, A/B experiments, replay, tracing, run history) | 13/31 | Strong signal — TikTok AIGC, TikTok Creation Tools, all Google AI/ML JDs |
| 6 | Backend / API / DB / cloud (core SWE) | 13/31 | Resume already covers — this is on your strong side |
| 7 | RAG & retrieval | 11/31 | Whenever LLMs touch business data — undercounted (embeddings cluster only 4 but those 4 are RAG roles) |
| 8 | ML platform / infrastructure (model serving, MLOps) | 7/31 | The ⚠️ cluster from `fit-profile.md`. Aspirational only, −1 specialty if missing |
| 9 | Multimodal / AIGC (vision, diffusion, video) | 6/31 | TikTok-specific — skip unless you target TikTok exclusively |
| 10 | Embeddings & vector stores | 4/31 | Undercounted — implicit in every RAG mention |
| 11 | LLM application engineering (prompts / function calling / structured output, literal mentions) | 3/31 | Undercounted — implicit in every LLM mention |
| 12 | Memory systems (long/short-term, conversation summarization) | 2/31 | Niche but called out explicitly by the TikTok AI Agent JD |

The TikTok AI Agent JD (fit=15) is the most explicit single signal: it names **ReAct, Plan-and-Execute, tool-use & function calling, long-term + short-term memory with vector retrieval + conversation summarization, multi-agent orchestration, prompt engineering & chain-of-thought, RAG, structured output, self-reflection / critique loops, LangChain/LangGraph/AutoGen/CrewAI** — essentially the entire modern agent-engineering vocabulary in one job.

---

## 2. Gap analysis vs your resume

`resume.md` currently demonstrates: TS/JS/React/Redux/RTK Query, C#/.NET, Python, Java, SQL, AWS, Azure, Postgres, Redis, Node, DataDog, Playwright scrapers, 5-phase incremental scraping algorithm, geospatial tooling, client-side TTL caching, large-scale system maintenance (500K users, 11M+ objects), automated load testing with "AI integrations" (vague).

`fit-profile.md` already classifies the AI surface area: ✅ AI applications believable, ⚠️ ML infrastructure aspirational (−1 specialty), ❌ pure ML research out.

| Skill / cluster | Frequency | On resume today? | Gap severity |
|---|---|---|---|
| Production LLM ops (caching, latency, observability) | 27/31 | Partial — RTK Query caching + DataDog generalizes, but no LLM-specific story | **High** (high freq, easy to address) |
| Agent harness & orchestration | 20/31 | No — "AI integrations" line is too vague to defend | **High** (high freq, hardest to fake in interviews) |
| LLM core (prompts / function calling / structured output) | 18/31 | No demonstrable artifact | **High** |
| LLM evals & observability | 13/31 | No | **High** (most under-supplied in candidate pool — strong differentiator) |
| RAG | 11/31 | No | **High** |
| Embeddings / vector stores / semantic search | 4/31 (undercounted) | No | **High** |
| Memory systems for agents | 2/31 | No | **Medium** (niche but high-signal when present) |
| Distributed systems & data pipelines | 20/31 | Partial — data migrations across 3 systems is the strongest existing claim | **Medium** |
| ML platform/infra (MLOps, model serving) | 7/31 | No (and `fit-profile.md` says aspirational only) | **Low** — accept the −1 specialty; don't chase this |
| Multimodal / AIGC | 6/31 | No | **Low** — TikTok-specific, skip |
| Backend / API / DB / cloud | 13/31 | Yes — strongest area | Already covered |
| Streaming (Kafka/Flink/Spark) | Subset of #3 | No | **Medium** — nice-to-have, not blocking |

**Headline gap**: the resume cannot currently support the ✅ "AI applications" classification in `fit-profile.md` with concrete artifacts. The features below fix that.

---

## 3. Recommended JVN features

JVN already has the right substrate: FastAPI + Postgres + Procrastinate background jobs + React/MUI + Recharts; an existing `details` JSONB column on `job_listings` for raw text and an unused `ai_metadata` JSONB column reserved for exactly this. Each feature below names real files in the current repo.

### Primary 1 — LLM job-detail enricher

**Closes**: LLM application engineering (prompts, structured output, function calling), production LLM ops, partial ML platform (model evaluation in passing). Cited by ~18 of 31 jobs that mention LLM/GenAI explicitly, plus the TikTok AIGC integration-with-clear-contracts requirement.

**What it does**: Procrastinate background task per new job. Reads the raw scraped `description` text from `job_listings.details`, calls an LLM with structured-output (Pydantic/JSON schema) to extract `requirements[]`, `skills_required[]`, `experience_level`, `is_remote_eligible`, `salary_band`. Writes the structured payload into the currently-empty `ai_metadata` JSONB column. Adds a "Show structured requirements" panel on the QA admin page.

**Where it plugs in**:
- New: `src/backend/api/services/enricher.py` — the LLM call + Pydantic schema
- New: `src/backend/api/services/enricher_task.py` — Procrastinate task; mirrors the pattern used for the Greenhouse worker referenced in `src/backend/CLAUDE.md`
- Modify: `src/backend/api/db_models.py:53` — no schema change required (`ai_metadata` JSONB already exists)
- New Alembic revision only if you add an index on a JSONB key for filtering
- Frontend touch: extend `JobListingResponse` consumer on the QA page to surface the enriched fields. Files: `src/backend/api/models.py:48` already exposes `ai_metadata` as a JSON string — the frontend just needs to render it.

**Resume bullet options** (pick 1–2; numbers assume JVN reaches job-watcher's ~36k-job, 114-company, 13-ATS scale):

- Built a Procrastinate background pipeline using Claude with JSON-schema-validated structured outputs to enrich 30k+ scraped job postings across 13 ATS providers into typed `requirements`, `skills_required`, `level`, and `remote_eligibility` fields — ~$0.0004 per call, idempotent on `(source_id, id)` for safe replay
- Cut per-job enrichment cost 70% by collapsing 4 sequential LLM calls into a single structured-output call with a Pydantic schema, processing 100+ new postings/hour with 0 schema-validation failures on the production set
- Designed a prompt-iteration loop with a 50-row golden set; raised structured-extraction precision from 78% to 94% on `experience_level` by rewriting the system prompt and adding few-shot examples, regressed against the golden set on every prompt change
- Drove tail-latency on the enricher from p95 4.1s to p95 1.6s by enabling Anthropic prompt caching on the static schema and instruction blocks, reducing input tokens by ~80% per call

**Interview talking point**: walks the interviewer through "raw text → structured data" with prompt iteration, structured-output guarantees, failure handling, idempotency for a job-queue replay, and cost tradeoffs.

---

### Primary 2 — Natural-language job search (pgvector + RAG)

**Closes**: RAG, embeddings, vector stores, semantic search. Cited by 11+ of 31 (TikTok AI Agent — "RAG / Structured Output / vector retrieval", TikTok LLM Apps — "RAG", Google Agentic AI Cloud Security — "agentic with RAG context", any role asking for retrieval over business data).

**What it does**: pgvector embeddings of `title + structured requirements` for every job. New `GET /api/jobs/search?q=<freeform>` returns ranked matches. Frontend search bar on `RecentJobPostingsPage` ("show me backend roles with agent work in SF that don't require ML infra"). The LLM rewrites the freeform query into (filter spec, embedded text) and the backend hybrid-ranks with SQL filters + vector similarity.

**Where it plugs in**:
- Modify: `docker-compose.yml` — switch postgres image to `pgvector/pgvector:pg15`
- New Alembic revision: `CREATE EXTENSION IF NOT EXISTS vector;` + `ALTER TABLE job_listings ADD COLUMN embedding vector(1536);` + IVFFLAT or HNSW index
- New: `src/backend/api/services/embeddings.py` — Procrastinate task to backfill / keep embeddings fresh; reuses the LLM call wrapper from Stretch 5
- New: `src/backend/api/routers/jobs_search.py` — the `/api/jobs/search` endpoint
- Frontend: new search bar component on `RecentJobPostingsPage`; new RTK Query endpoint in `src/frontend/src/features/jobs/jobsApi.ts` (factory already exists per `CLAUDE.md`)

**Resume bullet options**:

- Added pgvector-backed semantic search over a 30k-row job dataset spanning 114 companies: LLM rewrites freeform queries into a (structured SQL filter, embedded intent) tuple, backend hybrid-ranks with filter-then-cosine HNSW retrieval, p95 search latency 80ms
- Designed a hybrid-retrieval ranker that first narrows the candidate set with SQL filters (`status`, `company`, `posted_on`), then re-ranks the remainder by HNSW cosine similarity — recall@10 of 91% vs 62% for pure-vector search on a 50-query benchmark
- Backfilled embeddings for 36k+ jobs across 13 ATS providers via a Procrastinate worker with per-batch checkpointing; total backfill cost ~$3.20 using OpenAI `text-embedding-3-small`, p95 worker throughput 280 jobs/min
- Built a React search bar over the new endpoint using RTK Query with a 30s TTL cache; debounced input + cancelable in-flight requests cut frontend network calls by ~40% during typing

**Interview talking point**: covers chunking strategy (none — single document per job, but discuss when you'd chunk), embedding model choice + cost, hybrid retrieval (filter-then-rank), and IVFFLAT vs HNSW tradeoffs.

---

### Primary 3 — Per-job interview-prep agent

**Closes**: Agent harness, ReAct / Plan-and-Execute, tool-use & function calling, multi-step reasoning, RAG, memory (lightweight). Cited by 20 of 31 jobs in the agent cluster — including the entire TikTok AI Agent JD, TikTok AIGC, TikTok Creation Tools, Apple AI Agents & Automation, Google AI/ML Agentic.

**What it does**: New `POST /api/jobs/{id}/prep` endpoint. Runs a multi-step agent loop:

1. **Tool: read_job** — pulls the enriched requirements from `ai_metadata` (depends on Primary 1)
2. **Tool: web_search_company** — pulls recent company news / engineering blog posts via a web-search MCP or a simple fetcher
3. **Tool: read_resume_section** — pulls relevant slices from `resume.md` indexed by skill (this is the RAG bit)
4. **Tool: write_prep_doc** — emits a markdown doc with: 5 likely technical questions tailored to the JD's requirements, 3 behavioral questions tied to the company's recent news, 5 talking points from the user's resume that map to JD requirements

Agent loop: ReAct-style with planning, max 8 iterations, JSON tool-call schema, retries on tool failures, full trace persisted to a new `agent_runs` table for replay/inspection.

**Where it plugs in**:
- New: `src/backend/api/services/agents/__init__.py`, `loop.py`, `tools.py`
- New: `src/backend/api/routers/jobs_prep.py` (`POST /api/jobs/{id}/prep` + `GET /api/jobs/{id}/prep/runs/{run_id}` for the trace)
- New Alembic revision: `agent_runs` table (run_id, job_id, started_at, completed_at, status, trace JSONB, output JSONB)
- Frontend: new "Interview Prep" tab on the job detail view. Streaming via SSE recommended so the trace UI shows tool calls live.

**Resume bullet options**:

- Built a ReAct-style agent in FastAPI orchestrating 4 tools (structured-requirements lookup, web company-news search, resume-section RAG, prep-doc generation) to produce tailored interview-prep packets per job; full trace replay via SSE, 8-step planning cap, JSON-schema-validated tool-call envelope
- Designed an agent observability layer: every tool invocation persisted to an `agent_runs` table with start/end timestamps, token usage, and structured output — enabling replay-from-step and a Recharts admin dashboard showing p95 loop length and per-tool failure rate across 500+ runs
- Implemented safety rails for an autonomous agent loop in production: 8-iteration hard cap, exponential backoff on tool failures, per-run cost ceiling enforced before each LLM call, and a circuit breaker that opens after 3 consecutive failures of the same tool
- Reduced agent-loop p95 latency from 28s to 11s by streaming intermediate tool results to the client over Server-Sent Events and parallelizing the two independent retrieval tools (resume RAG + company-news search) in the same planning step

**Interview talking point**: the textbook agent-engineering conversation — planning loop, tool-call schemas, max-iteration safeguards, how you'd add memory across runs, eval strategy. This is the feature that lets you walk into a TikTok AI Agent / GigaML interview and not get caught flat.

---

### Stretch 4 — Match-quality eval harness

**Closes**: LLM evals & observability. Cited by 13 of 31 (TikTok AIGC — "offline metrics, A/B experiments, run history, replay"; TikTok Creation Tools — eval pipelines; Google AI/ML — "model evaluation, optimization").

**What it does**: Hand-label 50 jobs from the existing `job_listings` table with binary "good match / bad match" for a target persona (you). Build an eval runner that sweeps (prompt template × model × temperature) over the eval set, computes precision/recall/F1, tracks cost and latency per row, and surfaces a sortable dashboard at `/admin/evals` using the existing Recharts setup.

**Where it plugs in**:
- New directory: `src/backend/evals/` (golden_set.jsonl, runner.py, metrics.py)
- New router: `src/backend/api/routers/evals.py` — list runs, view per-row diffs
- Frontend: new `/admin/evals` page; admin gating already exists in `src/backend/api/routers/admin.py`

**Resume bullet options**:

- Built an LLM eval harness over a 50-row hand-labeled golden set: sweeps (prompt template × model × temperature), computes precision/recall/F1 per cell, tracks p95 latency and per-call cost, and surfaces a Recharts regression dashboard at `/admin/evals`
- Caught a silent regression in the enricher prompt before it shipped: nightly eval run flagged a 12-point drop in `experience_level` precision after a system-prompt rewrite, blocked by the regression gate on the eval CI step
- Quantified a model-switch decision with the eval harness: showed Haiku 4.5 hit 96% of Sonnet 4.6's F1 on the structured-extraction task at 1/8 the cost, justifying the production switch and saving ~$8/day on enrichment
- Extended the harness with a slice-based view: precision/recall broken down by ATS source (Greenhouse / Lever / Ashby / Workday / Gem / Eightfold) — exposed a 22-point precision gap on Workday's HTML descriptions and drove the fix in the parser

**Interview talking point**: differentiator. Most candidates can't talk about LLM evals concretely — having a golden set, sweeping configs, and showing the regression dashboard makes you look senior for the level.

---

### Stretch 5 — LLM call wrapper / observability layer (do this FIRST)

**Closes**: Production LLM ops (caching, cost, latency, reliability) — implicit in 27 of 31 jobs.

**What it does**: Single Python wrapper module that every LLM call in JVN routes through. Features: Anthropic prompt-cache enabled by default (use ephemeral cache breakpoints, see `claude-api` skill), per-call cost tracking, p50/p95 latency, retries with exponential backoff, request/response logged to a new `llm_calls` table with redaction for PII. Admin panel surfaces aggregates with existing Recharts.

**Where it plugs in**:
- New: `src/backend/api/services/llm.py` — the wrapper
- New Alembic revision: `llm_calls` table
- New router: `src/backend/api/routers/llm_metrics.py` (admin-only)
- Frontend: panel on the QA page or a new `/admin/llm` page

**Why FIRST**: features 1, 2, 3, 4 all depend on calling an LLM. Having the wrapper in place means each new feature inherits caching, cost tracking, and observability for free — and you can show interviewers the call-volume / cost dashboard as the umbrella story.

**Resume bullet options**:

- Designed a typed LLM-call wrapper for a FastAPI service shared by 4 downstream features: Anthropic prompt-caching, per-call cost + p95 latency tracking, exponential retries with jitter, PII-redacted request/response logging to an `llm_calls` table, surfaced via a Recharts admin dashboard
- Drove daily LLM spend from $18 to $3 across the enricher, search, agent, and eval features by routing all calls through a shared wrapper with Anthropic prompt caching enabled by default and per-feature cost ceilings
- Built per-feature LLM observability across 30k+ daily calls: p50/p95 latency by feature × model, cache-hit rate, retry count, and per-call cost — exposed via an `/admin/llm` Recharts dashboard, gated by the existing admin router
- Implemented graceful degradation across the LLM call surface: a single retry-with-backoff strategy, a circuit breaker that fails callers fast after 5 consecutive 5xxs from the provider, and a per-feature budget ceiling that hard-stops runaway loops before they exceed daily cost limits

---

## 4. Suggested build order

1. **Stretch 5 — LLM call wrapper.** Prerequisite for everything else.
2. **Primary 1 — LLM job-detail enricher.** First real consumer of the wrapper; produces the structured `ai_metadata` that Primaries 2 and 3 depend on.
3. **Primary 2 — Natural-language search (pgvector + RAG).** Adds the embeddings substrate, depends on having structured fields from Primary 1 to embed.
4. **Primary 3 — Interview-prep agent.** The capstone — uses the wrapper, the structured data, and the embeddings.
5. **Stretch 4 — Eval harness.** Do last so it can measure the full system end-to-end.

Each step compounds: Primary 3 isn't a one-off agent demo, it's the natural conclusion of a system you built up over the prior four features. That story sells better than five disconnected projects.

---

## 5. Per-job appendix

How each of the 31 LLM-matched AI/agent jobs maps to the recommended features. **P** = primary, **S** = stretch; numbers reference the features above.

| Fit | Company | Title | Features that let you speak to this JD |
|---|---|---|---|
| 16 | google | Software Engineer III, Full Stack, Google Cloud AI | P1, P2, S5 |
| 16 | tiktok | Software Engineer, TikTok Actor Integrity Foundation | P1, P3, S5 |
| 16 | tiktok | Software Engineer, TikTok AIGC Agentic Workflow | P1, P3, S4, S5 |
| 16 | tiktok | Software Engineer, AI & Agent — TikTok Ecosystem & Platform | P1, P2, P3, S5 |
| 16 | amazon | Software Engineer I, Ad Supply (Twitch) | P1, S5 |
| 16 | uber | Software Engineer II — Earner (multiple teams) | P1, S5 |
| 15 | google | Software Engineer, AI/ML Agentic AI Systems, Cloud Security | P1, P3, S5 |
| 15 | google | Software Engineer III, AI/ML Computer Vision, AR | P1, S5 |
| 15 | tiktok | Software Engineer — Creative AI, Ads Creative & Ecosystem | P1, P3, S5 |
| 15 | tiktok | Software Engineer Graduate (Data Arch — AI/ML Infrastructure) | P1, S5 |
| 15 | tiktok | Backend Software Engineer — Global E-commerce, Supply Chain and Logistics | S5 |
| 15 | tiktok | Software Engineer, TikTok AIGC Agentic Workflow (alt listing) | P1, P3, S4, S5 |
| 15 | tiktok | Software Engineer, AI Agent | **All five** — this JD is the canonical match |
| 15 | tiktok | Backend Engineer, TikTok BRIC ML Foundation | P1, S5 |
| 15 | uber | Software Engineer II — Uber Eats | S5 |
| 15 | uber | Software Engineer II — Grocery & Retail | S5 |
| 14 | tiktok | Software Engineer — LLM Applications and AI Agents | P1, P2, P3, S5 |
| 14 | tiktok | Software Engineer — Global E-Commerce Search Infrastructure (TikTok Shop) | P2, S5 |
| 13 | uber | Software Engineer II — Grocery & Retail (alt) | S5 |
| 13 | uber | Software Engineer II — Fullstack, Grocery | S5 |
| 13 | amazon | Software Engineer, Monetization ML (Twitch) | P1, S5 |
| 12 | google | Software Engineer, Generative AI, Workspace | P1, P3, S5 |
| 12 | tiktok | Software Engineer, Pangle — SIA | S5 |
| 12 | apple | Software Engineer — AI Agents & Automation, Maps Data Tooling | P3, S5 |
| 12 | tiktok | Software Engineer, Ads Measurement & Effectiveness | S5 |
| 12 | tiktok | Software Engineer, AI Agents for Creation Tools | P1, P3, S5 |
| 12 | amazon | Software Engineer II, SCOT — Automated Inventory Mgmt | S5 |
| 12 | amazon | Software Engineer II, Analytics Amazon Dedicated Cloud (ADC) | S5 |
| 12 | amazon | Full Stack Software Engineer, Amazon Leo OISL | S5 |
| 10 | uber | Software Engineer II, AdTech | S5 |
| 9 | tiktok | Backend Software Engineer — Global E-Commerce, Supply Chain and Logistics (alt) | S5 |

Coverage check: every primary feature maps to ≥ 2 jobs; the TikTok AI Agent JD (fit=15) is hit by all five features and should be treated as the canonical interview target. Even the "S5-only" rows benefit because production LLM ops is a near-universal implicit requirement and the wrapper anchors the broader story.

---

## 6. v2 vision — Multi-tenant AI job-fit notifier (user-proposed)

This section captures the user's proposed redesign: pivot JVN from a single-user dashboard to a **multi-tenant, AI-powered job-fit notification SaaS** — basically "job-watcher productionized for many users." Below: the concept in clean form, how it maps to the 31-job requirements, what's net-new, the design gaps to close before building, and resume bullets.

### 6.1 The concept

End-to-end pipeline per user:

1. **Shared ingestion** — continuous scraping into `job_listings` (already exists).
2. **Enrichment** — every new job hits the LLM enricher (Primary 1) to produce structured `ai_metadata.requirements`, `skills_required`, `experience_level`, etc.
3. **Vector store** — every new job is embedded into pgvector (Primary 2 substrate).
4. **Per-user search profile** — each user uploads a resume and writes a system prompt describing what they want ("backend SWE II at FAANG-tier, SF Bay, AI engineering preferred, no ML research, no mobile, no security"). The system prompt is then **synthesized into a structured rubric** by a meta-LLM call (basically auto-generates the equivalent of `fit-profile.md`).
5. **Two-stage prefilter per user × per new job**:
   - Stage A: vector similarity between the user's profile embedding and the job's embedding — drop bottom 90%.
   - Stage B: keyword filter on `details.requirements` (hard excludes the user defines: C++-only, ≥5 YOE, etc.) — drop another large chunk.
6. **LLM scoring** — surviving jobs get passed to an LLM with the user's resume + rubric and returned a 0–N score + reason.
7. **Notification** — if score ≥ user's threshold, fire a notification (email / push / Slack / Telegram).
8. **Rubric iteration UI** — user can edit their system prompt, see the resulting rubric, replay it against the last 7 days of jobs, view a score distribution histogram, and re-tune the threshold. This is the prompt-engineering playground.
9. **Stretch — "Datadog for job listings"** — natural-language dashboard builder. User describes a chart in plain English; the system selects from a small palette of templated React components (line, bar, KPI card, distribution, table) and instantiates one. Dashboards are draggable (`react-grid-layout`) and saved per-user.

### 6.2 How v2 maps to the 31 jobs' requirements

This design hits **more requirements clusters from §1 than the original 5 features combined**, because the multi-tenant + iteration + notification surface is exactly what production AI products look like:

| Cluster from §1 | How v2 hits it |
|---|---|
| LLM application engineering (prompts / function calling / structured output) | Rubric synthesis is the canonical "freeform prompt → structured schema" task; scoring uses structured outputs |
| Agent harness & orchestration | The rubric-synthesis loop with iteration UI is a single-purpose agent; could extend to a multi-tool "refine my rubric" agent |
| RAG & retrieval | Stage A vector prefilter against the user's profile is textbook RAG |
| Embeddings & semantic search / vector stores | Same |
| LLM evals & observability | Rubric iteration *requires* the eval harness (Stretch 4) to show "before/after my prompt change, here's how scoring shifted on the last 100 jobs" |
| Production LLM ops | Per-user fan-out + cost ceilings + caching = the LLM wrapper (Stretch 5) becomes load-bearing |
| LLM core (LLMs / foundation models / GenAI) | Universal |
| Distributed systems & data pipelines | Continuous ingestion → per-user fan-out → notification = classic event-driven architecture |
| Backend / API / DB / cloud | Multi-tenant data model, async fan-out workers, per-user budgets |
| Notification / event-driven | **New cluster** — directly mirrors TikTok AI Agent JD's "omni-channel personalized marketing Agents… WhatsApp, phone, email" requirement |

Clusters this design still doesn't hit: multimodal/AIGC, ML platform/infra, streaming (Kafka/Flink). Those remain "skip" per §6.

### 6.3 What's net-new vs the original Primaries 1–3 + Stretches 4–5

- **Primary 1 (enricher)** is reused unchanged — it's the upstream substrate.
- **Primary 2 (semantic search)** evolves from "freeform search bar" to "per-user profile vector compared continuously against every new job." Same embeddings, different consumer.
- **Primary 3 (interview-prep agent)** is **deprioritized** — the per-user matching pipeline tells a stronger and more general story than a one-off prep generator. Keep prep-agent on the back burner; if you build v2 it's no longer the centerpiece.
- **Stretch 4 (eval harness)** moves up to a **Primary** — rubric iteration is the user-visible application of the eval pattern, which makes it both the engineering substrate AND a UX feature you can demo.
- **Stretch 5 (LLM wrapper)** stays a **prerequisite** but is now mission-critical: O(active_users × new_jobs/day) LLM calls without cost discipline will burn through your wallet in a week.

### 6.4 New components needed (none of these exist in JVN today)

| Component | What it does | Files to add |
|---|---|---|
| `user_search_profiles` table | One row per user: `resume_text`, `system_prompt`, `rubric` (JSONB synthesized from prompt), `threshold`, `notification_channel`, `notification_address`, `daily_cost_cap`, `paused` flag | Alembic revision; SQLAlchemy model in `src/backend/api/db_models.py` |
| `prompt_versions` table | Append-only history of each user's `(system_prompt, rubric, threshold)` so the iteration UI can diff and roll back; FK to `user_search_profiles` | Same migration |
| `job_user_scores` table | Per (user × job) score + reason + which `prompt_version_id` produced it; lets you re-render the score timeline after a rubric edit | Same migration |
| `notifications` table | Per-user notification log with `status` (pending/sent/failed/clicked), `channel`, `sent_at`, and `feedback` (thumbs-up/down from the email link) | Same migration |
| Rubric synthesis service | Single LLM call: `system_prompt → structured rubric (JSON)`. Mirror of `fit-profile.md` but auto-generated. Validates with Pydantic; user can edit the JSON output before saving. | `src/backend/api/services/rubric_synthesis.py` |
| Fan-out scoring worker | Procrastinate task: for each new enriched job, enumerate users where `paused=False` AND prefilter passes, then queue per-(user, job) scoring jobs. Respects per-user `daily_cost_cap`. | `src/backend/api/services/scoring_fanout.py` |
| Notification dispatcher | Pluggable channel adapters (start with email via SES/Resend, add Telegram next since job-watcher already proved that channel works) | `src/backend/api/services/notifier/{email,telegram,slack}.py` |
| Calibration UX | "If you set threshold to 12, you would have been notified about 6 jobs this week. At 14: 1 job." Shows histogram of scores from a backfill. Critical for new-user onboarding. | New `RubricIterationPage` in frontend |
| Feedback loop endpoint | "Not interested" / "Looks good" buttons in the notification email POST back to a feedback endpoint; surfaced in iteration UI as "out of your last 10 thumbs-up, your rubric agrees on 8" | `src/backend/api/routers/notifications.py` |

### 6.5 Design gaps to close before building

These are the things you haven't explicitly addressed in the vision yet — none are blockers, all need a decision before code:

1. **Cost economics under fan-out.** O(active_users × new_jobs/day) LLM calls. At 100 users × 100 new jobs/day × ~$0.002/eval = $20/day; at 1000 users it's $200/day. **Mitigation**: aggressive vector prefilter (drop ≥90% before LLM), batch multiple jobs into one LLM call per user (5–10 jobs per call), reuse score across users when rubrics are similar (semantic dedup on rubrics), enforce per-user `daily_cost_cap` and pause silently when exceeded.
2. **Rubric synthesis quality.** "System prompt → rubric" is the load-bearing meta-LLM call. If it produces a bad rubric, every downstream score is bad. job-watcher's hand-tuned `fit-profile.md` took dozens of iterations to land. **Mitigation**: build the eval harness FIRST against your own rubric (use job-watcher's `fit-profile.md` + the 36 labeled matches as the golden set), then ship rubric-synthesis with the eval harness as a regression gate. Let users edit the synthesized JSON directly — don't pretend the LLM nails it first try.
3. **Threshold calibration for new users.** A new user has no intuition for "what does score 12 mean?" **Mitigation**: backfill scores against the last 30 days of jobs at signup time, show the score histogram, let them pick a threshold by clicking on the chart. (This is also a great interview demo.)
4. **Re-scoring on rubric edits.** When a user edits their prompt, do you re-score the last 7 days? Costs money. **Mitigation**: only re-score on explicit "preview my changes" click against a sampled window (50 jobs, not all). Show the per-job before/after delta in the iteration UI.
5. **Notification fatigue.** Wrong threshold → spam → unsubscribe. **Mitigation**: ship the feedback buttons (👍/👎) on day one, surface a "tune your threshold" nudge after N notifications, hard-cap notifications-per-day per user (configurable).
6. **Multi-tenant data isolation.** Auth0 is already wired (`src/backend/api/auth/`). Ensure every new query is filtered by `user_id` and add a parity test (similar to the env-agnostic-tables pattern in JVN's CLAUDE.md) so a missing `WHERE user_id = ?` is a compile-time error, not a data leak.
7. **Cold-start for the rubric.** First-time users don't know what to write. **Mitigation**: 5 preset profiles ("New grad SWE", "Mid-level backend", "AI engineering focused", "Hardware-adjacent", "Senior leadership"). User picks one as starting point, then iterates.
8. **The dashboard stretch is its own roadmap.** "Datadog for job listings" with NL → chart spec is a 2–3 month project on its own (text-to-SQL or text-to-component is non-trivial). **Recommendation**: defer until v2 ships. When you build it, start with a fixed palette of 5 components (line, bar, KPI, table, distribution), use the LLM to fill in a JSON schema per component rather than generating raw React, and use `react-grid-layout` for the drag-and-drop substrate. Reuse the rubric-synthesis eval pattern for the chart-spec LLM call.

### 6.6 Revised build order if you commit to v2

1. **Stretch 5 — LLM wrapper.** Same as before — prerequisite, more critical now.
2. **Primary 1 — Enricher.** Same as before.
3. **Stretch 4 (now promoted) — Eval harness.** Build it next, using your own hand-tuned rubric from `fit-profile.md` as the golden set seed.
4. **Rubric synthesis service + iteration UI.** This is the heart of v2; use the eval harness as the regression gate from the first commit.
5. **Per-user search profile table + auth-gated CRUD.**
6. **Fan-out scoring worker.** Vector prefilter → keyword filter → LLM scoring → write to `job_user_scores`.
7. **Notification dispatcher** (email first, Telegram second).
8. **Feedback loop + calibration UX.**
9. **(Defer) Primary 3 interview-prep agent** — only build if you find you need a second agentic story for interviews.
10. **(Defer) NL-dashboard stretch** — its own roadmap when v2 is live.

### 6.7 Resume bullets for v2 (multi-tenant pivot)

Pick the ones that line up with which roles you're applying to.

- Built a multi-tenant AI job-fit notification SaaS on FastAPI + Postgres: continuous ingestion of 30k+ jobs across 13 ATS providers fans out per-user through a 2-stage prefilter (pgvector similarity → keyword exclude rules) → LLM scoring against a user-specific synthesized rubric → email/Telegram notification when score crosses threshold
- Designed a "system-prompt → structured rubric" synthesis pipeline: single LLM call with JSON-schema validation converts freeform user preferences into a typed rubric stored in Postgres, with an iteration UI that diffs prompt versions and replays scoring against the last 7 days for instant feedback
- Cut per-user LLM cost 85% on a fan-out scoring pipeline by introducing a 2-stage prefilter (drop 90% of jobs via vector similarity before any LLM call) plus per-user `daily_cost_cap` enforcement and 5-job batching per LLM call — kept marginal cost per active user under $0.05/day at 100-user scale
- Built a prompt-iteration playground for end users: edit your system prompt, see the synthesized rubric diff, replay against a sampled 50-job window, view a score histogram, and click on the histogram to pick your notification threshold — backed by an eval harness using the user's previous 👍/👎 feedback as a regression set
- Designed an event-driven scoring fan-out on Procrastinate: each new enriched job enqueues per-(user, job) scoring tasks for every active user whose vector + keyword prefilter passes, with per-user budget enforcement, idempotent retries, and a `notifications` table tracking sent / failed / clicked status
- Shipped multi-tenant data isolation on a Postgres-backed FastAPI service: enforced `user_id` scoping on every query with a parity-test pattern that fails CI when a router function constructs a query missing the user predicate, modeled after the env-agnostic-tables pattern already in the codebase
- Built a notification preference + feedback loop: thumbs-up / thumbs-down buttons on every notification email POST back to a feedback endpoint, surfaced as "your rubric agrees on 8 of your last 10 thumbs-up" in the iteration UI, used to auto-suggest rubric tweaks

### 6.8 Verdict

**Does it fit well?** Yes — and it's a stronger interview story than the original 5 features because it pulls together prompt engineering, RAG, evals, production LLM ops, multi-tenancy, and event-driven fan-out into a single coherent product. The original Primaries 1, 2, and Stretch 4, 5 fold cleanly into this larger system; only Primary 3 (interview-prep agent) becomes redundant.

**Biggest risk**: cost economics. If you don't build the prefilter + per-user budget caps from day one, this becomes uneconomic at the 50-user mark and you'll be tempted to shut it down before it tells a story. Lead with cost discipline; that's also exactly the engineering judgment senior AI engineering interviews probe for.

**Don't conflate the dashboard stretch with v2.** Build v2, get it live, then attack the dashboard separately. Trying to ship both in one push will dilute both stories.
