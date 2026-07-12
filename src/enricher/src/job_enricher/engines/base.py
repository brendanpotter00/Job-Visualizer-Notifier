"""Engine interface + the shared build/time/parse/attach loop.

A concrete engine only implements `_call(prompt) -> str` (raw model text for one
chunk). The base turns a chunk of jobs into the recorder-shaped JSON, times the
backend call, tolerantly parses the array, and stamps per-item latency. Timing is
per chunk-CALL: with the eval's batch size of 1 that is exact per-item latency;
in production (batch > 1) it is the shared wall-time of the chunk call.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from job_enricher.engines.prompts import (
    build_classify_prompt,
    build_judge_prompt,
    extract_json_array,
)

CLASSIFY_LATENCY_FIELD = "classify_latency_ms"
JUDGE_LATENCY_FIELD = "judge_latency_ms"

# Appended to the prompt on a retry when the first parse was empty/short. The
# local open engines (qwen3 via ollama/opencode) sometimes emit an empty array
# or drop an element on a hard title; a stricter one-shot nudge recovers most.
# `/no_think` stays LAST by Qwen3 convention — a directive lands hardest as the
# most-recent instruction. (It is never a leading token regardless, since the
# nudge is always concatenated AFTER a non-empty prompt.)
_RETRY_NUDGE = (
    "\n\nIMPORTANT: return EXACTLY one JSON object per input job, in the same "
    "order, omitting none. Output only the raw JSON array. /no_think"
)


class EngineError(RuntimeError):
    """A backend call failed (non-zero exit, HTTP error, timeout, unparseable).

    Raised per chunk so the CLI runner can skip that chunk and keep going —
    a single bad chunk must never lose the work already recorded this tick.
    """


@runtime_checkable
class InferenceEngine(Protocol):
    """The one seam the pipeline talks to. `classify`/`judge` take a chunk of
    job dicts and return the recorder-compatible objects (with latency attached)."""

    name: str

    def classify(self, jobs: list[dict[str, Any]]) -> list[dict[str, Any]]: ...

    def judge(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]: ...


class ChunkEngine:
    """Base class: shared classify/judge orchestration over an abstract `_call`."""

    name: str = "base"

    def _call(self, prompt: str) -> str:  # pragma: no cover - abstract
        raise NotImplementedError

    def classify(self, jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self._call_with_repair(jobs, build_classify_prompt, CLASSIFY_LATENCY_FIELD)

    def judge(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self._call_with_repair(items, build_judge_prompt, JUDGE_LATENCY_FIELD)

    def _call_with_repair(
        self,
        inputs: list[dict[str, Any]],
        build_prompt: Callable[[list[dict[str, Any]]], str],
        latency_field: str,
    ) -> list[dict[str, Any]]:
        """Call the backend, then RECOVER dropped rows instead of losing them.

        Aimed at the local open engines (qwen3 via ollama/opencode), which
        occasionally emit an empty array, a degenerate non-object element, or a
        mis-echoed (source_id, job_listing_id) pair on a hard title — a silent
        coverage loss today. Every parse is filtered to dict objects at the
        boundary, so the counts the guards key off are always USABLE-row counts
        (`len(results)` == recoverable rows by construction). Three guards:
          1. retry ONCE (with a stricter nudge) when the parse yields fewer usable
             objects than the input chunk. A degenerate `[null]` / `["text"]`
             element is dropped by the dict filter, so it counts as zero recovered
             rows and still triggers the retry instead of silently collapsing to [].
          2. positional id-repair ONLY for the single-input chunk (`len(inputs) == 1`,
             the local default): the one output unambiguously belongs to the one
             input, so its (source_id, job_listing_id) is stamped on regardless of
             the echoed id. For a multi-input chunk (claude-code batch>1, `eval-run
             --batch>1`) position is NOT identity, so NOTHING is stamped — each
             result keeps its echoed ids and `record_enrichment_items`' identity
             guard safely skips any mismatch. That is exactly the pre-change
             behavior at batch>1, so the repair is never worse than before there.
          3. if at least one attempt raised AND nothing usable was recovered
             (`first_error is not None and not results`), re-raise so the callers'
             `except EngineError` logging still fires.
        At batch=1 a single mis-keyed or incomplete-echo result is recovered; a
        totally-degenerate parse (every element non-dict on both attempts) is
        UNRECOVERABLE and returns []. A safe no-op for Claude, which already
        returns the full count with correct ids.
        """
        prompt = build_prompt(inputs)
        first_error: EngineError | None = None
        try:
            text, latency_ms = _timed(self._call, prompt)
            results = [r for r in extract_json_array(text) if isinstance(r, dict)]
        except EngineError as exc:
            first_error, latency_ms, results = exc, 0, []
        if len(results) < len(inputs):
            try:
                text2, latency2 = _timed(self._call, prompt + _RETRY_NUDGE)
                results2 = [r for r in extract_json_array(text2) if isinstance(r, dict)]
                if len(results2) > len(results):
                    results, latency_ms = results2, latency_ms + latency2
            except EngineError as exc:
                first_error = first_error or exc
        if first_error is not None and not results:
            raise first_error  # >=1 attempt raised, nothing usable recovered
        if len(inputs) == 1 and len(results) == 1:
            # Single-input chunk: the lone output belongs to the lone input, so
            # stamp its identity on unconditionally (a matching echo is a no-op).
            # Multi-input chunks are NOT stamped — position != identity there.
            results[0]["source_id"] = inputs[0].get("source_id")
            results[0]["job_listing_id"] = inputs[0].get("job_listing_id")
        return _attach_latency(results, latency_field, latency_ms)


def _timed(fn, prompt: str) -> tuple[str, int]:
    start = time.monotonic()
    text = fn(prompt)
    return text, int((time.monotonic() - start) * 1000)


def _attach_latency(items: list[Any], field: str, latency_ms: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for it in items:
        if isinstance(it, dict):
            it.setdefault(field, latency_ms)
            out.append(it)
    return out


def build_engine(
    kind: str,
    *,
    model: str,
    settings_obj: Any | None = None,
) -> InferenceEngine:
    """Construct an engine by knob value.

    `model` is the tier (haiku/sonnet/opus) for `claude-code`, or the Ollama tag
    (e.g. qwen3:32b) for `ollama`/`opencode`. `settings_obj` overrides the global
    `config.settings` (used by tests). Import concretes lazily so importing the
    package never hard-requires httpx just to name an engine.
    """
    if settings_obj is None:
        from job_enricher.config import settings as settings_obj

    timeout = settings_obj.engine_timeout_seconds
    if kind == "claude-code":
        from job_enricher.engines.claude_code import ClaudeCodeEngine

        return ClaudeCodeEngine(
            model=model, binary=settings_obj.claude_binary, timeout=timeout
        )
    if kind == "ollama":
        from job_enricher.engines.ollama import OllamaEngine

        return OllamaEngine(
            model=model, base_url=settings_obj.ollama_base_url, timeout=timeout
        )
    if kind == "opencode":
        from job_enricher.engines.opencode_cli import OpenCodeEngine

        return OpenCodeEngine(
            model=model, binary=settings_obj.opencode_binary, timeout=timeout
        )
    raise ValueError(f"unknown engine {kind!r}; expected claude-code | ollama | opencode")
