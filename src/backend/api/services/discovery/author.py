"""DISCOVERY AUTHOR — the one Sonnet call that writes a candidate recipe (E7 3b).

Mirrors :mod:`api.services.llm_client`: an ``AsyncAnthropic`` client built with
``max_retries=0`` (Procrastinate owns retries), a structured-outputs call
(``output_config.format.json_schema``) whose schema is derived from the Phase-3a
recipe vocabulary (:mod:`api.services.recipe_schema`), and a ``MissingAnthropicKeyError``
raised BEFORE the client is constructed when the key is unset — so a keyless env
REFUSES cleanly instead of erroring mid-flow.

The output schema's ``op`` / ``transport`` / ``oracle.kind`` enumerations are read
from ``recipe_schema`` (the closed vocabulary minus the Phase-4 browser ops), so
the model can only emit a shape the validator's vocabulary admits — the
prompt/schema single-source-of-truth pattern from the location eval. The authored
script is still re-validated by ``recipe_schema.validate_recipe`` and replayed by
``recipe_runner`` before it is ever stored; this schema is a guide, not the gate.

This module imports ``anthropic``. It is imported ONLY by ``services/discovery`` +
the discovery task — never by ``recipe_runner`` or the replay leaf task's ``tasks/``
closure (the import-guard tests enforce that). ``anthropic`` being resident in the
shared worker is already normal (location normalization loads it) and does not trip
the replay path's runtime guard, which watches only the browser drivers.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from anthropic import AsyncAnthropic

from ...config import settings
from .. import recipe_schema

logger = logging.getLogger(__name__)

# Claude Sonnet — the discovery model (BUILD-PLAN §6). One structured-output call
# per authoring attempt, ≤2 attempts per add.
SONNET_MODEL = "claude-sonnet-5"
MAX_TOKENS = 4096
AUTHOR_TIMEOUT_SECONDS = 60.0


class DiscoveryAuthorError(Exception):
    """The author response was empty / non-JSON / not an object. Retryable."""


class MissingAnthropicKeyError(DiscoveryAuthorError):
    """anthropic_api_key falsy. discover() catches this and REFUSES without
    burning an authoring attempt (mirrors ``llm_client.MissingAnthropicKeyError``)."""


def build_recipe_output_schema() -> dict[str, Any]:
    """The JSON schema handed to Sonnet, derived from the recipe vocabulary.

    ``op`` is the closed op set MINUS the Phase-4 browser/click ops (so the model
    cannot even name one); ``transport`` and ``oracle.kind`` mirror the schema's
    own enumerations. Kept permissive per-step (the strict per-op param check is
    ``validate_recipe``'s job) but closed at the vocabulary level.
    """
    allowed_ops = sorted(set(recipe_schema._OP_VALIDATORS) - set(recipe_schema._BROWSER_OPS))
    # The union of every param key any op / oracle uses, so a well-formed step or
    # oracle validates against additionalProperties:false while still being
    # narrowed to the real op vocabulary by the enum above.
    step_props = {
        "op": {"type": "string", "enum": allowed_ops},
        "method": {"type": "string", "enum": ["GET", "POST"]},
        "url": {"type": "string"},
        "headers": {"type": "object"},
        "body": {"type": "object"},
        "param": {"type": "string"},
        "page_size": {"type": "integer"},
        "max_pages": {"type": "integer"},
        "max_pages_per_facet": {"type": "integer"},
        "start_page": {"type": "integer"},
        "window_cap": {"type": "integer"},
        "cursor_path": {"type": "string"},
        "facet_param": {"type": "string"},
        "facet_values": {"type": "array", "items": {"type": "string"}},
        "facet_values_path": {"type": "string"},
        "records_path": {"type": "string"},
        "fields": {"type": "object"},
        "selector": {"type": "string"},
        "source": {"type": "string", "enum": ["attribute", "text"]},
        "attribute": {"type": "string"},
        "record_selector": {"type": "string"},
        "field_selectors": {"type": "object"},
        "base_url": {"type": "string"},
        "field": {"type": "string"},
        "kind": {"type": "string"},
        "template": {"type": "string"},
        "mode": {"type": "string", "enum": ["strptime", "humanized", "iso"]},
        "format": {"type": "string"},
        "detail_fetch": {"type": "object"},
        "join_key": {"type": "string"},
        "error_keys": {"type": "array", "items": {"type": "string"}},
        "doc_id": {"type": "string"},
        "url_contains": {"type": "string"},
        "response_shape_path": {"type": "string"},
    }
    oracle_props = {
        "kind": {"type": "string", "enum": list(recipe_schema.ORACLE_KINDS)},
        "facet_path": {"type": "string"},
        "single_valued": {"type": "boolean"},
        "total_path": {"type": "string"},
        "window_cap": {"type": "integer"},
        "header_name": {"type": "string"},
        "sitemap_url": {"type": "string"},
        "url_pattern": {"type": "string"},
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "script_version": {"type": "integer", "const": recipe_schema.RECIPE_VERSION},
            "transport": {"type": "string", "enum": list(recipe_schema.TRANSPORTS)},
            "expected_min_jobs": {"type": "integer"},
            "base_url": {"type": "string"},
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": step_props,
                    "required": ["op"],
                },
            },
            "oracle": {
                "type": "object",
                "additionalProperties": False,
                "properties": oracle_props,
                "required": ["kind"],
            },
        },
        "required": ["script_version", "transport", "expected_min_jobs", "steps", "oracle"],
    }


RECIPE_OUTPUT_SCHEMA = build_recipe_output_schema()

SYSTEM_PROMPT = (
    "You author a deterministic, agent-free replay RECIPE for a company's careers "
    "board from an evidence report of one page load (network JSON responses, "
    "embedded JSON islands, repeated DOM classes). The recipe is later executed "
    "nightly by a plain HTTP runner — NO browser, NO LLM at replay time.\n\n"
    "Emit a single JSON object matching the provided schema:\n"
    "- transport 'http_json' when the jobs come from a JSON XHR/fetch endpoint; "
    "'http_html' when they live in an embedded JSON island (preferred) or, as a "
    "last resort, CSS-selectable DOM nodes.\n"
    "- steps: exactly one 'fetch' (https:// only) first; at most one pagination "
    "(paginate_offset/paginate_page/paginate_cursor/paginate_facet); exactly one "
    "extraction (extract_json_path/extract_embedded_island/extract_css). "
    "fields MUST map id, title, url (dotted paths or {templates}).\n"
    "- oracle: a completeness total. Use facet_sum ONLY with a SINGLE-VALUED facet "
    "(each job in exactly one bucket — a location facet that double-counts "
    "multi-site jobs is NOT single-valued); header for an X-*-Total-style count; "
    "sitemap for a <loc>-count; self_consistent when the board publishes no total.\n"
    "- expected_min_jobs: a conservative floor the board should never dip below.\n\n"
    "You may ONLY use the ops in the schema. If the board can only be read by "
    "clicking, scrolling a virtualized list, or a browser at read time, there is "
    "no valid recipe — do not invent one; the caller will REFUSE."
)


def _build_user_message(report: dict[str, Any], previous_error: str | None) -> str:
    parts = [
        "Evidence report for the careers page:",
        json.dumps(report, indent=1)[:180_000],
    ]
    if previous_error:
        parts.append(
            "\nYour previous attempt was rejected. Fix exactly this and try again:\n"
            + str(previous_error)[:2000]
        )
    parts.append("\nReturn the recipe JSON object now.")
    return "\n".join(parts)


def build_message_params(report: dict[str, Any], previous_error: str | None = None) -> dict[str, Any]:
    """The exact ``messages.create(...)`` kwargs. Single source of truth for the
    model, prompt, and structured-outputs schema (mirrors ``llm_client``)."""
    return {
        "model": SONNET_MODEL,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": _build_user_message(report, previous_error)}],
        "output_config": {"format": {"type": "json_schema", "schema": RECIPE_OUTPUT_SCHEMA}},
    }


def extract_text_content(response: object) -> str:
    return "".join(
        getattr(block, "text", "")
        for block in getattr(response, "content", [])
        if getattr(block, "type", None) == "text"
    ).strip()


async def author_script(
    report: dict[str, Any], *, previous_error: str | None = None
) -> dict[str, Any]:
    """One Sonnet call → a candidate recipe dict. RAISES on a keyless env
    (before building the client) or an unusable response."""
    api_key = settings.anthropic_api_key
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY unset; discovery cannot author a recipe")
        raise MissingAnthropicKeyError("anthropic_api_key is not configured")

    client = AsyncAnthropic(api_key=api_key, max_retries=0, timeout=AUTHOR_TIMEOUT_SECONDS)
    response = await client.messages.create(**build_message_params(report, previous_error))
    text = extract_text_content(response)
    if not text:
        raise DiscoveryAuthorError(
            f"author returned no text; stop_reason={getattr(response, 'stop_reason', None)!r}"
        )
    try:
        script = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DiscoveryAuthorError(f"author returned non-JSON: {exc}") from exc
    if not isinstance(script, dict):
        raise DiscoveryAuthorError(f"author returned a {type(script).__name__}, not an object")
    return script
