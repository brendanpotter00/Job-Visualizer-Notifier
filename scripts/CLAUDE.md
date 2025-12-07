# CLAUDE.md

Google Jobs Scraper - A Python-based web scraping tool that extracts job listings from Google Careers using Playwright. Designed to feed structured job data into the Job Visualizer application with support for resumable scraping, rate limiting, and comprehensive error handling.

## Commands

```bash
# Basic Usage (JSON Mode)
python scripts/run_scraper.py                    # Quick scrape (list data only)
.venv/bin/python scripts/run_scraper.py          # Using venv directly

# Production Scraping
python scripts/run_scraper.py --detail-scrape    # Full scrape with job details (slower)
python scripts/run_scraper.py --resume           # Resume interrupted scrape from checkpoint

# Database Mode (NEW)
python scripts/run_scraper.py --db-url sqlite:///jobs.db                    # SQLite database
python scripts/run_scraper.py --db-url sqlite:///jobs.db --incremental      # Smart incremental scrape
python scripts/run_scraper.py --db-url postgresql://user:pass@host/db       # PostgreSQL

# Testing & Development
python scripts/run_scraper.py --max-jobs 10 -v   # Test scrape with verbose logging
python scripts/run_scraper.py --no-headless      # Run with visible browser
python scripts/run_scraper.py -o custom.json     # Custom output location

# Running Tests (NEW)
pytest                                           # Run all tests
pytest tests/unit                                # Unit tests only
pytest tests/integration                         # Integration tests only
pytest -v --tb=short                            # Verbose with short tracebacks

# Dependencies
pip install -r scripts/requirements.txt          # Install Python dependencies
pip install -r scripts/requirements-dev.txt      # Install dev dependencies (testing)
.venv/bin/playwright install chromium            # Install browser binaries
```

## Architecture Quick Reference

**Core Components:**
- `run_scraper.py` - Entry point with dual-mode support (JSON/Database)
- `google_jobs_scraper/main.py` - CLI orchestration with async execution (JSON mode)
- `google_jobs_scraper/scraper.py` - Playwright browser automation (extends BaseScraper)
- `google_jobs_scraper/parser.py` - HTML parsing and data extraction functions
- `google_jobs_scraper/models.py` - Pydantic models (JobListing/GoogleJob, ScraperOutput, CheckpointData)
- `google_jobs_scraper/config.py` - Search queries, filters, rate limits, retry policies
- `google_jobs_scraper/utils.py` - Rate limiting, checkpoints, retry decorators, logging

**Shared Modules (NEW - Multi-Scraper Foundation):**
- `shared/base_scraper.py` - Abstract base class for all company scrapers
- `shared/database.py` - SQLite/PostgreSQL abstraction layer with CRUD operations
- `shared/incremental.py` - 5-phase incremental scraping algorithm
- `shared/models.py` - Database-aligned Pydantic models (JobListing, ScrapeRun)

**Testing (NEW):**
- `tests/conftest.py` - Shared pytest fixtures
- `tests/unit/` - Unit tests (models, utils, parser helpers, incremental diff)
- `tests/integration/` - Integration tests (database, incremental, scraper transform)
- `pytest.ini` - Test configuration

**Data Flow:**
User runs script → Parse CLI args → Choose mode (JSON vs Database) → **JSON Mode:** Load checkpoint (if --resume) → For each search query: paginate through results → Extract job cards → Filter by keywords → Optional detail scraping → Save checkpoints → Deduplicate → Transform to Pydantic models → Write JSON → Delete checkpoint | **Database Mode:** Connect to DB → **Incremental:** 5-phase algorithm (quick scrape → compare with DB → fetch details for new jobs only → update existing → mark closed) | **Full:** Scrape all → Transform → Insert to DB

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
- Database abstraction layer (SQLite/PostgreSQL)
- 5-phase incremental algorithm minimizes scraping time

## Common Tasks

**Running a Full Production Scrape (JSON Mode):**
```bash
python scripts/run_scraper.py --detail-scrape -o output/google_jobs.json
```
Takes ~15-30 minutes depending on number of results. Scrapes both list and detail pages.

**Running Incremental Database Scrape (NEW):**
```bash
# First run: Full scrape to populate database
python scripts/run_scraper.py --db-url sqlite:///jobs.db --detail-scrape

# Subsequent runs: Fast incremental updates (only new jobs)
python scripts/run_scraper.py --db-url sqlite:///jobs.db --incremental
```
Incremental mode: ~2-3 min for list scrape, only fetches details for NEW jobs.

**Testing Changes:**
```bash
python scripts/run_scraper.py --max-jobs 5 --no-headless -v
```
Quick validation with visible browser and verbose logs.

**Running Tests (NEW):**
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

**Adding Search Queries:**
Edit `google_jobs_scraper/config.py` and add to `SEARCH_QUERIES` list. Currently only "software engineer" is active. Available but commented out: software developer, frontend engineer, backend engineer, data scientist, etc.

**Modifying Filters:**
Edit `google_jobs_scraper/config.py`:
- `INCLUDE_TITLE_KEYWORDS` - Jobs must match at least one keyword
- `EXCLUDE_TITLE_KEYWORDS` - Jobs matching these are filtered out
- `LOCATION_FILTER` - Currently "United States" only

**Adjusting Rate Limits:**
Edit `google_jobs_scraper/config.py`:
- `REQUEST_DELAY_MIN/MAX` - Random delay range (default 2-5s)
- `MAX_PAGES` - Max pages per query (default 50 = 1000 jobs)
- `CHECKPOINT_INTERVAL` - Save frequency (default every 100 jobs)

## Critical Gotchas

1. **Playwright Installation Required**: Must run `.venv/bin/playwright install chromium` after pip install - browser binaries are separate from Python package
2. **Detail Scraping is Slow**: `--detail-scrape` makes individual requests for each job - expect 15-30 min for 500 jobs vs 2-3 min without
3. **Checkpoints Auto-Delete on Success** (JSON mode): `.checkpoint.json` only persists if scrape is interrupted - deleted automatically on completion
4. **Location Filtering is Restrictive**: Currently hardcoded to US-only jobs - jobs without clear US location are filtered out (see `parser.py:is_us_location()`)
5. **Google DOM Changes Break Parsers**: Scraper relies on specific CSS selectors - if Google redesigns careers site, update `parser.py` selectors
6. **Rate Limiting is Conservative**: 2-5s delays prevent rate limiting but slow scraping - adjust `config.py` at your own risk
7. **Run from Project Root**: Always execute as `python scripts/run_scraper.py` not `cd scripts && python run_scraper.py` - path setup depends on project root
8. **Database Mode Requires --db-url** (NEW): Incremental mode requires database connection - use `--db-url sqlite:///path.db` or `postgresql://...`
9. **Environment Flag Affects Tables** (NEW): `--env` flag determines table names (`job_listings_local`, `job_listings_prod`) - use consistent env for same database
10. **Incremental Mode Needs Initial Full Scrape** (NEW): First run should be without `--incremental` to populate database, subsequent runs use `--incremental`

## Key Files

**Entry Points:**
- `scripts/run_scraper.py` - Dual-mode CLI (JSON/Database)

**Google-Specific:**
- Main Logic: `scripts/google_jobs_scraper/scraper.py` (~350 lines, extends BaseScraper)
- HTML Parsing: `scripts/google_jobs_scraper/parser.py` (~400 lines)
- Data Models: `scripts/google_jobs_scraper/models.py`
- Configuration: `scripts/google_jobs_scraper/config.py`
- CLI Orchestration: `scripts/google_jobs_scraper/main.py` (JSON mode)

**Shared Modules (NEW):**
- Abstract Base: `scripts/shared/base_scraper.py` (~200 lines)
- Database Layer: `scripts/shared/database.py` (~350 lines)
- Incremental Algorithm: `scripts/shared/incremental.py` (~270 lines)
- Data Models: `scripts/shared/models.py` (~70 lines)

**Testing (NEW):**
- Test Config: `scripts/pytest.ini`
- Fixtures: `scripts/tests/conftest.py`
- Unit Tests: `scripts/tests/unit/` (4 files)
- Integration Tests: `scripts/tests/integration/` (3 files)

**Output:**
- JSON: `scripts/output/google_jobs.json`
- Checkpoint: `scripts/output/.checkpoint.json` (temporary, JSON mode)
- Database: SQLite file or PostgreSQL connection

## See Also

- **scripts/ARCHITECTURE.md** - Detailed architecture documentation with workflow diagrams
- **scripts/README.md** - User-facing documentation
- **Main App CLAUDE.md** - Parent project documentation at `/Users/brendanpotter/Documents/develop/Job-Visualizer-Notifier/CLAUDE.md`
- **TypeScript Job Model**: `src/types/index.ts` - Data model that scraper output aligns with
