"""REPLAY SIDE — the deterministic, agent-free recipe executor (E7 Phase 3a).

Production port of ``scripts/one_off/recipe_spike/replay.py``. Executes a stored
``company_scripts.script`` (the multi-primitive ``steps`` list validated by
:mod:`api.services.recipe_schema`) over plain ``httpx`` and emits the same
:class:`~api.services.harvest_meta.HarvestEvidence` the Phase-2 gate already
consumes — so ``run_gate`` / ``verify_harvest`` need no rewrite.

Non-negotiable contract (BUILD-PLAN, OVERVIEW):

* **Agent-free, enforced in code.** :func:`assert_no_agent_imports` runs first on
  every call and raises if ``anthropic``/``openai``/``stagehand``/``browserbase``/
  ``langchain``/**``playwright``** is in ``sys.modules``. HTTP-only replay must
  never reach a browser or an LLM — ``playwright`` is forbidden here even though
  discovery (Phase 3b) uses it. This is a proof, not a convention.
* **RAISES, never returns ``[]``.** A non-2xx, an in-band error key, unparseable
  JSON, a path that does not resolve, a vanished oracle, zero rows, or a post-dedup
  count below ``expected_min_jobs`` all raise :class:`RecipeExecutionError`. An
  empty list is indistinguishable from "this company stopped hiring" — the
  2026-03-29 false-close class. The leaf task maps the raise to a FAILED run.
* **Deterministic.** Same script + same responses ⇒ byte-identical rows twice.

This module imports only the stdlib, ``httpx``, the dependency-free
:mod:`recipe_schema` / :mod:`harvest_meta`, and (lazily, inside the HTML path)
``bs4``. It must stay that thin — the import guard test walks its AST.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from typing import Any
from xml.etree import ElementTree

import httpx

from .harvest_meta import HarvestEvidence
from .recipe_schema import RecipeError, dig, validate_recipe

# The full agent/LLM/browser set the REPLAY CODE PATH must never be able to import.
# ``playwright`` ADDED vs the spike: Phase-3a replay is HTTP-only, so a browser driver
# on this path is as much a violation as an LLM client. This set is enforced
# STATICALLY (sound regardless of process co-tenancy) by the import-guard tests: a
# subprocess imports the runner alone and asserts none of these landed in
# ``sys.modules``, and an AST walk proves the runner's whole first-party import
# closure imports none of them.
FORBIDDEN_MODULES = ("anthropic", "openai", "stagehand", "browserbase", "langchain", "playwright")

# The subset the per-call RUNTIME guard checks. It deliberately EXCLUDES the LLM
# SDKs (``anthropic``/``openai``): the replay leaf task runs in the shared
# Procrastinate worker, which co-hosts location-normalization — that task imports
# ``anthropic`` at module load, so ``anthropic`` is ALWAYS resident in the replay
# worker. Its residence is therefore NOT evidence that the replay path reached for
# it (the static guards above already prove it cannot). What must NEVER be resident
# in the replay worker are the discovery-only browser/agent-orchestration drivers —
# those are imported solely by ``services/discovery/`` (Phase 3b) and their presence
# is a decidable, in-process proof of contamination.
_RUNTIME_FORBIDDEN_MODULES = ("playwright", "stagehand", "browserbase", "langchain")

# The amazon.jobs ES window; the default cap above which `hits` is untrustworthy
# and a single-valued facet sum becomes the only path to the true total.
_DEFAULT_FACET_WINDOW_CAP = 10000

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def assert_no_agent_imports() -> None:
    """Raise if a discovery-only browser/agent driver has leaked into this process.

    Checks :data:`_RUNTIME_FORBIDDEN_MODULES` (playwright/stagehand/browserbase/
    langchain), never the LLM SDKs — see that constant for why ``anthropic`` is
    legitimately co-resident and must not trip this guard. The full
    :data:`FORBIDDEN_MODULES` set (LLM SDKs included) is enforced statically by the
    import-guard tests, which is the only place "the replay code cannot import an
    LLM" is a sound, co-tenancy-independent property.
    """
    leaked = sorted(m for m in _RUNTIME_FORBIDDEN_MODULES if m in sys.modules)
    if leaked:
        raise RuntimeError(
            f"replay worker must never import a browser/agent driver; found {leaked} — "
            "these belong only to services/discovery (Phase 3b), never on the replay path"
        )


class RecipeExecutionError(RuntimeError):
    """A recipe run failed. Callers must treat this as 'we learned nothing' (FAILED),
    never as 'no jobs today'."""


# --------------------------------------------------------------------------
# field mapping (ported verbatim from replay.py)
# --------------------------------------------------------------------------

_TEMPLATE_RE = re.compile(r"\{([^{}]+)\}")


def render_field(record: Any, spec: str) -> Any:
    """A field spec is either a dotted path or a template with ``{dotted.paths}``."""
    if "{" in spec:
        def substitute(match: "re.Match[str]") -> str:
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


def map_records(records: list[Any], fields: dict[str, str], base_url: str = "") -> list[dict]:
    """Map raw records to rows via ``fields``; drop rows missing id/title; stringify id."""
    mapped: list[dict] = []
    for record in records:
        row = {name: render_field(record, spec) for name, spec in fields.items()}
        if row.get("id") in (None, "") or row.get("title") in (None, ""):
            continue
        row["id"] = str(row["id"])
        if base_url and isinstance(row.get("url"), str) and row["url"].startswith("/"):
            row["url"] = base_url.rstrip("/") + row["url"]
        mapped.append(row)
    return mapped


# --------------------------------------------------------------------------
# parsed plan
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class _Plan:
    transport: str
    expected_min_jobs: int
    fetch: dict[str, Any]
    pagination: dict[str, Any] | None
    extraction: dict[str, Any]
    shaping: list[dict[str, Any]]
    oracle: dict[str, Any]
    base_url: str
    dedupe_field: str
    error_keys: tuple[str, ...]
    pinned: dict[str, Any] | None
    unique_field: str | None
    window_cap: int | None = field(default=None)


def _parse_steps(script: dict[str, Any]) -> _Plan:
    fetch: dict[str, Any] | None = None
    pagination: dict[str, Any] | None = None
    extraction: dict[str, Any] | None = None
    shaping: list[dict[str, Any]] = []
    dedupe_field = "id"
    error_keys: tuple[str, ...] = ()
    pinned: dict[str, Any] | None = None
    unique_field: str | None = None
    window_cap: int | None = None

    for step in script["steps"]:
        op = step["op"]
        if op == "fetch":
            fetch = step
        elif op.startswith("paginate_"):
            pagination = step
            if "window_cap" in step:
                window_cap = step["window_cap"]
        elif op.startswith("extract_"):
            extraction = step
        elif op in ("transform", "parse_date"):
            shaping.append(step)
        elif op == "dedupe_key":
            dedupe_field = step["field"]
        elif op == "assert_no_inband_error":
            error_keys = tuple(step["error_keys"])
        elif op == "assert_pinned_operation":
            pinned = step
        elif op == "assert_cap_not_hit":
            window_cap = step["window_cap"]
        elif op == "assert_unique":
            unique_field = step["field"]
        # assert_status / assert_page_advances / assert_unique_ids_vs_total /
        # assert_delta_vs_last_run are enforced structurally by the runner itself.

    assert fetch is not None and extraction is not None  # guaranteed by validate_recipe
    base_url = script.get("base_url") or extraction.get("base_url", "")
    return _Plan(
        transport=script["transport"],
        expected_min_jobs=script["expected_min_jobs"],
        fetch=fetch,
        pagination=pagination,
        extraction=extraction,
        shaping=shaping,
        oracle=script["oracle"],
        base_url=base_url,
        dedupe_field=dedupe_field,
        error_keys=error_keys,
        pinned=pinned,
        unique_field=unique_field,
        window_cap=window_cap,
    )


# --------------------------------------------------------------------------
# transport
# --------------------------------------------------------------------------

def _request(
    http: httpx.Client, fetch: dict[str, Any], params: dict[str, Any] | None
) -> httpx.Response:
    method = fetch.get("method", "GET")
    headers = {"User-Agent": USER_AGENT, **(fetch.get("headers") or {})}
    if method == "POST":
        merged_body = dict(fetch.get("body") or {})
        if params:
            merged_body.update(params)
        response = http.post(fetch["url"], json=merged_body, headers=headers)
    else:
        # MERGE the cursor into the URL's existing query rather than passing
        # params= — httpx replaces the whole query string, which silently drops
        # every filter and turns a 76-job search into the global 10,000-job one
        # (replay.py:104-108). Silent scope change is the failure class this exists
        # to eliminate.
        target = httpx.URL(fetch["url"])
        if params:
            target = target.copy_merge_params(params)
        response = http.get(target, headers=headers)
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
        raise RecipeExecutionError(
            f"unparseable JSON from {response.request.url}: {exc}"
        ) from exc


def _check_inband_error(payload: Any, error_keys: tuple[str, ...]) -> None:
    if not error_keys or not isinstance(payload, dict):
        return
    for key in error_keys:
        value = payload.get(key)
        if value:  # a truthy error/errors/message in a 200 body is fatal (Amazon: HTTP 200)
            raise RecipeExecutionError(
                f"in-band error key {key!r} present in a 200 body: {value!r}"
            )


def _dig_records(payload: Any, records_path: str, where: str) -> list[Any]:
    try:
        records = dig(payload, records_path)
    except RecipeError as exc:
        raise RecipeExecutionError(
            f"records_path {records_path!r} did not resolve {where}: {exc}"
        ) from exc
    if not isinstance(records, list):
        raise RecipeExecutionError(
            f"records_path {records_path!r} did not resolve to a list {where}"
        )
    return records


# --------------------------------------------------------------------------
# execution — http_json (paginated / facet / single)
# --------------------------------------------------------------------------

@dataclass
class _HarvestState:
    rows: list[dict]
    first_payload: Any
    first_headers: dict[str, str]
    page_id_sets: list[set[str]]
    cap_hit: bool
    terminated_cleanly: bool
    pages_fetched: int


def _sweep_offset_page(
    http: httpx.Client,
    plan: _Plan,
    state: _HarvestState,
    extra_params: dict[str, Any],
    style: str,
    param: str,
    page_size: int,
    max_pages: int,
    start_page: int,
    window_cap: int | None,
    records_path: str,
    fields: dict[str, str],
) -> None:
    """One offset/page sweep. Appends mapped rows + per-page id sets onto ``state``."""
    cursor = 0 if style == "offset" else start_page
    seen_pages = 0
    ended_short = False
    while seen_pages < max_pages:
        # Cap check BEFORE the request: offset + page_size must stay <= window_cap.
        if style == "offset" and window_cap is not None and cursor + page_size > window_cap:
            state.cap_hit = True
            break
        params = {**extra_params, param: cursor}
        response = _request(http, plan.fetch, params)
        payload = _parse_json(response)
        if state.first_payload is None:
            state.first_payload = payload
            state.first_headers = dict(response.headers)
        _check_inband_error(payload, plan.error_keys)
        page_records = _dig_records(payload, records_path, f"on page {seen_pages}")
        page_rows = map_records(page_records, fields, plan.base_url)
        state.rows.extend(page_rows)
        state.page_id_sets.append({r["id"] for r in page_rows})
        seen_pages += 1
        state.pages_fetched += 1
        if len(page_records) < page_size:
            ended_short = True
            break
        cursor += page_size if style == "offset" else 1
    # A sweep that ran out its page budget without a short final page has not
    # provably seen the whole slice.
    if ended_short:
        state.terminated_cleanly = state.terminated_cleanly and True
    else:
        state.terminated_cleanly = False


def _run_http_json(http: httpx.Client, plan: _Plan) -> _HarvestState:
    ext = plan.extraction
    records_path = ext["records_path"]
    fields = ext["fields"]
    state = _HarvestState(
        rows=[], first_payload=None, first_headers={}, page_id_sets=[],
        cap_hit=False, terminated_cleanly=True, pages_fetched=0,
    )
    pg = plan.pagination

    if pg is None:
        response = _request(http, plan.fetch, None)
        payload = _parse_json(response)
        state.first_payload = payload
        state.first_headers = dict(response.headers)
        _check_inband_error(payload, plan.error_keys)
        records = _dig_records(payload, records_path, "")
        state.rows = map_records(records, fields, plan.base_url)
        state.page_id_sets = [{r["id"] for r in state.rows}]
        state.pages_fetched = 1
        state.terminated_cleanly = True
        return state

    op = pg["op"]
    if op == "paginate_facet":
        facet_values = _resolve_facet_values(http, plan, pg)
        facet_param = pg["facet_param"]
        page_size = pg["page_size"]
        max_pages = pg["max_pages_per_facet"]
        window_cap = pg.get("window_cap")
        for value in facet_values:
            _sweep_offset_page(
                http, plan, state, {facet_param: value}, "offset", "offset",
                page_size, max_pages, 0, window_cap, records_path, fields,
            )
    else:
        style = {"paginate_offset": "offset", "paginate_page": "page"}[op]
        param = pg["param"]
        page_size = pg["page_size"]
        max_pages = pg["max_pages"]
        start_page = int(pg.get("start_page", 1))
        window_cap = pg.get("window_cap")
        _sweep_offset_page(
            http, plan, state, {}, style, param, page_size, max_pages,
            start_page, window_cap, records_path, fields,
        )
    return state


def _resolve_facet_values(http: httpx.Client, plan: _Plan, pg: dict[str, Any]) -> list[str]:
    if "facet_values" in pg:
        return list(pg["facet_values"])
    # facet_values_path: probe once (no pagination) to read the facet labels.
    response = _request(http, plan.fetch, None)
    payload = _parse_json(response)
    buckets = dig(payload, pg["facet_values_path"])
    if not isinstance(buckets, list) or not buckets:
        raise RecipeExecutionError(
            f"facet_values_path {pg['facet_values_path']!r} did not resolve to a "
            "non-empty list of facet buckets"
        )
    values: list[str] = []
    for bucket in buckets:
        if isinstance(bucket, dict):
            values.extend(str(k) for k in bucket)
    if not values:
        raise RecipeExecutionError(
            f"facet_values_path {pg['facet_values_path']!r} yielded no facet labels"
        )
    return values


# --------------------------------------------------------------------------
# execution — http_html (embedded island preferred; css last resort)
# --------------------------------------------------------------------------

def _run_http_html(http: httpx.Client, plan: _Plan) -> _HarvestState:
    ext = plan.extraction
    op = ext["op"]
    state = _HarvestState(
        rows=[], first_payload=None, first_headers={}, page_id_sets=[],
        cap_hit=False, terminated_cleanly=True, pages_fetched=1,
    )
    if op == "extract_embedded_island":
        _run_embedded_island(http, plan, state)
    else:  # extract_css
        _run_css(http, plan, state)
    return state


def _run_embedded_island(http: httpx.Client, plan: _Plan, state: _HarvestState) -> None:
    from bs4 import BeautifulSoup  # local import: html-only dependency

    ext = plan.extraction
    response = _request(http, plan.fetch, None)
    state.first_headers = dict(response.headers)
    soup = BeautifulSoup(response.text, "html.parser")
    node = soup.select_one(ext["selector"])
    if node is None:
        raise RecipeExecutionError(
            f"embedded island selector {ext['selector']!r} matched nothing (markup changed?)"
        )
    if ext.get("source", "attribute") == "attribute":
        raw_attr = node.get(ext["attribute"])
        if not raw_attr:
            raise RecipeExecutionError(
                f"element matched but attribute {ext['attribute']!r} is empty"
            )
        # bs4 returns a list for space-separated multi-valued attributes; a JSON
        # island is always a single string value.
        if not isinstance(raw_attr, str):
            raise RecipeExecutionError(
                f"attribute {ext['attribute']!r} is multi-valued, not a JSON string"
            )
        blob = raw_attr
    else:
        blob = node.get_text()
    try:
        payload = json.loads(blob, strict=False)
    except Exception as exc:  # noqa: BLE001
        raise RecipeExecutionError(f"embedded island JSON did not parse: {exc}") from exc
    state.first_payload = payload
    records = _dig_records(payload, ext["records_path"], "in the embedded island")
    state.rows = map_records(records, ext["fields"], plan.base_url)
    state.page_id_sets = [{r["id"] for r in state.rows}]


def _run_css(http: httpx.Client, plan: _Plan, state: _HarvestState) -> None:
    from bs4 import BeautifulSoup  # local import: html-only dependency

    ext = plan.extraction
    response = _request(http, plan.fetch, None)
    state.first_headers = dict(response.headers)
    soup = BeautifulSoup(response.text, "html.parser")
    nodes = soup.select(ext["record_selector"])
    rows: list[dict] = []
    for node in nodes:
        row: dict[str, Any] = {}
        for name, spec in ext["field_selectors"].items():
            row[name] = _select_html_field(node, spec)
        if row.get("id") in (None, "") or row.get("title") in (None, ""):
            continue
        row["id"] = str(row["id"])
        if plan.base_url and isinstance(row.get("url"), str) and row["url"].startswith("/"):
            row["url"] = plan.base_url.rstrip("/") + row["url"]
        rows.append(row)
    state.rows = rows
    state.page_id_sets = [{r["id"] for r in rows}]


def _select_html_field(node: Any, spec: str) -> Any:
    selector, _, attribute = spec.partition("@")
    selector = selector.strip()
    target = node if not selector or selector == "." else node.select_one(selector)
    if target is None:
        return None
    if attribute and attribute != "text":
        return target.get(attribute)
    return target.get_text(" ", strip=True)


# --------------------------------------------------------------------------
# field shaping (transform / parse_date)
# --------------------------------------------------------------------------

_MULTISPACE_RE = re.compile(r"\s+")


def _apply_shaping(rows: list[dict], shaping: list[dict[str, Any]]) -> list[dict]:
    for step in shaping:
        op = step["op"]
        field_name = step["field"]
        for row in rows:
            if op == "transform":
                row[field_name] = _transform_value(row, step)
            else:  # parse_date
                row[field_name] = _parse_date_value(row.get(field_name), step)
    return rows


def _transform_value(row: dict, step: dict[str, Any]) -> Any:
    if step["kind"] == "template":
        return render_field(row, step["template"])
    # base_url_join
    value = row.get(step["field"])
    if isinstance(value, str) and value.startswith("/"):
        return step["base_url"].rstrip("/") + value
    return value


def _parse_date_value(value: Any, step: dict[str, Any]) -> Any:
    """Normalize to ISO-8601; NEVER synthesize — unparseable → None (dropped later)."""
    if not isinstance(value, str) or not value.strip():
        return None
    mode = step["mode"]
    if mode == "iso":
        return value.strip()
    if mode == "strptime":
        from datetime import datetime
        cleaned = _MULTISPACE_RE.sub(" ", value.strip())  # Amazon's double-space dates
        try:
            return datetime.strptime(cleaned, step["format"]).date().isoformat()
        except ValueError:
            return None
    # humanized ("about 12 hours") — no reliable absolute timestamp; leave as None so
    # the leaf task's first_seen tracking governs freshness.
    return None


# --------------------------------------------------------------------------
# oracle computation → declared_total (rides HarvestEvidence.declared_total)
# --------------------------------------------------------------------------

def sum_single_valued_facet(payload: Any, facet_path: str) -> int:
    """Σ of the counts in a facet block shaped ``[{label: count}, ...]``."""
    buckets = dig(payload, facet_path)
    if not isinstance(buckets, list) or not buckets:
        raise RecipeExecutionError(
            f"facet_path {facet_path!r} did not resolve to a non-empty facet list"
        )
    total = 0
    for bucket in buckets:
        if not isinstance(bucket, dict):
            raise RecipeExecutionError(f"facet bucket {bucket!r} is not a {{label: count}} object")
        for count in bucket.values():
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise RecipeExecutionError(f"facet count {count!r} is not a non-negative int")
            total += count
    return total


def _oracle_facet_sum(payload: Any, oracle: dict[str, Any]) -> int:
    """facet_sum: single-valued facet Σ, enforcing the partition property (GM lesson).

    When the payload's own claimed total (``total_path``, default ``hits``) is BELOW
    the ES window cap the sum is cross-checkable: a clean single-valued partition has
    ``Σ facet == claimed``; anything else (a facet that covers but does not partition,
    like GM's 1,042-vs-835 location facet) raises. When ``claimed >= window_cap`` the
    claimed total is itself capped and the facet sum is the *only* path to the true
    total, so the pinned ``single_valued: true`` is trusted.
    """
    facet_sum = sum_single_valued_facet(payload, oracle["facet_path"])
    total_path = oracle.get("total_path", "hits")
    window_cap = oracle.get("window_cap", _DEFAULT_FACET_WINDOW_CAP)
    try:
        claimed = dig(payload, total_path)
    except RecipeError as exc:
        raise RecipeExecutionError(
            f"facet_sum total_path {total_path!r} did not resolve — cannot verify "
            f"single-valuedness: {exc}"
        ) from exc
    if not isinstance(claimed, int) or isinstance(claimed, bool) or claimed < 0:
        raise RecipeExecutionError(f"facet_sum total_path {total_path!r} = {claimed!r}, not a count")
    if claimed < window_cap and facet_sum != claimed:
        raise RecipeExecutionError(
            f"facet {oracle['facet_path']!r} is NOT single-valued: Σ={facet_sum} but the "
            f"under-cap claimed total is {claimed} — the facet double-counts (GM "
            f"1,042-vs-835). Refusing to use it as a completeness oracle."
        )
    return facet_sum


def _oracle_header(headers: dict[str, str], oracle: dict[str, Any]) -> int:
    name = oracle["header_name"]
    # httpx headers are case-insensitive on a Response; the dict we snapshot is not.
    lowered = {k.lower(): v for k, v in headers.items()}
    raw = lowered.get(name.lower())
    if raw is None:
        raise RecipeExecutionError(
            f"header oracle {name!r} is absent — the completeness oracle moved; FAILED"
        )
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise RecipeExecutionError(f"header oracle {name!r} = {raw!r}, not an int") from exc


def _oracle_sitemap(http: httpx.Client, oracle: dict[str, Any]) -> int:
    response = _request(http, {"method": "GET", "url": oracle["sitemap_url"], "headers": {}}, None)
    pattern = oracle["url_pattern"]
    try:
        root = ElementTree.fromstring(response.text)
    except ElementTree.ParseError as exc:
        raise RecipeExecutionError(f"sitemap {oracle['sitemap_url']!r} did not parse: {exc}") from exc
    count = 0
    for loc in root.iter():
        if loc.tag.endswith("}loc") or loc.tag == "loc":
            text = (loc.text or "").strip()
            if pattern in text:
                count += 1
    if count == 0:
        raise RecipeExecutionError(
            f"sitemap {oracle['sitemap_url']!r} yielded 0 <loc> matching {pattern!r} — "
            "empty/unusable oracle; FAILED"
        )
    return count


def _compute_declared_total(
    oracle: dict[str, Any], state: _HarvestState, http: httpx.Client
) -> int | None:
    kind = oracle["kind"]
    if kind == "self_consistent":
        return None
    if kind == "facet_sum":
        return _oracle_facet_sum(state.first_payload, oracle)
    if kind == "header":
        return _oracle_header(state.first_headers, oracle)
    if kind == "sitemap":
        return _oracle_sitemap(http, oracle)
    # declared_probed
    try:
        declared = dig(state.first_payload, oracle["total_path"])
    except RecipeError as exc:
        raise RecipeExecutionError(
            f"declared_probed total_path {oracle['total_path']!r} did not resolve — "
            f"the oracle moved; FAILED: {exc}"
        ) from exc
    if not isinstance(declared, int) or isinstance(declared, bool) or declared < 0:
        raise RecipeExecutionError(
            f"declared_probed total_path {oracle['total_path']!r} = {declared!r}, not a count"
        )
    return declared


# --------------------------------------------------------------------------
# public entry
# --------------------------------------------------------------------------

def _page_advance_ok(page_id_sets: list[set[str]]) -> bool | None:
    """Every page's id-set disjoint from the union of prior pages (check 6).

    ``None`` for a single page (vacuously satisfied — no page N to compare).
    """
    if len(page_id_sets) <= 1:
        return None
    seen: set[str] = set()
    for page in page_id_sets:
        if page & seen:
            return False
        seen |= page
    return True


def _assert_pinned(plan: _Plan, state: _HarvestState) -> None:
    if plan.pinned is None:
        return
    url = plan.fetch["url"]
    for key in ("doc_id", "url_contains"):
        needle = plan.pinned.get(key)
        if needle is not None and needle not in url:
            raise RecipeExecutionError(
                f"assert_pinned_operation: {key}={needle!r} not present in the fetch URL — "
                "the pinned operation identity drifted; FAILED"
            )
    shape_path = plan.pinned.get("response_shape_path")
    if shape_path is not None:
        try:
            dig(state.first_payload, shape_path)
        except RecipeError as exc:
            raise RecipeExecutionError(
                f"assert_pinned_operation: response_shape_path {shape_path!r} did not "
                f"resolve — the operation moved; FAILED: {exc}"
            ) from exc


def run_recipe(
    script: dict[str, Any],
    http: httpx.Client,
    *,
    transport: str | None = None,
    oracle_kind: str | None = None,
) -> tuple[list[dict], HarvestEvidence]:
    """Execute a validated script over ``http`` → (rows, evidence). RAISES on failure.

    The caller supplies ``http`` so timeouts / SSRF guarding live in one place (the
    leaf task and discovery pass an SSRF-guarded client). ``transport`` /
    ``oracle_kind`` are the ``company_scripts`` column values: when supplied, the
    read-path :func:`validate_recipe` also asserts the stored JSONB's
    ``transport`` / ``oracle.kind`` equal them, so a JSONB-vs-column drift is caught
    on replay, not just at write time. The returned :class:`HarvestEvidence` is
    exactly what ``run_gate`` / ``verify_harvest`` already consume.
    """
    assert_no_agent_imports()   # FIRST, every call — the agent-free proof.
    # validate-on-read: stored scripts drift, and the column-equality check catches
    # a JSONB row edited out of sync with its transport/oracle_kind columns.
    validate_recipe(script, transport=transport, oracle_kind=oracle_kind)
    plan = _parse_steps(script)

    if plan.transport == "http_json":
        state = _run_http_json(http, plan)
    else:
        state = _run_http_html(http, plan)

    _assert_pinned(plan, state)

    rows = _apply_shaping(state.rows, plan.shaping)
    if not rows:
        raise RecipeExecutionError(
            "recipe produced zero records — treated as FAILED, never as 'no jobs today'"
        )

    # Dedupe by the pinned key, keeping first occurrence (deterministic doc order).
    deduped_map: dict[str, dict] = {}
    for row in rows:
        key = row.get(plan.dedupe_field)
        if key is None:
            continue
        deduped_map.setdefault(str(key), row)
    deduped = list(deduped_map.values())

    # assert_unique (check 8) — the key field is unique post-dedup.
    if plan.unique_field is not None:
        keys = [r.get(plan.unique_field) for r in deduped]
        if len(keys) != len(set(map(str, keys))):
            raise RecipeExecutionError(
                f"assert_unique: field {plan.unique_field!r} is not unique post-dedup; FAILED"
            )

    if len(deduped) < plan.expected_min_jobs:
        raise RecipeExecutionError(
            f"recipe produced {len(deduped)} records, below expected_min_jobs="
            f"{plan.expected_min_jobs} — refusing to report a partial board"
        )

    declared_total = _compute_declared_total(plan.oracle, state, http)

    evidence = HarvestEvidence(
        declared_total=declared_total,
        cap_hit=state.cap_hit,
        terminated_cleanly=state.terminated_cleanly and not state.cap_hit,
        page_advance_ok=_page_advance_ok(state.page_id_sets),
        pages_fetched=state.pages_fetched,
        transport_ok=True,
    )
    return deduped, evidence
