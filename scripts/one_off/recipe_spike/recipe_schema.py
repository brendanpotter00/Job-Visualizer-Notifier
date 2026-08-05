"""Scrape-recipe schema v1 (spike candidate).

Imported by BOTH capture-side and replay-side code. It is pure data
definition and validation: it must never import an agent, an LLM client,
or a browser driver.
"""

from __future__ import annotations

from typing import Any

RECIPE_VERSION = 1

KINDS = ("http_json", "http_html", "browser_dom")

PAGINATION_STYLES = ("none", "offset", "page", "cursor")


class RecipeError(ValueError):
    """Raised when a recipe is structurally invalid."""


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise RecipeError(msg)


def validate_recipe(recipe: dict[str, Any]) -> dict[str, Any]:
    """Validate a recipe dict, raising RecipeError naming what is wrong.

    Validation runs on write AND on read: a stored recipe is data, not code,
    and drifts.
    """
    _require(isinstance(recipe, dict), "recipe must be an object")
    _require(
        recipe.get("recipe_version") == RECIPE_VERSION,
        f"recipe_version must be {RECIPE_VERSION}, got {recipe.get('recipe_version')!r}",
    )

    kind = recipe.get("kind")
    _require(kind in KINDS, f"kind must be one of {KINDS}, got {kind!r}")

    entry = recipe.get("entrypoint")
    _require(isinstance(entry, dict), "entrypoint must be an object")
    method = entry.get("method", "GET")
    _require(method in ("GET", "POST"), f"entrypoint.method must be GET or POST, got {method!r}")
    url = entry.get("url")
    _require(
        isinstance(url, str) and url.startswith("https://"),
        "entrypoint.url must be an https:// string",
    )
    _require(
        isinstance(entry.get("headers", {}), dict),
        "entrypoint.headers must be an object when present",
    )

    pagination = recipe.get("pagination") or {"style": "none"}
    _require(isinstance(pagination, dict), "pagination must be an object")
    style = pagination.get("style", "none")
    _require(
        style in PAGINATION_STYLES,
        f"pagination.style must be one of {PAGINATION_STYLES}, got {style!r}",
    )
    if style in ("offset", "page"):
        _require(
            isinstance(pagination.get("param"), str),
            f"pagination.param is required for style={style!r}",
        )
        _require(
            isinstance(pagination.get("page_size"), int) and pagination["page_size"] > 0,
            f"pagination.page_size must be a positive int for style={style!r}",
        )
        _require(
            isinstance(pagination.get("max_pages"), int) and pagination["max_pages"] > 0,
            f"pagination.max_pages must be a positive int for style={style!r}",
        )
        if style == "page":
            _require(
                isinstance(pagination.get("start_page", 1), int),
                "pagination.start_page must be an int when present",
            )

    fields = recipe.get("fields")
    _require(isinstance(fields, dict), "fields must be an object")
    for required_field in ("id", "title", "url"):
        _require(
            isinstance(fields.get(required_field), str) and fields[required_field],
            f"fields.{required_field} is required",
        )

    minimum = recipe.get("expected_min_jobs")
    _require(
        isinstance(minimum, int) and minimum > 0,
        "expected_min_jobs must be a positive int",
    )

    if kind == "http_json":
        _require(
            isinstance(recipe.get("records_path"), str),
            "records_path is required for kind=http_json",
        )
    elif kind == "http_html":
        # Two extraction modes. `embedded_json` is strongly preferred where the
        # page ships its data as a JSON island (Inertia `data-page`, Next.js
        # `__NEXT_DATA__`, ld+json): it survives CSS/class churn, which is the
        # single most common way a hand-written HTML scraper silently dies.
        embedded = recipe.get("embedded_json")
        selectors = recipe.get("selectors")
        _require(
            isinstance(embedded, dict) or isinstance(selectors, dict),
            "kind=http_html requires either embedded_json or selectors",
        )
        if isinstance(embedded, dict):
            _require(
                isinstance(embedded.get("selector"), str) and embedded["selector"],
                "embedded_json.selector (CSS selector for the element holding the JSON) is required",
            )
            _require(
                isinstance(embedded.get("records_path"), str),
                "embedded_json.records_path is required (may be '' for a top-level array)",
            )
            source = embedded.get("source", "attribute")
            _require(
                source in ("attribute", "text"),
                "embedded_json.source must be 'attribute' or 'text'",
            )
            if source == "attribute":
                _require(
                    isinstance(embedded.get("attribute"), str) and embedded["attribute"],
                    "embedded_json.attribute is required when source='attribute'",
                )
        else:
            _require(
                isinstance(selectors.get("record"), str) and selectors["record"],
                "selectors.record (a CSS selector for one job row) is required",
            )
    elif kind == "browser_dom":
        capture = recipe.get("capture")
        _require(isinstance(capture, dict), "capture is required for kind=browser_dom")
        mode = capture.get("mode")
        _require(
            mode in ("network_json", "dom"),
            "capture.mode must be 'network_json' or 'dom'",
        )
        if mode == "network_json":
            _require(
                isinstance(capture.get("url_contains"), str) and capture["url_contains"],
                "capture.url_contains is required for capture.mode=network_json",
            )
            _require(
                isinstance(recipe.get("records_path"), str)
                or isinstance(capture.get("records_shape_keys"), list),
                "browser_dom/network_json needs records_path or capture.records_shape_keys",
            )
        else:
            selectors = recipe.get("selectors")
            _require(
                isinstance(selectors, dict) and isinstance(selectors.get("record"), str),
                "selectors.record is required for capture.mode=dom",
            )

    return recipe


def dig(payload: Any, path: str) -> Any:
    """Resolve a dotted path such as 'data.jobs' or 'hits' inside a payload.

    An empty path returns the payload itself. List indices are supported as
    numeric segments ('data.0.jobs').
    """
    if not path:
        return payload
    current = payload
    for segment in path.split("."):
        if isinstance(current, list):
            try:
                index = int(segment)
            except ValueError:
                raise RecipeError(f"path segment {segment!r} is not a list index") from None
            if index >= len(current):
                raise RecipeError(f"list index {index} out of range at {segment!r}")
            current = current[index]
        elif isinstance(current, dict):
            if segment not in current:
                raise RecipeError(f"missing key {segment!r} while resolving path {path!r}")
            current = current[segment]
        else:
            raise RecipeError(f"cannot descend into {type(current).__name__} at {segment!r}")
    return current
