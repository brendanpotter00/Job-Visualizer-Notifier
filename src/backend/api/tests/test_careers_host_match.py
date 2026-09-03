"""Unit tests for the pure careers-host matcher (E7 unit 11).

No database, no network, no fixtures — the module under test is IO-free by contract
and these tests are what keeps it that way. The end-to-end behaviour (nothing created,
nothing enqueued) is asserted against the real endpoint in
``test_user_companies_router.py``.
"""

from __future__ import annotations

import pytest

from api.services.careers_host_match import (
    match_any_careers_url,
    match_careers_url,
    normalize_host,
)
from scripts.shared.constants import SCRIPT_COMPANY_CAREERS_HOSTS, SourceId


# --- the five boards, in the forms a person actually pastes -------------------

@pytest.mark.parametrize(
    "url,expected",
    [
        # The two URLs from the report that opened this unit.
        ("https://jobs.careers.microsoft.com/global/en/search", "microsoft"),
        ("https://www.amazon.jobs/en/search", "amazon"),
        # ...and the rest of the six.
        ("https://jobs.apple.com/en-us/search", "apple"),
        ("https://careers.google.com/", "google"),
        ("https://lifeattiktok.com/search", "tiktok"),
        ("https://www.metacareers.com/jobsearch", "meta"),
        ("https://metacareers.com/", "meta"),
    ],
)
def test_each_script_boards_careers_url_names_its_company(url, expected):
    assert match_careers_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://www.amazon.jobs/en/search",          # with www.
        "https://amazon.jobs/en/search",              # without
        "https://AMAZON.JOBS/en/search",              # mixed case host
        "https://WWW.Amazon.Jobs/EN/Search",          # mixed case, mixed case path
        "https://amazon.jobs./en/search",             # trailing root dot
        "https://amazon.jobs:443/en/search",          # explicit port
        "https://user:pw@www.amazon.jobs/en/search",  # userinfo
        "https://www.amazon.jobs/en/search/",         # trailing slash
        "https://www.amazon.jobs/en/search?base_query=engineer&offset=20",  # query
        "https://www.amazon.jobs/en/search#results",  # fragment
        "https://www.amazon.jobs",                    # bare, no path at all
        "http://www.amazon.jobs/en/search",           # http, not https
    ],
)
def test_every_spelling_of_one_board_still_names_it(url):
    """Case, ``www.``, a root dot, a port, userinfo, query, fragment, scheme.

    Each of these is a URL a real person or a real redirect produces, and each of them
    is a different string. Any one of them missing is a user who gets charged a Claude
    call and a Chromium session for Amazon's front page.
    """
    assert match_careers_url(url) == "amazon"


# --- the subdomain judgement call, in executable form -------------------------

@pytest.mark.parametrize(
    "url",
    [
        # THE near-miss class. All of these share a registrable domain with a board
        # above and none of them is that board. A "match the registrable domain" rule
        # — the obvious shortcut, given the pasted URL was a SUBdomain of
        # microsoft.com — answers "we already track Microsoft" for every one.
        "https://learn.microsoft.com/en-us/training/",
        "https://azure.microsoft.com/en-us/pricing/",
        "https://www.microsoft.com/en-us/microsoft-365",
        "https://microsoft.com/",
        "https://support.apple.com/en-us/contact",
        "https://www.apple.com/careers/",
        "https://www.amazon.com/jobs",
        "https://aws.amazon.com/careers/",
        "https://www.tiktok.com/about",
        # Meta's corporate / product domains are NOT the metacareers.com board.
        # No redirect to it was confirmed, and a careers-host hit is terminal.
        "https://www.meta.com/",
        "https://about.meta.com/",
        "https://www.facebook.com/careers",
    ],
)
def test_a_sibling_subdomain_is_not_the_job_board(url):
    assert match_careers_url(url) is None


@pytest.mark.parametrize(
    "url",
    [
        # THE SHARPER near-miss, and the one the sibling-subdomain cases above do NOT
        # cover. Each of these hosts ENDS WITH a declared board host without being it,
        # because the shared text stops mid-label rather than on a dot:
        #   notamazon.jobs             endswith amazon.jobs
        #   evil-careers.microsoft.com endswith careers.microsoft.com
        #   myjobs.apple.com           endswith jobs.apple.com
        #   xgoogle.com                endswith google.com
        #   fakelifeattiktok.com       endswith lifeattiktok.com
        # A ``host.endswith(declared)`` implementation passes every test above this one
        # and hands all five of these the wrong company's chart — including a host an
        # attacker can register. Exact equality is the only rule that refuses them.
        "https://notamazon.jobs/en/search",
        "https://evil-careers.microsoft.com/global/en/search",
        "https://myjobs.apple.com/en-us/search",
        "https://xgoogle.com/about/careers/applications/",
        "https://fakelifeattiktok.com/search",
        # notmetacareers.com endswith metacareers.com — the endswith trap.
        "https://notmetacareers.com/jobsearch",
    ],
)
def test_a_host_that_merely_ends_with_a_board_host_is_not_that_board(url):
    assert match_careers_url(url) is None


@pytest.mark.parametrize(
    "url,expected",
    [
        # Google is the reason the rule is exact-host-plus-path and not
        # registrable-domain: the board is a PATH on a domain that is mostly not a
        # board at all.
        ("https://www.google.com/about/careers/applications/jobs/results", "google"),
        ("https://www.google.com/about/careers/applications/", "google"),
        ("https://www.google.com/about/careers", "google"),
        ("https://google.com/about/careers/", "google"),
    ],
)
def test_googles_careers_path_names_google(url, expected):
    assert match_careers_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://www.google.com/",
        "https://www.google.com/maps",
        "https://www.google.com/search?q=jobs",
        "https://www.google.com/about/",
        # Shares a character prefix with ``/about/careers`` and is a different page.
        # ``startswith`` alone would call this Google's job board.
        "https://www.google.com/about/careersomething",
    ],
)
def test_the_rest_of_google_com_is_not_a_job_board(url):
    assert match_careers_url(url) is None


# --- non-answers --------------------------------------------------------------

@pytest.mark.parametrize(
    "url",
    [
        "https://acme.example/careers",     # the ordinary case: not one of ours
        "https://boards.greenhouse.io/duolingo",  # an ATS board — unit 9's job
        "",
        "not a url at all",
        "amazon.jobs/en/search",            # no scheme; url_guard rejects it anyway
        "//www.amazon.jobs/en/search",      # protocol-relative: still no scheme
        "ftp://www.amazon.jobs/en/search",  # wrong scheme
        "javascript:alert(1)",
        "file:///etc/passwd",
        "https://",
        "https:///en/search",               # no host
    ],
)
def test_anything_that_is_not_one_of_the_five_is_a_non_answer(url):
    assert match_careers_url(url) is None


def test_a_non_string_is_a_non_answer_not_a_crash():
    """TOTAL BY CONTRACT — this runs on the request path of the add endpoint."""
    assert match_careers_url(None) is None  # type: ignore[arg-type]
    assert match_careers_url(12345) is None  # type: ignore[arg-type]


def test_a_malformed_ipv6_host_does_not_raise():
    """``urlsplit(...).hostname`` raises ValueError on this; the caller must not see it."""
    assert match_careers_url("https://[not:valid:ipv6/careers") is None


def test_userinfo_cannot_forge_a_match():
    """``https://www.amazon.jobs@evil.tld/`` is an EVIL.TLD fetch, not an Amazon one.

    The host is what follows the ``@``. Taking the text before it — the mistake
    ``url_guard`` documents at length — would let any URL claim to be any board.
    """
    assert match_careers_url("https://www.amazon.jobs@evil.tld/careers") is None
    # ...and the inverse is a genuine amazon.jobs fetch, so it must still match.
    assert match_careers_url("https://evil.tld@www.amazon.jobs/en/search") == "amazon"


# --- normalize_host, directly --------------------------------------------------

@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://WWW.Example.COM/x", "example.com"),
        ("https://example.com.:8443/x", "example.com"),
        ("https://www.www.example.com/x", "www.example.com"),  # ONE www label only
        ("https://wwwexample.com/x", "wwwexample.com"),        # not a www. label
        ("https://example.com/x", "example.com"),
        ("http://example.com", "example.com"),
        ("mailto:a@example.com", None),
        # The root dot comes off BEFORE the ``www.`` label, so the fully-qualified
        # spelling of a board host normalizes to the same thing the bare one does.
        ("https://www.example.com./x", "example.com"),
        # Degenerate but not a crash: ``www.`` alone is the hostname ``www`` once the
        # root dot is stripped, and ``www`` matches nothing in the table.
        ("https://www./x", "www"),
    ],
)
def test_normalize_host(url, expected):
    assert normalize_host(url) == expected


# --- checking both URLs the add path holds -------------------------------------

def test_match_any_takes_the_first_hit_and_skips_the_blanks():
    # Submitted URL misses, resolver's final URL hits (a company page that redirects
    # into one of the five).
    assert match_any_careers_url("https://acme.example/careers",
                                 "https://www.amazon.jobs/en/search") == "amazon"
    # Submitted URL hits, final URL is None (the resolver could not settle on one).
    assert match_any_careers_url("https://careers.tiktok.com/", None) == "tiktok"
    assert match_any_careers_url(None, None) is None
    assert match_any_careers_url() is None


def test_the_redirect_aliases_resolve_to_the_same_company_as_their_targets():
    """Verified live 2026-08-26 — each left-hand host really does redirect to the right.

    They are separate table entries because the add path checks the SUBMITTED url too,
    and that one has not been through anybody's redirect.
    """
    assert match_careers_url("https://careers.tiktok.com/") == \
        match_careers_url("https://lifeattiktok.com/") == "tiktok"
    assert match_careers_url("https://jobs.careers.microsoft.com/global/en/search") == \
        match_careers_url("https://apply.careers.microsoft.com/") == "microsoft"
    assert match_careers_url("https://careers.google.com/") == \
        match_careers_url("https://www.google.com/about/careers/applications/") == "google"


# --- the staleness guard -------------------------------------------------------

def test_every_script_scraper_has_its_careers_hosts_registered():
    """THE ANTI-DRIFT RAIL. A mapping that silently goes stale is how this bug recurs.

    ``SourceId``'s ``*_scraper`` members ARE the set of script-scraped companies — the
    suffix is documented there as "a custom web scraper (no vendor ATS behind it)" — and
    a sixth one added without a careers host would reintroduce exactly the defect this
    unit closes, silently, for that company only.

    Deriving the expected set rather than restating it is the point: this test cannot be
    satisfied by editing it to match.
    """
    expected = {
        value[: -len("_scraper")]
        for name, value in vars(SourceId).items()
        if not name.startswith("_") and isinstance(value, str)
        and value.endswith("_scraper")
    }
    assert expected == {"google", "apple", "microsoft", "amazon", "tiktok", "meta"}, (
        "a script scraper was added or removed — update the careers-host table too"
    )
    assert set(SCRIPT_COMPANY_CAREERS_HOSTS) == expected


def test_no_two_companies_claim_the_same_careers_host():
    """A host claimed twice makes the match order-dependent and one of the two wrong."""
    seen: dict[tuple[str, str], str] = {}
    for company_id, entries in SCRIPT_COMPANY_CAREERS_HOSTS.items():
        for entry in entries:
            assert entry not in seen, f"{entry} claimed by {seen.get(entry)} and {company_id}"
            seen[entry] = company_id


def test_every_declared_host_is_already_normalized():
    """The table is compared against ``normalize_host`` output, so an entry that is not

    itself normalized (``www.amazon.jobs``, ``JOBS.APPLE.COM``, ``amazon.jobs:443``) can
    never match anything — a dead row that reads as if it works.
    """
    for company_id, entries in SCRIPT_COMPANY_CAREERS_HOSTS.items():
        for host, path_prefix in entries:
            assert normalize_host(f"https://{host}/") == host, (
                f"{company_id}: {host!r} is not in normalized form"
            )
            assert path_prefix == "" or path_prefix.startswith("/"), (
                f"{company_id}: path prefix {path_prefix!r} must start with '/'"
            )
            assert not path_prefix.endswith("/"), (
                f"{company_id}: path prefix {path_prefix!r} must not end with '/'"
            )
