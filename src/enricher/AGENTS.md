# AGENTS.md — src/enricher

The local enrichment worker. It runs on Brendan's Mac, not on Railway or Vercel: it pulls
OPEN jobs from the backend (`/api/internal/enrichment/*`), classifies them (category, level,
tags, locations) with a local model or Claude, and writes the results back. Python 3.12, its
own `uv` project (`pyproject.toml` + `uv.lock` here; the backend image and the frontend build
never include it).

**The full operating manual is `CLAUDE.md` in this directory** — it is what `claude` loads
with cwd = `src/enricher`. Read its "Which checkout am I in?" section before touching anything.

## Checkouts

| Role (`.checkout-role`) | Path | Rule |
|---|---|---|
| `prod` | `~/developer/personal/enricher-prod/src/enricher` (a JVN clone at the deployed ref) | never edit; deployed only by `scripts/deploy.sh <ref>`; merging to `main` deploys nothing |
| `dev` or absent | this checkout's `src/enricher`, or a JVN worktree's | edit freely; keep `.env.local` off real JVN |
| `retired` | `~/developer/personal/app`, `~/developer/personal/job-enricher` | never edit; `app/` is the pre-cutover rollback artifact |

Until the post-merge cutover runs, prod is still `~/developer/personal/app`; the launchd
plist's `WorkingDirectory` is the truth. Details: `docs/ENVIRONMENTS.md`.

**Never run the enricher CLI against prod from an agent shell** — even `cli health` opens
the DB and runs `init_schema` (a migration, if the code is newer).

**State is package-relative.** The DB, lock and chunk files live under this directory's
`data/` (`store.REPO_ROOT`), so every checkout owns its own. `.env.local` is per-checkout too.

## Tests

```bash
cd src/enricher && uv sync --locked && uv run pytest
```

CI runs this as the `enricher` job (macOS). The suite must run **inside JVN**:
`tests/test_taxonomy_parity.py` reads the backend's `src/backend/taxonomy.json`. To change a
taxonomy slug, change the backend, regenerate it with
`src/backend/tools/generate_taxonomy_artifact.py`, and update `job_enricher.taxonomy` in the
same PR.

## What Claude Code loads here

Only the `claude-code` engine calls `claude` (`claude -p /enrich-tick-once`, cwd =
`src/enricher`); prod's `ollama` engine runs the pipeline in-process. For that path, per the
Claude Code docs (checked 2026-11; `tests/test_monorepo_guards.py` pins it):

- `CLAUDE.md` / `CLAUDE.local.md` load from the cwd **and every ancestor** — into the tick
  and into every classifier/judge sub-agent. So JVN keeps no `CLAUDE.md` at its root or in
  `src/`; put JVN-wide agent notes in `AGENTS.md`. An untracked `CLAUDE.local.md` at a JVN
  clone's root loads too.
- `AGENTS.md` files load only when no `CLAUDE.md` exists at or above the cwd (the default
  mode). This directory's `CLAUDE.md` keeps every JVN `AGENTS.md`, this one included, out of
  enrichment prompts. A user setting of `claude-md-and-agents-md` would pull them in.
- Project skills load from the cwd up to the repo root, and a root skill wins over a nested
  one of the same name. JVN's root skills and commands are therefore visible to the tick;
  none may reuse an enricher name (`enrich-tick-once`, `taxonomy`, …).
- Shared `.claude/settings.json` comes from the starting directory only, but
  `.claude/settings.local.json` is read from the **git root** — never put hooks in a JVN
  clone's root `settings.local.json`.
