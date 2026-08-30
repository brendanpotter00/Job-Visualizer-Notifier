"""COMPANY-NAME MATCH — "lifeatspotify.com has 'spotify' in it" (E7, the third dedupe).

The case, in the owner's words: he watched ``lifeatspotify.com`` run a full one-time
discovery — a headless Chromium session plus a Claude call — and only *then* get told
"this looks like Spotify, which we already track", from the job-title overlap that can
only run once a discovery has finished.

    "The point of deduping things is to catch it before we do the expensive stuff...
    all those URLs are gonna have like Cisco in them, or in this case all of them are
    gonna have Spotify in them."

He is right that the answer was sitting in the string. ``lifeatspotify`` contains
``spotify``; we publish ``spotify``; nothing about knowing that requires a browser.

WHERE THIS SITS IN THE LADDER
-----------------------------
1. :mod:`api.services.ats_link_resolver` names an ``(ats, board_token)`` pair —
   ``find_public_company_for_candidate`` dedupes on it. Exact identifier.
2. :mod:`api.services.careers_host_match` matches the careers HOST of the five
   ``ats='script'`` boards against a declared table. Exact, declared host.
3. **This module** — the registrable domain LABEL against the names of companies we
   publish. A GUESS, and the whole design below is about that word.
4. :mod:`api.services.published_board_match` compares job SETS. Free, but only after a
   discovery has already run — which is the cost this module exists to avoid.

Rungs 1 and 2 are terminal: the user is told we already have it and there is no
"track it anyway" button, because a resolved board token and a declared host leave no
plausible world where they meant a different company. This rung is NOT terminal. It
keeps the escape hatch precisely because it is a guess, and the copy it drives says
"looks like" rather than "is".

THE RULE, AND WHY IT IS NOT CONTAINMENT
---------------------------------------
The tempting rule is "does the domain contain a name we publish". Measured against the
133 enabled public rows (147 distinct name keys) and 235,761 English dictionary words
used as bare ``<word>.com`` labels, plain containment produces **2,294 false hits** —
``affirmation`` → Affirm, ``afterlight`` → Light, ``adnominal`` → Nominal. It is also
wrong on our own fleet today: ``gm`` (General Motors) is a substring of ``figma``,
``judgmentlabs`` and ``thinkingmachines``, so ``figma.com`` answers "General Motors"
unless something else saves it. That is the ``box``/``dropbox`` collision the brief
names, except it is not hypothetical — it is in the table right now.

A false miss costs one discovery. A false hit sends somebody to a different company's
chart and tells them they are covered when they are not. So the rule is not containment:

    The registrable domain LABEL must BE a published name, or be that name
    wearing one declared careers/marketing affix.

``lifeatspotify`` = ``lifeat`` + ``spotify`` ✓.  ``dropbox`` is not ``<affix> + box``
for any affix in the list, so it stays Dropbox ✗.  ``blockchain`` is not
``block + <affix>`` ✗.  Same corpus, same 133 rows: **1 false hit** (``theanthropic``,
an obscure theology word that would in fact be a reasonable guess at Anthropic).

FOUR RAILS, each of which is load-bearing
-----------------------------------------
* **Registrable label only, never the whole host and never a subdomain.** A subdomain is
  chosen by whoever owns the domain, so matching one lets any host claim any identity —
  ``spotify.some-aggregator.com`` is an aggregator, not Spotify. ``jobs.cisco.com`` and
  ``careers.eu.cisco.com`` both reduce to ``cisco``.
* **ATS and aggregator domains never match** (:data:`_NEVER_MATCH_DOMAINS`), by
  registrable DOMAIN so subdomains are covered too. ``jobs.lever.co`` reduces to the
  label ``lever``, and one day we may publish a company called Lever; ``jobs.gem.com``
  is some *other* company's Gem board. Rung 1 owns these URLs and this rung must not
  speak about them.
* **Affix-stripping needs a core of at least** :data:`_MIN_AFFIX_CORE_LEN` **characters.**
  18 of the 147 keys are ≤4 characters (``gm``, ``exa``, ``fal``, ``gem``, ``snap``,
  ``ramp``, ``turo``…) and 46 are ordinary English words, so a short key plus a short
  affix matches things that have nothing to do with us: ``teamsnap.com`` is a real,
  different company that decomposes to ``team`` + ``snap``. Short names match only when
  the WHOLE label is the name — ``gm.com`` is General Motors, and that is safe because
  nothing else is spelled exactly ``gm``.
* **Ambiguity is refused, not guessed.** If two different companies tie on the strongest
  available evidence, the answer is ``None`` and the URL takes the ordinary path.

WHAT THIS DELIBERATELY DOES NOT SPEAK ABOUT
-------------------------------------------
The five ``ats='script'`` companies (:data:`_HOST_TABLE_COMPANY_IDS`) are excluded from
the name index entirely. They already have an EXACT host table one rung up, and that
table's ``None`` answers are deliberate: it refuses ``learn.microsoft.com``,
``aws.amazon.com`` and ``google.com/maps`` because the registrable domain is a training
site, a cloud provider and a search engine rather than a job board. A guess that
second-guessed those exact refusals could only add false positives on top of an
authority that already answered. The cost is one class of miss (a vanity host for those
five that is not in the table) and it is worth it.

**This module is IO-free and must stay that way**, for the same reason
:mod:`api.services.careers_host_match` is: no ``httpx``, no ``socket``, no database, no
LLM client. It is handed the published names and returns an id. That purity is what
makes the whole rule exhaustively unit-testable, and it is what makes the check cheap
enough to run before anything is created.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional, Sequence
from urllib.parse import urlsplit

from scripts.shared.constants import SCRIPT_COMPANY_CAREERS_HOSTS

from .careers_host_match import normalize_host

#: Company ids that :mod:`api.services.careers_host_match` already answers for, EXACTLY.
#: Excluded from the name index — see "WHAT THIS DELIBERATELY DOES NOT SPEAK ABOUT".
_HOST_TABLE_COMPANY_IDS = frozenset(SCRIPT_COMPANY_CAREERS_HOSTS)

#: Second-level labels that belong to the public suffix rather than to the name, so
#: ``careers.acme.co.uk`` reduces to ``acme`` and not to ``co``. Same list the add
#: path's ``_discovery_display_name`` uses; this is a short pragmatic stand-in for the
#: Public Suffix List, which we do not carry and do not want a network dependency for.
_SUFFIX_LABELS = frozenset({"co", "com", "net", "org", "ac", "gov", "edu"})

#: Registrable domains whose LABEL is an ATS/aggregator brand rather than the identity
#: of whoever's board is on it. A URL under any of these never name-matches.
#:
#: Keyed by registrable domain (not host) so every subdomain is covered: the danger with
#: ``jobs.lever.co`` is the label ``lever``, and that label is the same on ``api.lever.co``
#: and on ``lever.co`` itself. The first block is every ATS the resolver can name (rung 1
#: owns those URLs); the rest are vendors and aggregators we do not read but that users
#: paste, listed so that publishing a company whose name collides with one of them cannot
#: silently turn their whole site into a match.
#:
#: KNOWN COST, accepted: ``gem.com`` is Gem's own site AND the Gem ATS, so Gem is the one
#: published company this rung can never name-match. Their board is already deduped by
#: rung 1, and treating every ``*.gem.com`` URL as "Gem" would claim other companies'
#: boards — a false hit for many, to save one discovery for one company.
_NEVER_MATCH_DOMAINS = frozenset({
    # Rung 1's own ATSs.
    "greenhouse.io", "ashbyhq.com", "lever.co", "gem.com",
    "myworkdayjobs.com", "workday.com", "eightfold.ai",
    # Other ATS vendors and job aggregators. Not read by us; pasted by users.
    "smartrecruiters.com", "jobvite.com", "icims.com", "taleo.net",
    "successfactors.com", "workable.com", "recruitee.com", "teamtailor.com",
    "bamboohr.com", "personio.com", "rippling.com", "breezy.hr", "dover.com",
    "indeed.com", "linkedin.com", "glassdoor.com", "ziprecruiter.com",
    "wellfound.com", "builtin.com", "otta.com", "paylocity.com", "greenhouse.com",
})

#: Affixes a careers or marketing domain wraps a company name in. CLOSED and declared,
#: which is the entire safety property: the label must decompose EXACTLY into
#: ``<prefix?> + <published name> + <suffix?>``, so an undeclared word around a name
#: (``drop`` + ``box``, ``block`` + ``chain``) is not a match at all.
#:
#: Every entry is a shape we have actually seen, not a word that seemed plausible:
#: ``lifeat`` is in our own ``SCRIPT_COMPANY_CAREERS_HOSTS`` twice (lifeatspotify,
#: lifeattiktok); ``weare`` is wearenetflix.com; ``workat`` is workatastartup.com;
#: ``join`` is joinhandshake.com; ``get``/``try``/``use`` are the standard startup
#: domain prefixes; ``the`` is thebrowsercompany.com. Words with no such exemplar
#: (``team``, ``my``, ``go``, bare ``at``) are deliberately absent — ``team`` alone
#: would have claimed teamsnap.com for Snap.
_PREFIXES: tuple[str, ...] = (
    "lifeat", "life", "workat", "weare", "join",
    "careersat", "careers", "career", "jobsat", "jobs", "job",
    "get", "try", "use", "hello", "hey", "the",
)
_SUFFIXES: tuple[str, ...] = (
    "careers", "career", "jobs", "job", "hiring", "talent", "hq",
)

#: Minimum length of what is left after an affix is stripped. Five, because the shortest
#: name this check has to catch is ``cisco`` (5) and the longest name it has to REFUSE is
#: ``snap`` (4, via the real teamsnap.com). Every published key of 4 characters or fewer
#: is therefore exact-match-only, which is the same line that keeps ``box`` from being
#: found inside ``dropbox`` if we ever publish Box.
_MIN_AFFIX_CORE_LEN = 5

#: Everything that is not a letter or a digit is noise in a domain label: ``jane-street``
#: and ``janestreet`` are one name, and so are "Base Power Company" and ``basepower``.
_NON_ALNUM = re.compile(r"[^a-z0-9]+")

#: Path segments that introduce a DIRECTORY OF COMPANIES rather than naming one.
#: See :func:`directory_tenant`.
_DIRECTORY_SEGMENTS = frozenset({
    "companies", "company", "employers", "employer", "startups",
    "organizations", "organisations", "orgs", "org", "profiles",
})

#: Path segments that are about the JOBS, never about who is hiring. A candidate tenant
#: slug drawn from this set is not a tenant at all — it is the careers section of a
#: single-company site that happens to sit under ``/company/``. This is what keeps
#: ``atlassian.com/company/careers/all-jobs`` named "Atlassian" and not "Careers".
_GENERIC_PATH_SEGMENTS = frozenset({
    "careers", "career", "jobs", "job", "hiring", "apply", "search",
    "openings", "opening", "opportunities", "roles", "open-roles", "all-jobs",
    "positions", "position", "vacancies", "listings", "life", "culture",
    "join-us", "join", "work-with-us", "work", "about", "about-us", "team",
})


def directory_tenant(url: str) -> Optional[str]:
    """The company slug ``url``'s PATH names inside a directory host, or ``None``.

    THE PROBLEM THIS SOLVES. ``www.ycombinator.com/companies/raindrop/jobs`` is
    Raindrop's board, not Y Combinator's. On a host like that the registrable domain is
    the DIRECTORY's brand and every one of its ~1,500 tenants shares it, so anything
    that reads identity out of the host alone gives them all the SAME answer: the add
    flow named the row "Ycombinator", and this rung would hand every tenant to a
    published company called Ycombinator if one ever existed. The identity of a
    path-bearing board has to come from the path.

    THE SHAPE, and it is the only thing recognised — no host list, no per-board rule::

        /<directory segment>/<tenant slug>/<at least one more segment>

    THREE CONDITIONS, ALL REQUIRED, and each one is a false positive that was measured
    against the boards this repo already tracks:

    1. **A declared directory segment** (:data:`_DIRECTORY_SEGMENTS`). Jane Street's
       ``/join-jane-street/open-roles/`` has none, so it keeps its host name.
    2. **The next segment is not a generic careers word**
       (:data:`_GENERIC_PATH_SEGMENTS`). Atlassian's ``/company/careers/all-jobs``
       would otherwise be named "Careers".
    3. **Something follows the tenant.** A directory URL points AT a tenant's page and
       then keeps going; a single-company site's ``/company/<word>`` is a leaf. Without
       this, an undeclared leaf word (``/company/our-story``) becomes a company name.
       The cost is real and accepted: a bare ``/companies/raindrop`` with no trailing
       segment falls back to the host name. That is the status quo, and this codebase's
       rule is that a slightly ugly name beats a confidently wrong one.

    PURE, like everything else here, and it decides NO identity of its own: the row is
    still keyed on the full normalized URL (``discovered_source_key``), so two tenants
    were never at risk of sharing a row. This fixes what they DO share — the label, and
    this rung's reading of the host.

    Returns the raw slug (``"raindrop"``, ``"wispr-flow"``); callers normalize it.
    """
    if not isinstance(url, str):
        return None
    segments = [s for s in urlsplit(url).path.split("/") if s]
    for index, segment in enumerate(segments[:-2]):
        if segment.lower() not in _DIRECTORY_SEGMENTS:
            continue
        tenant = segments[index + 1]
        if tenant.lower() in _GENERIC_PATH_SEGMENTS or tenant.lower() in _DIRECTORY_SEGMENTS:
            continue
        return tenant
    return None


def normalize_name(value: str) -> str:
    """A comparable key: lowercase, letters and digits only. ``''`` if nothing is left.

    Used on BOTH sides — the published ``id``/``display_name`` and the domain label — so
    ``Base Power Company`` and ``basepowercompany.com`` meet in the middle, and so does
    ``Wispr Flow`` with ``wispr-flow``.
    """
    if not isinstance(value, str):
        return ""
    return _NON_ALNUM.sub("", value.lower())


def registrable_domain(host: str) -> str:
    """The last two labels of ``host``, or three when the second-to-last is a suffix label.

    ``jobs.lever.co`` → ``lever.co``; ``careers.acme.co.uk`` → ``acme.co.uk``;
    ``amazon.jobs`` → ``amazon.jobs``. Only used against :data:`_NEVER_MATCH_DOMAINS`,
    where being slightly generous is the safe direction: a domain we refuse to name-match
    just takes the ordinary path.
    """
    labels = [label for label in host.split(".") if label]
    if len(labels) < 2:
        return host
    if len(labels) >= 3 and labels[-2] in _SUFFIX_LABELS:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def registrable_label(host: str) -> Optional[str]:
    """The one label that carries identity — ``cisco`` in ``careers.eu.cisco.com``.

    ``None`` for a single-label host and for an IPv4 literal: neither has a name in it.
    Subdomains are dropped rather than searched, deliberately — see the "registrable label
    only" rail in the module docstring.
    """
    labels = [label for label in host.split(".") if label]
    if len(labels) < 2 or all(label.isdigit() for label in labels):
        return None
    core = labels[:-1]
    if len(core) > 1 and core[-1] in _SUFFIX_LABELS:
        core = core[:-1]
    return core[-1] if core else None


def build_name_index(
    companies: Iterable[tuple[str, str]],
) -> dict[str, set[str]]:
    """``{normalized name: {company id, ...}}`` from ``(id, display_name)`` pairs.

    BOTH fields, because neither alone is the name people put in a domain: Anduril's id
    is ``andurilindustries`` but their site is ``anduril.com``; General Motors' display
    name is two words but their site is ``gm.com``. Only the WHOLE normalized value is a
    key — never an individual word of a display name, which would make ``general``,
    ``labs``, ``trading`` and ``ai`` into company names.

    The five companies :mod:`api.services.careers_host_match` already answers for exactly
    are skipped; see the module docstring.
    """
    index: dict[str, set[str]] = {}
    for company_id, display_name in companies:
        if not company_id or company_id in _HOST_TABLE_COMPANY_IDS:
            continue
        for raw in (company_id, display_name):
            key = normalize_name(raw or "")
            if key:
                index.setdefault(key, set()).add(company_id)
    return index


def _candidate_cores(label: str) -> list[tuple[int, str]]:
    """``(tier, core)`` readings of one domain label, strongest tier first.

    Tier 1 is the whole label — the label IS the name. Tier 0 is the label with one
    declared prefix and/or one declared suffix removed. Nothing else is generated, which
    is why an undeclared word around a name is simply not a reading at all.
    """
    cores: list[tuple[int, str]] = [(1, label)]
    for prefix in ("",) + _PREFIXES:
        if prefix and not label.startswith(prefix):
            continue
        rest = label[len(prefix):]
        for suffix in ("",) + _SUFFIXES:
            if not prefix and not suffix:
                continue  # already covered by the tier-1 reading
            if suffix and not rest.endswith(suffix):
                continue
            core = rest[: len(rest) - len(suffix)] if suffix else rest
            if len(core) >= _MIN_AFFIX_CORE_LEN:
                cores.append((0, core))
    return cores


def match_name_in_url(url: str, index: dict[str, set[str]]) -> Optional[str]:
    """The published company id ``url``'s domain appears to name, or ``None``. PURE.

    ``None`` is the overwhelmingly common answer and means "no opinion", which routes the
    URL to exactly the path it takes today. A non-``None`` answer is a GUESS the caller
    must present as one.
    """
    host = normalize_host(url)
    if host is None:
        return None
    if registrable_domain(host) in _NEVER_MATCH_DOMAINS:
        return None
    # A URL whose PATH names a tenant is a page ON a directory, so its host label is the
    # directory's brand and speaks for none of the ~1,500 companies underneath it.
    # :data:`_NEVER_MATCH_DOMAINS` says the same thing for the aggregators we happen to
    # have listed (``wellfound.com``, ``builtin.com``); this says it for the ones we have
    # not, which is the half that would otherwise hand EVERY tenant of an unlisted
    # directory to one published company the day its name collided with the host's.
    #
    # We do NOT then match on the tenant slug instead. It would be a real improvement —
    # ``ycombinator.com/companies/ramp/jobs`` is the Ramp we publish — but a slug is
    # chosen by the directory, not by the company, and this rung's failure mode is
    # telling somebody they are already covered when they are not. Declining is free;
    # the cost of a wrong guess here is a user sent to another company's chart.
    if directory_tenant(url) is not None:
        return None
    label = normalize_name(registrable_label(host) or "")
    if not label:
        return None

    hits: list[tuple[int, int, str]] = []
    for tier, core in _candidate_cores(label):
        for company_id in index.get(core, ()):
            hits.append((tier, len(core), company_id))
    if not hits:
        return None

    # Strongest evidence wins: an exact label beats an affix reading, and among equals a
    # longer name beats a shorter one (``modallabs`` is Modal Labs, not a coincidence
    # containing something else). A genuine tie between two DIFFERENT companies is
    # refused rather than broken arbitrarily — see the "ambiguity" rail.
    best = max(hit[:2] for hit in hits)
    winners = {company_id for tier, length, company_id in hits if (tier, length) == best}
    if len(winners) != 1:
        return None
    return winners.pop()


def match_name_in_any_url(
    urls: Sequence[Optional[str]], index: dict[str, set[str]]
) -> Optional[str]:
    """The first company id any of ``urls`` names, or ``None``. ``None`` entries skipped.

    Two URLs are worth checking for the same reason
    :func:`careers_host_match.match_any_careers_url` checks two: what the user submitted
    and what the resolver's redirect-following settled on are different strings, and the
    name can be in either. A vanity host that redirects to a bare CDN shell only has it in
    the submitted URL; an aggregator link that redirects to the company's own site only
    has it in the final one.
    """
    for url in urls:
        if not url:
            continue
        matched = match_name_in_url(url, index)
        if matched is not None:
            return matched
    return None
