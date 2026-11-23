"""Swappable inference engines for classify + judge.

The `/enrich-tick` pipeline historically ran ALL inference inside Claude Code's
sandboxed sub-agent orchestration (the Agent `model` arg on the subscription).
This package adds a Python-level seam so the SAME classify/judge contract can be
produced by different backends behind one interface:

  claude-code  -> headless `claude -p --model <tier>` (subscription auth)
  ollama       -> the local open model over Ollama's HTTP API (default open engine)
  opencode     -> the same local weights via the OpenCode CLI harness

Every engine emits the exact JSON the recorders (`record_enrichment_items` /
`apply_judge_verdicts`) already validate, so all taxonomy validation, level-change
rails, provenance, and durability are reused unchanged. Each returned item also
carries a per-call `classify_latency_ms` / `judge_latency_ms` so the eval harness
and the DB can report speed. See docs/LOCAL-OPEN-MODEL.md and the plan.
"""

from __future__ import annotations

from job_enricher.engines.base import EngineError, InferenceEngine, build_engine
from job_enricher.engines.claude_code import ClaudeCodeEngine
from job_enricher.engines.ollama import OllamaEngine
from job_enricher.engines.opencode_cli import OpenCodeEngine

__all__ = [
    "EngineError",
    "InferenceEngine",
    "build_engine",
    "ClaudeCodeEngine",
    "OllamaEngine",
    "OpenCodeEngine",
]
