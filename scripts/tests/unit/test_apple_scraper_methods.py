"""
Unit tests for AppleJobsScraper methods that override BaseScraper behavior.

These pin behavioral choices that don't have a fixture-level test elsewhere —
in particular the Apple-specific page.goto strategy, which is load-bearing for
the appleScraperHangFix work (see docs/implementations/appleScraperHangFix/PLAN.md).
"""

import asyncio
import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from apple_jobs_scraper.scraper import AppleJobsScraper, _APPLE_GOTO_WAIT_UNTIL


@pytest.fixture
def scraper():
    """AppleJobsScraper with __init__ skipped — we only need methods."""
    return AppleJobsScraper.__new__(AppleJobsScraper)


@pytest.fixture
def page():
    p = MagicMock()
    p.goto = AsyncMock()
    return p


class TestNavigateToPage:
    """The Apple `navigate_to_page` override is the load-bearing override
    for the page.goto strategy: networkidle never fires within 30 s on
    Apple's analytics-chatty careers site, so we go straight to
    domcontentloaded. A regression that drops this override (e.g. someone
    deleting the method "because the base class works") would silently
    re-introduce ~30 s of dead time per pagination step."""

    def test_apple_wait_until_constant_is_domcontentloaded(self):
        """Pin the constant value so the test below catches a sneaky
        constant rename without changing this assertion."""
        assert _APPLE_GOTO_WAIT_UNTIL == "domcontentloaded"

    @pytest.mark.asyncio
    async def test_navigate_to_page_uses_domcontentloaded(self, scraper, page):
        await scraper.navigate_to_page(page, "https://jobs.apple.com/x", timeout=30000)

        page.goto.assert_awaited_once()
        kwargs = page.goto.call_args.kwargs
        assert kwargs["wait_until"] == "domcontentloaded"
        assert kwargs["timeout"] == 30000

    @pytest.mark.asyncio
    async def test_navigate_to_page_passes_through_timeout(self, scraper, page):
        await scraper.navigate_to_page(page, "https://jobs.apple.com/x", timeout=12345)

        kwargs = page.goto.call_args.kwargs
        assert kwargs["timeout"] == 12345

    @pytest.mark.asyncio
    async def test_navigate_to_page_retries_once_on_first_failure(self, scraper, page):
        """Mirrors BaseScraper.navigate_to_page: a single retry survives
        transient TLS/connection blips. Without the retry,
        scrape_query's outer consecutive_errors loop walks to the next
        page number and silently drops the failed page's ~20 jobs.
        """
        attempts = {"n": 0}

        async def _goto(*args, **kwargs):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("transient TLS blip")

        page.goto = AsyncMock(side_effect=_goto)

        await scraper.navigate_to_page(page, "https://jobs.apple.com/x")

        assert attempts["n"] == 2
        # Both attempts use the same wait_until — Apple's analytics chatter
        # makes networkidle-then-domcontentloaded a non-strategy here.
        for call in page.goto.call_args_list:
            assert call.kwargs["wait_until"] == "domcontentloaded"

    @pytest.mark.asyncio
    async def test_navigate_to_page_propagates_second_failure(self, scraper, page):
        """If both attempts fail, the exception must reach `scrape_query`
        so its consecutive_errors loop can record and bound the failure.
        Swallowing it here would let the scraper proceed against an
        unloaded page and produce empty job extractions silently.
        """
        page.goto = AsyncMock(side_effect=RuntimeError("connection refused"))

        with pytest.raises(RuntimeError, match="connection refused"):
            await scraper.navigate_to_page(page, "https://jobs.apple.com/x")

        assert page.goto.await_count == 2


class TestTransformPostedDate:
    """U5b — list mode's posted date used to be dropped on the floor.

    Apple has two collection paths and they name the field differently:
    detail mode (`api_client.parse_job_details`) emits `posted_on` from
    `postDateInGMT`; list mode (`parser.parse_job_element`) emits
    `posted_date` scraped off the card. `transform_to_job_model` read only
    `posted_on`, so every list-mode date was silently discarded — a
    non-detail Apple run stored `posted_on = NULL` for the whole board.
    """

    def test_list_mode_card_date_is_stored_normalised_and_seeds_first_seen_at(
        self, scraper
    ):
        """U5b stored the card's date; U3 makes it reach the sort key too.

        The raw card string was accepted by ``posted_on`` (a TIMESTAMPTZ —
        Postgres reads "Jan 15, 2026") but rejected by ``shared/posted_date.py``,
        which is strict on purpose, so ``first_seen_at`` fell back to first
        sight. ``parser.parse_card_posted_date`` normalises at the boundary that
        derives both, following the precedent set by
        ``amazon_jobs_scraper.api_client.parse_posted_date`` rather than teaching
        the shared parser to read human dates (``03/04/2026`` is two different
        days depending on locale — the strictness is the point).
        """
        # Exactly what `parser.parse_job_element` returns. Its card regex is
        # `([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})`, so this is the real shape — and
        # it can only ever produce an unambiguous English three-letter month.
        job = scraper.transform_to_job_model({
            "id": "200640732-0836",
            "title": "Software QA Engineer",
            "job_url": "https://jobs.apple.com/en-us/details/200640732-0836/x",
            "posted_date": "Jan 15, 2026",
            "company": "apple",
        })

        assert job.posted_on == "2026-01-15"
        assert job.first_seen_at == "2026-01-15T00:00:00+00:00", (
            "the card's date reached posted_on but not first_seen_at — the fix "
            "is half-done again"
        )

    def test_detail_mode_date_still_wins(self, scraper):
        """`posted_on` (postDateInGMT) is the better source — when both are
        present the detail value must not be shadowed by the card text."""
        job = scraper.transform_to_job_model({
            "id": "200640732-0836",
            "title": "Software QA Engineer",
            "job_url": "https://jobs.apple.com/en-us/details/200640732-0836/x",
            "posted_on": "2026-01-15T10:30:00Z",
            "posted_date": "Jan 15, 2026",
            "company": "apple",
        })

        assert job.posted_on == "2026-01-15T10:30:00Z"

    def test_no_date_from_either_source_stays_none(self, scraper):
        """A board that publishes nothing must give NULL, never `now()`."""
        job = scraper.transform_to_job_model({
            "id": "200640732-0836",
            "title": "Software QA Engineer",
            "job_url": "https://jobs.apple.com/en-us/details/200640732-0836/x",
            "company": "apple",
        })

        assert job.posted_on is None
        assert job.created_at is not None


class TestDetailPostedDateIsValidatedAndLoud:
    """The detail half of the pair, held to the same bar as the list half.

    `parse_card_posted_date` validates + warns for `posted_date`. `postDateInGMT`
    was passed straight through: never checked, never logged. That is the exact
    failure that function's docstring already describes, on the other feed — a
    string the TIMESTAMPTZ `posted_on` accepts but `shared/posted_date.py`
    rejects reaches diagnostics and silently misses `first_seen_at`.

    Prod is ISO today (9,949 of 9,990 rows), so this is about what happens the
    day it isn't.
    """

    LOGGER = "apple_jobs_scraper.scraper"

    def _records(self, caplog, level):
        return [r for r in caplog.records if r.levelname == level]

    def _job(self, **extra):
        return {
            "id": "200640732-0836",
            "title": "Software QA Engineer",
            "job_url": "https://jobs.apple.com/en-us/details/200640732-0836/x",
            "company": "apple",
            **extra,
        }

    def test_unreadable_detail_date_warns_and_does_not_reach_posted_on(
        self, scraper, caplog
    ):
        """The whole finding in one assertion: a value the column would have
        swallowed must not reach it silently. Here there is no card date either,
        so the row degrades to NULL — loudly."""
        with caplog.at_level(logging.WARNING, logger=self.LOGGER):
            job = scraper.transform_to_job_model(
                self._job(posted_on="Posted 30+ Days Ago")
            )

        assert job.posted_on is None
        warnings = self._records(caplog, "WARNING")
        assert len(warnings) == 1, warnings
        assert "Posted 30+ Days Ago" in warnings[0].getMessage()

    def test_unreadable_detail_date_never_reaches_first_seen_at(self, scraper, caplog):
        """Belt and braces on the half that actually hurts. `posted_on` and
        `first_seen_at` must tell the same story — the old code could put a
        string in one and not the other."""
        with caplog.at_level(logging.WARNING, logger=self.LOGGER):
            job = scraper.transform_to_job_model(
                self._job(posted_on="whenever we felt like it")
            )

        assert job.posted_on is None
        assert job.first_seen_at == job.created_at

    def test_unreadable_detail_date_still_falls_back_to_the_card(self, scraper, caplog):
        """Warning is not the same as discarding. A detail value we cannot read
        must not cost us the card date we CAN read — that fallback is the
        behaviour the old `or` chain had and it is worth keeping."""
        with caplog.at_level(logging.WARNING, logger=self.LOGGER):
            job = scraper.transform_to_job_model(
                self._job(posted_on="not a date", posted_date="Jan 15, 2026")
            )

        assert job.posted_on == "2026-01-15"
        assert job.first_seen_at == "2026-01-15T00:00:00+00:00"
        assert len(self._records(caplog, "WARNING")) == 1

    def test_empty_detail_date_is_distinguishable_from_a_list_mode_row(
        self, scraper, caplog
    ):
        """The `or` short-circuit. `"" or card` and `missing-key -> card` produced
        the identical outcome and the identical (empty) log, so a board that
        started emitting `""` for every job read as a plain list run: no signal
        anywhere, every date NULL, `first_seen_at` back to "posted today"
        board-wide. Presence of the key now decides, so the two cases separate.
        """
        with caplog.at_level(logging.INFO, logger=self.LOGGER):
            detail_empty = scraper.transform_to_job_model(self._job(posted_on=""))
        empty_records = self._records(caplog, "INFO")

        caplog.clear()
        with caplog.at_level(logging.INFO, logger=self.LOGGER):
            list_mode = scraper.transform_to_job_model(self._job())
        list_records = self._records(caplog, "INFO")

        assert detail_empty.posted_on is None
        assert list_mode.posted_on is None
        # Same stored value, different story — and only one of them is silent.
        assert len(empty_records) == 1, empty_records
        assert list_records == []

    def test_good_detail_date_is_silent_and_kept_verbatim(self, scraper, caplog):
        """The 9,949-row case. Apple's own string is stored unchanged, and
        nothing is logged."""
        with caplog.at_level(logging.INFO, logger=self.LOGGER):
            job = scraper.transform_to_job_model(
                self._job(
                    posted_on="2026-07-29T03:01:01.898+00:00",
                    posted_date="Jul 29, 2026",
                )
            )

        assert job.posted_on == "2026-07-29T03:01:01.898+00:00"
        # `effective_posted_date` round-trips through a datetime, so it pads the
        # microseconds — same instant, and the reason `posted_on` keeps the raw
        # string while `first_seen_at` carries the parser's rendering.
        assert job.first_seen_at == "2026-07-29T03:01:01.898000+00:00"
        assert caplog.records == []

    def test_detail_fetch_failure_falls_back_silently(self, scraper, caplog):
        """`_fetch_job_details` yields `{**job_card, "_detail_fetch_failed": True}`
        with no `posted_on` key at all — 41 of 9,990 prod rows. It already logged
        the fetch failure; the date path must not log it a second time."""
        with caplog.at_level(logging.INFO, logger=self.LOGGER):
            job = scraper.transform_to_job_model(
                self._job(posted_date="Jan 15, 2026", _detail_fetch_failed=True)
            )

        assert job.posted_on == "2026-01-15"
        assert caplog.records == []
