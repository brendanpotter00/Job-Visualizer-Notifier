"""DISCOVERY SIDE — pick the jobs request out of a capture, and map its fields ONCE.

Steps 3 and 4 of the capture flow, and the ONLY place an LLM is involved in the whole
custom-company feature. It is two halves on purpose, and the order is load-bearing:

* :func:`prefilter_candidates` — **pure code**. Keeps only JSON responses that actually
  contain an array of job-shaped objects, which drops the analytics/config/tracking
  noise a careers page fires (a real board sends dozens). This is what makes the LLM
  prompt small, cheap and reproducible; without it the model would be asked to reason
  over 40 bodies of which 38 are session pings.
* :func:`select_request` — **Claude Haiku 4.5, once, ever**, with structured output:
  which candidate is the jobs feed and how its record fields map to
  ``{id, title, url, location?, posted_at?, description?, department?}``. Runtime
  never calls this again; the answer is baked into the stored recipe.

The client/validation/degradation pattern is copied deliberately from
:mod:`api.services.llm_client` (same model constant family, ``max_retries=0`` — the
queue owns retries — an explicit timeout, a pydantic envelope, and a
``MissingAnthropicKeyError``-shaped graceful degradation when the key is unset, raised
BEFORE any client is constructed so no attempt is burned).

**THE MODEL'S ANSWER IS UNTRUSTED INPUT.** It is validated three times, and each layer
catches something the next cannot:

1. here, by pydantic + the deterministic re-checks below (a hallucinated index, a
   ``records_path`` that does not resolve in the body we actually captured, a field map
   whose id/title render empty on the real records);
2. by ``recipe_schema.validate_recipe`` when the synthesized recipe is assembled;
3. by the acceptance replay, which is the only layer that can prove the thing actually
   works from our production environment.

A malformed or hallucinated answer must REFUSE — never crash, never store.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qsl, urlsplit

from anthropic import APIError, AsyncAnthropic
from pydantic import BaseModel, ValidationError

from ...config import settings
from ..llm_client import extract_text_content
# ``_MULTISPACE_RE`` is imported rather than re-declared for the same reason
# ``render_row_field`` is: :func:`detect_posted_at_format` decides whether a strptime
# pattern fits, and the runner then applies it — so both must normalize the string
# identically or discovery stores a format that fails on every replay.
from ..recipe_runner import _MULTISPACE_RE, render_field, render_row_field
from ..recipe_schema import RECORDS_WILDCARD, RecipeError, dig_records

logger = logging.getLogger(__name__)

HAIKU_MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1024
LLM_TIMEOUT_SECONDS = 30.0

# How deep the record-array walk descends. Six levels covers every real board shape
# seen in the POCs (``jobs``, ``data.job_post_list``, ``results.hits.items``) without
# turning a pathological payload into a traversal cost.
_MAX_WALK_DEPTH = 6

# How many candidates the LLM is shown, and how much of each. Both are prompt-cost
# bounds AND blast-radius bounds: a board that fires 40 JSON XHRs must not be able to
# turn one discovery into a 200k-token call.
_MAX_CANDIDATES = 6
_SAMPLE_RECORDS = 2
# Per-RECORD, not per-blob. Truncating the JSON of several records together hands the
# model a body that stops mid-key, and a model shown a half-written field name invents a
# plausible whole one (measured on amazon.jobs: it answered ``position_title`` for a
# record whose key is ``title``, which the deterministic render check then refused).
_SAMPLE_RECORD_CHARS = 700
_MAX_KEYS_SHOWN = 40
# The URL is shown as path + a PARSED parameter list rather than one truncated string.
# Amazon's search.json carries a dozen ``facets[]`` params before ``offset``/
# ``result_limit``, so any character-truncated URL hides exactly the query parameters the
# pagination question is about — measured: the model correctly answered "no pagination"
# because the offset parameter was past the cut.
_URL_PROMPT_CHARS = 220
_MAX_PARAMS_SHOWN = 30
_PARAM_VALUE_CHARS = 60

# A record key counts as job-ish if it contains one of these. The bar for keeping an
# array is deliberately LOW (two hits): the acceptance replay is what proves a
# candidate, so over-keeping costs a few prompt tokens while under-keeping silently
# refuses a board we could have read.
_JOB_KEY_HINTS = (
    "title", "job", "position", "role", "req", "posting", "location", "department",
    "team", "city", "country", "state", "url", "slug", "apply", "category",
    "employment", "remote", "office", "posted", "date", "id",
)
_MIN_JOB_SCORE = 2


class RequestSelectionError(Exception):
    """The model's answer could not be believed. The caller REFUSES the board."""


class SelectorKeyMissingError(RequestSelectionError):
    """``ANTHROPIC_API_KEY`` is unset. Discovery degrades WITHOUT burning an attempt —
    the deployment is misconfigured, which is not the board's fault and must not be
    recorded as "this board is not trackable" any more loudly than it has to be."""


class NoJobsFeedError(RequestSelectionError):
    """The model looked at every candidate and NONE of them is a list of job postings.

    A distinct exception because it means the opposite of the others: re-asking is
    pointless (the answer will not change) and the caller must stop the ladder rather
    than spend another round. It exists at all because a schema that REQUIRES an index
    forces an answer — and a forced answer over a leftover facet/filter catalogue
    passes every downstream check, since the acceptance gate compares the replay
    against that SAME array. "None of these" has to be sayable.
    """


# --------------------------------------------------------------------------
# step 3 — the deterministic pre-filter
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Candidate:
    """One captured response that survived the pre-filter, plus what we found in it.

    ``payload`` is the PARSED body and is kept because two later steps need the real
    bytes and not a summary: the deterministic total-path search that picks the oracle,
    and the "matches the capture" assertion that compares the acceptance replay's ids
    against the ids this browser actually saw.
    """

    index: int
    url: str
    method: str
    request_headers: dict[str, str]
    post_data: str | None
    payload: Any
    records_path: str
    record_count: int
    job_score: int
    sample_keys: tuple[str, ...] = ()
    # WHERE THIS CAME FROM in the capture — the position of its response in
    # ``CaptureResult.responses``, which is the order the browser saw them in.
    #
    # Distinct from ``index``, and both are needed. ``index`` is reassigned after
    # ranking and again after every dropped candidate, because it means "the position in
    # the list the MODEL was shown" and is what ``chosen_request_index`` refers to.
    # ``source_index`` never moves, which is what lets the network log the user is
    # reading — capture order, never re-sorted — say which of those rows we picked.
    source_index: int = -1

    @property
    def records(self) -> list[Any]:
        """The record list this candidate was selected for. Never raises — the
        pre-filter already proved the path resolves to a list."""
        try:
            found = dig_records(self.payload, self.records_path)
        except RecipeError:  # pragma: no cover - the pre-filter guarantees otherwise
            return []
        return found if isinstance(found, list) else []


def _job_score(records: list[Any]) -> tuple[int, tuple[str, ...]]:
    """``(how job-ish these records look, their sampled key names)``."""
    keys: set[str] = set()
    for record in records[:5]:
        if isinstance(record, dict):
            keys |= {str(k).lower() for k in record}
    score = sum(1 for k in keys if any(hint in k for hint in _JOB_KEY_HINTS))
    return score, tuple(sorted(keys))


def _grouped_union_arrays(
    node: list[Any], path: str, out: list[tuple[str, int, int, tuple[str, ...]]]
) -> None:
    """Emit a ``<path>.*.<key>`` candidate for every array this list of groups SHARES.

    THE WHOLE-BOARD PATH on a grouped payload, and the reason it exists is a measured
    partial read: binance.com returns its entire board as 14 department groups
    (``[{title, postings: [...]}, ...]``). Every concrete path into that is one
    department — the ranking below picked ``4.postings``, 88 of 276 postings — while the
    other 188 sat in the same response we had already downloaded. ``*.postings`` is the
    union, and it is the path ``records_path`` should carry whenever the whole board is
    present (see :func:`recipe_schema.dig_records`).

    The union is only offered when it is STRICTLY bigger than the largest single group.
    A key only one group carries would otherwise be offered twice — once concrete, once
    wildcarded — for exactly the same records, and spending one of the model's six
    candidate slots on a duplicate is a real cost.

    Deliberately walks EVERY element, unlike the recursion below which samples five: the
    count is the claim being made ("this is the whole board"), and a count taken over
    five of fourteen groups would understate it by exactly the amount that matters. The
    job-shape SAMPLE stays at five records, because that is a shape question, not a
    size one.
    """
    if len(node) < 2:
        return
    shared: set[str] | None = None
    for element in node:
        if not isinstance(element, dict):
            return
        listy = {str(k) for k, v in element.items() if isinstance(v, list)}
        shared = listy if shared is None else (shared & listy)
        if not shared:
            return
    for key in sorted(shared or ()):
        sample: list[Any] = []
        total = 0
        largest = 0
        for element in node:
            inner = element[key]
            total += len(inner)
            largest = max(largest, len(inner))
            if len(sample) < 5:
                sample.extend(x for x in inner[:5] if isinstance(x, dict))
        if total <= largest:
            continue
        score, keys = _job_score(sample)
        if score >= _MIN_JOB_SCORE:
            union_path = f"{path}.{RECORDS_WILDCARD}.{key}" if path else f"{RECORDS_WILDCARD}.{key}"
            out.append((union_path, total, score, keys))


def _walk_record_arrays(
    node: Any, path: str, depth: int, out: list[tuple[str, int, int, tuple[str, ...]]]
) -> None:
    """Collect ``(path, count, job_score, sample_keys)`` for every job-shaped array."""
    if depth > _MAX_WALK_DEPTH:
        return
    if isinstance(node, list):
        if node and all(isinstance(x, dict) for x in node[:5]):
            score, keys = _job_score(node)
            if score >= _MIN_JOB_SCORE:
                out.append((path, len(node), score, keys))
            _grouped_union_arrays(node, path, out)
        for i, child in enumerate(node[:5]):
            _walk_record_arrays(child, f"{path}.{i}" if path else str(i), depth + 1, out)
    elif isinstance(node, dict):
        for key, child in node.items():
            _walk_record_arrays(child, f"{path}.{key}" if path else str(key), depth + 1, out)


def prefilter_candidates(responses: list[Any]) -> list[Candidate]:
    """Keep only the captured responses that contain an array of job-shaped objects.

    ``responses`` is a list of ``network_capture.CapturedResponse``. A response is
    dropped when it is not 2xx, does not parse as JSON, or contains no array whose
    objects carry at least :data:`_MIN_JOB_SCORE` job-ish keys — which is exactly the
    analytics/config/tracking traffic we never want the model reasoning about.

    Ranked most-job-shaped first (score, then record count) and capped at
    :data:`_MAX_CANDIDATES`, so the ranking — not the page's firing order — decides
    what the model sees and what the acceptance ladder tries first.
    """
    scored: list[Candidate] = []
    for source_index, response in enumerate(responses):
        if not (200 <= response.status < 300):
            continue
        try:
            # strict=False mirrors the replay tiers: some boards embed raw control
            # bytes in descriptions and json.loads is strict about them by default.
            payload = json.loads(response.body, strict=False)
        except Exception:  # noqa: BLE001 - a body that does not parse is simply not a candidate
            continue
        found: list[tuple[str, int, int, tuple[str, ...]]] = []
        _walk_record_arrays(payload, "", 0, found)
        if not found:
            continue
        # One candidate per RESPONSE: the best array in it. Two arrays from the same
        # body are the same request, so offering both would just spend the model's
        # attention on a choice the ``records_path`` already expresses.
        path, count, score, keys = max(found, key=lambda t: (t[2], t[1]))
        scored.append(Candidate(
            index=0,                    # assigned after ranking, so it is prompt-stable
            url=response.url,
            method=response.method,
            request_headers=dict(response.request_headers),
            post_data=response.post_data,
            payload=payload,
            records_path=path,
            record_count=count,
            job_score=score,
            sample_keys=keys,
            source_index=source_index,
        ))
    scored.sort(key=lambda c: (c.job_score, c.record_count), reverse=True)
    ranked = scored[:_MAX_CANDIDATES]
    # Re-index so ``chosen_request_index`` means "position in the list I was shown".
    return [replace(candidate, index=i) for i, candidate in enumerate(ranked)]


# --------------------------------------------------------------------------
# step 4 — the one LLM call
# --------------------------------------------------------------------------

# The CLOSED key set. Anthropic strict mode forbids dynamic keys, so ``field_map`` is
# an object over exactly these names and adding or removing one is a deliberate edit in
# FOUR places at once: here, :data:`_SELECTION_SCHEMA`, :data:`SYSTEM_PROMPT` (a key the
# model is never told about is a key it never returns), and the optional-field tuples in
# :func:`_to_selection` / :func:`_prune_non_scalar_optionals` (a key missing there is a
# mapping the model returned and we then dropped in silence). A mutation harness pins
# all four: removing either optional from any one of them fails a test.
#
# ``description`` (Δ2) is the whole reason custom-company jobs got zero enrichment rows:
# the claim in ``routers/internal_enrichment`` has no source filter at all — the ONLY
# thing excluding them is ``enrichment_monitor.DESCRIPTION_SQL IS NOT NULL``, which
# reads ``details->>'description'``, and a closed six-key object with no description key
# meant the model could not return one even while looking straight at 5.8 KB of it.
# Atlassian (249/249), amazon.jobs (10/10) and Jane Street (231/231) all ship the text
# in the list payload we already download nightly and throw away.
#
# ``department`` left with it and has come BACK, and the reason is worth recording
# because it is the same reason stated twice with opposite answers. Δ2 dropped it on the
# finding that nothing read it: the only reader was the classifier hint in
# ``internal_enrichment``'s ``/pending`` projection, a no-op when the key is absent. That
# was true when it was written and stopped being true hours later — the UI's Department
# filter turned out to have been silently dead (``/api/jobs`` never sent the key, so
# ``selectAvailableDepartments`` returned ``[]`` and the control hid itself), and the fix
# denormalized a ``job_listings.department`` column (migration ``c1539fa03b23``) fed from
# ``details['department']``. So the field now has a USER-FACING reader, and a recipe that
# does not map it writes NULL into that column on every upsert
# (``_UPSERT_ON_CONFLICT``: ``department = EXCLUDED.department``).
#
# The two do not compete for the ``details`` blob: ``fetch_custom_company`` bounds this
# one at ``_DEPARTMENT_MAX_BYTES`` precisely so a long department can never be the reason
# a description is shrunk. Description is the expensive field and wins any conflict.
class _FieldMap(BaseModel):
    id: str
    title: str
    url: str
    location: str | None = None
    posted_at: str | None = None
    description: str | None = None
    department: str | None = None


class _Pagination(BaseModel):
    style: str
    param: str
    page_size: int


class _SelectionEnvelope(BaseModel):
    # ``None`` is THE refusal branch — see :class:`NoJobsFeedError`. The rest of the
    # envelope is then ignored, so the model is told to send empty strings.
    chosen_request_index: int | None = None
    records_path: str
    field_map: _FieldMap
    pagination: _Pagination | None = None


@dataclass(frozen=True)
class PaginationHint:
    """How the model says this endpoint pages. ``style`` is ``offset`` or ``page``."""

    style: str
    param: str
    page_size: int


@dataclass(frozen=True)
class PostedDateFormat:
    """What the sampled ``posted_at`` values ACTUALLY look like on this board.

    Observed from the captured bytes, never asked of the model — the same rule the
    oracle, the headers and the in-band error keys already follow. ``mode`` is a
    ``parse_date`` mode (``recipe_schema.PARSE_DATE_MODES``); ``format`` is the
    ``strptime`` pattern and is set only for that mode.
    """

    mode: str
    format: str | None = None


@dataclass(frozen=True)
class RequestSelection:
    """The believed-and-re-checked answer: which candidate, and how to read it.

    Only ever built for a REAL pick — "none of these is a jobs feed" is
    :class:`NoJobsFeedError`, not a sentinel index, so no caller can forget to check.
    """

    chosen_request_index: int
    records_path: str
    field_map: dict[str, str]
    pagination: PaginationHint | None = None
    # POSTED-DATE-PLAN.md §5/U6. ``None`` means one of two DIFFERENT things and the
    # caller treats them the same way (emit no ``parse_date`` step): the board maps no
    # ``posted_at`` at all, or it maps one whose values are not a date we can read.
    # Both correctly end in a NULL ``posted_on`` — §3's rule is that a value we cannot
    # turn into a date is not a date, and the one thing we may never do is invent one.
    posted_at_format: PostedDateFormat | None = None


SYSTEM_PROMPT = (
    "You identify a job board's underlying jobs API from captured browser network "
    "traffic. You are shown a numbered list of JSON responses a careers page fetched, "
    "each with its method, URL, the dotted path to an array of records inside it, the "
    "record count, and one or two sample records.\n"
    "Choose the ONE response that is the board's list of JOB POSTINGS — not a facet/"
    "filter list, not a list of offices or departments, not search suggestions, not "
    "analytics. Prefer the response whose records are individual job postings with "
    "titles.\n"
    "If NONE of the responses is a list of job postings — they are all filter "
    "catalogues, office lists, suggestions or analytics — return "
    "chosen_request_index: null with empty strings for records_path and the field "
    "map, and null pagination. Say null rather than picking the closest thing: a "
    "wrong pick is stored and tracked as if it were the company's jobs.\n"
    "Then map that record shape to our canonical fields using DOTTED PATHS relative to "
    "ONE record. Use ONLY field names that appear in that response's 'record fields' "
    "list or inside its sample records — never a name you expect a job board to have. "
    "For a value nested inside an object, use the dotted path (e.g. 'city_info.en_name'). "
    "The fields are:\n"
    "- id: a stable per-job identifier that will not change between days (a job id or "
    "requisition id; never an array index or a position).\n"
    "- title: the job title.\n"
    "- url: the link to the job's own page. If the record holds only a path or an id, "
    "return a TEMPLATE with {dotted.path} placeholders, e.g. "
    "'https://example.com/jobs/{id}' or 'https://example.com{job_path}'.\n"
    "- location, posted_at, department: dotted paths when the record has them, "
    "otherwise null.\n"
    "- description: the field holding the job's own prose — whatever the record calls "
    "it (description, summary, overview, about, responsibilities, qualifications, "
    "jobDescription). It is normally the LONGEST string in the record and is often "
    "HTML. When several such fields exist, pick the one describing THIS ROLE — what "
    "the person will do and what they need — over one describing the COMPANY: an "
    "'overview' that opens with the employer's benefits or values reads the same on "
    "every posting and identifies nothing, while 'responsibilities' or 'qualifications' "
    "differ per job. Compare the sample records: prefer the field whose text CHANGES "
    "between them. Return null when the record carries none — a title, a category or a "
    "location is not a description, and pointing at one is worse than saying null.\n"
    "EVERY mapped path must resolve to a STRING or a NUMBER, never to an object or an "
    "array. If the value lives inside an object, point at the LEAF: 'city_info.en_name', "
    "not 'city_info'.\n"
    "Set records_path to the dotted path of the job array inside the chosen response "
    "(use the one you were shown unless it is wrong). A path containing '*' means "
    "'every element of the list here' — e.g. '*.postings' is the union of the postings "
    "arrays of ALL groups, while '4.postings' is only the fifth group's. When the "
    "response splits the board into groups (by department, category or office), ALWAYS "
    "choose the '*' path: the concrete one tracks a single department as if it were the "
    "whole company.\n"
    "Finally, if the request has an obvious paging parameter you can see in its URL or "
    "POST body (offset/from/start, or page/pageNumber), return pagination with style "
    "'offset' (the parameter counts RECORDS) or 'page' (it counts PAGES), the exact "
    "parameter name, and the page size the request used. Return null when you cannot "
    "see one — guessing a paging parameter is worse than not paging."
)

_SELECTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "chosen_request_index": {"type": ["integer", "null"]},
        "records_path": {"type": "string"},
        "field_map": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "id": {"type": "string"},
                "title": {"type": "string"},
                "url": {"type": "string"},
                "location": {"type": ["string", "null"]},
                "posted_at": {"type": ["string", "null"]},
                "description": {"type": ["string", "null"]},
                "department": {"type": ["string", "null"]},
            },
            "required": [
                "id", "title", "url", "location", "posted_at", "description", "department",
            ],
        },
        "pagination": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "properties": {
                "style": {"type": "string", "enum": ["offset", "page"]},
                "param": {"type": "string"},
                "page_size": {"type": "integer"},
            },
            "required": ["style", "param", "page_size"],
        },
    },
    "required": ["chosen_request_index", "records_path", "field_map", "pagination"],
}


def _sample_records(candidate: Candidate) -> list[Any]:
    return [r for r in candidate.records[:_SAMPLE_RECORDS] if isinstance(r, dict)]


def _record_keys(records: list[Any]) -> list[str]:
    """The record's field names in their ORIGINAL casing, in first-seen order.

    Shown to the model verbatim and separately from the sample JSON, because the sample
    is truncated and the key list is not: an explicit, complete, correctly-cased roster
    is what makes "use only these names" enforceable rather than a hope.
    """
    seen: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        for key in record:
            name = str(key)
            if name not in seen:
                seen.append(name)
    return seen[:_MAX_KEYS_SHOWN]


def _query_params(url: str) -> str:
    """The URL's query as ``k=v`` pairs — see :data:`_MAX_PARAMS_SHOWN` for why this is
    not just the tail of the URL string."""
    pairs = parse_qsl(urlsplit(url).query, keep_blank_values=True)
    return ", ".join(
        f"{k}={v[:_PARAM_VALUE_CHARS]}" for k, v in pairs[:_MAX_PARAMS_SHOWN]
    )


def _describe(candidate: Candidate) -> str:
    records = _sample_records(candidate)
    body = (candidate.post_data or "")[:_SAMPLE_RECORD_CHARS]
    parts = urlsplit(candidate.url)
    lines = [
        f"[{candidate.index}] {candidate.method} "
        f"{parts.scheme}://{parts.netloc}{parts.path}"[:_URL_PROMPT_CHARS],
        f"    records_path: {candidate.records_path or '(top level)'} "
        f"({candidate.record_count} records)",
        f"    record fields: {', '.join(_record_keys(records)) or '(none)'}",
    ]
    params = _query_params(candidate.url)
    if params:
        lines.append(f"    query params: {params}")
    if body:
        lines.append(f"    request body: {body}")
    for i, record in enumerate(records):
        # One line per record, each truncated on its OWN budget — see
        # ``_SAMPLE_RECORD_CHARS`` for the failure this shape prevents.
        lines.append(
            f"    sample record {i}: "
            f"{json.dumps(record, default=str)[:_SAMPLE_RECORD_CHARS]}"
        )
    return "\n".join(lines)


def build_message_params(candidates: list[Candidate]) -> dict[str, Any]:
    """The exact ``messages.create(...)`` kwargs for one selection.

    Single source of truth for the request shape (model, prompt, structured-outputs
    schema), for the same reason ``llm_client.build_message_params`` is: a test or a
    future eval that builds its own would drift from what production actually sends.
    """
    listing = "\n".join(_describe(c) for c in candidates)
    return {
        "model": HAIKU_MODEL,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM_PROMPT,
        "messages": [{
            "role": "user",
            "content": f"Captured JSON responses:\n\n{listing}\n\nChoose the jobs feed.",
        }],
        "output_config": {"format": {"type": "json_schema", "schema": _SELECTION_SCHEMA}},
    }


CreateMessage = Callable[[dict[str, Any]], Awaitable[Any]]


async def _default_create_message(params: dict[str, Any]) -> Any:
    """The real Haiku call. ``max_retries=0`` — Procrastinate owns retries, and a
    discovery run that burned three selection calls has spent three times the money for
    the same answer."""
    api_key = settings.anthropic_api_key      # read at call time, like llm_client
    if not api_key:
        raise SelectorKeyMissingError("anthropic_api_key is not configured")
    client = AsyncAnthropic(api_key=api_key, max_retries=0, timeout=LLM_TIMEOUT_SECONDS)
    return await client.messages.create(**params)


def _resolved_records(candidate: Candidate, records_path: str) -> list[Any]:
    """The records at ``records_path`` in the CAPTURED body, or raise.

    This is the check that catches a plausible-looking hallucination: a path the model
    invented resolves to nothing in the bytes we actually recorded, and finding that out
    here costs nothing, while finding it out at 3am costs a FAILED run every night.
    """
    try:
        found = dig_records(candidate.payload, records_path)
    except RecipeError as exc:
        raise RequestSelectionError(
            f"records_path {records_path!r} does not resolve in the captured response: {exc}"
        ) from exc
    if not isinstance(found, list) or not found:
        raise RequestSelectionError(
            f"records_path {records_path!r} did not resolve to a non-empty list"
        )
    return found


def _is_scalar(value: Any) -> bool:
    """A value that can be written into a job column as-is. Not a container."""
    return isinstance(value, (str, int, float)) and not isinstance(value, bool)


def _validate_field_map(records: list[Any], field_map: dict[str, str]) -> None:
    """Render the map against the REAL records; ``id`` and ``title`` must come out
    non-empty AND SCALAR for at least one of them.

    Two distinct failures, both fatal: ``map_records`` silently drops a row missing id or
    title, so a map that renders neither produces a zero-row replay — the failure that
    must never be mistaken for "no jobs today". And a path that lands on an OBJECT
    (``city_info`` rather than ``city_info.en_name``) renders as a Python repr, which as
    an id would make the dedupe/close key a dict spelling and as a title would put
    ``{'en_name': 'San Jose'}`` on every job card. Measured on lifeattiktok.com — the
    model does reach for the container when the leaf is one level down.
    """
    for record in records[:5]:
        rendered_id = render_field(record, field_map["id"])
        rendered_title = render_field(record, field_map["title"])
        if (
            rendered_id not in (None, "") and rendered_title not in (None, "")
            and _is_scalar(rendered_id) and _is_scalar(rendered_title)
        ):
            return
    raise RequestSelectionError(
        f"field_map {field_map!r} renders no usable scalar id/title on the captured records"
    )


def _validate_url_field(records: list[Any], spec: str) -> None:
    """Render ``url`` against the REAL records; it must come out link-shaped.

    ``url`` is the third REQUIRED field and, until this check existed, the only one
    never rendered — so a plausible-looking mapping was stored unchallenged and every
    "view job" link on the board came out dead. Two measured shapes on
    lifeattiktok.com: ``url='code'`` renders the bare requisition string ``A215432``
    (``map_records`` only resolves a value against ``base_url`` when it starts with
    ``/``, so it is stored verbatim), and a template pointed at the API host renders a
    well-formed URL that 404s.

    Only the FIRST of those is decidable without fetching, and that is what this
    enforces: at least one captured record must render an absolute ``http(s)://`` URL
    or a leading-slash path ``base_url`` can resolve. A board whose job links we
    cannot build is not trackable, so this REFUSES (like id/title) rather than
    pruning — and the caller's next round re-asks, which is where a better mapping
    comes from.
    """
    for record in records[:5]:
        rendered = render_field(record, spec)
        if isinstance(rendered, str) and rendered.startswith(("https://", "http://", "/")):
            return
    raise RequestSelectionError(
        f"field_map.url {spec!r} renders no usable link on the captured records "
        "(expected an absolute http(s) URL or a leading-slash path)"
    )


def _prune_non_scalar_optionals(
    records: list[Any], field_map: dict[str, str]
) -> dict[str, str]:
    """Drop any OPTIONAL mapping that renders a container rather than a scalar.

    Dropping beats keeping: an absent location is a job with no location, while a
    location of ``{'en_name': 'San Jose'}`` is a job whose location is a Python repr —
    which then flows into the location-normalization cascade and gets canonicalized as
    if it were a place. The required three are not pruned; they RAISE in
    :func:`_validate_field_map`, because a board we cannot identify or title is a board
    we must refuse rather than half-read.

    Renders through :func:`render_row_field`, NOT :func:`render_field`, so this sees the
    value the replay runner will actually store. That distinction is the whole fix for the
    over-prune this check used to commit: a ``locations: [...]`` list of plain strings is
    multi-value data the runner folds to ``"a; b"``, and pruning it deleted the only
    location mapping the board had — Atlassian and Microsoft each lost 100% of their
    locations that way, correctly mapped and then silently discarded.

    ``description`` is checked here for the same reason the others are — the model can
    point at a ``content: {html: …}`` wrapper as readily as at a ``city_info`` one — and
    survives for the same reason a plain string does: a long HTML string is a scalar,
    not a container. It is deliberately NOT in ``recipe_runner._MULTI_VALUE_FIELDS``, so
    a description mapped to a LIST is a mis-map one level too high and is dropped rather
    than joined into one blob of unrelated prose.

    ``department`` IS one of the runner's multi-value fields, so it behaves like
    ``location`` and not like ``description``: a list of plain strings is real data the
    runner folds to ``"a; b"`` and this keeps it, while a list of objects is still
    dropped. Rendering through :func:`render_row_field` is what makes that distinction
    free — the prune sees exactly the value the runner will store.
    """
    pruned = dict(field_map)
    for name in ("location", "posted_at", "description", "department"):
        spec = pruned.get(name)
        if spec is None or "{" in spec:      # a template always renders a string
            continue
        rendered = [render_row_field(r, name, spec) for r in records[:5] if isinstance(r, dict)]
        useful = [v for v in rendered if v not in (None, "")]
        if useful and not any(_is_scalar(v) for v in useful):
            logger.info(
                "dropping non-scalar field_map.%s=%r (renders %r)", name, spec, useful[0]
            )
            del pruned[name]
    return pruned


# --------------------------------------------------------------------------
# what shape is this board's posting date? (POSTED-DATE-PLAN.md §5/U6)
# --------------------------------------------------------------------------

# Absolute date spellings we will commit to, and the reason the list is this short.
#
# Every entry carries a MONTH NAME, which is what makes it unambiguous. The formats
# deliberately absent are the all-numeric ones — ``%m/%d/%Y`` and ``%d/%m/%Y`` are
# indistinguishable for any day ≤ 12, so guessing between them silently mis-dates
# roughly 40% of a board's rows by up to eleven months. A wrong date in the sort key
# is worse than no date: NULL falls back to first sight and is visibly a fallback,
# while "2026-03-07" that should be "2026-07-03" is confidently wrong forever.
# ``%Y/%m/%d`` and ``%Y-%m-%d`` are year-first and therefore safe, but the latter is
# already ISO and never reaches here.
_STRPTIME_CANDIDATES: tuple[str, ...] = (
    "%B %d, %Y",     # "August 26, 2026"  — amazon.jobs
    "%b %d, %Y",     # "Aug 26, 2026"
    "%B %d %Y",      # "August 26 2026"
    "%b %d %Y",      # "Aug 26 2026"
    "%d %B %Y",      # "26 August 2026"
    "%d %b %Y",      # "26 Aug 2026"
    "%Y/%m/%d",      # "2026/08/26"       — year-first, unambiguous
)

# Epoch plausibility. A jobs feed carries plenty of large integers that are NOT
# timestamps — Microsoft's ``atsJobId: 200050821`` is one — and reading an id as unix
# time yields a confident 1976 date. Requiring the result to land in a window a job
# posting could actually occupy is what separates the two. Deliberately generous on
# both sides: the sanity WINDOW is the leaf task's job (``_validated_posted_on``), and
# this only has to answer "is this field a timestamp at all".
_EPOCH_PLAUSIBLE_MIN_YEAR = 2000
_EPOCH_PLAUSIBLE_MAX_YEAR = 2100

# Above this, a numeric timestamp is milliseconds — the repo's one rule for this
# (``recipe_runner._EPOCH_MS_THRESHOLD``, ``eightfold_client._parse_eightfold_epoch``).
_EPOCH_MS_THRESHOLD = 1e11

# The cheap SHAPE gate only. It says "this opens with a YYYY-MM-DD", which is not the
# same claim as "this is a date" — see ``_is_iso_datetime``, which is what decides.
_ISO_SHAPE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]|$)")


def _is_iso_datetime(value: Any) -> bool:
    """``value`` is ISO-8601 IN ITS ENTIRETY — not merely one with an ISO prefix.

    The distinction is load-bearing because of what ``iso`` MEANS downstream: it is the
    one classification that emits NO ``parse_date`` step (``discover``: the value is
    already a date, so nothing has to convert it). A value that merely STARTS with a
    date therefore skips every parser we have and is written through verbatim, where
    ``_validated_posted_on`` cannot read it and stores NULL.

    That is the exact failure the prefix-only match produced: ``"2026-08-26 (reposted)"``
    matched, the recipe got no ``parse_date`` step, every row on the board stored NULL,
    and NOTHING raised, logged or looked wrong — a board silently missing its posting
    dates while reporting a clean synthesis. Proving the whole value parses turns that
    into an ordinary "we cannot read this format" outcome, which is logged and which
    still leaves the board perfectly trackable.

    Total by contract, like everything else on this path: a non-string, an empty string
    or an unparseable one is ``False``, never an exception.
    """
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not _ISO_SHAPE_RE.match(text):
        return False
    # ``fromisoformat`` handles ``Z`` from 3.11, but not a lowercase ``z``; normalize
    # both so a board's casing cannot decide whether its dates are readable.
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return False
    return True


def _epoch_mode(value: Any) -> str | None:
    """``'epoch_s'`` / ``'epoch_ms'`` if ``value`` is a plausible unix timestamp."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        # A string is only an epoch if it is ALL DECIMAL digits. ``float()`` would
        # happily accept "2026" (a year), "1e9" and "nan", so the predicate is doing
        # real work — but ``isdigit()`` was the wrong one: it is True for characters
        # ``float()`` cannot read, superscripts among them. ``"²".isdigit()`` is True
        # and ``float("²")`` raises ``ValueError``, which would have escaped
        # ``detect_posted_at_format`` — a function whose docstring promises it never
        # raises, running inside discovery's synthesis step where an exception refuses
        # the whole board. ``isdecimal()`` is exactly the set ``float()`` accepts
        # (Arabic-Indic "٢" included, which parses to 2.0).
        if not text.isdecimal():
            return None
        numeric: float = float(text)
    elif isinstance(value, (int, float)):
        numeric = float(value)
    else:
        return None
    if numeric <= 0:
        return None
    mode = "epoch_ms" if numeric > _EPOCH_MS_THRESHOLD else "epoch_s"
    seconds = numeric / 1000.0 if mode == "epoch_ms" else numeric
    try:
        year = datetime.fromtimestamp(seconds, tz=timezone.utc).year
    except (OverflowError, OSError, ValueError):
        return None
    if not _EPOCH_PLAUSIBLE_MIN_YEAR <= year <= _EPOCH_PLAUSIBLE_MAX_YEAR:
        return None
    return mode


def detect_posted_at_format(
    records: list[Any], spec: str
) -> PostedDateFormat | None:
    """The observed shape of ``spec``'s values on the REAL captured records.

    Answers the one question ``synthesize_recipe`` needs: does this board's posting
    date already arrive as ISO-8601 (nothing to do), does it arrive as unix time or in
    a datable text format (emit a ``parse_date`` step), or is it something we cannot
    turn into a date (emit nothing, store NULL).

    **EVERY sampled value must agree.** A format that reads 3 of 5 rows is not this
    board's format — it is a coincidence, and committing to it writes a wrong date on
    the rows it happens to fit. Returning ``None`` there costs a NULL; guessing costs a
    wrong entry in the column the product sorts by.

    Returns ``None`` — never raises. This runs inside discovery's synthesis step,
    where an exception refuses a board outright; a board whose dates we cannot read is
    still a perfectly trackable board.
    """
    values = [
        v
        for v in (render_row_field(r, "posted_at", spec) for r in records[:20]
                  if isinstance(r, dict))
        if v is not None and v != ""
    ]
    if not values:
        return None

    if all(_is_iso_datetime(v) for v in values):
        return PostedDateFormat(mode="iso")

    # Something that LOOKS like a date and is not one is the case worth saying out loud.
    # Everything else here degrades to "unreadable format, store NULL", which is a normal
    # outcome; this one used to be classified ``iso``, storing NULL with no signal at all.
    decorated = next(
        (
            v
            for v in values
            if isinstance(v, str)
            and _ISO_SHAPE_RE.match(v.strip())
            and not _is_iso_datetime(v)
        ),
        None,
    )
    if decorated is not None:
        logger.warning(
            "posted_at=%r opens with an ISO date but is not one (%r) — NOT classifying "
            "it as ISO: that would emit no parse_date step and store NULL for every row "
            "with nothing in the logs. Falling through to the remaining formats",
            spec, decorated,
        )

    epoch_modes = {_epoch_mode(v) for v in values}
    if len(epoch_modes) == 1:
        only = epoch_modes.pop()
        if only is not None:
            return PostedDateFormat(mode=only)

    texts = [v.strip() for v in values if isinstance(v, str) and v.strip()]
    if len(texts) == len(values):
        for fmt in _STRPTIME_CANDIDATES:
            if all(_parses_with(t, fmt) for t in texts):
                return PostedDateFormat(mode="strptime", format=fmt)

    logger.info(
        "posted_at=%r renders values we cannot read as a date (%r); storing no "
        "parse_date step — the column stays NULL rather than invented",
        spec, values[0],
    )
    return None


def _parses_with(text: str, fmt: str) -> bool:
    try:
        datetime.strptime(_MULTISPACE_RE.sub(" ", text), fmt)
    except (ValueError, TypeError):
        return False
    return True


def _to_selection(envelope: _SelectionEnvelope, candidates: list[Candidate]) -> RequestSelection:
    index = envelope.chosen_request_index
    if index is None:
        raise NoJobsFeedError(
            f"none of the {len(candidates)} captured request(s) is a list of job postings"
        )
    if not 0 <= index < len(candidates):
        raise RequestSelectionError(
            f"chosen_request_index {index} is not one of the {len(candidates)} "
            "candidates it was shown"
        )
    candidate = candidates[index]
    records = _resolved_records(candidate, envelope.records_path)

    field_map = {
        "id": envelope.field_map.id.strip(),
        "title": envelope.field_map.title.strip(),
        "url": envelope.field_map.url.strip(),
    }
    for name in ("location", "posted_at", "description", "department"):
        value = getattr(envelope.field_map, name)
        if isinstance(value, str) and value.strip():
            field_map[name] = value.strip()
    for required in ("id", "title", "url"):
        if not field_map[required]:
            raise RequestSelectionError(f"field_map.{required} is empty")
    _validate_field_map(records, field_map)
    _validate_url_field(records, field_map["url"])
    field_map = _prune_non_scalar_optionals(records, field_map)

    pagination: PaginationHint | None = None
    if envelope.pagination is not None:
        pg = envelope.pagination
        # A paging hint we cannot act on is DROPPED, not fatal: harvesting page 1 of a
        # board is a real (if partial) recipe, and the completeness gate will simply
        # never call such a run VERIFIED — so it can never close a job either.
        if pg.style in ("offset", "page") and pg.param.strip() and pg.page_size > 0:
            pagination = PaginationHint(
                style=pg.style, param=pg.param.strip(), page_size=pg.page_size
            )
        else:
            logger.info("selector returned an unusable pagination hint %r; ignoring", pg)

    # Observed AFTER the prune, so a posted_at that was just deleted for rendering a
    # container never gets a format (and never gets a step for a field the recipe no
    # longer maps).
    posted_at_spec = field_map.get("posted_at")
    posted_at_format = (
        detect_posted_at_format(records, posted_at_spec) if posted_at_spec else None
    )

    return RequestSelection(
        chosen_request_index=index,
        records_path=envelope.records_path,
        field_map=field_map,
        pagination=pagination,
        posted_at_format=posted_at_format,
    )


async def select_request(
    candidates: list[Candidate],
    *,
    create_message: CreateMessage | None = None,
) -> RequestSelection:
    """Ask Haiku 4.5 which candidate is the jobs feed and how to read its records.

    Raises :class:`SelectorKeyMissingError` when no API key is configured (degrade, do
    not retry), :class:`NoJobsFeedError` when the model says none of the candidates is
    a jobs feed (stop, do not re-ask) and :class:`RequestSelectionError` for every
    other unbelievable answer or a failed call (re-ask). ``create_message`` is the
    injectable seam: the unit tests run at $0 against a canned response object.
    """
    if not candidates:
        raise RequestSelectionError("no job-shaped JSON responses were captured")

    try:
        response = await (create_message or _default_create_message)(
            build_message_params(candidates)
        )
    except APIError as exc:
        # A 529/overload/connection blip is not an unbelievable ANSWER, but the caller
        # must treat it the same way — as a failed ROUND it can re-ask, not as an
        # escaping exception. Uncaught, it lands in ``discover``'s last-resort handler
        # and permanently refuses a trackable board on a transient LLM outage.
        # ``max_retries=0`` above is why this surfaces at all: the queue owns retries.
        # Deliberately narrow: ``SelectorKeyMissingError`` is not an ``APIError``, so
        # the "degrade without burning an attempt" path still passes straight through.
        raise RequestSelectionError(f"the selector call failed: {exc!r}") from exc
    text = extract_text_content(response)
    if not text:
        raise RequestSelectionError(
            "the selector returned no text content "
            f"(stop_reason={getattr(response, 'stop_reason', None)!r})"
        )
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RequestSelectionError(f"the selector returned non-JSON text: {exc}") from exc
    try:
        envelope = _SelectionEnvelope.model_validate(raw)
    except ValidationError as exc:
        raise RequestSelectionError(
            f"the selector's answer failed schema validation: {exc}"
        ) from exc
    return _to_selection(envelope, candidates)
