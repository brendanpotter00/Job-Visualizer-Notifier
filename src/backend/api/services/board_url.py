"""The human-openable board URL behind a tracked company — WHERE WE READ.

THE QUESTION THIS ANSWERS. Someone types a company NAME ("Cisco"), the search
picks a board, and we start tracking it — and then nothing anywhere on the row
says which page we ended up reading. The link is the only way to check a board
that has started serving dead job links without opening the database, and it is
the only answer to "is this even the right Cisco?".

IT LIVES ON THE SERVER BECAUSE THE DATA DOES. The frontend used to build this
link itself from ``ats`` + ``board_token``, which works for the four providers
whose token IS the slug their public board is addressed by — and cannot work at
all for Workday and Eightfold, whose ``board_token`` is a cosmetic tenant label
(``blueorigin``, ``netflix``) and whose real host lives in ``provider_config``,
a column the list payload does not carry. So those two rendered NOTHING, which
is exactly the case the owner hit. Reassembling provider-specific URL shapes in
the browser would need that column on the wire and a second copy of every shape;
computing it here needs neither.

EVERY SHAPE HERE IS ONE WE ALREADY DEPEND ON, not a guess:

* ``workday`` → ``{base_url}/{career_site_slug}``, which is both the URL the
  resolver parsed the config OUT of (``ats_link_resolver._workday_candidate``)
  and the fallback board link ``workday_client._transform_one`` emits for a
  posting whose own slug is missing.
* ``eightfold`` → ``https://{tenant_host}/careers?domain={domain}``, the form
  Eightfold's own career sites link with and the only form
  ``ats_link_resolver._eightfold_candidate`` accepts as input.
* the four token providers → the host their public board is served on, with
  Greenhouse on ``job-boards.`` rather than the older ``boards.`` (both are
  accepted as input and the old one 301s here, so emitting the destination
  saves every reader a redirect).
* ``discovered`` → the normalized URL the user pasted, which IS the row's
  ``board_token`` (``custom_companies_service.add_discovered_company``).

``None`` IS A REAL ANSWER and the caller must render nothing for it — never a
plausible-looking link we have not derived from real config. It comes back for
an ATS we have never heard of, and for any config that fails the shape checks
below. Those checks are not ceremony: the values originate in a URL a stranger
pasted, this string becomes an ``href``, and a row written by an older or
buggier path must cost the link, not the page.

Pure — no IO, no database, no settings. It takes the three columns and returns a
string, so the whole matrix is unit-testable without a connection.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlencode, urlsplit

# The two host authorities, imported rather than restated so this module cannot
# drift from the matchers that produced the config in the first place.
from .ats_link_resolver import WORKDAY_HOST_PATTERN
from .eightfold_client import _is_allowed_eightfold_host

# Where each token-only ATS publishes the human board for a bare slug. These four
# are the providers whose ``board_token`` IS that slug (``ats_link_resolver``
# extracts exactly it), so the URL is a template and nothing else is needed.
_TOKEN_BOARD_HOSTS: dict[str, str] = {
    "greenhouse": "https://job-boards.greenhouse.io",
    "ashby": "https://jobs.ashbyhq.com",
    "lever": "https://jobs.lever.co",
    "gem": "https://jobs.gem.com",
}

# ``companies.ats`` for a board we discovered ourselves. Its ``board_token`` is the
# normalized URL, not a slug. Spelled here rather than imported from
# ``custom_companies_service`` so this module stays free of that module's psycopg2
# import chain; ``test_board_url`` pins the two together.
DISCOVERED_ATS = "discovered"

# A board token is one short word (``ats_link_resolver._BOARD_TOKEN_PATTERN``), so
# anything longer than this is not a slug we produced and gets no link.
_MAX_TOKEN_LENGTH = 100


def _config(provider_config: Any) -> dict[str, Any]:
    """``provider_config`` as a dict — ``{}`` for anything else.

    The column is NOT NULL with a ``'{}'::jsonb`` default, but this function is
    also handed rows assembled in Python by the add path, so a missing or
    wrong-shaped value must yield "no link" rather than an AttributeError on the
    one endpoint the Add Companies page cannot live without.
    """
    return provider_config if isinstance(provider_config, dict) else {}


def _text(value: Any) -> str:
    """A stripped ``str`` for a JSONB value, or ``''`` for anything non-string."""
    return value.strip() if isinstance(value, str) else ""


def _is_http_url(url: str) -> bool:
    """True iff ``url`` is an absolute ``http(s)`` URL with a host.

    The one check standing between a stored value and an ``href``: a
    ``javascript:`` or ``data:`` token must never become a link, and a bare
    hostname with no scheme is a RELATIVE url that would resolve against our own
    origin.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def board_url(
    ats: str | None,
    board_token: str | None,
    provider_config: Any = None,
) -> str | None:
    """The board this company is read from, as a URL a person can open, or ``None``.

    See the module docstring for where each shape comes from and why ``None`` is a
    real answer rather than a failure.
    """
    ats_name = _text(ats)
    token = _text(board_token)
    config = _config(provider_config)

    if ats_name == DISCOVERED_ATS:
        # The pasted URL itself, verbatim — already normalized on the way in, and
        # the only case where the token is a URL rather than a slug.
        return token if _is_http_url(token) else None

    if ats_name == "workday":
        return _workday_board_url(config)

    if ats_name == "eightfold":
        return _eightfold_board_url(config)

    host = _TOKEN_BOARD_HOSTS.get(ats_name)
    if host is None or not token or len(token) > _MAX_TOKEN_LENGTH:
        return None
    # ``quote`` with nothing safe: the token is a single path segment, so a stray
    # ``/`` or ``?`` in a row we did not write cannot re-point the URL.
    return f"{host}/{quote(token, safe='')}"


def _workday_board_url(config: dict[str, Any]) -> str | None:
    """``{base_url}/{career_site_slug}`` — the tenant's own career site.

    Both halves are required, and the host must be a real Workday board host: the
    same ``WORKDAY_HOST_PATTERN`` the resolver matched to produce this config and
    ``url_guard`` re-checks before any fetch. A config missing either key belongs
    to a row we cannot describe, and it gets no link.
    """
    base_url = _text(config.get("base_url")).rstrip("/")
    career_site_slug = _text(config.get("career_site_slug"))
    if not base_url or not career_site_slug or not _is_http_url(base_url):
        return None
    if not WORKDAY_HOST_PATTERN.fullmatch(urlsplit(base_url).netloc.lower()):
        return None
    return f"{base_url}/{quote(career_site_slug, safe='')}"


def _eightfold_board_url(config: dict[str, Any]) -> str | None:
    """``https://{tenant_host}/careers?domain={domain}``.

    ``domain`` is an Eightfold TENANT KEY and not the registrable domain of the
    host — Netflix's board is ``explore.jobs.netflix.net`` serving
    ``domain=netflix.com`` — so it is carried, never derived. ``tenant_host`` is
    re-checked against the same SSRF allowlist the fetch uses: a host we would
    refuse to read is not a host we should link to either.
    """
    tenant_host = _text(config.get("tenant_host"))
    domain = _text(config.get("domain"))
    if not tenant_host or not domain or not _is_allowed_eightfold_host(tenant_host):
        return None
    return f"https://{tenant_host}/careers?{urlencode({'domain': domain})}"
