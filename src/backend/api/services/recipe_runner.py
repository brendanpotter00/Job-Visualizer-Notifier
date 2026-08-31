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

It is ALSO the home of the transport-agnostic half every other tier reuses:
:func:`parse_plan`, :func:`harvest_json_pages` and :func:`finalize_harvest`. The
``browser_fetch`` tier (Phase 3c) fetches its pages in a Chromium subprocess and
so can never execute inside this module — but it calls those three, so the
RAISES-never-empty ladder, the first-occurrence dedupe and the oracle exist in
exactly one place. The dependency arrow is one-way: ``browser_fetch`` imports
``recipe_runner``, NEVER the reverse (the AST import guard walks this module's
whole closure and would fail the moment it could reach a browser driver).

This module imports only the stdlib, ``httpx``, the dependency-free
:mod:`recipe_schema` / :mod:`harvest_meta`, and (lazily, inside the HTML path)
``bs4``. It must stay that thin — the import guard test walks its AST.
"""

from __future__ import annotations

import copy
import html
import json
import logging
import re
import sys
import time
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit
from xml.etree import ElementTree

import httpx

from .harvest_meta import HarvestEvidence
from .recipe_schema import (
    RecipeError,
    dig,
    dig_records_with_skips,
    validate_recipe,
)

logger = logging.getLogger(__name__)

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

# --------------------------------------------------------------------------
# THE TWO RUNTIME BOUNDS ON A SWEEP. Neither is a page count, and that is the point.
# --------------------------------------------------------------------------
# There used to be a third: a FLAT 100-page ceiling baked into the stored recipe (the
# now-deleted ``capture/discover._MAX_HARVEST_PAGES``). A flat page ceiling means a
# different job ceiling on every board, because the page SIZE is the board's choice —
# 100 pages is
# 10,000 jobs of amazon.jobs (100/page) and 1,000 jobs of Microsoft's Eightfold board
# (10/page, hard — it ignores every page-size parameter). Microsoft declares 2,111 and
# we read 1,000 of them: under half the board, truncated by our constant and by nothing
# about Microsoft. The ceiling existed to fit the leaf task's 120s timeout, which is the
# tail wagging the dog — the timeout moved (``fetch_custom_company._TASK_TIMEOUT_S``)
# and the bounds below replaced the page count with the two things that actually cost
# something.
#
# WALL CLOCK is the real protection, and the only one a lying board cannot inflate. A
# fake feed that declares ten million jobs still gets exactly this many seconds; a
# 47,000-job board (Walmart, the largest measured anywhere) reads as far as the clock
# allows and reports honestly that it did not finish. Ten minutes at the ~0.25-0.72s
# per page measured on real boards is ~830-2,400 pages, which covers every board we
# have measured except Walmart-scale ones — and those are the ones that MUST come back
# incomplete rather than pretend.
HARVEST_TIME_BUDGET_S = 600.0

# ...and a ROW ceiling, because time alone does not bound memory. Every row is held in
# ``_HarvestState.rows`` until ``finalize_harvest``, so a fast-paging board could stay
# inside the clock and still stream a very large transient allocation into a worker
# that co-hosts the API. 50,000 covers Walmart's 47,298 — the largest board measured
# anywhere — with headroom, so it is a backstop nobody should ever meet, not a
# truncation.
MAX_HARVEST_RECORDS = 50_000

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


# The optionals a board may legitimately publish as a LIST of scalars, so a list there is
# real multi-value data rather than a mis-mapped path one level too high. ``posted_at`` is
# deliberately NOT one of them: a posting has a single publish date, so a list is always a
# mis-map, and folding it would hand ``parse_date`` a string it can only fail on.
_MULTI_VALUE_FIELDS = frozenset({"location", "department", "company"})

# Not cosmetic: ``"; "`` is the multi-location spelling the Tier-2 normalization prompt
# already documents and few-shots ("Sunnyvale, CA, USA; Kirkland, WA, USA" is two), so a
# folded list canonicalizes into the several ``job_locations`` rows it should rather than
# into one nonsense place.
_MULTI_VALUE_SEPARATOR = "; "


def _fold_scalar_list(value: Any) -> Any:
    """Fold a list of scalars into one ``'; '``-joined string; pass everything else through.

    A board that publishes ``locations: ["Remote - Japan - Remote", "Remote - Remote"]``
    has a perfectly good location — it just is not a bare string. Until this existed the
    list tripped discovery's non-scalar prune
    (``request_selector._prune_non_scalar_optionals``) and the model's CORRECT mapping was
    deleted from the stored recipe outright, so every job on the board landed with a NULL
    location and ``normalization_status='failed'`` — silently, at 100%. Measured on
    Atlassian (235/235 jobs, ``locations``) and Microsoft (2,055/2,055,
    ``standardizedLocations``).

    A list holding a CONTAINER is returned untouched so the prune still deletes it:
    ``[{'en_name': 'San Jose'}]`` has its leaf one level down, and joining reprs would write
    a Python spelling into the location column — the exact corruption the prune exists to
    stop. An empty list folds to ``None`` (a board that published no location for this job),
    never to ``""``, so it reads as absent everywhere downstream.
    """
    if not isinstance(value, list):
        return value
    if any(isinstance(v, (dict, list)) for v in value):
        return value
    parts = [
        text
        for text in (
            str(v).strip()
            for v in value
            if isinstance(v, (str, int, float)) and not isinstance(v, bool)
        )
        if text
    ]
    return _MULTI_VALUE_SEPARATOR.join(parts) if parts else None


# Mapped fields that are NOT unescaped, and why each one is exempt rather than merely
# unlisted — see :func:`render_row_field`.
#
# ``id`` is the half of ``job_listings``' composite primary key this board owns
# (``recipe_rows`` writes it verbatim). Rewriting it is not a cosmetic change: every
# existing row's key stops matching what tonight's harvest produces, so the whole board
# closes and re-inserts under new ids — the never-wrong-close failure, caused by us. It is
# also the default ``dedupe_key`` field, so the harvest's own identity would shift under it.
#
# ``url`` is a transport value, not display text: nothing renders it as prose, and an
# ``&amp;`` inside a query string is the *correct* spelling when the value came out of an
# HTML attribute. Measured on the dev DB: 0 of 4,741 custom rows carry an entity in ``url``
# (19 carry one in ``title``), so unescaping it buys nothing and risks rewriting a link.
_UNESCAPE_EXEMPT_FIELDS = frozenset({"id", "url"})

# Mapped fields that ARE unescaped, but LATER — a different claim from the set above, kept
# in a different name so the two reasons cannot be read as one.
#
# ``description`` is the only mapped field that is additionally TAG-STRIPPED downstream
# (``fetch_custom_company._plain_text``), and that extra step is what makes decoding here
# wrong for it. Decode-then-strip destroys the distinction the escaping exists to carry: a
# board publishing the literal text ``&lt;p&gt;`` has it decoded into a real ``<p>``, and
# the stripper — which by then cannot tell that from markup the board actually emitted —
# deletes it along with the prose around it. ``Own the P99 &lt; 100ms budget`` and a board
# describing HTML in an engineering job spec are the realistic shapes of that.
#
# Strip first, then decode once, and the ambiguity never exists: real tags are gone before
# any entity becomes an angle bracket. So this field's single decode happens at the strip
# site instead of here. It is still exactly one decode — see :func:`render_row_field`.
_DEFERRED_UNESCAPE_FIELDS = frozenset({"description"})


def render_row_field(record: Any, name: str, spec: str) -> Any:
    """Render ONE mapped field the way a stored row will actually carry it.

    THE shared seam between this runner and discovery's ``_prune_non_scalar_optionals``:
    the prune decides whether a mapping is usable, so it has to render through exactly what
    the runner will produce. Rendering the two differently is how a usable mapping gets
    thrown away — or an unusable one kept and written as a repr.

    **THE ENTITY RULE, in one line: one decode per field, and for a field that is
    tag-stripped, that decode happens AFTER the stripping.**

    That is the whole invariant, and it is sharper than the "this is the single unescape
    site" it replaces — which was both false and, for one field, the wrong target anyway.

    *Why decode at all.* A discovered board hands us whatever its own page markup carried
    — 19 of 85 custom Spotify titles arrive as ``Client Partner, Emerging &amp; Scaled``
    — and leaving that costs twice: the entity renders literally in the job list, and any
    exact-match comparison against another board silently misses (it measured the Spotify
    title overlap at 56/81 instead of the true 70/81).

    *Why exactly once.* Two decodes turn ``&amp;amp;`` — a board that really does publish
    the five characters ``&amp;`` — into a bare ``&``, and nothing downstream can tell
    that from a board that published ``&`` to begin with. ``_plain_text`` used to be a
    silent second site for ``description``, so every recipe-path job hit both passes.

    *Why the ORDER is part of the rule and not a detail.* Decoding before a tag strip
    destroys the very distinction the escaping carries. A board publishing the literal
    text ``&lt;p&gt;`` gets it decoded into a real ``<p>``; the stripper then cannot tell
    that from markup the board actually emitted, and deletes it along with the prose
    around it. Removing the second decode does not fix that — the FIRST one is the one
    doing the damage. So ``description``, the one tag-stripped field, is deferred here
    (``_DEFERRED_UNESCAPE_FIELDS``) and decoded once at the strip site instead.

    Both halves are pinned by tests in ``test_recipe_runner_invariants``, including
    against a real captured Atlassian payload, because a docstring is not an enforcement
    mechanism — that is exactly how the previous claim came to be false.

    Fold order is unrelated and also load-bearing: the fold runs first so a multi-value
    list is joined and then decoded once, rather than element-by-element with a separator
    that carries no entities anyway.
    """
    rendered = render_field(record, spec)
    if name in _MULTI_VALUE_FIELDS:
        rendered = _fold_scalar_list(rendered)
    if (
        isinstance(rendered, str)
        and name not in _UNESCAPE_EXEMPT_FIELDS
        and name not in _DEFERRED_UNESCAPE_FIELDS
    ):
        return html.unescape(rendered)
    return rendered


def map_records(records: list[Any], fields: dict[str, str], base_url: str = "") -> list[dict]:
    """Map raw records to rows via ``fields``; drop rows missing id/title; stringify id."""
    mapped: list[dict] = []
    for record in records:
        row = {name: render_row_field(record, name, spec) for name, spec in fields.items()}
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
class RecipePlan:
    """A validated script folded into the shape the executors read.

    PUBLIC because the ``browser_fetch`` tier (which runs its transport out of
    process and cannot live in this module) needs the same parsed plan to build its
    subprocess request and to re-assert the page bound on read. Everything on it is
    transport-agnostic.
    """

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


# Ops that carry NOTHING for the plan to fold because the runner enforces them
# structurally on every run regardless of whether the script asks for one: 2xx is checked
# at every fetch, page advance is derived from ``state.page_id_sets``, ids-vs-total and
# delta-vs-last-run are computed in ``finalize_harvest`` / the Phase-2 gate. Listing them
# is what lets the dispatch below have a raising ``else`` — without this set, "the runner
# handles it elsewhere" and "the runner cannot handle it at all" are the same silence.
_STRUCTURAL_OPS = frozenset({
    "assert_status",
    "assert_page_advances",
    "assert_unique_ids_vs_total",
    "assert_delta_vs_last_run",
})


def parse_plan(script: dict[str, Any]) -> RecipePlan:
    """Fold a VALIDATED script's ``steps`` list into a :class:`RecipePlan`.

    Assumes :func:`~api.services.recipe_schema.validate_recipe` already ran — the
    ``assert`` below is the shape guarantee it makes, not a check. Public for the
    same reason :class:`RecipePlan` is.

    The dispatch is EXHAUSTIVE and its ``else`` raises. It used to fall off the end: an op
    the schema knows the shape of but this engine cannot execute — ``lookup_join`` is the
    one that exists — validated on write and was then dropped on the floor here, so the
    board scraped "successfully" every night while never doing the per-job detail fetch its
    own recipe asked for. Nothing anywhere reported it. That is the same class of silence as
    returning ``[]`` for a board that failed, and it gets the same answer: raise.
    :class:`~api.services.recipe_schema.RecipeError` is a ``ValueError``, which is in the
    leaf task's narrow ``except`` — so this lands as a recorded FAILED run, which harvests
    nothing and closes nothing, not as an unhandled crash.
    """
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
        elif op in _STRUCTURAL_OPS:
            pass  # nothing to fold — see _STRUCTURAL_OPS.
        else:
            raise RecipeError(
                f"steps[].op {op!r} validates but the replay engine has no executor for "
                "it — refusing to run a recipe that would silently do less than it says"
            )

    assert fetch is not None and extraction is not None  # guaranteed by validate_recipe
    base_url = script.get("base_url") or extraction.get("base_url", "")
    return RecipePlan(
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

def iter_body_params(body: Any) -> Iterator[tuple[tuple[str, ...], str, Any]]:
    """Every LEAF slot in a captured POST body as ``(path, name, value)``, SHALLOWEST
    FIRST.

    A "leaf" is any key whose value is not a nested object, so a wrapper such as
    ``page: {pageSize, pageNumber}`` yields its two children and never itself —
    a cursor merge that replaced the wrapper with an int would destroy the request.

    Breadth-first, and that ordering is the compatibility guarantee: a body that
    already carries the parameter at the TOP level resolves to the top level exactly
    as ``dict.update`` did, so every board whose cursor was already flat (TikTok's
    ``offset``, Amazon's query cursor) is untouched by construction. Only a body where
    the name appears solely deeper down behaves differently — which is the bug.

    Lists are not descended into. No board we have captured nests its cursor inside an
    array, and walking one would make "the parameter" ambiguous across elements.
    """
    if not isinstance(body, dict):
        return
    queue: deque[tuple[tuple[str, ...], dict[str, Any]]] = deque([((), body)])
    while queue:
        prefix, node = queue.popleft()
        for key, value in node.items():
            name = str(key)
            if isinstance(value, dict):
                queue.append((prefix + (name,), value))
            else:
                yield prefix + (name,), name, value


def find_body_param_path(body: Any, name: str) -> tuple[str, ...] | None:
    """Where ``name`` already lives inside ``body``, or ``None`` if it is not there."""
    for path, key, _value in iter_body_params(body):
        if key == name:
            return path
    return None


def merge_body_params(
    body: dict[str, Any] | None, params: dict[str, Any] | None
) -> dict[str, Any]:
    """The captured POST body with the cursor set WHERE IT ALREADY IS.

    THE BUG THIS REPLACES: ``merged_body.update(params)`` writes the cursor at the top
    level unconditionally. A GraphQL envelope carries it nested —
    ``body.variables.searchQueryInput.page.pageNumber`` on higher.gs.com — so the
    update added an ignored sibling key and every one of the 56 pages was page 0.
    Dedupe then collapsed 1,120 rows to 20 and the board looked like a 20-job company.
    Measured live: the top-level injection is byte-identical to page 0, the nested one
    has zero id overlap with it.

    A name that appears nowhere in the body still lands at the TOP LEVEL, unchanged —
    a board that genuinely takes a cursor key it did not send us keeps working.

    Deep-copies, and that is load-bearing rather than tidy: the body belongs to the
    STORED recipe and every page re-merges into it, so mutating a nested dict in place
    would edit the recipe under the sweep.
    """
    merged = copy.deepcopy(dict(body or {}))
    for name, value in (params or {}).items():
        path = find_body_param_path(merged, name)
        if path is None:
            merged[name] = value
            continue
        node: Any = merged
        for segment in path[:-1]:
            node = node[segment]
        node[path[-1]] = value
    return merged


# THE OTHER PLACE A PAGE CURSOR HIDES: inside ONE query parameter's value.
#
# Oracle Fusion Recruiting — one of the largest enterprise ATSs, and the ATS behind
# jpmc.fa.oraclecloud.com's 7,181 postings — carries its whole search, including the
# paging, in a single composite value:
#
#     finder=findReqs;siteNumber=CX_1001,facetsList=...,limit=25,sortBy=...,offset=75
#
# ``offset`` is not a query parameter there, it is a token inside one. Merging a new
# top-level ``?offset=25`` changes nothing the board reads, so every page of the sweep
# would be page one — the exact shape of the higher.gs.com nested-body bug this module
# already fixes for POSTs, in the other transport.
#
# Delimited by ``,`` OR ``;`` because Oracle uses both in the same value, and the token
# value must be an INTEGER: that is what keeps ``sortBy=POSTING_DATES_DESC`` and
# ``facetsList=LOCATIONS;WORK_LOCATIONS`` out of reach of a cursor write.
_COMPOSITE_DELIMITERS = ",;"


def composite_param_pattern(name: str) -> re.Pattern[str]:
    """Match ``<name>=<int>`` as a whole delimited token of a composite value."""
    return re.compile(
        rf"(?:(?<=[{_COMPOSITE_DELIMITERS}])|\A){re.escape(name)}="
        rf"(?P<value>\d+)(?=[{_COMPOSITE_DELIMITERS}]|\Z)"
    )


def iter_composite_query_params(url: str) -> Iterator[tuple[str, str, str]]:
    """``(container, name, value)`` for every ``name=<int>`` token inside a query value.

    ``container`` is the query parameter the token lives in, so a caller can rewrite
    that one value and leave the rest of the query byte-identical.
    """
    for container, raw in parse_qsl(urlsplit(url).query, keep_blank_values=True):
        if not any(d in raw for d in _COMPOSITE_DELIMITERS):
            continue
        for token in re.split(f"[{_COMPOSITE_DELIMITERS}]", raw):
            name, sep, value = token.partition("=")
            if sep and value.isdigit() and name:
                yield container, name, value


def merge_query_params(url: str, params: dict[str, Any] | None) -> httpx.URL:
    """The captured URL with the cursor set WHERE IT ALREADY IS.

    The GET twin of :func:`merge_body_params`, and it exists for the same reason: a
    cursor written somewhere the board does not read it makes every page page one.
    A name that is already a real query parameter, or that appears nowhere, still goes
    through ``copy_merge_params`` exactly as before — so every board that works today
    is untouched by construction.
    """
    target = httpx.URL(url)
    if not params:
        return target
    inline = {k: v for k, v in params.items() if k not in target.params}
    if not inline:
        return target.copy_merge_params(params)
    placed: set[str] = set()
    rewritten: list[tuple[str, str]] = []
    for container, raw in parse_qsl(urlsplit(url).query, keep_blank_values=True):
        for name, cursor in inline.items():
            pattern = composite_param_pattern(name)
            if pattern.search(raw):
                raw = pattern.sub(lambda _m: f"{name}={cursor}", raw, count=1)
                placed.add(name)
        rewritten.append((container, raw))
    if not placed:
        return target.copy_merge_params(params)
    target = httpx.URL(url).copy_with(query=urlencode(rewritten).encode())
    left = {k: v for k, v in params.items() if k not in placed}
    return target.copy_merge_params(left) if left else target


def _form_fields(body: Any) -> dict[str, str]:
    """A validated form body as the ``name=value`` strings httpx will urlencode.

    ``validate_recipe`` already refused any non-scalar value (a nested form body pages
    correctly in the recipe and not at all on the wire), so this only has to stringify.
    The merged pagination cursor arrives as an ``int``, which is exactly why the
    stringify happens HERE rather than being assumed of the stored body.
    """
    if not isinstance(body, dict):
        return {}
    return {str(name): str(value) for name, value in body.items() if value is not None}


def _request(
    http: httpx.Client, fetch: dict[str, Any], params: dict[str, Any] | None
) -> httpx.Response:
    method = fetch.get("method", "GET")
    headers = {"User-Agent": USER_AGENT, **(fetch.get("headers") or {})}
    if method == "POST":
        # SET the cursor where the captured body already carries it — see
        # :func:`merge_body_params`. A flat body is merged exactly as before.
        merged_body = merge_body_params(fetch.get("body"), params)
        if fetch.get("body_encoding", "json") == "form":
            # ...and OVERRIDE the captured content-type, which is the one header that
            # cannot be allowed to disagree with the encoding: form bytes under
            # ``application/json`` is a 400 on every board, and the recipe's own
            # ``body_encoding`` is the authoritative statement of what is on the wire.
            # Only the ``form`` branch does this — the ``json`` branch is left byte-for-
            # byte as it was so no stored recipe changes meaning.
            headers = {
                **headers, "content-type": "application/x-www-form-urlencoded",
            }
            response = http.post(
                fetch["url"], data=_form_fields(merged_body), headers=headers
            )
        else:
            response = http.post(fetch["url"], json=merged_body, headers=headers)
    else:
        # MERGE the cursor into the URL's existing query rather than passing
        # params= — httpx replaces the whole query string, which silently drops
        # every filter and turns a 76-job search into the global 10,000-job one
        # (replay.py:104-108). Silent scope change is the failure class this exists
        # to eliminate.
        # ...and SET it inside a composite value where the board already carries it —
        # see :func:`merge_query_params`. A flat cursor merges exactly as before.
        response = http.get(merge_query_params(fetch["url"], params), headers=headers)
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
    # The records-only form, for every caller that is NOT deciding whether a page was
    # short. A ``records_path`` may carry one ``*`` segment meaning "the union of every
    # group's array" (binance.com ships its whole board as 14 department groups); a
    # path that does not resolve, or resolves to something that is not a list, is still
    # the loud failure it always was.
    return _dig_page_records(payload, records_path, where)[0]


def _dig_page_records(
    payload: Any, records_path: str, where: str
) -> tuple[list[Any], int]:
    """``(records, elements the wildcard skipped)`` — the form a SWEEP must use.

    A sweep decides "was this the last page?" by comparing what came back against the
    page size, and the wildcard can drop an element (a null Relay ``node``, an element
    missing its wrapper key — see :func:`recipe_schema.dig_records_with_skips`). Those
    two facts multiply: 25 elements minus one null node is 24 records, 24 < 25 reads
    as a short final page, the loop breaks with ``terminated_cleanly=True``, and every
    job on every page after it is absent from a harvest that calls itself complete.
    Two of those close the lot. Counting the skips is what lets the caller ask the only
    question that is actually about the board — *how many elements did it serve?*
    """
    try:
        records, skipped = dig_records_with_skips(payload, records_path)
    except RecipeError as exc:
        raise RecipeExecutionError(
            f"records_path {records_path!r} did not resolve {where}: {exc}"
        ) from exc
    if not isinstance(records, list):
        raise RecipeExecutionError(
            f"records_path {records_path!r} did not resolve to a list {where}"
        )
    return records, skipped


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
    # Set when :data:`HARVEST_TIME_BUDGET_S` ran out mid-sweep. Distinct from
    # ``cap_hit`` (which it also sets) because a FACET fan-out must tell the two
    # apart: a ``window_cap`` stops ONE facet and the next one still deserves its
    # sweep, while an exhausted clock stops the whole run.
    budget_exhausted: bool = False


def _sweep_offset_page(
    http: httpx.Client,
    plan: RecipePlan,
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
    deadline: float | None = None,
) -> None:
    """One offset/page sweep. Appends mapped rows + per-page id sets onto ``state``.

    ``deadline`` is a ``time.monotonic()`` stamp shared across the WHOLE harvest (every
    facet included). Blowing it stops the sweep exactly like a ``window_cap`` does —
    ``cap_hit=True`` and no short final page — which is what makes an over-budget run
    read as UNVERIFIED ``cap_hit`` in ``verify_harvest`` instead of a completed read.
    That routing is the load-bearing half: an unfinished sweep that looked finished
    would let the destructive tail close every job it never got to (invariant #2).
    """
    cursor = 0 if style == "offset" else start_page
    seen_pages = 0
    ended_short = False
    while seen_pages < max_pages:
        # THE TWO RUNTIME BOUNDS, checked BEFORE the request so neither is exceeded
        # rather than merely detected. Both are gated on at least one page having been
        # fetched somewhere in this harvest: the first page of a run must always
        # happen, or an already-spent budget would turn a run into zero rows — and zero
        # rows is FAILED ("we learned nothing"), which is a louder, wronger answer than
        # a partial UNVERIFIED read.
        if state.pages_fetched > 0:
            if deadline is not None and time.monotonic() >= deadline:
                state.cap_hit = True
                state.budget_exhausted = True
                logger.warning(
                    "recipe sweep hit the %.0fs wall-clock budget after %d page(s) / "
                    "%d row(s) at %s — the run is INCOMPLETE (cap_hit → UNVERIFIED, "
                    "closes nothing). Raise HARVEST_TIME_BUDGET_S only together with "
                    "fetch_custom_company._TASK_TIMEOUT_S.",
                    HARVEST_TIME_BUDGET_S, state.pages_fetched, len(state.rows),
                    plan.fetch.get("url"),
                )
                break
            if len(state.rows) >= MAX_HARVEST_RECORDS:
                state.cap_hit = True
                state.budget_exhausted = True
                logger.warning(
                    "recipe sweep hit the %d-record ceiling after %d page(s) at %s — "
                    "the run is INCOMPLETE (cap_hit → UNVERIFIED, closes nothing)",
                    MAX_HARVEST_RECORDS, state.pages_fetched, plan.fetch.get("url"),
                )
                break
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
        page_records, skipped = _dig_page_records(
            payload, records_path, f"on page {seen_pages}"
        )
        page_rows = map_records(page_records, fields, plan.base_url)
        state.rows.extend(page_rows)
        state.page_id_sets.append({r["id"] for r in page_rows})
        seen_pages += 1
        state.pages_fetched += 1
        # THE SHORT-PAGE TEST IS ABOUT THE BOARD, NOT ABOUT OUR PATH. ``skipped`` is
        # the elements the wildcard dropped (see :func:`_dig_page_records`), so adding
        # it back asks "did the board serve a full page?" instead of "did a full page
        # survive ``records_path``?". Without it, one null ``edges[].node`` ends the
        # sweep mid-board and still reports a clean complete read — the one shape that
        # closes jobs that are still open. ``skipped`` is 0 for every non-wildcard
        # path, so this is byte-identical for every board running today, and where it
        # differs it can only make the sweep keep paging: the worst it can do is run
        # out of pages, which is ``terminated_cleanly=False`` → UNVERIFIED → nothing
        # closes.
        if len(page_records) + skipped < page_size:
            ended_short = True
            break
        cursor += page_size if style == "offset" else 1
    # A sweep that ran out its page budget without a short final page has not
    # provably seen the whole slice.
    if ended_short:
        state.terminated_cleanly = state.terminated_cleanly and True
    else:
        state.terminated_cleanly = False


def _run_http_json(http: httpx.Client, plan: RecipePlan) -> _HarvestState:
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

    # ONE deadline for the whole harvest, stamped here rather than per sweep: a facet
    # fan-out is N sweeps of the same board, and N budgets would multiply the wall clock
    # by the facet count — which is exactly the bound we are trying to hold.
    deadline = time.monotonic() + HARVEST_TIME_BUDGET_S

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
                deadline=deadline,
            )
            # An exhausted clock ends the RUN, not just this facet — otherwise every
            # remaining facet pays one wasted request to discover the same thing, and
            # a 38-facet board turns the bound into 38 extra round-trips.
            if state.budget_exhausted:
                break
    else:
        style = {"paginate_offset": "offset", "paginate_page": "page"}[op]
        param = pg["param"]
        page_size = pg["page_size"]
        max_pages = pg["max_pages"]
        start_page = int(pg.get("start_page", 1))
        window_cap = pg.get("window_cap")
        _sweep_offset_page(
            http, plan, state, {}, style, param, page_size, max_pages,
            start_page, window_cap, records_path, fields, deadline=deadline,
        )
    return state


def _resolve_facet_values(http: httpx.Client, plan: RecipePlan, pg: dict[str, Any]) -> list[str]:
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

def _run_http_html(http: httpx.Client, plan: RecipePlan) -> _HarvestState:
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


# --------------------------------------------------------------------------
# the Next.js App-Router (React Flight) row parser — extract_embedded_island
# with source='rsc_flight' (PATH-TO-90-PERCENT.md §6, Stage 2)
# --------------------------------------------------------------------------
#
# A Next.js App-Router page does not embed one JSON island. It streams a React Flight
# document in dozens of ``<script>self.__next_f.push([1,"<chunk>"])</script>`` calls
# whose decoded chunks CONCATENATE into one text stream, and that stream is a sequence
# of rows::
#
#     <hex-id> ":" <payload> "\n"
#
# ``<payload>`` is a JSON value, optionally with a one-letter tag in front (``I[…]``
# module refs, ``HL[…]`` preloads, ``E{…}`` errors), OR a length-prefixed text blob
# ``T<hexlen>,<blob>``.
#
# THE BYTE LENGTH IS THE DETAIL THAT DECIDES WHETHER THIS WORKS. ``T<hexlen>`` counts
# UTF-8 BYTES, not characters, and the blobs are job descriptions full of typographic
# quotes and em dashes. Framing on characters lands mid-blob, the parser loses sync with
# the row grammar, and the row holding the jobs is never seen at all — measured on
# jobs.deel.com/job-boards/klarna, where a character-framed parse found 0 job arrays and
# a byte-framed one found all 81 at ``9.3.jobPostings``. So the whole parse runs on
# ``bytes``.
_RSC_PUSH_RE = re.compile(r"self\.__next_f\.push\(\[\s*1\s*,\s*")
_RSC_ROW_RE = re.compile(rb"([0-9a-fA-F]{1,8}):")

# Bounds. The body itself is whatever the board served; these keep a hostile or merely
# enormous page from turning one nightly replay into an unbounded allocation. Klarna's
# is 174 chunks / 473,102 chars / 32 rows, so each is ~an order of magnitude of headroom.
_RSC_MAX_CHUNKS = 4_000
_RSC_MAX_STREAM_CHARS = 8_000_000
_RSC_MAX_ROWS = 2_000


def parse_rsc_flight(scripts: list[str]) -> dict[str, Any]:
    """``{row_id: parsed JSON}`` for every Flight row in these ``<script>`` bodies.

    Public because it is the whole of the new capability and is worth testing directly
    against captured bytes. TEXT rows (``T<hexlen>,``) are FRAMED but not returned: they
    are the ``$<id>``-referenced description blobs, and resolving those references is
    the element-tree half of RSC that Stage 2 deliberately skips. Their length still has
    to be honoured or every row after them is lost.

    Never raises. An unparseable stream yields ``{}``, and the caller's ``records_path``
    dig is what turns that into the loud FAILED run — one place that decides, as
    everywhere else here.
    """
    decoder = json.JSONDecoder()
    chunks: list[str] = []
    total = 0
    for script in scripts:
        for match in _RSC_PUSH_RE.finditer(script):
            if len(chunks) >= _RSC_MAX_CHUNKS or total >= _RSC_MAX_STREAM_CHARS:
                break
            start = match.end()
            if script[start:start + 1] != '"':
                continue  # push([1, <non-string>]) — a flush marker, not a chunk
            try:
                value, _ = decoder.raw_decode(script, start)
            except ValueError:
                continue
            if isinstance(value, str):
                chunks.append(value)
                total += len(value)
    if not chunks:
        return {}

    raw = "".join(chunks).encode("utf-8")
    rows: dict[str, Any] = {}
    pos, end = 0, len(raw)
    while pos < end and len(rows) < _RSC_MAX_ROWS:
        marker = _RSC_ROW_RE.match(raw, pos)
        if marker is None:
            newline = raw.find(b"\n", pos)
            if newline == -1:
                break
            pos = newline + 1
            continue
        row_id = marker.group(1).decode("ascii")
        pos = marker.end()
        if raw[pos:pos + 1] == b"T":
            comma = raw.find(b",", pos)
            if comma == -1:
                break
            try:
                length = int(raw[pos + 1:comma], 16)
            except ValueError:
                break
            pos = comma + 1 + length          # BYTES — see the note above
            if raw[pos:pos + 1] == b"\n":
                pos += 1
            continue
        newline = raw.find(b"\n", pos)
        stop = end if newline == -1 else newline
        payload = raw[pos:stop].lstrip(b"IHEL")
        pos = stop + 1
        if payload[:1] in (b"[", b"{"):
            try:
                rows.setdefault(row_id, json.loads(payload))
            except ValueError:
                continue
    return rows


def _run_embedded_island(http: httpx.Client, plan: RecipePlan, state: _HarvestState) -> None:
    from bs4 import BeautifulSoup  # local import: html-only dependency

    ext = plan.extraction
    response = _request(http, plan.fetch, None)
    state.first_headers = dict(response.headers)
    soup = BeautifulSoup(response.text, "html.parser")
    if ext.get("source") == "rsc_flight":
        # ALL matching nodes, not one: the stream is split across every push script and
        # a single node holds a fragment that parses to nothing.
        nodes = soup.select(ext["selector"])
        if not nodes:
            raise RecipeExecutionError(
                f"rsc_flight selector {ext['selector']!r} matched nothing (markup changed?)"
            )
        payload = parse_rsc_flight([node.get_text() for node in nodes])
        if not payload:
            raise RecipeExecutionError(
                f"rsc_flight selector {ext['selector']!r} matched {len(nodes)} node(s) "
                "but no React Flight rows parsed out of them"
            )
        state.first_payload = payload
        records = _dig_records(payload, ext["records_path"], "in the RSC flight stream")
        state.rows = map_records(records, ext["fields"], plan.base_url)
        state.page_id_sets = [{r["id"] for r in state.rows}]
        return
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


def _run_css(http: httpx.Client, plan: RecipePlan, state: _HarvestState) -> None:
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


# The longest subject a stored ``regex_capture`` pattern is ever run against. A URL
# longer than this is not a slug to read a title out of, and bounding the SUBJECT is the
# other half of the pattern bound in ``recipe_schema.validate_capture_pattern``: that
# one closes the exponential shapes, this one caps the polynomial residue.
CAPTURE_SUBJECT_MAX_CHARS = 512

# What ``unslug`` collapses to a space. ``+`` is here because a query-string slug spells
# a space that way, and ``unquote_plus`` is deliberately NOT used — a literal ``+`` in a
# PATH segment is a plus sign, and one rule that reads both is better than a decode that
# is right for one shape and silently wrong for the other.
_SLUG_SEPARATORS_RE = re.compile(r"[-_+]+")


def _unslug(text: str) -> str:
    """A URL slug as prose: percent-decoded, separators to spaces, whitespace collapsed.

    TITLE-CASING IS CONDITIONAL, and the condition is the whole of the rule: the result
    is title-cased ONLY when the slug carries no case information at all. Bloomberg's
    ``Senior-Software-Engineer-Data`` already spells its own capitalisation and
    ``.title()`` would not improve it, while Citadel's ``commodities-portfolio-manager``
    has none to preserve. Upper-casing a slug that already had case would be the wrong
    kind of confident — it would rewrite ``iOS`` and ``ML`` — so it is left alone.
    """
    text = unquote(text)
    text = _SLUG_SEPARATORS_RE.sub(" ", text)
    text = _MULTISPACE_RE.sub(" ", text).strip()
    if text and not any(ch.isupper() for ch in text):
        text = text.title()
    return text


def _transform_value(row: dict, step: dict[str, Any]) -> Any:
    kind = step["kind"]
    if kind == "template":
        return render_field(row, step["template"])
    if kind == "regex_capture":
        return _regex_capture_value(row, step)
    # base_url_join
    value = row.get(step["field"])
    if isinstance(value, str) and value.startswith("/"):
        return step["base_url"].rstrip("/") + value
    return value


def _regex_capture_value(row: dict, step: dict[str, Any]) -> Any:
    """Derive a field from another mapped field. **No match → ``None``, never a guess.**

    THE ONE RULE THIS PRIMITIVE EXISTS TO HOLD: a pattern that does not match must
    degrade the field to ABSENT, not leave the source value standing in its place. Both
    the boards this was built for map ``title`` to the job's own URL as the only way to
    get a row past ``map_records``; "leave it alone on a miss" would therefore ship a URL
    as a job title on exactly the rows where the derivation failed — the Bloomberg defect
    the primitive is meant to fix, reintroduced only on the rows nobody looks at.

    ``finalize_harvest`` is what turns an absent REQUIRED field into a FAILED run (see
    :func:`_assert_shaping_kept_required_fields`); an absent optional is simply absent.
    """
    value = row.get(step["from"])
    if not isinstance(value, str) or not value:
        return None
    match = re.search(step["pattern"], value[:CAPTURE_SUBJECT_MAX_CHARS])
    if match is None:
        return None
    captured = match.group(1)
    if captured is None:                      # an optional group that matched nothing
        return None
    if step.get("unslug"):
        captured = _unslug(captured)
    return captured or None


# Above this a numeric timestamp is MILLISECONDS, not seconds: 1e11 seconds is the
# year 5138, so nothing genuinely in seconds can reach it and nothing genuinely in
# milliseconds (1.7e12 today) falls below it. Same constant, same reasoning, as
# ``eightfold_client._parse_eightfold_epoch`` and ``scripts/shared/posted_date`` —
# the repo has exactly one rule for this and this is it.
_EPOCH_MS_THRESHOLD = 1e11


def _parse_date_value(value: Any, step: dict[str, Any]) -> Any:
    """Normalize to ISO-8601; NEVER synthesize — unparseable → None (dropped later)."""
    mode = step["mode"]
    # Epoch modes FIRST, and before the string guard: a board that publishes unix
    # time publishes a JSON *number*, so ``postedTs: 1787617881`` never reaches the
    # string branch. Requiring a string here is what made Microsoft's 2,055 rows
    # land with a NULL date even once a parse_date step existed.
    if mode in ("epoch_s", "epoch_ms"):
        return _parse_epoch_value(value)
    if not isinstance(value, str) or not value.strip():
        return None
    if mode == "iso":
        return _parse_iso_value(value.strip())
    if mode == "strptime":
        from datetime import datetime
        cleaned = _MULTISPACE_RE.sub(" ", value.strip())  # Amazon's double-space dates
        try:
            return datetime.strptime(cleaned, step["format"]).date().isoformat()
        except ValueError:
            return None
    # humanized ("about 12 hours") — no reliable absolute timestamp; leave as None so
    # the leaf task's first_seen tracking governs freshness. Correct as written, NOT a
    # gap: POSTED-DATE-PLAN.md §3 — a board that gives us a bucket has given us no date,
    # and synthesizing one from "12 hours" is the fabrication that rule exists to stop.
    return None


def _parse_iso_value(text: str) -> Any:
    """``text`` if it really is ISO-8601, else ``None``. Never raises.

    ``iso`` mode used to be the one mode that checked nothing: it returned
    ``value.strip()`` for any non-empty string, so a board that swapped its date field
    for a slug, a job id, or "Posted recently" sent that text down the path to
    ``recipe_rows`` → ``JobListing.posted_on`` → a TIMESTAMPTZ. The only thing standing
    between that and the column was ``fetch_custom_company._validated_posted_on``, one
    layer with no second — and ``recipe_rows``' own docstring meanwhile asserted the
    value was "already ISO-normalized", which nothing enforced. Every sibling mode
    (``strptime``, ``epoch_s``, ``epoch_ms``) has always returned ``None`` on input it
    could not read; this one now does too.

    Validated with ``fromisoformat``, not the shared ``posted_date`` parser, and that is
    the point of the mode's name: the shared parser also accepts a bare unix epoch, so a
    ten-digit JOB ID sitting in a date field would be read as a date in the year 2026
    and stored with total confidence. ``iso`` means the board publishes ISO; anything
    else is a board that changed, and a change we cannot read is a NULL.

    The value is handed back as the board spelled it (only stripped) rather than
    re-rendered, so ``posted_on`` keeps the raw board value the way the column is
    documented to. ``effective_posted_date`` / ``_validated_posted_on`` do the
    normalizing downstream.
    """
    from datetime import datetime

    candidate = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        datetime.fromisoformat(candidate)
    except (TypeError, ValueError):
        return None
    return text


def _parse_epoch_value(value: Any) -> Any:
    """Unix epoch (seconds or milliseconds, number or numeric string) → ISO-8601 UTC.

    ``epoch_s`` and ``epoch_ms`` name what discovery SAMPLED, and the magnitude
    decides what is actually parsed — deliberately, because the two failure modes
    of trusting the declared mode are both silent and both catastrophic for a sort
    key: milliseconds read as seconds land in the year 58,600, and seconds read as
    milliseconds land in January 1970. A board that changes magnitude between
    capture and tonight would produce one of those every night with no error. The
    mode stays in the schema because it records what the board looked like at
    capture time; the guard is what makes a drift a non-event.

    Never raises and never synthesizes: anything non-numeric, non-positive, or out
    of ``datetime``'s range is ``None``, exactly like every other mode here.
    """
    if isinstance(value, bool):
        # ``True`` is an int and epoch 1 is 1970-01-01. A flag in a date field is
        # not a date.
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
    elif not isinstance(value, (int, float)):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if numeric != numeric or numeric in (float("inf"), float("-inf")) or numeric <= 0:
        return None
    if numeric > _EPOCH_MS_THRESHOLD:
        numeric = numeric / 1000.0
    from datetime import datetime, timezone
    try:
        return datetime.fromtimestamp(numeric, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
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


# How many child sitemaps a ``<sitemapindex>`` may name before we refuse to count it.
# A sharded sitemap is real and small (Walmart's is one document; a big board shards
# into a handful); an index naming hundreds is a site map of a whole website, and
# reading every shard would turn one 300 ms oracle into a minutes-long crawl inside the
# harvest's own clock. Refusing is the safe answer — a FAILED oracle closes nothing.
_SITEMAP_INDEX_MAX_CHILDREN = 4


def _sitemap_locs(body: str, sitemap_url: str) -> tuple[list[str], bool]:
    """``(<loc> texts, is_index)`` for one sitemap document.

    THE SPLIT THIS FUNCTION EXISTS FOR. ``<urlset>`` and ``<sitemapindex>`` both carry
    ``<loc>`` elements and they mean opposite things — pages in the first, other
    SITEMAPS in the second. Measured on ``atlassian.com/sitemap.xml`` (2026-08-29): an
    index naming eight children, none of them jobs. Counting those eight as eight job
    pages is a wrong total that a tolerance-0 oracle would then compare a real harvest
    against.
    """
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise RecipeExecutionError(
            f"sitemap {sitemap_url!r} did not parse: {exc}"
        ) from exc
    tag = root.tag.rsplit("}", 1)[-1].lower() if isinstance(root.tag, str) else ""
    locs: list[str] = []
    for element in root.iter():
        name = (
            element.tag.rsplit("}", 1)[-1].lower() if isinstance(element.tag, str) else ""
        )
        if name != "loc":
            continue
        text = (element.text or "").strip()
        if text:
            locs.append(text)
    return locs, tag == "sitemapindex"


def _oracle_sitemap(http: httpx.Client, oracle: dict[str, Any]) -> int:
    """The board's own page count, from the sitemap it publishes for crawlers.

    A ``<sitemapindex>`` is followed exactly ONE level and only up to
    :data:`_SITEMAP_INDEX_MAX_CHILDREN` children, because a total we could only
    PARTLY read is worse than no total at all: this oracle is compared at tolerance 0
    (``harvest_verification._verify_oracle_total``), so an undercount from a truncated
    crawl is a number that could coincidentally equal tonight's harvest and VERIFY a
    board we never finished reading. Refuse instead — a FAILED oracle closes nothing.
    """
    pattern = oracle["url_pattern"]
    sitemap_url = oracle["sitemap_url"]
    response = _request(http, {"method": "GET", "url": sitemap_url, "headers": {}}, None)
    locs, is_index = _sitemap_locs(response.text, sitemap_url)

    if is_index:
        if len(locs) > _SITEMAP_INDEX_MAX_CHILDREN:
            raise RecipeExecutionError(
                f"sitemap {sitemap_url!r} is an index naming {len(locs)} child "
                f"sitemap(s), more than the {_SITEMAP_INDEX_MAX_CHILDREN} we will "
                "follow — a partly-read index is an undercount, not a total; FAILED"
            )
        child_locs: list[str] = []
        for child_url in locs:
            child = _request(
                http, {"method": "GET", "url": child_url, "headers": {}}, None
            )
            nested, nested_is_index = _sitemap_locs(child.text, child_url)
            if nested_is_index:
                # ONE level. A second is where an enormous site would spend the whole
                # harvest clock, and there is no honest partial answer to give.
                raise RecipeExecutionError(
                    f"sitemap {sitemap_url!r} is an index of indexes ({child_url!r} is "
                    "itself an index) — we follow exactly one level; FAILED"
                )
            child_locs.extend(nested)
        locs = child_locs

    count = sum(1 for text in locs if pattern in text)
    if count == 0:
        raise RecipeExecutionError(
            f"sitemap {sitemap_url!r} yielded 0 <loc> matching {pattern!r} — "
            "empty/unusable oracle; FAILED"
        )
    return count


def _compute_declared_total(
    oracle: dict[str, Any], state: _HarvestState, http: httpx.Client | None
) -> int | None:
    """``http`` is used by the SITEMAP branch ONLY, and may be ``None`` for a
    transport that has no HTTP client of its own (browser_fetch passes one only
    when the oracle needs it — a sitemap GET needs no browser). A ``None`` client
    with a sitemap oracle RAISES rather than silently reporting no total, because a
    vanished oracle must be FAILED, never 'no total today'."""
    kind = oracle["kind"]
    if kind in ("self_consistent", "none"):
        # Neither publishes a total. ``none`` additionally makes no completeness claim
        # at all — ``verify_harvest`` answers UNVERIFIED for it, so the run can never
        # close a job. Returning None here (rather than falling through to the
        # declared_probed branch) is what keeps that a verdict and not a KeyError.
        return None
    if kind == "facet_sum":
        return _oracle_facet_sum(state.first_payload, oracle)
    if kind == "header":
        return _oracle_header(state.first_headers, oracle)
    if kind == "sitemap":
        if http is None:
            raise RecipeExecutionError(
                "sitemap oracle needs an HTTP client but none was supplied; FAILED"
            )
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


def _assert_pinned(plan: RecipePlan, state: _HarvestState) -> None:
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


# The two row keys ``map_records`` refuses to let a row live without, and therefore the
# two a SHAPING step may not quietly take away again.
_SHAPING_REQUIRED_FIELDS = ("id", "title")


def _assert_shaping_kept_required_fields(
    rows: list[dict], shaping: list[dict[str, Any]]
) -> None:
    """RAISE if a shaping step emptied ``id`` or ``title`` on any row.

    Shaping is OUR derivation, not the board's data, and that asymmetry is the whole
    argument for raising here while ``map_records`` merely drops. ``map_records`` drops a
    record the BOARD published without a title — a real, ordinary thing for a board to
    do. A ``regex_capture`` that stops matching is us discovering that the recipe no
    longer describes the board, and there are only bad ways to be quiet about it:

    * leave the source value → a job list full of URLs where titles should be, which is
      the exact Bloomberg defect this primitive was added to fix;
    * drop the row → a SHORTER sweep that still reports ``terminated_cleanly`` with no
      cap, which on a ``self_consistent`` board VERIFIES and starts closing the missing
      jobs. That is invariant #2, lost to a silent partial;
    * write ``None`` → ``recipe_rows`` does ``str(row["title"])`` and stores the literal
      string ``"None"`` on every affected job.

    Raising is the only option that harvests nothing and closes nothing. It is a FAILED
    run: the leaf task records it, does not count a miss, and retries.

    Scoped to recipes that actually shape a required field, so a board with no such step
    pays one tuple comparison and nothing else.
    """
    targets = {
        step["field"] for step in shaping if step["field"] in _SHAPING_REQUIRED_FIELDS
    }
    if not targets:
        return
    for row in rows:
        for name in targets:
            if row.get(name) in (None, ""):
                raise RecipeExecutionError(
                    f"a shaping step emptied the required field {name!r} on a row "
                    f"(id={row.get('id')!r}, url={row.get('url')!r}) — the recipe no "
                    "longer describes this board; FAILED rather than storing a wrong "
                    "title or silently dropping the row"
                )


def finalize_harvest(
    plan: RecipePlan, state: _HarvestState, http: httpx.Client | None
) -> tuple[list[dict], HarvestEvidence]:
    """The transport-agnostic tail: pinned-identity → shaping → RAISES-never-empty →
    dedupe → assert_unique → the ``expected_min_jobs`` floor → oracle → evidence.

    ONE copy on purpose. Every one of those steps is an invariant-#1 surface, and a
    second transport that copy-pasted them would drift from this one silently — the
    exact way a "we saw zero rows" turns back into "no jobs today". ``browser_fetch``
    calls this same function with a state it built from raw subprocess output, so
    the ladder cannot fork.
    """
    _assert_pinned(plan, state)

    rows = _apply_shaping(state.rows, plan.shaping)
    _assert_shaping_kept_required_fields(rows, plan.shaping)
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


def harvest_json_pages(
    plan: RecipePlan,
    page_payloads: list[Any],
    *,
    first_headers: dict[str, str],
    terminated_cleanly: bool,
    cap_hit: bool = False,
    http: httpx.Client | None = None,
) -> tuple[list[dict], HarvestEvidence]:
    """Turn ALREADY-FETCHED JSON page bodies into ``(rows, evidence)``.

    The parsing half of ``_run_http_json`` with the transport removed: the caller
    says WHERE the payloads came from, this says what they MEAN. It exists so the
    ``browser_fetch`` tier — whose pages are fetched by a Chromium subprocess and
    can therefore never run inside this module — reuses the exact in-band-error
    check, ``records_path`` dig, field mapping, per-page id sets, dedupe, oracle and
    evidence build that the httpx tier uses, instead of a second implementation
    that drifts.

    ``terminated_cleanly`` / ``cap_hit`` are the CALLER's honest report about how
    its pagination loop stopped; ``first_headers`` is the first page's response
    headers (the ``header`` oracle reads them, case-insensitively).
    """
    if not page_payloads:
        raise RecipeExecutionError(
            "browser transport returned no pages at all — treated as FAILED, never "
            "as 'no jobs today'"
        )
    records_path = plan.extraction["records_path"]
    fields = plan.extraction["fields"]
    state = _HarvestState(
        rows=[], first_payload=page_payloads[0], first_headers=dict(first_headers),
        page_id_sets=[], cap_hit=cap_hit, terminated_cleanly=terminated_cleanly,
        pages_fetched=0,
    )
    for index, payload in enumerate(page_payloads):
        _check_inband_error(payload, plan.error_keys)
        page_records = _dig_records(payload, records_path, f"on page {index}")
        page_rows = map_records(page_records, fields, plan.base_url)
        state.rows.extend(page_rows)
        state.page_id_sets.append({r["id"] for r in page_rows})
        state.pages_fetched += 1
    return finalize_harvest(plan, state, http)


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

    HTTP transports ONLY. The dispatch below is exhaustive and its ``else`` RAISES:
    ``browser_fetch`` is a valid stored transport that this function must never
    silently run, because an implicit "everything else is HTML" would hand a JSON
    API to bs4 and fail with a nonsense selector error instead of naming the real
    problem (a browser transport reached the agent-free path).
    """
    assert_no_agent_imports()   # FIRST, every call — the agent-free proof.
    # validate-on-read: stored scripts drift, and the column-equality check catches
    # a JSONB row edited out of sync with its transport/oracle_kind columns.
    validate_recipe(script, transport=transport, oracle_kind=oracle_kind)
    plan = parse_plan(script)

    if plan.transport == "http_json":
        state = _run_http_json(http, plan)
    elif plan.transport == "http_html":
        state = _run_http_html(http, plan)
    else:
        raise RecipeExecutionError(
            f"transport {plan.transport!r} cannot run on the agent-free HTTP replay "
            "path — it needs its own out-of-band executor; FAILED"
        )

    return finalize_harvest(plan, state, http)
