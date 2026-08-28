"""The pure company-name matcher — ``api.services.company_name_match``.

No database, no network, no fixtures: the module is IO-free by contract, so the whole
rule is exhaustively testable as string in / id out. The router-level behaviour (nothing
created, nothing enqueued, the escape hatch) lives in ``test_user_companies_router.py``.

The fixture below is the REAL published fleet as measured against prod on 2026-08-27 —
name lengths, English-word collisions and the ``gm``/``figma`` substring pair are all
properties of that data, not of a corpus invented to make the rule look good.
"""

from __future__ import annotations

import pytest

from api.services.company_name_match import (
    build_name_index,
    match_name_in_any_url,
    match_name_in_url,
    normalize_name,
    registrable_domain,
    registrable_label,
)

#: A representative slice of the 133 enabled public rows, chosen to carry every hazard
#: the real table has: two-character names (``gm``), three- and four-character names,
#: ordinary English words (``block``, ``light``, ``console``, ``merge``, ``snap``), an
#: id that differs from the display name (``andurilindustries``/``Anduril``), a display
#: name with spaces (``Hudson River Trading``) and the ``gm``-inside-``figma`` pair.
PUBLISHED = [
    ("spotify", "Spotify"),
    ("dropbox", "Dropbox"),
    ("figma", "Figma"),
    ("gm", "General Motors"),
    ("snap", "Snap"),
    ("block", "Block"),
    ("light", "Light"),
    ("console", "Console"),
    ("merge", "Merge"),
    ("cursor", "Cursor"),
    ("reducto", "Reducto"),
    ("anthropic", "Anthropic"),
    ("andurilindustries", "Anduril"),
    ("hrt", "Hudson River Trading"),
    ("thinkingmachines", "Thinking Machines"),
    ("judgmentlabs", "Judgment Labs"),
    ("modal", "Modal Labs"),
    ("gem", "Gem"),
    ("wispr-flow", "Wispr Flow"),
    # The five with a declared careers-host table. Present so the exclusion is under
    # test with real rows rather than by their absence.
    ("amazon", "Amazon"),
    ("apple", "Apple"),
    ("google", "Google"),
    ("microsoft", "Microsoft"),
    ("tiktok", "TikTok"),
]

INDEX = build_name_index(PUBLISHED)


def match(url: str, index=None) -> str | None:
    return match_name_in_url(url, INDEX if index is None else index)


# ─────────────────────────── the case this unit exists for ───────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "https://www.lifeatspotify.com/jobs",
        "https://lifeatspotify.com/",
        "https://lifeatspotify.com/jobs/search?q=engineer",
        "https://LifeAtSpotify.com/jobs",
        "https://careers.lifeatspotify.com/jobs",
        "https://www.lifeatspotify.com./jobs",
        "https://lifeatspotify.com:443/jobs",
        "https://evil.tld@www.lifeatspotify.com/jobs",
    ],
)
def test_lifeatspotify_names_spotify_in_every_spelling(url):
    """The owner's case. ``lifeat`` is a declared affix and ``spotify`` is published,
    so the whole label decomposes exactly — no containment involved."""
    assert match(url) == "spotify"


@pytest.mark.parametrize(
    "url",
    [
        "https://jobs.cisco.com/jobs/SearchJobs/",
        "https://careers.cisco.com/",
        "https://www.cisco.com/careers",
        "https://lifeatcisco.com/",
        "https://ciscojobs.com/",
        "https://joincisco.com/",
    ],
)
def test_a_cisco_vanity_url_names_the_published_cisco(url):
    """``cisco`` is five characters — the shortest name the affix rung is allowed to
    find, and the reason ``_MIN_AFFIX_CORE_LEN`` is 5 rather than 6."""
    index = build_name_index(PUBLISHED + [("cisco", "Cisco")])
    assert match_name_in_url(url, index) == "cisco"


def test_cisco_is_not_claimed_when_we_do_not_publish_it():
    """The table is the fleet, not a guess list. We do not publish Cisco today."""
    assert match("https://jobs.cisco.com/jobs/SearchJobs/") is None


# ───────────────────────────── the false-positive class ──────────────────────────────


def test_dropbox_is_dropbox_and_never_box():
    """THE collision the brief names. ``dropbox`` contains ``box``, and ``drop`` is not
    a careers affix, so the only reading is the exact one."""
    index = build_name_index(PUBLISHED + [("box", "Box")])
    assert match_name_in_url("https://www.dropbox.com/jobs", index) == "dropbox"
    # And Box itself still resolves — refusing the substring did not cost the real hit.
    assert match_name_in_url("https://www.box.com/careers", index) == "box"


def test_box_is_not_claimed_by_dropbox_when_only_dropbox_is_published():
    """The mirror image: with Box unpublished, ``box.com`` is not "we already track
    Dropbox". A short name inside a longer published one is not evidence either way."""
    assert match("https://www.box.com/careers") is None


@pytest.mark.parametrize(
    "url,why",
    [
        ("https://www.figma.com/careers",
         "'gm' (General Motors) is a substring of 'figma' in the REAL published table"),
        ("https://www.thinkingmachines.ai/careers", "'gm' is inside 'thinkingmachines'"),
        ("https://judgmentlabs.ai/careers", "'gm' is inside 'judgmentlabs'"),
    ],
)
def test_a_short_name_hiding_inside_a_longer_one_never_wins(url, why):
    """These three are the ``box``/``dropbox`` class as it exists in prod TODAY. A naive
    containment rule answers "General Motors" for ``figma.com``."""
    assert match(url) != "gm", why
    assert match(url) is not None, "the exact reading must still resolve"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.teamsnap.com/careers",   # a real, different company; 'team' + 'snap'
        "https://www.blockchain.com/careers",  # 'block' + 'chain'
        "https://flashlight.com/careers",      # 'flash' + 'light'
        "https://consoles.example.com/jobs",   # subdomain, and not a bare 'console'
        "https://emerge.com/careers",          # 'e' + 'merge'
        "https://sunlight.com/careers",
    ],
)
def test_an_undeclared_word_around_a_published_name_is_not_a_match(url):
    """The safety property in one sentence: the label must decompose into a DECLARED
    affix plus a published name, not merely contain one."""
    assert match(url) is None


def test_short_names_only_match_as_the_whole_label():
    """``gm.com`` is General Motors. ``lifeatgm.com`` is a coin flip, so we decline."""
    assert match("https://gm.com/careers") == "gm"
    assert match("https://lifeatgm.com/careers") is None
    assert match("https://getsnap.com/careers") is None
    assert match("https://snap.com/careers") == "snap"


# ─────────────────────────────── ATS hosts never match ───────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "https://boards.greenhouse.io/spotify",
        "https://job-boards.greenhouse.io/anthropic",
        "https://boards-api.greenhouse.io/v1/boards/spotify/jobs",
        "https://jobs.lever.co/spotify",
        "https://jobs.lever.co/anything",
        "https://api.lever.co/v0/postings/spotify",
        "https://jobs.ashbyhq.com/cursor",
        "https://api.ashbyhq.com/posting-api/job-board/cursor",
        "https://acme.wd1.myworkdayjobs.com/en-US/careers",
        "https://gm.wd5.myworkdayjobs.com/Careers_GM",
        "https://jobs.gem.com/retool",
        "https://gem.com/careers",
        "https://netflix.eightfold.ai/careers",
        "https://www.linkedin.com/company/spotify/jobs/",
        "https://www.indeed.com/cmp/Spotify/jobs",
        "https://builtin.com/company/spotify",
    ],
)
def test_an_ats_or_aggregator_host_never_name_matches(url):
    """``jobs.lever.co`` reduces to the label ``lever``; the day we publish a company
    called Lever, every Lever board in the world would become "we already track Lever".
    Rung 1 owns these URLs, so this rung must say nothing about them — including for the
    company whose name IS the ATS (``gem.com``)."""
    assert match(url) is None


# ──────────────────────── the five with an exact host table ──────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        # The exact careers hosts — rung 2 answers these, before this rung runs.
        "https://www.amazon.jobs/en/search",
        "https://jobs.apple.com/en-us/search",
        "https://careers.google.com/jobs",
        "https://jobs.careers.microsoft.com/global/en/search",
        "https://lifeattiktok.com/search",
        # And rung 2's deliberate REFUSALS, which this rung must not overturn.
        "https://learn.microsoft.com/en-us/training/",
        "https://www.microsoft.com/en-us/microsoft-365",
        "https://aws.amazon.com/careers/",
        "https://www.google.com/maps",
        "https://www.apple.com/careers/",
    ],
)
def test_the_five_script_boards_are_left_entirely_to_the_host_table(url):
    """Amazon, Apple, Google, Microsoft and TikTok are excluded from the name index.

    They already have an EXACT declared host table, and that table's ``None`` answers are
    considered judgements — ``learn.microsoft.com`` is a training site and
    ``google.com/maps`` is a map. A guess layered on top of an exact check can only add
    false positives."""
    assert match(url) is None


# ──────────────────────────────── shape and totality ────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "cursor.com/careers",           # no scheme — url_guard rejects it long before us
        "ftp://cursor.com/careers",
        "javascript:alert(1)",
        "https://",
        "https://localhost/careers",    # single label, no registrable name
        "https://127.0.0.1:8000/jobs",  # IPv4 literal
        "https://[::1]:8000/jobs",
        "https://[not-ipv6/jobs",
    ],
)
def test_a_url_with_no_name_in_it_is_a_non_answer_not_an_error(url):
    """TOTAL BY CONTRACT — this runs on the request path of the one endpoint the Add
    Companies page cannot live without, on a string a user pasted. Nothing raises."""
    assert match(url) is None


def test_a_subdomain_is_never_searched_for_a_name():
    """A subdomain is chosen by whoever owns the domain. If we searched subdomains, any
    host could claim any identity by naming a label after it."""
    assert match("https://spotify.some-aggregator.example/jobs") is None
    assert match("https://cursor.not-a-company.example/careers") is None


def test_the_registrable_label_survives_a_compound_suffix():
    assert registrable_label("careers.acme.co.uk") == "acme"
    assert registrable_label("jobs.cisco.com") == "cisco"
    assert registrable_label("amazon.jobs") == "amazon"
    assert registrable_label("localhost") is None
    assert registrable_domain("jobs.lever.co") == "lever.co"
    assert registrable_domain("careers.acme.co.uk") == "acme.co.uk"


def test_punctuation_in_a_name_meets_punctuation_in_a_domain():
    """``Wispr Flow`` / ``wispr-flow`` / ``wisprflow.com`` are one company."""
    assert normalize_name("Wispr Flow") == "wisprflow"
    assert normalize_name("wispr-flow") == "wisprflow"
    assert match("https://wisprflow.ai/careers") == "wispr-flow"
    assert match("https://wispr-flow.com/careers") == "wispr-flow"


def test_both_the_id_and_the_display_name_are_names():
    """Neither field alone is what people put in a domain: Anduril's id is
    ``andurilindustries`` and their site is ``anduril.com``; General Motors' display
    name is two words and their site is ``gm.com``."""
    assert match("https://www.anduril.com/careers/") == "andurilindustries"
    assert match("https://andurilindustries.com/careers") == "andurilindustries"
    assert match("https://gm.com/careers") == "gm"
    assert match("https://www.generalmotors.com/careers") == "gm"
    assert match("https://www.hudsonrivertrading.com/careers/") == "hrt"


def test_an_individual_word_of_a_display_name_is_not_a_name():
    """Only the WHOLE normalized display name is a key. Otherwise ``general``,
    ``trading``, ``labs`` and ``machines`` become company names."""
    assert match("https://generaltrading.com/careers") is None
    assert match("https://machines.com/careers") is None
    assert match("https://labs.example.com/careers") is None


def test_an_ambiguous_label_is_refused_rather_than_guessed():
    """Two different companies, equally good readings of the same label. The honest
    answer is no answer — the URL takes the ordinary path."""
    index = build_name_index([("acmejobs", "Acme Jobs"), ("acme", "Acme")])
    # 'acmejobs' reads exactly as Acme Jobs (tier 1) — the stronger evidence wins,
    # so this is NOT ambiguous.
    assert match_name_in_url("https://acmejobs.com/careers", index) == "acmejobs"
    # But two companies whose names normalize identically cannot be told apart.
    tie = build_name_index([("acme-one", "Acme"), ("acme-two", "Acme")])
    assert match_name_in_url("https://acme.com/careers", tie) is None


def test_the_longer_reading_wins_when_one_company_matches_twice():
    """``modallabs`` and ``modal`` are both Modal Labs; the exact label is the answer,
    and one company matching two ways is not ambiguity."""
    assert match("https://modallabs.com/careers") == "modal"
    assert match("https://modal.com/careers") == "modal"


def test_a_company_we_do_not_publish_is_never_invented():
    assert match("https://www.tesla.com/careers") is None
    assert match("https://lifeatuber.com/") is None
    assert match("https://joinshopify.com/") is None


def test_either_url_can_carry_the_name():
    """The submitted URL and the resolver's final URL are different strings and the name
    can be in either — a vanity host that lands on a bare CDN shell only has it in the
    first, an aggregator link that redirects to the company site only in the second."""
    assert match_name_in_any_url(
        ["https://www.lifeatspotify.com/jobs", "https://cdn.example/shell"], INDEX
    ) == "spotify"
    assert match_name_in_any_url(
        ["https://hiring.example/x", "https://www.lifeatspotify.com/jobs"], INDEX
    ) == "spotify"
    assert match_name_in_any_url([None, None], INDEX) is None
    assert match_name_in_any_url([], INDEX) is None


def test_the_index_skips_rows_with_no_usable_name():
    index = build_name_index([("", "Nameless"), ("ok-co", ""), ("dashes", "---")])
    assert index.get("") is None
    assert match_name_in_url("https://okco.com/careers", index) == "ok-co"
