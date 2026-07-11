# job-enricher

A local [Claude Code](https://claude.com/claude-code) agentic workflow that enriches job
postings for **JVN** (Job-Visualizer-Notifier) — adding a **normalized location**, a cleaned
**description**, a **category**, and a **leveling** tier — under the Claude Code
**subscription** (no per-token API cost), gated by an **adversarial Sonnet LLM-as-judge**. The category and
level enums (the single source of truth) live in `.claude/skills/taxonomy/SKILL.md`.

> **Prod vs dev:** this repo is checked out twice — `~/developer/personal/app` (**prod**,
> where the launchd worker runs against real JVN) and `~/developer/personal/job-enricher`
> (**dev**, where you edit). Run `cat .checkout-role` to see which you're in, and read
> [`docs/ENVIRONMENTS.md`](docs/ENVIRONMENTS.md) before editing or deploying.

## Why a second path?
JVN already normalizes locations via **cloud Haiku** on the paid API. This workflow adds richer
enrichment on the laptop for free, and JVN can switch to it behind a feature flag. Because the
laptop is unmanaged, the integration is **PULL**: the laptop polls JVN, enriches, and writes
back. If the laptop is down, JVN's Haiku location floor keeps working — the job board never
depends on this machine.

```
JVN (Railway/local)                        Laptop (Claude Code subscription)
  GET  /api/internal/enrichment/pending     <──  cli pull         (claim OPEN unenriched jobs)
                                                 cli clean        (deterministic HTML->text)
                                                 /enrich-tick     (Haiku classify -> Sonnet judge)
  POST /api/internal/enrichment/results     <──  cli write-back   (durable, idempotent)
  POST /api/internal/enrichment/metrics     <──  cli metrics-push (per-tick observability, best-effort)
  GET  /api/internal/enrichment/corrections <──  cli golden-merge (human corrections -> gold labels)
```
Identity is the composite `(source_id, job_listing_id)` pair everywhere (JVN job ids are
not globally unique across sources). The laptop's liveness heartbeat and status counts are
LOCAL (`cli health`, backed by SQLite); each tick's counters/timings/knobs additionally ride
to JVN via `cli metrics-push` (best-effort — a metrics failure never fails a tick).

The classify/judge sub-agents are the restricted agents in `.claude/agents/` (Read/Grep/
WebSearch only — scraped postings are untrusted input and never reach a tool that can
execute or write). The Sonnet judge defaults to `judge_scope=low_confidence`: it judges only
rows classify was unsure about (confidence < `judge_confidence_ceiling`, default 0.85), rows
with a nulled facet, or rows already flagged `needs_human`.

## Quick start
```bash
uv sync
cp .env.example .env.local     # set JVN_BASE_URL + INTERNAL_API_KEY
uv run python -m job_enricher.cli init
uv run python -m job_enricher.cli pull        # claim a batch from JVN
uv run python -m job_enricher.cli clean
claude -p /enrich-tick                         # classify -> judge -> write-back, then loops
```

Run the loop continuously with `claude` + `/loop /enrich-tick`, or install the launchd worker:
`scripts/install_launchagents.sh` (StartInterval=600s).

## Tests
```bash
uv run pytest
```

See `CLAUDE.md` for the full operator guide and `docs/` for architecture + the JVN handoff.
