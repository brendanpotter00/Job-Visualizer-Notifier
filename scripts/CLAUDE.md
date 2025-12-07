# CLAUDE.md

Google Jobs Scraper - A Python-based web scraping tool that extracts job listings from Google Careers using Playwright. Designed to feed structured job data into the Job Visualizer application with support for resumable scraping, rate limiting, and comprehensive error handling.

## Commands

```bash
# Basic Usage
python scripts/run_scraper.py                    # Quick scrape (list data only)
.venv/bin/python scripts/run_scraper.py          # Using venv directly

# Production Scraping
python scripts/run_scraper.py --detail-scrape    # Full scrape with job details (slower)
python scripts/run_scraper.py --resume           # Resume interrupted scrape from checkpoint

# Testing & Development
python scripts/run_scraper.py --max-jobs 10 -v   # Test scrape with verbose logging
python scripts/run_scraper.py --no-headless      # Run with visible browser
python scripts/run_scraper.py -o custom.json     # Custom output location

# Dependencies
pip install -r scripts/requirements.txt          # Install Python dependencies
.venv/bin/playwright install chromium            # Install browser binaries
```

## Architecture Quick Reference

**Core Components:**
- `run_scraper.py` - Entry point that sets up Python path
- `google_jobs_scraper/main.py` - CLI orchestration with async execution
- `google_jobs_scraper/scraper.py` - Playwright browser automation (GoogleJobsScraper class)
- `google_jobs_scraper/parser.py` - HTML parsing and data extraction functions
- `google_jobs_scraper/models.py` - Pydantic models (GoogleJob, ScraperOutput, CheckpointData)
- `google_jobs_scraper/config.py` - Search queries, filters, rate limits, retry policies
- `google_jobs_scraper/utils.py` - Rate limiting, checkpoints, retry decorators, logging

**Data Flow:**
User runs script → Parse CLI args → Load checkpoint (if --resume) → For each search query: paginate through results → Extract job cards → Filter by keywords → Optional detail scraping → Save checkpoints → Deduplicate → Transform to Pydantic models → Write JSON → Delete checkpoint

**Output Format:**
Scraped jobs are written to `scripts/output/google_jobs.json` with metadata. Schema matches TypeScript `Job` interface from main app (id, source, company, title, location, createdAt, url + 15 extended fields). Compatible with Redux store ingestion.

**Key Design Patterns:**
- Async context manager for browser lifecycle
- Pydantic validation for type safety
- Checkpoint system saves progress every 100 jobs
- Exponential backoff retry logic (4-60s delays)
- Anti-detection measures (real user agent, random delays 2-5s)

## Common Tasks

**Running a Full Production Scrape:**
```bash
python scripts/run_scraper.py --detail-scrape -o output/google_jobs.json
```
Takes ~15-30 minutes depending on number of results. Scrapes both list and detail pages.

**Testing Changes:**
```bash
python scripts/run_scraper.py --max-jobs 5 --no-headless -v
```
Quick validation with visible browser and verbose logs.

**Resuming Failed Scrape:**
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
3. **Checkpoints Auto-Delete on Success**: `.checkpoint.json` only persists if scrape is interrupted - deleted automatically on completion
4. **Location Filtering is Restrictive**: Currently hardcoded to US-only jobs - jobs without clear US location are filtered out (see `parser.py:is_us_location()`)
5. **Google DOM Changes Break Parsers**: Scraper relies on specific CSS selectors - if Google redesigns careers site, update `parser.py` selectors
6. **Rate Limiting is Conservative**: 2-5s delays prevent rate limiting but slow scraping - adjust `config.py` at your own risk
7. **Run from Project Root**: Always execute as `python scripts/run_scraper.py` not `cd scripts && python run_scraper.py` - path setup depends on project root

## Key Files

- Entry Point: `scripts/run_scraper.py`
- Main Logic: `scripts/google_jobs_scraper/scraper.py` (~350 lines)
- HTML Parsing: `scripts/google_jobs_scraper/parser.py` (~400 lines)
- Data Models: `scripts/google_jobs_scraper/models.py`
- Configuration: `scripts/google_jobs_scraper/config.py`
- Output: `scripts/output/google_jobs.json`
- Checkpoint: `scripts/output/.checkpoint.json` (temporary)

## See Also

- **scripts/ARCHITECTURE.md** - Detailed architecture documentation with workflow diagrams
- **scripts/README.md** - User-facing documentation
- **Main App CLAUDE.md** - Parent project documentation at `/Users/brendanpotter/Documents/develop/Job-Visualizer-Notifier/CLAUDE.md`
- **TypeScript Job Model**: `src/types/index.ts` - Data model that scraper output aligns with
