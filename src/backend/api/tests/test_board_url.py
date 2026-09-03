"""The provenance link: ``services.board_url`` — where a tracked board is read from.

Pure, so every provider is covered here without a database. The router test
(``test_user_companies_router``) proves the value actually reaches the wire; this
file is the matrix.
"""

from __future__ import annotations

import pytest

from api.services.board_url import DISCOVERED_ATS, board_url
from api.services import custom_companies_service as svc


def test_discovered_ats_label_matches_the_service_that_writes_it():
    """The one string this module restates rather than imports. If the service ever
    renames it, a discovered row would silently fall through to the token branch and
    get no link — so pin the two together."""
    assert DISCOVERED_ATS == svc._DISCOVERED_ATS


@pytest.mark.parametrize(
    "ats,token,expected",
    [
        ("greenhouse", "spacex", "https://job-boards.greenhouse.io/spacex"),
        ("ashby", "sierra", "https://jobs.ashbyhq.com/sierra"),
        ("lever", "zoox", "https://jobs.lever.co/zoox"),
        ("gem", "nominal", "https://jobs.gem.com/nominal"),
    ],
)
def test_the_four_token_providers_publish_a_board_at_host_plus_slug(ats, token, expected):
    """These four are the ones whose ``board_token`` IS the slug the public board is
    addressed by, so the URL is a template. Greenhouse gets ``job-boards.`` — the
    older ``boards.`` host 301s here, and emitting the destination saves a redirect."""
    assert board_url(ats, token, {}) == expected


def test_workday_is_built_from_provider_config_not_from_its_cosmetic_token():
    """THE CASE THE OWNER HIT. ``board_token`` for a Workday row is the tenant label
    (``cisco``) and names no host; the board is ``{base_url}/{career_site_slug}``,
    which is the URL the resolver parsed this very config out of."""
    assert board_url(
        "workday",
        "cisco",
        {
            "base_url": "https://cisco.wd5.myworkdayjobs.com",
            "tenant_slug": "cisco",
            "career_site_slug": "Cisco_Careers",
        },
    ) == "https://cisco.wd5.myworkdayjobs.com/Cisco_Careers"


def test_workday_keeps_the_career_site_slug_verbatim():
    """``BlueOrigin``, ``Capital_One``, ``external_experienced`` are all real prod
    values and all case-sensitive — the CXS path they land in is too."""
    config = {
        "base_url": "https://blueorigin.wd5.myworkdayjobs.com",
        "tenant_slug": "blueorigin",
        "career_site_slug": "BlueOrigin",
    }
    assert board_url("workday", "blueorigin", config) == (
        "https://blueorigin.wd5.myworkdayjobs.com/BlueOrigin"
    )


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"base_url": "https://acme.wd5.myworkdayjobs.com"},          # no career site
        {"career_site_slug": "External"},                            # no host
        # A host that is not a Workday board host — the same fullmatch ``url_guard``
        # runs before any fetch. We do not link to what we would refuse to read.
        {"base_url": "https://evil.tld", "career_site_slug": "External"},
        {
            "base_url": "https://acme.wd5.myworkdayjobs.com.evil.tld",
            "career_site_slug": "External",
        },
        # Not a URL at all.
        {"base_url": "acme.wd5.myworkdayjobs.com", "career_site_slug": "External"},
        {"base_url": "javascript:alert(1)", "career_site_slug": "External"},
    ],
)
def test_workday_config_we_cannot_vouch_for_gets_no_link(config):
    assert board_url("workday", "acme", config) is None


def test_eightfold_carries_its_tenant_key_because_the_host_never_spells_it():
    """Netflix's board is ``explore.jobs.netflix.net`` serving ``domain=netflix.com``
    — ``netflix.net`` 404s. The tenant key is data, never derived from the host."""
    assert board_url(
        "eightfold",
        "netflix",
        {"tenant_host": "explore.jobs.netflix.net", "domain": "netflix.com"},
    ) == "https://explore.jobs.netflix.net/careers?domain=netflix.com"


def test_eightfold_accepts_the_ordinary_tenant_hosts_too():
    assert board_url(
        "eightfold", "acme", {"tenant_host": "acme.eightfold.ai", "domain": "acme.com"}
    ) == "https://acme.eightfold.ai/careers?domain=acme.com"


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"tenant_host": "acme.eightfold.ai"},                  # no tenant key
        {"domain": "acme.com"},                                # no host
        # Off the SSRF allowlist: a host we would refuse to FETCH is not a host we
        # should hand the user as a link either.
        {"tenant_host": "eightfold.ai.evil.tld", "domain": "acme.com"},
        {"tenant_host": "explore.jobs.example.net", "domain": "acme.com"},
    ],
)
def test_eightfold_config_we_cannot_vouch_for_gets_no_link(config):
    assert board_url("eightfold", "acme", config) is None


def test_a_discovered_board_uses_the_pasted_url_verbatim():
    """A discovered row's ``board_token`` IS the normalized URL we read."""
    url = "https://www.janestreet.com/join-jane-street/open-roles/"
    assert board_url(DISCOVERED_ATS, url, {"discovery": {"outcome": "tracking"}}) == url


@pytest.mark.parametrize(
    "ats,token",
    [
        # The token originates in something a stranger pasted and this becomes an
        # ``href``; a non-http scheme must never survive that trip.
        (DISCOVERED_ATS, "javascript:alert(1)"),
        (DISCOVERED_ATS, "data:text/html,<script>"),
        # No scheme is a RELATIVE url — it would resolve against our own origin.
        (DISCOVERED_ATS, "careers.acme.example"),
        (DISCOVERED_ATS, ""),
        (DISCOVERED_ATS, "   "),
        ("greenhouse", ""),
        ("greenhouse", "   "),
        # An ATS we have never heard of gets nothing rather than a guessed host.
        ("brand_new_ats", "acme"),
        ("script", "amazon"),
        ("", "acme"),
    ],
)
def test_anything_we_cannot_name_honestly_gets_no_link(ats, token):
    assert board_url(ats, token, {}) is None


def test_a_token_that_is_not_one_short_word_cannot_repoint_the_url():
    """``quote`` with nothing safe. A stray path or query in a row we did not write
    stays a single path segment instead of becoming a different destination."""
    assert board_url("greenhouse", "acme/../evil", {}) == (
        "https://job-boards.greenhouse.io/acme%2F..%2Fevil"
    )
    assert board_url("lever", "acme?x=1", {}) == "https://jobs.lever.co/acme%3Fx%3D1"
    # ...and a multi-kilobyte segment is not a slug we produced.
    assert board_url("greenhouse", "a" * 101, {}) is None


@pytest.mark.parametrize("provider_config", [None, "not-a-dict", 7, []])
def test_a_wrong_shaped_provider_config_costs_the_link_not_the_endpoint(provider_config):
    """This runs inside the one endpoint the Add Companies page cannot live without,
    so a row written by an older or buggier path must degrade to "no link"."""
    assert board_url("workday", "acme", provider_config) is None
    assert board_url("eightfold", "acme", provider_config) is None
    # ...while a provider that needs no config is unaffected.
    assert board_url("lever", "zoox", provider_config) == "https://jobs.lever.co/zoox"


def test_none_inputs_are_answered_rather_than_raised():
    assert board_url(None, None, None) is None
    assert board_url("greenhouse", None, None) is None
