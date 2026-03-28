"""Tests for the background auto-scraper loop."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.config import Settings
from api.services.auto_scraper import auto_scraper_loop
from api.services.scraper_runner import ScraperResult


@pytest.fixture
def config():
    """Minimal Settings for auto-scraper tests."""
    return Settings(
        database_url="postgresql://test:test@localhost/test",
        scraper_environment="local",
        scraper_companies="google,apple",
        scraper_interval_hours=1,
        scraper_timeout_minutes=5,
        scraper_scripts_path="/fake/scripts",
        scraper_python_path="python3",
    )


def _ok_result(company: str) -> ScraperResult:
    return ScraperResult(
        exit_code=0, output="ok", error="", company=company,
        completed_at="2025-01-15T00:00:00Z",
    )


# -- Company iteration --


class TestCompanyIteration:
    @pytest.mark.asyncio
    async def test_all_companies_scraped(self, config):
        call_log = []

        async def mock_run(cfg, company):
            call_log.append(company)
            return _ok_result(company)

        call_count = 0

        async def mock_sleep(seconds):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError

        with patch("api.services.auto_scraper.run_scraper", side_effect=mock_run), \
             patch("asyncio.sleep", side_effect=mock_sleep):
            with pytest.raises(asyncio.CancelledError):
                await auto_scraper_loop(config)

        assert call_log == ["google", "apple"]


# -- Continues on failure --


class TestContinuesOnFailure:
    @pytest.mark.asyncio
    async def test_continues_after_company_failure(self, config):
        call_log = []

        async def mock_run(cfg, company):
            call_log.append(company)
            if company == "google":
                raise RuntimeError("boom")
            return _ok_result(company)

        call_count = 0

        async def mock_sleep(seconds):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError

        with patch("api.services.auto_scraper.run_scraper", side_effect=mock_run), \
             patch("asyncio.sleep", side_effect=mock_sleep):
            with pytest.raises(asyncio.CancelledError):
                await auto_scraper_loop(config)

        assert "google" in call_log
        assert "apple" in call_log


# -- Cancellation --


class TestCancellation:
    @pytest.mark.asyncio
    async def test_cancelled_during_sleep(self, config):
        async def mock_run(cfg, company):
            return _ok_result(company)

        async def mock_sleep(seconds):
            raise asyncio.CancelledError

        with patch("api.services.auto_scraper.run_scraper", side_effect=mock_run), \
             patch("asyncio.sleep", side_effect=mock_sleep):
            with pytest.raises(asyncio.CancelledError):
                await auto_scraper_loop(config)

    @pytest.mark.asyncio
    async def test_cancelled_during_scrape(self, config):
        async def mock_run(cfg, company):
            raise asyncio.CancelledError

        with patch("api.services.auto_scraper.run_scraper", side_effect=mock_run), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(asyncio.CancelledError):
                await auto_scraper_loop(config)


# -- Startup delay --


class TestStartupDelay:
    @pytest.mark.asyncio
    async def test_startup_delay_is_10_seconds(self, config):
        sleep_calls = []

        async def mock_sleep(seconds):
            sleep_calls.append(seconds)
            if len(sleep_calls) == 1:
                raise asyncio.CancelledError

        with patch("api.services.auto_scraper.run_scraper", new_callable=AsyncMock), \
             patch("asyncio.sleep", side_effect=mock_sleep):
            with pytest.raises(asyncio.CancelledError):
                await auto_scraper_loop(config)

        assert sleep_calls[0] == 10


# -- Exponential backoff --


class TestBackoff:
    @pytest.mark.asyncio
    async def test_backoff_increases_on_repeated_failure(self, config):
        """Outer-loop errors should trigger exponential backoff.

        An error in the for-loop body (outside the inner try/except) prevents
        the loop from completing, so consecutive_failures is never reset and
        backoff escalates: 60 → 120 → 240.
        """
        sleep_args = []
        backoff_count = 0

        async def mock_sleep(seconds):
            nonlocal backoff_count
            sleep_args.append(seconds)
            if seconds == 10:
                return
            if seconds >= 60:
                backoff_count += 1
                if backoff_count >= 3:
                    raise asyncio.CancelledError

        # Patch the logger so the "Starting scrape for" log raises before
        # entering the inner try/except — this triggers the outer except.
        with patch("api.services.auto_scraper.run_scraper") as mock_run, \
             patch("api.services.auto_scraper.logger") as mock_logger, \
             patch("asyncio.sleep", side_effect=mock_sleep):

            def info_side_effect(msg, *args):
                if "Starting scrape for" in str(msg):
                    raise RuntimeError("simulated outer-loop error")

            mock_logger.info = MagicMock(side_effect=info_side_effect)
            mock_logger.exception = MagicMock()

            with pytest.raises(asyncio.CancelledError):
                await auto_scraper_loop(config)

            mock_run.assert_not_called()

        backoff_sleeps = [s for s in sleep_args if s >= 60]
        assert len(backoff_sleeps) >= 3
        assert backoff_sleeps[0] == 60
        assert backoff_sleeps[1] == 120
        assert backoff_sleeps[2] == 240
