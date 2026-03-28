"""Tests for the background auto-scraper loop."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from api.config import Settings
from api.services.auto_scraper import auto_scraper_loop
from api.services.scraper_runner import ScraperResult


@pytest.fixture
def config():
    """Minimal Settings for auto-scraper tests."""
    return Settings(
        database_url="postgresql://test:test@localhost/test",
        scraper_environment="test",
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

        The outer except is triggered by making the interval sleep raise a
        RuntimeError (simulating an unexpected failure outside the per-company
        inner try/except). Backoff sleeps are distinguished by value (>=60).
        """
        sleep_args = []
        backoff_count = 0

        async def mock_sleep(seconds):
            nonlocal backoff_count
            sleep_args.append(seconds)
            if seconds == 10:
                # Startup delay -- let it pass
                return
            if seconds == config.scraper_interval_hours * 3600:
                # The post-cycle interval sleep -- make it fail to trigger outer except
                raise RuntimeError("simulated interval sleep failure")
            if seconds >= 60:
                # This is a backoff sleep
                backoff_count += 1
                if backoff_count >= 3:
                    raise asyncio.CancelledError

        async def mock_run(cfg, company):
            return ScraperResult(
                exit_code=0, output="ok", error="", company=company,
                completed_at="2025-01-15T00:00:00Z",
            )

        with patch("api.services.auto_scraper.run_scraper", side_effect=mock_run), \
             patch("asyncio.sleep", side_effect=mock_sleep):
            with pytest.raises(asyncio.CancelledError):
                await auto_scraper_loop(config)

        backoff_sleeps = [s for s in sleep_args if s >= 60 and s != config.scraper_interval_hours * 3600]
        assert len(backoff_sleeps) >= 3
        assert backoff_sleeps[0] == 60
        assert backoff_sleeps[1] == 120
        assert backoff_sleeps[2] == 240
