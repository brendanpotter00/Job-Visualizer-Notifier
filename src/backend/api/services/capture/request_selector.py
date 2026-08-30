"""DISCOVERY SIDE — pick the jobs request out of a capture, and map its fields ONCE.

Steps 3 and 4 of the capture flow, and the ONLY place an LLM is involved in the whole
custom-company feature. It is two halves on purpose, and the order is load-bearing:

* :func:`prefilter_candidates` — **pure code**. Keeps only JSON responses that actually
  contain an array of job-shaped objects, which drops the analytics/config/tracking
  noise a careers page fires (a real board sends dozens). This is what makes the LLM
  prompt small, cheap and reproducible; without it the model would be asked to reason
  over 40 bodies of which 38 are session pings.
* :func:`select_candidates` — **Claude Haiku 4.5, once per surviving candidate, in
  parallel**, with structured output: is THIS array a list of job postings, and how do
  its record fields map to ``{id, title, url, location?, posted_at?, description?}``.
  One array per call is what makes "no" cheap — it costs that array and not the board —
  and the crowding-out it fixes happened WITHIN one source, so fanning out per source
  kind would have changed nothing. Runtime never calls any of this again; the answer is
  baked into the stored recipe, and which of several yeses gets stored is decided on
  MEASUREMENTS by ``discover._rank_answers``, never on the model's own ranking.

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

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qsl, urljoin, urlsplit

from anthropic import APIError, AsyncAnthropic
from pydantic import BaseModel, ValidationError

from ...config import settings
from ..llm_client import extract_text_content
# ``_MULTISPACE_RE`` is imported rather than re-declared for the same reason
# ``render_row_field`` is: :func:`detect_posted_at_format` decides whether a strptime
# pattern fits, and the runner then applies it — so both must normalize the string
# identically or discovery stores a format that fails on every replay.
#
# ``_TEMPLATE_RE`` for the same reason once removed: :func:`repair_url_template` reads a
# url spec's placeholders and rewrites them, and ``render_field`` is what SUBSTITUTES
# them. Two spellings of "what is a placeholder" would let the repair rewrite something
# the runner never fills in, which renders a literal ``{...}`` into every job link.
#
# ``_regex_capture_value`` closes the same seam for :func:`derive_title_from_url`: it
# PROVES a slug pattern against the captured records, and the runner is what applies it
# nightly. Re-implementing the match/unslug/degrade-to-absent rule here would let a
# pattern be proven under one meaning and replayed under another.
from ..recipe_runner import (
    _MULTISPACE_RE,
    _TEMPLATE_RE,
    _regex_capture_value,
    render_field,
    render_row_field,
)
from ..recipe_schema import (
    RECORDS_WILDCARD,
    RecipeError,
    dig_records,
    validate_capture_pattern,
)

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
class HtmlSource:
    """This candidate's records came out of a DOCUMENT, not out of an XHR.

    It is the whole of what makes a source HONEST: a source with no replay transport can
    never become a stored recipe, whatever anything says about it. Carrying the
    extraction shape ON the candidate is how synthesis knows to emit ``http_html`` with
    an ``extract_embedded_island`` / ``extract_css`` step instead of ``http_json`` with
    an ``extract_json_path`` — two replay paths that have been implemented since Phase 3a
    and that discovery has never emitted.

    ``document_url`` is the one URL the nightly replay fetches. There is deliberately no
    field for a paging parameter: ``validate_recipe`` forbids any pagination step on
    ``http_html`` (``_run_http_html`` issues ONE request and reports a clean complete
    sweep, so a paginating html recipe would close every job past page one), which makes
    every candidate of this kind a single-page read by construction.
    """

    document_url: str
    op: str                                   # extract_embedded_island | extract_css
    selector: str                             # island: the <script>; css: the record
    source: str = "text"                      # island only
    attribute: str = ""                       # island only
    field_selectors: dict[str, str] | None = None   # css only


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
    # ``None`` for the XHR/fetch source this class was written for. Set for a candidate
    # that came out of a DOCUMENT — see :class:`HtmlSource`.
    html: HtmlSource | None = None

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


def _unwrapped_element_arrays(
    node: list[Any], path: str, out: list[tuple[str, int, int, tuple[str, ...]]]
) -> None:
    """Emit ``<path>.*.<key>`` when every element WRAPS its record one level down.

    The per-element analogue of :func:`_grouped_union_arrays`, and the same kind of
    blind spot: that one could not see a record array split ACROSS siblings, this one
    could not see a record nested INSIDE each element.

    Measured on ``www-api.ibm.com/search/api/v2`` (2026-08-30, 23,990 B): an
    Elasticsearch response, ``hits.total.value = 1806``, records at
    ``hits.hits[]._source``. The elements of ``hits.hits`` carry
    ``['_index','_id','_score','_source','sort']`` — job score **1**, under
    :data:`_MIN_JOB_SCORE` — while the job objects one level down in ``_source`` score
    **3**. The walk returned NOTHING, ``prefilter_candidates`` dropped the response with
    the tracking pings, and the user was told none of the 37 requests the page made is a
    list of job postings. This is every Elasticsearch board and every Relay/GraphQL
    ``edges[].node`` board, not one employer.

    THE RULE IS "EXACTLY ONE DICT-VALUED KEY, SHARED BY EVERY ELEMENT". Two of them is
    not a wrapper — it is a record with two nested objects, and unwrapping it would pick
    one of them arbitrarily. One is unambiguous, and it is what both real shapes look
    like (``_source`` beside four scalars; ``node`` beside ``cursor``).

    Called ONLY from the branch where the element array itself did not qualify: a board
    whose elements are already job-shaped needs no unwrapping, and offering both paths
    for the same records would spend one of the model's six candidate slots on a
    duplicate.

    ...and TWO ELEMENTS MINIMUM, the same floor :func:`_grouped_union_arrays` keeps, for
    a measured reason. In a one-element array a wrapper and a record are indistinguishable
    — every record "has exactly one dict-valued key" if you only look at one of them. On
    the live IBM capture that admitted an Adobe analytics blob
    (``handle.2.payload.0.items.*.meta``, ONE element, job score 8) which then outranked
    the 30-record jobs feed it was supposed to be helping find. With the floor, the jobs
    feed ranks first.
    """
    if len(node) < 2:
        return
    shared: set[str] | None = None
    for element in node:
        if not isinstance(element, dict):
            return
        dicty = {str(k) for k, v in element.items() if isinstance(v, dict)}
        shared = dicty if shared is None else (shared & dicty)
        if not shared:
            return
    if shared is None or len(shared) != 1:
        return
    (key,) = shared
    sample = [element[key] for element in node[:5]]
    score, keys = _job_score(sample)
    if score < _MIN_JOB_SCORE:
        return
    unwrapped = f"{path}.{RECORDS_WILDCARD}.{key}" if path else f"{RECORDS_WILDCARD}.{key}"
    out.append((unwrapped, len(node), score, keys))


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
            else:
                # ...and if the ELEMENTS are not job-shaped, the records may still be
                # one level inside each of them. See :func:`_unwrapped_element_arrays`.
                _unwrapped_element_arrays(node, path, out)
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
# ``department`` was in this set twice and is gone for good: the Department filter it fed
# was removed from the product (the option counts were ~1 job per option — Stripe 46 jobs
# / 39 departments, Anduril 377 / 195 — a list, not a filter), and with the filter gone
# the key had no reader at all. A stored recipe that still maps it keeps replaying: the
# read-path ``validate_recipe`` deliberately does not constrain the key set.
class _FieldMap(BaseModel):
    id: str
    title: str
    url: str
    location: str | None = None
    posted_at: str | None = None
    description: str | None = None


class _Pagination(BaseModel):
    style: str
    param: str
    page_size: int


class _SelectionEnvelope(BaseModel):
    # ``False`` is THE refusal branch, and it is now per-ARRAY rather than per-page —
    # see :func:`select_candidates`. The rest of the envelope is then ignored, so the
    # model is told to send empty strings.
    is_jobs_feed: bool = False
    confidence: str = "low"
    records_path: str = ""
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
class TitleFromUrl:
    """Derive ``title`` from the job's own URL slug — the ``transform`` step's payload.

    Built ONLY by :func:`derive_title_from_url`, which measures it against the captured
    records; the model never writes the pattern. That split is the same one the oracle,
    the headers and the in-band error keys already follow, and it is what makes the
    bounded-regex rule in ``recipe_schema.validate_capture_pattern`` a defence against
    JSONB drift rather than the only thing standing between us and a model's regex.
    """

    pattern: str
    unslug: bool = True


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
    # WHAT THE FIELD-QUALITY PRUNE THREW AWAY, in words, so a retry can say so. A drop is
    # a degrade and never causes a round of its own — but when a round happens for some
    # OTHER reason, telling the model "location rendered nothing on all 20 records" is
    # free and is the only way it can map the field differently. Empty on the happy path.
    field_notes: tuple[str, ...] = ()
    # SET when the mapped ``title`` renders a URL on the captured records — the
    # "title is the URL" defect (PATH-TO-90-PERCENT.md §3). ``None`` on every board
    # whose title is a title, which is all of them today.
    title_from_url: TitleFromUrl | None = None


SYSTEM_PROMPT = (
    "You are shown ONE array of records that a careers page's own code produced — "
    "either from a network response it fetched, or from JSON embedded in its HTML — "
    "with its method, URL or page selector, the dotted path to the array, the record "
    "count, the record's field names, and one or two sample records.\n"
    "ANSWER ONE QUESTION: is this a list of JOB POSTINGS?\n"
    "Set is_jobs_feed false for anything else — a facet or filter catalogue, a list of "
    "offices, departments or categories, search suggestions, analytics, a chat "
    "transcript, a navigation menu. Saying false is cheap and correct: it costs this "
    "one array and nothing else, and other arrays from the same page are being asked "
    "about separately. A wrong true is STORED and tracked as if it were the company's "
    "jobs. When you answer false, return empty strings for records_path and the field "
    "map, and null pagination.\n"
    "If it IS a jobs feed, map that record shape to our canonical fields using DOTTED "
    "PATHS relative to "
    "ONE record. Use ONLY field names that appear in that response's 'record fields' "
    "list or inside its sample records — never a name you expect a job board to have. "
    "For a value nested inside an object, use the dotted path (e.g. 'city_info.en_name'). "
    "The fields are:\n"
    "- id: a stable per-job identifier that will not change between days (a job id or "
    "requisition id; never an array index or a position).\n"
    "- title: the job title. If — and ONLY if — the record carries no title field at "
    "all but its link or path holds a readable slug "
    "('/JobDetail/Senior-Software-Engineer/21653', "
    "'/careers/details/commodities-portfolio-manager/'), map title to that same "
    "link/path field: we derive the title from the slug afterwards, deterministically. "
    "Never do this when a real title field exists, and never point title at an id, a "
    "category or a location.\n"
    "- url: the link to the job's own page. If the record holds only a path or an id, "
    "return a TEMPLATE with {dotted.path} placeholders, e.g. "
    "'https://example.com/jobs/{id}' or 'https://example.com{job_path}'. When a record "
    "carries SEVERAL ids, use the one the site's own links are built from — usually the "
    "short numeric one (an 'externalId'/'sourceId'/'jobNumber'), not a long compound or "
    "UUID id. A link that is well-formed but points at the wrong id looks correct here "
    "and 404s for every user.\n"
    "- location, posted_at: dotted paths when the record has them, "
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
    "Set records_path to the dotted path of the job array (use the one you were shown "
    "unless it is wrong). A path containing '*' means 'every element of the list here' "
    "— '*.postings' is the union of the postings arrays of ALL groups, while "
    "'4.postings' is only the fifth group's — so leave a '*' path exactly as you were "
    "shown it.\n"
    "If the request has an obvious paging parameter you can see in its URL or "
    "POST body (offset/from/start, or page/pageNumber), return pagination with style "
    "'offset' (the parameter counts RECORDS) or 'page' (it counts PAGES), the exact "
    "parameter name, and the page size the request used. Return null when you cannot "
    "see one — guessing a paging parameter is worse than not paging.\n"
    "Finally set confidence: 'high' when these records are unmistakably individual job "
    "postings, 'low' when you are answering true but could be wrong. Confidence is only "
    "ever used to break a tie between arrays that every measurement rates equally."
)

_SELECTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "is_jobs_feed": {"type": "boolean"},
        "confidence": {"type": "string", "enum": ["high", "low"]},
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
            },
            "required": [
                "id", "title", "url", "location", "posted_at", "description",
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
    "required": [
        "is_jobs_feed", "confidence", "records_path", "field_map", "pagination",
    ],
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
    origin = (
        # A document candidate has no method worth naming and no query to reason about;
        # what identifies it is the selector its records were extracted with.
        f"[{candidate.index}] {candidate.html.op} {candidate.html.selector} in "
        f"{parts.scheme}://{parts.netloc}{parts.path}"
        if candidate.html is not None else
        f"[{candidate.index}] {candidate.method} "
        f"{parts.scheme}://{parts.netloc}{parts.path}"
    )
    lines = [
        origin[:_URL_PROMPT_CHARS],
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


# How much of the previous round's evidence rides in the prompt. A refusal detail is a
# sentence; a stack of them from a board that failed several ways is not, and the point
# of feedback is that the model READS it.
_FEEDBACK_CHARS = 1_200


def build_message_params(
    candidate: Candidate, *, feedback: str | None = None
) -> dict[str, Any]:
    """The exact ``messages.create(...)`` kwargs for ONE candidate.

    ONE ARRAY PER CALL, and that is the whole of the fan-out. The old shape rendered
    every candidate into one prompt and asked the model to RANK and MAP in a single
    answer, so a wrong-but-plausible array could crowd out a right one — and the
    crowding-out that actually happened was WITHIN one source (a chatbot response and a
    real jobs response are both XHR JSON), which is why fanning out per source KIND
    would have changed nothing. Per candidate, the question is strictly simpler, the
    context is a tenth the size, and "no" costs one array instead of the board.

    Single source of truth for the request shape (model, prompt, structured-outputs
    schema), for the same reason ``llm_client.build_message_params`` is: a test or a
    future eval that builds its own would drift from what production actually sends.

    ``feedback`` is WHAT WE MEASURED ABOUT THE LAST ANSWER — a job link that 404'd on two
    real jobs, a field that rendered nothing on every record, an acceptance replay that
    would not run. Until it existed a second round was a blind re-roll of the same
    question over the same bytes, which is the least likely way to get a different
    answer; and on a board with only ONE candidate feed there was no second round at all,
    because the loop dropped the failed candidate and found nothing left to ask about.
    """
    content = (
        f"One captured array:\n\n{_describe(candidate)}\n\n"
        "Is this a list of job postings?"
    )
    if feedback:
        content += (
            "\n\nYour previous answer was REJECTED. What we CHECKED against the real "
            "board, and what we found:\n"
            f"{feedback[:_FEEDBACK_CHARS]}\n"
            "Answer again over the same records. Change what the evidence says is "
            "wrong; leave the rest alone. Every required field is still required — an "
            "empty string is not a correction."
        )
    return {
        "model": HAIKU_MODEL,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": content}],
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


# --------------------------------------------------------------------------
# the url TEMPLATE repair (a well-formed link that 404s)
# --------------------------------------------------------------------------

# How many of the sampled records a replacement field must be PROVEN on. Three is a
# coincidence bar, not a confidence one: one or two matches is what an unrelated
# numeric field can hit by accident against a page's worth of URL segments.
_URL_REPAIR_MIN_HITS = 3

# How many records the scoring reads, and how deep it looks for a replacement.
_URL_REPAIR_SAMPLE = 20
_URL_REPAIR_MAX_DEPTH = 3


def _same_board_host(netloc: str, board_host: str) -> bool:
    """``netloc`` is the board's own host or a subdomain of it. Not a substring test —
    ``higher.gs.com`` is a substring of ``api-higher.gs.com``, which is a different
    service whose paths carry no job ids."""
    host = (netloc.split("@")[-1].split(":")[0]).lower()
    board = board_host.lower()
    return bool(board) and (host == board or host.endswith("." + board))


def _board_url_segments(captured_urls: list[str], board_host: str) -> set[str]:
    """Path segments (and their pre-dot stems) of every captured URL on the board's
    own host. ``/_next/data/<build>/roles/181782.json`` contributes both
    ``181782.json`` and ``181782`` — a Next.js data route spells the id with a suffix."""
    segments: set[str] = set()
    for url in captured_urls:
        parts = urlsplit(url)
        if not _same_board_host(parts.netloc, board_host):
            continue
        for segment in parts.path.split("/"):
            if not segment:
                continue
            segments.add(segment)
            if "." in segment:
                segments.add(segment.rsplit(".", 1)[0])
    return segments


def _renders_id_token(records: list[Any], path: str) -> bool:
    """``path`` renders an OPAQUE TOKEN on every sampled record — never a path.

    THE GUARD THAT KEEPS MICROSOFT WORKING, and it was learned the expensive way: the
    first version of this repair scored placeholder fields against URL SEGMENTS, and
    ``https://apply.careers.microsoft.com{positionUrl}`` renders a whole path
    (``/careers/job/1970393556982379``) which can never equal one segment. It scored 0,
    ``id`` scored 8, and the rule would have rewritten every Microsoft link to
    ``https://apply.careers.microsoft.com1970393556982379`` — repairing Goldman by
    breaking a board that was already right.

    A value containing ``/`` is a path, so neither the template's own field nor any
    candidate replacement may contain one. The rule can then only ever swap one opaque
    id token for another.
    """
    rendered = [render_field(record, path) for record in records[:10]]
    values = [
        str(value) for value in rendered
        if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value)
    ]
    return bool(values) and all("/" not in value for value in values)


def _scalar_paths(record: Any, prefix: str = "", depth: int = 0) -> list[str]:
    """Every dotted path in one record whose leaf is a scalar, to a bounded depth."""
    out: list[str] = []
    if not isinstance(record, dict):
        return out
    for key, value in record.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if _is_scalar(value):
            out.append(path)
        elif isinstance(value, dict) and depth < _URL_REPAIR_MAX_DEPTH:
            out.extend(_scalar_paths(value, path, depth + 1))
    return out


def _segment_hits(records: list[Any], path: str, segments: set[str]) -> int:
    """How many sampled records render ``path`` as a segment of a captured board URL."""
    hits = 0
    for record in records:
        value = render_field(record, path)
        if (
            isinstance(value, (str, int)) and not isinstance(value, bool)
            and str(value) and str(value) in segments
        ):
            hits += 1
    return hits


# --------------------------------------------------------------------------
# published vs synthesised — WHO AUTHORED THIS PATH
# --------------------------------------------------------------------------
#
# THE ONE QUESTION THIS WHOLE FILE'S URL HANDLING TURNS ON, asked once and answered in
# one place. ``field_map["url"]`` comes back as one of two very different things:
#
#   PUBLISHED    a field the BOARD filled with a link — ``absolute_url``,
#                ``hostedUrl``, ``portalJobPost.portalUrl``, ``job_path`` — or a
#                template wrapped around one (``https://apply.careers.microsoft.com``
#                ``{positionUrl}``, where ``positionUrl`` is ``/careers/job/197…``).
#                The board is the authority. Nothing here may second-guess it.
#
#   SYNTHESISED  a path WE invented with an id pasted into it
#                (``https://www.janestreet.com/jobs/{id}``). Nobody has ever confirmed
#                it resolves, and three of the six template boards in the corpus were
#                measured dead (JOB-LINK-RULE.md).
#
# Measured 2026-08-29 over 19 real payloads: 13 of 19 boards publish a link field, 6
# force a template. The split is what makes the fix a rule and not a third patch.


def is_published_url_spec(records: list[Any], spec: str) -> bool:
    """``spec`` renders a path THE BOARD authored, not one we invented.

    Two shapes count, and both mean "the slashes came from the payload":

    * a plain field path whose value renders ``http(s)://…`` or ``/…``;
    * a template whose single placeholder renders a PATH rather than an opaque id —
      :func:`_renders_id_token` inverted. This is the Microsoft shape, and reusing that
      predicate is deliberate: there must be exactly ONE definition of "we made this
      path up", or the verification below and the repair above can disagree about
      Microsoft and one of them will break it.

    A template with two or more placeholders, or one whose placeholder renders a bare
    id, is synthesised — we chose every character around the substitution.
    """
    sample = [record for record in records[:_URL_REPAIR_SAMPLE] if isinstance(record, dict)]
    if not sample:
        return False
    if "{" not in spec:
        return _is_per_job_link_field(sample, spec)
    placeholders = set(_TEMPLATE_RE.findall(spec))
    if len(placeholders) != 1:
        return False
    return not _renders_id_token(sample, next(iter(placeholders)))


def _renders_link(record: Any, spec: str) -> bool:
    """``spec`` renders something ``map_records`` can turn into a link on ``record`` —
    an absolute URL, or a leading-slash path it resolves against ``base_url``."""
    rendered = render_field(record, spec)
    return isinstance(rendered, str) and rendered.startswith(("https://", "http://", "/"))


def _names_a_page(value: Any) -> bool:
    """The rendered link names a PAGE, not a query against the site root.

    THE GUARD THAT KEEPS RUNG 1 HONEST, and it was learned on a board we were already
    tracking. Nintendo's Greenhouse feed publishes
    ``absolute_url = "https://careers.nintendo.com/?gh_jid=4295098009"`` — every posting
    distinct, every one link-shaped, so every other test here passes it and discovery
    kept it verbatim without fetching anything. Measured live 2026-08-30: that URL
    answers **200 with 64,408 bytes of the LISTING PAGE**, titled "Careers at Nintendo -
    Join Our Team", and the job's own title is nowhere in it. The working link is
    ``/jobs/4295098009/``.

    ALL THE IDENTITY IS IN THE QUERY STRING, and the codebase already states the reason
    that is fatal, on the derivation side: see :func:`repair_url_template`'s note that
    the QUERY IS DROPPED when a board's own links are read, so "a board that keys its
    jobs by query parameter alone cannot be derived". This is its counterpart on the
    PUBLISHED side, and it costs nothing on the boards that are right: all 13 of the 19
    corpus boards that take rung 1 publish a path-bearing link (``job_path``,
    ``positionUrl``, ``portalJobPost.portalUrl``, Lever ``hostedUrl``, Greenhouse
    ``absolute_url`` at ``boards.greenhouse.io/<board>/jobs/<id>``,
    ``canonicalPositionUrl``, Recruitee ``careers_url``, SmartRecruiters ``ref``).

    Falling through sends the spec to rung 3, where ``derive_url_templates_from_links``
    reads the board's own anchors and PROVES what it emits by fetching two real jobs —
    which is exactly the treatment a link we cannot vouch for should get.
    """
    return isinstance(value, str) and urlsplit(value).path.strip("/") != ""


def _is_per_job_link_field(sample: list[Any], spec: str) -> bool:
    """``spec`` is a field the board fills with a link TO THIS JOB — not to the same
    place on every row, and not to the site root with an id hung off the query.

    The distinctness half is what keeps a board's ``companyLogoUrl``, careers-site
    banner or department page out of the ``url`` slot. Every one of them renders a
    perfectly well-formed absolute URL on every record, so "is it link-shaped" alone
    would happily store a PNG as the link to 2,000 jobs — a failure that looks fine in
    the recipe and is only visible by clicking. A per-job link is different per job by
    definition, so requiring it costs nothing real and closes the whole class.

    The path half is :func:`_names_a_page`, and it closes the other half of the same
    class: a URL that is distinct per job and still serves the same page to all of them.

    A board with a SINGLE record cannot answer the DISTINCTNESS question either way;
    there, being link-shaped is the best evidence available and the acceptance replay
    has already proved the board is readable. It still has to name a page.
    """
    values = {
        render_field(record, spec) for record in sample if _renders_link(record, spec)
    }
    if not values or not all(_names_a_page(value) for value in values):
        return False
    return len(values) > 1 or len(sample) == 1


# Field names that are the APPLY step rather than the posting — Lever publishes
# ``hostedUrl`` and ``applyUrl`` (the same URL plus ``/app``), Recruitee ``careers_url``
# and ``careers_apply_url``, Amazon ``job_path`` and ``url_next_step``. Both are real
# pages for the same job, so this is a preference and never a rejection: it only decides
# WHICH published field wins when the selector picked neither.
_APPLY_HINTS = ("apply", "next_step", "nextstep")


def published_url_fields(records: list[Any]) -> list[str]:
    """Every field path in ``records`` the BOARD filled with a link, best first.

    Ranked so the posting beats the apply form (:data:`_APPLY_HINTS`) and a shallower
    path beats a deeper one; ties break alphabetically so the answer is stable across
    runs. Only consulted when the selector answered a SYNTHESISED template — a board
    that publishes a link and a model that invented one instead is the model being
    wrong about a question the payload already answers.

    Held to the same per-job bar as :func:`is_published_url_spec`: a field that renders
    the SAME url on every record is a logo, a banner or the careers site, not a link to
    this job, and swapping an invented template for one of those would be a worse lie
    than the template.
    """
    sample = [record for record in records[:_URL_REPAIR_SAMPLE] if isinstance(record, dict)]
    if not sample:
        return []
    candidates = {
        path for path in _scalar_paths(sample[0]) if _is_per_job_link_field(sample, path)
    }
    return sorted(
        candidates,
        key=lambda path: (
            any(hint in path.lower() for hint in _APPLY_HINTS),
            path.count("."),
            path,
        ),
    )


def repair_url_template(
    records: list[Any], spec: str, captured_urls: list[str], board_host: str
) -> str:
    """``spec`` with its placeholder re-pointed at the field the board's OWN LINKS use,
    or ``spec`` unchanged. Pure; never raises.

    ONE OF TWO CANDIDATE GENERATORS for a synthesised template, and no longer the last
    word on one: ``discover._prove_job_link`` now FETCHES what this returns before it is
    stored. That is the fix for the half of the defect this function cannot reach — it
    needs the board to have requested a job page during the capture, and a board whose
    listing page never does (Jane Street) leaves it nothing to score, so it correctly
    refuses and the wrong link used to ship anyway.

    THE DEFECT. higher.gs.com publishes two ids per role: ``roleId``
    (``181783_GS_NOTICE_OF_FILING_LCA``, and a bare UUID on 21 of them) and
    ``externalSource.sourceId`` (``181783``). Only the second is the route key. The
    selector stored ``https://higher.gs.com/roles/{roleId}``, and because the board is
    a Next.js SPA that answers 200 for ``/roles/<anything>``, the wrong URL serves a
    6 KB empty shell where the right one serves 24 KB with the job title on it.
    :func:`_validate_url_field` cannot see that — its own docstring concedes it cannot
    detect a well-formed URL that 404s — so every "view job" link on the board was
    dead and nothing anywhere said so.

    THE RULE, and why it is safe rather than merely clever. Score fields against the
    path segments of URLs THE CAPTURE ITSELF RECORDED on the board's host, and rewrite
    only when

    1. the spec is a template with exactly ONE distinct placeholder,
    2. that placeholder renders an opaque id token, not a path (see
       :func:`_renders_id_token` — the Microsoft guard),
    3. it appears in ZERO of the board's own links, and
    4. exactly one OTHER id-token field appears in at least
       :data:`_URL_REPAIR_MIN_HITS` of them.

    Condition 3 is the whole safety story: a template whose id already shows up in the
    board's links can never be rewritten, so every board the model got right is
    untouched BY CONSTRUCTION rather than by a threshold that could drift. Every other
    condition can only make the rule refuse.

    Deliberately scoped to ``url``. ``id`` is half of ``job_listings``' composite
    primary key and the default ``dedupe_key``; re-pointing it would orphan every row
    the board already has, which then misses and eventually closes — the never-wrong-
    close failure, caused by us.
    """
    if "{" not in spec:
        return spec
    placeholders = set(_TEMPLATE_RE.findall(spec))
    if len(placeholders) != 1:
        return spec
    sample = [r for r in records[:_URL_REPAIR_SAMPLE] if isinstance(r, dict)]
    if len(sample) < _URL_REPAIR_MIN_HITS:
        return spec
    segments = _board_url_segments(captured_urls, board_host)
    if not segments:
        return spec
    current = next(iter(placeholders))
    if not _renders_id_token(sample, current):
        return spec                       # a PATH placeholder is never repaired
    if _segment_hits(sample, current, segments) > 0:
        return spec                       # already the board's own route key
    winners = {
        path: hits
        for path in _scalar_paths(sample[0])
        if path != current
        and _renders_id_token(sample, path)
        and (hits := _segment_hits(sample, path, segments)) >= _URL_REPAIR_MIN_HITS
    }
    if len(winners) != 1:
        return spec
    winner, hits = next(iter(winners.items()))
    # A lambda, not a replacement STRING: a backslash in a payload key would otherwise
    # be read as a group reference and corrupt the template.
    repaired = _TEMPLATE_RE.sub(lambda _m: "{" + winner + "}", spec)
    logger.warning(
        "field_map.url %r never appears in this board's own links; re-pointing it at "
        "%r, which does on %d of %d sampled records (repaired: %r)",
        spec, winner, hits, len(sample), repaired,
    )
    return repaired


# --------------------------------------------------------------------------
# DERIVING a job-url template — the rung above "prove it or degrade"
# --------------------------------------------------------------------------
#
# WHY THIS IS A NEW RULE AND NOT AN EXTENSION OF ``repair_url_template``. That function
# swaps the PLACEHOLDER FIELD and never the surrounding path, and its condition 3
# refuses unless the current id appears in ZERO of the board's own links. Jane Street's
# ``{id}`` is the RIGHT id in the WRONG path — the id appears everywhere, so condition 3
# fails and the repair correctly no-ops. Nothing that only rewrites the substitution can
# reach a defect in the path.
#
# WHAT THESE TWO FUNCTIONS DO INSTEAD is derive the PATH, from evidence the board itself
# published, and hand the result to ``discover._prove_job_link`` — which fetches two real
# jobs and compares the rendered pages — before it can be stored. They only ever PROPOSE.
# A derivation that is wrong is rejected by the same gate that rejects the model's guess:
# measured against the live board, ``/join-jane-street/position/{id}/`` proves,
# ``/search/?query={id}`` is refused ("two different jobs served the same page") and the
# model's ``/jobs/{id}`` is refused (HTTP 404).

# How many sampled records must independently produce the SAME template shape. Three
# different job ids landing in the same URL shape is not a coincidence; one is a
# navigation link that happens to contain a number.
_MIN_TEMPLATE_AGREEMENT = 3
# Below this an id token matches path segments by accident — "1" or "42" occurs in
# pagination links, breadcrumbs and asset names on nearly every page.
_MIN_ID_TOKEN_CHARS = 3
# How many derived candidates are handed on. Each one costs two live GETs to prove, and
# the ranking below is confident enough that a third-placed template has never been the
# answer in the corpus.
MAX_DERIVED_LINK_CANDIDATES = 2

# ``href="/join-jane-street/position/${t.id}/"`` — a link the board's OWN CODE builds,
# carrying exactly one substitution. This is the fallback source for a board that renders
# no job anchors at all, and it is the only reason Jane Street is reachable: its listing
# page is a chooser that renders zero postings, so there are no anchors to mine, but the
# script it loads spells the shape literally. Deliberately anchored on ``href=`` rather
# than on any URL-looking string: a bare path in a bundle is as likely to be an API route
# or an image as a page, while an ``href`` is by definition something the board intends a
# human to open.
_HREF_TEMPLATE_RE = re.compile(
    r"""href\s*=\s*(?P<q>["'`])"""
    r"""(?P<head>(?:https?://[^"'`\s>]{1,200})?/[^"'`\s>${}]{0,200})"""
    r"""\$\{[^{}]{1,60}\}"""
    r"""(?P<tail>[^"'`\s>${}]{0,200})(?P=q)"""
)


def _absolute_board_links(links: list[str], base_url: str, board_host: str) -> list[str]:
    """The hrefs that are pages on the BOARD'S OWN HOST, absolutized against ``base_url``.

    Everything else is dropped without ceremony: ``mailto:``/``javascript:``/``#anchor``
    are not pages, and an off-host link is somebody else's site. Same-host is the same
    predicate :func:`repair_url_template` uses, for the same reason — there must be one
    definition of "the board's own host" or two rules can disagree about a subdomain.
    """
    out: list[str] = []
    for href in links:
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
            continue
        absolute = urljoin(base_url, href) if not href.startswith(("http://", "https://")) else href
        parts = urlsplit(absolute)
        if parts.scheme not in ("http", "https"):
            continue
        if not _same_board_host(parts.netloc, board_host):
            continue
        out.append(absolute)
    return out


def _id_token_paths(sample: list[Any], preferred: str | None = None) -> list[str]:
    """Record paths that render an OPAQUE ID TOKEN, ``preferred`` first.

    ``preferred`` is the field the recipe already uses as ``id``; putting it first is
    what makes the derived template agree with the ``dedupe_key`` whenever the board
    routes on the same id, which is the common case and the one worth being stable on.
    """
    if not sample:
        return []
    paths = [p for p in _scalar_paths(sample[0]) if _renders_id_token(sample, p)]
    if preferred in paths:
        paths.remove(preferred)
        paths.insert(0, preferred)
    return paths


def _generalize(url: str, token: str, field: str) -> str | None:
    """``url`` with the path segment equal to ``token`` replaced by ``{field}``.

    Only whole SEGMENTS and their pre-dot stems count (``/roles/181782.json`` yields
    ``/roles/{field}.json``), which is the same reading of "the board spells the id here"
    that :func:`_board_url_segments` already uses.

    The QUERY IS DROPPED. An anchor's query string is where boards put tracking
    (``?gh_src=``, ``?utm_campaign=``), and carrying it into a stored template would
    replay somebody's campaign parameters on every job link forever. A board that keys
    its jobs by query parameter alone therefore cannot be derived from its anchors — it
    falls through to the model's own answer, which is where it is today.
    """
    parts = urlsplit(url)
    segments = parts.path.split("/")
    for i, segment in enumerate(segments):
        if segment == token:
            segments[i] = "{" + field + "}"
        elif "." in segment and segment.rsplit(".", 1)[0] == token:
            segments[i] = "{" + field + "}." + segment.rsplit(".", 1)[1]
        else:
            continue
        return f"{parts.scheme}://{parts.netloc}{'/'.join(segments)}"
    return None


def derive_url_templates_from_links(
    records: list[Any], board_links: list[str], base_url: str, board_host: str,
    *, id_spec: str | None = None,
) -> list[str]:
    """Job-url templates the BOARD'S OWN ANCHORS agree on, best first. Pure; never raises.

    THE DERIVATION THE PROBE COULD NOT DO. ``_prove_job_link`` can prove a template wrong
    and cannot find the right one, so a board with no published link field degraded to a
    ``listing-page#{id}`` fragment however obvious its real shape was. This reads the
    shape straight off the page: match each record's id tokens against the path segments
    of the links the rendered document contains, and generalize the ones that hit.

    Agreement is the whole guard. A single record whose id happens to equal a path
    segment proves nothing — ``/careers/2024/`` matches a job id of ``2024`` — so a
    template is only returned when :data:`_MIN_TEMPLATE_AGREEMENT` DIFFERENT records
    produce it (or every record, on a board that has fewer). Ranked by agreement, then by
    the shortest template, so ``/company/careers/details/{id}`` beats a longer link that
    merely contains the same segment.
    """
    sample = [r for r in records[:_URL_REPAIR_SAMPLE] if isinstance(r, dict)]
    links = _absolute_board_links(board_links, base_url, board_host)
    if not sample or not links:
        return []
    # {template: the records that produced it} — records, not hits, so one record
    # matching one template ten times still counts once.
    agreement: dict[str, set[int]] = {}
    for path in _id_token_paths(sample, id_spec):
        for index, record in enumerate(sample):
            value = render_field(record, path)
            if not isinstance(value, (str, int)) or isinstance(value, bool):
                continue
            token = str(value)
            if len(token) < _MIN_ID_TOKEN_CHARS:
                continue
            for link in links:
                template = _generalize(link, token, path)
                if template is not None:
                    agreement.setdefault(template, set()).add(index)
    floor = min(_MIN_TEMPLATE_AGREEMENT, len(sample))
    winners = [t for t, seen in agreement.items() if len(seen) >= floor]
    winners.sort(key=lambda t: (-len(agreement[t]), len(t), t))
    if winners:
        logger.info(
            "derived %d job-url template(s) from the board's own links, best %r "
            "(agreed on by %d of %d sampled records)",
            len(winners), winners[0], len(agreement[winners[0]]), len(sample),
        )
    return winners[:MAX_DERIVED_LINK_CANDIDATES]


def href_templates(body: str) -> list[str]:
    """Every ``href="…${…}…"`` literal in one document or script, deduped, in order.

    A template with TWO substitutions is not returned — Jane Street's bundle also builds
    ``/join-jane-street/closed-internship/${i}-${a}-${s}/``, which is assembled from a
    slug, a duration and a location and cannot be reconstructed from a job id. The regex
    admits exactly one ``${…}`` and rejects the rest by construction.
    """
    seen: dict[str, None] = {}
    for match in _HREF_TEMPLATE_RE.finditer(body):
        seen.setdefault(match.group("head") + "{}" + match.group("tail"), None)
    return list(seen)


def derive_url_templates_from_code(
    records: list[Any], templates: list[str], base_url: str, board_host: str,
    *, id_spec: str | None = None, careers_path: str = "",
) -> list[str]:
    """The board's own link templates, filled with OUR id fields, best first. Pure.

    Ranked by how much of the careers page's own path each one shares. That is the whole
    heuristic and it is a good one: a board's job page lives next to its listing page
    (``/join-jane-street/open-roles/`` → ``/join-jane-street/position/{id}/``), while the
    site-wide search box the same bundle also builds (``/search/?query={}``) shares
    nothing. It only decides ORDER — every candidate is still fetched and proved, and the
    search template is exactly the one the proof rejects for serving the same page twice.
    """
    sample = [r for r in records[:_URL_REPAIR_SAMPLE] if isinstance(r, dict)]
    id_paths = _id_token_paths(sample, id_spec)
    if not sample or not id_paths:
        return []
    wanted = [s for s in careers_path.split("/") if s]

    def shared_prefix(template: str) -> int:
        got = [s for s in urlsplit(template).path.split("/") if s]
        n = 0
        for a, b in zip(wanted, got):
            if a != b:
                break
            n += 1
        return n

    ranked = sorted(
        {t for t in templates if t.count("{}") == 1},
        key=lambda t: (-shared_prefix(t), len(t), t),
    )
    out: list[str] = []
    for template in ranked:
        absolute = (
            template if template.startswith(("http://", "https://"))
            else urljoin(base_url, template)
        )
        if not _same_board_host(urlsplit(absolute).netloc, board_host):
            continue
        # ONE id field per template, not the cross product: a second field would double
        # the proof's fetch bill for a shape we have no evidence prefers it, and
        # ``_id_token_paths`` already puts the recipe's own id first.
        out.append(absolute.replace("{}", "{" + id_paths[0] + "}"))
        if len(out) >= MAX_DERIVED_LINK_CANDIDATES:
            break
    if out:
        logger.info(
            "derived %d job-url template(s) from the board's own code, best %r", len(out), out[0]
        )
    return out


# How many records the field-quality rules read. WIDER than the five the container check
# used, and the direction matters: every rule below asks whether something is true of
# EVERY sampled record, so more samples make a drop HARDER to reach, not easier. Twenty
# identical descriptions is boilerplate; five could be one job family.
_FIELD_QUALITY_SAMPLE = 20
# Below this the distinctness question is unanswerable — two jobs can legitimately share
# a description (the same role posted in two cities), and one job can answer nothing at
# all. A board that small keeps whatever it mapped.
_MIN_DISTINCTNESS_SAMPLE = 3

# The optionals whose value must DIFFER between jobs to be worth storing, and the whole
# argument for why this list has exactly one member.
#
# ``description`` is per-job data by definition: it is the prose about THIS role. Prose
# that is byte-identical across twenty different postings is describing the EMPLOYER —
# "Working at Atlassian", a benefits blurb, an EEO statement — and it identifies nothing.
# Storing it is worse than storing nothing: it fills the field, so nothing downstream
# ever asks again, and every job on the board reads the same.
#
# EVERY OTHER FIELD IS DELIBERATELY ABSENT, because for them identical is CORRECT:
#
#   location    a single-office company has one location on every job. Dropping it would
#               delete correct data from exactly the boards that are easiest to read.
#   posted_at   a board that published its catalogue on one day, or that stamps a batch
#               date, is a real board with a real date.
#   company_name  is SUPPOSED to be identical. That is what the field means.
#   id, title   are required; an unusable one RAISES in ``_validate_field_map`` and the
#               board is refused, which is the taxonomy's answer for a required field.
#   url         is already held to this bar by ``_is_per_job_link_field`` — the same idea,
#               generalized here rather than duplicated.
_MUST_DIFFER_FIELDS = ("description",)


def _prune_unusable_optionals(
    records: list[Any], field_map: dict[str, str]
) -> tuple[dict[str, str], tuple[str, ...]]:
    """``(field_map minus the optionals that are not real data, why each was dropped)``.

    THREE FAILURES, one of which this check has always caught and two of which walked
    straight past it. All three are invisible to every replay-time gate — the baseline is
    taken on the first run, so a field that was wrong at birth is simply what this board
    looks like, forever.

    1. **renders a container** (the original rule, unchanged — see below).
    2. **renders NOTHING, on every record.** ``useful`` is empty, so the container rule's
       ``if useful and …`` is vacuously false and the mapping was KEPT. Measured shape:
       ``location: "locations[0].city"`` against a payload whose ``locations`` is a list
       of plain strings — a column of NULLs on 100% of rows, reported as a healthy board.
    3. **renders the SAME value on every record** (:data:`_MUST_DIFFER_FIELDS`). A
       description identical across twenty jobs is company boilerplate, not this job's
       prose. Read that constant for why the list has exactly one member and why
       ``location``/``posted_at`` must never join it.

    Dropping is a DEGRADE and never a refusal: the board keeps being tracked with one
    fewer optional. The required three are not pruned here at all — they RAISE in
    :func:`_validate_field_map` / :func:`_validate_url_field`, because a board we cannot
    identify, title or link is a board we must refuse rather than half-read.

    Drop any OPTIONAL mapping that renders a container rather than a scalar.

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

    Rendering through :func:`render_row_field` is what makes the scalar/container
    distinction free — the prune sees exactly the value the runner will store.
    """
    pruned = dict(field_map)
    notes: list[str] = []

    def _drop(name: str, spec: str, why: str) -> None:
        logger.info("dropping field_map.%s=%r: %s", name, spec, why)
        notes.append(f"field_map.{name} {spec!r} was dropped — {why}")
        del pruned[name]

    sample = [r for r in records[:_FIELD_QUALITY_SAMPLE] if isinstance(r, dict)]
    for name in ("location", "posted_at", "description"):
        spec = pruned.get(name)
        if spec is None:
            continue
        if "{" in spec:                      # a template always renders a string
            continue
        rendered = [render_row_field(r, name, spec) for r in sample]
        useful = [v for v in rendered if v not in (None, "")]
        if not rendered:
            continue
        if not useful:
            _drop(
                name, spec,
                f"it renders nothing on all {len(rendered)} sampled record(s), so it "
                "would store an empty column on every job",
            )
            continue
        if not any(_is_scalar(v) for v in useful):
            _drop(name, spec, f"it renders a container ({useful[0]!r}), not a value")
            continue
        if (
            name in _MUST_DIFFER_FIELDS
            and len(rendered) >= _MIN_DISTINCTNESS_SAMPLE
            and len({str(v) for v in rendered}) == 1
        ):
            _drop(
                name, spec,
                f"it renders the SAME value on all {len(rendered)} sampled record(s), so "
                "it describes the company rather than this job",
            )
    return pruned, tuple(notes)


# --------------------------------------------------------------------------
# "title is the URL" — deriving a title from a job link's slug
# (PATH-TO-90-PERCENT.md §3 "Our schema", §6 Stage 2)
# --------------------------------------------------------------------------
#
# Two measured boards are readable ONLY from a source that publishes URLs and nothing
# else. Bloomberg's Avature sitemap and Citadel's Yoast career sitemap both list
# ``<loc>`` and ``<lastmod>``, so the only value a recipe can put in ``title`` is the
# job's own URL — and ``map_records`` drops a row with no title, so mapping title to the
# URL is not a mistake, it is the only way the row exists at all. What was missing was
# any way to say "and the title is the slug inside it".
#
# THE PATTERN IS DERIVED AND PROVEN HERE, NEVER ASKED OF THE MODEL. Same rule as the
# oracle, the headers and the in-band error keys: a plausible hallucination in this
# position costs a nightly FAILED run, and the bytes we captured can answer it exactly.
# ``recipe_schema.validate_capture_pattern`` still bounds whatever ends up stored,
# because a JSONB row can be edited by someone who is not this function.
#
# The family is ORDERED and short. Each entry has exactly one capture group and stays
# inside the schema's quantifier bound; a board whose links match neither simply gets no
# transform, which is the same outcome it has today.
_TITLE_SLUG_PATTERNS: tuple[str, ...] = (
    # ``…/JobDetail/Senior-Software-Engineer/21653`` — the slug, then a numeric req id.
    r"/([^/?#]+)/\d+/?$",
    # ``…/careers/details/commodities-portfolio-manager/`` — the slug is the last
    # segment, trailing slash or not.
    r"/([^/?#]+)/?$",
)

# How many records the derivation reads. Shared with the field-quality prune on purpose:
# both are answering "what does this map ACTUALLY produce on this board".
_TITLE_DERIVE_SAMPLE = _FIELD_QUALITY_SAMPLE

# Below this the questions below cannot be answered — a two-record board cannot show
# that a derivation is distinct rather than a constant.
_MIN_TITLE_DERIVE_RECORDS = 3

# A derived title has to be plausible PROSE, not the leftovers of a path. All three
# bounds come from the failure they prevent: too short is an id fragment, no letter is a
# number, and looking like a URL means the pattern captured the wrong segment.
_MIN_DERIVED_TITLE_CHARS = 3


def _looks_like_url(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(("https://", "http://", "/"))


def _usable_derived_title(text: Any) -> bool:
    return (
        isinstance(text, str)
        and len(text) >= _MIN_DERIVED_TITLE_CHARS
        and any(ch.isalpha() for ch in text)
        and not _looks_like_url(text)
    )


def derive_title_from_url(
    records: list[Any], field_map: dict[str, str]
) -> TitleFromUrl | None:
    """A proven slug-to-title derivation for this board, or ``None``.

    ``None`` is the answer for every board whose title is a title, which is all of them
    today — the derivation only fires when the mapped ``title`` renders a LINK on EVERY
    sampled record, i.e. when the recipe would otherwise store a URL in the title column.

    The proof bar is 100% of the sample, not a majority, and that is deliberate: as of
    Stage 2 a shaping step that empties a required field is a FAILED run
    (``recipe_runner._assert_shaping_kept_required_fields``), so a pattern that works on
    nine records in ten would take the board down every night instead of mis-titling one
    row. A pattern that cannot do the whole sample is not this board's pattern.
    """
    sample = [r for r in records[:_TITLE_DERIVE_SAMPLE] if r is not None]
    if len(sample) < _MIN_TITLE_DERIVE_RECORDS:
        return None
    titles = [render_row_field(r, "title", field_map["title"]) for r in sample]
    if not all(_looks_like_url(t) for t in titles):
        return None
    urls = [render_row_field(r, "url", field_map["url"]) for r in sample]
    if not all(isinstance(u, str) and u for u in urls):
        return None

    for pattern in _TITLE_SLUG_PATTERNS:
        try:
            validate_capture_pattern(pattern, "transform")
        except RecipeError:  # pragma: no cover - the family is pinned by a test
            continue
        derived = [
            _regex_capture_value({"url": url}, {"from": "url", "pattern": pattern,
                                                "unslug": True})
            for url in urls
        ]
        if not all(_usable_derived_title(d) for d in derived):
            continue
        if len(set(derived)) < 2:
            # One value for the whole board is not a title, it is a path constant the
            # pattern happened to capture (``/careers/details/`` on every link).
            continue
        return TitleFromUrl(pattern=pattern, unslug=True)
    return None


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


def _to_selection(envelope: _SelectionEnvelope, candidate: Candidate) -> RequestSelection:
    """The believed-and-re-checked answer for ONE candidate.

    Every check below is unchanged from when this took a whole list and an index: the
    records path must resolve, the required fields must render scalars, the url must be
    a link, the unusable optionals are pruned. What changed is only WHAT it is checking —
    one array the model said yes about, instead of one array it ranked first.
    """
    index = candidate.index
    records = _resolved_records(candidate, envelope.records_path)

    field_map = {
        "id": envelope.field_map.id.strip(),
        "title": envelope.field_map.title.strip(),
        "url": envelope.field_map.url.strip(),
    }
    for name in ("location", "posted_at", "description"):
        value = getattr(envelope.field_map, name)
        if isinstance(value, str) and value.strip():
            field_map[name] = value.strip()
    for required in ("id", "title", "url"):
        if not field_map[required]:
            raise RequestSelectionError(f"field_map.{required} is empty")
    _validate_field_map(records, field_map)
    _validate_url_field(records, field_map["url"])
    field_map, field_notes = _prune_unusable_optionals(records, field_map)

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
        field_notes=field_notes,
        # Measured LAST, after the prune, for the same reason ``posted_at_format`` is:
        # it is a statement about the field map that will actually be stored.
        title_from_url=derive_title_from_url(records, field_map),
    )


@dataclass(frozen=True)
class CandidateAnswer:
    """What the model said about ONE array.

    ``selection`` is ``None`` for a no — the per-array restatement of
    :class:`NoJobsFeedError`, and the reason a no is now CHEAP: saying it about one
    array does not forfeit the board.
    """

    candidate_index: int
    selection: RequestSelection | None
    confidence: str = "low"


# The keys that mark a request as SESSION-BOUND (check C15). Walmart's stored fetch body
# carries ``thread_id: "S-1788038636412-<uuid>"`` whose embedded epoch decodes to six
# seconds after the company row was created — minted inside that one discovery browser
# session. It is the defining property of a chat reply masquerading as a jobs API.
#
# It is a RANKING DEMOTION and never a refusal, because code cannot prove a session key
# is fatal: plenty of boards send a correlation id the server ignores. And a recipe
# carrying one PASSES ACCEPTANCE BY CONSTRUCTION, because acceptance runs minutes later
# while the token is still alive — which is exactly why the honest handling is to demote
# it below every candidate without one rather than to trust the gate.
SESSION_KEY_NAMES = frozenset({
    "threadid", "sessionid", "conversationid", "chatid",
    "correlationid", "requestid", "traceid",
})

# THE FAN-OUT'S BOUNDS. Ten calls per round, six at a time. Ten because the pre-filter
# already ranks and caps, so the tail this truncates is the least job-shaped; six
# because the calls are ~1.3k input tokens each and the point of the semaphore is to
# keep one board's discovery from being the thing that rate-limits the next one's.
_MAX_FANOUT_CALLS = 10
_FANOUT_CONCURRENCY = 6


def _candidate_body(candidate: Candidate) -> Any:
    if not candidate.post_data:
        return None
    try:
        return json.loads(candidate.post_data, strict=False)
    except Exception:  # noqa: BLE001 - a body we cannot read carries no session key
        return None


def session_token_keys(candidate: Candidate) -> tuple[str, ...]:
    """The session-bound parameter names this candidate's request carries (C15).

    Deliberately reuses ``iter_body_params`` — the same walker ``page_shape_refusal``
    uses to find a page parameter — so "where a parameter lives in this body" keeps
    exactly one definition in the codebase.
    """
    from ..recipe_runner import iter_body_params

    body = _candidate_body(candidate)
    if body is None:
        return ()
    found: list[str] = []
    for _path, key, _value in iter_body_params(body):
        flat = "".join(ch for ch in str(key).lower() if ch.isalnum())
        if flat in SESSION_KEY_NAMES and key not in found:
            found.append(str(key))
    return tuple(found)


def _records_digest(candidate: Candidate) -> str:
    """A stable fingerprint of the RECORDS, so the same array is never paid for twice.

    Islands frequently duplicate an XHR payload byte for byte — the served document
    embeds exactly what the page would otherwise fetch — and asking about the same rows
    from two sources is one wasted call and two chances at a different answer.
    """
    try:
        blob = json.dumps(candidate.records, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001 - an unserializable record is its own fingerprint
        blob = repr(candidate.records)
    return hashlib.sha256(blob.encode("utf-8", "replace")).hexdigest()


def _is_known_non_feed(candidate: Candidate) -> bool:
    """A shape we can rule out without spending a token.

    One or zero records from a request carrying a conversational session key is a chat
    reply, not a board. Both halves are needed: a one-record jobs API is a small board,
    and a session key on a hundred records is a correlation id.
    """
    return candidate.record_count < 2 and bool(session_token_keys(candidate))


async def classify_candidate(
    candidate: Candidate,
    *,
    feedback: str | None = None,
    create_message: CreateMessage | None = None,
) -> CandidateAnswer:
    """Ask Haiku 4.5 about ONE array: is it a jobs feed, and how does it map?

    Raises :class:`SelectorKeyMissingError` when no API key is configured (degrade, do
    not retry) and :class:`RequestSelectionError` for an unbelievable answer or a failed
    call. A ``False`` answer is a RETURN, not an exception — it kills this candidate and
    nothing else.
    """
    try:
        response = await (create_message or _default_create_message)(
            build_message_params(candidate, feedback=feedback)
        )
    except APIError as exc:
        # A 529/overload/connection blip is not an unbelievable ANSWER, but the caller
        # must treat it the same way — as a failed candidate it can re-ask about, not as
        # an escaping exception. Uncaught, it lands in ``discover``'s last-resort handler
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
    confidence = envelope.confidence if envelope.confidence in ("high", "low") else "low"
    if not envelope.is_jobs_feed:
        return CandidateAnswer(candidate.index, None, confidence)
    return CandidateAnswer(
        candidate.index, _to_selection(envelope, candidate), confidence
    )


async def select_candidates(
    candidates: list[Candidate],
    *,
    feedback: str | None = None,
    create_message: CreateMessage | None = None,
) -> list[CandidateAnswer]:
    """THE FAN-OUT — one model call per record-bearing candidate, in parallel.

    Returns only the candidates the model said YES about, in the order they were asked
    (i.e. pre-filter rank order); the referee in ``discover`` re-ranks them on
    MEASUREMENTS, and the ``confidence`` field is only ever the last tie-break.

    Raises :class:`NoJobsFeedError` when every candidate came back a clean no — asking
    again cannot change that. Raises :class:`RequestSelectionError` when nothing came
    back usable but something went WRONG (a timeout, an unbelievable answer, an SDK
    error), because that is a round worth re-asking with the evidence attached. The
    difference between those two is the difference between stopping and retrying.

    A call that raises or times out kills THAT CANDIDATE ONLY. That is a strict
    robustness gain over one call over the whole list, where a single bad answer burned
    the round and, on a single-feed board, the discovery.
    """
    if not candidates:
        raise RequestSelectionError("no job-shaped JSON responses were captured")

    asked: list[Candidate] = []
    digests: set[str] = set()
    for candidate in candidates:
        if len(asked) >= _MAX_FANOUT_CALLS:
            break
        if _is_known_non_feed(candidate):
            logger.info(
                "fan-out skipped %s %s: %d record(s) from a request carrying %s",
                candidate.method, candidate.url, candidate.record_count,
                ", ".join(session_token_keys(candidate)),
            )
            continue
        digest = _records_digest(candidate)
        if digest in digests:
            logger.info(
                "fan-out skipped %s: byte-identical to a candidate already asked about",
                candidate.url,
            )
            continue
        digests.add(digest)
        asked.append(candidate)

    if not asked:
        raise NoJobsFeedError(
            f"none of the {len(candidates)} captured array(s) can be a list of job "
            "postings"
        )

    semaphore = asyncio.Semaphore(_FANOUT_CONCURRENCY)

    async def _one(candidate: Candidate) -> CandidateAnswer:
        async with semaphore:
            return await asyncio.wait_for(
                classify_candidate(
                    candidate, feedback=feedback, create_message=create_message
                ),
                timeout=LLM_TIMEOUT_SECONDS,
            )

    results = await asyncio.gather(
        *(_one(c) for c in asked), return_exceptions=True
    )

    answers: list[CandidateAnswer] = []
    key_missing: SelectorKeyMissingError | None = None
    failures: list[str] = []
    for candidate, result in zip(asked, results):
        if isinstance(result, SelectorKeyMissingError):
            key_missing = result
            continue
        if isinstance(result, BaseException):
            failures.append(f"{candidate.url}: {result}")
            logger.info(
                "fan-out call failed for %s (%s) — this candidate only",
                candidate.url, result,
            )
            continue
        if result.selection is not None:
            answers.append(result)
    if answers:
        return answers
    # A misconfigured deployment is not the board's fault and must not burn an attempt.
    if key_missing is not None:
        raise key_missing
    if failures:
        raise RequestSelectionError(
            f"every candidate's selection call failed: {'; '.join(failures[:3])}"
        )
    raise NoJobsFeedError(
        f"none of the {len(asked)} captured array(s) is a list of job postings"
    )
