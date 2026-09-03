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
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from ..config import settings
from .ats_link_resolver import AtsCandidate, resolve_ats_url

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


def _rank_careers_urls(company: str, urls: list[str]) -> list[str]:
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

    A stable sort, so search rank still decides between two equally-good hosts.
    """
    normalized = normalize_name(company)
    if not normalized:
        return urls

    # A MULTIWORD NAME MUST STILL OWN ITS OWN DOMAIN. `normalize_name` strips
    # spaces, so "Cisco Systems" becomes `ciscosystems`, which no label of
    # `cisco.com` starts with — the company's real careers page then loses to
    # whatever unrelated URL happened to rank above it, and that URL is what gets
    # offered for a PAID discovery run. So the first word counts too, under the
    # same length floor `_names_match` uses: "GM Financial" does not get to match
    # on a two-character `gm`.
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

    return sorted(urls, key=lambda url: not owns_host(url))


class NameSearchUnavailable(RuntimeError):
    """Search could not run — no credentials, or Browserbase refused/failed.

    Distinct from "we searched and found nothing", which is an empty result list.
    The caller turns this into a different HTTP status because the two mean
    different things to a user: one is "try again", the other is "type a URL".
    """


async def search_ats_candidates(
    company: str, http: httpx.AsyncClient
) -> tuple[list[NameCandidate], list[str], NameSearchTrace]:
    """One search call, then score every result.

    Returns ``(candidates, careers_urls, trace)``.

    ``careers_urls`` are the non-aggregator results that resolved to no board, in
    rank order — rung B feeds the best of them to the existing
    ``ats_discovery.discover_ats``, which is free and recovers ~3 more companies
    in 29, Cisco among them.

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
    if len(name) > _MAX_NAME_CHARS:
        raise NameSearchUnavailable(
            f"company name is {len(name)} characters, over the {_MAX_NAME_CHARS} limit"
        )
    if not settings.browserbase_api_key:
        raise NameSearchUnavailable("BROWSERBASE_API_KEY is not configured")

    # Built ONCE and kept, because the trace reports the query verbatim and
    # rebuilding it for the report would be a second chance to report something
    # other than what was sent.
    query = build_query(name)
    try:
        response = await http.post(
            _SEARCH_API,
            headers={
                "X-BB-API-Key": settings.browserbase_api_key,
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

    candidates: list[NameCandidate] = []
    careers_urls: list[str] = []
    filtered = 0
    seen: set[tuple[str, str, tuple[tuple[str, str], ...]]] = set()

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
            continue
        resolved = resolve_ats_url(url)
        if resolved is None:
            careers_urls.append(url)
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
                title=str(result.get("title") or ""),
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
        _rank_careers_urls(name, careers_urls),
        NameSearchTrace(
            query=query,
            results=len(results),
            filtered=filtered,
            # The DEDUPLICATED count, which is what the user is about to be shown
            # a slice of. Counting pre-dedupe hits would promise boards that are
            # the same board twice.
            boards=len(candidates),
        ),
    )
