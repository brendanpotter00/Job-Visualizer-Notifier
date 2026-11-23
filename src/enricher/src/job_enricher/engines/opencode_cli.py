"""OpenCode CLI engine — the local weights via the OpenCode harness.

Secondary open path (the `ollama` engine is the default). `opencode run` drives
the same Ollama model through OpenCode's agentic harness; its stdout carries the
answer amid the harness's own output, so we lean entirely on the tolerant array
extractor (which strips `<think>` blocks and fences). Kept behind the same
interface so it is a drop-in `classify:engine`/`judge:engine` value.
"""

from __future__ import annotations

import subprocess
from typing import Any

from job_enricher.engines.base import ChunkEngine, EngineError


class OpenCodeEngine(ChunkEngine):
    name = "opencode"

    def __init__(self, model: str, binary: str = "opencode", timeout: float = 300.0) -> None:
        self._model = model  # Ollama tag, e.g. qwen3:32b
        self._binary = binary
        self._timeout = timeout

    def _call(
        self, prompt: str, *, response_schema: dict[str, Any] | None = None
    ) -> str:
        # `response_schema` is ACCEPTED AND IGNORED: `opencode run` has no
        # structured-output flag, so the constraint is NOT enforced here. The
        # tolerant extract_json_array + taxonomy.validate_subcategories are what
        # protect this path.
        try:
            proc = subprocess.run(
                [self._binary, "run", "--model", f"ollama/{self._model}", prompt],
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise EngineError(f"opencode run invocation failed: {exc}") from exc
        if proc.returncode != 0:
            raise EngineError(
                f"opencode run exit {proc.returncode}: {(proc.stderr or '')[:500]}"
            )
        return proc.stdout
