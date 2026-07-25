"""One-time Claude Haiku recipe generation for a custom (non-ATS) career site.

This is the ONLY place an LLM is involved in the add-company feature, and it runs
**once per company at add time** — never on the recurring scrape. Given a set of
JSON API calls captured from the site's careers page (by the Playwright step in
``tasks/onboard_custom_company.py``), it asks Claude Haiku to pick the call that
returns the job list and emit a ``custom_json`` *recipe* (endpoint, pagination,
field map). The recipe is then **validated deterministically** by the caller
(run it, require >=1 real job) before anything is stored — the model's output is
never trusted blind.

Mirrors ``services/llm_client.py`` exactly: reads ``settings.anthropic_api_key``
at call time, raises :class:`MissingAnthropicKeyError` when unset (graceful
degrade — the onboarding task marks the submission ``failed`` instead of
crashing), builds an ``AsyncAnthropic(max_retries=0)`` client, and uses the
structured-outputs (``json_schema``) call path.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from anthropic import AsyncAnthropic
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from ..config import settings

logger = logging.getLogger(__name__)

HAIKU_MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1024
LLM_TIMEOUT_SECONDS = 30.0
# Keep each captured sample small so a big response can't blow the token budget.
MAX_SAMPLE_CHARS = 6000
MAX_CANDIDATES = 12


class RecipeGenerationError(Exception):
    """Recipe could not be generated / parsed. Onboarding marks submission failed."""


class MissingAnthropicKeyError(RecipeGenerationError):
    """ANTHROPIC_API_KEY unset. Caught specifically so we degrade without retries."""


class _Pagination(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: str  # 'offset' | 'page' | 'none'
    param: str | None = None
    page_size: int = 20
    start: int = 0

    @field_validator("type")
    @classmethod
    def _known_type(cls, v: str) -> str:
        if v not in ("offset", "page", "none"):
            raise ValueError(f"pagination.type must be offset|page|none; got {v!r}")
        return v


class _FieldMap(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    title: str
    url: str
    location: str | None = None
    posted_on: str | None = None


class RecipeModel(BaseModel):
    """Validated recipe = the ``provider_config`` for a ``custom_json`` company."""

    model_config = ConfigDict(extra="ignore")
    endpoint: str
    method: str = "GET"
    list_path: str
    field_map: _FieldMap
    pagination: _Pagination
    base_url: str | None = None
    body_template: dict[str, Any] | None = None
    headers: dict[str, str] | None = None

    @field_validator("method")
    @classmethod
    def _known_method(cls, v: str) -> str:
        up = v.upper()
        if up not in ("GET", "POST"):
            raise ValueError(f"method must be GET or POST; got {v!r}")
        return up

    @field_validator("endpoint")
    @classmethod
    def _http_endpoint(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("endpoint must be an absolute http(s) URL")
        return v


SYSTEM_PROMPT = (
    "You are a web-scraping engineer. You are given several JSON API responses "
    "captured from a company's careers page. Exactly one of them is the endpoint "
    "that returns the list of job postings. Identify it and produce a machine "
    "recipe that another program will replay (with NO browser) to fetch jobs.\n\n"
    "Rules:\n"
    "- Choose the single request whose JSON contains an array of job postings.\n"
    "- 'list_path' is the dotted path from the response root to that array "
    "(e.g. 'data.jobs' or 'jobPostings'); '' if the root itself is the array.\n"
    "- 'field_map' values are dotted paths WITHIN one job object to that job's "
    "id, title, url, and (optionally) location and posted_on. Use '[0]' for "
    "array indexing (e.g. 'locations[0].name').\n"
    "- 'pagination': if the request pages via an offset query/body param use "
    "type 'offset' with that 'param' and the observed 'page_size'; if it pages "
    "by page-number use 'page'; if all jobs come in one response use 'none' with "
    "param null.\n"
    "- For a POST endpoint put the observed request JSON (minus the paging field) "
    "in 'body_template'; otherwise null.\n"
    "- 'base_url' is the site origin used to resolve relative job urls, or null.\n"
    "- Only use endpoints and fields actually present in the captured data. If "
    "none of the captured responses is a job list, still return your best guess "
    "for the most likely endpoint; the caller validates it."
)


def _truncate(obj: Any) -> str:
    text = json.dumps(obj, default=str)
    if len(text) > MAX_SAMPLE_CHARS:
        return text[:MAX_SAMPLE_CHARS] + "…(truncated)"
    return text


def _build_user_message(page_url: str, candidates: list[dict[str, Any]]) -> str:
    lines = [f"Careers page: {page_url}", "", "Captured JSON API responses:"]
    for i, cand in enumerate(candidates[:MAX_CANDIDATES]):
        lines.append(
            f"\n[{i}] {cand.get('method', 'GET')} {cand.get('url', '')}\n"
            f"response sample: {_truncate(cand.get('sample'))}"
        )
    lines.append("\nReturn the recipe for the job-list endpoint.")
    return "\n".join(lines)


_RECIPE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "endpoint": {"type": "string"},
        "method": {"type": "string", "enum": ["GET", "POST"]},
        "list_path": {"type": "string"},
        "base_url": {"type": ["string", "null"]},
        "body_template": {"type": ["object", "null"]},
        "field_map": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "id": {"type": "string"},
                "title": {"type": "string"},
                "url": {"type": "string"},
                "location": {"type": ["string", "null"]},
                "posted_on": {"type": ["string", "null"]},
            },
            "required": ["id", "title", "url", "location", "posted_on"],
        },
        "pagination": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "type": {"type": "string", "enum": ["offset", "page", "none"]},
                "param": {"type": ["string", "null"]},
                "page_size": {"type": "integer"},
                "start": {"type": "integer"},
            },
            "required": ["type", "param", "page_size", "start"],
        },
    },
    "required": [
        "endpoint", "method", "list_path", "base_url",
        "body_template", "field_map", "pagination",
    ],
}


def build_message_params(page_url: str, candidates: list[dict[str, Any]]) -> dict:
    """The exact ``messages.create(...)`` kwargs. Isolated for testability."""
    return {
        "model": HAIKU_MODEL,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM_PROMPT,
        "messages": [
            {"role": "user", "content": _build_user_message(page_url, candidates)}
        ],
        "output_config": {"format": {"type": "json_schema", "schema": _RECIPE_SCHEMA}},
    }


def _extract_text(response: object) -> str:
    return "".join(
        getattr(block, "text", "")
        for block in getattr(response, "content", [])
        if getattr(block, "type", None) == "text"
    ).strip()


def parse_recipe_text(text: str) -> dict[str, Any]:
    """Parse + validate a model text payload into a recipe dict.

    Raises :class:`RecipeGenerationError` on empty / non-JSON / schema-invalid.
    """
    if not text:
        raise RecipeGenerationError("LLM returned no text content")
    try:
        raw_obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RecipeGenerationError(f"LLM returned non-JSON: {exc}") from exc
    try:
        recipe = RecipeModel.model_validate(raw_obj)
    except ValidationError as exc:
        raise RecipeGenerationError(f"recipe failed schema validation: {exc}") from exc
    return recipe.model_dump(exclude_none=True)


async def generate_recipe(
    page_url: str, candidates: list[dict[str, Any]]
) -> dict[str, Any]:
    """Generate a ``custom_json`` recipe from captured API calls via Claude Haiku.

    ``candidates`` is a list of ``{method, url, sample}`` where ``sample`` is the
    (JSON-decoded) response body. Returns a recipe dict suitable for
    ``companies.provider_config``. The caller MUST still validate it by running
    the recipe before storing.

    Raises
    ------
    MissingAnthropicKeyError
        ANTHROPIC_API_KEY unset.
    RecipeGenerationError
        No candidates, or the model output is unparseable/invalid.
    anthropic.APIError
        Propagates so the onboarding task's retry policy applies.
    """
    if not candidates:
        raise RecipeGenerationError("no candidate JSON API responses were captured")

    api_key = settings.anthropic_api_key
    if not api_key:
        logger.warning(
            "ANTHROPIC_API_KEY is not set; cannot generate a custom-site recipe for %s",
            page_url,
        )
        raise MissingAnthropicKeyError("anthropic_api_key is not configured")

    client = AsyncAnthropic(api_key=api_key, max_retries=0, timeout=LLM_TIMEOUT_SECONDS)
    response = await client.messages.create(
        **build_message_params(page_url, candidates)
    )
    return parse_recipe_text(_extract_text(response))
