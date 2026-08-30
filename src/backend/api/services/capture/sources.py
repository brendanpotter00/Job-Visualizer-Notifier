"""THE EVIDENCE SOURCES discovery may look at, and the one nobody can observe.

Discovery had exactly one source of evidence: network responses with a JSON
content-type. Everything it could ever know was whatever happened to be in that list,
and every traced failure is one of two shapes — *the answer was not in that list*, or
*a wrong-but-plausible entry was in it*.

``careers.walmart.com/sitemap.xml`` is the first shape, in its purest form: 16,210
``<loc>`` entries, 15,660 of them job pages, one 2 MB GET, ~294 ms — and **the page
never requests it**, because a sitemap exists for crawlers and not for the site's own
JavaScript. No amount of watching network traffic produces it. It is findable only by
CONVENTION.

So this module composes a fixed list of well-known paths from the entry origin and
fetches them through :func:`~api.services.guarded_client.guarded_sync_client` — the
same SSRF boundary ``discover._default_probe`` and the nightly replay already use,
because these are URLs WE composed from a host a stranger pasted.

**A miss is silent and costs nothing.** Measured hit rate is roughly 1 in 4:
``janestreet.com``, ``amazon.jobs`` and ``higher.gs.com`` all 404 on
``/sitemap.xml``; ``atlassian.com`` answers 200 with a ``<sitemapindex>`` naming eight
child sitemaps, none of which is jobs. Three of those four boards are boards we track
perfectly well, so anything this module cannot find has to be indistinguishable from
never having asked.

**``robots.txt`` is READ, never OBEYED as a gate.** Walmart's ``Disallow: /api`` covers
the exact GraphQL endpoint its own careers page calls. Treating a disallow as a refusal
would kill boards we can read; the file is parsed for its ``Sitemap:`` lines and for
nothing else.

**What a sitemap can and cannot be.** ``CANONICAL_REQUIRED_FIELDS`` is
``(id, title, url)`` and ``map_records`` drops any row missing an id or a title. A
``<loc>`` gives an id and a URL and **no title** — Walmart's sitemap carries no
``<news:title>`` and no JobPosting extension. So a sitemap can enumerate a board
perfectly and still never BE the board. It contributes an ORACLE and an ID SET, never
records, and :attr:`EvidenceSource.contributions` is where that is stated once instead
of re-argued at every call site.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Literal
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree

from ..guarded_client import guarded_sync_client

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# the type
# --------------------------------------------------------------------------

# What a source is ALLOWED to contribute. This is the fan-out's short-circuit and the
# reason the type exists at all: a source with no ``records`` contribution can never
# cost a model call and can never become a stored recipe, whatever anything says about
# it. It is also what keeps the sitemap out of the record path without needing a rule
# about sitemaps.
Contribution = Literal["records", "oracle", "link_template", "id_set"]


@dataclass(frozen=True)
class EvidenceSource:
    """A bag of bytes, where it came from, and what it may contribute.

    ``replay_transport`` is what makes a source HONEST. A source no transport can
    replay may never produce a stored recipe — that is the invariant that keeps the
    rendered DOM a link-and-counting source without a special case, because there is no
    transport that replays markup (``browser_fetch`` hard-requires
    ``extract_json_path``; every DOM transport is a rejected Phase-4 capability).
    """

    kind: str                    # "well_known" | "island" | "server_html" | ...
    origin: str                  # the URL these bytes came from — provenance + logs
    media: str                   # "json" | "html" | "xml" | "js" | "text"
    body: str                    # raw bytes as text; may be ""
    contributions: frozenset[Contribution]
    replay_transport: str | None = None
    note: str = ""               # why it was collected / why it is capped


# --------------------------------------------------------------------------
# source 5 — well-known paths, fetched by convention
# --------------------------------------------------------------------------

# THE WHOLE COST of this collector, and every number is a ceiling it enforces on
# ITSELF. It runs CONCURRENTLY with the browser capture (which takes 30-120 s), so the
# 15 s wall clock is spent entirely inside the browser's shadow and the added latency of
# the whole source is zero.
_WELL_KNOWN_BUDGET_S = 15.0
# Rows 1-4 of the plan's table can ASK for eight requests (1 robots + 4 sitemap
# documents + 3 speculative). Seven is the ceiling, so the speculative probes are the
# ones that get cut — which is the right order: rows 1-3 have measured evidence behind
# them and row 4 has none.
_WELL_KNOWN_MAX_REQUESTS = 7
_WELL_KNOWN_MAX_TOTAL_BYTES = 12_000_000
# Measured: Walmart's robots.txt is 197 bytes. The cap is three orders of magnitude of
# headroom and still bounds a hostile answer.
_ROBOTS_MAX_BYTES = 256_000
# Measured: Walmart's sitemap is 2,019,397 bytes / 294 ms. Same 4 MB per-document cap
# the capture child applies to a JSON body, for the same reason.
_SITEMAP_MAX_BYTES = 4_000_000
# Rows 2 AND 3 of the table share this budget: a ``<sitemapindex>`` expansion spends
# from the same four documents its index came out of, so following an index can never
# multiply the cost.
_MAX_SITEMAP_DOCUMENTS = 4
# How many ``Sitemap:`` lines we are willing to consider before the document budget
# above decides which of them actually get fetched.
_MAX_ROBOTS_SITEMAP_LINES = 16
_PER_REQUEST_TIMEOUT_S = 8.0

# SPECULATIVE, and said so out loud. No board in this repo's corpus publishes any of
# these; they cost three GETs that 404 in well under a second, which is cheap enough to
# keep and nowhere near evidence. Nobody should be told this module is about /jobs.json.
_SPECULATIVE_PATHS = ("/jobs.json", "/feed", "/api/jobs")

# Which child of a ``<sitemapindex>`` to spend the budget on first. Atlassian's index
# names eight children (products/solutions/resources/templates/customers/company/
# locales/other) and none of them is jobs — so the ordering is what stops us spending
# four documents on marketing pages, and the fact that it finds nothing there is the
# correct answer for that board.
_JOB_WORD_HINTS = ("job", "career", "position", "opening", "vacanc", "role")

_SITEMAP_LINE_RE = re.compile(r"^\s*sitemap\s*:\s*(\S+)\s*$", re.IGNORECASE | re.MULTILINE)


# One well-known fetch: ``(url, max_bytes) -> (status, body)``. A status of 0 means the
# fetch never happened (guard refusal, DNS, timeout, reset) and is treated exactly like
# a 404 — this source simply is not there.
WellKnownFetch = Callable[[str, int], tuple[int, str]]


@dataclass(frozen=True)
class SitemapDocument:
    """One fetched sitemap, reduced to the URLs it lists.

    ``is_index`` is the difference between "these are pages" and "these are other
    sitemaps", and getting it wrong is the bug §4.3 of the plan names: a
    ``<sitemapindex>``'s ``<loc>`` entries are child SITEMAP urls, and counting eight of
    them as eight jobs (or raising "0 matching") are both wrong answers.
    """

    url: str
    locs: tuple[str, ...]
    is_index: bool


@dataclass(frozen=True)
class WellKnownEvidence:
    """Everything source 5 found. The EMPTY value is the common case — see the module
    docstring's hit rate — and it must behave exactly like never having asked."""

    sources: tuple[EvidenceSource, ...] = ()
    sitemaps: tuple[SitemapDocument, ...] = ()

    @property
    def page_locs(self) -> tuple[str, ...]:
        """Every page URL any non-index sitemap listed, deduped, order preserved."""
        seen: dict[str, None] = {}
        for doc in self.sitemaps:
            if doc.is_index:
                continue
            for loc in doc.locs:
                seen.setdefault(loc, None)
        return tuple(seen)


def _origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else ""


def _hostname_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _default_fetch(url: str, max_bytes: int) -> tuple[int, str]:
    """GET ``url`` through the SAME SSRF-guarded client the nightly replay uses.

    Never raises: every failure is ``(0, "")``. Byte-capped by stopping the read, not by
    trusting a Content-Length nobody has to tell the truth about.

    Reusing :func:`~api.services.guarded_client.guarded_sync_client` is not incidental
    and is not optional — this fetches a URL WE composed against a host a stranger
    pasted, which is the exact threat that client's per-hop revalidation, host-pin and
    IP-pin exist for.
    """
    try:
        http = guarded_sync_client()
    except Exception:                       # pragma: no cover - client build cannot fail
        return 0, ""
    try:
        with http.stream("GET", url, timeout=_PER_REQUEST_TIMEOUT_S) as response:
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) >= max_bytes:
                    break
            return response.status_code, bytes(body).decode("utf-8", "replace")
    except Exception as exc:                # noqa: BLE001 - every failure is "not there"
        logger.info("well-known fetch could not read %s: %r", url, exc)
        return 0, ""
    finally:
        http.close()


def robots_sitemap_urls(body: str, origin: str) -> list[str]:
    """The ``Sitemap:`` lines, absolutised. Everything else in robots.txt is ignored.

    ``Disallow`` is deliberately NOT read. Walmart disallows ``/api``, which is where
    its own careers page fetches its jobs from; a crawler directive is a statement about
    crawlers, and treating it as a refusal would throw away boards we read correctly.
    """
    out: list[str] = []
    for match in _SITEMAP_LINE_RE.finditer(body):
        url = urljoin(origin + "/", match.group(1).strip())
        if url.startswith("https://") and url not in out:
            out.append(url)
        if len(out) >= _MAX_ROBOTS_SITEMAP_LINES:
            break
    return out


def parse_sitemap(url: str, body: str) -> SitemapDocument | None:
    """One sitemap document, or ``None`` when it is not XML we can read.

    THE ``<sitemapindex>`` SPLIT IS THE WHOLE FUNCTION. Both document types carry
    ``<loc>`` elements and they mean opposite things — pages in a ``<urlset>``, other
    sitemaps in a ``<sitemapindex>``. Measured on ``atlassian.com/sitemap.xml``: an
    index with eight children. Counting those eight as eight job pages, or raising
    "0 <loc> matching", are both wrong; knowing which document you are holding is what
    makes the difference expressible.
    """
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError:
        return None
    tag = root.tag.rsplit("}", 1)[-1].lower()
    locs: list[str] = []
    for element in root.iter():
        name = element.tag.rsplit("}", 1)[-1].lower() if isinstance(element.tag, str) else ""
        if name != "loc":
            continue
        text = (element.text or "").strip()
        if text:
            locs.append(text)
    return SitemapDocument(url=url, locs=tuple(locs), is_index=(tag == "sitemapindex"))


def _rank_index_children(children: list[str]) -> list[str]:
    """Job-shaped child sitemaps first. See :data:`_JOB_WORD_HINTS`.

    Matched on the PATH, never on the whole URL. Every child of
    ``careers.walmart.com/sitemap.xml`` contains the word "career" — in the HOST — so a
    whole-URL test hints every child equally and ranks nothing at all.
    """
    def _hinted(url: str) -> int:
        path = (urlsplit(url).path + "?" + urlsplit(url).query).lower()
        return 0 if any(hint in path for hint in _JOB_WORD_HINTS) else 1
    return sorted(children, key=_hinted)


def _collect_well_known_sync(
    entry_url: str, fetch: WellKnownFetch, *, budget_s: float = _WELL_KNOWN_BUDGET_S
) -> WellKnownEvidence:
    """The whole of source 5, synchronously. NEVER raises — a miss is silence.

    Order is the plan's table: robots.txt, then the sitemaps it names (or
    ``/sitemap.xml`` when it names none), then ONE level of ``<sitemapindex>``
    expansion out of the same document budget, then the speculative paths with whatever
    request budget is left.

    THE CLOCK IS ENFORCED HERE, not only by the caller's ``wait_for``, and that is the
    difference between DEGRADING and losing everything. Measured live on
    ``www.atlassian.com`` (2026-08-29): five documents, 17.4 s — over the ceiling. A
    timeout at the coroutine boundary would throw away the robots.txt and the three
    sitemaps already in hand and leave the thread running; stopping HERE returns what
    was read and simply asks for nothing more.
    """
    origin = _origin_of(entry_url)
    if not origin:
        return WellKnownEvidence()
    entry_host = _hostname_of(entry_url)

    deadline = time.monotonic() + budget_s
    sources: list[EvidenceSource] = []
    sitemaps: list[SitemapDocument] = []
    spent_requests = 0
    spent_bytes = 0

    def _get(url: str, max_bytes: int) -> tuple[int, str]:
        nonlocal spent_requests, spent_bytes
        if spent_requests >= _WELL_KNOWN_MAX_REQUESTS:
            return 0, ""
        if spent_bytes >= _WELL_KNOWN_MAX_TOTAL_BYTES:
            return 0, ""
        if time.monotonic() >= deadline:
            logger.info(
                "well-known collector out of time after %d request(s); keeping what it "
                "already read", spent_requests,
            )
            return 0, ""
        spent_requests += 1
        status, body = fetch(url, min(max_bytes, _WELL_KNOWN_MAX_TOTAL_BYTES - spent_bytes))
        spent_bytes += len(body)
        return status, body

    # ROW 1 — robots.txt, read only for its Sitemap: lines.
    robots_url = origin + "/robots.txt"
    status, body = _get(robots_url, _ROBOTS_MAX_BYTES)
    named: list[str] = []
    if 200 <= status < 300 and body:
        sources.append(EvidenceSource(
            kind="well_known", origin=robots_url, media="text", body=body,
            contributions=frozenset({"oracle"}),
            note="read for Sitemap: lines only — a Disallow is never a gate",
        ))
        named = robots_sitemap_urls(body, origin)

    # ROWS 2+3 — the sitemaps robots named (or the conventional one), then one level of
    # index expansion, all out of ONE document budget.
    #
    # SAME HOST ONLY. A sitemap is a claim source, not a feed, so following a
    # ``Sitemap:`` line to a third-party host buys nothing measurable and widens the set
    # of hosts a pasted URL can make us fetch. The guarded client is still the boundary;
    # this is the cheaper bound in front of it.
    queue: list[tuple[str, int]] = [
        (u, 0) for u in (named or [origin + "/sitemap.xml"])
        if _hostname_of(u) == entry_host
    ]
    seen_sitemaps: set[str] = set()
    while queue and len(sitemaps) < _MAX_SITEMAP_DOCUMENTS:
        url, depth = queue.pop(0)
        if url in seen_sitemaps:
            continue
        seen_sitemaps.add(url)
        status, body = _get(url, _SITEMAP_MAX_BYTES)
        if not (200 <= status < 300) or not body:
            continue
        doc = parse_sitemap(url, body)
        if doc is None:
            continue
        sitemaps.append(doc)
        sources.append(EvidenceSource(
            kind="well_known", origin=url, media="xml", body=body,
            contributions=frozenset({"oracle", "id_set"}),
            note=(
                f"sitemapindex naming {len(doc.locs)} child sitemap(s)"
                if doc.is_index else f"{len(doc.locs)} <loc> entries"
            ),
        ))
        # ONE level, and ``depth`` is what makes that literal. A sitemap index that
        # names indexes is not followed further: the budget is four documents and the
        # second level is where a hostile or merely enormous site would spend all of
        # them. Children are queued at the FRONT so an index's own postings are read
        # before the next ``Sitemap:`` line robots happened to name.
        if doc.is_index and depth == 0:
            children = [
                (u, 1) for u in _rank_index_children(list(doc.locs))
                if _hostname_of(u) == entry_host and u not in seen_sitemaps
            ]
            queue[:0] = children

    # ROW 4 — speculative, with whatever request budget rows 1-3 left. See
    # :data:`_SPECULATIVE_PATHS`: zero measured evidence, kept only because it is cheap.
    # ONE request guard, and it lives in ``_get``. A second copy of the same condition
    # here would look like belt and braces and is actually the opposite: two redundant
    # guards each hide the other's absence, so neither can be shown to be load-bearing.
    for path in _SPECULATIVE_PATHS:
        url = origin + path
        status, body = _get(url, _SITEMAP_MAX_BYTES)
        if 200 <= status < 300 and body:
            sources.append(EvidenceSource(
                kind="well_known", origin=url, media="json", body=body,
                contributions=frozenset({"id_set"}),
                note="speculative well-known path",
            ))

    return WellKnownEvidence(sources=tuple(sources), sitemaps=tuple(sitemaps))


async def collect_well_known(
    entry_url: str, *, fetch: WellKnownFetch | None = None
) -> WellKnownEvidence:
    """Source 5, off the event loop and bounded at :data:`_WELL_KNOWN_BUDGET_S`.

    NEVER raises and never cancels the thing it runs beside. A timeout, a guard refusal
    or an outright crash all return the same empty evidence, because three of the four
    boards we measured have no sitemap at all and the collector must be
    indistinguishable from never having asked on every one of them.
    """
    try:
        # The INNER deadline is the real one — it stops asking for more and returns what
        # it has. This outer one is the backstop for a single request that hangs past
        # its own 8 s timeout, and it is deliberately slack enough that the inner one
        # always fires first on a merely slow board.
        return await asyncio.wait_for(
            asyncio.to_thread(
                _collect_well_known_sync, entry_url, fetch or _default_fetch
            ),
            timeout=_WELL_KNOWN_BUDGET_S + _PER_REQUEST_TIMEOUT_S,
        )
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - a miss must cost nothing downstream
        logger.info("well-known collection failed for %s (continuing)", entry_url,
                    exc_info=True)
        return WellKnownEvidence()


# --------------------------------------------------------------------------
# turning <loc> lists into a claim about the board
# --------------------------------------------------------------------------

# An id has to be long enough to mean something inside a URL. A one-character id
# "matches" every loc on the site and would manufacture a claim out of nothing.
_MIN_SITEMAP_ID_CHARS = 3
# ...and one matching loc is a coincidence. The prefix below is derived from AGREEMENT
# between locs, so it needs at least two of them to be agreement at all.
_MIN_SITEMAP_MATCHES = 2
# What may sit either side of an id inside a URL. Walmart's job pages are
# ``/us/en/jobs/R-1075582-senior-software-engineer`` — the id ends at a hyphen, so a
# bare substring test is right and an "id is a whole path segment" test is wrong.
_ID_BOUNDARY = re.compile(r"[^A-Za-z0-9]")


@dataclass(frozen=True)
class SitemapMatch:
    """The board, as its own sitemap enumerates it.

    ``url_pattern`` is a PREFIX and is used as a substring test, which is exactly what
    ``recipe_runner._oracle_sitemap`` does with it. It is derived from the locs that
    carry ids we actually captured, so it is a statement the board made about itself and
    not a shape anybody guessed.
    """

    sitemap_url: str
    url_pattern: str
    loc_count: int
    matched_ids: frozenset[str]


def _bounded_index(loc: str, job_id: str) -> int:
    """Where ``job_id`` sits in ``loc`` as a whole token, or ``-1``.

    Bounded on BOTH sides by a non-alphanumeric character, which is what stops the id
    ``107`` from "matching" inside ``R-1075582`` and manufacturing a claim about a board
    out of a coincidence. Every occurrence is tried, not only the first: an id can
    legitimately appear once unbounded (inside a longer requisition number) and once
    bounded (as the job's own segment) in the same URL.
    """
    at = loc.find(job_id)
    while at >= 0:
        after = at + len(job_id)
        before_ok = at == 0 or bool(_ID_BOUNDARY.match(loc[at - 1]))
        after_ok = after >= len(loc) or bool(_ID_BOUNDARY.match(loc[after]))
        if before_ok and after_ok:
            return at
        at = loc.find(job_id, at + 1)
    return -1


def _prefix_before(loc: str, index: int) -> str:
    """Everything up to and including the last ``/`` before ``index``."""
    cut = loc.rfind("/", 0, index)
    return loc[: cut + 1] if cut > 0 else ""


def sitemap_match(
    evidence: WellKnownEvidence, ids: set[str]
) -> SitemapMatch | None:
    """Which sitemap enumerates THESE jobs, and how many pages it lists like them.

    Deterministic, no model, no network. For each captured job id, find the ``<loc>``
    entries that carry it, take the URL prefix each one sits under, and keep the prefix
    the most locs AGREE on: Walmart's 10 captured ids all land under
    ``https://careers.walmart.com/us/en/jobs/``, and 15,660 of its 16,210 locs start
    with it.

    ``None`` when nothing lines up — no sitemap, no id in any loc, or fewer than
    :data:`_MIN_SITEMAP_MATCHES` agreeing. That is the silent-miss path and it is the
    common one.
    """
    usable = {i for i in ids if isinstance(i, str) and len(i) >= _MIN_SITEMAP_ID_CHARS}
    if not usable:
        return None
    best: SitemapMatch | None = None
    for doc in evidence.sitemaps:
        if doc.is_index or not doc.locs:
            continue
        prefixes: dict[str, set[str]] = {}
        for loc in doc.locs:
            for job_id in usable:
                at = _bounded_index(loc, job_id)
                if at < 0:
                    continue
                prefix = _prefix_before(loc, at)
                if prefix:
                    prefixes.setdefault(prefix, set()).add(job_id)
                break
        if not prefixes:
            continue
        pattern, matched = max(prefixes.items(), key=lambda kv: (len(kv[1]), len(kv[0])))
        if len(matched) < _MIN_SITEMAP_MATCHES:
            continue
        count = sum(1 for loc in doc.locs if pattern in loc)
        candidate = SitemapMatch(
            sitemap_url=doc.url, url_pattern=pattern, loc_count=count,
            matched_ids=frozenset(matched),
        )
        if best is None or candidate.loc_count > best.loc_count:
            best = candidate
    return best


# --------------------------------------------------------------------------
# sources 2 and 6 — the document as a candidate
# --------------------------------------------------------------------------

# How many document-derived candidates may join the list the model is shown. Two, and
# they go on the END: a board that publishes a real jobs XHR must never have its answer
# crowded out by a marketing page's ld+json, and the JSON candidates were ranked by the
# pre-filter for exactly that reason.
_MAX_HTML_CANDIDATES = 2

# The smallest number of same-shaped job anchors in a SERVED document that is worth
# calling a job list. A page's own navigation is the false positive this bounds, so it is
# bounded twice: this count, and the requirement below that the path they share reads as
# a jobs path.
_MIN_HTML_RECORDS = 8

# ...and the second bound. The anchors must sit under a path that SAYS jobs. A nav menu
# under ``/company/`` is the shape this excludes; a board whose job URLs carry none of
# these words is missed, silently, which is the safe direction.
_JOB_PATH_HINTS = ("job", "career", "position", "opening", "vacanc", "role", "opportunit")

# The field map an anchor-derived candidate uses, and it is FIXED, never asked of a
# model: an ``<a href>`` carries exactly a link and a label. ``id`` is the raw href
# because that is what ``recipe_runner._run_css`` stores (it stringifies ``id`` and
# base-joins only ``url``), so the candidate's ids and the replay's ids are the same
# strings by construction — which is what the match-the-capture assertion compares.
_ANCHOR_FIELD_SELECTORS = {"id": ".@href", "title": ".@text", "url": ".@href"}


def island_sources(captured: Any) -> list[EvidenceSource]:
    """Every embedded island the child carried, typed by what it may contribute.

    The served/rendered split IS the contribution: an island in the served document is
    replayable by one GET plus one CSS selector, so it may carry records; an island that
    exists only after hydration is reproducible by no transport we admit, so it may
    carry ids and nothing else.
    """
    out: list[EvidenceSource] = []
    for island in getattr(captured, "islands", ()) or ():
        served = island.get("scope") == "served"
        out.append(EvidenceSource(
            kind="island",
            origin=(
                f"{getattr(captured, 'server_html_url', '') or getattr(captured, 'final_url', '')}"
                f" {island.get('selector', '')}"
            ).strip(),
            media="json",
            body=island.get("body", ""),
            contributions=(
                frozenset({"records", "oracle", "id_set"}) if served
                else frozenset({"id_set"})
            ),
            replay_transport="http_html" if served else None,
            note=f"{island.get('scope')} document, {island.get('selector')}",
        ))
    return out


def island_candidates(captured: Any, document_url: str) -> list[Any]:
    """SERVED islands, as ``Candidate``s the existing ladder can already read.

    A rendered-only island never reaches this function, and that is the whole rule: it
    has no replay transport, so it must not be able to become a stored recipe however
    job-shaped its contents are.
    """
    from .request_selector import Candidate, HtmlSource, _walk_record_arrays

    out: list[Any] = []
    for island in getattr(captured, "islands", ()) or ():
        if island.get("scope") != "served":
            continue
        try:
            payload = json.loads(island.get("body") or "", strict=False)
        except Exception:  # noqa: BLE001 - already parsed once in the child; be safe
            continue
        found: list[tuple[str, int, int, tuple[str, ...]]] = []
        _walk_record_arrays(payload, "", 0, found)
        if not found:
            continue
        path, count, score, keys = max(found, key=lambda t: (t[2], t[1]))
        out.append(Candidate(
            index=0,
            url=document_url,
            method="GET",
            request_headers={},
            post_data=None,
            payload=payload,
            records_path=path,
            record_count=count,
            job_score=score,
            sample_keys=keys,
            source_index=-1,
            html=HtmlSource(
                document_url=document_url,
                op="extract_embedded_island",
                selector=island.get("selector", ""),
                source=island.get("source", "text"),
                attribute=island.get("attribute", ""),
            ),
        ))
    return out


_ANCHOR_RE = re.compile(
    r"""(?is)<a\b[^>]*?\bhref\s*=\s*["']([^"'>\s]{1,400})["'][^>]*>(.*?)</a\s*>"""
)
_TAG_RE = re.compile(r"<[^>]+>")


def _anchor_rows(markup: str, board_host: str) -> dict[str, list[dict[str, str]]]:
    """Same-host anchors with visible text, grouped by the directory they share."""
    groups: dict[str, list[dict[str, str]]] = {}
    seen: set[str] = set()
    for href, inner in _ANCHOR_RE.findall(markup):
        text = " ".join(_TAG_RE.sub(" ", inner).split())
        if len(text) < 3 or href in seen:
            continue
        parts = urlsplit(href)
        if parts.netloc and (parts.hostname or "").lower() != board_host:
            continue
        directory = parts.path.rsplit("/", 1)[0] + "/"
        if len(directory) <= 1:
            continue
        seen.add(href)
        groups.setdefault(directory, []).append(
            {"id": href, "title": text, "url": href}
        )
    return groups


def anchor_candidate(captured: Any, board_host: str) -> Any | None:
    """SOURCE 6 — the served document's own job anchors, as one ``extract_css`` candidate.

    Wholly deterministic: no model is asked anything, because an ``<a href>`` carries
    exactly a link and a label and there is nothing to map. The candidate is still put
    through the normal ladder — the selector call can decline it, the acceptance replay
    has to reproduce it, the coverage floor still applies — so the derivation only ever
    PROPOSES, which is the same discipline the job-link derivations follow.

    Two bounds keep a page's own NAVIGATION out: at least :data:`_MIN_HTML_RECORDS`
    distinct anchors, and a shared path that reads as a jobs path. A board whose job URLs
    say none of those words is missed silently — the safe direction, and it costs nothing
    because that board's XHR candidates are unaffected.
    """
    from .request_selector import Candidate, HtmlSource

    markup = getattr(captured, "server_html", "") or ""
    document_url = (
        getattr(captured, "server_html_url", "")
        or getattr(captured, "final_url", "")
    )
    if not markup or not document_url:
        return None
    groups = _anchor_rows(markup, board_host)
    best: tuple[str, list[dict[str, str]]] | None = None
    for directory, rows in groups.items():
        if len(rows) < _MIN_HTML_RECORDS:
            continue
        if not any(hint in directory.lower() for hint in _JOB_PATH_HINTS):
            continue
        if best is None or len(rows) > len(best[1]):
            best = (directory, rows)
    if best is None:
        return None
    directory, rows = best
    return Candidate(
        index=0,
        url=document_url,
        method="GET",
        request_headers={},
        post_data=None,
        # A SYNTHETIC payload, so everything downstream — the prompt, the field-map
        # validation, ``_capture_ids``, the match-the-capture assertion — reads this
        # candidate exactly the way it reads a JSON one. The rows are built with the
        # same rule ``_run_css`` replays with, so the two id sets are equal by
        # construction rather than by hope.
        payload={"records": rows},
        records_path="records",
        record_count=len(rows),
        job_score=0,
        sample_keys=("id", "title", "url"),
        source_index=-1,
        html=HtmlSource(
            document_url=document_url,
            op="extract_css",
            selector=f'a[href*="{directory}"]',
            field_selectors=dict(_ANCHOR_FIELD_SELECTORS),
        ),
    )


def document_candidates(captured: Any, board_host: str, document_url: str) -> list[Any]:
    """Sources 2a and 6 together, capped, ranked most-job-shaped first.

    Capped at :data:`_MAX_HTML_CANDIDATES` and appended AFTER the pre-filter's own list
    by the caller, because a board that publishes a real jobs XHR must never have its
    answer crowded out by a marketing page's ld+json.
    """
    candidates = island_candidates(captured, document_url)
    candidates.sort(key=lambda c: (c.job_score, c.record_count), reverse=True)
    anchors = anchor_candidate(captured, board_host)
    if anchors is not None:
        candidates.append(anchors)
    return candidates[:_MAX_HTML_CANDIDATES]


__all__ = [
    "Contribution",
    "EvidenceSource",
    "SitemapDocument",
    "SitemapMatch",
    "WellKnownEvidence",
    "WellKnownFetch",
    "anchor_candidate",
    "collect_well_known",
    "document_candidates",
    "island_candidates",
    "island_sources",
    "parse_sitemap",
    "robots_sitemap_urls",
    "sitemap_match",
]
