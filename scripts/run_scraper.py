#!/usr/bin/env python
"""
Job scraper CLI - supports Google (and future companies)

Modes:
  - JSON mode (default): Scrapes jobs and saves to JSON file
  - Database mode (--db-url): Saves to database with incremental support
"""

import argparse
import asyncio
import json
import sys
import logging
from pathlib import Path
from datetime import datetime
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeRemainingColumn

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import scraper modules
from scripts.google_jobs_scraper.scraper import GoogleJobsScraper
from scripts.apple_jobs_scraper.scraper import AppleJobsScraper
from scripts.microsoft_jobs_scraper.scraper import MicrosoftJobsScraper
from scripts.google_jobs_scraper.config import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_OUTPUT_FILE,
    CHECKPOINT_INTERVAL,
)
from scripts.google_jobs_scraper.models import ScraperOutput, CheckpointData
from scripts.google_jobs_scraper.utils import (
    setup_logging,
    save_checkpoint,
    load_checkpoint,
    delete_checkpoint,
    get_iso_timestamp,
    ensure_output_directory,
)

# Import shared modules for database mode
from scripts.shared import database as db
from scripts.shared import incremental
from scripts.shared.batch_writer import BatchWriter

console = Console()
logger = logging.getLogger(__name__)

# Scraper factory - maps company names to scraper classes
SCRAPER_CLASSES = {
    "google": GoogleJobsScraper,
    "apple": AppleJobsScraper,
    "microsoft": MicrosoftJobsScraper,
}


def should_use_database_mode(args) -> bool:
    """Determine if scraper should run in database mode based on CLI args."""
    return args.db_url is not None


async def run_json_mode(args):
    """Run scraper in JSON output mode with multi-company support"""
    company = args.company

    # For backwards compatibility, Google uses the original main module
    if company == "google":
        from scripts.google_jobs_scraper.main import run_scraper as run_original_scraper
        await run_original_scraper(args)
        return

    # Handle --company all by running all scrapers sequentially
    if company == "all":
        console.print(f"\n[bold cyan]Running all scrapers (JSON mode): {', '.join(SCRAPER_CLASSES.keys())}[/bold cyan]\n")
        for comp in SCRAPER_CLASSES:
            args.company = comp
            await run_json_mode(args)
        args.company = "all"
        return

    # Get output file path
    output_dir = Path(DEFAULT_OUTPUT_DIR)
    output_file = args.output or str(output_dir / f"{company}_jobs.json")
    ensure_output_directory(output_file)

    scraper_class = SCRAPER_CLASSES.get(company)
    if not scraper_class:
        console.print(f"[bold red]Unsupported company: {company}[/bold red]")
        sys.exit(1)

    console.print(f"\n[bold cyan]{company.title()} Jobs Scraper (JSON mode)[/bold cyan]")
    console.print(f"Detail scrape: {'Yes' if args.detail_scrape else 'No'}")
    console.print(f"Output file: {output_file}")
    if args.max_jobs:
        console.print(f"Max jobs: {args.max_jobs}")
    console.print()

    scraper = scraper_class(headless=args.headless, detail_scrape=args.detail_scrape)

    try:
        async with scraper:
            # Scrape all queries
            job_cards = await scraper.scrape_all_queries(args.max_jobs)
            console.print(f"Found {len(job_cards)} jobs")

            # Optionally scrape details
            if args.detail_scrape:
                console.print("Fetching job details...")
                enriched_jobs = []
                async for job in scraper.scrape_job_details_streaming(job_cards):
                    enriched_jobs.append(job)
                job_cards = enriched_jobs

            # Deduplicate and transform
            unique_jobs = scraper.deduplicate_jobs(job_cards)

            # Build output - convert JobListing models to dicts for compatibility
            # ScraperOutput expects google_jobs_scraper.models.JobListing
            # but Microsoft uses shared.models.JobListing
            from scripts.google_jobs_scraper.models import JobListing as GoogleJobListing
            jobs_for_output = []
            for job in unique_jobs:
                job_dict = job.model_dump()
                jobs_for_output.append(GoogleJobListing(**job_dict))

            output = ScraperOutput(
                scraped_at=get_iso_timestamp(),
                total_jobs=len(job_cards),
                filtered_jobs=len(unique_jobs),
                metadata={"search_queries": scraper.get_search_queries()},
                jobs=jobs_for_output,
            )

            # Write to file
            with open(output_file, "w") as f:
                json.dump(output.model_dump(), f, indent=2)

            console.print(f"\n[bold green]✓ Scraping completed successfully![/bold green]")
            console.print(f"Total jobs: {len(unique_jobs)}")
            console.print(f"Output file: {output_file}")

    except Exception as e:
        console.print(f"[bold red]Error: {e}[/bold red]")
        logger.exception("Scraper failed")
        sys.exit(1)


async def run_database_mode(args):
    """Run scraper in database mode with incremental support"""
    company = args.company
    env = args.env
    db_url = args.db_url

    # Handle --company all by running all scrapers sequentially
    if company == "all":
        console.print(f"\n[bold cyan]Running all scrapers: {', '.join(SCRAPER_CLASSES.keys())}[/bold cyan]\n")
        for comp in SCRAPER_CLASSES:
            args.company = comp
            await run_database_mode(args)
        args.company = "all"
        return

    logger.info(f"Running scraper in database mode: company={company}, env={env}")

    # Connect to database
    try:
        conn = db.get_connection(db_url, env)
        db.init_schema(conn, env)
    except Exception as e:
        console.print(f"[bold red]Database connection failed: {e}[/bold red]")
        sys.exit(2)

    scraper_class = SCRAPER_CLASSES.get(company)
    if not scraper_class:
        console.print(f"[bold red]Unsupported company: {company}[/bold red]")
        sys.exit(1)

    scraper = scraper_class(headless=args.headless, detail_scrape=args.detail_scrape)

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

                # Scrape all queries (list pages only - fast)
                job_cards = await scraper.scrape_all_queries(args.max_jobs)
                console.print(f"Found {len(job_cards)} jobs")

                # Initialize batch writer for efficient database writes
                timestamp = get_iso_timestamp()
                writer = BatchWriter(
                    db_conn=conn,
                    env=env,
                    scraper=scraper,
                    batch_size=50,
                    detail_scrape=args.detail_scrape,
                    use_upsert=False  # Full scrape uses insert
                )

                # Track details count (used in scrape run record)
                details_count = 0

                if args.detail_scrape:
                    # Stream details and batch write to database
                    console.print("Fetching job details and saving in batches...")

                    async for enriched_job in scraper.scrape_job_details_streaming(job_cards):
                        writer.add_job(enriched_job, timestamp)
                        details_count += 1

                        # Progress update every batch
                        if details_count % 50 == 0:
                            console.print(
                                f"  Progress: {details_count}/{len(job_cards)} details fetched, "
                                f"{writer.stats.total_written} saved"
                            )
                else:
                    # No detail scrape - batch insert cards directly
                    for job_data in job_cards:
                        writer.add_job(job_data, timestamp)

                # Flush remaining jobs in buffer
                writer.flush()

                console.print(f"\n[bold green]✓ Full scrape completed![/bold green]")
                console.print(f"Jobs processed: {writer.stats.total_processed}")
                console.print(f"Jobs written: {writer.stats.total_written}")
                console.print(f"Batches: {writer.stats.batches_written}")
                if writer.stats.errors > 0:
                    console.print(f"[yellow]Errors: {writer.stats.errors}[/yellow]")

                # Record scrape run for full mode (audit trail)
                from scripts.shared.models import ScrapeRun
                import uuid
                run_record = ScrapeRun(
                    run_id=str(uuid.uuid4()),
                    company=company,
                    started_at=timestamp,
                    completed_at=get_iso_timestamp(),
                    mode="full",
                    jobs_seen=len(job_cards),
                    new_jobs=writer.stats.total_written,
                    closed_jobs=0,
                    details_fetched=details_count if args.detail_scrape else 0,
                    error_count=writer.stats.errors,
                )
                db.record_scrape_run(conn, run_record, env)
                console.print(f"Scrape run recorded: {run_record.run_id}")

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
        choices=["google", "apple", "microsoft", "all"],
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
    run_mode = run_database_mode if should_use_database_mode(args) else run_json_mode
    asyncio.run(run_mode(args))


if __name__ == "__main__":
    main()
