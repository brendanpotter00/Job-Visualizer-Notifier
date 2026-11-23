# Local open-source model via OpenCode + Ollama — handoff

**Date:** 2026-07-11 · **Status:** exploratory, NOT wired into the enrich pipeline.

This documents a spike: running an open-weight model **fully locally** on the laptop as a
possible alternative to the Claude-subscription classify/judge tiers. It is a standalone
sandbox — **nothing in the `/enrich-tick` pipeline was changed.** Production still classifies
and judges with Claude (Sonnet default) over the Claude Code subscription; see the root
`CLAUDE.md` and `docs/ENVIRONMENTS.md` for the real pipeline.

## What was installed / changed on this machine

| Thing | Detail |
|---|---|
| **Ollama** (new) | Installed via `brew install ollama` (v0.31.1). Runs as a **login background service** (`brew services`, `homebrew.mxcl.ollama.plist`) — headless, no window, listens on `http://localhost:11434`. |
| **OpenCode** (pre-existing) | Already installed (v1.17.15); not installed by this spike. Its global config was written. |
| **OpenCode config** (new) | `~/.config/opencode/opencode.jsonc` — registers a local Ollama provider + model tiers, default `ollama/qwen3:32b`. (Global user config, **not** in this repo.) |
| **Model pulled** | `qwen3:32b` (~20 GB, Q4). Kept. |
| **Models deleted** | `qwen3:0.6b` (smoke test) and `qwen3:8b` (interim, used while disk was tight) were pulled during setup then removed. |

> Stale config note: `opencode.jsonc` still lists a `qwen3:0.6b` entry, but that model was
> deleted — harmless leftover; remove the entry (or `ollama pull qwen3:0.6b`) if it bothers you.
> `llama3.3:70b` is **registered but not pulled** — pulling it needs ~40 GB free.

## How it's meant to be used

```
you ──▶ OpenCode (CLI harness) ──HTTP──▶ Ollama (localhost:11434) ──▶ qwen3:32b (local weights)
        reads ~/.config/opencode/opencode.jsonc                       streams answer back
```

- Run a one-shot: `opencode run "…your prompt…"` → uses the default model (`qwen3:32b`).
- Swap tiers: change the top-level `"model"` in `opencode.jsonc`, or `opencode run --model ollama/<tag> "…"`.
- Model tiers (see `docs/`-level analysis / chat history): **sweet spot** `qwen3:32b` (~20 GB, the
  usable default); **pushing it** `llama3.3:70b` (~40 GB, not pulled). On a 64 GB M2 Max the
  practical ceiling is a 70B dense or a ~100B MoE at low quant.

### Gotchas
- **It's slow, especially the first call** — cold weight-load + qwen3 is a *reasoning* model
  (emits hidden `<think>` tokens) + OpenCode ships a big system prompt. It stays warm ~5 min after use.
- **Suppress reasoning** with the Qwen3 prompt token `/no_think` **in the message text** (put it at
  the *end* so OpenCode doesn't treat a leading `/` as one of its own commands).
- **Disk** — the laptop was near-full during setup; the 32B fits, the 70B does not without freeing space.

## Why this is NOT a drop-in for the pipeline

- The `/enrich-tick` pipeline selects models via Claude Code's Agent `model` arg (`haiku`/`sonnet`/`opus`
  only) on the **subscription** — there is no code path that sends a job to a non-Claude model.
- Using an open model for real would require **porting the classify/judge agents to OpenCode**
  (or a shim), which reintroduces per-token cost/self-hosting and loses the sandboxed sub-agent
  orchestration. Not done here.
- If ever pursued, validate with the existing eval harness (`golden/seed/golden.json`, `/enrich-eval`,
  `cli eval --gate`) before trusting it — don't trust benchmarks.

## Undo / uninstall

```sh
brew services stop ollama        # stop the background server
ollama rm qwen3:32b              # reclaim ~20 GB
brew uninstall ollama            # remove Ollama entirely
rm ~/.config/opencode/opencode.jsonc   # or just delete the "provider.ollama" block
```
