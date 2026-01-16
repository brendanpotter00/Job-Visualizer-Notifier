# CLAUDE.md

Multi-Company Job Scraper - A Python-based web scraping framework that extracts job listings from multiple company career sites. Currently supports **Google Careers** (Playwright browser automation) and **Apple Jobs** (hybrid HTML + API approach). Designed to feed structured job data into the Job Visualizer application with support for incremental scraping, database persistence, and comprehensive error handling.

## Commands

```bash
# Basic Usage (Google - JSON Mode)
python scripts/run_scraper.py                    # Quick scrape (list data only)
python scripts/run_scraper.py --detail-scrape    # Full scrape with job details (slower)
python scripts/run_scraper.py --resume           # Resume interrupted scrape from checkpoint

# Apple Scraper
python scripts/run_scraper.py --company apple                           # Apple scrape (list data only)
python scripts/run_scraper.py --company apple --detail-scrape           # Apple with job details
python scripts/run_scraper.py --company all                             # Run all scrapers

# Database Mode (PostgreSQL)
python scripts/run_scraper.py --company google --env local --db-url postgresql://user:pass@host/db
python scripts/run_scraper.py --company apple --env local --db-url postgresql://user:pass@host/db
python scripts/run_scraper.py --company google --env local --db-url postgresql://user:pass@host/db --incremental

# Testing & Development
python scripts/run_scraper.py --max-jobs 10 -v   # Test scrape with verbose logging
python scripts/run_scraper.py --no-headless      # Run with visible browser
python scripts/run_scraper.py -o custom.json     # Custom output location

# Running Tests
pytest                                           # Run all tests
pytest tests/unit                                # Unit tests only
pytest tests/integration                         # Integration tests only
pytest -v --tb=short                            # Verbose with short tracebacks

# Dependencies
pip install -r scripts/requirements.txt          # Install Python dependencies
pip install -r scripts/requirements-dev.txt      # Install dev dependencies (testing)
.venv/bin/playwright install chromium            # Install browser binaries
```

## CLI Options

```
--company {google,apple,all}  # Which scraper to run (default: google)
--env {local,qa,prod}         # Environment for table naming (default: local)
--db-url URL                  # PostgreSQL connection URL
--incremental                 # Run incremental mode (requires --db-url)
--detail-scrape               # Scrape individual job detail pages
--max-jobs N                  # Limit jobs scraped (useful for testing)
--resume                      # Resume from checkpoint (JSON mode only)
--no-headless                 # Show browser window (debugging)
-v, --verbose                 # Verbose logging output
-o, --output PATH             # Custom JSON output path
```

## Architecture Quick Reference

**Core Components:**
- `run_scraper.py` - Entry point with multi-company support (JSON/Database modes)

**Google-Specific:**
- `google_jobs_scraper/scraper.py` - Playwright browser automation (extends BaseScraper)
- `google_jobs_scraper/parser.py` - HTML parsing and data extraction functions
- `google_jobs_scraper/models.py` - Pydantic models (JobListing/GoogleJob, ScraperOutput, CheckpointData)
- `google_jobs_scraper/config.py` - Search queries, filters, rate limits, retry policies
- `google_jobs_scraper/utils.py` - Rate limiting, checkpoints, retry decorators, logging
- `google_jobs_scraper/main.py` - CLI orchestration with async execution (JSON mode)

**Apple-Specific:**
- `apple_jobs_scraper/scraper.py` - Hybrid HTML+API scraper (extends BaseScraper)
- `apple_jobs_scraper/parser.py` - HTML parsing for list/search result pages
- `apple_jobs_scraper/api_client.py` - JSON API client for job details
- `apple_jobs_scraper/config.py` - Apple-specific configuration (locations, keywords)

**Shared Modules:**
- `shared/base_scraper.py` - Abstract base class for all company scrapers (~267 lines)
- `shared/database.py` - PostgreSQL database layer with CRUD operations (~571 lines)
- `shared/incremental.py` - 5-phase incremental scraping algorithm (~275 lines)
- `shared/models.py` - Database-aligned Pydantic models (JobListing, ScrapeRun) (~62 lines)
- `shared/batch_writer.py` - Buffered batch writing utility (~157 lines)
- `shared/utils.py` - Shared utilities (timestamps) (~13 lines)

**Testing:**
- `tests/conftest.py` - Shared pytest fixtures
- `tests/unit/` - Unit tests (7 files)
- `tests/integration/` - Integration tests (4 files)
- `pytest.ini` - Test configuration

**Data Flow:**
User runs script → Parse CLI args → Select company scraper → Choose mode (JSON vs Database) → **JSON Mode:** Load checkpoint (if --resume) → For each search query: paginate through results → Extract job cards → Filter by keywords → Optional detail scraping → Save checkpoints → Deduplicate → Transform to Pydantic models → Write JSON → Delete checkpoint | **Database Mode:** Connect to DB → **Incremental:** 5-phase algorithm (quick scrape → compare with DB → fetch details for new jobs only → update existing → mark closed) | **Full:** Scrape all → Transform → Insert to DB

**Output Format:**
- **JSON Mode:** Scraped jobs written to `scripts/output/google_jobs.json` with metadata. Schema matches TypeScript `Job` interface from main app (id, source, company, title, location, createdAt, url + 15 extended fields). Compatible with Redux store ingestion.
- **Database Mode:** Jobs stored in `job_listings_{env}` table with incremental tracking fields (first_seen_at, last_seen_at, consecutive_misses, details_scraped). Scrape metadata in `scrape_runs_{env}` table.

**Key Design Patterns:**
- Async context manager for browser lifecycle
- Pydantic validation for type safety
- Checkpoint system saves progress every 100 jobs (JSON mode)
- Exponential backoff retry logic (4-60s delays)
- Anti-detection measures (real user agent, random delays 2-5s)
- Abstract factory pattern (BaseScraper) for multi-company support
- PostgreSQL database layer
- 5-phase incremental algorithm minimizes scraping time
- Batch writing for database performance

## Apple Scraper Details

The Apple scraper uses a **hybrid approach**:

1. **HTML Parsing for List Pages:** Navigates search results pages using Playwright, extracts job cards from HTML
2. **JSON API for Job Details:** Fetches structured job data from Apple's internal API endpoints

**Key Differences from Google Scraper:**
- **Location-based filtering:** Apple's site doesn't support keyword search - filters by location instead
- **Job ID format:** Includes location suffix for uniqueness (e.g., `200554363-united-states`)
- **Salary extraction:** Available from API response when provided by Apple
- **No checkpoints:** Designed for database mode (incremental scraping handles resume)

**Apple Configuration (`apple_jobs_scraper/config.py`):**
- `LOCATION_FILTER` - Target location (default: "United States")
- `INCLUDE_TITLE_KEYWORDS` / `EXCLUDE_TITLE_KEYWORDS` - Job title filters
- `MAX_PAGES` - Maximum pages to scrape
- Rate limits and timeouts

## Common Tasks

**Running Google Scraper (JSON Mode):**
```bash
python scripts/run_scraper.py --detail-scrape -o output/google_jobs.json
```

**Running Apple Scraper (Database Mode):**
```bash
python scripts/run_scraper.py --company apple --env local \
  --db-url "postgresql://postgres:postgres@localhost:5432/jobscraper"
```

**Running All Scrapers:**
```bash
python scripts/run_scraper.py --company all --env local \
  --db-url "postgresql://postgres:postgres@localhost:5432/jobscraper" --incremental
```

**Running Incremental Database Scrape (PostgreSQL):**
```bash
# First run: Full scrape to populate database
python scripts/run_scraper.py --company google --env local \
  --db-url "postgresql://user:pass@host/db" --detail-scrape

# Subsequent runs: Fast incremental updates (only new jobs)
python scripts/run_scraper.py --company google --env local \
  --db-url "postgresql://user:pass@host/db" --incremental
```

**Testing Changes:**
```bash
python scripts/run_scraper.py --max-jobs 5 --no-headless -v
python scripts/run_scraper.py --company apple --max-jobs 5 -v
```

**Running Tests:**
```bash
pytest                    # All tests
pytest tests/unit         # Unit tests only
pytest tests/integration  # Integration tests only
pytest -v                 # Verbose output
```

**Resuming Failed Scrape (JSON Mode):**
If scraping is interrupted, checkpoint is automatically saved. Resume with:
```bash
python scripts/run_scraper.py --resume
```

**Adding Search Queries (Google):**
Edit `google_jobs_scraper/config.py` and add to `SEARCH_QUERIES` list. Currently only "software engineer" is active. Available but commented out: software developer, frontend engineer, backend engineer, data scientist, etc.

**Modifying Filters:**
Edit company-specific `config.py`:
- `INCLUDE_TITLE_KEYWORDS` - Jobs must match at least one keyword
- `EXCLUDE_TITLE_KEYWORDS` - Jobs matching these are filtered out
- `LOCATION_FILTER` - Location filter (US-only for Google, configurable for Apple)

**Adding a New Company Scraper:**
1. Create new directory: `scripts/<company>_jobs_scraper/`
2. Implement scraper extending `BaseScraper` from `shared/base_scraper.py`
3. Create `parser.py`, `config.py`, and optionally `api_client.py`
4. Add company to `run_scraper.py` CLI choices and scraper factory
5. Add unit and integration tests

## Critical Gotchas

1. **Playwright Installation Required**: Must run `.venv/bin/playwright install chromium` after pip install - browser binaries are separate from Python package
2. **Detail Scraping is Slow**: `--detail-scrape` makes individual requests for each job - expect 15-30 min for 500 jobs vs 2-3 min without
3. **Checkpoints Auto-Delete on Success** (JSON mode): `.checkpoint.json` only persists if scrape is interrupted - deleted automatically on completion
4. **Location Filtering is Restrictive**: Currently hardcoded to US-only jobs for both scrapers
5. **Google DOM Changes Break Parsers**: Google scraper relies on specific CSS selectors - if Google redesigns careers site, update `google_jobs_scraper/parser.py` selectors
6. **Apple Uses Location-Based Filtering**: Apple doesn't support keyword search - it filters by location only, then applies title keyword filters client-side
7. **Rate Limiting is Conservative**: 2-5s delays prevent rate limiting but slow scraping - adjust `config.py` at your own risk
8. **Run from Project Root**: Always execute as `python scripts/run_scraper.py` not `cd scripts && python run_scraper.py` - path setup depends on project root
9. **Database Mode Requires --db-url**: Incremental mode requires database connection - use `--db-url postgresql://user:pass@host/db`
10. **Environment Flag Affects Tables**: `--env` flag determines table names (`job_listings_local`, `job_listings_prod`) - use consistent env for same database
11. **Incremental Mode Needs Initial Full Scrape**: First run should be without `--incremental` to populate database, subsequent runs use `--incremental`
12. **Apple Job IDs Include Location**: Apple job IDs have location suffix for uniqueness - this is intentional to distinguish same role in different locations

## Key Files

**Entry Points:**
- `scripts/run_scraper.py` - Multi-company CLI (JSON/Database modes)

**Google-Specific:**
- Main Logic: `scripts/google_jobs_scraper/scraper.py` (~350 lines, extends BaseScraper)
- HTML Parsing: `scripts/google_jobs_scraper/parser.py` (~400 lines)
- Data Models: `scripts/google_jobs_scraper/models.py`
- Configuration: `scripts/google_jobs_scraper/config.py`
- CLI Orchestration: `scripts/google_jobs_scraper/main.py` (JSON mode)
- Utilities: `scripts/google_jobs_scraper/utils.py`

**Apple-Specific:**
- Main Logic: `scripts/apple_jobs_scraper/scraper.py` (~372 lines, extends BaseScraper)
- HTML Parsing: `scripts/apple_jobs_scraper/parser.py` (~215 lines)
- API Client: `scripts/apple_jobs_scraper/api_client.py` (~201 lines)
- Configuration: `scripts/apple_jobs_scraper/config.py` (~77 lines)

**Shared Modules:**
- Abstract Base: `scripts/shared/base_scraper.py` (~267 lines)
- Database Layer: `scripts/shared/database.py` (~571 lines)
- Incremental Algorithm: `scripts/shared/incremental.py` (~275 lines)
- Data Models: `scripts/shared/models.py` (~62 lines)
- Batch Writer: `scripts/shared/batch_writer.py` (~157 lines)
- Utilities: `scripts/shared/utils.py` (~13 lines)

**Testing:**
- Test Config: `scripts/pytest.ini`
- Fixtures: `scripts/tests/conftest.py`
- Unit Tests (7 files):
  - `tests/unit/test_models.py`
  - `tests/unit/test_utils.py`
  - `tests/unit/test_parser_helpers.py`
  - `tests/unit/test_incremental_diff.py`
  - `tests/unit/test_batch_writer.py`
  - `tests/unit/test_apple_parser.py`
  - `tests/unit/test_apple_api_client.py`
- Integration Tests (4 files):
  - `tests/integration/test_database.py`
  - `tests/integration/test_incremental.py`
  - `tests/integration/test_apple_scraper.py`
  - `tests/integration/test_scraper_transform.py`

**Output:**
- JSON: `scripts/output/google_jobs.json`
- Checkpoint: `scripts/output/.checkpoint.json` (temporary, JSON mode)
- Database: PostgreSQL connection

## See Also

- **ARCHITECTURE.md** - Detailed architecture documentation with workflow diagrams
- **README.md** - User-facing documentation
- **Root CLAUDE.md** - Parent project documentation
- **TypeScript Job Model**: `src/frontend/src/types/index.ts` - Data model that scraper output aligns with
