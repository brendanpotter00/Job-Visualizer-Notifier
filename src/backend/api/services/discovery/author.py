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

SYSTEM_PROMPT = """\
You author a deterministic, agent-free replay RECIPE for a company's careers board \
from an evidence report of one page load (network JSON responses, embedded JSON \
islands, repeated DOM classes). The recipe is executed nightly by a plain HTTP \
runner — NO browser, NO LLM at replay time.

Emit the recipe by CALLING the submit_recipe tool with real nested JSON (headers, \
body, fields, field_selectors are objects, not strings). The tool schema is lenient \
and does NOT check per-op keys — THIS PROMPT is the only place the exact key names \
are defined, and a separate strict validator then rejects the recipe if it carries \
ANY key not listed below for that op or oracle.kind. Set ONLY the keys each op / \
oracle actually uses and omit the rest. An unknown key, a typo, or a key borrowed \
from a different op is rejected with "unknown key(s) [...]" and burns your one retry.

TOP-LEVEL OBJECT — use exactly these keys, nothing else:
  script_version    integer, must be 1
  transport         "http_json" or "http_html"
  expected_min_jobs integer > 0 — a conservative floor the board never dips below
  steps             non-empty array of step objects (see below)
  oracle            object (see below)
  base_url          optional string
Do NOT put recipe_version, target, kind, entrypoint, pagination, records_path, \
fields, or total_path at the TOP level. records_path/fields live INSIDE an extract \
step; total_path lives INSIDE the oracle.

TRANSPORT:
  http_json — jobs come from a JSON XHR/fetch endpoint (pair with extract_json_path).
  http_html — jobs live in an embedded JSON island (pair with extract_embedded_island, \
preferred) or, last resort, CSS-selectable DOM nodes (pair with extract_css).

STEPS — cardinality: EXACTLY ONE 'fetch' and it MUST be the first step; AT MOST ONE \
pagination; EXACTLY ONE extraction. Each step is an object with an "op" plus ONLY \
that op's keys (required unless marked optional):
  fetch            method ("GET"|"POST", default GET), url (https:// only), \
headers (object, optional), body (object, optional)
  paginate_offset  param (str), page_size (int>0), max_pages (int>0), \
window_cap (int>0, optional)
  paginate_page    param (str), page_size (int>0), max_pages (int>0), \
start_page (int, optional), window_cap (int>0, optional)
  paginate_facet   facet_param (str); EITHER facet_values (non-empty array of \
strings) OR facet_values_path (str); page_size (int>0), max_pages_per_facet (int>0), \
window_cap (int>0, optional)
  extract_json_path        records_path (str; "" means the payload itself is the \
top-level array), fields (object)
  extract_embedded_island  selector (str), records_path (str; "" allowed), \
source ("attribute"|"text", default attribute), attribute (str, required when \
source="attribute"), fields (object), base_url (str, optional)
  extract_css              record_selector (str), field_selectors (object), \
base_url (str, optional)
  transform        field (str), kind ("template"|"base_url_join"); template (str) \
when kind="template", base_url (str) when kind="base_url_join"
  parse_date       field (str), mode ("strptime"|"humanized"|"iso"); format (str) \
required when mode="strptime"
  dedupe_key       field (str)
  assert_status              no keys
  assert_no_inband_error     error_keys (non-empty array of strings)
  assert_pinned_operation    at least one of doc_id (str), url_contains (str), \
response_shape_path (str)
  assert_cap_not_hit         window_cap (int>0)
  assert_page_advances       no keys
  assert_unique_ids_vs_total no keys
  assert_unique              field (str)
  assert_delta_vs_last_run   no keys

The `fields` object (extract_json_path / extract_embedded_island) and the \
`field_selectors` object (extract_css) map canonical job fields to dotted paths or \
{templates}: id, title, url are REQUIRED; location, posted_at, department, company \
are optional. Use only those field names.

ORACLE — a completeness total. Set oracle.kind, then ONLY that kind's extra keys:
  facet_sum       facet_path (str), single_valued (MUST be true — each job in \
exactly ONE bucket; a location facet that double-counts multi-site jobs is NOT \
single-valued), window_cap (int>0, optional), total_path (str, optional).
  header          header_name (str, e.g. "X-Total-Count"). NO total_path.
  sitemap         sitemap_url (https:// str), url_pattern (str). NO total_path.
  declared_probed total_path (str) — the dotted path to a board-declared grand total \
in the JSON body (e.g. "hits"). This is its ONLY extra key. Use declared_probed \
(NOT header) when the total is a number in the response body.
  self_consistent no extra keys. Use when the board publishes no total. NO total_path.
total_path is a valid key ONLY on facet_sum and declared_probed. Putting total_path \
(or window_cap, facet_path, header_name, ...) on the wrong kind is the classic \
"unknown key(s)" rejection — match the key list to your chosen kind exactly.

COMPLETE, VALID EXAMPLE (Amazon-style http_json + facet_sum). Copy this shape; keep \
only the keys shown:
{
  "script_version": 1,
  "transport": "http_json",
  "expected_min_jobs": 500,
  "steps": [
    {"op": "fetch", "method": "GET",
     "url": "https://www.amazon.jobs/en/search.json?sort=recent&facets[]=is_intern",
     "headers": {}},
    {"op": "paginate_facet",
     "facet_param": "normalized_country_code_facet[]",
     "facet_values": ["USA", "IND", "GBR", "CAN", "DEU"],
     "page_size": 100, "max_pages_per_facet": 100, "window_cap": 10000},
    {"op": "extract_json_path", "records_path": "jobs",
     "fields": {"id": "id_icims", "title": "title",
                "url": "https://www.amazon.jobs{job_path}",
                "location": "normalized_location", "posted_at": "posted_date",
                "department": "job_category", "company": "company_name"}},
    {"op": "parse_date", "field": "posted_at", "mode": "strptime", "format": "%B %d, %Y"},
    {"op": "dedupe_key", "field": "id"},
    {"op": "assert_cap_not_hit", "window_cap": 10000},
    {"op": "assert_page_advances"},
    {"op": "assert_unique", "field": "id"}
  ],
  "oracle": {"kind": "facet_sum", "facet_path": "facets.is_intern",
             "single_valued": true, "window_cap": 10000, "total_path": "hits"}
}

You may ONLY use the ops listed above. If the board can only be read by clicking, \
scrolling a virtualized list, or a browser at read time, there is no valid recipe — \
do not invent one; the caller will REFUSE."""


def _build_user_message(report: dict[str, Any], previous_error: str | None) -> str:
    parts = [
        "Evidence report for the careers page:",
        json.dumps(report, indent=1)[:180_000],
    ]
    if previous_error:
        parts.append(
            "\nYOUR PREVIOUS ATTEMPT WAS REJECTED. The validator message below names "
            "the exact op or oracle.kind and the exact offending key. A key it calls "
            "an \"unknown key\" is NOT accepted on that op/oracle — the schema does not "
            "have it there; a key it calls missing/invalid must be added or fixed. "
            "Re-read the ALLOWED KEYS for that specific op (or that oracle.kind) in the "
            "instructions above and rebuild the recipe using ONLY those keys. Do not "
            "invent keys, do not rename them, and do not move the same wrong key to "
            "another step. Common case: total_path is valid ONLY on a facet_sum or "
            "declared_probed oracle — never on header/sitemap/self_consistent.\n"
            "Validator error:\n"
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
