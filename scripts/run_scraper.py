#!/usr/bin/env python
"""
Job scraper CLI - supports Google (and future companies)

Modes:
  - JSON mode (default): Scrapes jobs and saves to JSON file
  - Database mode (--db-url): Saves to database with incremental support
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from rich.console import Console

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import scraper modules
from scripts.google_jobs_scraper.config import DEFAULT_OUTPUT_DIR, DEFAULT_OUTPUT_FILE
from scripts.google_jobs_scraper.scraper import GoogleJobsScraper
from scripts.google_jobs_scraper.utils import get_iso_timestamp, setup_logging

# Import shared modules for database mode
from scripts.shared import database as db
from scripts.shared import incremental

console = Console()
logger = logging.getLogger(__name__)


async def run_json_mode(args):
    """Run scraper in JSON output mode (original behavior)"""
    # Import the original main module for JSON mode
    from scripts.google_jobs_scraper.main import run_scraper as run_original_scraper

    # Call original scraper logic
    await run_original_scraper(args)


async def run_database_mode(args):
    """Run scraper in database mode with incremental support"""
    company = args.company
    env = args.env
    db_url = args.db_url

    logger.info(f"Running scraper in database mode: company={company}, env={env}")

    # Connect to database
    try:
        conn = db.get_connection(db_url, env)
        db.init_schema(conn, env)
    except Exception as e:
        console.print(f"[bold red]Database connection failed: {e}[/bold red]")
        sys.exit(2)

    # Initialize scraper based on company
    if company == "google":
        scraper = GoogleJobsScraper(
            headless=args.headless,
            detail_scrape=args.detail_scrape
        )
    else:
        console.print(f"[bold red]Unsupported company: {company}[/bold red]")
        sys.exit(1)

    try:
        async with scraper:
            if args.incremental:
                # Run 5-phase incremental scrape
                console.print(f"\n[bold cyan]Running incremental scrape for {company}[/bold cyan]\n")
                result = await incremental.run_incremental_scrape(
                    scraper, conn, env, company, args.detail_scrape
                )

                console.print(f"\n[bold green]✓ Incremental scrape completed![/bold green]")
                console.print(f"Jobs seen: {result.jobs_seen}")
                console.print(f"New jobs: {result.new_jobs}")
                console.print(f"Closed jobs: {result.closed_jobs}")
                console.print(f"Details fetched: {result.details_fetched}")

            else:
                # Run full scrape and save to database
                console.print(f"\n[bold cyan]Running full scrape for {company}[/bold cyan]\n")

                # Scrape all queries
                job_cards = await scraper.scrape_all_queries(args.max_jobs)
                console.print(f"Found {len(job_cards)} jobs")

                # Fetch details if requested
                if args.detail_scrape:
                    enriched_jobs = await scraper.scrape_job_details_batch(job_cards)
                else:
                    enriched_jobs = job_cards

                # Transform and insert into database
                timestamp = get_iso_timestamp()
                for job_data in enriched_jobs:
                    try:
                        job = scraper.transform_to_job_model(job_data)
                        job.first_seen_at = timestamp
                        job.last_seen_at = timestamp
                        job.details_scraped = args.detail_scrape
                        db.insert_job(conn, job, env)
                    except Exception as e:
                        logger.error(f"Error inserting job: {e}")

                console.print(f"\n[bold green]✓ Full scrape completed![/bold green]")
                console.print(f"Inserted {len(enriched_jobs)} jobs into database")

    finally:
        conn.close()


def main():
    """CLI entry point with extended flags"""
    parser = argparse.ArgumentParser(
        description="Job scraper with JSON and database modes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # JSON mode (backwards compatible)
  python scripts/run_scraper.py --detail-scrape

  # Database mode with PostgreSQL (local development via Docker)
  python scripts/run_scraper.py --company google --env local \\
    --db-url "postgresql://postgres:postgres@localhost:5432/jobscraper"

  # Incremental mode (requires database)
  python scripts/run_scraper.py --company google --env local \\
    --db-url "postgresql://postgres:postgres@localhost:5432/jobscraper" --incremental

  # PostgreSQL production mode
  python scripts/run_scraper.py --company google --env prod \\
    --db-url "postgresql://user:pass@host:5432/jobscraper" --incremental
        """,
    )

    # Original flags (for backwards compatibility)
    parser.add_argument(
        "--output",
        "-o",
        help=f"Output JSON file path (JSON mode only, default: {DEFAULT_OUTPUT_DIR}/{DEFAULT_OUTPUT_FILE})",
    )
    parser.add_argument(
        "--queries",
        "-q",
        nargs="+",
        help="Custom search queries (default: software roles from config)",
    )
    parser.add_argument(
        "--detail-scrape",
        action="store_true",
        help="Also scrape individual job detail pages (slower but more complete data)",
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        help="Maximum number of jobs to scrape (useful for testing)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from checkpoint file if available (JSON mode only)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=True,
        help="Run browser in headless mode (default: True)",
    )
    parser.add_argument(
        "--no-headless",
        dest="headless",
        action="store_false",
        help="Show browser window (useful for debugging)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose logging output",
    )

    # New flags for database mode
    parser.add_argument(
        "--company",
        choices=["google", "all"],
        default="google",
        help="Which company scraper to run (default: google)",
    )
    parser.add_argument(
        "--env",
        choices=["local", "qa", "prod"],
        default="local",
        help="Environment (affects table naming: job_listings_ENV) (default: local)",
    )
    parser.add_argument(
        "--db-url",
        help="PostgreSQL connection URL (e.g., postgresql://user:pass@localhost:5432/dbname)",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Run in incremental mode (only fetch new jobs, requires --db-url)",
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(verbose=args.verbose)

    # Validation
    if args.incremental and not args.db_url:
        console.print("[bold red]Error: --incremental requires --db-url[/bold red]")
        sys.exit(1)

    # Route to appropriate mode
    if args.db_url:
        # Database mode
        asyncio.run(run_database_mode(args))
    else:
        # JSON mode (original behavior)
        asyncio.run(run_json_mode(args))


if __name__ == "__main__":
    main()
