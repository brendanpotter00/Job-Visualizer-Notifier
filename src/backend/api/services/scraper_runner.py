"""Async subprocess runner for Python scrapers."""

import asyncio
import logging
from datetime import datetime, timezone

from ..config import Settings

logger = logging.getLogger(__name__)


class ScraperResult:
    def __init__(self, exit_code: int, output: str, error: str, company: str, completed_at: str):
        self.exit_code = exit_code
        self.output = output
        self.error = error
        self.company = company
        self.completed_at = completed_at


async def run_scraper(config: Settings, company: str) -> ScraperResult:
    """Run a scraper as an async subprocess.

    Mirrors C# ScraperProcessRunner behavior:
    - Builds command: python run_scraper.py --company X --env Y --db-url Z --incremental --headless
    - Timeout handling with process kill
    - Captures stdout/stderr
    """
    detail_flag = ["--detail-scrape"] if config.scraper_detail_scrape else []
    args = [
        config.scraper_python_path,
        f"{config.scraper_scripts_path}/run_scraper.py",
        "--company", company,
        "--env", config.scraper_environment,
        "--db-url", config.database_url,
        "--incremental",
        "--headless",
        *detail_flag,
    ]

    logger.info("Running scraper: %s", " ".join(args))

    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        timeout_seconds = config.scraper_timeout_minutes * 60
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            logger.warning("Scraper timed out after %d minutes, killing process", config.scraper_timeout_minutes)
            process.kill()
            await process.wait()
            return ScraperResult(
                exit_code=-2,
                output="",
                error=f"Process timed out after {config.scraper_timeout_minutes} minutes",
                company=company,
                completed_at=datetime.now(timezone.utc).isoformat(),
            )

        exit_code = process.returncode or 0
        logger.info("Scraper exited with code %d", exit_code)

        return ScraperResult(
            exit_code=exit_code,
            output=stdout.decode("utf-8", errors="replace"),
            error=stderr.decode("utf-8", errors="replace"),
            company=company,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )

    except Exception as ex:
        logger.error("Failed to run scraper for %s: %s", company, ex)
        return ScraperResult(
            exit_code=-1,
            output="",
            error=str(ex),
            company=company,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
