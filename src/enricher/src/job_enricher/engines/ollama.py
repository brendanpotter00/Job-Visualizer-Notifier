"""Ollama HTTP engine — the default local open-model backend.

Talks to Ollama's native `/api/chat` (localhost:11434) with structured output
(`format` = a permissive array JSON schema) + temperature 0. This is the clean,
fast, unit-testable path (mirrors JVNClient; mockable with respx) that drives the
same local weights OpenCode would, minus the harness overhead.
"""

from __future__ import annotations

import httpx

from job_enricher.engines.base import ChunkEngine, EngineError

# Permissive schema: forces a JSON *array of objects* (so we never get an
# object-wrapped result) while leaving the fields to the prompt.
_ARRAY_SCHEMA = {"type": "array", "items": {"type": "object"}}


class OllamaEngine(ChunkEngine):
    name = "ollama"

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
        timeout: float = 300.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._model = model
        self._base = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=timeout)

    def _call(self, prompt: str) -> str:
        try:
            resp = self._client.post(
                f"{self._base}/api/chat",
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "format": _ARRAY_SCHEMA,
                    "options": {"temperature": 0},
                },
            )
            resp.raise_for_status()
            # .json() must be INSIDE the handler: a non-JSON 200 body raises
            # ValueError (not httpx.HTTPError), which would otherwise escape as a
            # non-EngineError and abort the whole run instead of skipping one chunk.
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise EngineError(f"ollama call failed ({self._model}): {exc}") from exc
        # native /api/chat -> {"message": {"role","content"}, ...}
        msg = data.get("message") if isinstance(data, dict) else None
        if isinstance(msg, dict) and isinstance(msg.get("content"), str):
            return msg["content"]
        raise EngineError(f"ollama returned no message content: {str(data)[:300]}")
