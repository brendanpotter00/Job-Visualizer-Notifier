"""Pure URL → ATS candidate resolver (layer L0 of the resolution ladder).

Given a URL, decide whether it *is* an ATS job board we already know how to
scrape, and if so produce the exact ``board_token`` / ``provider_config`` the
existing client would need. Returns ``None`` rather than guessing.

**This module is IO-free and must stay that way.** No ``httpx``, no
``socket``, no database, no LLM client — ``urllib.parse``, ``re``, and the
imported ``_is_allowed_eightfold_host`` are the entire dependency list. That
purity is what lets the matcher table be exhaustively unit-tested with
``socket.getaddrinfo`` monkeypatched to raise. Everything that touches the
network lives in ``ats_discovery`` (L1 redirect-following, L2 embedded-board
sniffing), which *calls* this module.

Matcher notes that are not obvious from the table
-------------------------------------------------
**Workday** (verified against prod + live, 2026-08-05). The tenant comes from
the *host*, not the path — ``generalmotors.wd5.myworkdayjobs.com/Careers_GM``
is the company we call ``gm``, and ``salesforce.wd12.myworkdayjobs.com/Slack``
is ``slack``. The career-site slug is the **first** path segment (after an
optional locale prefix) and is taken **verbatim**: ``BlueOrigin``,
``Capital_One``, ``external_experienced`` are all real prod values and all
case-sensitive. Every segment after the first is ignored — Intel's real URL is
``/External/page/6042070b79e01001f04fa9b468070000`` and resolves to
``career_site_slug = "External"``.

``board_token`` for a Workday candidate is the tenant slug. ``workday_client``
never reads ``board_token`` (it takes ``provider_config`` only), and prod's
Workday rows store the internal company id there (``gm``, ``slack``), which is
not derivable from any URL. The value is therefore cosmetic; the PR-3 add path
may overwrite it with the generated company id.

**Eightfold**. Prod's Netflix row is
``{"domain": "netflix.com", "tenant_host": "explore.jobs.netflix.net"}``. The
``domain`` is an Eightfold tenant key, *not* the registrable domain of the
host: ``netflix.net`` returns 404 from Eightfold's API (verified live
2026-08-05) while ``netflix.com`` returns 200. Nothing in the host spells
``netflix.com``, so we only emit an Eightfold candidate when the URL itself
carries ``?domain=`` — the form Eightfold's own career sites link with. Without
it we return ``None`` rather than fabricate a tenant key that would 404.
``board_token`` is the first label of that domain (``netflix.com`` →
``netflix``), which matches prod and is likewise cosmetic (``eightfold_client``
takes ``tenant_host`` + ``domain``).

**Greenhouse** is "first path segment" *except* under ``/embed/``, where the
segment is Greenhouse's own routing and the board lives in ``?for=``. See
``_greenhouse_candidate`` — that form is the one an embedded board on a careers
page actually links, so L2 hits it constantly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from .eightfold_client import _is_allowed_eightfold_host

# Canonical Workday board-host shape. Owned here (the matcher needs the capture
# group) and imported by ``url_guard`` for its allowlist so the two can never
# drift apart. ``workday_client`` has no host check of its own — that gap is E0
# ticket 0.3 and is deliberately NOT fixed in this PR.
WORKDAY_HOST_PATTERN = re.compile(
    r"(?P<tenant>[a-z0-9][a-z0-9-]*)\.wd(?P<n>[0-9]+)\.myworkdayjobs\.com"
)

# An optional leading locale segment: ``/en-US/BlueOrigin`` is the same board as
# ``/BlueOrigin``. Lowercase language subtag only, per PLAN §1.3.
_LOCALE_SEGMENT_PATTERN = re.compile(r"[a-z]{2}(-[A-Za-z]{2})?")

_GREENHOUSE_HOSTS = frozenset({"boards.greenhouse.io", "job-boards.greenhouse.io"})
# First path segments on a Greenhouse board host that are Greenhouse's own
# routing, never a board token. See ``_greenhouse_candidate``.
_GREENHOUSE_RESERVED_SEGMENTS = frozenset({"embed"})

# Every board token and career-site slug this module emits is attacker-influenced
# text — a query value or a path segment of a URL a user pasted — and every one of
# them is interpolated straight into an ATS API path by
# ``ats_discovery._probe_url`` and persisted by PR 3. So all of them are
# shape-checked, not just the ``?for=`` one: ``https://boards.greenhouse.io/..``
# yielded ``board_token='..'`` and a probe URL that httpx normalized to
# ``https://boards-api.greenhouse.io/v1/jobs`` (a different endpoint on the same
# pinned host), and a 3000-character token was accepted verbatim.
#
# The shape is the same one ``ats_discovery._EMBEDDED_ATS_PATTERNS`` already
# uses to *find* boards, and it covers every real value in prod and in the
# matcher tests: ``blueorigin``, ``Capital_One``, ``external_experienced``,
# ``Cisco_Careers``, ``External``.
_BOARD_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]+")
# Real tokens are one short word. 100 is two orders of magnitude of slack and
# still stops a multi-kilobyte path segment from reaching an API host or a
# database column.
_MAX_BOARD_TOKEN_LENGTH = 100
_ASHBY_HOST = "jobs.ashbyhq.com"
_LEVER_HOST = "jobs.lever.co"
_GEM_HOST = "jobs.gem.com"


@dataclass(frozen=True)
class AtsCandidate:
    """An ATS board we recognized, in the shape the existing clients consume."""

    ats: str                          # greenhouse|ashby|lever|gem|workday|eightfold
    board_token: str
    provider_config: dict[str, str]   # {} for the token-only ATSs
    source_url: str                   # the URL this was derived from


def _path_segments(path: str) -> list[str]:
    """Non-empty path segments, so trailing slashes never create a blank token."""
    return [segment for segment in path.split("/") if segment]


def resolve_ats_url(url: str) -> AtsCandidate | None:
    """Return the ATS candidate ``url`` names, or ``None``.

    ``None`` is a real answer, not a failure: ``https://www.tesla.com/careers``
    and a bare ``https://boards.greenhouse.io/`` both produce it. Callers that
    want redirect-following or embedded-board detection use
    ``ats_discovery.discover_ats``, which layers IO on top of this function.
    """
    if not isinstance(url, str) or not url.strip():
        return None

    # ``urlsplit`` itself raises ``ValueError: Invalid IPv6 URL`` on unbalanced
    # square brackets (``https://a]b.com/`` is enough), so the parse has to be
    # inside the guard too — not just the ``.hostname`` access, which never
    # raises once ``urlsplit`` has succeeded.
    try:
        parts = urlsplit(url.strip())
        hostname = parts.hostname
    except ValueError:
        return None
    if parts.scheme not in ("https", "http"):
        return None
    if not hostname:
        return None

    host = hostname.lower()
    if host.startswith("www."):
        host = host[4:]

    segments = _path_segments(parts.path)

    if host in _GREENHOUSE_HOSTS:
        return _greenhouse_candidate(segments, parts.query, url)
    if host == _ASHBY_HOST:
        # Ashby board tokens are case-insensitive upstream (verified live:
        # ``Sierra`` and ``sierra`` return byte-identical payloads), so we
        # normalize to lowercase for a stable key.
        return _token_candidate("ashby", segments, url, lowercase=True)
    if host == _LEVER_HOST:
        return _token_candidate("lever", segments, url)
    if host == _GEM_HOST:
        return _token_candidate("gem", segments, url)

    workday_match = WORKDAY_HOST_PATTERN.fullmatch(host)
    if workday_match:
        return _workday_candidate(host, workday_match.group("tenant"), segments, url)

    if _is_allowed_eightfold_host(host):
        return _eightfold_candidate(host, parts.query, url)

    return None


def _greenhouse_candidate(
    segments: list[str],
    query: str,
    url: str,
) -> AtsCandidate | None:
    """Greenhouse, with ``/embed/...`` handled as the special case it is.

    ``https://boards.greenhouse.io/embed/job_board?for=acme`` is *the* canonical
    Greenhouse embed form — it is what a careers page that hosts its board in an
    iframe actually links, so it is precisely what an L2 sniff finds. Taking the
    first path segment verbatim there yields ``board_token='embed'``, which is a
    valid-looking token pointing at nothing: ``sniff_embedded_ats`` returns at
    the first page that produces *any* candidate, and ``_rank`` cannot rescue it
    because ``embed`` would be the only candidate. So ``embed`` is reserved and
    the real token is read from ``?for=``; with no usable ``?for=`` we return
    ``None`` rather than a token we know is wrong.
    """
    if segments and segments[0].lower() in _GREENHOUSE_RESERVED_SEGMENTS:
        values = parse_qs(query).get("for") or []
        token = values[0].strip() if values else ""
        if not _is_token_shaped(token):
            return None
        return AtsCandidate(
            ats="greenhouse",
            board_token=token,
            provider_config={},
            source_url=url,
        )
    return _token_candidate("greenhouse", segments, url)


def _is_token_shaped(token: str) -> bool:
    """True iff ``token`` is safe to interpolate into an ATS API path.

    ``None`` from the caller is the right answer for anything else: a value we
    cannot vouch for is not a board we recognized.
    """
    return (
        bool(token)
        and len(token) <= _MAX_BOARD_TOKEN_LENGTH
        and _BOARD_TOKEN_PATTERN.fullmatch(token) is not None
    )


def _token_candidate(
    ats: str,
    segments: list[str],
    url: str,
    *,
    lowercase: bool = False,
) -> AtsCandidate | None:
    """Build a candidate for the four ATSs identified by a single path token."""
    if not segments:
        # A bare board host names no board. Never guess one.
        return None
    token = segments[0]
    if not _is_token_shaped(token):
        return None
    return AtsCandidate(
        ats=ats,
        board_token=token.lower() if lowercase else token,
        provider_config={},
        source_url=url,
    )


def _workday_candidate(
    host: str,
    tenant: str,
    segments: list[str],
    url: str,
) -> AtsCandidate | None:
    if segments and _LOCALE_SEGMENT_PATTERN.fullmatch(segments[0]):
        segments = segments[1:]
    if not segments:
        # A bare tenant host has no career site. Workday tenants routinely host
        # several (``External``, ``Internal``, campus boards); picking one would
        # be a guess with a wrong-population failure mode.
        return None
    career_site_slug = segments[0]     # VERBATIM — never .lower(), never .title()
    if not _is_token_shaped(career_site_slug):
        # Verbatim does not mean unchecked: the slug lands in the CXS path
        # ``/wday/cxs/<tenant>/<slug>/jobs``, and ``..`` there resolved to a
        # different endpoint on the tenant's own host.
        return None
    return AtsCandidate(
        ats="workday",
        board_token=tenant,
        provider_config={
            "base_url": f"https://{host}",
            "tenant_slug": tenant,
            "career_site_slug": career_site_slug,
        },
        source_url=url,
    )


def _eightfold_candidate(host: str, query: str, url: str) -> AtsCandidate | None:
    domains = parse_qs(query).get("domain") or []
    domain = domains[0].strip().lower() if domains else ""
    if not domain or "." not in domain:
        # See the module docstring: the Eightfold tenant key is not derivable
        # from the host. No ``?domain=`` means no candidate.
        return None
    return AtsCandidate(
        ats="eightfold",
        board_token=domain.split(".")[0],
        provider_config={"tenant_host": host, "domain": domain},
        source_url=url,
    )
