"""Tests for the async scraper subprocess runner."""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.config import Settings
from api.services.scraper_runner import run_scraper


@pytest.fixture
def config():
    """Minimal Settings for scraper tests."""
    return Settings(
        database_url="postgresql://test:test@localhost/test",
        scraper_environment="test",
        scraper_scripts_path="/fake/scripts",
        scraper_python_path="/usr/bin/python3",
        scraper_timeout_minutes=5,
        scraper_detail_scrape=False,
        scraper_companies="testco",
    )


def _make_mock_process(returncode=0, stdout=b"ok\n", stderr=b""):
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.returncode = returncode
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    return proc


# -- Command construction --


class TestCommandConstruction:
    @pytest.mark.asyncio
    async def test_basic_command_args(self, config):
        mock_proc = _make_mock_process()
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc) as mock_exec:
            await run_scraper(config, "google")
            args = mock_exec.call_args[0]
            assert args[0] == "/usr/bin/python3"
            assert args[1] == "/fake/scripts/run_scraper.py"
            assert "--company" in args
            idx = args.index("--company")
            assert args[idx + 1] == "google"
            assert "--env" in args
            assert "--db-url" in args
            assert "--incremental" in args
            assert "--headless" in args
            assert "--detail-scrape" not in args

    @pytest.mark.asyncio
    async def test_detail_scrape_flag_included(self, config):
        config_detail = Settings(
            database_url="postgresql://test:test@localhost/test",
            scraper_environment="test",
            scraper_scripts_path="/fake/scripts",
            scraper_python_path="/usr/bin/python3",
            scraper_timeout_minutes=5,
            scraper_detail_scrape=True,
            scraper_companies="testco",
        )
        mock_proc = _make_mock_process()
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc) as mock_exec:
            await run_scraper(config_detail, "google")
            args = mock_exec.call_args[0]
            assert "--detail-scrape" in args


# -- Credential redaction --


class TestCredentialRedaction:
    @pytest.mark.asyncio
    async def test_db_url_not_in_log_output(self, config, caplog):
        mock_proc = _make_mock_process()
        with caplog.at_level(logging.DEBUG):
            with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
                await run_scraper(config, "google")
        for record in caplog.records:
            assert "test:test@localhost" not in record.getMessage()

    @pytest.mark.asyncio
    async def test_redacted_placeholder_in_log(self, config, caplog):
        with caplog.at_level(logging.INFO):
            mock_proc = _make_mock_process()
            with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
                await run_scraper(config, "google")
        log_text = " ".join(r.getMessage() for r in caplog.records)
        assert "***REDACTED***" in log_text


# -- Successful execution --


class TestSuccessfulExecution:
    @pytest.mark.asyncio
    async def test_success_result(self, config):
        mock_proc = _make_mock_process(returncode=0, stdout=b"scraped 10 jobs\n", stderr=b"")
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
            result = await run_scraper(config, "google")
        assert result.exit_code == 0
        assert result.company == "google"
        assert "scraped 10 jobs" in result.output
        assert result.error == ""
        assert result.completed_at

    @pytest.mark.asyncio
    async def test_nonzero_exit_code(self, config):
        mock_proc = _make_mock_process(returncode=1, stdout=b"", stderr=b"crash\n")
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
            result = await run_scraper(config, "google")
        assert result.exit_code == 1
        assert "crash" in result.error


# -- Timeout handling --


class TestTimeoutHandling:
    @pytest.mark.asyncio
    async def test_timeout_returns_exit_code_minus_2(self, config):
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError)
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
            result = await run_scraper(config, "google")

        assert result.exit_code == -2
        assert "timed out" in result.error.lower()
        assert result.company == "google"
        mock_proc.kill.assert_called_once()
        mock_proc.wait.assert_awaited_once()


# -- Exception fallback --


class TestExceptionFallback:
    @pytest.mark.asyncio
    async def test_file_not_found_error(self, config):
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            side_effect=FileNotFoundError("/usr/bin/python3"),
        ):
            result = await run_scraper(config, "google")
        assert result.exit_code == -1
        assert "FileNotFoundError" in result.error

    @pytest.mark.asyncio
    async def test_permission_error(self, config):
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            side_effect=PermissionError("permission denied"),
        ):
            result = await run_scraper(config, "google")
        assert result.exit_code == -1
        assert "PermissionError" in result.error

    @pytest.mark.asyncio
    async def test_generic_exception(self, config):
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            side_effect=RuntimeError("something unexpected"),
        ):
            result = await run_scraper(config, "google")
        assert result.exit_code == -1
        assert "something unexpected" in result.error
        assert result.company == "google"
