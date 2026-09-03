"""Choose WHICH of the trusted careers results to offer — the list, not the poster.

``trusted_careers_urls`` answers "may we offer this at all?". This module answers
"which one", over exactly the set that filter already passed. It never widens that
set and never invents a host: everything here either reorders results the search
returned or derives a path prefix out of them.

THE BUG THIS EXISTS TO FIX. We used to offer the first trusted result in search
rank order, and search rank favours the page a human links to — the marketing
landing page — over the page a human uses. Typing "AMD" offered
``amd.com/en/corporate/careers.html``; typing "Airbnb" offered
``careers.airbnb.com/``. Neither has a job on it, so the user then spent a paid
discovery run on a page with nothing to find. Measured over a 28-company corpus of
real ``{company} careers`` results, first-by-rank lands on the company's real job
list **3 times out of 28**.

TWO MECHANISMS, IN THIS ORDER.

**Y — derive the list URL from the job URLs** (``derive_list_url`` +
``verify_list_url``). A search that never returns the list page still returns job
*detail* pages from it. Cluster those by the path immediately above their id
segment and you have constructed the list URL from data instead of guessing it.
Then prove it with ONE fetch: keep it only on a 200 that did not redirect away from
itself. Measured: fires for 7 of 28, correct 7/7, **zero** false positives — and
five of those seven (AMD, Pinterest, Zalando, Airbnb, Nintendo) are companies whose
real list URL never appears in the 25 results at all, so no ranker could ever have
reached them.

**T — the ranker, for when Y does not fire** (``rank_careers_results``). Score the
Exa *title*, which the old code ignored entirely, with the URL path as a tiebreak,
and drop URLs shaped like a single posting. The title is independent information:
SpaceX serves ``<title>SpaceX</title>`` on every page, while the search returns
"SpaceX - Jobs" and "SpaceX - Careers" as separate titles for separate URLs.

Together they land on the real job list **16 of 28**, against 3 for search rank and
11 for a word list alone. An LLM over the same (url, title) pairs scored 11 — worse
than this once Y is in, non-deterministic, billable per search, and it picked
Citadel *Securities* for "Citadel", which is the wrong-legal-entity failure the
whole name-matching layer exists to prevent.

EVERY FETCH FAILS OPEN. Tesla, Citadel, Epic Games and Dell all 403 a plain
request, and 90 of 364 own-domain results in the corpus were not 200 at all. A
verification that treated "not 200" as "reject the candidate" would throw away
every candidate on a Cloudflare-fronted careers site. So a failed fetch means only
that Y does not fire, and T decides — never that a result is discarded.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from urllib.parse import SplitResult, urlsplit, urlunsplit

import httpx

# Same-package private constant, imported rather than retyped so the two paths
# that fetch a user-supplied careers page cannot drift apart. The contact URL in
# the User-Agent is load-bearing — Intel's WAF 403s a bare product token — and we
# never impersonate a browser. See ``ats_discovery`` for the measurements.
from .ats_discovery import _DISCOVERY_HEADERS
from .url_guard import UrlGuardError, guarded_get

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CareersResult:
    """One search result that resolved to no board — a careers page candidate.

    Carries the search engine's ``title`` because that is half of what decides
    which page we offer, and the raw ``rank`` because search order is the honest
    fallback when nothing else separates two results.
    """

    url: str
    title: str
    #: 1-based place in the search engine's own ranking.
    rank: int


# ─────────────────────────────────────────────────────────────────────────────
# Structure: is this URL one posting, or a collection of them?
# ─────────────────────────────────────────────────────────────────────────────

# A path segment that is a RECORD ID rather than a word. Vocabulary-free on
# purpose: it recognises the *shape* of an identifier (a long number, optionally
# with a short vendor prefix; a UUID; a long hex blob), so it works on boards we
# have never seen. Both halves of the module need it — T drops these URLs, Y
# clusters on the segment immediately above them.
_ID_SEGMENT = re.compile(
    r"^(?:[A-Za-z]{0,3}[-_]?\d{4,}[A-Za-z0-9_-]*"
    r"|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"|[0-9a-f]{16,})$"
)


def _split(url: str) -> SplitResult | None:
    """``urlsplit`` that answers ``None`` instead of raising.

    These URLs come from a third party, and one unparseable result must cost that
    result and nothing else.
    """
    try:
        return urlsplit(url)
    except ValueError:
        return None


def _id_segment_indexes(url: str) -> list[int]:
    """Which path segments of ``url`` look like a record id (0-based)."""
    parts = _split(url)
    if parts is None:
        return []
    segments = [s for s in (parts.path or "/").split("/") if s]
    return [i for i, s in enumerate(segments) if _ID_SEGMENT.match(s)]


def is_single_posting_url(url: str) -> bool:
    """Does this URL address ONE job rather than a list of them?

    A structural test, not a vocabulary one. It is the only exclusion signal we
    need: JSON-LD ``JobPosting`` markup was measured to appear on single-job pages
    and never on lists, which makes it strictly redundant with this — and it costs
    a fetch, which this does not.
    """
    return bool(_id_segment_indexes(url))


# ─────────────────────────────────────────────────────────────────────────────
# T — the ranker
# ─────────────────────────────────────────────────────────────────────────────

# Word lists, scored against the URL PATH. First positive match wins (they are in
# descending specificity); every negative match applies. The weights are the ones
# measured over the corpus — they encode "a page whose path says `all-jobs` beats
# one whose path says `jobs`, and anything saying `life-at` is marketing".
_PATH_POSITIVE: tuple[tuple[str, float], ...] = (
    ("all-jobs", 10), ("alljobs", 10), ("search-results", 9), ("job-search", 9),
    ("search_jobs", 9), ("search-jobs", 9), ("openings", 8), ("open-roles", 8),
    ("openroles", 8), ("vacancies", 8), ("positions", 8), ("jobs", 7),
    ("search", 6), ("opportunities", 5), ("roles", 5),
)
_PATH_NEGATIVE: tuple[tuple[str, float], ...] = (
    ("home", -6), ("locations", -6), ("life-at", -8), ("lifeat", -8),
    ("benefits", -8), ("culture", -8), ("students", -6), ("intern", -6),
    ("graduates", -6), ("faq", -8), ("blog", -8), ("news", -8),
    ("how-we-hire", -8), ("teams", -4), ("early", -6), ("apply", -5),
)

# Word lists, scored against the SEARCH ENGINE'S title. Kept separate from the
# path lists because they are separate evidence: SpaceX serves the same
# ``<title>SpaceX</title>`` on every page, so only the search engine's title
# distinguishes "SpaceX - Jobs" from "SpaceX - Careers".
#
# The three hard negatives ("not found", "404", "error") are why T needs no
# liveness fetch of its own: 90 of the corpus's 364 own-domain results answered
# something other than 200, and the search engine's title for them literally reads
# "Page not found". A dead page announces itself for free.
_TITLE_POSITIVE: tuple[tuple[str, float], ...] = (
    ("all jobs", 10), ("open roles", 9), ("job openings", 9), ("open positions", 9),
    ("search jobs", 9), ("search for jobs", 9), ("job search", 9),
    ("view jobs", 9), ("search our job", 9), ("openings", 8), ("vacancies", 8),
    ("find your", 6), ("jobs", 5), ("search", 4),
)
_TITLE_NEGATIVE: tuple[tuple[str, float], ...] = (
    ("life at", -8), ("benefits", -8), ("how we", -8), ("culture", -8),
    ("intern", -6), ("student", -6), ("graduate", -6), ("early", -6),
    ("not found", -20), ("404", -20), ("error", -20), ("home", -5),
    ("overview", -5), ("apply", -4), ("faq", -8), ("locations", -6),
    (" in ", -8), (" at ", -3),
)

# An id in the LAST path segment, or a long number in the query string. Both say
# "one record", and both are softer than ``_ID_SEGMENT``: this is a penalty, not
# an exclusion, because a real list page can carry one (Pinterest's own job list
# came back as ``/jobs/?gh_jid=8088867``).
_ID_TAIL = re.compile(r"(?:^|[/\-_])(\d{4,}|[0-9a-f]{8}-[0-9a-f]{4})")
_QUERY_ID = re.compile(r"\d{4,}")


def path_score(url: str) -> float:
    """How much this URL's PATH looks like a job list."""
    parts = _split(url)
    if parts is None:
        return 0.0
    path = (parts.path or "/").lower()
    score = 0.0
    for word, value in _PATH_POSITIVE:
        if word in path:
            score += value
            break
    for word, value in _PATH_NEGATIVE:
        if word in path:
            score += value
    tail = path.rstrip("/").split("/")[-1]
    if _ID_TAIL.search(tail):
        score -= 12
    if parts.query and _QUERY_ID.search(parts.query):
        score -= 6
    # A shallow path beats a deep one at equal wording: `/careers/jobs` is the
    # list, `/careers/jobs/engineering/emea` is a slice of it.
    score -= 0.1 * len(path.strip("/").split("/"))
    return score


def title_score(title: str) -> float:
    """How much the search engine's TITLE for this result looks like a job list."""
    text = (title or "").lower()
    score = 0.0
    for word, value in _TITLE_POSITIVE:
        if word in text:
            score += value
            break
    for word, value in _TITLE_NEGATIVE:
        if word in text:
            score += value
    return score


def rank_careers_results(rows: Sequence[CareersResult]) -> list[CareersResult]:
    """Best first: title, then path, then the search engine's own order.

    SINGLE POSTINGS ARE DROPPED, not demoted. Offering one spends a paid discovery
    run on a page with exactly one job on it, which is a worse answer than "we
    found nothing you can use" — and the UI already knows how to say the second
    one. If that empties the list, the caller offers nothing from this source.

    Ties fall through to ``rank``, so when nothing scores — every result equally
    wordless — this returns the search engine's order unchanged, which is exactly
    the behaviour it is replacing.
    """
    keep = [row for row in rows if not is_single_posting_url(row.url)]
    return sorted(
        keep, key=lambda row: (-title_score(row.title), -path_score(row.url), row.rank)
    )


# ─────────────────────────────────────────────────────────────────────────────
# Y — derive the list URL from the job URLs, then verify it
# ─────────────────────────────────────────────────────────────────────────────

# How many job-detail URLs must agree on a parent before we believe it is a list.
# Two, because one detail page is an anecdote — a single `/careers/jobs/12345`
# tells you nothing about whether `/careers/jobs` exists — while two independent
# results sharing a parent is the board's own URL scheme showing through.
_MIN_CLUSTER = 2

# The verification fetch. Small numbers on purpose: the acceptance rule reads the
# status line and the final URL, so the body is only ever incidental.
_VERIFY_TIMEOUT_S = 6.0
_VERIFY_MAX_HOPS = 5
_VERIFY_MAX_BYTES = 65_536


def derive_list_url(rows: Sequence[CareersResult]) -> str | None:
    """The path immediately above the biggest cluster of job-detail URLs.

    Returns a URL that is *constructed*, not chosen — but constructed only from
    scheme, host and path segments the search results themselves contained. No
    suffix is ever appended and no host is ever guessed, so the worst case is a
    prefix of somebody's real URL, which the verification fetch then refuses.

    ``None`` when fewer than ``_MIN_CLUSTER`` results agree, which is the common
    case: the corpus derives a candidate for 15 of 28 companies and 7 survive
    verification.
    """
    clusters: Counter[tuple[str, str, str]] = Counter()
    for row in rows:
        id_indexes = _id_segment_indexes(row.url)
        # `[0] == 0` means the id is the FIRST segment, so there is no path above
        # it to derive — the parent would be the bare host.
        if not id_indexes or id_indexes[0] == 0:
            continue
        parts = _split(row.url)
        if parts is None:  # pragma: no cover - _id_segment_indexes already parsed it
            continue
        segments = [s for s in (parts.path or "/").split("/") if s]
        parent = "/" + "/".join(segments[: id_indexes[0]])
        clusters[(parts.scheme, parts.netloc, parent)] += 1
    if not clusters:
        return None
    # `most_common` breaks ties by insertion order, so an even split is decided by
    # search rank — deterministic, and the same answer on every replay.
    (scheme, netloc, parent), count = clusters.most_common(1)[0]
    if count < _MIN_CLUSTER:
        return None
    return urlunsplit((scheme, netloc, parent, "", ""))


def _stayed_put(requested: str, final: str) -> bool:
    """Did the fetch end up on the page we asked for, rather than somewhere else?

    Same host, and a final path that still starts with the one we asked for. This
    is what rejects the three ways a derived URL is wrong in the corpus: Walmart's
    ``/us/en/jobs`` bounces to ``/us/en/home``, Jane Street's ``/apply`` bounces to
    ``/open-roles``, and Microsoft's ``jobs.careers.microsoft.com`` bounces to a
    different host entirely.

    The prefix is deliberately NOT segment-bounded. Riot Games' detail URLs sit
    under ``/en/work-with-us/job``, which the site itself redirects to
    ``/en/work-with-us/jobs`` — their real job list. Requiring a ``/`` after the
    prefix would reject that, and it was measured correct.
    """
    start, end = _split(requested), _split(final)
    if start is None or end is None:
        return False
    if start.netloc.lower() != end.netloc.lower():
        return False
    return end.path.rstrip("/").startswith(start.path.rstrip("/"))


async def verify_list_url(
    url: str,
    http: httpx.AsyncClient,
    *,
    deadline: float | None = None,
    timeout: float = _VERIFY_TIMEOUT_S,
) -> str | None:
    """Fetch ``url`` once. Return where it landed if it is real, else ``None``.

    Kept only on a 200 that did not redirect away from itself (``_stayed_put``).
    The URL returned is the FINAL one — verified, and one redirect cheaper for
    whatever discovery run the user starts from it.

    FAIL OPEN, ALWAYS. Every failure — refused by the SSRF guard, 403, timeout,
    unparseable — is ``None``, meaning "Y does not fire", never "this candidate is
    bad". ``guarded_get`` is used because this is a URL derived from third-party
    search results, so it gets the same per-hop SSRF revalidation and the same
    bounded body as everything else a user can point us at.
    """
    try:
        response, hops = await guarded_get(
            url,
            http,
            max_hops=_VERIFY_MAX_HOPS,
            max_bytes=_VERIFY_MAX_BYTES,
            # Follow a hop off-host so we can SEE that it left and reject it
            # ourselves; refusing at the guard would be the same verdict reached
            # with less to log.
            allow_cross_host=True,
            # We asked for `identity` and do not need the body; this only means an
            # origin that compresses anyway still gets verified rather than
            # refused. `_VERIFY_MAX_BYTES` bounds the decoded size either way.
            allow_compressed=True,
            headers=_DISCOVERY_HEADERS,
            timeout=timeout,
            deadline=deadline,
        )
    except (UrlGuardError, httpx.HTTPError, UnicodeError) as exc:
        logger.info("Derived careers list %s did not verify: %s", url, exc)
        return None

    requested = hops[0] if hops else url
    final_url = hops[-1] if hops else url
    if response.status_code != 200 or not _stayed_put(requested, final_url):
        logger.info(
            "Derived careers list %s did not verify: HTTP %d at %s",
            url, response.status_code, final_url,
        )
        return None
    return final_url


async def pick_careers_url(
    rows: Sequence[CareersResult],
    http: httpx.AsyncClient,
    *,
    is_trusted: Callable[[str], bool],
    deadline: float | None = None,
) -> str | None:
    """The one careers URL to offer, or ``None``. Y first, then T.

    ``is_trusted`` is the caller's own host filter (``trusted_careers_urls``),
    applied to the DERIVED URL before it is fetched. ``rows`` have already passed
    it; the derived URL is new, so it has to pass it too — and it is asked before
    the fetch, so a host we would never offer is never contacted either.

    At most ONE outbound request, and only when Y has something to verify.
    """
    derived = derive_list_url(rows)
    if derived is not None and is_trusted(derived):
        verified = await verify_list_url(derived, http, deadline=deadline)
        if verified is not None:
            logger.info("Derived careers list %s verified as %s", derived, verified)
            return verified

    ranked = rank_careers_results(rows)
    return ranked[0].url if ranked else None
