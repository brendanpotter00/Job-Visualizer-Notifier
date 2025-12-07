# Google Jobs Scraper

A Python-based web scraper for Google Careers that extracts software engineering, developer, and data science job listings in the United States.

## Overview

This scraper uses Playwright (browser automation) to scrape job listings from Google's careers site at `https://www.google.com/about/careers/applications/jobs/results`. It filters for software-related roles in the US and outputs structured JSON data.

## Installation

### 1. Install Python Dependencies

```bash
pip install -r scripts/requirements.txt           # Core dependencies
pip install -r scripts/requirements-dev.txt       # Development/testing dependencies
```

### 2. Install Playwright Browser

```bash
playwright install chromium
```

## Usage

### Basic Usage

```bash
# Scrape software/developer/data science jobs in the US
python scripts/run_scraper.py
```

This will:
- Search for software engineering, developer, and data science roles
- Filter to United States locations only
- Save results to `scripts/output/google_jobs.json`

### Advanced Options

```bash
# Scrape with full job details (slower, more complete data)
python scripts/run_scraper.py --detail-scrape

# Limit to 100 jobs for testing
python scripts/run_scraper.py --max-jobs 100

# Custom output file
python scripts/run_scraper.py -o data/google_jobs_dec2024.json

# Resume interrupted scrape
python scripts/run_scraper.py --resume

# Show browser window (useful for debugging)
python scripts/run_scraper.py --no-headless

# Verbose logging
python scripts/run_scraper.py -v

# Custom search queries
python scripts/run_scraper.py -q "machine learning" "AI engineer"
```

### Database Mode (NEW)

```bash
# SQLite database (local development)
python scripts/run_scraper.py --db-url sqlite:///jobs.db

# PostgreSQL database (production)
python scripts/run_scraper.py --db-url postgresql://user:pass@host:5432/db

# Incremental scrape (smart updates - only fetch new jobs)
python scripts/run_scraper.py --db-url sqlite:///jobs.db --incremental

# Full scrape with details to database
python scripts/run_scraper.py --db-url sqlite:///jobs.db --detail-scrape

# Specify environment (affects table naming)
python scripts/run_scraper.py --db-url sqlite:///jobs.db --env prod
```

### Command Line Arguments

| Argument | Description |
|----------|-------------|
| `--output, -o` | Output JSON file path (JSON mode only) |
| `--queries, -q` | Custom search queries (space-separated) |
| `--detail-scrape` | Also scrape individual job detail pages |
| `--max-jobs` | Maximum number of jobs to scrape |
| `--resume` | Resume from checkpoint if available (JSON mode only) |
| `--headless` | Run browser in headless mode (default: True) |
| `--no-headless` | Show browser window for debugging |
| `--verbose, -v` | Enable verbose logging |
| `--company` | Which company to scrape (choices: google, all; default: google) |
| `--env` | Environment for table naming (choices: local, qa, prod; default: local) |
| `--db-url` | Database connection URL (enables database mode) |
| `--incremental` | Run incremental scrape (requires --db-url) |

## Output Format

The scraper outputs JSON with the following structure:

```json
{
  "scraped_at": "2025-12-04T20:00:00.000Z",
  "total_jobs": 689,
  "filtered_jobs": 542,
  "metadata": {
    "search_queries": ["software engineer", "data scientist", ...],
    "location_filter": "United States",
    "scrape_duration_seconds": 1847
  },
  "jobs": [
    {
      "id": "114423471240291014",
      "source": "google",
      "company": "google",
      "title": "Software Engineer III, Google Cloud",
      "location": "Mountain View, CA, USA",
      "createdAt": "2025-12-04T20:00:00.000Z",
      "url": "https://www.google.com/about/careers/applications/jobs/results/...",
      "experience_level": "Mid",
      "minimum_qualifications": ["Bachelor's degree...", ...],
      "preferred_qualifications": ["Master's degree...", ...],
      "about_the_job": "Google's software engineers develop...",
      "responsibilities": ["Write product code...", ...],
      "apply_url": "...",
      "salary_range": "$185,000-$283,000 + bonus + equity",
      "is_remote_eligible": false,
      "scraped_at": "2025-12-04T20:00:00.000Z",
      "raw": {}
    }
  ]
}
```

## How It Works

### 1. Search Queries

The scraper runs multiple search queries to capture different types of software roles:

- software engineer
- software developer
- frontend engineer
- backend engineer
- full stack engineer
- data scientist
- data engineer
- machine learning engineer
- DevOps engineer
- SRE
- platform engineer

### 2. Filtering

Jobs are filtered by:

**Location**: United States only

**Title keywords** (must include):
- software, engineer, developer, frontend, backend, data scientist, ML, AI, DevOps, SRE, platform, infrastructure, cloud, systems

**Excluded keywords** (filtered out):
- recruiter, sales, marketing, legal, finance, HR, operations manager, support specialist

### 3. Rate Limiting

To avoid detection and be respectful of Google's servers:
- 2-5 second random delay between requests
- Exponential backoff on errors
- Checkpoint saving every 100 jobs for resume capability

### 4. Data Extraction

**List page scraping** (fast):
- Job title, location, experience level
- Minimum qualifications preview
- Job URL and ID

**Detail page scraping** (with `--detail-scrape` flag):
- Preferred qualifications
- Full "About the job" section
- Responsibilities list
- Apply URL
- Salary range (when available)

## Troubleshooting

### CAPTCHA or Bot Detection

If you encounter CAPTCHAs:
1. Use `--no-headless` to see what's happening
2. Increase rate limiting delays in `config.py`
3. Run with `--max-jobs 50` to scrape smaller batches

### Timeout Errors

If pages are timing out:
1. Increase `PAGE_LOAD_TIMEOUT` in `config.py`
2. Check your internet connection
3. Try again later (Google's servers might be slow)

### Missing Job Fields

Some jobs don't have all fields (e.g., salary, preferred qualifications). This is normal - the scraper extracts what's available.

### Interrupted Scrapes

If the scrape is interrupted:
```bash
# Resume from where it left off
python -m scripts.google_jobs_scraper.main --resume
```

The scraper automatically saves checkpoints every 100 jobs.

## Configuration

Edit `scripts/google_jobs_scraper/config.py` to customize:

- `SEARCH_QUERIES`: Add/remove search terms
- `INCLUDE_TITLE_KEYWORDS`: Modify inclusion filters
- `EXCLUDE_TITLE_KEYWORDS`: Modify exclusion filters
- `REQUEST_DELAY_MIN/MAX`: Adjust rate limiting
- `MAX_PAGES`: Change pagination limit

## Testing

The scraper includes a comprehensive test suite with both unit and integration tests.

### Running Tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test types
pytest tests/unit                # Unit tests only
pytest tests/integration         # Integration tests only

# Run with coverage
pytest --cov=google_jobs_scraper --cov=shared
```

### Test Organization

- **Unit Tests** (`tests/unit/`): Test individual functions and models
  - `test_models.py` - JobListing and ScrapeRun validation
  - `test_incremental_diff.py` - Job diff algorithm
  - `test_parser_helpers.py` - Salary extraction, remote detection
  - `test_utils.py` - Filtering, ID extraction, timestamps

- **Integration Tests** (`tests/integration/`): Test with real database
  - `test_database.py` - Database operations (CRUD, schema)
  - `test_incremental.py` - 5-phase incremental algorithm
  - `test_scraper_transform.py` - Job transformation logic

## Architecture

```
scripts/
├── run_scraper.py                # Entry point with dual-mode support
├── google_jobs_scraper/          # Google-specific implementation
│   ├── main.py                   # CLI orchestration (JSON mode)
│   ├── scraper.py                # Playwright automation (extends BaseScraper)
│   ├── parser.py                 # HTML parsing and data extraction
│   ├── models.py                 # Pydantic data models
│   ├── config.py                 # Configuration constants
│   └── utils.py                  # Helper functions
├── shared/                       # Multi-scraper framework (NEW)
│   ├── base_scraper.py           # Abstract base class for scrapers
│   ├── database.py               # SQLite/PostgreSQL abstraction
│   ├── incremental.py            # 5-phase incremental algorithm
│   └── models.py                 # Database-aligned models
├── tests/                        # Test suite (NEW)
│   ├── conftest.py               # Shared fixtures
│   ├── unit/                     # Unit tests
│   └── integration/              # Integration tests
├── pytest.ini                    # Test configuration (NEW)
└── requirements-dev.txt          # Dev dependencies (NEW)
```

## Notes

- **No job post dates**: Google doesn't show when jobs were posted, so the scraper uses the scrape timestamp instead
- **Salary extraction**: Parsed from the "About the job" text when available (format: "$X-$Y + bonus + equity")
- **Resume capability** (JSON mode): The scraper saves checkpoints, so you can safely interrupt and resume
- **Deduplication**: Jobs appearing in multiple search queries are automatically deduplicated by URL
- **Database mode** (NEW): Stores jobs in SQLite or PostgreSQL with incremental tracking
- **Incremental scraping** (NEW): 5-phase algorithm only fetches details for new jobs, dramatically reducing scrape time
- **Environment-based tables** (NEW): `--env` flag creates separate tables (e.g., `job_listings_local`, `job_listings_prod`)

## Examples

### Quick Test (10 jobs)
```bash
python scripts/run_scraper.py --max-jobs 10 -v
```

### Full Scrape with Details (JSON)
```bash
python scripts/run_scraper.py --detail-scrape -o data/google_jobs_full.json
```

### Machine Learning Jobs Only
```bash
python scripts/run_scraper.py -q "machine learning" "ML engineer" "AI" -o data/ml_jobs.json
```

### Database Mode Examples (NEW)

#### Initial Full Scrape to Database
```bash
python scripts/run_scraper.py --db-url sqlite:///jobs.db --detail-scrape
```

#### Incremental Updates (Fast)
```bash
# Run daily/hourly - only fetches new jobs
python scripts/run_scraper.py --db-url sqlite:///jobs.db --incremental
```

#### Production PostgreSQL
```bash
python scripts/run_scraper.py \
  --db-url postgresql://user:pass@db.example.com:5432/jobs \
  --env prod \
  --incremental
```

## License

This scraper is for personal and educational use. Be respectful of Google's servers and adhere to their Terms of Service.
