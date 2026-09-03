"""CAREERS-HOST MATCH — "that URL is Amazon's board, which we already publish" (E7 unit 11).

The case that actually bit, in the owner's words: he pasted
``jobs.careers.microsoft.com/global/en/search`` and ``www.amazon.jobs/en/search`` into
Add Companies and both started a **one-time discovery** — a Claude call plus a headless
Chromium session — to build a private duplicate of boards we have published for years.

**Why unit 9 could not catch it.** ``custom_companies_service.find_public_company_for_
candidate`` dedupes on the ``(ats, board_token)`` pair the ATS resolver emits, and the
resolver only names Greenhouse / Ashby / Lever / Gem / Workday / Eightfold. Amazon,
Apple, Google, Microsoft and TikTok are published with ``ats='script'`` — a sentinel the
resolver never emits and no URL ever spells — so their careers URLs resolve to no
candidate at all and fall through to discovery. That limit was documented (in
``user_companies.py`` and ``src/frontend/CLAUDE.md``) and documenting it did not make it
acceptable: the user asked for a company we already have and we charged an LLM call for
the privilege.

**What this does.** Matches the pasted URL's HOST against a declared table of the five
script boards' careers hosts (``scripts.shared.constants.SCRIPT_COMPANY_CAREERS_HOSTS``)
and returns the public company id, or ``None``. It answers with an id, not a row: the
identity, the display name and the "is this still published?" question all come from the
``companies`` table, exactly as unit 9's does — see
``custom_companies_service.find_public_company_for_careers_url``.

**This module is IO-free and must stay that way**, for the same reason
``ats_link_resolver`` is: no ``httpx``, no ``socket``, no database, no LLM client.
``urllib.parse`` is the entire dependency list beyond the constants table. That purity is
what lets the whole matcher table be exhaustively unit-tested, and it is what makes the
check cheap enough to run before anything is created.

EXACT HOST, NEVER A SUFFIX — the one judgement call in here
-----------------------------------------------------------
``jobs.careers.microsoft.com`` is a subdomain of ``microsoft.com``, so the tempting rule
is "match the registrable domain". It is wrong, and Google is the proof: the registrable
domain ``google.com`` is a search engine, a mail client and a maps app, and the job board
is a PATH under it (``/about/careers/applications``). A registrable-domain rule answers
"we already track Google" for ``google.com/maps``, which is worse than the bug it fixes —
a false miss costs one discovery, a false hit sends somebody to the wrong company's chart
and tells them their board is already covered when it is not.

The rule is therefore: **exact equality against a declared host, after normalization**,
plus an optional path prefix for the one host (``google.com``) that is not itself a board.
Sibling subdomains do not match — ``learn.microsoft.com``, ``azure.microsoft.com`` and
``microsoft.com`` itself are not the job board and must keep falling through to the normal
path.

The single concession to subdomains is one leading ``www.`` label, stripped in
:func:`normalize_host`. ``www.amazon.jobs`` and ``amazon.jobs`` are the same server
(verified live: the bare apex 302s into the same site) and ``www`` is a display artifact
rather than an identity — every other label is meaningful.

What normalization covers, and what it deliberately does not
------------------------------------------------------------
Case, ``www.``, a trailing root dot, an explicit port, and userinfo are all handled — see
:func:`normalize_host`. Percent-encoded and punycode-adjacent hosts are NOT decoded: they
simply fail to match anything in the table, which routes the URL to the normal add path.
That is the safe direction. A schemeless string (``amazon.jobs/en/search``) also does not
match, because ``url_guard`` rejects anything but ``https`` long before this and inventing
a scheme here would be this module guessing.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlsplit

from scripts.shared.constants import SCRIPT_COMPANY_CAREERS_HOSTS

#: The only schemes a careers URL can arrive under. ``url_guard.normalize_public_url``
#: is stricter still (https only), but this module is not a security control and
#: refusing ``http://www.amazon.jobs`` here would just send a correct URL to discovery.
_ALLOWED_SCHEMES = frozenset({"http", "https"})

#: The one subdomain label that is a display artifact rather than an identity.
_WWW_PREFIX = "www."


def normalize_host(url: str) -> Optional[str]:
    """The comparable host of ``url``, or ``None`` if it has none.

    ``urlsplit(...).hostname`` does most of the work and is the reason this is short: it
    already lowercases, drops userinfo (``https://evil.tld@amazon.jobs/`` → ``amazon.jobs``
    — note that is genuinely an ``amazon.jobs`` fetch, so taking the host after the ``@``
    is correct, not lenient) and drops an explicit port. On top of that we strip a trailing
    root dot (``amazon.jobs.`` is the fully-qualified spelling of ``amazon.jobs``) and one
    leading ``www.``.

    ``None`` for anything without an ``http``/``https`` scheme, and for anything
    ``urlsplit`` cannot split — a malformed URL is not a match, it is a non-answer.

    TOTAL BY CONTRACT. The input is a string a user pasted, on the request path of the one
    endpoint the Add Companies page cannot live without. Nothing in here raises.
    """
    if not isinstance(url, str) or not url:
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        # An IPv6-bracket-shaped host that is not valid IPv6 raises here.
        return None
    if parts.scheme.lower() not in _ALLOWED_SCHEMES:
        return None
    try:
        host = parts.hostname
    except ValueError:
        return None
    if not host:
        return None

    host = host.rstrip(".")
    if host.startswith(_WWW_PREFIX):
        host = host[len(_WWW_PREFIX):]
    return host or None


def _path_matches(path: str, prefix: str) -> bool:
    """Is ``path`` inside ``prefix``? An empty prefix means the whole host counts.

    ``/about/careers`` matches itself, ``/about/careers/`` and
    ``/about/careers/applications/jobs/results`` — but NOT ``/about/careersomething``,
    which is a different page that merely shares a prefix of characters. The boundary check
    is the whole reason this is not ``path.startswith(prefix)``.

    Case-folded because we compare against a lowercase table and a careers path is not a
    place where case carries meaning; a wrong answer here costs a missed match at worst,
    since ``prefix`` narrows the host rather than widening it.
    """
    if not prefix:
        return True
    path = path.casefold()
    prefix = prefix.casefold()
    return path == prefix or path.startswith(prefix + "/")


def match_careers_url(url: str) -> Optional[str]:
    """The public company id whose careers board ``url`` is, or ``None``. PURE.

    Returns an id (``"amazon"``), never a row: whether that company is still published and
    still enabled is a question for the database, and answering it from a hardcoded table
    is how you point somebody at a chart that stopped updating. The caller
    (``custom_companies_service.find_public_company_for_careers_url``) asks.

    A ``None`` return is the overwhelmingly common case — every URL that is not one of five
    boards — and it means "not one of ours", which routes the URL to exactly the path it
    takes today.
    """
    host = normalize_host(url)
    if host is None:
        return None
    path = urlsplit(url).path or "/"
    for company_id, entries in SCRIPT_COMPANY_CAREERS_HOSTS.items():
        for candidate_host, path_prefix in entries:
            if host == candidate_host and _path_matches(path, path_prefix):
                return company_id
    return None


def match_any_careers_url(*urls: Optional[str]) -> Optional[str]:
    """The first company id any of ``urls`` matches, or ``None``. ``None`` entries skipped.

    The add path has two URLs worth checking and they are not the same string: what the user
    submitted, and what the resolver's redirect-following settled on. ``careers.tiktok.com``
    is only in the table as the submitted form (it 302s to ``lifeattiktok.com``), while a
    company careers page that redirects INTO one of these boards is only recognisable as the
    final URL. Checking both is one table lookup each and closes both directions.
    """
    for url in urls:
        if not url:
            continue
        matched = match_careers_url(url)
        if matched is not None:
            return matched
    return None
