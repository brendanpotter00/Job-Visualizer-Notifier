"""Runtime client for user-added custom sites scraped via a stored JSON recipe.

A ``custom_json`` company carries a *recipe* in ``companies.provider_config`` —
generated once at add-time by ``services/recipe_generator.py`` from a captured
network trace, then validated. This module replays that recipe on the normal
``*/30`` worker fan-out: a plain paginated HTTP call + field mapping. **No
browser, no LLM** — the recurring scrape costs exactly one HTTP round-trip per
page, same as any ATS client.

The recipe endpoint is fully user-controlled and re-hit forever, so every
request is routed through the SSRF guard (:mod:`services.url_guard`).

Recipe shape (``provider_config`` for ``ats='custom_json'``)::

    {
      "endpoint": "https://careers.example.com/api/jobs",
      "method": "GET" | "POST",
      "headers": { ... }?,                 # optional static headers
      "body_template": { ... }?,           # POST only; pagination param merged in
      "base_url": "https://careers.example.com",  # optional; resolves relative job urls
      "pagination": {
          "type": "offset" | "page" | "none",
          "param": "start",                # query/body key to advance
          "page_size": 20,
          "start": 0                        # first offset/page (default 0)
      },
      "list_path": "data.results",          # dotted path to the job array
      "field_map": {                        # dotted paths within one job object
          "id": "id",
          "title": "title",
          "location": "location.name",
          "url": "absoluteUrl",
          "posted_on": "postedDate"         # optional
      }
    }

``fetch_jobs`` returns the raw job dicts across pages;
``transform_to_job_listings`` maps them to :class:`JobListing` rows via the
recipe's ``field_map``. Kept as two functions to mirror every other
``*_client.py`` (pure fetch vs. pure transform).
"""

from __future__ import annotations

import copy
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urljoin

import httpx

from scripts.shared.constants import SourceId
from scripts.shared.models import JobListing
from scripts.shared.utils import get_iso_timestamp

from . import url_guard

logger = logging.getLogger(__name__)

SOURCE_ID = SourceId.CUSTOM_JSON
DEFAULT_TIMEOUT_SECONDS = 20.0
# Bound the pagination walk. 200 pages × a typical page_size covers very large
# boards while stopping a runaway recipe from looping forever.
MAX_PAGES = 200
# Clamp a recipe-declared page size so a bad recipe can't request 10^9 rows.
MAX_PAGE_SIZE = 200
_REQUIRED_RECIPE_KEYS = ("endpoint", "list_path", "field_map")


class RecipeError(ValueError):
    """Raised when a recipe is structurally invalid. ValueError so the fetch
    task records it as an expected error rather than crashing the worker."""


def _resolve_path(obj: Any, path: str) -> Any:
    """Resolve a dotted path with optional ``[index]`` segments against ``obj``.

    Supports ``a.b.c`` and ``a[0].b`` and a trailing ``[*]`` (ignored — the
    caller treats the resolved value as the list). Returns ``None`` if any
    segment is missing, rather than raising, so a partially-shaped job row maps
    to ``None`` fields instead of aborting the whole scrape. Deliberately NOT a
    full JSONPath engine — keeps the recurring hot path dependency-free and
    predictable.
    """
    if not path:
        return obj
    current = obj
    for raw_segment in path.split("."):
        segment = raw_segment.strip()
        if not segment:
            continue
        # Split "key[0][1]" into key + indices.
        key = segment.split("[", 1)[0]
        if key:
            if not isinstance(current, dict) or key not in current:
                return None
            current = current[key]
        # Apply any [n] indices (skip a trailing [*]).
        for idx_token in _bracket_indices(segment):
            if idx_token == "*":
                continue
            try:
                index = int(idx_token)
            except ValueError:
                return None
            if not isinstance(current, list) or not (-len(current) <= index < len(current)):
                return None
            current = current[index]
    return current


def _bracket_indices(segment: str) -> list[str]:
    """Extract the ``n`` tokens from ``key[1][2]`` → ``['1', '2']``."""
    out: list[str] = []
    depth_start = segment.find("[")
    rest = segment[depth_start:] if depth_start != -1 else ""
    token = ""
    inside = False
    for ch in rest:
        if ch == "[":
            inside = True
            token = ""
        elif ch == "]":
            if inside:
                out.append(token.strip())
            inside = False
        elif inside:
            token += ch
    return out


def _validate_recipe(recipe: dict[str, Any]) -> None:
    missing = [k for k in _REQUIRED_RECIPE_KEYS if not recipe.get(k)]
    if missing:
        raise RecipeError(f"recipe missing required keys: {missing}")
    field_map = recipe.get("field_map")
    if not isinstance(field_map, dict) or not all(
        field_map.get(k) for k in ("id", "title", "url")
    ):
        raise RecipeError("recipe field_map must map id, title and url")


def _page_size(recipe: dict[str, Any]) -> int:
    pagination = recipe.get("pagination") or {}
    size = pagination.get("page_size", 20)
    try:
        size = int(size)
    except (TypeError, ValueError):
        size = 20
    return max(1, min(size, MAX_PAGE_SIZE))


async def fetch_jobs(provider_config: dict[str, Any], http: httpx.AsyncClient) -> list[dict]:
    """Replay the recipe and return the raw job dicts across all pages.

    Raises
    ------
    RecipeError
        Recipe is structurally invalid.
    url_guard.BlockedURLError
        Endpoint (or a page thereof) points at a non-public host.
    httpx.HTTPError
        Transport / non-2xx failure — surfaced so Procrastinate retries.
    """
    _validate_recipe(provider_config)

    endpoint = provider_config["endpoint"]
    method = str(provider_config.get("method", "GET")).upper()
    headers = provider_config.get("headers") or {}
    list_path = provider_config["list_path"]
    pagination = provider_config.get("pagination") or {}
    ptype = str(pagination.get("type", "none")).lower()
    param = pagination.get("param")
    page_size = _page_size(provider_config)
    start = int(pagination.get("start", 0) or 0)

    all_items: list[dict] = []
    for page in range(MAX_PAGES):
        cursor = start + (page * page_size if ptype == "offset" else page)
        params, body = _build_page_request(
            provider_config, ptype, param, cursor, page_size
        )

        url_guard.validate_public_url(endpoint)
        if method == "POST":
            response = await http.post(
                endpoint, json=body, params=params, headers=headers,
                timeout=DEFAULT_TIMEOUT_SECONDS, follow_redirects=False,
            )
        else:
            response = await http.get(
                endpoint, params=params, headers=headers,
                timeout=DEFAULT_TIMEOUT_SECONDS, follow_redirects=False,
            )
        if response.is_redirect:
            raise url_guard.BlockedURLError(
                f"custom_json endpoint {endpoint!r} returned a redirect; refusing "
                "to follow (would bypass SSRF validation)"
            )
        if len(response.content) > url_guard.MAX_RESPONSE_BYTES:
            raise RecipeError(f"custom_json response exceeded size cap for {endpoint!r}")
        response.raise_for_status()

        payload = response.json()
        items = _resolve_path(payload, list_path)
        if not isinstance(items, list):
            if page == 0:
                raise RecipeError(
                    f"list_path {list_path!r} did not resolve to a list "
                    f"(got {type(items).__name__})"
                )
            break  # a later page returning non-list = end of data
        if not items:
            break
        all_items.extend(i for i in items if isinstance(i, dict))
        if ptype == "none" or len(items) < page_size:
            break

    logger.info(
        "custom_json fetched %d raw items from %s in %d page(s)",
        len(all_items), endpoint, page + 1,
    )
    return all_items


def _build_page_request(
    recipe: dict[str, Any],
    ptype: str,
    param: Optional[str],
    cursor: int,
    page_size: int,
) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    """Return ``(query_params, json_body)`` for one page of the recipe."""
    method = str(recipe.get("method", "GET")).upper()
    if ptype == "none" or not param:
        if method == "POST":
            return {}, copy.deepcopy(recipe.get("body_template") or {})
        return {}, None

    if method == "POST":
        body = copy.deepcopy(recipe.get("body_template") or {})
        body[param] = cursor
        # Common Workday-ish shape: also pass a limit alongside the offset.
        body.setdefault("limit", page_size)
        return {}, body
    return {param: cursor}, None


# --- transform ---------------------------------------------------------------


def _parse_timestamp(value: Any) -> Optional[str]:
    """Best-effort convert a recipe-mapped ``posted_on`` value to ISO 8601.

    Accepts ISO strings and Unix epoch seconds/milliseconds. Returns None on any
    failure so a bad source value never becomes a wrong date.
    """
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        num = float(value)
        if num > 1e11:  # looks like milliseconds
            num /= 1000.0
        try:
            return datetime.fromtimestamp(num, tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
        except ValueError:
            return value  # store the raw string; better than dropping it
    return None


def transform_to_job_listings(
    company_id: str,
    raw_items: list[dict],
    provider_config: dict[str, Any],
) -> list[JobListing]:
    """Map raw recipe items to :class:`JobListing` rows via ``field_map``.

    Drops rows missing id / title / a resolvable absolute url. Relative urls are
    resolved against ``recipe.base_url`` (or the endpoint origin). Dedups by id.
    """
    field_map = provider_config.get("field_map") or {}
    base_url = provider_config.get("base_url") or provider_config.get("endpoint", "")
    now = get_iso_timestamp()

    deduped: dict[str, JobListing] = {}
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        job_id = _resolve_path(raw, field_map.get("id", ""))
        title = _resolve_path(raw, field_map.get("title", ""))
        url_val = _resolve_path(raw, field_map.get("url", ""))
        if job_id in (None, "") or not isinstance(title, str) or not title.strip():
            continue
        url = _normalize_url(url_val, base_url)
        if url is None:
            continue

        location = _resolve_path(raw, field_map.get("location", "")) if field_map.get("location") else None
        posted_on = _parse_timestamp(
            _resolve_path(raw, field_map["posted_on"]) if field_map.get("posted_on") else None
        )
        job_id_str = str(job_id)
        deduped[job_id_str] = JobListing(
            id=job_id_str,
            title=title.strip(),
            company=company_id,
            location=location if isinstance(location, str) and location.strip() else None,
            url=url,
            source_id=SOURCE_ID,
            details={
                "experience_level": None,
                "is_remote_eligible": False,
                "custom_source": True,
            },
            posted_on=posted_on,
            created_at=now,
            first_seen_at=now,
            last_seen_at=now,
            consecutive_misses=0,
            details_scraped=True,
            status="OPEN",
            has_matched=False,
            ai_metadata={},
            closed_on=None,
        )
    return list(deduped.values())


def _normalize_url(value: Any, base_url: str) -> Optional[str]:
    """Return an absolute http(s) URL from ``value``, or None if unusable."""
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    if candidate.startswith(("http://", "https://")):
        return candidate
    if base_url:
        joined = urljoin(base_url, candidate)
        if joined.startswith(("http://", "https://")):
            return joined
    return None
