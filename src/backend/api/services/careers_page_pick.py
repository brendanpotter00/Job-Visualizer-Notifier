"""Choose WHICH of the trusted careers results to offer — the list, not the poster.

``trusted_careers_urls`` answers "may we offer this at all?". This module answers
"which one", over exactly the set that filter already passed. It never invents a
URL: everything here either reorders results the search returned, derives a path
prefix out of them, or reads an ``href`` off one of their pages — and every
constructed or harvested URL is put back through the caller's host filter before it
can be offered or even contacted.

THE BUG THIS EXISTS TO FIX. We used to offer the first trusted result in search
rank order, and search rank favours the page a human links to — the marketing
landing page — over the page a human uses. Typing "AMD" offered
``amd.com/en/corporate/careers.html``; typing "Airbnb" offered
``careers.airbnb.com/``. Neither has a job on it, so the user then spent a paid
discovery run on a page with nothing to find. Measured over a 28-company corpus of
real ``{company} careers`` results, first-by-rank lands on the company's real job
list **3 times out of 28**.

THE BAR IS "IS IT A JOB LIST", NOT "IS IT THEIRS" — and that is a correction, not
a refinement. ``CAREERS-FALLBACK-POC.md`` §Q3, which this module was built from,
scored an answer correct when its host named the company, because the failure it
was written against was offering ``resumeadapter.com`` for Oracle. Under that
criterion ``www.oracle.com/careers/`` is a *pass*: Oracle's own domain, Oracle's
own careers page, no jobs on it. So the POC's own ground truth recorded a
marketing page as the right answer for Oracle, and the "16 of 28" it produced was
counting brochures. ``is_job_list_url`` is the corrected criterion, applied to
everything before it may be offered; the host filter it does not replace
(``trusted_careers_urls``) is now necessary and no longer sufficient. Re-scored
against "does this URL demonstrably lead to postings" — each answer loaded in a real
browser, job-detail links counted — these mechanisms offer a URL for 22 of 28 and
**21 of those 22 are a real job list**, against 18 of 28 for the code they replace,
which also handed out **10** pages with no job on them. See the module's tests and
``CAREERS-FALLBACK-POC.md``'s correction header.

THREE MECHANISMS, IN THIS ORDER.

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
"SpaceX - Jobs" and "SpaceX - Careers" as separate titles for separate URLs. It
now picks the best row that is a job LIST, so when every trusted result is a
brochure it picks nothing and Z gets the fetch.

**Z — read the careers page and take the link it publishes** (``follow_to_job_list``).
For the class of company where the real board is on a *different host* to the
careers page, search returns the careers page and never the board: Oracle's
``careers.oracle.com/en/sites/jobsearch/jobs`` appears nowhere in the 25 results,
not even as a job detail URL, so T has nothing to rank and Y has nothing to
cluster. It is *absent*, and the only place it exists is in the HTML of
``www.oracle.com/careers/``, which links to it three times under the words "Search
jobs". One fetch of the page we would otherwise have offered, and the company tells
us where its board is.

Together they land on the real job list **21 of 28**, against 3 for search rank and
11 for a word list alone. An LLM over the same (url, title) pairs scored 11 — worse
than this once Y is in, non-deterministic, billable per search, and it picked
Citadel *Securities* for "Citadel", which is the wrong-legal-entity failure the
whole name-matching layer exists to prevent.

NOTHING IS A REAL ANSWER. When no mechanism produces a job list, this returns
``None`` and the UI asks the user to paste a URL. That is strictly better than the
best of a bad set: offering ``facebook.it/careers/`` for "Facebook" — a different
company's site that passes the host rule on a country-code TLD — spends a paid
discovery run and one of the user's twenty monthly adds on a stranger.

STILL OPEN, AND NOT THIS MODULE'S TO CLOSE. The host filter accepts a label that
merely *extends* the typed name, which is what lets "Meta" reach ``metacareers.com``
and "Pinterest" reach ``pinterestcareers.com`` — and, on the same rule, lets
"Citadel" reach ``citadelsecurities.com``, a different legal entity. Measured
2026-09-04: Citadel is the one company in the 28 where the URL offered is a
different company's. Separating "extends with a recruiting word" from "extends into
another company's name" is a change to ``_host_owner`` in ``company_name_search``,
not to the picker, and `metabase.com` for "Meta" is the same hole recorded open in
``CAREERS-FALLBACK-POC.md``.

EVERY FETCH FAILS OPEN. Tesla, Citadel, Epic Games and Dell all 403 a plain
request, and 90 of 364 own-domain results in the corpus were not 200 at all. A
verification that treated "not 200" as "reject the candidate" would throw away
every candidate on a Cloudflare-fronted careers site. So a failed fetch means only
that Y does not fire, and T decides — never that a result is discarded.
"""

from __future__ import annotations

import html as html_module
import logging
import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from urllib.parse import SplitResult, parse_qsl, urljoin, urlsplit, urlunsplit

import httpx

# Same-package private constant, imported rather than retyped so the two paths
# that fetch a user-supplied careers page cannot drift apart. The contact URL in
# the User-Agent is load-bearing — Intel's WAF 403s a bare product token — and we
# never impersonate a browser. See ``ats_discovery`` for the measurements.
from .ats_discovery import _DISCOVERY_HEADERS

# The pure L0 resolver, used here for ONE question only: does this URL's query
# name a board? See ``unscoped_variant``.
from .ats_link_resolver import resolve_ats_url
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


# A path segment that means "a collection of open roles" rather than "a page about
# working here". A CLOSED vocabulary of LIST words, and the omissions are the
# point: `careers`, `company`, `about`, `life-at`, `working-here` are absent
# because those are exactly what a brochure's URL is made of. `www.oracle.com/
# careers/` has to fail this, and it does; `careers.oracle.com/en/sites/jobsearch/
# jobs` earns its pass from `jobsearch` and `jobs`, not from its host.
#
# SHARED, DELIBERATELY, with `is_job_list_shaped` in
# `e2e/company-name-search/intent_test.py`. That suite refuses to record a careers
# URL as ground truth unless it passes this same rule, so the two vocabularies are
# one rule with two implementations and must be changed together. This copy is the
# STRICTER of the two — it reads the last segment only — so everything it offers
# the suite also accepts; see `is_job_list_url`.
_JOB_LIST_SEGMENT = re.compile(
    r"^(?:"
    r"jobs?|job[-_]?search|jobsearch|job[-_]?listings?|joblist"
    r"|all[-_]?jobs|open[-_]?jobs|job[-_]?openings|openings"
    r"|open[-_]?roles|roles|open[-_]?positions|positions|vacancies"
    r"|opportunities|open[-_]?opportunities|search|search[-_]?results"
    # Not in the intent test's copy, and a deliberate widening rather than a
    # drift: `search-jobs` / `search_jobs` is the reverse spelling of
    # `job-search` and is what Disney and Dell call their real list
    # (`jobs.disneycareers.com/search-jobs`). Widening can only ever offer a
    # real list the narrower rule would have withheld — it cannot let a
    # brochure through, because no brochure's path ends in these words.
    r"|search[-_]?jobs"
    r")$"
)

# Stripped before the segment test, so `careers.html` is judged as `careers` — a
# brochure does not become a job list by wearing a file extension.
_PAGE_EXTENSION = re.compile(r"\.(?:html?|aspx|php|jsp)$", re.IGNORECASE)

# A host whose FIRST LABEL already says the whole site is the job list, so the list
# may legitimately sit at `/` — `jobs.zalando.com`, `job-boards.greenhouse.io`.
# `careers` is deliberately absent: `careers.airbnb.com/` and
# `www.oracle.com/careers/` are the brochures this rule exists to reject.
_JOB_LIST_HOST_LABEL = re.compile(r"^(?:jobs?|job[-_]boards?|jobsearch|joblist|apply)$")


def is_job_list_url(url: str) -> bool:
    """Does this URL claim to be a LIST OF OPEN ROLES rather than a page about them?

    THE OFFER BAR. Whatever we hand back is put behind a button that spends a paid
    discovery run, and a brochure has nothing to discover — so "on the company's own
    domain" is necessary and no longer sufficient. ``trusted_careers_urls`` answers
    "is this theirs?"; this answers "is it a job list?", and a candidate has to pass
    both to be offered at all.

    THIS IS AN OBJECTIVE CHANGE, not a bug fix, and it invalidates a number.
    ``CAREERS-FALLBACK-POC.md`` §Q3 scored an answer correct when its host named the
    company, because the failure it was written against was offering
    ``resumeadapter.com`` for Oracle. Under that rule ``www.oracle.com/careers/`` is
    a pass — it is on Oracle's domain — and Oracle was recorded as a success while
    the user was being handed a marketing page. The POC's findings about MECHANISM
    survive (a liveness fetch cannot tell a list from a brochure on a JS-rendered
    site; asking for 25 results rather than 5 buys one company). Its LABELS and the
    16/28 that rests on them do not.

    STRUCTURAL, not content-based. The alternative — fetch the page and look for
    jobs on it — cannot work here: every board that matters renders its list in
    JavaScript, so the HTML of ``careers.oracle.com/…/jobs`` contains no more job
    text than ``oracle.com/careers/`` does. The URL is the only honest signal
    available inside one request.
    """
    parts = _split(url)
    if parts is None:
        return False
    segments = [s for s in (parts.path or "").split("/") if s]
    if not segments:
        # Nothing but a host to judge, so the host has to carry it: `jobs.sap.com/`
        # really is the list. `careers.homedepot.com/` and `careers.airbnb.com/`
        # are not, which is why `careers` is not a job-list label.
        host = (parts.netloc or "").lower().split(":")[0].removeprefix("www.")
        return bool(_JOB_LIST_HOST_LABEL.match(host.split(".")[0] if host else ""))
    # THE LAST SEGMENT, not any segment, and Oracle is the whole reason. A list
    # word anywhere in the path also matches `oracle.com/careers/opportunities/
    # engineering-development/` — a brochure about engineering roles, sitting under
    # a directory named `opportunities`. What comes after the list word is what the
    # page is ABOUT: `…/careers/all-jobs` is the list, `…/opportunities/support` is
    # an article. A trailing slash is not a segment and does not change the answer.
    return bool(
        _JOB_LIST_SEGMENT.match(_PAGE_EXTENSION.sub("", segments[-1]).lower())
    )


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


def _phrase(word: str) -> re.Pattern[str]:
    """``word`` as a whole phrase, not as a substring of a longer word.

    Titles are WORDS, and a substring test reads them wrong in a way that changes
    answers: Meta's research page offers two links to the same board, "Jobs" →
    ``/jobsearch/`` and "View full-time research jobs" → ``/jobsearch/?teams[0]=…``,
    and "re|search jobs" contains the phrase "search jobs", so the filtered slice
    scored 9 against the whole list's 5 and won. The path lists keep plain
    ``in`` because a URL path is not a sentence — ``/jobsearch/`` really does mean
    jobs — but a title has spaces and they mean something.
    """
    return re.compile(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])")


_TITLE_POSITIVE_RE = tuple((_phrase(w), v) for w, v in _TITLE_POSITIVE)
_TITLE_NEGATIVE_RE = tuple((_phrase(w), v) for w, v in _TITLE_NEGATIVE)


def title_score(title: str) -> float:
    """How much the search engine's TITLE for this result looks like a job list."""
    text = (title or "").lower()
    score = 0.0
    for pattern, value in _TITLE_POSITIVE_RE:
        if pattern.search(text):
            score += value
            break
    for pattern, value in _TITLE_NEGATIVE_RE:
        if pattern.search(text):
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


@dataclass(frozen=True)
class _Page:
    """One page read: what it answered, where it ended up, and what it said.

    The BODY rides along even for the verification fetch, because one request has
    to serve two questions — "is the derived URL real?" and, when it is not, "does
    this page link to the real one?". See ``best_job_list_link``.
    """

    status: int
    #: The FINAL url after redirects — what relative links resolve against.
    url: str
    body: str


async def _read_page(
    url: str,
    http: httpx.AsyncClient,
    *,
    deadline: float | None = None,
    timeout: float = _VERIFY_TIMEOUT_S,
    max_bytes: int = _VERIFY_MAX_BYTES,
) -> _Page | None:
    """GET ``url`` once, guarded and bounded. ``None`` only if it could not be read.

    A NON-200 IS STILL A PAGE, and is returned rather than swallowed: the caller
    decides what a 410 means, and eBay's 410 is a 90 KB page with the right link on
    it. ``None`` is reserved for "there is no response at all" — a refusal from the
    SSRF guard, a timeout, a transport error.

    THE SECOND USER-AGENT SPELLING happens here and only on ``_AGENT_REFUSED``; see
    ``_HARVEST_HEADERS`` for the measurement that makes two spellings necessary.
    """
    response = None
    hops: tuple[str, ...] = ()
    for headers in _HARVEST_HEADERS:
        try:
            response, hops = await guarded_get(
                url,
                http,
                max_hops=_VERIFY_MAX_HOPS,
                max_bytes=max_bytes,
                # Follow a hop off-host so we can SEE that it left and reject it
                # ourselves; refusing at the guard would be the same verdict
                # reached with less to log.
                allow_cross_host=True,
                # We asked for `identity`; this only means an origin that
                # compresses anyway is read rather than refused. `max_bytes`
                # bounds the decoded size either way.
                allow_compressed=True,
                headers=headers,
                timeout=timeout,
                deadline=deadline,
            )
        except (UrlGuardError, httpx.HTTPError, UnicodeError) as exc:
            logger.info("Careers page %s could not be read: %s", url, exc)
            return None
        if response.status_code not in _AGENT_REFUSED:
            break
        logger.info(
            "Careers page %s answered HTTP %d; retrying as %r",
            url, response.status_code, _BARE_AGENT,
        )
    if response is None:  # pragma: no cover - the loop body always assigns or returns
        return None
    return _Page(
        status=response.status_code,
        url=hops[-1] if hops else url,
        body=response.text,
    )


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
    page = await _read_page(url, http, deadline=deadline, timeout=timeout)
    return None if page is None else _verified_url(url, page)


def _verified_url(requested: str, page: _Page) -> str | None:
    """``page``'s final URL if the fetch proved ``requested`` is a live list."""
    if page.status != 200 or not _stayed_put(requested, page.url):
        logger.info(
            "Derived careers list %s did not verify: HTTP %d at %s",
            requested, page.status, page.url,
        )
        return None
    return page.url


# ─────────────────────────────────────────────────────────────────────────────
# Z — ask the careers page itself where its job board is
# ─────────────────────────────────────────────────────────────────────────────

# The page is read, not just status-checked, so it gets the cap `ats_discovery`
# uses for exactly this ("fetch a careers page and scan it"), not the small one
# `verify_list_url` uses for a page whose body it never looks at.
_HARVEST_MAX_BYTES = 1024 * 1024
_HARVEST_TIMEOUT_S = 8.0

# TWO SPELLINGS OF THE SAME IDENTITY, and we need both. Measured 2026-09-04 with
# httpx, holding every other header constant:
#
#   User-Agent                                          oracle.com  jobs.intel.com
#   ``Job-Visualizer-Notifier/1.0 (+https://…)``           403           200
#   ``Job-Visualizer-Notifier/1.0``                        200           403
#   ``…/1.0 (onesecondswe.dev)`` (no scheme)               200           403
#   ``…/1.0 (https://onesecondswe.dev)`` (no ``+``)        403           200
#
# Perfectly anti-correlated: Oracle's WAF refuses any agent string containing a
# URL, Intel's refuses a bare product token, and no single string satisfies both.
# So the SECOND spelling is tried once, and only when the first was refused
# outright — the same page, one more time, saying who we are the other way. We
# still never claim to be a browser, and a site that answers the first spelling
# (all of them but Oracle, in the corpus) costs exactly one request as before.
#
# Derived from the shared header rather than retyped, so the identity has one
# source and the two spellings cannot drift into two different bots.
_BARE_AGENT = _DISCOVERY_HEADERS["User-Agent"].split(" (", 1)[0]
_HARVEST_HEADERS: tuple[dict[str, str], ...] = (
    _DISCOVERY_HEADERS,
    {**_DISCOVERY_HEADERS, "User-Agent": _BARE_AGENT},
)

# Statuses that mean "we did not like your request", as opposed to "there is
# nothing here". Only these earn the second spelling; a 404 or a 500 is an answer.
_AGENT_REFUSED = frozenset({401, 403, 406, 429})

# A host a company stands up FOR RECRUITING — `careers.oracle.com`,
# `jobs.apple.com`, `www.github.careers`, `metacareers.com`. Searched over the
# whole host rather than matched per label, because the word is as often glued on
# (`metacareers`, `pinterestcareers`) as it is a label of its own.
#
# THE STRONGEST SIGNAL A HARVESTED LINK CARRIES, and the only one that separates
# Apple's two links. Its design brochure offers "Search apple.com" →
# `apple.com/us/search` and "Search Roles" → `jobs.apple.com/en-us/search`: same
# words, same path shape, same (empty) query, and the first one is a product
# search that has never had a job on it. What tells them apart is that one link
# leaves the corporate site for the recruiting site and the other does not.
_RECRUITING_HOST = re.compile(r"job|career|recruit|talent|hiring")

# Anchors, scanned as text. No HTML parser, for the reason `ats_discovery` gives:
# BeautifulSoup is a heavier dependency than a body scan needs, and a malformed
# document must cost one link rather than raise.
_ANCHOR = re.compile(r"<a\b([^>]{0,2000}?)>(.{0,4000}?)</a>", re.IGNORECASE | re.DOTALL)
_HREF = re.compile(
    r"""\bhref\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.IGNORECASE
)
_LABEL_ATTR = re.compile(
    r"""\b(?:aria-label|title)\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE
)
_TAG = re.compile(r"<[^>]*>")
_WHITESPACE = re.compile(r"\s+")

# A page with more anchors than this is a sitemap, not a careers page, and we stop
# reading it rather than score ten thousand links.
_MAX_ANCHORS = 2_000


def _anchor_text(inner: str, attrs: str) -> str:
    """The words a human sees on a link — its text, else its accessible label.

    The link text is the same KIND of evidence as the search engine's title, which
    is why it is scored with ``title_score`` rather than a second word list: Oracle's
    careers page offers ``/en/sites/jobsearch/jobs`` under "Search jobs" and
    ``/en/sites/jobsearch/join-talent-community`` under "Join our network", and both
    paths contain the substring ``jobs``. The path cannot separate them; the words
    can.
    """
    text = _WHITESPACE.sub(" ", html_module.unescape(_TAG.sub(" ", inner))).strip()
    if text:
        return text[:120]
    label = _LABEL_ATTR.search(attrs)
    if label is None:
        return ""
    return _WHITESPACE.sub(
        " ", html_module.unescape(label.group(1) or label.group(2) or "")
    ).strip()[:120]


def _query_length(url: str) -> int:
    """How much of this URL is filters. Unparseable sorts last, not first."""
    parts = _split(url)
    return len(parts.query) if parts is not None else 1_000


def _is_recruiting_host(url: str) -> bool:
    """Is this URL on a host the company runs for hiring, not for its product?"""
    parts = _split(url)
    if parts is None:
        return False
    return bool(_RECRUITING_HOST.search((parts.netloc or "").lower()))


def harvest_job_list_links(body: str, base_url: str) -> list[tuple[str, str]]:
    """Every ``(url, link text)`` on this page that is shaped like a job list.

    Resolved against ``base_url`` — the page's FINAL url, so a link harvested after
    a redirect belongs to the host we actually landed on — and returned in document
    order, which is the honest tiebreak when two links score the same.

    Nothing is invented: every URL here is one the page itself published. No suffix
    is appended, no host is guessed, and a page that links to no job list yields an
    empty list rather than a constructed one.
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for count, match in enumerate(_ANCHOR.finditer(body)):
        if count >= _MAX_ANCHORS:
            break
        href_match = _HREF.search(match.group(1))
        if href_match is None:
            continue
        href = (
            href_match.group(1) or href_match.group(2) or href_match.group(3) or ""
        ).strip()
        if not href or href.startswith(("#", "mailto:", "javascript:", "tel:")):
            continue
        try:
            url = urljoin(base_url, html_module.unescape(href)).split("#")[0]
        except ValueError:
            continue
        parts = _split(url)
        if parts is None or parts.scheme not in ("http", "https"):
            continue
        if url in seen or not is_job_list_url(url) or is_single_posting_url(url):
            continue
        seen.add(url)
        out.append((url, _anchor_text(match.group(2), match.group(1))))
    return out


async def follow_to_job_list(
    page_url: str,
    http: httpx.AsyncClient,
    *,
    is_trusted: Callable[[str], bool],
    deadline: float | None = None,
) -> str | None:
    """Fetch ONE careers page and take the job-list link it publishes, if any.

    THE MECHANISM THAT REACHES A URL SEARCH NEVER RETURNED. Oracle's real board is
    ``careers.oracle.com/en/sites/jobsearch/jobs`` and it is not among the 25 results
    for "Oracle careers" — not the list page, not one job detail page under it,
    nothing. So the ranker cannot order its way to it and ``derive_list_url`` has no
    cluster to build it from: it is *absent*, and no amount of scoring the results we
    have can fix an answer that is not in them. What IS there is
    ``www.oracle.com/careers/``, and that page links to the board three times. The
    company's own careers page is the authority on where its job board lives, and
    reading it is the only source of a URL nobody searched up.

    THIS IS NOT A SUFFIX GUESS. Every candidate is an ``href`` the page published;
    the same rules that gate a search result gate it — ``is_trusted`` (the host must
    name the company) and ``is_job_list_url`` (it must be a list, not another
    brochure) — and a page with no such link yields ``None``.

    Best by link TEXT, then path, then document order: the same key
    ``rank_careers_results`` uses, because a link's words and a search result's title
    are the same kind of evidence.

    FAILS OPEN, like every other fetch here. 403, timeout, SSRF refusal, a body we
    cannot parse — all of them are ``None``, meaning "this did not find anything",
    never "the candidate is bad".
    """
    page = await _read_page(
        page_url,
        http,
        deadline=deadline,
        timeout=_HARVEST_TIMEOUT_S,
        max_bytes=_HARVEST_MAX_BYTES,
    )
    return None if page is None else best_job_list_link(page, is_trusted=is_trusted)


def best_job_list_link(
    page: _Page, *, is_trusted: Callable[[str], bool]
) -> str | None:
    """The job-list link this page publishes, or ``None``. Pure — no network.

    Split out from the fetch so ONE page read can serve both mechanisms: when Y's
    derived URL turns out not to be a list, the response we already hold is still
    a page on the company's site, and its links are still the answer. eBay is
    exactly that: the cluster derives ``jobs.ebayinc.com/us/en/job``, which answers
    HTTP 410 — but with a 90 KB page whose navigation links to
    ``/us/en/search-results``, eBay's real list. Throwing that body away to keep a
    tidy "verify, then separately follow" shape would cost a company for nothing.
    """
    links = [
        (url, text)
        for url, text in harvest_job_list_links(page.body, page.url)
        # Asked of the HARVESTED url, not the page's: a careers page is free to
        # link anywhere, and a job list on a host that does not name the company
        # is the `resumeadapter.com` failure arriving through a new door.
        if is_trusted(url)
    ]
    if not links:
        return None
    best = min(
        range(len(links)),
        key=lambda i: (
            not _is_recruiting_host(links[i][0]),
            -title_score(links[i][1]),
            -path_score(links[i][0]),
            # THE UNFILTERED LIST, when two links are the same list. Meta's
            # research page links to `metacareers.com/jobsearch/` ("Jobs") and to
            # `…/jobsearch/?teams[0]=University Grad - PhD & Postdoc&roles[0]=…`
            # ("View full-time research jobs") — identical words, identical path,
            # and the second one is a slice of the first. A query string is what
            # narrows a job list, so the shorter one is the whole of it. This is
            # the same "shallow beats deep" idea `path_score` applies to the path.
            _query_length(links[i][0]),
            i,
        ),
    )
    url, text = links[best]
    logger.info(
        "Careers page %s links to its job list %s (%r), of %d candidate link(s)",
        page.url, url, text, len(links),
    )
    return url


# ─────────────────────────────────────────────────────────────────────────────
# The query — does it NARROW this list, or does it NAME it?
# ─────────────────────────────────────────────────────────────────────────────

#: Query parameter names that SCOPE a job list: they select a subset of a page
#: that exists, and is the same page, without them. Compared after casefolding
#: and stripping non-alphanumerics, so ``locationId``, ``location_id`` and
#: ``location-id`` are one entry.
#:
#: DELIBERATELY A CLOSED LIST OF FILTER WORDS, and deliberately short. It has to
#: separate "narrows the results" from "says which board this is", and only one of
#: those two mistakes is cheap: dropping a filter that turns out to be an
#: identifier hands the user a URL with no jobs behind it. So the rule is that
#: EVERY parameter must be a known filter before any of them is dropped, and a
#: query with one unrecognised name is kept whole. Notably absent, and they are
#: the reason the list is a whitelist: ``for`` (Greenhouse's board token — see
#: ``_greenhouse_candidate``), ``domain`` (Eightfold's tenant), and anything else
#: that could be an id, a key or a company.
_SCOPE_PARAMS = frozenset({
    # where
    "location", "locations", "locationid", "locationids", "locationname",
    "loc", "city", "cities", "state", "province", "country", "countries",
    "region", "regions", "area", "areas", "radius", "distance",
    # which part of the company
    "department", "departments", "dept", "team", "teams", "division",
    "function", "functions", "discipline", "businessunit",
    # what kind of job
    "category", "categories", "jobcategory", "jobcategories", "jobfamily",
    "jobfield", "jobtype", "employmenttype", "worktype", "level", "seniority",
    # the site's own record of which filter chips are lit
    "facet", "facets", "lastselectedfacet", "selectedfacet",
})


def _param_name(raw: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", raw.lower())


def unscoped_variant(url: str) -> str | None:
    """The same page with a purely SCOPING query dropped, or ``None``. Pure.

    THE PROBLEM THIS SOLVES. Oracle's own careers page links to its job list three
    times, and every one of those links is
    ``careers.oracle.com/en/sites/jobsearch/jobs?location=United%20States&locationId=…``.
    Offer that and we build a **US-only scraper**: a stored recipe inherits its
    capture's filter scope — nothing later drops a query parameter — so the company
    is tracked at whatever slice of itself the link we happened to read was showing,
    and the system marks it ``partial``. The same path without the query is the same
    page and a superset of the jobs (measured 2026-09-04: HTTP 200, byte-identical
    shell), so it is the one to offer.

    ``None`` — meaning "keep the query" — for every case we cannot call, and the
    caller must treat it that way:

    * no query at all;
    * ANY parameter that is not a known filter (``_SCOPE_PARAMS``);
    * a query the ATS resolver reads as the board's IDENTITY. That last check is
      belt and braces over the whitelist: ``boards.greenhouse.io/embed/job_board/js
      ?for=acme`` *is* Acme's board and ``…/js`` alone is nobody's, and the day
      somebody adds an innocent-looking name to the list above, this refuses the
      rewrite anyway.
    """
    parts = _split(url)
    if parts is None or not parts.query:
        return None
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    if not pairs or not all(_param_name(key) in _SCOPE_PARAMS for key, _ in pairs):
        return None
    unscoped = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    if resolve_ats_url(url) is not None and resolve_ats_url(unscoped) is None:
        return None
    return unscoped


async def prefer_unscoped_list(
    url: str,
    http: httpx.AsyncClient,
    *,
    is_trusted: Callable[[str], bool],
    deadline: float | None = None,
) -> str:
    """``url`` with its scoping query dropped IF that page is really there.

    One extra fetch, and only for a URL whose query is entirely filter words —
    none of the eleven answers this suite offers today except Oracle's. It is the
    cheapest possible way to avoid tracking a company through a keyhole.

    THE UNSCOPED URL IS WHAT COMES BACK, not the fetch's final URL, and that is
    the one place this differs from ``verify_list_url``. A site that answers the
    bare list by redirecting to its own default filter would otherwise hand the
    scope straight back; we asked for the whole list, it answered 200 on the same
    page, and the whole list is what we offer.

    FAILS OPEN like every other fetch here: unreadable, non-200, or redirected
    somewhere else all mean "keep the URL we already had".
    """
    unscoped = unscoped_variant(url)
    # Asked of the REWRITTEN url before it is fetched, like every other URL this
    # module constructs — even though dropping a query cannot change the host.
    if unscoped is None or not is_trusted(unscoped):
        return url
    page = await _read_page(unscoped, http, deadline=deadline, timeout=_VERIFY_TIMEOUT_S)
    if page is None or _verified_url(unscoped, page) is None:
        logger.info("Kept the scoped list %s: %s is not a page of its own", url, unscoped)
        return url
    logger.info("Offering the whole list %s rather than the scoped %s", unscoped, url)
    return unscoped


async def pick_careers_url(
    rows: Sequence[CareersResult],
    http: httpx.AsyncClient,
    *,
    is_trusted: Callable[[str], bool],
    deadline: float | None = None,
) -> str | None:
    """The one careers URL to offer, or ``None``.

    ``_best_offer`` decides WHICH page (Y, then T, then Z — its docstring has the
    mechanism), and this adds the last rule on top of it: **offer the whole list,
    not a slice of it**. Oracle's careers page links only to the United States
    view of its job board, and a recipe captured through that link is a US-only
    scraper for a global company. See ``prefer_unscoped_list``.
    """
    chosen = await _best_offer(rows, http, is_trusted=is_trusted, deadline=deadline)
    if chosen is None:
        return None
    return await prefer_unscoped_list(
        chosen, http, is_trusted=is_trusted, deadline=deadline
    )


async def _best_offer(
    rows: Sequence[CareersResult],
    http: httpx.AsyncClient,
    *,
    is_trusted: Callable[[str], bool],
    deadline: float | None = None,
) -> str | None:
    """WHICH page to offer, or ``None``. Y, then T, then Z.

    The picker proper. ``pick_careers_url`` is the entry point and adds one rule
    after this one has chosen (offer the whole list, not a scoped view of it);
    everything about *which page* is here.

    ``is_trusted`` is the caller's own host filter (``trusted_careers_urls``). The
    ``rows`` have already passed it; every URL this function *constructs* or *reads
    off a page* is new, so each is asked again — and always before it is fetched, so
    a host we would never offer is never contacted either.

    EVERYTHING OFFERED MUST BE JOB-LIST-SHAPED (``is_job_list_url``). That gate is
    what turns "we would rather say nothing" from a slogan into behaviour: for
    ``Facebook`` the only trusted results are ``facebook.it/careers/`` and
    ``facebook.dk/careers/`` — a different company's site that passes the host rule
    on a country-code TLD — and for ``Poke`` they are a poke-bowl chain's ``/careers``
    pages. Under the old rule both were offered and both spent a user's discovery
    run. Now neither is a list, so neither is an answer.

    AT MOST ONE PAGE READ, and it answers two questions rather than one:

    1. **T** ranks what search returned and takes the best row that is a job list.
       Free, and the common case — it costs nothing and runs first whenever Y has
       no candidate worth proving.
    2. **Y** verifies a *derived* list URL, when the cluster produced one that is
       job-list shaped and trusted.
    3. **Z** reads the job-list link off whatever page that request returned —
       Y's derived URL if it did not verify, otherwise the best-ranked page,
       which is where the Oracle class is fixed.

    Steps 2 and 3 SHARE THE ONE REQUEST. eBay is why: the cluster derives
    ``jobs.ebayinc.com/us/en/job``, which answers 410 — and the body of that 410
    links to ``/us/en/search-results``, eBay's real list. A shape that fetched for
    Y and then declined to look at what came back would spend the budget and throw
    the answer away.
    """
    ranked = rank_careers_results(rows)
    listed = [row for row in ranked if is_job_list_url(row.url)]

    # Y's candidate, but only if it is something we could actually OFFER. A
    # derived URL that is not a job list is not worth a request: for `Meta` the
    # cluster derives `metacareers.com/profile/job_details`, and proving that page
    # exists would spend the fetch that finds `metacareers.com/jobsearch/`.
    derived = derive_list_url(rows)
    to_verify = (
        derived
        if derived is not None and is_job_list_url(derived) and is_trusted(derived)
        else None
    )

    # T answers for free. Pay only when it cannot, or when Y has something to prove.
    if to_verify is None and listed:
        return listed[0].url
    target = to_verify or (ranked[0].url if ranked else None)
    if target is None:
        return None

    page = await _read_page(
        target,
        http,
        deadline=deadline,
        timeout=_HARVEST_TIMEOUT_S,
        max_bytes=_HARVEST_MAX_BYTES,
    )
    if page is not None:
        if to_verify is not None:
            verified = _verified_url(target, page)
            if verified is not None and is_job_list_url(verified):
                logger.info("Derived careers list %s verified as %s", target, verified)
                return verified
        # Y did not verify, or there was nothing to verify. Either way we are
        # holding a page on the company's site — but only ask it where its board
        # is when SEARCH GAVE US NOTHING. A page's own links are weaker evidence
        # than a result the search engine ranked and we scored: Atlassian's
        # derived `join.atlassian.com/atlassian-talent-community/jobs` redirects
        # to a talent-community form, whose one job link is
        # `join.atlassian.com/jobs` — while `atlassian.com/company/careers/
        # all-jobs` was sitting in `listed` the whole time, for free.
        if not listed:
            followed = best_job_list_link(page, is_trusted=is_trusted)
            if followed is not None:
                return followed

    if listed:
        return listed[0].url
    logger.info(
        "No job-list careers URL to offer from %d trusted result(s); "
        "offering nothing rather than a brochure", len(rows),
    )
    return None
