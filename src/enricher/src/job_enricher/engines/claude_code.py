"""Claude Code engine — headless `claude -p` on the subscription.

Makes the Claude side a real Python-callable engine so the eval harness drives it
identically to the open engines (same prompt, per-item latency, reproducible).
`--output-format json` returns an envelope object whose `result` field holds the
assistant text; we parse the JSON array out of that.

NOTE: production `/enrich-tick` keeps the SANDBOXED sub-agent fan-out for Claude
(prompt-injection hardening on untrusted scraped text). This headless path is for
eval + explicit opt-in via the engine knob, where the input is trusted golden text.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

from job_enricher.engines.base import ChunkEngine, EngineError


class ClaudeCodeEngine(ChunkEngine):
    name = "claude-code"

    def __init__(self, model: str, binary: str = "claude", timeout: float = 300.0) -> None:
        self._model = model  # tier: haiku | sonnet | opus
        self._binary = binary
        self._timeout = timeout

    def _call(
        self, prompt: str, *, response_schema: dict[str, Any] | None = None
    ) -> str:
        # `response_schema` is ACCEPTED AND IGNORED: `claude -p` has no
        # structured-output flag, so the constraint is NOT enforced here. The
        # tolerant extract_json_array + taxonomy.validate_subcategories are what
        # protect this path — which is exactly why those rules live in code.
        try:
            proc = subprocess.run(
                [self._binary, "-p", prompt, "--model", self._model,
                 "--output-format", "json"],
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise EngineError(f"claude -p invocation failed: {exc}") from exc
        if proc.returncode != 0:
            raise EngineError(
                f"claude -p exit {proc.returncode}: {(proc.stderr or '')[:500]}"
            )
        return _result_text(proc.stdout)


def _result_text(stdout: str) -> str:
    """Pull the assistant text out of `claude -p --output-format json`.

    In Claude Code 2.x that output is a JSON ARRAY of stream events; the model's
    final text is the `result` field of the `type == "result"` event. Also handles
    a single-object envelope (other CLI versions). Falls back to raw stdout — the
    array extractor then recovers the JSON downstream."""
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return stdout
    if isinstance(data, list):
        for evt in reversed(data):
            if (isinstance(evt, dict) and evt.get("type") == "result"
                    and isinstance(evt.get("result"), str)):
                return evt["result"]
    elif isinstance(data, dict) and isinstance(data.get("result"), str):
        return data["result"]
    return stdout
