"""REPLAY SIDE — deterministic recipe executor. NO agent, NO LLM, ever.

This module is the spike's stand-in for the production `recipe_runner`. It
must be reachable without any AI dependency: the import guard below fails
loudly if an agent/LLM package ever leaks into this path.

Contract (mirrors src/backend/api/services/greenhouse_client.py in spirit):
a broken source RAISES. It never returns [] — an empty result would feed the
miss counter and false-close a company (docs/incidents/2026-03-29).

Usage:
    python replay.py --recipe recipes/amazon.json
    python replay.py --all --label replay-1
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from recipe_schema import RecipeError, dig, validate_recipe

HERE = Path(__file__).parent
RECIPES = HERE / "recipes"
RESULTS = HERE / "results"

FORBIDDEN_MODULES = ("anthropic", "openai", "stagehand", "browserbase", "langchain")

TIMEOUT_SECONDS = 30.0
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def assert_no_agent_imports() -> None:
    leaked = sorted(m for m in FORBIDDEN_MODULES if m in sys.modules)
    if leaked:
        raise RuntimeError(f"replay path must never import an agent/LLM client; found {leaked}")


class RecipeExecutionError(RuntimeError):
    """A recipe run failed. Callers must treat this as 'we learned nothing'."""


# --------------------------------------------------------------------------
# field mapping
# --------------------------------------------------------------------------

_TEMPLATE_RE = re.compile(r"\{([^{}]+)\}")


def render_field(record: Any, spec: str) -> Any:
    """A field spec is either a dotted path or a template with {dotted.paths}."""
    if "{" in spec:
        def substitute(match: re.Match[str]) -> str:
            try:
                value = dig(record, match.group(1))
            except RecipeError:
                return ""
            return "" if value is None else str(value)
        return _TEMPLATE_RE.sub(substitute, spec)
    try:
        return dig(record, spec)
    except RecipeError:
        return None


def map_records(records: list[Any], fields: dict[str, str]) -> list[dict]:
    mapped = []
    for record in records:
        row = {name: render_field(record, spec) for name, spec in fields.items()}
        if row.get("id") in (None, "") or row.get("title") in (None, ""):
            continue
        row["id"] = str(row["id"])
        mapped.append(row)
    return mapped


# --------------------------------------------------------------------------
# kind: http_json
# --------------------------------------------------------------------------

def _request(client: httpx.Client, entry: dict, params: dict | None) -> httpx.Response:
    method = entry.get("method", "GET")
    headers = {"User-Agent": USER_AGENT, **(entry.get("headers") or {})}
    body = entry.get("body")
    if method == "POST":
        merged_body = dict(body or {})
        if params:
            merged_body.update(params)
        response = client.post(entry["url"], json=merged_body, headers=headers)
    else:
        # MERGE the cursor into the URL's existing query rather than passing
        # params= — httpx replaces the whole query string, which silently
        # dropped every filter on a filtered board and turned a 76-job search
        # into the global 10,000-job one. Silent scope changes are exactly the
        # failure class this spike exists to eliminate.
        target = httpx.URL(entry["url"])
        if params:
            target = target.copy_merge_params(params)
        response = client.get(target, headers=headers)
    if response.status_code >= 400:
        raise RecipeExecutionError(
            f"HTTP {response.status_code} from {response.request.url} "
            f"(body starts: {response.text[:180]!r})"
        )
    return response


def _parse_json(response: httpx.Response) -> Any:
    try:
        # strict=False: some boards (Amazon) embed raw control bytes in descriptions.
        return json.loads(response.text, strict=False)
    except Exception as exc:  # noqa: BLE001
        raise RecipeExecutionError(f"unparseable JSON from {response.request.url}: {exc}") from exc


def check_completeness(recipe: dict, payload: Any, got: int) -> None:
    """Compare the harvest against the payload's own declared total.

    expected_min_jobs catches a collapse to near-zero. This catches the far
    more dangerous case: a scrape that quietly returns 100 of 4,000 jobs and
    looks perfectly healthy. The source told us the real number — use it.
    """
    total_path = recipe.get("total_path")
    if not total_path:
        return
    try:
        declared = dig(payload, total_path)
    except RecipeError as exc:
        raise RecipeExecutionError(
            f"total_path {total_path!r} did not resolve — the completeness oracle "
            f"moved, so this run cannot be trusted: {exc}"
        ) from exc
    if not isinstance(declared, int) or declared < 0:
        raise RecipeExecutionError(f"total_path {total_path!r} resolved to {declared!r}, not a count")
    tolerance = recipe.get("completeness_tolerance", 0.05)
    floor = declared * (1 - tolerance)
    if got < floor:
        raise RecipeExecutionError(
            f"incomplete harvest: got {got} records but the source declares {declared} "
            f"(floor {floor:.0f} at {tolerance:.0%} tolerance) — refusing to report a partial board"
        )


def run_http_json(recipe: dict) -> list[dict]:
    entry = recipe["entrypoint"]
    pagination = recipe.get("pagination") or {"style": "none"}
    style = pagination.get("style", "none")
    records: list[Any] = []
    first_payload: Any = None
    seen_pages = 0

    with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client:
        if style == "none":
            payload = first_payload = _parse_json(_request(client, entry, None))
            records = dig(payload, recipe["records_path"])
            if not isinstance(records, list):
                raise RecipeExecutionError(
                    f"records_path {recipe['records_path']!r} did not resolve to a list"
                )
        else:
            page_size = pagination["page_size"]
            max_pages = pagination["max_pages"]
            param = pagination["param"]
            cursor = 0 if style == "offset" else int(pagination.get("start_page", 1))
            while seen_pages < max_pages:
                payload = _parse_json(_request(client, entry, {param: cursor}))
                if first_payload is None:
                    first_payload = payload
                page_records = dig(payload, recipe["records_path"])
                if not isinstance(page_records, list):
                    raise RecipeExecutionError(
                        f"records_path {recipe['records_path']!r} did not resolve to a list on page {seen_pages}"
                    )
                seen_pages += 1
                records.extend(page_records)
                if len(page_records) < page_size:
                    break
                cursor += page_size if style == "offset" else 1

    check_completeness(recipe, first_payload, len(records))
    return map_records(records, recipe["fields"])


# --------------------------------------------------------------------------
# kind: http_html
# --------------------------------------------------------------------------

def _select_html_field(node, spec: str):
    selector, _, attribute = spec.partition("@")
    selector = selector.strip()
    target = node if not selector or selector == "." else node.select_one(selector)
    if target is None:
        return None
    if attribute and attribute != "text":
        return target.get(attribute)
    return target.get_text(" ", strip=True)


def run_embedded_json(recipe: dict) -> list[dict]:
    """http_html pages that ship their data as a JSON island in the markup."""
    from bs4 import BeautifulSoup  # local import: html-only dependency

    embedded = recipe["embedded_json"]
    with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client:
        response = _request(client, recipe["entrypoint"], None)

    soup = BeautifulSoup(response.text, "html.parser")
    node = soup.select_one(embedded["selector"])
    if node is None:
        raise RecipeExecutionError(
            f"embedded_json.selector {embedded['selector']!r} matched nothing "
            "(markup changed?)"
        )

    if embedded.get("source", "attribute") == "attribute":
        blob = node.get(embedded["attribute"])
        if not blob:
            raise RecipeExecutionError(
                f"element matched but attribute {embedded['attribute']!r} is empty"
            )
    else:
        blob = node.get_text()

    try:
        payload = json.loads(blob, strict=False)
    except Exception as exc:  # noqa: BLE001
        raise RecipeExecutionError(f"embedded JSON did not parse: {exc}") from exc

    records = dig(payload, embedded["records_path"])
    if not isinstance(records, list):
        raise RecipeExecutionError(
            f"embedded_json.records_path {embedded['records_path']!r} did not resolve to a list"
        )

    rows = map_records(records, recipe["fields"])
    base_url = recipe.get("base_url", "")
    if base_url:
        for row in rows:
            if isinstance(row.get("url"), str) and row["url"].startswith("/"):
                row["url"] = base_url.rstrip("/") + row["url"]
    return rows


def run_http_html(recipe: dict) -> list[dict]:
    if recipe.get("embedded_json"):
        return run_embedded_json(recipe)

    from bs4 import BeautifulSoup  # local import: html-only dependency

    entry = recipe["entrypoint"]
    selectors = recipe["selectors"]
    pagination = recipe.get("pagination") or {"style": "none"}
    style = pagination.get("style", "none")
    base_url = recipe.get("base_url", "")
    rows: list[dict] = []
    pages = 1 if style == "none" else pagination["max_pages"]
    cursor = 0 if style == "offset" else int(pagination.get("start_page", 1))

    with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client:
        for _ in range(pages):
            params = None if style == "none" else {pagination["param"]: cursor}
            response = _request(client, entry, params)
            soup = BeautifulSoup(response.text, "html.parser")
            nodes = soup.select(selectors["record"])
            if not nodes:
                break
            for node in nodes:
                row = {}
                for name, spec in recipe["fields"].items():
                    value = _select_html_field(node, spec)
                    if name == "url" and value and base_url and value.startswith("/"):
                        value = base_url.rstrip("/") + value
                    row[name] = value
                if row.get("id") in (None, "") or row.get("title") in (None, ""):
                    continue
                row["id"] = str(row["id"])
                rows.append(row)
            if style == "none" or len(nodes) < pagination.get("page_size", len(nodes)):
                break
            cursor += pagination["page_size"] if style == "offset" else 1
    return rows


# --------------------------------------------------------------------------
# kind: browser_dom  (deterministic Playwright — a browser, NOT an agent)
# --------------------------------------------------------------------------

def _arrays_matching_shape(payload: Any, keys: list[str], depth: int = 0) -> list[list]:
    """Find arrays of objects carrying all of `keys` — shape-based, not name-based.

    Name-based matching is what silently zeroed job-watcher's Meta adapter for
    41 days when the GraphQL operation was renamed.
    """
    found: list[list] = []
    if depth > 8:
        return found
    if isinstance(payload, list):
        objs = [i for i in payload[:5] if isinstance(i, dict)]
        if objs and all(any(k in o for o in objs) for k in keys):
            found.append(payload)
        for item in payload[:5]:
            found.extend(_arrays_matching_shape(item, keys, depth + 1))
    elif isinstance(payload, dict):
        for value in payload.values():
            found.extend(_arrays_matching_shape(value, keys, depth + 1))
    return found


def run_browser_dom(recipe: dict) -> list[dict]:
    from playwright.sync_api import sync_playwright  # local import: browser-only dependency

    entry = recipe["entrypoint"]
    capture = recipe["capture"]
    settle_ms = int(capture.get("settle_ms", 4000))
    scrolls = int(capture.get("scrolls", 0))
    collected: list[Any] = []
    records: list[Any] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            user_agent=USER_AGENT,
        )
        page = context.new_page()

        if capture["mode"] == "network_json":
            needle = capture["url_contains"]

            def on_response(response) -> None:
                if needle not in response.url:
                    return
                try:
                    collected.append(json.loads(response.text(), strict=False))
                except Exception:  # noqa: BLE001 - a non-JSON hit is not fatal by itself
                    return

            page.on("response", on_response)

        page.goto(entry["url"], wait_until=capture.get("wait_until", "networkidle"), timeout=60_000)
        for _ in range(scrolls):
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(1200)
        page.wait_for_timeout(settle_ms)

        if capture["mode"] == "dom":
            nodes = page.query_selector_all(recipe["selectors"]["record"])
            for node in nodes:
                row: dict[str, Any] = {}
                for name, spec in recipe["fields"].items():
                    selector, _, attribute = spec.partition("@")
                    selector = selector.strip()
                    target = node if not selector or selector == "." else node.query_selector(selector)
                    if target is None:
                        row[name] = None
                        continue
                    row[name] = target.get_attribute(attribute) if attribute and attribute != "text" else target.inner_text().strip()
                if row.get("id") and row.get("title"):
                    row["id"] = str(row["id"])
                    records.append(row)
            context.close()
            browser.close()
            if not records:
                raise RecipeExecutionError("browser_dom/dom captured zero rows (selector or bot-wall regression?)")
            return records

        context.close()
        browser.close()

    if not collected:
        raise RecipeExecutionError(
            f"browser_dom/network_json captured zero responses matching {capture['url_contains']!r} "
            "(navigation blocked, or the site stopped using that endpoint)"
        )

    path = recipe.get("records_path")
    shape_keys = capture.get("records_shape_keys")
    for payload in collected:
        if path:
            try:
                candidate = dig(payload, path)
            except RecipeError:
                continue
            if isinstance(candidate, list) and candidate:
                records.extend(candidate)
        elif shape_keys:
            for array in _arrays_matching_shape(payload, shape_keys):
                records.extend(array)

    if not records:
        raise RecipeExecutionError(
            "browser_dom/network_json matched responses but found no job records "
            "(payload shape changed?)"
        )
    return map_records(records, recipe["fields"])


# --------------------------------------------------------------------------
# entry points
# --------------------------------------------------------------------------

RUNNERS = {
    "http_json": run_http_json,
    "http_html": run_http_html,
    "browser_dom": run_browser_dom,
}


def run_recipe(recipe: dict) -> list[dict]:
    """Execute a recipe. RAISES on any failure — never returns []."""
    assert_no_agent_imports()
    validate_recipe(recipe)
    rows = RUNNERS[recipe["kind"]](recipe)

    if not rows:
        raise RecipeExecutionError("recipe produced zero records — treated as failure, never as 'no jobs'")

    deduped = {row["id"]: row for row in rows}
    minimum = recipe["expected_min_jobs"]
    if len(deduped) < minimum:
        raise RecipeExecutionError(
            f"recipe produced {len(deduped)} records, below expected_min_jobs={minimum}"
        )
    return list(deduped.values())


def replay_file(path: Path) -> dict:
    recipe = json.loads(path.read_text())
    started = time.time()
    result: dict[str, Any] = {"recipe": path.name, "target": recipe.get("target", path.stem), "kind": recipe.get("kind")}
    try:
        rows = run_recipe(recipe)
    except Exception as exc:  # noqa: BLE001 - the report records failures as data
        result.update(ok=False, error=f"{type(exc).__name__}: {exc}"[:400], job_count=0)
    else:
        result.update(ok=True, job_count=len(rows), sample=rows[:2])
    result["seconds"] = round(time.time() - started, 1)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay scrape recipes deterministically (no agent)")
    parser.add_argument("--recipe", help="path to a single recipe json")
    parser.add_argument("--all", action="store_true", help="replay every recipe in recipes/")
    parser.add_argument("--label", default="manual", help="label for the results file")
    args = parser.parse_args()

    paths = sorted(RECIPES.glob("*.json")) if args.all else [Path(args.recipe)]
    if not paths:
        raise SystemExit("no recipes found")

    results = [replay_file(p) for p in paths]
    RESULTS.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out = RESULTS / f"{args.label}-{stamp}.json"
    out.write_text(json.dumps({"label": args.label, "utc": stamp, "results": results}, indent=2))

    for r in results:
        status = f"OK   {r['job_count']:>6} jobs" if r["ok"] else f"FAIL {r.get('error', '')[:110]}"
        print(f"{r['target']:<14} {r.get('kind', '?'):<12} {status}  ({r['seconds']}s)")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
