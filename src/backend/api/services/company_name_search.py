"""Turn a typed COMPANY NAME into ATS board candidates (rung A of the name ladder).

The add box has always been URL-only, and strictly so: ``url_guard`` rejects even
``cisco.com`` for having no scheme. This module is the other front door — you type
``Cisco``, we find the board. A pasted URL never reaches this code; it still enters
at ``resolve_ats_url`` (L0) exactly as before, because L0 is exact, free and
instant and nothing should be allowed to get in front of it.

What this module is, precisely: **one Browserbase Search call, then our own free
deterministic scoring of every result it returns.** The search engine is used only
to enumerate URLs a human might have pasted. Deciding which of them is a real board
is done by ``resolve_ats_url``, which is pure and costs nothing, so we can afford to
score all 25 rather than trusting the ranking.

Measured 2026-09-01 over a 30-company ground-truth set (see
``docs/implementations/custom-company-sources/COMPANY-NAME-SEARCH-EVALUATION.md``):

======================================  ======  ==========
strategy                                calls   correct
======================================  ======  ==========
bare name (``Cisco``)                        1      7%
naive (``Cisco careers job board``)          1     48%
the 174-char instruction prompt              1     41%
**host-shaped, scoring all 25**              1    **76%**
======================================  ======  ==========

Two findings from that sweep are load-bearing here and are why the code looks the
way it does rather than simpler.

**An instruction prompt is WORSE than a naive one (41% vs 48%).** Browserbase Search
is Exa-backed retrieval, not an agent: it has no ability to "go look behind the
careers page". Telling it to prefer an ATS spends characters of a 200-char budget on
words that only dilute the query. Naming the ATS HOSTS instead plays to what an index
is actually good at, and that is the entire difference between 41% and 76%. Do not
"improve" ``_QUERY_TEMPLATE`` back into a sentence.

**The dangerous failure is a live board owned by someone else.** Searching
``Databricks`` returned Guidehouse's Workday board at rank 1 — 794 real jobs. It
passes every automated check we own, because it *is* a real board that *does* return
jobs; only a human reading the name catches it. Hence ``_names_match``: a candidate
is only ever eligible for a silent auto-add when the board token names the company.
Everything else is a question for the user, never an answer.

**A miss escalates to a SECOND, plain query — and only a miss.** The ATS hostnames
that make the query above good at finding BOARDS actively poison it for finding a
CAREERS PAGE: for a company with no board on any of the six, the whole result set
becomes SEO content *about* applicant tracking systems. Searching ``Oracle`` really
did offer ``resumeadapter.com/ats/workday/companies`` as Oracle's careers page. So
when no candidate survives its probe as auto-addable, ``search_careers_page`` asks the
plain question instead — ``Oracle careers`` — which returns ``oracle.com/careers/`` at
rank 1. Measured 2026-09-02 over 15 escalating companies
(``docs/implementations/custom-company-sources/CAREERS-FALLBACK-POC.md``): the offered
fallback lands on the company's own domain **14/15, up from 7/15**, and "we offered
nothing at all" goes from 6 companies to **0**.

**A fallback we do not trust is not offered at all.** ``owns_host`` is a FILTER here,
not only a sort key: when no result's host names the company we return ``None`` and
the UI falls back to "paste the URL of their careers page". Handing over the
top-ranked stranger is not a cosmetic miss — accepting it spends a paid discovery run
and one of the user's twenty monthly adds on somebody else's website.

**WHICH trusted result to offer is decided in ``careers_page_pick``, not here.** This
module says which URLs are theirs; that one says which of them is the job list rather
than the brochure about working there. Taking the first trusted result in search rank
order — what this used to hand back — lands on the real job list 3 times in 28,
because search rank prefers the page people link to. Hence ``CareersResult``: every
non-board result keeps its title and rank so the picker has something to score.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from ..config import settings
from .ats_link_resolver import AtsCandidate, resolve_ats_url
from .careers_page_pick import CareersResult
from .discovery.progress import display_url

logger = logging.getLogger(__name__)

_SEARCH_API = "https://api.browserbase.com/v1/search"

# Browserbase caps ``query`` at 200 characters. The hosts are the payload; the two
# English words are there only to bias away from marketing pages. Substituting a
# company name leaves room for one up to 62 characters, which covers every real one.
_QUERY_TEMPLATE = (
    "{company} jobs myworkdayjobs.com greenhouse.io ashbyhq.com "
    "lever.co jobs.gem.com eightfold.ai"
)
_QUERY_MAX_CHARS = 200

# The API's own ceiling. 25 BECAUSE IT IS FREE, not because it is worth much —
# and the difference matters if the vendor ever changes.
#
# Measured over the 29-company ground-truth set, the correct board is found in:
#
#     the top 1 result   11/29 · 38%
#     the top 5 results  21/29 · 72%
#     all 25 results     22/29 · 76%
#
# So the cliff is between 1 and 5, not between 5 and 25 — going to the ceiling buys
# exactly ONE company out of 29 over asking for five. We ask for it anyway because
# Browserbase bills a flat rate per CALL regardless of result count, and scoring is
# a pure local function, so those twenty extra results cost nothing at all.
#
# EXA, which is what Browserbase Search is built on, bills per RESULT: $7/1k requests
# covering the first 10, then $1/1k beyond. Under that model 25 results is $0.022
# against $0.007 — so if this ever moves to Exa directly, drop this to 10 and accept
# the one company. Verified against exa.ai/docs/reference/pricing, 2026-09-02.
_NUM_RESULTS = 25

# THE SECOND QUERY, and the whole of it. Plain words, no hosts: naming the ATS hosts
# is what makes `_QUERY_TEMPLATE` good at finding boards and is exactly what stops it
# finding a careers page (see the module docstring). Same `_NUM_RESULTS`, same flat
# per-call price.
#
# Measured 2026-09-02, 15 escalating companies, three wordings (CAREERS-FALLBACK-POC
# §Q3). All three put an own-domain result at rank 1 for 15/15, so the two longer ones
# buy nothing and both cost something: `{company} careers jobs` lands on a single job
# posting 5 times in 15, and `{company} official careers site` pulls 20% more
# aggregator results. The short one ships.
#
# WHAT IT COSTS. It fires ONLY on a miss — when no probed candidate came back
# auto-addable — so every company whose board resolves spends exactly ONE search and
# gets a byte-identical answer. At Browserbase's flat $0.007 per call that is roughly
# **24 extra searches and $0.17 per 100 name-adds** on a realistic mix; 68% on the POC's
# deliberately adversarial corpus, 41% on the narrower "no board at all" trigger. It
# pays for itself against a single prevented junk fallback, because accepting one costs
# a $0.04-0.08 discovery run PLUS one of the user's 20 monthly adds.
_CAREERS_QUERY_TEMPLATE = "{company} careers"

# How many of the NON-BOARD results we are willing to put on the wire for the add
# page to draw as rows.
#
# The page's morphing list is only honest if every row is a result that really came
# back, so the rows have to be sent rather than invented — but all 25 would be a
# ~4 KB list nobody reads, on a response whose useful half is five candidates. Six is
# what the fold reads well at (they land, they go), and the count of the ones left
# out is sent alongside so the page can say "…and 18 more" without guessing.
_MAX_TRACE_ROWS = 6

_SEARCH_TIMEOUT_S = 12.0

# Typed names are capped well below the query budget. Anything longer is not a
# company name, and letting it through would silently truncate the ATS hosts off
# the end of the query — turning the 76% strategy back into the 7% one.
_MAX_NAME_CHARS = 60

# Hosts that are real search hits and never a board we can read. Without this the
# careers-page fallback happily hands back a LinkedIn or Indeed listing, which is
# not something discovery can ever turn into a recipe.
_AGGREGATOR_HOSTS = (
    "linkedin.com", "indeed.com", "glassdoor.com", "ziprecruiter.com",
    "monster.com", "simplyhired.com", "dice.com", "wellfound.com",
    "angel.co", "builtin.com", "levels.fyi", "teamblind.com",
    "youtube.com", "facebook.com", "x.com", "twitter.com", "reddit.com",
    "wikipedia.org", "bloomberg.com", "crunchbase.com",
)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")

# Shortest normalized string that may be matched by PREFIX rather than exactly.
# Four, because three-letter tokens are common enough as whole company names
# (`ibm`, `sap`) that treating them as prefixes of longer unrelated tokens is a
# real collision risk, and one- or two-character prefixes match almost anything.
_MIN_PREFIX_CHARS = 4

# Career-site slugs that are ordinary words rather than anybody's identity. All of
# these are real values seen on live Workday tenants, and any of them matching a
# typed name would auto-add a company nobody asked for.
_GENERIC_SLUGS = frozenset(
    {
        "careers", "career", "jobs", "job", "search", "external", "internal",
        "global", "campus", "corporate", "professional", "experienced",
        "students", "student", "university", "main", "default", "public",
        "site", "home", "apply", "talent", "recruiting", "hiring", "en", "us",
    }
)


@dataclass(frozen=True)
class SearchResultRow:
    """One result that resolved to no board, kept only so it can be RENDERED.

    The add page narrates a search as a list that narrows: the results land, the
    ones we cannot use fold away, and the answer is what survives. Those rows must
    be real results, which means they have to travel — there is nothing else on the
    response that names them.

    ``url`` is already sanitized (``display_url``) when this is built, so nothing
    downstream has to remember to do it.
    """

    #: Display-safe: no userinfo, no port, query values replaced, clipped.
    url: str
    #: 1-based place in the search engine's own ranking.
    rank: int
    #: Dropped as an aggregator/social host, rather than simply not being a board.
    aggregator: bool


@dataclass(frozen=True)
class NameSearchTrace:
    """What one search actually did, in numbers, for a client that narrates it.

    Every field is something that really happened on this call — there is nothing
    derived, estimated or averaged in here. It exists because the add page shows
    the run as a short list of steps, and a step is only allowed on screen if we
    can point at the number behind it.

    ``filtered`` counts results dropped by ``is_aggregator`` ONLY. A malformed row
    (no URL, not an object) is not filtering, it is a broken result, and lumping
    the two together would let the displayed arithmetic
    (``results - filtered = scored``) quietly stop adding up.
    """

    #: The host-shaped query we sent, verbatim. Sent rather than rebuilt client-side
    #: so ``_QUERY_TEMPLATE`` stays the one place that decides it.
    query: str
    #: How many results the search engine returned (<= ``_NUM_RESULTS``).
    results: int
    #: Aggregator / social hosts dropped before any scoring.
    filtered: int
    #: How many of the scored results resolved to a board we can read.
    boards: int
    #: The non-board results, in rank order, capped at ``_MAX_TRACE_ROWS``. The
    #: BOARDS are deliberately absent: the caller already returns them as
    #: candidates, with a token, a probe and a job count, and one result described
    #: twice on one response is one result that can be described two ways.
    non_boards: tuple[SearchResultRow, ...] = ()
    #: Non-board results the cap left out. ``len(non_boards) + this`` is every
    #: result that was not a board.
    non_boards_omitted: int = 0


@dataclass(frozen=True)
class CareersSearchTrace:
    """What the SECOND search did — present only when a second search happened.

    A separate type from ``NameSearchTrace`` rather than a reuse of it, because two
    of its four numbers would be lies here: the second query is not scored against
    the six job boards (measured over 1,125 results, ``resolve_ats_url`` matched
    zero times), so there is no ``boards`` count to report. What there is instead is
    ``trusted`` — how many results sat on a host that names the company, which is the
    only number that decides whether anything is offered at all.

    Its existence is itself the fact the client narrates: if this is ``None`` the
    panel must not say a second search happened.
    """

    #: The plain query we sent, verbatim (``"Oracle careers"``).
    query: str
    #: How many results the search engine returned (<= ``_NUM_RESULTS``).
    results: int
    #: Aggregator / social hosts dropped before anything else.
    filtered: int
    #: Of the rest, how many sat on a host that names the company. Zero means we
    #: offered nothing, which is the point of the rule.
    trusted: int


@dataclass(frozen=True)
class NameCandidate:
    """One scored search result.

    ``auto_addable`` is the only field with teeth: it is the difference between
    adding a company silently and asking the user to confirm one. It is True only
    when the board token names the company (see ``_names_match``).
    """

    candidate: AtsCandidate
    source_url: str
    title: str
    rank: int
    auto_addable: bool


def normalize_name(value: str) -> str:
    """Casefold and strip every non-alphanumeric character.

    ``Jane Street`` -> ``janestreet``, so it can be compared against the board
    token ``janestreet``. Suffixes like "Inc" are deliberately NOT stripped: a
    company that really is called ``Nominal Inc`` should not be silently matched
    against a board token ``nominal`` owned by someone else.
    """
    return _NON_ALNUM.sub("", value.strip().lower())


def _names_match(typed: str, candidate: AtsCandidate) -> bool:
    """Does the board token name the company the user typed?

    PREFIX MATCH, either direction, and deliberately no edit distance and no
    substring search. Both of the looser rules were tried and both let a real
    wrong-company board through:

    * *Edit distance 1* accepts ``poki`` — a Dutch games site with 2 live jobs —
      for a search for ``Poke``.
    * *Substring, either direction* accepts ``river`` for ``Hudson River
      Trading``, because "river" really is inside "hudsonrivertrading". That is
      ``jobs.ashbyhq.com/river``, a bitcoin company.

    A prefix still covers the cases that matter, because the distinctive part of
    a company name is its head: someone typing ``Cisco Systems`` should match the
    board token ``cisco``, and ``Ramp`` should match ``ramp-payments``. A word
    from the MIDDLE of the typed name matching a whole token is the near-miss
    this gate exists to refuse.

    Both the Workday tenant and the career-site slug count, because for Workday
    the brand can live in either half — ``salesforce.wd12…/Slack`` names Slack
    only in the slug.
    """
    typed_norm = normalize_name(typed)
    if not typed_norm:
        return False
    words = [w for w in (normalize_name(part) for part in typed.split()) if w]
    first_word = words[0] if words else ""

    tokens = [(True, candidate.board_token)]
    tokens.extend(
        (False, str(value))
        for key, value in candidate.provider_config.items()
        if key in ("tenant_slug", "career_site_slug", "domain")
    )
    for is_board_token, token in tokens:
        token_norm = normalize_name(token)
        if not token_norm:
            continue
        # A GENERIC SLUG NAMES NOBODY. `career_site_slug` is routinely an ordinary
        # English word — real prod values include `External`, `Careers` and
        # `Global` — so letting one establish identity means typing "Global
        # Payments" auto-matches ANY unrelated tenant whose site is called
        # `…/Global`. That is the Guidehouse failure reached through the slug
        # instead of the token. `board_token` is exempt: it is the company's own
        # identifier, and a company really can be called `global`.
        if not is_board_token and token_norm in _GENERIC_SLUGS:
            continue
        if token_norm == typed_norm:
            return True
        # A PREFIX IS ONLY MEANINGFUL WHEN IT IS LONG ENOUGH TO IDENTIFY ANYONE.
        # The request model allows a one-character name, and without this floor
        # typing "A" prefix-matches the board token "acme" — which then probes
        # non-empty and gets auto-added. Below the floor, only an exact match
        # counts, so "GM" still matches the token `gm` and matches nothing else.
        if min(len(token_norm), len(typed_norm)) < _MIN_PREFIX_CHARS:
            continue
        # FORWARD: the token elaborates on the whole typed name — "Ramp" against
        # the board `ramp-payments`. Safe, because the user's entire input has to
        # be the start of the token.
        if token_norm.startswith(typed_norm):
            return True
        # REVERSE: the typed name elaborates on the token — "Cisco Systems"
        # against the board `cisco`. This one must land on a WORD BOUNDARY, not
        # any prefix, and that distinction is load-bearing: a bare prefix accepts
        # "Metabase" for Meta's board and "Applebee's" for Apple's, which is
        # exactly the auto-add-the-wrong-company failure this gate exists to stop.
        if token_norm == first_word:
            return True
    return False


def is_aggregator(url: str) -> bool:
    """A job aggregator or social host — a real result, never a readable board.

    MATCHES THE PARSED HOST, never a substring of the URL, and that is the whole
    point of this function's shape. The substring version silently deleted every
    company whose domain merely *ends with* a listed one: ``x.com`` is in the list,
    so ``careers.nutanix.com``, ``jobs.wix.com``, ``careers.citrix.com`` and
    Netflix's ``…/careers?domain=netflix.com`` were all classified as aggregators
    and dropped. Measured live: searching Nutanix dropped all eight real careers
    hits and returned an aggregator as the fallback — which the user would then
    hand to a paid one-time discovery.

    A host matches only if it IS the listed domain or is a subdomain of it, so
    ``linkedin.com.attacker.example`` is correctly not LinkedIn.
    """
    try:
        host = (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    if not host:
        return False
    return any(
        host == aggregator or host.endswith(f".{aggregator}")
        for aggregator in _AGGREGATOR_HOSTS
    )


def build_query(company: str) -> str:
    """The host-shaped query, guaranteed to fit Browserbase's 200-char cap."""
    query = _QUERY_TEMPLATE.format(company=company.strip())
    if len(query) > _QUERY_MAX_CHARS:  # pragma: no cover - _MAX_NAME_CHARS prevents it
        raise ValueError(f"query is {len(query)} chars, over the {_QUERY_MAX_CHARS} cap")
    return query


def _host_owner(company: str) -> Callable[[str], bool]:
    """Build the "does this URL's host NAME the company?" test for one typed name.

    A closure over the identities rather than a bare function, because the
    identities are derived once and asked of up to fifty URLs across two searches.

    A MULTIWORD NAME MUST STILL OWN ITS OWN DOMAIN. ``normalize_name`` strips
    spaces, so "Cisco Systems" becomes ``ciscosystems``, which no label of
    ``cisco.com`` starts with — the company's real careers page would then lose to
    whatever unrelated URL happened to rank above it, and that URL is what gets
    offered for a PAID discovery run. So the first word counts too, under the same
    length floor ``_names_match`` uses: "GM Financial" does not get to match on a
    two-character ``gm``.
    """
    normalized = normalize_name(company)
    if not normalized:
        return lambda _url: False

    identities = {normalized}
    first_word = next(
        (w for w in (normalize_name(part) for part in company.split()) if w), ""
    )
    if len(first_word) >= _MIN_PREFIX_CHARS:
        identities.add(first_word)

    def owns_host(url: str) -> bool:
        # PER LABEL, not "anywhere in the host". The substring form had the same
        # flaw `_names_match` explicitly refuses: `figma.com` would "own" the host
        # for a search for GM (`gm` ⊂ `figma`), and `pineapple.io` for Apple.
        try:
            host = (urlsplit(url).hostname or "").lower()
        except ValueError:
            return False
        labels = [normalize_name(label) for label in host.split(".") if label]
        for label in labels:
            for identity in identities:
                if label == identity:
                    return True
                # SHORT IDENTITIES MATCH WHOLE LABELS ONLY — the same floor
                # `_names_match` applies, for the same reason. As a prefix, "GM"
                # claims `gmc.com` and "HP" claims `hpe.com`, and the URL that
                # wins here is the one offered for a PAID discovery run.
                if len(identity) >= _MIN_PREFIX_CHARS and label.startswith(identity):
                    return True
        return False

    return owns_host


def _rank_careers_results(
    company: str, rows: list[CareersResult]
) -> list[CareersResult]:
    """Put careers pages on the company's OWN domain first, preserving rank within.

    The fallback URL is offered to the user as "no board found, try their careers
    page" — and whatever they accept goes to the add endpoint, where a non-ATS URL
    starts a PAID one-time discovery. So handing back the wrong site is not a
    cosmetic miss, it spends money and one of the user's monthly adds.

    Measured 2026-09-01: searching ``Databricks`` found no board, and the
    top-ranked non-board result was ``scoutify.com/companies/databricks/`` — a job
    aggregator, and one that ``_AGGREGATOR_HOSTS`` does not list. Extending that
    denylist is whack-a-mole (``tryjeremy.com``, ``workway.dev``, ``standout.work``
    and ``digitalhire.com`` all showed up in the same sweep). Preferring a host
    that NAMES the company is the general form of the same idea, and it is the
    same containment test the board-token gate uses: ``databricks.com`` wins,
    ``scoutify.com`` does not, no list required.

    SORTING IS NOT THE DECISION. This orders the list; ``trusted_careers_urls``
    is what decides whether anything in it may be offered. Ranking alone was the
    Oracle failure: not one of the 23 results was on oracle.com, so the sort left
    ``resumeadapter.com/ats/workday/companies`` on top and we handed it over.

    A stable sort, so search rank still decides between two equally-good hosts.
    WHICH of the own-domain pages is the job list rather than the brochure is not
    decided here at all — that is ``careers_page_pick``, over the rows this leaves.
    """
    if not normalize_name(company):
        return rows
    owns_host = _host_owner(company)
    return sorted(rows, key=lambda row: not owns_host(row.url))


def trusted_careers_urls(company: str, urls: Iterable[str]) -> list[str]:
    """Only the URLs whose host NAMES the company, in the order they arrived.

    The same ``owns_host`` rule ``_rank_careers_results`` sorts by, used to REJECT
    rather than to demote — which is the entire change. An untrusted host the user
    accepts is a paid discovery run plus one of their twenty monthly adds, spent on
    a stranger's website, so "we found nothing you can use" is the better answer and
    the UI already knows how to say it.

    Measured over all 22 companies of the 2026-09-02 corpus, 76 accepted URLs: 72 on
    the company's own registrable domain, 4 on a vendor domain carrying the company's
    name (``kingarthurbaking.hrmdirect.com`` is King Arthur's real recruiting site),
    and **0** belonging to a different company.
    """
    owns_host = _host_owner(company)
    return [url for url in urls if owns_host(url)]


def trusted_careers_results(
    company: str, rows: Iterable[CareersResult]
) -> list[CareersResult]:
    """``trusted_careers_urls``, keeping the title and rank attached.

    A thin wrapper and deliberately not a second implementation: it asks the same
    function the same question, so there is still exactly one rule for "may we
    offer this host at all". Everything that ranks or derives runs after this.
    """
    rows = list(rows)
    trusted = set(trusted_careers_urls(company, [row.url for row in rows]))
    return [row for row in rows if row.url in trusted]


class NameSearchUnavailable(RuntimeError):
    """Search could not run — no credentials, or Browserbase refused/failed.

    Distinct from "we searched and found nothing", which is an empty result list.
    The caller turns this into a different HTTP status because the two mean
    different things to a user: one is "try again", the other is "type a URL".
    """


def _check_searchable(name: str) -> None:
    """Refuse a search we already know is wrong, before it costs anything.

    Shared by both queries so neither can drift: the 60-character cap protects the
    200-character query budget the ATS hosts live in, and a missing key is an
    unavailability rather than an empty answer.
    """
    if len(name) > _MAX_NAME_CHARS:
        raise NameSearchUnavailable(
            f"company name is {len(name)} characters, over the {_MAX_NAME_CHARS} limit"
        )
    if not settings.browserbase_api_key:
        raise NameSearchUnavailable("BROWSERBASE_API_KEY is not configured")


async def _run_search(query: str, http: httpx.AsyncClient) -> list[object]:
    """One Browserbase Search call. Returns the raw result rows, unfiltered.

    Every failure mode here is ``NameSearchUnavailable`` — "we could not look" —
    and never an empty result list, which means "we looked and found nothing".
    """
    try:
        response = await http.post(
            _SEARCH_API,
            headers={
                "X-BB-API-Key": settings.browserbase_api_key or "",
                "Content-Type": "application/json",
            },
            json={"query": query, "numResults": _NUM_RESULTS},
            timeout=_SEARCH_TIMEOUT_S,
        )
    except httpx.HTTPError as exc:
        raise NameSearchUnavailable(f"search request failed: {exc}") from exc

    if response.status_code != 200:
        # 429 is the documented rate-limit code (120/min per project). Everything
        # here is "search is unavailable", never "this company has no board" —
        # conflating the two would tell a user their employer is untrackable
        # because we hit a quota.
        raise NameSearchUnavailable(f"search returned HTTP {response.status_code}")

    # EVERY shape that is not "an object with a list of results" is an
    # unavailability, not an empty answer. A bare `[]` body would make
    # `.get` raise AttributeError, which escapes NameSearchUnavailable and turns
    # the route's honest 503 into a 500 — i.e. "your employer cannot be tracked"
    # becomes "the site is broken". Neither is true; the search just misbehaved.
    try:
        payload = response.json()
    except ValueError as exc:
        raise NameSearchUnavailable("search returned a non-JSON body") from exc
    if not isinstance(payload, dict):
        raise NameSearchUnavailable(
            f"search returned a {type(payload).__name__}, not an object"
        )
    results = payload.get("results") or []
    if not isinstance(results, list):
        raise NameSearchUnavailable("search returned a non-list `results`")
    return results


def build_careers_query(company: str) -> str:
    """The plain second query — ``"Oracle careers"``, and nothing else."""
    return _CAREERS_QUERY_TEMPLATE.format(company=company.strip())


async def search_careers_page(
    company: str, http: httpx.AsyncClient
) -> tuple[list[CareersResult], CareersSearchTrace]:
    """The SECOND search: find the company's own careers page. Miss path only.

    Returns ``(trusted_rows, trace)`` — the results whose host names the company,
    in rank order, and what the call did. An empty list is a real answer meaning
    "nothing here is theirs", and the caller must offer nothing rather than the
    best of a bad set.

    RANK ORDER IS NOT THE ANSWER, it is just the order they arrived in. Which of
    these rows to offer is ``careers_page_pick``'s job, which is why the search
    engine's TITLE rides along on every row instead of being dropped here: taking
    ``trusted[0]`` lands on the company's real job list 3 times in 28, because
    search rank prefers the marketing landing page.

    Callers must only reach this when the first search produced no auto-addable
    candidate. It cannot help otherwise, and it is a paid call: measured over
    1,125 results from this query shape, ``resolve_ats_url`` matched **zero**
    times, so a plain careers query can neither find a board the host-shaped query
    missed nor smuggle a stranger's board in. That is what makes it safe, and it is
    also its ceiling.
    """
    name = company.strip()
    if not name:
        return [], CareersSearchTrace(query="", results=0, filtered=0, trusted=0)
    _check_searchable(name)

    query = build_careers_query(name)
    results = await _run_search(query, http)

    rows: list[CareersResult] = []
    filtered = 0
    for rank, result in enumerate(results, start=1):
        if not isinstance(result, dict):
            continue
        url = result.get("url")
        if not isinstance(url, str) or not url:
            continue
        if is_aggregator(url):
            filtered += 1
            continue
        # A board here would be a board the host-shaped query missed, and this is
        # not the rung that adds boards — `careers_url` feeds the paste-a-URL path.
        # Measured never to fire; kept so that if it ever does, the URL is dropped
        # rather than offered as a "careers page" the user is asked to trust.
        if resolve_ats_url(url) is not None:
            continue
        rows.append(
            CareersResult(url=url, title=str(result.get("title") or ""), rank=rank)
        )

    trusted = trusted_careers_results(name, rows)
    logger.info(
        "Careers fallback for %r: %d result(s), %d aggregator(s) dropped -> "
        "%d on a host that names them",
        name, len(results), filtered, len(trusted),
    )
    return trusted, CareersSearchTrace(
        query=query,
        results=len(results),
        filtered=filtered,
        trusted=len(trusted),
    )


async def search_ats_candidates(
    company: str, http: httpx.AsyncClient
) -> tuple[list[NameCandidate], list[CareersResult], NameSearchTrace]:
    """One search call, then score every result.

    Returns ``(candidates, careers_results, trace)``.

    ``careers_results`` are the non-aggregator results that resolved to no board,
    ranked so the ones on the company's own domain come first — rung B feeds the
    best of them to the existing ``ats_discovery.discover_ats``, which is free and
    recovers ~3 more companies in 29, Cisco among them. They carry the search
    engine's title because ``careers_page_pick`` scores on it.

    RANKED, NOT FILTERED, on purpose: this list is raw material, and the caller
    decides what it is for. Anything about to be OFFERED to the user must go
    through ``trusted_careers_urls`` first, because accepting an untrusted one
    spends a paid discovery run on a stranger's site.

    ``trace`` is the run's own counts (see ``NameSearchTrace``). It is a THIRD
    RETURN VALUE rather than something the caller recomputes because two of its
    four fields — the query we sent and how many results came back — exist only
    inside this function; a caller that guessed at them would be narrating a run
    it never saw.

    Candidates are deduplicated on board identity and returned in rank order.
    """
    name = company.strip()
    if not name:
        return [], [], NameSearchTrace(query="", results=0, filtered=0, boards=0)
    _check_searchable(name)

    # Built ONCE and kept, because the trace reports the query verbatim and
    # rebuilding it for the report would be a second chance to report something
    # other than what was sent.
    query = build_query(name)
    results = await _run_search(query, http)

    candidates: list[NameCandidate] = []
    careers_results: list[CareersResult] = []
    filtered = 0
    # The rows the page folds away, and how many more there were than we send.
    # Collected HERE rather than derived by the caller because this is the only
    # place that still has the raw result list and its ranking.
    non_boards: list[SearchResultRow] = []
    non_boards_seen = 0
    seen: set[tuple[str, str, tuple[tuple[str, str], ...]]] = set()

    def keep_non_board(url: str, rank: int, aggregator: bool) -> None:
        """Record a result that produced no board, up to the display cap."""
        nonlocal non_boards_seen
        non_boards_seen += 1
        if len(non_boards) < _MAX_TRACE_ROWS:
            non_boards.append(
                SearchResultRow(
                    url=display_url(url), rank=rank, aggregator=aggregator
                )
            )

    for rank, result in enumerate(results, start=1):
        # A non-object item is skipped rather than fatal: one malformed row in an
        # otherwise good response should cost that row, not the whole search.
        if not isinstance(result, dict):
            continue
        url = result.get("url")
        if not isinstance(url, str) or not url:
            continue
        if is_aggregator(url):
            filtered += 1
            keep_non_board(url, rank, aggregator=True)
            continue
        title = str(result.get("title") or "")
        resolved = resolve_ats_url(url)
        if resolved is None:
            careers_results.append(CareersResult(url=url, title=title, rank=rank))
            keep_non_board(url, rank, aggregator=False)
            continue
        key = (
            resolved.ats,
            resolved.board_token,
            tuple(sorted((k, str(v)) for k, v in resolved.provider_config.items())),
        )
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            NameCandidate(
                candidate=resolved,
                source_url=url,
                title=title,
                rank=rank,
                auto_addable=_names_match(name, resolved),
            )
        )

    logger.info(
        "Name search for %r: %d result(s), %d aggregator(s) dropped -> "
        "%d board candidate(s), %d auto-addable",
        name, len(results), filtered, len(candidates),
        sum(1 for c in candidates if c.auto_addable),
    )
    return (
        candidates,
        _rank_careers_results(name, careers_results),
        NameSearchTrace(
            query=query,
            results=len(results),
            filtered=filtered,
            # The DEDUPLICATED count, which is what the user is about to be shown
            # a slice of. Counting pre-dedupe hits would promise boards that are
            # the same board twice.
            boards=len(candidates),
            non_boards=tuple(non_boards),
            non_boards_omitted=non_boards_seen - len(non_boards),
        ),
    )
