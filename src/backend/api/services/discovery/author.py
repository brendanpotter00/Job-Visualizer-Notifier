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


# The author emits the recipe by CALLING a forced tool rather than via strict
# structured output. A tool ``input_schema`` is a LENIENT JSON Schema — it is NOT
# subject to strict mode's additionalProperties / all-required / ≤16-union limits
# (those apply only to ``output_config.format.schema``, and cost us two pre-inference
# 400s: "additionalProperties must be false" then "too many union types"). So the
# schema is a small, ordinary recipe shape — op/transport/oracle.kind ENUMS for
# guidance, optional params simply omitted from ``required``, and the arbitrary maps
# (headers/body/fields/field_selectors/detail_fetch) as plain open objects. The model
# emits REAL nested JSON, so ``tool_use.input`` is already the recipe dict (no
# JSON-string coercion). The REAL gate is ``recipe_schema.validate_recipe``
# (unchanged) — this schema is only guidance; a malformed/invalid recipe fails the
# validator → the ≤2-attempt retry → REFUSE.
RECIPE_TOOL_NAME = "submit_recipe"


def build_recipe_tool_schema() -> dict[str, Any]:
    """The lenient ``submit_recipe`` tool ``input_schema`` (guidance, not the gate).

    Keeps the op/transport/oracle.kind ENUMS (still excluding the Phase-4 browser
    ops AND the unimplemented ``paginate_cursor``, so the model can only NAME a real
    op), lists a step's params as optional, and leaves the arbitrary maps as open
    objects. Deliberately shallow — depth/shape correctness is ``validate_recipe``'s job.
    """
    allowed_ops = sorted(
        set(recipe_schema._OP_VALIDATORS) - set(recipe_schema._BROWSER_OPS)
    )
    canonical_fields = ", ".join(
        [*recipe_schema.CANONICAL_REQUIRED_FIELDS, *recipe_schema.CANONICAL_OPTIONAL_FIELDS]
    )
    step_props: dict[str, Any] = {
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
        "facet_param": {"type": "string"},
        "facet_values": {"type": "array", "items": {"type": "string"}},
        "facet_values_path": {"type": "string"},
        "records_path": {"type": "string"},
        "fields": {
            "type": "object",
            "description": (
                f"map of canonical job fields ({canonical_fields}) to dotted "
                f"paths/templates; id, title, url required"
            ),
        },
        "selector": {"type": "string"},
        "source": {"type": "string", "enum": ["attribute", "text"]},
        "attribute": {"type": "string"},
        "record_selector": {"type": "string"},
        "field_selectors": {"type": "object"},
        "base_url": {"type": "string"},
        "field": {"type": "string"},
        "kind": {"type": "string", "enum": ["template", "base_url_join"]},
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
    oracle_props: dict[str, Any] = {
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
        "properties": {
            "script_version": {"type": "integer", "enum": [recipe_schema.RECIPE_VERSION]},
            "transport": {"type": "string", "enum": list(recipe_schema.TRANSPORTS)},
            "expected_min_jobs": {"type": "integer"},
            "base_url": {"type": "string"},
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": step_props,
                    "required": ["op"],
                },
            },
            "oracle": {
                "type": "object",
                "properties": oracle_props,
                "required": ["kind"],
            },
        },
        "required": ["script_version", "transport", "expected_min_jobs", "steps", "oracle"],
    }


RECIPE_TOOL: dict[str, Any] = {
    "name": RECIPE_TOOL_NAME,
    "description": (
        "Submit the deterministic replay recipe for this careers board. Emit real "
        "nested JSON (headers/body/fields are objects). Set only the keys each op "
        "uses; omit the rest."
    ),
    "input_schema": build_recipe_tool_schema(),
}

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
    "(paginate_offset/paginate_page/paginate_facet); exactly one "
    "extraction (extract_json_path/extract_embedded_island/extract_css). "
    "fields MUST map id, title, url (dotted paths or {templates}).\n"
    "- oracle: a completeness total. Use facet_sum ONLY with a SINGLE-VALUED facet "
    "(each job in exactly one bucket — a location facet that double-counts "
    "multi-site jobs is NOT single-valued); header for an X-*-Total-style count; "
    "sitemap for a <loc>-count; self_consistent when the board publishes no total.\n"
    "- expected_min_jobs: a conservative floor the board should never dip below.\n\n"
    "Emit the recipe by calling the submit_recipe tool with real nested JSON: set "
    "only the keys each op actually uses and omit the rest (headers/body/fields are "
    "objects, not strings). fields maps id/title/url (required) plus optionally "
    "location/posted_at/department/company to dotted paths or {templates}.\n"
    "You may ONLY use the ops in the tool schema. If the board can only be read by "
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
    parts.append("\nCall submit_recipe with the recipe now.")
    return "\n".join(parts)


def build_message_params(report: dict[str, Any], previous_error: str | None = None) -> dict[str, Any]:
    """The exact ``messages.create(...)`` kwargs. Single source of truth for the
    model, prompt, and the forced ``submit_recipe`` tool (mirrors ``llm_client``)."""
    return {
        "model": SONNET_MODEL,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": _build_user_message(report, previous_error)}],
        "tools": [RECIPE_TOOL],
        "tool_choice": {"type": "tool", "name": RECIPE_TOOL_NAME},
    }


def extract_tool_input(response: object, tool_name: str) -> Any:
    """The ``input`` of the first ``tool_name`` tool_use block, or ``None``.

    A ``tool_use`` block's ``.input`` is already a parsed dict (the SDK decodes it),
    so the authored recipe needs no JSON parsing — the model emits real nested JSON.
    """
    for block in getattr(response, "content", []):
        if (
            getattr(block, "type", None) == "tool_use"
            and getattr(block, "name", None) == tool_name
        ):
            return getattr(block, "input", None)
    return None


async def author_script(
    report: dict[str, Any], *, previous_error: str | None = None
) -> dict[str, Any]:
    """One Sonnet call → a candidate recipe dict, read from the forced
    ``submit_recipe`` tool call. RAISES on a keyless env (before building the
    client) or a response that carries no usable tool call."""
    api_key = settings.anthropic_api_key
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY unset; discovery cannot author a recipe")
        raise MissingAnthropicKeyError("anthropic_api_key is not configured")

    client = AsyncAnthropic(api_key=api_key, max_retries=0, timeout=AUTHOR_TIMEOUT_SECONDS)
    response = await client.messages.create(**build_message_params(report, previous_error))
    recipe = extract_tool_input(response, RECIPE_TOOL_NAME)
    if not isinstance(recipe, dict):
        raise DiscoveryAuthorError(
            f"author did not emit a {RECIPE_TOOL_NAME} tool call; "
            f"stop_reason={getattr(response, 'stop_reason', None)!r}"
        )
    return recipe
