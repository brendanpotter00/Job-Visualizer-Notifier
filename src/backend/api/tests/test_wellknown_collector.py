"""SOURCE 5 — the well-known paths, and the SSRF seam every one of them goes through. $0.

The source exists because ``careers.walmart.com/sitemap.xml`` enumerates 15,660 job
pages and **the careers page never requests it**. Nothing that watches network traffic
can find it; only convention can.

What is under test here is mostly what the collector must NOT do:

* ``robots.txt`` is read for ``Sitemap:`` lines and its ``Disallow`` is never a gate —
  Walmart disallows ``/api``, which is where its own careers page fetches its jobs;
* a ``<sitemapindex>`` is followed exactly ONE level, out of the same document budget,
  so an index can never multiply the cost (Atlassian's names eight children);
* every composed URL goes through ``guarded_sync_client`` — these are URLs WE built
  against a host a stranger pasted;
* 404 on all seven is not an error, it is silence, because three boards in four have no
  sitemap at all.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import pytest

from api.services.capture import sources as src
from api.services.capture.sources import (
    _MAX_SITEMAP_DOCUMENTS,
    _SPECULATIVE_PATHS,
    _WELL_KNOWN_MAX_REQUESTS,
    _WELL_KNOWN_MAX_TOTAL_BYTES,
    SitemapDocument,
    WellKnownEvidence,
    _collect_well_known_sync,
    collect_well_known,
    parse_sitemap,
    robots_sitemap_urls,
    sitemap_match,
)

_WALMART = "https://careers.walmart.com/us/en/results"
_ORIGIN = "https://careers.walmart.com"

# Measured 2026-08-29: 197 bytes, and it names the sitemap explicitly.
_WALMART_ROBOTS = (
    "User-agent: *\n"
    "Disallow: /api\n"
    "Disallow: /us/en/search-results\n"
    "\n"
    "Sitemap: https://careers.walmart.com/sitemap.xml\n"
)

_NS = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'


def _urlset(*locs: str) -> str:
    body = "".join(f"<url><loc>{loc}</loc></url>" for loc in locs)
    return f'<?xml version="1.0" encoding="UTF-8"?><urlset {_NS}>{body}</urlset>'


def _sitemapindex(*locs: str) -> str:
    body = "".join(f"<sitemap><loc>{loc}</loc></sitemap>" for loc in locs)
    return f'<?xml version="1.0" encoding="UTF-8"?><sitemapindex {_NS}>{body}</sitemapindex>'


def _walmart_job_locs(n: int) -> list[str]:
    return [
        f"{_ORIGIN}/us/en/jobs/R-10755{i:02d}-senior-software-engineer" for i in range(n)
    ]


def _fetcher(pages: dict[str, str], *, seen: list[str] | None = None):
    """A well-known fetch double: 200 + body for a known URL, 404 for everything else."""
    def _fetch(url: str, max_bytes: int) -> tuple[int, str]:
        if seen is not None:
            seen.append(url)
        body = pages.get(url)
        if body is None:
            return 404, ""
        return 200, body[:max_bytes]
    return _fetch


# --- robots.txt --------------------------------------------------------------

def test_robots_is_read_for_sitemap_lines_and_a_disallow_is_never_a_gate() -> None:
    """Walmart's ``Disallow: /api`` covers the exact GraphQL endpoint its own careers
    page calls. If a disallow were a refusal, this board — and every board that
    disallows its own API — would be untrackable for a reason that has nothing to do
    with whether we can read it."""
    assert robots_sitemap_urls(_WALMART_ROBOTS, _ORIGIN) == [
        "https://careers.walmart.com/sitemap.xml"
    ]
    # The parser has no opinion about Disallow at all — there is nothing to disable.
    assert "Disallow" not in "".join(robots_sitemap_urls(_WALMART_ROBOTS, _ORIGIN))


def test_a_relative_sitemap_line_is_resolved_against_the_origin() -> None:
    assert robots_sitemap_urls("Sitemap: /sitemaps/jobs.xml", _ORIGIN) == [
        "https://careers.walmart.com/sitemaps/jobs.xml"
    ]


def test_a_non_https_sitemap_line_is_dropped() -> None:
    """The recipe schema requires an https ``sitemap_url``, and the guarded client
    refuses plaintext anyway. Dropping it here means the refusal never has to be
    explained twice."""
    assert robots_sitemap_urls("Sitemap: http://careers.walmart.com/s.xml", _ORIGIN) == []


# --- the sitemapindex split --------------------------------------------------

def test_a_urlset_and_a_sitemapindex_are_told_apart() -> None:
    """THE BUG §4.3 NAMES. Both document types carry ``<loc>`` and they mean opposite
    things. Atlassian's ``/sitemap.xml`` is an index naming eight children, none of them
    jobs; counting those eight as eight job pages is a wrong claim about the board."""
    pages = parse_sitemap("https://x/s.xml", _urlset("https://x/a", "https://x/b"))
    assert pages is not None and pages.is_index is False and len(pages.locs) == 2

    index = parse_sitemap(
        "https://www.atlassian.com/sitemap.xml",
        _sitemapindex(*[f"https://www.atlassian.com/sitemap-{n}.xml" for n in (
            "products", "solutions", "resources", "templates",
            "customers", "company", "locales", "other",
        )]),
    )
    assert index is not None and index.is_index is True and len(index.locs) == 8


def test_a_body_that_is_not_xml_is_simply_not_a_sitemap() -> None:
    """A 200 that serves an HTML 404 page is the commonest shape of "no sitemap here"."""
    assert parse_sitemap("https://x/s.xml", "<!doctype html><html>Not found</html>") is None


def test_a_sitemapindex_is_followed_exactly_one_level_and_jobs_first() -> None:
    """One level, out of the SAME four-document budget the index came from — so an
    index can never multiply the cost — and job-shaped children first, so the budget is
    not spent on marketing pages before it reaches the postings."""
    index_url = f"{_ORIGIN}/sitemap.xml"
    child = f"{_ORIGIN}/sitemap-jobs.xml"
    seen: list[str] = []
    evidence = _collect_well_known_sync(_WALMART, _fetcher({
        f"{_ORIGIN}/robots.txt": _WALMART_ROBOTS,
        index_url: _sitemapindex(
            f"{_ORIGIN}/sitemap-marketing.xml",
            f"{_ORIGIN}/sitemap-stores.xml",
            child,
            f"{_ORIGIN}/sitemap-legal.xml",
        ),
        child: _urlset(*_walmart_job_locs(30)),
        f"{_ORIGIN}/sitemap-marketing.xml": _urlset("https://careers.walmart.com/about"),
        f"{_ORIGIN}/sitemap-stores.xml": _urlset("https://careers.walmart.com/stores"),
        f"{_ORIGIN}/sitemap-legal.xml": _urlset("https://careers.walmart.com/legal"),
    }, seen=seen))

    # The jobs child is fetched FIRST of the four children, on the hint in its name.
    fetched_children = [u for u in seen if u.startswith(f"{_ORIGIN}/sitemap-")]
    assert fetched_children[0] == child
    # ...and the index itself is carried as a source, marked as an index.
    kinds = {doc.url: doc.is_index for doc in evidence.sitemaps}
    assert kinds[index_url] is True
    assert kinds[child] is False
    # Four documents total, index included — the budget is shared, never doubled.
    assert len(evidence.sitemaps) <= _MAX_SITEMAP_DOCUMENTS
    # The budget is spent on the jobs child first; whatever is left goes on the rest, so
    # the page list is the 30 postings plus whichever marketing pages fitted.
    assert set(_walmart_job_locs(30)) <= set(evidence.page_locs)


def test_an_index_of_indexes_is_not_followed_a_second_level() -> None:
    """The budget is four documents and the second level is where an enormous (or
    hostile) site would spend all of them."""
    first = f"{_ORIGIN}/sitemap.xml"
    second = f"{_ORIGIN}/sitemap-jobs.xml"
    third = f"{_ORIGIN}/sitemap-jobs-1.xml"
    seen: list[str] = []
    _collect_well_known_sync(_WALMART, _fetcher({
        f"{_ORIGIN}/robots.txt": _WALMART_ROBOTS,
        first: _sitemapindex(second),
        second: _sitemapindex(third),
        third: _urlset(*_walmart_job_locs(5)),
    }, seen=seen))
    assert third not in seen


# --- the caps ----------------------------------------------------------------

def test_the_collector_never_makes_more_than_seven_requests() -> None:
    """Four sitemap documents + robots leaves two of the three speculative probes
    unmade, which is the right thing to cut: rows 1-3 have measured evidence behind them
    and row 4 has none."""
    seen: list[str] = []
    children = [f"{_ORIGIN}/sitemap-jobs-{i}.xml" for i in range(6)]
    pages: dict[str, str] = {
        f"{_ORIGIN}/robots.txt": _WALMART_ROBOTS,
        f"{_ORIGIN}/sitemap.xml": _sitemapindex(*children),
    }
    for url in children:
        pages[url] = _urlset(*_walmart_job_locs(3))
    _collect_well_known_sync(_WALMART, _fetcher(pages, seen=seen))
    assert len(seen) <= _WELL_KNOWN_MAX_REQUESTS


def test_the_speculative_probes_run_when_the_sitemap_budget_is_untouched() -> None:
    """They have zero measured evidence and are kept only because they are cheap — but
    "kept" has to mean they actually run when there is budget for them."""
    seen: list[str] = []
    _collect_well_known_sync(_WALMART, _fetcher({}, seen=seen))
    for path in _SPECULATIVE_PATHS:
        assert _ORIGIN + path in seen


def test_the_total_byte_ceiling_stops_the_collector_dead() -> None:
    """Twelve megabytes across every document. A board that answers each request with
    four megabytes must not be able to spend more than the ceiling however many
    documents it names."""
    huge = _urlset(*[f"{_ORIGIN}/us/en/jobs/R-{i}" for i in range(200_000)])
    assert len(huge) > _WELL_KNOWN_MAX_TOTAL_BYTES // 3
    children = [f"{_ORIGIN}/sitemap-jobs-{i}.xml" for i in range(4)]
    pages = {
        f"{_ORIGIN}/robots.txt": _WALMART_ROBOTS,
        f"{_ORIGIN}/sitemap.xml": _sitemapindex(*children),
    }
    for url in children:
        pages[url] = huge
    total = [0]

    def _fetch(url: str, max_bytes: int) -> tuple[int, str]:
        body = pages.get(url)
        if body is None:
            return 404, ""
        clipped = body[:max_bytes]
        total[0] += len(clipped)
        return 200, clipped

    _collect_well_known_sync(_WALMART, _fetch)
    assert total[0] <= _WELL_KNOWN_MAX_TOTAL_BYTES


def test_running_out_of_time_keeps_what_was_already_read() -> None:
    """MEASURED LIVE on ``www.atlassian.com`` (2026-08-29): five documents, 17.4 s —
    over the ceiling. A timeout at the coroutine boundary would throw away the
    robots.txt and the sitemaps already in hand; stopping inside the collector returns
    them and simply asks for nothing more. Degrade before you refuse.
    """
    children = [f"{_ORIGIN}/sitemap-jobs-{i}.xml" for i in range(3)]
    pages = {
        f"{_ORIGIN}/robots.txt": _WALMART_ROBOTS,
        f"{_ORIGIN}/sitemap.xml": _urlset(*_walmart_job_locs(9)),
    }
    for url in children:
        pages[url] = _urlset(*_walmart_job_locs(3))
    seen: list[str] = []
    slow = _fetcher(pages, seen=seen)

    def _slow(url: str, max_bytes: int) -> tuple[int, str]:
        time.sleep(0.05)
        return slow(url, max_bytes)

    evidence = _collect_well_known_sync(_WALMART, _slow, budget_s=0.06)
    # It STOPPED ASKING: the last speculative path is never reached, and without the
    # deadline every one of them is.
    assert f"{_ORIGIN}/api/jobs" not in seen
    assert len(seen) < _WELL_KNOWN_MAX_REQUESTS
    # ...and it kept the documents it had already read rather than losing all of them.
    assert len(evidence.sitemaps) == 1
    assert len(evidence.page_locs) == 9


def test_a_sitemap_on_another_host_is_not_followed() -> None:
    """A sitemap is a claim source, not a feed. Following a ``Sitemap:`` line to a
    third-party host buys nothing measurable and widens the set of hosts a pasted URL
    can make us fetch."""
    seen: list[str] = []
    _collect_well_known_sync(_WALMART, _fetcher({
        f"{_ORIGIN}/robots.txt": "Sitemap: https://cdn.example.com/sitemap.xml\n",
        "https://cdn.example.com/sitemap.xml": _urlset(*_walmart_job_locs(10)),
    }, seen=seen))
    assert "https://cdn.example.com/sitemap.xml" not in seen


# --- the silent miss ---------------------------------------------------------

def test_a_404_on_every_path_is_silence_not_an_error() -> None:
    """Jane Street, amazon.jobs and higher.gs.com ALL 404 on ``/sitemap.xml``, and all
    three are boards we read perfectly well. A miss must be indistinguishable from never
    having asked."""
    evidence = _collect_well_known_sync(
        "https://www.janestreet.com/join-jane-street/open-roles/", _fetcher({})
    )
    assert evidence == WellKnownEvidence()
    assert evidence.sources == ()
    assert evidence.sitemaps == ()
    assert evidence.page_locs == ()


@pytest.mark.asyncio
async def test_a_collector_that_explodes_returns_empty_evidence() -> None:
    """It runs beside the browser capture. Whatever it does, it may not be able to fail
    a discovery that the capture itself completed."""
    def _boom(url: str, max_bytes: int) -> tuple[int, str]:
        raise RuntimeError("dns exploded")

    assert await collect_well_known(_WALMART, fetch=_boom) == WellKnownEvidence()


def test_an_entry_url_with_no_origin_collects_nothing() -> None:
    assert _collect_well_known_sync("not-a-url", _fetcher({})) == WellKnownEvidence()


# --- THE SSRF SEAM -----------------------------------------------------------

def test_every_composed_url_is_fetched_through_the_guarded_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE MUTATION TARGET. These are URLs WE composed against a host a stranger pasted
    — the exact threat ``guarded_sync_client``'s per-hop revalidation, host-pin and
    IP-pin exist for. A plain ``httpx.get`` here would follow a 302 from a vanity
    careers host straight to 169.254.169.254 and hand the body back.

    Asserted on the FACTORY, which is the same seam ``_default_probe`` uses, so a
    refactor that reaches for a bare client fails this test rather than shipping.
    """
    built: list[str] = []
    requested: list[str] = []

    def _client_factory(**kwargs: Any) -> httpx.Client:
        built.append("guarded")

        def _handler(request: httpx.Request) -> httpx.Response:
            requested.append(str(request.url))
            return httpx.Response(404)

        return httpx.Client(transport=httpx.MockTransport(_handler))

    monkeypatch.setattr(src, "guarded_sync_client", _client_factory)
    _collect_well_known_sync(_WALMART, src._default_fetch)

    assert requested, "the collector composed no URLs at all"
    # One guarded client per fetch, and NOTHING fetched outside one.
    assert len(built) == len(requested)
    assert requested[0] == f"{_ORIGIN}/robots.txt"


def test_the_default_fetch_stops_reading_at_the_byte_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cap is enforced by stopping the READ, never by trusting a Content-Length
    nobody has to tell the truth about."""
    chunks_pulled = [0]

    def _client_factory(**kwargs: Any) -> httpx.Client:
        def _handler(request: httpx.Request) -> httpx.Response:
            def _stream():
                for _ in range(1_000):
                    chunks_pulled[0] += 1
                    yield b"x" * 512
            return httpx.Response(200, content=_stream())
        return httpx.Client(transport=httpx.MockTransport(_handler))

    monkeypatch.setattr(src, "guarded_sync_client", _client_factory)
    status, body = src._default_fetch(f"{_ORIGIN}/robots.txt", 1_000)
    assert status == 200
    # Stopped on the cap, not on the end of a 512 KB body: at most one chunk of
    # overshoot, and nothing like the 1,000 chunks the server was willing to send.
    assert 1_000 <= len(body) < 1_000 + 512 + 1
    assert chunks_pulled[0] < 10


# --- turning locs into a claim ----------------------------------------------

def test_the_sitemap_claim_is_derived_from_the_ids_we_actually_captured() -> None:
    """Walmart, at fixture scale. Ten captured ids, all of them present in the sitemap
    under one prefix, and 15,660 of the document's locs sitting under that same prefix.

    The prefix is AGREEMENT between the board's own URLs, not a shape anybody guessed.
    """
    job_locs = [
        f"{_ORIGIN}/us/en/jobs/R-{1075582 + i}-software-engineer" for i in range(500)
    ]
    other = [f"{_ORIGIN}/us/en/stores/{i}" for i in range(50)]
    evidence = WellKnownEvidence(
        sitemaps=(SitemapDocument(f"{_ORIGIN}/sitemap.xml",
                                  tuple(job_locs + other), False),),
    )
    match = sitemap_match(evidence, {f"R-{1075582 + i}" for i in range(10)})
    assert match is not None
    assert match.url_pattern == f"{_ORIGIN}/us/en/jobs/"
    assert match.loc_count == 500                   # the stores are NOT counted
    assert len(match.matched_ids) == 10


def test_an_id_that_appears_only_inside_a_longer_id_does_not_match() -> None:
    """A bare substring test would let the id ``107`` match inside ``R-1071`` and
    manufacture a claim about a board out of a coincidence.

    Two ids and two locs on purpose: one loose match is thrown away by the
    "agreement between at least two locs" rule anyway, so the boundary check is only
    load-bearing when enough of them line up to look like a real claim.
    """
    evidence = WellKnownEvidence(
        sitemaps=(SitemapDocument(
            f"{_ORIGIN}/sitemap.xml",
            (f"{_ORIGIN}/us/en/jobs/R-1071", f"{_ORIGIN}/us/en/jobs/R-1082"), False,
        ),),
    )
    assert sitemap_match(evidence, {"107", "108"}) is None
    # ...and the SAME two locs do match the ids they really carry.
    match = sitemap_match(evidence, {"R-1071", "R-1082"})
    assert match is not None and match.loc_count == 2


def test_an_id_that_appears_twice_matches_on_the_bounded_occurrence() -> None:
    """``R-1075582`` sits inside ``R-10755820`` earlier in the same URL. Stopping at the
    first occurrence would throw away a loc that really does carry the job."""
    locs = (
        f"{_ORIGIN}/us/en/jobs/R-10755820x-R-1075582",
        f"{_ORIGIN}/us/en/jobs/R-10755830x-R-1075583",
    )
    evidence = WellKnownEvidence(
        sitemaps=(SitemapDocument(f"{_ORIGIN}/sitemap.xml", locs, False),),
    )
    match = sitemap_match(evidence, {"R-1075582", "R-1075583"})
    assert match is not None
    assert match.url_pattern == f"{_ORIGIN}/us/en/jobs/"
    assert match.loc_count == 2


def test_one_matching_loc_is_a_coincidence_not_a_claim() -> None:
    """The prefix is derived from agreement, so it needs at least two locs to agree."""
    evidence = WellKnownEvidence(
        sitemaps=(SitemapDocument(
            f"{_ORIGIN}/sitemap.xml",
            (f"{_ORIGIN}/us/en/jobs/R-1", f"{_ORIGIN}/about"), False,
        ),),
    )
    assert sitemap_match(evidence, {"R-1"}) is None


def test_a_sitemapindex_never_supplies_a_claim() -> None:
    """Its locs are child SITEMAPS. Atlassian's eight of them are not eight jobs, and a
    shard name that happens to carry a job id would otherwise read as one.

    The child URLs here are deliberately built so that they WOULD match on every other
    rule — two ids, two agreeing locs, one shared prefix — so the only thing standing
    between a sitemap index and a fabricated count of two is knowing which document type
    you are holding.
    """
    evidence = WellKnownEvidence(
        sitemaps=(SitemapDocument(
            "https://www.atlassian.com/sitemap.xml",
            ("https://www.atlassian.com/sitemap-25583.xml",
             "https://www.atlassian.com/sitemap-25584.xml"), True,
        ),),
    )
    assert sitemap_match(evidence, {"25583", "25584"}) is None
    # The same locs in a <urlset> DO make a claim — the document type is the only
    # difference, which is the point.
    as_pages = WellKnownEvidence(
        sitemaps=(SitemapDocument(
            evidence.sitemaps[0].url, evidence.sitemaps[0].locs, False,
        ),),
    )
    assert sitemap_match(as_pages, {"25583", "25584"}) is not None


def test_a_board_whose_sitemap_carries_none_of_our_ids_makes_no_claim() -> None:
    """Atlassian's board publishes iCIMS links; its own sitemap is marketing pages. The
    honest answer is no claim at all, not a claim about the wrong thing."""
    evidence = WellKnownEvidence(
        sitemaps=(SitemapDocument(
            "https://www.atlassian.com/sitemap.xml",
            tuple(f"https://www.atlassian.com/software/{n}" for n in ("jira", "confluence")),
            False,
        ),),
    )
    assert sitemap_match(evidence, {"25583", "25584"}) is None
