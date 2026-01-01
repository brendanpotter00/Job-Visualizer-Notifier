"""
Google Jobs Scraper - Main entry point
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeRemainingColumn

from .config import (
    SEARCH_QUERIES,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_OUTPUT_FILE,
    CHECKPOINT_INTERVAL,
)
from .models import ScraperOutput, CheckpointData
from .scraper import GoogleJobsScraper
from .utils import (
    setup_logging,
    save_checkpoint,
    load_checkpoint,
    delete_checkpoint,
    get_iso_timestamp,
    ensure_output_directory,
)

console = Console()


async def run_scraper(args):
    """Main scraper execution function"""
    # Set up logging
    setup_logging(verbose=args.verbose)

    # Determine output path
    output_path = args.output or str(
        Path(DEFAULT_OUTPUT_DIR) / DEFAULT_OUTPUT_FILE
    )
    ensure_output_directory(output_path)

    # Determine search queries
    search_queries = args.queries if args.queries else SEARCH_QUERIES

    console.print(f"\n[bold cyan]Google Jobs Scraper[/bold cyan]")
    console.print(f"Search queries: {', '.join(search_queries)}")
    console.print(f"Location filter: United States")
    console.print(f"Detail scrape: {'Yes' if args.detail_scrape else 'No'}")
    console.print(f"Output file: {output_path}")
    if args.max_jobs:
        console.print(f"Max jobs: {args.max_jobs}")
    console.print()

    # Load checkpoint if resuming
    checkpoint = None
    if args.resume:
        checkpoint = load_checkpoint()
        if checkpoint:
            console.print(
                f"[yellow]Resuming from checkpoint: "
                f"{len(checkpoint.jobs)} jobs already scraped[/yellow]\n"
            )

    # Initialize checkpoint if not resuming
    if not checkpoint:
        checkpoint = CheckpointData(
            completed_queries=[],
            jobs=[],
            total_jobs_seen=0,
            last_updated=get_iso_timestamp(),
        )

    start_time = datetime.now()
    all_jobs_data = []
    total_jobs_seen = checkpoint.total_jobs_seen

    try:
        async with GoogleJobsScraper(
            headless=args.headless, detail_scrape=args.detail_scrape
        ) as scraper:

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeRemainingColumn(),
                console=console,
            ) as progress:

                # Create main progress task
                query_task = progress.add_task(
                    "[cyan]Scraping queries...",
                    total=len(search_queries),
                )

                for query in search_queries:
                    # Skip completed queries if resuming
                    if query in checkpoint.completed_queries:
                        console.print(
                            f"[dim]Skipping completed query: {query}[/dim]"
                        )
                        progress.advance(query_task)
                        continue

                    progress.update(
                        query_task, description=f"[cyan]Scraping: {query}"
                    )

                    # Scrape job list for this query
                    job_cards = await scraper.scrape_query(
                        query, max_jobs=args.max_jobs
                    )
                    total_jobs_seen += len(job_cards)

                    # Optionally scrape job details
                    if args.detail_scrape and job_cards:
                        console.print(
                            f"[yellow]Scraping details for {len(job_cards)} jobs...[/yellow]"
                        )
                        enriched_jobs = await scraper.scrape_job_details_batch(
                            job_cards
                        )
                        all_jobs_data.extend(enriched_jobs)
                    else:
                        all_jobs_data.extend(job_cards)

                    # Update checkpoint
                    checkpoint.completed_queries.append(query)
                    checkpoint.total_jobs_seen = total_jobs_seen
                    checkpoint.last_updated = get_iso_timestamp()

                    # Save checkpoint periodically
                    if len(all_jobs_data) % CHECKPOINT_INTERVAL == 0:
                        save_checkpoint(checkpoint)

                    progress.advance(query_task)

                    # Check if we've hit max jobs
                    if args.max_jobs and total_jobs_seen >= args.max_jobs:
                        console.print(
                            f"[yellow]Reached max jobs limit ({args.max_jobs})[/yellow]"
                        )
                        break

            # Deduplicate and transform to models
            console.print(
                f"\n[cyan]Processing {len(all_jobs_data)} jobs...[/cyan]"
            )
            unique_jobs = scraper.deduplicate_jobs(all_jobs_data)

            # Create output
            output = ScraperOutput(
                scraped_at=get_iso_timestamp(),
                total_jobs=total_jobs_seen,
                filtered_jobs=len(unique_jobs),
                metadata={
                    "search_queries": search_queries,
                    "completed_queries": checkpoint.completed_queries,
                    "location_filter": "United States",
                    "scrape_duration_seconds": (
                        datetime.now() - start_time
                    ).total_seconds(),
                    "detail_scrape": args.detail_scrape,
                },
                jobs=unique_jobs,
            )

            # Write output to JSON
            with open(output_path, "w") as f:
                json.dump(output.model_dump(), f, indent=2)

            console.print(
                f"\n[bold green]✓ Scraping completed successfully![/bold green]"
            )
            console.print(f"Total jobs seen: {total_jobs_seen}")
            console.print(f"Unique jobs saved: {len(unique_jobs)}")
            console.print(f"Output file: {output_path}")
            console.print(
                f"Duration: {(datetime.now() - start_time).total_seconds():.1f}s"
            )

            # Delete checkpoint on success
            delete_checkpoint()

    except KeyboardInterrupt:
        console.print("\n[yellow]Scraping interrupted by user[/yellow]")

        # Save checkpoint with current progress
        checkpoint.jobs = scraper.deduplicate_jobs(all_jobs_data)
        checkpoint.total_jobs_seen = total_jobs_seen
        checkpoint.last_updated = get_iso_timestamp()
        save_checkpoint(checkpoint)

        console.print(
            f"[green]Progress saved to checkpoint. "
            f"Run with --resume to continue.[/green]"
        )
        sys.exit(1)

    except Exception as e:
        console.print(f"\n[bold red]Error: {e}[/bold red]")

        # Save checkpoint on error
        checkpoint.jobs = scraper.deduplicate_jobs(all_jobs_data)
        checkpoint.total_jobs_seen = total_jobs_seen
        checkpoint.last_updated = get_iso_timestamp()
        save_checkpoint(checkpoint)

        console.print(
            f"[yellow]Progress saved to checkpoint. "
            f"Run with --resume to continue.[/yellow]"
        )
        raise


def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Scrape Google Careers for software/developer/data science jobs in the US",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic scrape (software jobs in US)
  python -m scripts.google_jobs_scraper.main

  # Custom output location
  python -m scripts.google_jobs_scraper.main -o data/google_jobs.json

  # Include job details (slower, more data)
  python -m scripts.google_jobs_scraper.main --detail-scrape

  # Limit to 100 jobs for testing
  python -m scripts.google_jobs_scraper.main --max-jobs 100

  # Resume interrupted scrape
  python -m scripts.google_jobs_scraper.main --resume
        """,
    )

    parser.add_argument(
        "--output",
        "-o",
        help=f"Output JSON file path (default: {DEFAULT_OUTPUT_DIR}/{DEFAULT_OUTPUT_FILE})",
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
        help="Resume from checkpoint file if available",
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

    args = parser.parse_args()

    # Run async scraper
    asyncio.run(run_scraper(args))


if __name__ == "__main__":
    main()
