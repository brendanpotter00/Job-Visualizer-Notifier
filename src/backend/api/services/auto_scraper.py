"""Background auto-scraper that runs on a configurable interval.

- Waits 10 seconds after startup to let the server finish initialization
- Iterates through configured companies each cycle
- Sleeps for interval_hours between cycles
"""

import asyncio
import logging

from ..config import Settings
from .scraper_lock import scraper_lock
from .scraper_runner import run_scraper

logger = logging.getLogger(__name__)


def _tail(text: str, n: int) -> str:
    """Return the last *n* lines of *text*, or all of it if shorter."""
    lines = text.rstrip("\n").splitlines()
    return "\n".join(lines[-n:]) if lines else ""


async def auto_scraper_loop(config: Settings) -> None:
    """Run scrapers in a loop. Intended to be launched as an asyncio task."""
    companies = config.companies_list
    interval_seconds = config.scraper_interval_hours * 3600

    logger.info(
        "Auto-scraper starting (companies=%s, interval=%dh)",
        companies,
        config.scraper_interval_hours,
    )

    # Wait 10 seconds before first cycle to let the app finish startup
    await asyncio.sleep(10)

    consecutive_failures = 0

    while True:
        try:
            for company in companies:
                logger.info("Starting scrape for %s", company)
                try:
                    async with scraper_lock:
                        result = await run_scraper(config, company)
                    if result.exit_code == 0:
                        logger.info("Scrape completed successfully for %s", company)
                        if result.output:
                            logger.info(
                                "Scraper output for %s (last 20 lines):\n%s",
                                company, _tail(result.output, 20),
                            )
                        if result.error:
                            logger.info(
                                "Scraper stderr for %s (last 30 lines):\n%s",
                                company, _tail(result.error, 30),
                            )
                    else:
                        logger.warning(
                            "Scrape finished with exit code %d for %s: %s",
                            result.exit_code,
                            company,
                            result.error,
                        )
                        if result.output:
                            logger.warning(
                                "Scraper stdout for %s (last 50 lines):\n%s",
                                company, _tail(result.output, 50),
                            )
                except Exception:
                    logger.exception("Unexpected error scraping %s", company)

            consecutive_failures = 0
            logger.info("Scrape cycle complete, waiting %dh before next run", config.scraper_interval_hours)
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            consecutive_failures += 1
            backoff = min(60 * (2 ** (consecutive_failures - 1)), 3600)
            logger.exception(
                "Unexpected error in auto-scraper loop (failure #%d), retrying in %ds",
                consecutive_failures, backoff,
            )
            await asyncio.sleep(backoff)
