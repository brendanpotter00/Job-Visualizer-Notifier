"""Async subprocess runner for Python scrapers."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from ..config import Settings

logger = logging.getLogger(__name__)


@dataclass
class ScraperResult:
    exit_code: int
    output: str
    error: str
    company: str
    completed_at: str


async def run_scraper(config: Settings, company: str) -> ScraperResult:
    """Run a scraper as an async subprocess.

    Builds command: python run_scraper.py --company X --env Y --db-url Z --incremental --headless [--detail-scrape]
    Manages timeout with process kill and captures stdout/stderr.
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

    # Redact --db-url value to avoid logging credentials
    safe_args = []
    skip_next = False
    for arg in args:
        if skip_next:
            safe_args.append("***REDACTED***")
            skip_next = False
        elif arg == "--db-url":
            safe_args.append(arg)
            skip_next = True
        else:
            safe_args.append(arg)
    logger.info("Running scraper: %s", " ".join(safe_args))

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

        exit_code = process.returncode if process.returncode is not None else -3
        logger.info("Scraper exited with code %d", exit_code)

        return ScraperResult(
            exit_code=exit_code,
            output=stdout.decode("utf-8", errors="replace"),
            error=stderr.decode("utf-8", errors="replace"),
            company=company,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )

    except (FileNotFoundError, PermissionError) as ex:
        logger.error(
            "Scraper configuration error for %s: %s: %s",
            company, type(ex).__name__, ex,
        )
        return ScraperResult(
            exit_code=-1,
            output="",
            error=f"{type(ex).__name__}: {ex}",
            company=company,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as ex:
        logger.error("Unexpected failure running scraper for %s: %s", company, ex, exc_info=True)
        return ScraperResult(
            exit_code=-1,
            output="",
            error=str(ex),
            company=company,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
