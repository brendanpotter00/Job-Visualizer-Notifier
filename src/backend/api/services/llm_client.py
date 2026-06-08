"""Tier 2 of the location-normalization cascade: the Claude Haiku client.

Invoked ONLY on Tier-1 (alias cache) misses by the Unit-5 ``normalize_location``
task. Given one raw free-text location string, asks Claude Haiku 4.5 to return
one OR MORE canonical locations as structured JSON, validated into
``list[CanonicalLocation]``.

Design constraints (locked decisions — do not "simplify" away):

* **NO lat/lng** (Decision #7).
* **Per-location ``confidence``** (Decision #9) surfaced here; the floor is applied in Unit 5.
* **No retry library.** Procrastinate owns retries — client built with ``max_retries=0`` + ``timeout=10.0``.
* **Graceful degradation when ANTHROPIC_API_KEY is unset:** raise ``MissingAnthropicKeyError`` BEFORE
  constructing the client / making any call. Unit 5 catches it and degrades without burning retries.

Makes NO database calls (Decision #3 keeps the DB connection closed across the LLM call).
"""

from __future__ import annotations

import json
import logging

import anthropic
from anthropic import AsyncAnthropic
from pydantic import BaseModel, ValidationError, field_validator

from ..config import settings

logger = logging.getLogger(__name__)

HAIKU_MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1024
LLM_TIMEOUT_SECONDS = 10.0
_VALID_KINDS = {"city", "region", "country", "remote"}


class LocationLLMError(Exception):
    """Base error: response unparseable into >=1 valid location. Lets Procrastinate retry."""


class MissingAnthropicKeyError(LocationLLMError):
    """anthropic_api_key falsy. Unit 5 catches this specifically and degrades WITHOUT retries."""


class CanonicalLocation(BaseModel):
    """One canonical location. NO lat/lng (Decision #7)."""

    canonical_name: str
    kind: str
    city: str | None = None
    region: str | None = None
    country: str | None = None
    remote_scope: str | None = None
    confidence: float

    @field_validator("kind")
    @classmethod
    def _kind_must_be_valid(cls, v: str) -> str:
        if v not in _VALID_KINDS:
            raise ValueError(f"kind must be one of {sorted(_VALID_KINDS)}; got {v!r}")
        return v

    @field_validator("confidence")
    @classmethod
    def _confidence_in_unit_range(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"confidence must be in [0, 1]; got {v}")
        return v


class _LocationsEnvelope(BaseModel):
    locations: list[CanonicalLocation]


SYSTEM_PROMPT = (
    "You normalize messy free-text job-posting location strings into a list of "
    "canonical locations. A single input string may contain ONE OR MORE "
    "locations (e.g. 'Sunnyvale, CA, USA; Kirkland, WA, USA' is two). For each "
    "location, return:\n"
    "- canonical_name: a clean human-readable label. For cities use "
    "'City, REGION, COUNTRY' with short region/country codes when unambiguous "
    "(e.g. 'San Francisco, CA, US'). For remote, use 'Remote (US)', 'Remote (EU)', "
    "or 'Remote (Global)'.\n"
    "- kind: one of 'city', 'region', 'country', or 'remote'.\n"
    "- city, region, country: the structured parts (short codes, e.g. 'CA', 'US'). "
    "Set a part to null when it does not apply for the kind.\n"
    "- remote_scope: ONLY for kind='remote'. Use 'us', 'eu', a code, or 'global' "
    "when unscoped/worldwide. Null for non-remote kinds.\n"
    "- confidence: your confidence in this single parsed location, 0.0 to 1.0.\n"
    "Strip embedded building/site codes, parenthetical annotations like '(HQ)', and "
    "reorder reversed inputs (e.g. 'United States, Washington, Redmond' is Redmond, "
    "WA, US). Do NOT invent coordinates. Do NOT include latitude or longitude."
)

FEW_SHOT_GUIDE = (
    "Examples:\n"
    'Input: "San Francisco, CA"\n'
    'Output: {"locations": [{"canonical_name": "San Francisco, CA, US", '
    '"kind": "city", "city": "San Francisco", "region": "CA", "country": "US", '
    '"remote_scope": null, "confidence": 0.97}]}\n'
    'Input: "Sunnyvale, CA, USA; Kirkland, WA, USA"\n'
    'Output: {"locations": [{"canonical_name": "Sunnyvale, CA, US", '
    '"kind": "city", "city": "Sunnyvale", "region": "CA", "country": "US", '
    '"remote_scope": null, "confidence": 0.96}, '
    '{"canonical_name": "Kirkland, WA, US", "kind": "city", "city": "Kirkland", '
    '"region": "WA", "country": "US", "remote_scope": null, "confidence": 0.96}]}\n'
    'Input: "Remote - United States"\n'
    'Output: {"locations": [{"canonical_name": "Remote (US)", "kind": "remote", '
    '"city": null, "region": null, "country": null, "remote_scope": "us", '
    '"confidence": 0.95}]}\n'
    'Input: "Remote"\n'
    'Output: {"locations": [{"canonical_name": "Remote (Global)", '
    '"kind": "remote", "city": null, "region": null, "country": null, '
    '"remote_scope": "global", "confidence": 0.9}]}'
)

_LOCATIONS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "locations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "canonical_name": {"type": "string"},
                    "kind": {"type": "string", "enum": ["city", "region", "country", "remote"]},
                    "city": {"type": ["string", "null"]},
                    "region": {"type": ["string", "null"]},
                    "country": {"type": ["string", "null"]},
                    "remote_scope": {"type": ["string", "null"]},
                    "confidence": {"type": "number"},
                },
                "required": ["canonical_name", "kind", "city", "region", "country", "remote_scope", "confidence"],
            },
        }
    },
    "required": ["locations"],
}


def _build_user_message(raw: str) -> str:
    return f'{FEW_SHOT_GUIDE}\n\nNow normalize this input:\n"{raw}"'


def _parse_envelope(raw_obj: object) -> list[CanonicalLocation]:
    try:
        envelope = _LocationsEnvelope.model_validate(raw_obj)
    except ValidationError as exc:
        raise LocationLLMError(f"LLM response failed schema validation: {exc}") from exc
    if not envelope.locations:
        raise LocationLLMError("LLM returned zero locations for a non-empty input")
    return envelope.locations


async def normalize_location_via_llm(raw: str) -> list[CanonicalLocation]:
    """Normalize one raw location string via Claude Haiku 4.5.

    Raises:
        MissingAnthropicKeyError: no key configured. No client built, no call made.
        LocationLLMError: response unparseable into >=1 valid location.
        anthropic.APIError / anthropic.APITimeoutError: propagate so Procrastinate retries.
    """
    api_key = settings.anthropic_api_key  # read at call time
    if not api_key:
        logger.warning(
            "ANTHROPIC_API_KEY is not set; skipping Tier-2 LLM normalization for %r. "
            "Job will remain unnormalized for the safety-net.", raw,
        )
        raise MissingAnthropicKeyError("anthropic_api_key is not configured")

    client = AsyncAnthropic(api_key=api_key, max_retries=0, timeout=LLM_TIMEOUT_SECONDS)

    # ---- PATH A (PRIMARY): structured outputs ----
    response = await client.messages.create(
        model=HAIKU_MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_user_message(raw)}],
        output_config={"format": {"type": "json_schema", "schema": _LOCATIONS_SCHEMA}},
    )
    text = "".join(
        getattr(block, "text", "")
        for block in response.content
        if getattr(block, "type", None) == "text"
    ).strip()
    if not text:
        raise LocationLLMError(
            f"LLM returned no text content for {raw!r}; "
            f"stop_reason={getattr(response, 'stop_reason', None)!r}"
        )
    try:
        raw_obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LocationLLMError(f"LLM returned non-JSON text for {raw!r}: {exc}") from exc
    return _parse_envelope(raw_obj)


async def _call_via_forced_tool_use(client: AsyncAnthropic, raw: str) -> list[CanonicalLocation]:
    """PATH B fallback. If Step 0 picks this, replace the PATH A block in
    normalize_location_via_llm with `return await _call_via_forced_tool_use(client, raw)`.
    Ship only ONE active path."""
    response = await client.messages.create(
        model=HAIKU_MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_user_message(raw)}],
        tools=[{
            "name": "emit_locations",
            "description": "Emit the normalized canonical location(s) parsed from the raw input string.",
            "input_schema": _LOCATIONS_SCHEMA,
        }],
        tool_choice={"type": "tool", "name": "emit_locations"},
    )
    tool_input = None
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "emit_locations":
            tool_input = block.input
            break
    if tool_input is None:
        raise LocationLLMError(
            f"LLM did not return the forced emit_locations tool_use for {raw!r}; "
            f"stop_reason={getattr(response, 'stop_reason', None)!r}"
        )
    return _parse_envelope(tool_input)
