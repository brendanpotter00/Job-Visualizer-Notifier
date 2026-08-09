# CLAUDE.md

Multi-Company Job Scraper - A Python-based web scraping framework that extracts job listings from multiple company career sites. Currently supports **Google Careers** (Playwright browser automation), **Apple Jobs** (hybrid HTML + API approach), **Microsoft Careers** (Eightfold ATS JSON APIs), **Amazon Jobs** (public JSON search endpoint, no detail fetch), and **TikTok Jobs** (public JSON search endpoint, POST, no detail fetch). Designed to feed structured job data into the Job Visualizer application with support for incremental scraping, database persistence, and comprehensive error handling.

## Commands

```bash
# Basic Usage (Google - JSON Mode)
python scripts/run_scraper.py                    # Quick scrape (list data only)
python scripts/run_scraper.py --detail-scrape    # Full scrape with job details (slower)
python scripts/run_scraper.py --resume           # Resume interrupted scrape from checkpoint

# Apple Scraper
python scripts/run_scraper.py --company apple                           # Apple scrape (list data only)
python scripts/run_scraper.py --company apple --detail-scrape           # Apple with job details

# Microsoft Scraper
python scripts/run_scraper.py --company microsoft                       # Microsoft scrape (list data only)
python scripts/run_scraper.py --company microsoft --detail-scrape       # Microsoft with job details

# Amazon Scraper
python scripts/run_scraper.py --company amazon                          # Amazon scrape
python scripts/run_scraper.py --company amazon --max-jobs 10 -v         # Quick smoke test

# TikTok Scraper
python scripts/run_scraper.py --company tiktok                          # TikTok scrape
python scripts/run_scraper.py --company tiktok --max-jobs 10 -v         # Quick smoke test

python scripts/run_scraper.py --company all                             # Run all scrapers

# Database Mode (PostgreSQL)
python scripts/run_scraper.py --company google --db-url postgresql://user:pass@host/db
python scripts/run_scraper.py --company apple --db-url postgresql://user:pass@host/db
python scripts/run_scraper.py --company google --db-url postgresql://user:pass@host/db --incremental

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
--company {google,apple,microsoft,amazon,tiktok,all}  # Which scraper to run (default: google)
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
- `shared/base_scraper.py` - Abstract base class for all company scrapers
- `shared/database.py` - PostgreSQL database layer with CRUD operations
- `shared/incremental.py` - 5-phase incremental scraping algorithm
- `shared/models.py` - Database-aligned Pydantic models (JobListing, ScrapeRun)
- `shared/batch_writer.py` - Buffered batch writing utility
- `shared/utils.py` - Shared utilities (timestamps)
- `shared/constants.py` - Shared constants (table names, etc.)
- Schema is managed by Alembic in `src/backend/alembic/` (see `src/backend/CLAUDE.md` § Schema migrations).

**Testing:**
- `tests/conftest.py` - Shared pytest fixtures
- `tests/unit/` - Unit tests (16 files)
- `tests/integration/` - Integration tests (11 files)
- `pytest.ini` - Test configuration

**Data Flow:**
User runs script → Parse CLI args → Select company scraper → Choose mode (JSON vs Database) → **JSON Mode:** Load checkpoint (if --resume) → For each search query: paginate through results → Extract job cards → Filter by keywords → Optional detail scraping → Save checkpoints → Deduplicate → Transform to Pydantic models → Write JSON → Delete checkpoint | **Database Mode:** Connect to DB → **Incremental:** 5-phase algorithm (quick scrape → compare with DB → fetch details for new jobs only → update existing → mark closed) | **Full:** Scrape all → Transform → Insert to DB

**Output Format:**
- **JSON Mode:** Scraped jobs written to `scripts/output/google_jobs.json` with metadata. Schema matches TypeScript `Job` interface from main app (id, source, company, title, location, createdAt, url + 15 extended fields). Compatible with Redux store ingestion.
- **Database Mode:** Jobs stored in the `job_listings` table (first_seen_at, details_scraped); per-job freshness tracking (last_seen_at, consecutive_misses) lives in the `job_freshness` sidecar table since `18fe9c20a8fd`. Scrape metadata in the `scrape_runs` table. Table names are the same across every environment; test isolation is handled via per-worker Postgres schemas (see `src/backend/CLAUDE.md` § Schema migrations).

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

## Microsoft Scraper Details

The Microsoft scraper uses **Eightfold ATS JSON APIs**:

1. **API-First Approach:** Uses `/api/pcsx/search` for job listings and `/api/pcsx/position_details` for job details
2. **HTML Fallback:** Falls back to HTML parsing if API is unavailable
3. **Keyword Search:** Microsoft's site supports keyword search (e.g., "software engineer")

**Key Differences from Other Scrapers:**
- **Eightfold Platform:** Microsoft uses Eightfold ATS (like many enterprise companies)
- **Position IDs:** Large numeric IDs (e.g., `1970393556642428`)
- **Job Numbers:** Internal reference numbers (e.g., `200016306`)
- **Pagination:** Uses `start` parameter (0, 10, 20...) with 10 jobs per page

**Microsoft Configuration (`microsoft_jobs_scraper/config.py`):**
- `DOMAIN` - Microsoft domain for API calls (`microsoft.com`)
- `LOCATION_FILTER` - Target location (default: "United States")
- `SEARCH_QUERIES` - Search keywords (default: `["software engineer"]`)
- `INCLUDE_TITLE_KEYWORDS` / `EXCLUDE_TITLE_KEYWORDS` - Job title filters
- `JOBS_PER_PAGE` - 10 (Microsoft's pagination size)
- `MAX_PAGES` - Maximum pages to scrape (500)
- Rate limits and timeouts

## Amazon Scraper Details

The Amazon scraper is **API-only** — no HTML parsing and no detail-fetch phase:

1. **Single JSON endpoint:** `GET https://www.amazon.jobs/en/search.json` with
   `offset` / `result_limit` / `sort=recent` / `country=USA` / `base_query`
2. **Descriptions arrive inline:** the list row carries `description`,
   `basic_qualifications`, and `preferred_qualifications`, so
   `scrape_job_details_streaming` is a deliberate **pass-through**

**Key Differences from Other Scrapers:**
- **No detail fetch.** Overriding the streaming method is mandatory, not an
  optimization — the BaseScraper default would open a page and sleep 2-5s per
  job (45-110 min for a ~1,300 job board, past `SCRAPER_TIMEOUT_MINUTES`).
- **Requisition id, not the GUID.** Key on `id_icims`; the `id` field is a GUID
  that never appears in the canonical URL.
- **`result_limit` is hard-capped at 100.** Asking for 200 returns
  `{"error": "...", "jobs": null}` — note `jobs` is `null`, not `[]`.
- **`posted_date` is date-only English** ("August  8, 2026", with a double
  space), normalised to a 10-char `YYYY-MM-DD`. Note that `posted_on` is a
  `timestamptz`, so Postgres casts that to UTC midnight on write — the bare
  date is the honest encoding of a date-only source, not a way to avoid the
  timezone skew. Recency UI reads `firstSeenAt`, so impact is minimal.
- **Same-origin navigation is required.** search.json sends no
  `Access-Control-Allow-Origin`, so the in-page `fetch()` is blocked unless the
  page is already on an amazon.jobs origin (`_establish_session`).
- **Control bytes.** Amazon intermittently embeds raw `\x01` in description
  HTML, which V8's `JSON.parse` rejects. `_FETCH_JS` parses `r.text()` and only
  sanitises on failure, so healthy payloads are never mutated.

**Amazon Configuration (`amazon_jobs_scraper/config.py`):**
- `SEARCH_QUERIES` - `["software engineer"]` (server-side `base_query`)
- `COUNTRY` - `USA`
- `INCLUDE_TITLE_KEYWORDS` / `EXCLUDE_TITLE_KEYWORDS` - title filters. EXCLUDE is
  matched on **word boundaries** and only against the **role segment** (text
  before the first comma). As a bare substring "HR" matches "T-h-r-eat"; matched
  against the whole title, "recruiting" in a *team* name killed a real
  "Principal Engineer, … Global Specialty Recruiting Team" req. An empty
  EXCLUDE list means "exclude nothing" (an unguarded empty alternation would
  reject the whole board).
- `JOBS_PER_PAGE` - 100 (API hard cap)
- `MAX_PAGES` - 50 safety bound (live `hits` was 1303)

## TikTok Scraper Details

The TikTok scraper is **API-only** — no HTML parsing and no detail-fetch phase:

1. **Single JSON endpoint:** `POST https://api.lifeattiktok.com/api/v1/public/supplier/search/job/posts`
2. **Descriptions arrive inline:** the row carries plain-text `description` and
   `requirement`, so `scrape_job_details_streaming` is a **pass-through**

**Key Differences from Other Scrapers:**
- **POST, not GET.** Pagination and keyword live in a JSON body, not the query string.
- **`website-path: tiktok` header is REQUIRED** — without it the edge returns HTTP 400.
- **HTTP 200 can still be an error.** The envelope carries `code`; a non-zero
  value raises rather than returning partial results, because swallowing it
  would let the incremental lifecycle close the whole company during an outage.
- **No posted date exists.** Nothing in the payload carries one, so `posted_on`
  is always `None` and `first_seen_at` is the only honest signal.
- **Location is filtered client-side.** `location_code_list` takes *city* codes
  (`CT_163`); passing a country code (`CN_6` = USA) silently returns zero
  results, so the US filter matches on the flattened `city_info` string instead.
- **Same-origin navigation is required.** The API sends no
  `Access-Control-Allow-Origin`, so the in-page `fetch()` only works once the
  page is on lifeattiktok.com (`_establish_session`).
- **Descriptions are plain text** — no HTML stripping, unlike Amazon.

**TikTok Configuration (`tiktok_jobs_scraper/config.py`):**
- `SEARCH_QUERIES` - `["software engineer"]` (~716 of a ~3,900 global catalogue)
- `LOCATION_FILTER` - `"United States"`, applied client-side
- `INCLUDE_TITLE_KEYWORDS` / `EXCLUDE_TITLE_KEYWORDS` - title filters; EXCLUDE is
  matched on **word boundaries** ("HR" as a substring matches "T-h-r-eat")
- `JOBS_PER_PAGE` - 100
- `MAX_PAGES` - 50 safety bound

## Common Tasks

**Running Google Scraper (JSON Mode):**
```bash
python scripts/run_scraper.py --detail-scrape -o output/google_jobs.json
```

**Running Apple Scraper (Database Mode):**
```bash
python scripts/run_scraper.py --company apple \
  --db-url "postgresql://postgres:postgres@localhost:5432/jobscraper"
```

**Running All Scrapers:**
```bash
python scripts/run_scraper.py --company all \
  --db-url "postgresql://postgres:postgres@localhost:5432/jobscraper" --incremental
```

**Running Incremental Database Scrape (PostgreSQL):**
```bash
# First run: Full scrape to populate database
python scripts/run_scraper.py --company google \
  --db-url "postgresql://user:pass@host/db" --detail-scrape

# Subsequent runs: Fast incremental updates (only new jobs)
python scripts/run_scraper.py --company google \
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
10. **Tables are env-agnostic**: All environments (local, prod, per-worker test schemas) share bare names — `job_listings`, `scrape_runs`, `users`, `user_enabled_companies`. There is no `--env` flag and no `SCRAPER_ENVIRONMENT`. Test isolation uses per-worker Postgres schemas via `PYTEST_SCHEMA` + `search_path`; see `src/backend/CLAUDE.md` § Schema migrations.
11. **Incremental Mode Needs Initial Full Scrape**: First run should be without `--incremental` to populate database, subsequent runs use `--incremental`
12. **Apple Job IDs Include Location**: Apple job IDs have location suffix for uniqueness - this is intentional to distinguish same role in different locations
13. **Microsoft Uses Eightfold APIs**: Microsoft scraper primarily uses JSON APIs (`/api/pcsx/*`) with HTML fallback - if APIs change, check Eightfold documentation
14. **Microsoft Position IDs are Large Numbers**: Microsoft uses 16-digit numeric position IDs - ensure database columns can handle large integers or store as strings

## Key Files

**Entry Points:**
- `scripts/run_scraper.py` - Multi-company CLI (JSON/Database modes)

**Google-Specific:**
- Main Logic: `scripts/google_jobs_scraper/scraper.py` - Playwright browser automation (extends BaseScraper)
- HTML Parsing: `scripts/google_jobs_scraper/parser.py` - HTML parsing and data extraction
- Data Models: `scripts/google_jobs_scraper/models.py`
- Configuration: `scripts/google_jobs_scraper/config.py`
- CLI Orchestration: `scripts/google_jobs_scraper/main.py` (JSON mode)
- Utilities: `scripts/google_jobs_scraper/utils.py`

**Apple-Specific:**
- Main Logic: `scripts/apple_jobs_scraper/scraper.py` - Hybrid HTML+API scraper (extends BaseScraper)
- HTML Parsing: `scripts/apple_jobs_scraper/parser.py` - HTML parsing for list/search result pages
- API Client: `scripts/apple_jobs_scraper/api_client.py` - JSON API client for job details
- Configuration: `scripts/apple_jobs_scraper/config.py`

**Microsoft-Specific:**
- Main Logic: `scripts/microsoft_jobs_scraper/scraper.py` - Eightfold API + HTML fallback scraper (extends BaseScraper)
- HTML Parsing: `scripts/microsoft_jobs_scraper/parser.py`
- API Client: `scripts/microsoft_jobs_scraper/api_client.py` - `/api/pcsx/search` and position_details client
- Configuration: `scripts/microsoft_jobs_scraper/config.py`

**Amazon-Specific:**
- Main Logic: `scripts/amazon_jobs_scraper/scraper.py` - API-only scraper, pass-through details (extends BaseScraper)
- API Client: `scripts/amazon_jobs_scraper/api_client.py` - search.json client, HTML stripper, date normaliser
- URL Helpers: `scripts/amazon_jobs_scraper/parser.py`
- Configuration: `scripts/amazon_jobs_scraper/config.py`

**TikTok-Specific:**
- Main Logic: `scripts/tiktok_jobs_scraper/scraper.py` - API-only scraper, pass-through details (extends BaseScraper)
- API Client: `scripts/tiktok_jobs_scraper/api_client.py` - POST search client, location/department flatteners
- URL Helpers: `scripts/tiktok_jobs_scraper/parser.py`
- Configuration: `scripts/tiktok_jobs_scraper/config.py`

**Shared Modules:**
- `scripts/shared/base_scraper.py` - Abstract base class for all company scrapers
- `scripts/shared/database.py` - PostgreSQL database layer with CRUD operations
- `scripts/shared/incremental.py` - 5-phase incremental scraping algorithm
- `scripts/shared/models.py` - Database-aligned Pydantic models (JobListing, ScrapeRun)
- `scripts/shared/batch_writer.py` - Buffered batch writing utility
- `scripts/shared/utils.py` - Shared utilities (timestamps)

**Testing:**
- Test Config: `scripts/pytest.ini`
- Fixtures: `scripts/tests/conftest.py`
- Unit tests: `scripts/tests/unit/`
- Integration tests: `scripts/tests/integration/`

**Output:**
- JSON: `scripts/output/google_jobs.json` (`scripts/output/` is created at runtime by `ensure_output_directory()` — not committed to the repo)
- Checkpoint: `scripts/output/.checkpoint.json` (temporary, JSON mode; auto-deleted on success)
- Database: PostgreSQL connection

## See Also

- **ARCHITECTURE.md** - Detailed architecture documentation with workflow diagrams
- **README.md** - User-facing documentation
- **Root CLAUDE.md** - Parent project documentation
- **TypeScript Job Model**: `src/frontend/src/types/index.ts` - Data model that scraper output aligns with
