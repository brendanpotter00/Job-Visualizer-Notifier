"""Ollama HTTP engine — the default local open-model backend.

Talks to Ollama's native `/api/chat` (localhost:11434) with structured output
(`format` = a permissive array JSON schema) + temperature 0. This is the clean,
fast, unit-testable path (mirrors JVNClient; mockable with respx) that drives the
same local weights OpenCode would, minus the harness overhead.
"""

from __future__ import annotations

from typing import Any

import httpx

from job_enricher import taxonomy as tax
from job_enricher.engines.base import ChunkEngine, EngineError

# Permissive schema: forces a JSON *array of objects* (so we never get an
# object-wrapped result) while leaving the fields to the prompt. Deliberately
# left permissive for classify/judge: constraining every classify field is a far
# larger blast radius on the lane that is already at capacity, and that lane's
# protection is validate_facets + validate_subcategories IN CODE.
_ARRAY_SCHEMA = {"type": "array", "items": {"type": "object"}}

# The subcategory-only lane's ENUM-CONSTRAINED schema. BUILT FROM
# `sorted(tax.SUBCATEGORIES)` rather than a literal list so it can never drift
# from the frozenset — ENR-PAR-1 asserts the enum equals that sorted list
# exactly, INCLUDING ORDER, which is only meaningful because it is derived.
_SUBCATEGORY_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "job_listing_id": {"type": "string"},
            "source_id": {"type": "string"},
            "subcategories": {
                "type": "array",
                "maxItems": tax.MAX_SUBCATEGORIES,
                "items": {"type": "string", "enum": sorted(tax.SUBCATEGORIES)},
            },
            "subcategory_confidence": {"type": ["number", "null"]},
        },
        "required": ["job_listing_id", "source_id", "subcategories"],
    },
}


class OllamaEngine(ChunkEngine):
    name = "ollama"

    # Overrides ChunkEngine.subcategory_schema (None). A response schema is an
    # ENGINE CAPABILITY, so the engine owns it — this keeps `base.py`
    # dependency-free instead of having the abstract base import a concrete
    # engine (which would also drag httpx into every ChunkEngine import path).
    subcategory_schema = _SUBCATEGORY_SCHEMA

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

    def _call(
        self, prompt: str, *, response_schema: dict[str, Any] | None = None
    ) -> str:
        try:
            resp = self._client.post(
                f"{self._base}/api/chat",
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "format": response_schema or _ARRAY_SCHEMA,
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
