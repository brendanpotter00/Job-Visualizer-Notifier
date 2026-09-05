"""
Integration tests for MetaJobsScraper.scrape_query — the GraphQL-sniff capture.

``scrape_query`` owns the browser + response handler + settle poll, so these
tests drive it with a MOCKED page/context: a fake ``page`` whose ``.on`` captures
the response handler and whose ``.goto`` feeds that handler fake GraphQL
responses built from the committed fixture.

The headline invariant (mirrors TikTok's
``test_consecutive_error_bail_raises_instead_of_returning_partial``): an empty or
truncated capture RAISES ``MetaCaptureError`` — it never returns ``[]`` or a
partial list, which the incremental lifecycle would read as "every job is gone".
"""

import copy
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from playwright.async_api import Error as PlaywrightError

from meta_jobs_scraper import scraper as meta_scraper_module
from meta_jobs_scraper.parser import MetaCaptureError
from meta_jobs_scraper.scraper import MetaJobsScraper

WRAPPER_KEY = "job_search_with_featured_jobs_v2"
GRAPHQL_URL = "https://www.metacareers.com/api/graphql/"


class FakeResponse:
    """A minimal Playwright response double for the on_response handler."""

    def __init__(self, url: str, method: str, body: str):
        self.url = url
        self.request = MagicMock()
        self.request.method = method
        self._body = body

    async def text(self) -> str:
        return self._body


class FakePage:
    """A page whose ``.on`` captures the handler and whose ``.goto`` feeds it.

    ``goto`` delivers every configured response to the handler (as the browser
    would during navigation), then optionally raises ``goto_error`` to model a
    ``networkidle`` timeout that lands AFTER the results body already arrived.
    """

    def __init__(self, responses, goto_error=None):
        self._responses = responses
        self._goto_error = goto_error
        self._handler = None
        self.closed = False

    def on(self, event, handler):
        if event == "response":
            self._handler = handler

    async def goto(self, url, **kwargs):
        if self._handler is not None:
            for resp in self._responses:
                await self._handler(resp)
        if self._goto_error is not None:
            raise self._goto_error

    async def close(self):
        self.closed = True


def _responses_from_payloads(payloads, *, url=GRAPHQL_URL, method="POST"):
    return [FakeResponse(url, method, json.dumps(p)) for p in payloads]


def _make_scraper(fake_page):
    s = MetaJobsScraper(headless=True, detail_scrape=False)
    context = MagicMock()
    context.new_page = AsyncMock(return_value=fake_page)
    s.context = context
    return s


@pytest.fixture(autouse=True)
def _instant_sleep():
    """Make the settle poll's sleeps no-ops so tests run instantly."""
    with patch.object(meta_scraper_module.asyncio, "sleep", AsyncMock()):
        yield


@pytest.mark.asyncio
class TestFullCapture:
    async def test_returns_filtered_us_software_cards(self, meta_graphql_capture):
        page = FakePage(_responses_from_payloads(meta_graphql_capture))
        scraper = _make_scraper(page)

        cards = await scraper.scrape_query("all")

        # j1, j2, j5 are US software/data; j3 is a tech role in "London, UK", so
        # the US location filter drops it (the title filter would keep it). This
        # is the regression: the old "United States" substring dropped ALL of
        # j1/j2/j5 too, because Meta writes "Menlo Park, CA", never "…, US".
        assert {c["id"] for c in cards} == {"j1", "j2", "j5"}
        assert all(scraper.filter_location(c["location"]) for c in cards)
        assert page.closed is True

    async def test_max_jobs_slices(self, meta_graphql_capture):
        page = FakePage(_responses_from_payloads(meta_graphql_capture))
        scraper = _make_scraper(page)
        cards = await scraper.scrape_query("all", max_jobs=2)
        assert len(cards) == 2

    async def test_renamed_wrapper_still_yields_jobs(self, meta_graphql_capture):
        """Shape-based selection end-to-end: rename the wrapper to ..._v3."""
        renamed = copy.deepcopy(meta_graphql_capture)
        payload = renamed[0]["data"]
        payload["job_search_with_featured_jobs_v3"] = payload.pop(WRAPPER_KEY)

        page = FakePage(_responses_from_payloads(renamed))
        scraper = _make_scraper(page)
        cards = await scraper.scrape_query("all")
        assert {c["id"] for c in cards} == {"j1", "j2", "j5"}


@pytest.mark.asyncio
class TestRaiseInvariant:
    async def test_empty_capture_raises_never_returns_empty(self):
        """A GraphQL response with no job arrays must RAISE, not return []."""
        payloads = [{"data": {"unrelated_strip": {"foo": []}}}]
        page = FakePage(_responses_from_payloads(payloads))
        scraper = _make_scraper(page)

        with pytest.raises(MetaCaptureError, match="renamed the job-search payload"):
            await scraper.scrape_query("all")
        assert page.closed is True

    async def test_no_graphql_traffic_raises(self):
        """Zero GraphQL POSTs seen (bot wall) → raise, not []."""
        # A non-graphql response is ignored by the handler → nothing captured.
        page = FakePage(
            [FakeResponse("https://www.metacareers.com/static.js", "GET", "x")]
        )
        scraper = _make_scraper(page)
        with pytest.raises(MetaCaptureError, match="zero GraphQL POST responses"):
            await scraper.scrape_query("all")

    async def test_truncated_capture_raises(self):
        """Job arrays present but job_count says far more → raise (truncation)."""
        payloads = [
            {"data": {"w": {"all_jobs": [
                {"id": "j1", "title": "Software Engineer",
                 "locations": ["Menlo Park, CA"]}
            ]}}},
            {"data": {"filters": {"job_count": 100}}},
        ]
        page = FakePage(_responses_from_payloads(payloads))
        scraper = _make_scraper(page)
        with pytest.raises(MetaCaptureError) as exc:
            await scraper.scrape_query("all")
        assert "100" in str(exc.value)
        assert page.closed is True

    async def test_healthy_fetch_all_filtered_out_raises(self):
        """A COMPLETE fetch whose every job is non-US must RAISE, not return [].

        The completeness guard passes (parsed == advertised job_count) so the
        fetch is healthy, but the US filter keeps nothing. Meta always has open
        US tech roles, so 0 kept means the FILTER broke — returning [] here would
        read to the incremental lifecycle as "every Meta job is gone" and close
        the whole board. This is exactly the bug that shipped: a healthy 891-job
        fetch kept 0 and returned [] silently. The guard now raises instead.
        """
        payloads = [
            {"data": {"w": {"all_jobs": [
                {"id": "n1", "title": "Software Engineer, Payments",
                 "locations": ["London, UK"]},
                {"id": "n2", "title": "Data Engineer, Growth",
                 "locations": ["Singapore"]},
            ]}}},
            {"data": {"filters": {"job_count": 2}}},
        ]
        page = FakePage(_responses_from_payloads(payloads))
        scraper = _make_scraper(page)
        with pytest.raises(MetaCaptureError, match="0 survived"):
            await scraper.scrape_query("all")
        assert page.closed is True


@pytest.mark.asyncio
class TestNavErrorAndTeardown:
    async def test_nav_error_tolerated_when_capture_good(self, meta_graphql_capture):
        """goto raises PlaywrightError but the handler delivered a good payload."""
        page = FakePage(
            _responses_from_payloads(meta_graphql_capture),
            goto_error=PlaywrightError("networkidle timeout"),
        )
        scraper = _make_scraper(page)

        cards = await scraper.scrape_query("all")
        assert {c["id"] for c in cards} == {"j1", "j2", "j5"}  # nav error not surfaced
        assert page.closed is True

    async def test_page_closed_even_when_loop_raises(self, meta_graphql_capture):
        """An exception inside the poll loop still runs the finally: page.close."""
        page = FakePage(_responses_from_payloads(meta_graphql_capture))
        scraper = _make_scraper(page)

        with patch.object(
            meta_scraper_module.asyncio, "sleep",
            AsyncMock(side_effect=RuntimeError("hard failure")),
        ):
            with pytest.raises(RuntimeError, match="hard failure"):
                await scraper.scrape_query("all")
        assert page.closed is True
