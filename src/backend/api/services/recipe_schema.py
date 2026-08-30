"""Custom-company replay-script schema v1 — the closed primitive vocabulary (E7 Phase 3).

This is the strict validator for the ``company_scripts.script`` JSONB shape. It is
pure data definition + validation and — like ``harvest_meta`` — must never import
an agent, an LLM client, or a browser driver. It is consumed on **write** (the
discovery author, Phase 3b) *and* on **read** (``recipe_runner.run_recipe`` calls
it before touching a stored script, because a stored script is data that drifts).

The script is a multi-primitive ``steps`` list plus a completeness ``oracle``
block (BUILD-PLAN section 6). ``transport`` and ``oracle`` mirror the
``company_scripts.transport`` / ``oracle_kind`` columns and are validated equal to
them when the caller passes the column values.

Three transports are admitted, and the rule is about WHO ISSUES THE REQUEST, not
about how much browser a board needs:

* ``http_json`` / ``http_html`` — plain ``httpx`` from the agent-free replay worker.
* ``browser_fetch`` — the SAME captured request, re-issued by ``fetch()`` inside our
  own headless Chromium on the board's own origin (E7 Phase 3c). It exists for
  boards that origin-check / cookie-gate / sign their otherwise-deterministic JSON
  API (TikTok 400s outside the browser). It is still a deterministic recipe: no
  LLM, no DOM parsing, no agent. A ``browser_fetch`` script carries one extra
  REQUIRED top-level key, ``origin_url`` — the page to navigate to before fetching
  — which is **rejected** on the two HTTP transports (a stray ``origin_url`` there
  means the author mislabelled the transport, and silently ignoring it would ship a
  board that never gets its origin).

Everything ELSE browser-shaped is still rejected: the ``page_fetch``/``page_request``/
``dom``/``browser_dom`` transports and the ``click_sequence`` op are Phase 4
capabilities, and a rejected op names the missing capability so the REFUSE reason
is itself the next-primitive roadmap. Do not weaken this validator to admit them
early — ``browser_fetch`` deliberately buys "run our captured HTTP call on the
site's origin", NOT "let a script drive a browser".

Anything not enumerated here is a :class:`RecipeError`. Unknown keys inside a step
are rejected too: a typo must fail loudly, never silently no-op.

STAGE 2 (PATH-TO-90-PERCENT.md §6) widened the vocabulary in exactly three places, and
each one is a WIDENING of a closed set rather than an opening of it — the reason the
prior-art survey gave for keeping it closed (nobody documents sandboxing LLM-written
scraper code, so a config vocabulary is the feature) applies with equal force to the
additions:

* ``transform.kind = 'regex_capture'`` — derive a field from another MAPPED field via a
  regex in a bounded subset (:func:`validate_capture_pattern`). Not an expression
  language, nothing eval-shaped, and a non-matching pattern yields ABSENT, never a
  wrong value.
* ``fetch.body_encoding`` — ``json`` (the default, and what every stored recipe still
  means) or ``form``.
* ``extract_embedded_island.source = 'rsc_flight'`` — the Next.js App-Router row parser.
"""

from __future__ import annotations

import re
from typing import Any, Callable

RECIPE_VERSION = 1

# The admitted transports. ``browser_fetch`` re-issues the SAME captured request
# from inside our own Chromium (Phase 3c); the ``page_*``/``dom`` browser
# transports below stay Phase 4 and rejected.
TRANSPORTS = ("http_json", "http_html", "browser_fetch")

# The transport that runs the captured request on the site's origin, and therefore
# the ONLY one that carries ``origin_url``.
BROWSER_FETCH = "browser_fetch"

# The HTML transport. Named because it has a rule of its own below: its executor cannot
# paginate and reports a one-page read as a complete sweep, so a paginating html recipe
# is unstorable (see ``validate_recipe``).
HTTP_HTML = "http_html"

# THE BROWSER TIER'S PAGE CEILING, and the reason it lives in the SCHEMA rather than
# only in ``browser_fetch.runner``: a page budget the tier cannot honour is a property
# of the RECIPE, so it must be caught where every other unstorable recipe is — on write
# (discovery may not author one) and again on read (a drifted JSONB row FAILS loudly).
# The parent's own ``min(max_pages, ceiling)`` clamp still exists as defence in depth,
# but a clamp is the wrong last line: it silently truncates the sweep, and a truncated
# sweep that still terminates "cleanly" is how a partial board gets reported as a
# complete one. Each page here is a fresh in-browser ``fetch()`` inside one Chromium
# session bounded at 90s (``runner._SUBPROCESS_TIMEOUT_S``), which is what fixes the
# number at 25.
#
# IT DID NOT MOVE WHEN THE HTTP TIER'S DID, and that asymmetry is deliberate. The http
# tier dropped its flat page ceiling for a row ceiling plus a 600s clock
# (``recipe_runner.MAX_HARVEST_RECORDS`` / ``HARVEST_TIME_BUDGET_S``) because there a
# page is one cheap ``httpx`` GET and rows are what cost something. Here the PAGE is
# what costs: it holds a Chromium renderer, and the binding constraint is the single
# 90s session, not this count. Raising this number without raising that session just
# converts an honest truncated-and-UNVERIFIED sweep (which shows the board's jobs and
# closes none of them) into a FAILED run; raising the session means parking a browser
# on the worker for ten minutes per board, which is a different cost profile from 830
# sequential GETs. A browser-tier board bigger than 25 pages is a board this tier
# cannot fully read, and saying so is the correct answer.
BROWSER_FETCH_MAX_PAGES = 25

# Browser transports / ops that are still Phase 4 and rejected with a capability
# message. ``browser_fetch`` is deliberately NOT here — it is a captured-HTTP
# transport that happens to need an origin, not a drive-the-DOM capability.
_BROWSER_TRANSPORTS = ("page_fetch", "page_request", "dom", "browser_dom")
_BROWSER_OPS = ("click_sequence", "page_fetch", "page_request", "dom", "browser_dom")

# Ops that are named in the vocabulary's shape but NOT implemented by the replay
# engine, and are rejected with a capability message so an unsupported board
# REFUSES cleanly instead of crashing (a ``KeyError`` in ``_run_http_json`` would
# escape the RAISES-never-empty contract → the leaf task retries 5x and the
# discovery task dies with no refusal row). ``paginate_cursor`` is deliberately
# NOT implemented: reading the next URL/token out of the response body would add a
# fresh next-URL-from-body SSRF surface (E7 Phase 3b review, Finding 2).
#
# ``lookup_join`` belongs here for a worse reason than "unimplemented": it used to
# validate cleanly and then be DISCARDED by ``recipe_runner.parse_plan``'s
# non-exhaustive dispatch, so a stored recipe asking for a per-job detail fetch
# scraped happily every night while doing none of it, and nothing reported the gap.
# ``parse_plan`` now raises on any op it cannot run — this entry is the front half of
# the same fix, refusing the recipe at WRITE time so discovery records a refusal
# instead of storing a board that fails every replay for the rest of its life.
# ``_v_lookup_join`` is kept below as the shape spec for the day it is implemented
# (per-job detail fetch, deferred: ~10 min serial on the 2,055-job Microsoft board
# against a 600 s budget, and impossible on ``browser_fetch``); until then the
# validator is unreachable and this tuple is why.
_UNIMPLEMENTED_OPS = ("paginate_cursor", "lookup_join")

# Why each one is refused, so the rejection message names the actual reason rather than
# the reason of whichever op happened to be first in the tuple.
_UNIMPLEMENTED_OP_REASONS = {
    "paginate_cursor": "cursor pagination would add a next-URL-from-body SSRF surface",
    "lookup_join": "a per-job detail fetch has no executor and is deferred",
}

# Canonical job-field names an extraction may map (``fields`` / ``field_selectors``).
# A FIXED set — the discovery author's strict structured-output schema expresses
# ``fields`` as a CLOSED object over exactly these keys (no dynamic keys, which
# Anthropic strict mode forbids). ``id``/``title``/``url`` are mandatory (a row
# missing either id or title is dropped by ``map_records``); the rest are optional.
# ``recipe_rows`` promotes id/title/url/location/posted_at and folds the remainder
# into ``details``. ``validate_recipe`` requires the mandatory three and, being a
# read-path check over possibly-drifted stored data, does not otherwise constrain
# the key set — which is what lets a recipe captured under an older set keep
# replaying unchanged after this tuple moves.
#
# ``description`` earns its place by being the ONE key the enrichment claim reads:
# ``enrichment_monitor.DESCRIPTION_SQL`` COALESCEs over ``details->>'description'``,
# and until it could be mapped, every custom-company job was invisible to the
# enricher. A recipe that does not map it still validates; its rows are simply
# never claimable.
# The one non-literal segment a ``records_path`` may carry: "every element of the list
# here". See :func:`dig_records` for what it buys and why it is not in :func:`dig`.
RECORDS_WILDCARD = "*"

CANONICAL_REQUIRED_FIELDS = ("id", "title", "url")
CANONICAL_OPTIONAL_FIELDS = ("location", "posted_at", "description", "company")

# Oracle kinds. The three Phase-3 exact-match oracles, plus the two inherited from
# Phase 2 (a discovered board with no published total is legitimately
# ``self_consistent`` — Jane Street, YC), plus ``none``.
#
# ``none`` is the EXPLICIT no-claim oracle, matching the value the leaf task already
# defaults an un-oracled company to. ``verify_harvest`` maps it to UNVERIFIED
# ``no_oracle``, so a script carrying it shows its jobs every night and can never
# close one. Discovery stores it for a recipe that reads a single page of a board
# whose length nobody published — the case where claiming ``self_consistent`` would be
# certifying a sweep that never happened.
ORACLE_KINDS = (
    "facet_sum", "header", "sitemap", "declared_probed", "self_consistent", "none",
)

# Op categories used to enforce cardinality (exactly-one fetch, <=1 pagination,
# exactly-one extraction, exactly-one oracle-carrying script). ``paginate_cursor``
# is intentionally absent — it is rejected as unimplemented (see ``_UNIMPLEMENTED_OPS``).
_PAGINATION_OPS = ("paginate_offset", "paginate_page", "paginate_facet")
_EXTRACTION_OPS = ("extract_json_path", "extract_embedded_island", "extract_css")


class RecipeError(ValueError):
    """Raised when a script is structurally invalid. The message names the field."""


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise RecipeError(msg)


def _require_str(obj: dict[str, Any], key: str, where: str) -> None:
    _require(
        isinstance(obj.get(key), str) and bool(obj[key]),
        f"{where}.{key} must be a non-empty string",
    )


def _require_pos_int(obj: dict[str, Any], key: str, where: str) -> None:
    _require(
        isinstance(obj.get(key), int) and not isinstance(obj[key], bool) and obj[key] > 0,
        f"{where}.{key} must be a positive int",
    )


def _reject_unknown_keys(step: dict[str, Any], allowed: set[str], where: str) -> None:
    extra = set(step) - allowed - {"op"}
    _require(not extra, f"{where}: unknown key(s) {sorted(extra)} — a typo must fail loudly")


def _require_https(obj: dict[str, Any], key: str, where: str) -> None:
    url = obj.get(key)
    _require(
        isinstance(url, str) and url.startswith("https://"),
        f"{where}.{key} must be an https:// string",
    )


# ``[0]`` written where this resolver wants ``.0``. Digits only — a bracket holding
# anything else is left alone, so a board with a literal ``"items[all]"`` key still
# resolves by its real name.
_BRACKET_INDEX_RE = re.compile(r"\[(\d+)\]")


def dig(payload: Any, path: str) -> Any:
    """Resolve a dotted path such as ``data.jobs`` or ``hits`` inside a payload.

    An empty path returns the payload itself. List indices are supported as numeric
    segments (``data.0.jobs``). Kept verbatim from the spike — it is the resolver
    every extractor and oracle uses.

    ONE ADDITION to the spike's version: a path that fails AND spells a list index in
    BRACKETS is retried with ``[0]`` rewritten to ``.0``. ``locations[0].city`` is what
    the selector wrote for higher.gs.com; ``dig`` split on ``.`` only, so the lookup
    raised, ``render_field`` swallowed it, and every Goldman row stored
    ``location = NULL`` — silently, at 100%, the same class as the Atlassian and
    Microsoft location bugs commemorated in ``recipe_runner._fold_scalar_list``.

    The retry is a strict SUPERSET and that is the whole safety argument: a path that
    resolves today takes the first branch and never sees the rewrite, so no stored
    recipe changes meaning. A path that resolves under NEITHER spelling re-raises the
    ORIGINAL error, so diagnostics still name the path the recipe actually carries.
    """
    try:
        return _dig_dotted(payload, path)
    except RecipeError as original:
        normalized = _BRACKET_INDEX_RE.sub(r".\1", path)
        if normalized == path:
            raise
        try:
            return _dig_dotted(payload, normalized)
        except RecipeError:
            raise original from None


def _dig_dotted(payload: Any, path: str) -> Any:
    """:func:`dig` for a strictly dot-separated path. Every segment is a key or index."""
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


def dig_records(payload: Any, path: str) -> Any:
    """Resolve a ``records_path``, which MAY carry one :data:`RECORDS_WILDCARD` segment.

    THE ONE PATH SHAPE ``dig`` CANNOT EXPRESS, and the reason it exists is a measured
    partial read: binance.com serves its whole board as a list of 14 department groups
    (``[{title, postings: [...]}, ...]``), so every concrete path — ``4.postings`` — is
    ONE department. ``*.postings`` is the union of all fourteen: 276 postings instead
    of 88, from the very same captured bytes. Where the whole board is present in the
    response, ``records_path`` must be able to point at the whole board.

    ``*`` means "for each element of the list here, resolve the rest of the path and
    collect what it yields" — a list is CONCATENATED, a dict is taken as ONE RECORD. The
    second half is the per-element wrapper, and it is a whole family rather than one
    board: Elasticsearch answers ``hits.hits: [{_index, _id, _score, _source: {...}}]``
    and Relay answers ``edges: [{cursor, node: {...}}]``, so ``hits.hits.*._source`` and
    ``edges.*.node`` yield one dict per element. At most ONE wildcard is admitted
    (validated on write and again on read): a second one is a cross-product whose cost
    is unbounded in a payload we did not write, and no real board has needed it.

    An element that does not carry the remainder is SKIPPED rather than fatal — a
    grouped board legitimately ships an empty or shapeless group beside fourteen good
    ones, and refusing the whole board over one of them is the wrong trade. A path that
    yields nothing at all still raises through the caller's own non-empty check
    (``recipe_runner._dig_records``, ``request_selector._resolved_records``), so the
    RAISES-never-empty contract is unchanged.

    Kept beside :func:`dig` rather than folded into it on purpose: ``dig`` also resolves
    oracle totals and field templates, where a path returning a CONCATENATION instead of
    the value at that path would be a silent type change in the one place a wrong number
    closes jobs.
    """
    segments = path.split(".")
    if RECORDS_WILDCARD not in segments:
        return dig(payload, path)
    at = segments.index(RECORDS_WILDCARD)
    if at == len(segments) - 1 or RECORDS_WILDCARD in segments[at + 1:]:
        raise RecipeError(
            f"records_path {path!r} must carry at most one {RECORDS_WILDCARD!r} segment, "
            "and it may not be the last one"
        )
    # An EMPTY head is the common case, not an edge one: the payload itself is the list
    # of groups (binance ships a bare ``[{title, postings}, ...]``), which is the path
    # ``*.postings`` with nothing before the wildcard. ``dig(payload, "")`` returns the
    # payload, so this needs no special case — only a split that survives it.
    head = ".".join(segments[:at])
    tail = ".".join(segments[at + 1:])
    groups = dig(payload, head)
    if not isinstance(groups, list):
        raise RecipeError(
            f"records_path {path!r}: {head or '<root>'!r} is a "
            f"{type(groups).__name__}, not a list to iterate"
        )
    out: list[Any] = []
    for group in groups:
        try:
            found = dig(group, tail)
        except RecipeError:
            continue
        if isinstance(found, list):
            out.extend(found)
        elif isinstance(found, dict):
            # ONE RECORD PER ELEMENT, not a list of them — the PER-ELEMENT WRAPPER, and
            # the second shape a whole ATS family needs. Elasticsearch answers
            # ``hits.hits: [{_index, _id, _score, _source: {...}, sort}]`` and Relay
            # answers ``edges: [{cursor, node: {...}}]``: the job is one level inside
            # each element, so ``hits.hits.*._source`` and ``edges.*.node`` resolve to a
            # dict per element rather than to a list. Measured on
            # ``www-api.ibm.com/search/api/v2``: 1,806 postings that no concrete path in
            # the payload can name.
            out.append(found)
    return out


# --------------------------------------------------------------------------
# per-op validators (the closed vocabulary)
# --------------------------------------------------------------------------

# How a POST body goes on the wire. ``json`` is the DEFAULT and the only value a
# pre-Stage-2 recipe can mean, so an absent key must keep meaning exactly what it
# meant before — every stored script keeps its current behaviour byte for byte.
#
# ``form`` exists because a board measured on 2026-08-30 accepts NOTHING else:
# metacareers.com's ``CareersJobSearchResultsV2DataQuery`` answers 200 with 876 job
# records to an ``application/x-www-form-urlencoded`` body and **400** to the same
# fields as JSON — from inside its own origin, where the request works at all. Both
# executors used to hard-code JSON, so the only way past it was to move the whole body
# into the query string, and a board needing a non-empty form body was unreachable.
BODY_ENCODINGS = ("json", "form")


def _v_fetch(step: dict[str, Any]) -> None:
    _reject_unknown_keys(
        step, {"method", "url", "headers", "body", "body_encoding"}, "fetch"
    )
    method = step.get("method", "GET")
    _require(method in ("GET", "POST"), f"fetch.method must be GET or POST, got {method!r}")
    _require_https(step, "url", "fetch")
    _require(isinstance(step.get("headers", {}), dict), "fetch.headers must be an object")
    _require(isinstance(step.get("body", {}), dict), "fetch.body must be an object")
    encoding = step.get("body_encoding", "json")
    _require(
        encoding in BODY_ENCODINGS,
        f"fetch.body_encoding must be one of {BODY_ENCODINGS}, got {encoding!r}",
    )
    if "body_encoding" in step:
        # A GET has no body to encode, so the key can only be a mislabel — and silently
        # ignoring it is how an author believes a request is form-encoded when it is not.
        _require(
            method == "POST",
            "fetch.body_encoding is only meaningful on a POST (a GET carries no body)",
        )
    if encoding == "form":
        # A form body is a FLAT list of name=value pairs by definition. A nested object
        # has no single spelling on the wire (PHP brackets? JSON-in-a-field? repeated
        # keys?), and — the half that actually bites — ``merge_body_params`` sets the
        # pagination cursor at whatever depth it finds the name, so a nested form body
        # would page correctly in the recipe and not at all on the wire. Refusing here
        # is cheaper than a sweep that reads page one N times.
        body = step.get("body") or {}
        assert isinstance(body, dict)  # narrow for mypy; checked above
        for name, value in body.items():
            _require(
                isinstance(value, (str, int, float)) and not isinstance(value, bool),
                f"fetch.body[{name!r}] is a {type(value).__name__}; a form-encoded body "
                "must be flat name=value pairs of strings or numbers",
            )


def _v_paginate_offset(step: dict[str, Any]) -> None:
    _reject_unknown_keys(step, {"param", "page_size", "max_pages", "window_cap"}, "paginate_offset")
    _require_str(step, "param", "paginate_offset")
    _require_pos_int(step, "page_size", "paginate_offset")
    _require_pos_int(step, "max_pages", "paginate_offset")
    if "window_cap" in step:
        _require_pos_int(step, "window_cap", "paginate_offset")


def _v_paginate_page(step: dict[str, Any]) -> None:
    _reject_unknown_keys(
        step, {"param", "page_size", "max_pages", "start_page", "window_cap"}, "paginate_page"
    )
    _require_str(step, "param", "paginate_page")
    _require_pos_int(step, "page_size", "paginate_page")
    _require_pos_int(step, "max_pages", "paginate_page")
    if "start_page" in step:
        _require(
            isinstance(step["start_page"], int) and not isinstance(step["start_page"], bool),
            "paginate_page.start_page must be an int",
        )
    if "window_cap" in step:
        _require_pos_int(step, "window_cap", "paginate_page")


def _v_paginate_facet(step: dict[str, Any]) -> None:
    _reject_unknown_keys(
        step,
        {"facet_param", "facet_values", "facet_values_path", "page_size",
         "max_pages_per_facet", "window_cap"},
        "paginate_facet",
    )
    _require_str(step, "facet_param", "paginate_facet")
    has_values = isinstance(step.get("facet_values"), list) and bool(step["facet_values"])
    has_path = isinstance(step.get("facet_values_path"), str) and bool(step.get("facet_values_path"))
    _require(
        has_values or has_path,
        "paginate_facet requires facet_values (non-empty list) or facet_values_path",
    )
    if has_values:
        _require(
            all(isinstance(v, str) and v for v in step["facet_values"]),
            "paginate_facet.facet_values must be non-empty strings",
        )
    _require_pos_int(step, "page_size", "paginate_facet")
    _require_pos_int(step, "max_pages_per_facet", "paginate_facet")
    if "window_cap" in step:
        _require_pos_int(step, "window_cap", "paginate_facet")


def _v_fields(fields: Any, where: str) -> None:
    _require(isinstance(fields, dict), f"{where}.fields must be an object")
    for required in ("id", "title", "url"):
        _require(
            isinstance(fields.get(required), str) and bool(fields[required]),
            f"{where}.fields.{required} is required (a non-empty dotted-path/template string)",
        )


def _require_records_path(step: dict[str, Any], where: str) -> None:
    """``records_path`` is a string, and its wildcard use is one this engine can run.

    Checked on WRITE and again on READ, like everything else here, because the wildcard
    is the one segment whose cost is not obvious from the string: a second ``*`` is a
    cross-product over a payload a stranger's board authored, and a TRAILING ``*`` names
    no key at all. Both are rejected where every other unrunnable recipe is rejected —
    loudly, before a nightly replay can discover it.
    """
    path = step.get("records_path")
    _require(
        isinstance(path, str),
        f"{where}.records_path is required (may be '' for a top-level array)",
    )
    assert isinstance(path, str)  # narrow for mypy
    segments = path.split(".")
    wildcards = segments.count(RECORDS_WILDCARD)
    _require(
        wildcards <= 1,
        f"{where}.records_path {path!r} carries {wildcards} {RECORDS_WILDCARD!r} "
        "segments; at most one is supported",
    )
    _require(
        not (wildcards and segments[-1] == RECORDS_WILDCARD),
        f"{where}.records_path {path!r} ends in {RECORDS_WILDCARD!r}, which names no "
        "records to collect",
    )


def _v_extract_json_path(step: dict[str, Any]) -> None:
    _reject_unknown_keys(step, {"records_path", "fields"}, "extract_json_path")
    _require_records_path(step, "extract_json_path")
    _v_fields(step.get("fields"), "extract_json_path")


# Where an embedded island's JSON lives inside the matched node(s).
#
# ``rsc_flight`` is the Next.js App-Router source and the third one because it is a
# different SHAPE, not a different selector: the page does not hold one JSON blob, it
# holds a React Flight STREAM split across dozens of ``self.__next_f.push([1,"…"])``
# calls that have to be concatenated and then framed by the stream's own row grammar
# (``<hex-id>:<payload>``, where a ``T<hexlen>,`` row is delimited by a BYTE length and
# may contain raw newlines). ``text`` reads ONE node and hands it to ``json.loads``,
# which on such a page parses nothing at all — measured on jobs.deel.com/job-boards/klarna,
# where the whole 81-job board sits at ``9.3.jobPostings`` inside that stream.
#
# The harder half of RSC is deliberately NOT here: rows that serialize React ELEMENT
# TREES (``["$","div",null,{children:…}]``) would need a walker, and Roblox — the board
# that would need one — publishes a static CloudFront ``jobs.json`` that is a better
# source anyway (PATH-TO-90-PERCENT.md §3). A records_path into an element tree simply
# fails to resolve, which is a loud FAILED run, not a wrong answer.
ISLAND_SOURCES = ("attribute", "text", "rsc_flight")


def _v_extract_embedded_island(step: dict[str, Any]) -> None:
    _reject_unknown_keys(
        step, {"selector", "source", "attribute", "records_path", "fields", "base_url"},
        "extract_embedded_island",
    )
    _require_str(step, "selector", "extract_embedded_island")
    _require_records_path(step, "extract_embedded_island")
    source = step.get("source", "attribute")
    _require(
        source in ISLAND_SOURCES,
        f"extract_embedded_island.source must be one of {ISLAND_SOURCES}",
    )
    if source == "attribute":
        _require_str(step, "attribute", "extract_embedded_island")
    _v_fields(step.get("fields"), "extract_embedded_island")


def _v_extract_css(step: dict[str, Any]) -> None:
    _reject_unknown_keys(step, {"record_selector", "field_selectors", "base_url"}, "extract_css")
    _require_str(step, "record_selector", "extract_css")
    fs = step.get("field_selectors")
    _require(isinstance(fs, dict), "extract_css.field_selectors must be an object")
    assert isinstance(fs, dict)  # narrow for mypy
    for required in ("id", "title", "url"):
        _require(
            isinstance(fs.get(required), str) and bool(fs[required]),
            f"extract_css.field_selectors.{required} is required",
        )


# The closed ``transform`` kind set. ``regex_capture`` is Stage 2's addition
# (PATH-TO-90-PERCENT.md §6): a board whose only readable source publishes URLs and no
# titles — Bloomberg's and Citadel's sitemaps publish ``<loc>`` and ``<lastmod>`` and
# nothing else — had ``title`` mapped to the job's own URL, and no primitive could turn
# ``…/JobDetail/Senior-Software-Engineer/12345`` into "Senior Software Engineer".
TRANSFORM_KINDS = ("template", "base_url_join", "regex_capture")

# A ``regex_capture`` reads one ALREADY-MAPPED canonical field, never an arbitrary path
# into the raw record. Shaping runs on ROWS (``_apply_shaping``), after ``map_records``
# has flattened them, so a raw-record path would silently render empty; naming the
# closed field set here makes that a write-time refusal instead.
CAPTURE_SOURCE_FIELDS = CANONICAL_REQUIRED_FIELDS + CANONICAL_OPTIONAL_FIELDS

# --------------------------------------------------------------------------
# THE PATTERN BOUND — why a stored regex is a restricted language, not a regex
# --------------------------------------------------------------------------
# The pattern lands in ``company_scripts.script`` JSONB, which is data that DRIFTS and
# is re-validated on every nightly READ. Python's ``re`` has no timeout and no step
# budget, so a pattern that backtracks catastrophically is a worker pinned for hours,
# per row, with no way to interrupt it. The answer that fits this module is the same one
# the op vocabulary already uses: admit a CLOSED, checkable subset rather than the whole
# language, and refuse everything else by name.
#
# The subset forbids exactly the shapes that make backtracking blow up:
#
# * a quantifier applied to a GROUP — ``(a+)+``, ``(a|a)*``, ``(a*)*``. Every classic
#   exponential form needs one, because the ambiguity has to be re-tried across a
#   quantified sub-expression;
# * backreferences and lookaround (``\1``, ``(?=``, ``(?<``), whose cost is not
#   expressible as a function of the input length at all;
# * an unbounded ``{n,}`` and any ``{n,m}`` past :data:`CAPTURE_PATTERN_MAX_REPEAT`;
# * more than :data:`CAPTURE_PATTERN_MAX_QUANTIFIERS` quantified atoms in total.
#
# WHAT THAT BUYS, STATED HONESTLY: it is a bound, not a proof of linearity. Adjacent
# quantified atoms over overlapping classes (``[^/]*[^/]*x``) still backtrack
# polynomially, so the residual worst case is O(n^q) with q <= 3 over a subject the
# runner caps at ``recipe_runner.CAPTURE_SUBJECT_MAX_CHARS`` — ~1.3e8 engine steps for a
# deliberately adversarial pattern, and linear for every realistic one. Reaching that
# requires the ability to write the recipe row; the exponential cliff, which does not,
# is closed.
CAPTURE_PATTERN_MAX_CHARS = 200
CAPTURE_PATTERN_MAX_QUANTIFIERS = 3
CAPTURE_PATTERN_MAX_REPEAT = 64

_REPEAT_SPEC_RE = re.compile(r"(\d+)(?:,(\d*))?$")


def validate_capture_pattern(pattern: str, where: str) -> None:
    """Raise unless ``pattern`` is in the bounded regex subset described above.

    Public because both the WRITE path (discovery's synthesis) and the READ path
    (``validate_recipe`` on a stored row) must apply the identical rule — a pattern that
    is admitted on one side and not the other is a recipe that stores and can never
    replay.
    """
    _require(
        len(pattern) <= CAPTURE_PATTERN_MAX_CHARS,
        f"{where}.pattern is {len(pattern)} chars; at most "
        f"{CAPTURE_PATTERN_MAX_CHARS} are allowed",
    )
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        raise RecipeError(f"{where}.pattern is not a valid regex: {exc}") from None
    _require(
        compiled.groups == 1,
        f"{where}.pattern must have EXACTLY one capture group (the derived value); "
        f"got {compiled.groups}",
    )

    quantifiers = 0
    i, n = 0, len(pattern)
    while i < n:
        ch = pattern[i]
        if ch == "\\":
            nxt = pattern[i + 1:i + 2]
            _require(
                not (nxt.isdigit() and nxt != "0"),
                f"{where}.pattern uses a backreference (\\{nxt}); its cost is not "
                "bounded by the input length",
            )
            i += 2
            continue
        if ch == "[":                       # a character class: skip it wholesale
            j = i + 1
            if pattern[j:j + 1] == "^":
                j += 1
            if pattern[j:j + 1] == "]":     # a literal ']' first in the class
                j += 1
            while j < n and pattern[j] != "]":
                j += 2 if pattern[j] == "\\" else 1
            _require(j < n, f"{where}.pattern has an unterminated character class")
            i = j + 1
            continue
        if ch == "(":
            if pattern.startswith("(?", i):
                _require(
                    pattern.startswith("(?:", i),
                    f"{where}.pattern uses a '(?…)' construct other than the "
                    "non-capturing '(?:' — lookaround, named groups, inline flags and "
                    "conditionals are all outside the bounded subset",
                )
                i += 3
            else:
                i += 1
            continue
        if ch == ")":
            _require(
                pattern[i + 1:i + 2] not in ("*", "+", "?", "{"),
                f"{where}.pattern applies a quantifier to a GROUP, which is the shape "
                "every catastrophic-backtracking pattern needs",
            )
            i += 1
            continue
        if ch in ("*", "+", "?"):
            quantifiers += 1
            i += 1
            if ch != "?" and pattern[i:i + 1] == "?":
                i += 1                      # the lazy modifier, not a second quantifier
            continue
        if ch == "{":
            close = pattern.find("}", i)
            _require(close != -1, f"{where}.pattern has an unterminated '{{'")
            spec = _REPEAT_SPEC_RE.fullmatch(pattern[i + 1:close])
            _require(
                spec is not None,
                f"{where}.pattern has a repetition '{pattern[i:close + 1]}' that is not "
                "{n} or {n,m}",
            )
            assert spec is not None  # narrow for mypy; _require already raised otherwise
            high = spec.group(2)
            _require(
                high != "",
                f"{where}.pattern uses an unbounded repetition "
                f"'{pattern[i:close + 1]}'; give it an upper bound",
            )
            ceiling = int(high) if high is not None else int(spec.group(1))
            _require(
                ceiling <= CAPTURE_PATTERN_MAX_REPEAT,
                f"{where}.pattern repeats up to {ceiling} times; the bound is "
                f"{CAPTURE_PATTERN_MAX_REPEAT}",
            )
            quantifiers += 1
            i = close + 1
            if pattern[i:i + 1] == "?":
                i += 1
            continue
        i += 1

    _require(
        quantifiers <= CAPTURE_PATTERN_MAX_QUANTIFIERS,
        f"{where}.pattern has {quantifiers} quantifiers; at most "
        f"{CAPTURE_PATTERN_MAX_QUANTIFIERS} are allowed (each one multiplies the "
        "backtracking the engine may do on a subject that does not match)",
    )


def _v_transform(step: dict[str, Any]) -> None:
    _reject_unknown_keys(
        step,
        {"field", "kind", "template", "base_url", "from", "pattern", "unslug"},
        "transform",
    )
    _require_str(step, "field", "transform")
    kind = step.get("kind")
    _require(kind in TRANSFORM_KINDS, f"transform.kind must be one of {TRANSFORM_KINDS}")
    if kind == "template":
        _require_str(step, "template", "transform")
    elif kind == "base_url_join":
        _require_str(step, "base_url", "transform")
    else:  # regex_capture
        _require_str(step, "from", "transform")
        _require(
            step["from"] in CAPTURE_SOURCE_FIELDS,
            f"transform.from must be one of {CAPTURE_SOURCE_FIELDS}, got "
            f"{step['from']!r} — shaping reads MAPPED rows, not raw records",
        )
        _require_str(step, "pattern", "transform")
        validate_capture_pattern(step["pattern"], "transform")
        if "unslug" in step:
            _require(
                isinstance(step["unslug"], bool),
                "transform.unslug must be true or false",
            )


# The closed mode set for ``parse_date``. ``epoch_s``/``epoch_ms`` were added by
# POSTED-DATE-PLAN.md §5/U6: a board that publishes unix time (Microsoft's
# ``postedTs: 1787617881``) had no mode that could read it, so discovery emitted no
# step at all and every one of its rows stored a NULL date. Widening this set is
# what lets ``synthesize_recipe`` emit one. Both are validated on WRITE and again on
# every nightly READ, so an older backend can never replay a recipe it cannot parse.
PARSE_DATE_MODES = ("strptime", "humanized", "iso", "epoch_s", "epoch_ms")


def _v_parse_date(step: dict[str, Any]) -> None:
    _reject_unknown_keys(step, {"field", "mode", "format"}, "parse_date")
    _require_str(step, "field", "parse_date")
    mode = step.get("mode")
    _require(
        mode in PARSE_DATE_MODES,
        f"parse_date.mode must be {'|'.join(PARSE_DATE_MODES)}",
    )
    if mode == "strptime":
        _require_str(step, "format", "parse_date")


def _v_lookup_join(step: dict[str, Any]) -> None:
    # Declared for completeness; unexercised until a real target needs it. The
    # validator accepts a well-formed shape but no in-scope Phase-3 script uses it,
    # so the runner leaves its execution path un-built (YAGNI, not gold-plated).
    _reject_unknown_keys(step, {"detail_fetch", "join_key", "fields"}, "lookup_join")
    df = step.get("detail_fetch")
    _require(isinstance(df, dict), "lookup_join.detail_fetch must be an object")
    assert isinstance(df, dict)  # narrow for mypy
    _require_str(df, "url_template", "lookup_join.detail_fetch")
    _require_str(step, "join_key", "lookup_join")
    _require(isinstance(step.get("fields"), dict), "lookup_join.fields must be an object")


def _v_dedupe_key(step: dict[str, Any]) -> None:
    _reject_unknown_keys(step, {"field"}, "dedupe_key")
    _require_str(step, "field", "dedupe_key")


def _v_assert_no_inband_error(step: dict[str, Any]) -> None:
    _reject_unknown_keys(step, {"error_keys"}, "assert_no_inband_error")
    ek = step.get("error_keys")
    _require(
        isinstance(ek, list) and bool(ek) and all(isinstance(k, str) and k for k in ek),
        "assert_no_inband_error.error_keys must be a non-empty list of strings",
    )


def _v_assert_pinned_operation(step: dict[str, Any]) -> None:
    _reject_unknown_keys(step, {"doc_id", "url_contains", "response_shape_path"}, "assert_pinned_operation")
    _require(
        any(k in step for k in ("doc_id", "url_contains", "response_shape_path")),
        "assert_pinned_operation needs at least one of doc_id/url_contains/response_shape_path",
    )
    for key in ("doc_id", "url_contains", "response_shape_path"):
        if key in step:
            _require_str(step, key, "assert_pinned_operation")


def _v_assert_cap_not_hit(step: dict[str, Any]) -> None:
    _reject_unknown_keys(step, {"window_cap"}, "assert_cap_not_hit")
    _require_pos_int(step, "window_cap", "assert_cap_not_hit")


def _v_assert_unique(step: dict[str, Any]) -> None:
    _reject_unknown_keys(step, {"field"}, "assert_unique")
    _require_str(step, "field", "assert_unique")


def _v_noparam_assert(step: dict[str, Any]) -> None:
    # assert_status / assert_page_advances / assert_unique_ids_vs_total /
    # assert_delta_vs_last_run — take no params.
    _reject_unknown_keys(step, set(), step["op"])


# The closed op vocabulary. Anything not a key here → RecipeError.
_OP_VALIDATORS: dict[str, Callable[[dict[str, Any]], None]] = {
    "fetch": _v_fetch,
    "paginate_offset": _v_paginate_offset,
    "paginate_page": _v_paginate_page,
    "paginate_facet": _v_paginate_facet,
    "extract_json_path": _v_extract_json_path,
    "extract_embedded_island": _v_extract_embedded_island,
    "extract_css": _v_extract_css,
    "transform": _v_transform,
    "parse_date": _v_parse_date,
    "lookup_join": _v_lookup_join,
    "dedupe_key": _v_dedupe_key,
    "assert_status": _v_noparam_assert,
    "assert_no_inband_error": _v_assert_no_inband_error,
    "assert_pinned_operation": _v_assert_pinned_operation,
    "assert_cap_not_hit": _v_assert_cap_not_hit,
    "assert_page_advances": _v_noparam_assert,
    "assert_unique_ids_vs_total": _v_noparam_assert,
    "assert_unique": _v_assert_unique,
    "assert_delta_vs_last_run": _v_noparam_assert,
}


def _validate_oracle(oracle: Any) -> None:
    _require(isinstance(oracle, dict), "oracle must be an object")
    assert isinstance(oracle, dict)  # narrow for mypy; _require already raised otherwise
    kind = oracle.get("kind")
    _require(kind in ORACLE_KINDS, f"oracle.kind must be one of {ORACLE_KINDS}, got {kind!r}")
    if kind == "facet_sum":
        _reject_unknown_keys(
            {**oracle, "op": None}, {"kind", "facet_path", "single_valued", "window_cap", "total_path"},
            "oracle",
        )
        _require_str(oracle, "facet_path", "oracle")
        _require(
            oracle.get("single_valued") is True,
            "oracle.single_valued must be true — a facet_sum oracle must partition (GM 1,042-vs-835)",
        )
        if "window_cap" in oracle:
            _require_pos_int(oracle, "window_cap", "oracle")
        if "total_path" in oracle:
            _require_str(oracle, "total_path", "oracle")
    elif kind == "header":
        _reject_unknown_keys({**oracle, "op": None}, {"kind", "header_name"}, "oracle")
        _require_str(oracle, "header_name", "oracle")
    elif kind == "sitemap":
        _reject_unknown_keys({**oracle, "op": None}, {"kind", "sitemap_url", "url_pattern"}, "oracle")
        _require_https(oracle, "sitemap_url", "oracle")
        _require_str(oracle, "url_pattern", "oracle")
    elif kind == "declared_probed":
        _reject_unknown_keys({**oracle, "op": None}, {"kind", "total_path"}, "oracle")
        _require_str(oracle, "total_path", "oracle")
    else:  # self_consistent / none — no params
        _reject_unknown_keys({**oracle, "op": None}, {"kind"}, "oracle")


def validate_recipe(
    script: dict[str, Any], *, transport: str | None = None, oracle_kind: str | None = None
) -> dict[str, Any]:
    """Validate a replay script, raising :class:`RecipeError` naming what is wrong.

    Runs on **write** and on **read**. When ``transport``/``oracle_kind`` (the
    ``company_scripts`` column values) are supplied, the script's own ``transport``
    and ``oracle.kind`` are asserted equal to them — the JSONB must not drift from
    the columns that route it.
    """
    _require(isinstance(script, dict), "script must be an object")
    _require(
        script.get("script_version") == RECIPE_VERSION,
        f"script_version must be {RECIPE_VERSION}, got {script.get('script_version')!r}",
    )

    _reject_unknown_keys(
        {**script, "op": None},
        {"script_version", "transport", "expected_min_jobs", "steps", "oracle", "base_url",
         "origin_url", "discovered_at", "discovered_by"},
        "script",
    )

    # PROVENANCE — optional, inert at replay, and DECLARED here rather than tolerated.
    # Discovery stamps which engine produced a recipe and when; that is what makes a
    # future "re-discover everything authored by engine X" sweep possible without a
    # migration. It must be part of the schema because ``_reject_unknown_keys`` is
    # deliberately strict: a stamp added after validation would pass on write and then
    # FAIL ``validate_recipe`` on every nightly READ — a stored recipe that can never
    # replay, which is the exact class of bug validate-on-read exists to surface.
    for provenance in ("discovered_at", "discovered_by"):
        if provenance in script:
            _require_str(script, provenance, "script")

    tr = script.get("transport")
    # Reject browser transports explicitly with a capability message BEFORE the
    # generic "must be one of" check, so the REFUSE reason names Phase 4.
    _require(
        tr not in _BROWSER_TRANSPORTS,
        f"transport {tr!r} is a browser transport (Phase 4 capability, not in Phase 3a) — "
        f"replay supports {TRANSPORTS}",
    )
    _require(tr in TRANSPORTS, f"transport must be one of {TRANSPORTS}, got {tr!r}")
    if transport is not None:
        _require(
            tr == transport,
            f"script.transport {tr!r} != company_scripts.transport {transport!r}",
        )

    # ``origin_url`` is REQUIRED iff browser_fetch and REJECTED otherwise. Both
    # directions matter: without it the executor has no page to fetch from, and an
    # origin_url on an http_json script means the author mislabelled the transport
    # — silently ignoring it would store a board that never reaches its origin.
    if tr == BROWSER_FETCH:
        _require(
            "origin_url" in script,
            "script.origin_url is required for transport 'browser_fetch' (the page to "
            "navigate to before the captured fetch runs on its origin)",
        )
        _require_https(script, "origin_url", "script")
    else:
        _require(
            "origin_url" not in script,
            f"script.origin_url is only valid for transport 'browser_fetch', not {tr!r}",
        )

    _require_pos_int(script, "expected_min_jobs", "script")

    steps = script.get("steps")
    _require(isinstance(steps, list) and bool(steps), "steps must be a non-empty list")
    assert isinstance(steps, list)  # narrow for mypy; _require already raised otherwise

    counts = {"fetch": 0, "pagination": 0, "extraction": 0}
    pagination_op: str | None = None
    pagination_step: dict[str, Any] | None = None
    extraction_op: str | None = None
    extraction_step: dict[str, Any] | None = None
    for i, step in enumerate(steps):
        _require(isinstance(step, dict), f"steps[{i}] must be an object")
        op = step.get("op")
        _require(isinstance(op, str) and bool(op), f"steps[{i}].op is required")
        # Reject cut/browser ops with a capability message (the REFUSE roadmap).
        _require(
            op not in _BROWSER_OPS,
            f"steps[{i}].op {op!r} is a browser/click capability (Phase 4, not in Phase 3a) — "
            f"replay is HTTP-only; discovery must REFUSE rather than emit it",
        )
        # Reject named-but-unimplemented ops with a capability message, so an
        # unsupported board REFUSES cleanly instead of crashing at replay time.
        _require(
            op not in _UNIMPLEMENTED_OPS,
            f"steps[{i}].op {op!r} is not implemented in the replay engine "
            f"({_UNIMPLEMENTED_OP_REASONS.get(op, 'no executor exists')}); "
            f"discovery must REFUSE rather than emit it",
        )
        validator = _OP_VALIDATORS.get(op)
        _require(validator is not None, f"steps[{i}].op {op!r} is not in the closed vocabulary")
        assert validator is not None  # for mypy — _require already raised otherwise
        validator(step)
        if op == "fetch":
            counts["fetch"] += 1
        elif op in _PAGINATION_OPS:
            counts["pagination"] += 1
            pagination_op = op
            pagination_step = step
        elif op in _EXTRACTION_OPS:
            counts["extraction"] += 1
            extraction_op = op
            extraction_step = step

    _require(counts["fetch"] == 1, f"exactly one 'fetch' step is required, got {counts['fetch']}")
    _require(steps[0].get("op") == "fetch", "the first step must be 'fetch'")
    _require(counts["pagination"] <= 1, "at most one pagination step is allowed")
    _require(counts["extraction"] == 1, f"exactly one extraction step is required, got {counts['extraction']}")

    if tr == HTTP_HTML:
        # THE LANDMINE, defused at write time and on every nightly read.
        #
        # ``recipe_runner._run_http_html`` does not paginate. It issues ONE request and
        # hardcodes ``pages_fetched=1, cap_hit=False, terminated_cleanly=True`` — i.e. it
        # reports a page-one-only read as a CLEAN, COMPLETE sweep. A stored html recipe
        # carrying a ``paginate_page`` step would validate, the runner would ignore the
        # step, the completeness gate would read "terminated cleanly, no cap" as
        # self-consistent and VERIFY it — and a VERIFIED harvest is allowed to close.
        # Every job past page one would be closed, every night, by a recipe that looks
        # like it paginates.
        #
        # Discovery emits no ``http_html`` today, so this is not live; that is exactly
        # why the rule belongs here rather than in a runbook. The refusal is the honest
        # answer either way — a board that needs paging and can only be read as HTML is a
        # board this tier cannot fully read, and saying so beats closing it.
        _require(
            counts["pagination"] == 0,
            f"transport {HTTP_HTML!r} does not paginate — the HTML executor issues one "
            f"request and reports a clean complete sweep, so a {pagination_op!r} step "
            f"would silently close every job past page one",
        )

    # ``rsc_flight`` reads a SERVED HTML DOCUMENT's ``<script>`` stream. Only
    # ``_run_http_html`` ever hands an extraction the raw markup: ``http_json`` feeds its
    # extraction a ``json.loads``-ed body and ``browser_fetch``'s child returns raw JSON
    # bodies, so on either of them this source names a document that never arrives.
    # Rejected on write and on every read rather than left to fail at 3am with a
    # selector error that names the wrong problem.
    if (
        extraction_step is not None
        and extraction_step.get("source") == "rsc_flight"
        and tr != HTTP_HTML
    ):
        raise RecipeError(
            f"extract_embedded_island.source 'rsc_flight' parses a served HTML "
            f"document's script stream and is only replayable on transport "
            f"{HTTP_HTML!r}, not {tr!r}"
        )

    if tr == BROWSER_FETCH:
        # The browser_fetch executor replays ONE captured JSON request per page and
        # hands the RAW body back to the agent-free parent, which parses it. HTML
        # extraction has no body to parse (the child never returns markup) and a
        # facet fan-out would multiply Chromium round-trips per run. Both are
        # rejected HERE — at write time and again on every read — so an
        # unreplayable script can never be stored, rather than crashing at 3am.
        _require(
            extraction_op == "extract_json_path",
            f"transport 'browser_fetch' requires the 'extract_json_path' extraction "
            f"(the subprocess returns raw JSON bodies), got {extraction_op!r}",
        )
        _require(
            pagination_op != "paginate_facet",
            "transport 'browser_fetch' does not support 'paginate_facet' — a facet "
            "fan-out would issue one in-browser sweep per facet value; use "
            "paginate_offset/paginate_page or no pagination",
        )
        # THE TIER'S PAGE CEILING, asserted on the RECIPE (see
        # :data:`BROWSER_FETCH_MAX_PAGES`). Rejecting here — on write AND on every
        # nightly read — rather than leaving it to the parent's ``min()`` clamp is what
        # stops an over-budget browser recipe from harvesting a TRUNCATED board that
        # still reports a finished sweep.
        if pagination_step is not None:
            _require(
                pagination_step["max_pages"] <= BROWSER_FETCH_MAX_PAGES,
                f"transport 'browser_fetch' allows at most {BROWSER_FETCH_MAX_PAGES} "
                f"pages per run, got max_pages={pagination_step['max_pages']} — each "
                f"page is a fresh in-browser fetch inside one 90s Chromium session",
            )

    _validate_oracle(script.get("oracle"))
    if oracle_kind is not None:
        actual = script["oracle"]["kind"]
        _require(
            actual == oracle_kind,
            f"script.oracle.kind {actual!r} != company_scripts.oracle_kind {oracle_kind!r}",
        )

    return script
