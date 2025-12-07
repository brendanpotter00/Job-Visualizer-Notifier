# Google Jobs Scraper Architecture

## Overview

The Google Jobs Scraper is a production-ready web scraper that uses Playwright browser automation to extract software engineering job listings from Google Careers. The system is designed to be modular, resilient, and resumable with anti-detection measures.

## Directory Structure

```
scripts/
├── run_scraper.py                          # Main entry point (dual-mode: JSON/Database)
├── requirements.txt                         # Python dependencies
├── requirements-dev.txt                     # Development dependencies (NEW)
├── pytest.ini                               # Test configuration (NEW)
├── README.md                                # User documentation
├── ARCHITECTURE.md                          # This file
├── CLAUDE.md                                # Quick reference
├── __init__.py                              # Package marker
├── google_jobs_scraper/                     # Google-specific implementation
│   ├── __init__.py                          # Package metadata
│   ├── main.py                              # CLI orchestration (JSON mode)
│   ├── config.py                            # Configuration constants
│   ├── models.py                            # Pydantic data models
│   ├── scraper.py                           # Playwright automation (extends BaseScraper)
│   ├── parser.py                            # HTML parsing and data extraction
│   └── utils.py                             # Helper functions
├── shared/                                  # Multi-scraper framework (NEW)
│   ├── __init__.py                          # Package marker
│   ├── base_scraper.py                      # Abstract base class for scrapers
│   ├── database.py                          # SQLite/PostgreSQL abstraction
│   ├── incremental.py                       # 5-phase incremental algorithm
│   └── models.py                            # Database-aligned Pydantic models
├── tests/                                   # Test suite (NEW)
│   ├── __init__.py                          # Package marker
│   ├── conftest.py                          # Shared pytest fixtures
│   ├── fixtures/                            # HTML fixtures for parser tests
│   ├── unit/                                # Unit tests
│   │   ├── test_models.py                   # JobListing/ScrapeRun validation
│   │   ├── test_incremental_diff.py         # Job diff algorithm
│   │   ├── test_parser_helpers.py           # Salary/remote detection
│   │   └── test_utils.py                    # Filtering, ID extraction
│   └── integration/                         # Integration tests
│       ├── test_database.py                 # Database CRUD operations
│       ├── test_incremental.py              # 5-phase algorithm
│       └── test_scraper_transform.py        # Job transformation
└── output/                                  # Generated output
    ├── google_jobs.json                     # Scraped job data (JSON mode)
    ├── .checkpoint.json                     # Resume checkpoint (JSON mode, temporary)
    └── *.db                                 # SQLite databases (database mode)
```

## Data Flow Diagram

```mermaid
flowchart TD
    Start([User runs python scripts/run_scraper.py]) --> Entry[run_scraper.py]
    Entry --> CLI[main.py:main<br/>Parse CLI arguments]
    CLI --> Orchestrate[main.py:run_scraper]

    Orchestrate --> LoadCP{Resume mode?}
    LoadCP -->|Yes| LoadCPFile[utils.py:load_checkpoint]
    LoadCP -->|No| InitBrowser[Initialize Playwright Browser]
    LoadCPFile --> InitBrowser

    InitBrowser --> QueryLoop[For each search query]

    QueryLoop --> BuildURL[Build URL with query + location filter]
    BuildURL --> Navigate[Navigate to Google Jobs page<br/>wait for networkidle]
    Navigate --> ExtractList[parser.py:extract_job_cards_from_list<br/>Parse h3 headings, extract URLs]

    ExtractList --> FilterTitle{Title matches<br/>include/exclude<br/>keywords?}
    FilterTitle -->|No| Skip[Skip job]
    FilterTitle -->|Yes| AddJob[Add to job list]

    AddJob --> CheckPage{Next page<br/>exists?}
    CheckPage -->|Yes| Delay1[Rate limit delay 2-5s]
    Delay1 --> Navigate
    CheckPage -->|No| DetailCheck{--detail-scrape<br/>enabled?}

    DetailCheck -->|Yes| DetailLoop[For each job URL]
    DetailLoop --> DetailNav[Navigate to job detail page]
    DetailNav --> ExtractDetail[parser.py:extract_job_details<br/>Parse qualifications, salary, etc.]
    ExtractDetail --> MergeData[Merge with list page data]
    MergeData --> Delay2[Rate limit delay 2-5s]
    Delay2 --> DetailNext{More jobs?}
    DetailNext -->|Yes| DetailLoop
    DetailNext -->|No| SaveCP

    DetailCheck -->|No| SaveCP{100 jobs<br/>processed?}
    SaveCP -->|Yes| Checkpoint[utils.py:save_checkpoint]
    SaveCP -->|No| NextQuery
    Checkpoint --> NextQuery{More queries?}

    NextQuery -->|Yes| QueryLoop
    NextQuery -->|No| Dedup[scraper.py:deduplicate_jobs<br/>Remove duplicates by URL]

    Dedup --> Transform[scraper.py:transform_to_job_model<br/>Convert to GoogleJob Pydantic models]
    Transform --> CreateOutput[Create ScraperOutput with metadata]
    CreateOutput --> WriteJSON[Write to google_jobs.json]
    WriteJSON --> Cleanup[Delete checkpoint file]
    Cleanup --> End([Complete])

    Skip --> CheckPage

    style Start fill:#e1f5e1
    style End fill:#e1f5e1
    style ExtractList fill:#fff4e6
    style ExtractDetail fill:#fff4e6
    style FilterTitle fill:#ffe6e6
    style DetailCheck fill:#ffe6e6
    style Checkpoint fill:#e6f3ff
    style WriteJSON fill:#e6f3ff
```

## Component Descriptions

### 1. run_scraper.py
**Purpose:** Convenience wrapper that adds project root to Python path and launches the main entry point.

**Usage:**
```bash
python scripts/run_scraper.py [options]
```

### 2. main.py
**Purpose:** CLI orchestration and async runner.

**Key Functions:**
- `main()` - Parses command-line arguments with rich formatting
- `run_scraper(args)` - Async orchestration function that coordinates the entire scraping process

**CLI Arguments:**
- `--output, -o` - Output JSON file path (default: `google_jobs.json`)
- `--queries, -q` - Custom search queries (space-separated)
- `--detail-scrape` - Scrape individual job detail pages for complete data
- `--max-jobs` - Maximum number of jobs to scrape
- `--resume` - Resume from checkpoint
- `--headless/--no-headless` - Browser visibility toggle
- `--verbose, -v` - Enable verbose logging

### 3. config.py
**Purpose:** Centralized configuration constants.

**Key Configuration:**
```python
BASE_URL = "https://www.google.com/about/careers/applications/jobs/results"
SEARCH_QUERIES = ["software engineer", ...]
LOCATION_FILTER = "United States"
INCLUDE_TITLE_KEYWORDS = ["software", "engineer", "developer", ...]
EXCLUDE_TITLE_KEYWORDS = ["recruiter", "sales", "marketing", ...]
REQUEST_DELAY_MIN = 2.0  # seconds
REQUEST_DELAY_MAX = 5.0  # seconds
PAGE_LOAD_TIMEOUT = 30000  # milliseconds
JOBS_PER_PAGE = 20
MAX_PAGES = 50  # Max 1000 jobs per query
```

### 4. models.py
**Purpose:** Pydantic data models for type safety and validation.

**Models:**

**GoogleJob** - Aligned with TypeScript Job interface:
- Core fields: `id`, `source`, `company`, `title`, `location`, `createdAt`, `url`
- Extended fields: `experience_level`, `minimum_qualifications`, `preferred_qualifications`, `about_the_job`, `responsibilities`, `apply_url`, `salary_range`, `is_remote_eligible`
- Metadata: `scraped_at`, `raw`

**ScraperOutput** - JSON output format:
- `scraped_at` - ISO timestamp
- `total_jobs` - Total jobs seen across all queries
- `filtered_jobs` - After deduplication
- `metadata` - Search queries, duration, location filter, etc.
- `jobs` - List of GoogleJob objects

**CheckpointData** - For resuming interrupted scrapes:
- `completed_queries` - Which searches finished
- `jobs` - Partially scraped jobs
- `total_jobs_seen` - Running counter
- `last_updated` - ISO timestamp

### 5. scraper.py
**Purpose:** Browser automation using Playwright.

**GoogleJobsScraper Class:**

**Key Methods:**
- `scrape_query(search_query, max_jobs)` - Main scraping loop for a single query
  - Builds URL with search query and location filter
  - Navigates to page and extracts job cards
  - Filters by title keywords
  - Handles pagination with rate limiting

- `scrape_job_details_batch(job_cards)` - Optional detail scraping
  - Navigates to each job's detail page
  - Extracts full qualifications, responsibilities, salary
  - Merges with basic info from list page
  - Includes error handling to preserve basic info on failures

- `deduplicate_jobs(jobs)` - Removes duplicates by URL
  - Transforms dictionaries to GoogleJob Pydantic models

- `transform_to_job_model(job_data)` - Converts raw data to GoogleJob model
  - Extracts job ID from URL
  - Sets timestamps
  - Maps fields to model

**Anti-Detection Features:**
- Headless browser with `--disable-blink-features=AutomationControlled`
- Real user agent (Chrome on macOS)
- Viewport and locale settings
- Random delays (2-5 seconds) between requests
- Exponential backoff on errors (4-60 seconds)

### 6. parser.py
**Purpose:** HTML parsing and data extraction.

**List Page Functions:**
- `extract_job_cards_from_list(page)` - Extracts job cards from search results
  - Finds all `<h3>` elements (job titles)
  - Navigates to parent `<li>` container
  - Extracts job URL and location

**Detail Page Functions:**
- `extract_job_details(page, job_url)` - Extracts comprehensive job information
  - `extract_job_title()` - From h2 element
  - `extract_experience_level()` - From img alt text
  - `extract_qualifications()` - Minimum and preferred lists
  - `extract_about_section()` - Job description paragraphs
  - `extract_responsibilities()` - Responsibilities list
  - `extract_apply_url()` - Apply button URL

- `extract_salary_from_text(text)` - Regex pattern for salary ranges
- `check_remote_eligible(job_details)` - Detects remote work eligibility
- `check_for_next_page(page)` - Pagination detection

### 7. utils.py
**Purpose:** Helper functions for common operations.

**Categories:**
- **Rate Limiting:** `random_delay()` - Async delay between 2-5 seconds
- **Logging:** `setup_logging()`, `get_retry_decorator()`
- **Checkpoints:** `save_checkpoint()`, `load_checkpoint()`, `delete_checkpoint()`
- **Data Extraction:** `get_iso_timestamp()`, `extract_job_id_from_url()`, `should_include_job()`
- **File Operations:** `ensure_output_directory()`

---

## Shared Modules (NEW)

The `shared/` directory contains reusable components for multi-company scraper support.

### 8. shared/base_scraper.py
**Purpose:** Abstract base class providing shared browser automation and defining the scraper interface.

**Abstract Methods** (must be implemented by subclasses):
- `get_company_name() -> str` - Return company identifier (e.g., "google")
- `build_search_url(query, page_num) -> str` - Build company-specific search URL
- `async extract_job_cards(page) -> List[Dict]` - Extract jobs from search results page
- `async extract_job_details(page, url) -> Dict` - Extract detailed job information
- `get_search_queries() -> List[str]` - Return list of search queries
- `filter_job(title) -> bool` - Determine if job should be included

**Concrete Methods** (shared implementation):
- `async __aenter__()` / `async __aexit__()` - Async context manager for browser lifecycle
- `async initialize_browser()` - Launch Chromium with anti-detection settings
- `async close_browser()` - Cleanup browser resources
- `async navigate_to_page(page, url, timeout)` - Navigate with retry logic
- `async scrape_all_queries(max_jobs)` - Scrape all search queries

**Anti-Detection Configuration:**
- User agent: `Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ... Chrome/120.0.0.0`
- Viewport: 1920x1080
- Locale: en-US
- Browser args: `--disable-blink-features=AutomationControlled`

### 9. shared/database.py
**Purpose:** Database abstraction layer supporting SQLite (local) and PostgreSQL (production).

**Connection Management:**
- `get_connection(db_url, env) -> Connection` - Create DB connection from URL
  - SQLite: `sqlite:///path/to/file.db`
  - PostgreSQL: `postgresql://user:pass@host:port/dbname`
- `init_schema(conn, env)` - Create tables with environment-based naming

**Schema:**
- `job_listings_{env}` table:
  - Primary: id, title, company, location, url, source_id
  - Details: details (JSONB), posted_on, created_at, closed_on
  - Status: status, has_matched, ai_metadata (JSONB)
  - Incremental: first_seen_at, last_seen_at, consecutive_misses, details_scraped
- `scrape_runs_{env}` table:
  - Metadata: run_id, company, started_at, completed_at, mode
  - Statistics: jobs_seen, new_jobs, closed_jobs, details_fetched, error_count

**Query Operations:**
- `get_active_job_ids(conn, company, env) -> Set[str]` - Get all OPEN job IDs
- `get_job_by_id(conn, job_id, env) -> JobListing` - Retrieve job by ID
- `get_all_active_jobs(conn, company, env) -> List[JobListing]` - Fetch all OPEN jobs
- `insert_job(conn, job, env)` - Insert new job (with upsert logic)

**Status Updates:**
- `update_last_seen(conn, job_ids, env)` - Update timestamp, reset consecutive_misses
- `increment_consecutive_misses(conn, job_ids, env)` - Track missing jobs
- `mark_jobs_closed(conn, job_ids, env)` - Mark jobs as CLOSED
- `reactivate_job(conn, job_id, env)` - Reopen closed jobs if they reappear

**Audit Trail:**
- `record_scrape_run(conn, run_data, env)` - Log scrape execution metadata

**Features:**
- JSON serialization/deserialization for JSONB fields
- Indexes on status, company, last_seen_at for performance
- Environment-based table naming (local/qa/prod)

### 10. shared/incremental.py
**Purpose:** 5-phase incremental scraping algorithm that minimizes scraping time.

**Algorithm Overview:**
```
Phase 1: Quick list scrape (2-3 min) → Extract job IDs + basic info
Phase 2: Compare with database → Identify new, active, missing jobs
Phase 3: Fetch details for NEW jobs only → Minimizes detail page requests
Phase 4: Update existing jobs → Reset last_seen, increment misses
Phase 5: Mark as closed → consecutive_misses >= THRESHOLD (2)
```

**Key Functions:**
- `run_incremental_scrape(scraper, conn, env, company, detail_scrape) -> ScrapeResult`
  - Main orchestration function
  - Returns statistics (jobs_seen, new_jobs, closed_jobs, details_fetched)

- `calculate_job_diff(current_ids, known_ids, active_ids) -> Tuple`
  - Compare current scrape vs database
  - Returns: (new_job_ids, still_active_ids, missing_ids)
  - Uses set operations for O(1) lookups

- `process_new_jobs(scraper, conn, new_job_cards, env, detail_scrape)`
  - Insert only NEW jobs into database
  - Optional detail scraping via `scraper.scrape_job_details_batch()`
  - Sets incremental tracking fields

- `update_existing_jobs(conn, still_active, missing, env)`
  - Update last_seen_at for still-active jobs
  - Increment consecutive_misses for missing jobs
  - Mark as CLOSED when consecutive_misses >= 2

**Data Models:**
- `ScrapeResult` - Result object with counters
- `MISSED_RUN_THRESHOLD = 2` - Jobs marked closed after 2 consecutive misses

### 11. shared/models.py
**Purpose:** Database-aligned Pydantic models.

**JobListing Model:**
```python
class JobListing(BaseModel):
    id: str
    title: str
    company: str = "google"
    location: Optional[str]
    url: str
    source_id: str = "google_scraper"
    details: Dict[str, Any]           # JSONB for qualifications, etc.
    posted_on: Optional[str]
    created_at: str
    closed_on: Optional[str]
    status: str = "OPEN"
    has_matched: bool = False
    ai_metadata: Dict[str, Any]
    first_seen_at: Optional[str]      # Incremental tracking
    last_seen_at: Optional[str]
    consecutive_misses: int = 0
    details_scraped: bool = False

GoogleJob = JobListing  # Alias for backwards compatibility
```

**ScrapeRun Model:**
```python
class ScrapeRun(BaseModel):
    run_id: str
    company: str
    started_at: str
    completed_at: Optional[str]
    mode: str                          # "incremental" or "full"
    jobs_seen: int
    new_jobs: int
    closed_jobs: int
    details_fetched: int
    error_count: int
```

---

## Database Mode

The scraper supports dual-mode operation: JSON output (legacy) and database persistence (NEW).

### Mode Selection

**JSON Mode** (default when `--db-url` not provided):
- Outputs to `scripts/output/google_jobs.json`
- Supports checkpoint/resume functionality
- Deduplicates jobs by URL
- Compatible with Redux store ingestion

**Database Mode** (when `--db-url` provided):
- Stores jobs in relational database (SQLite or PostgreSQL)
- Supports incremental scraping
- Tracks job lifecycle (open → missing → closed)
- Environment-based table naming

### Database Schema

**job_listings_{env} Table:**
| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PRIMARY KEY | Job ID from URL |
| title | TEXT NOT NULL | Job title |
| company | TEXT NOT NULL | Company name |
| location | TEXT | Job location |
| url | TEXT UNIQUE NOT NULL | Job detail URL |
| source_id | TEXT NOT NULL | Scraper identifier |
| details | TEXT/JSONB | Job details (qualifications, etc.) |
| posted_on | TEXT | When job was posted |
| created_at | TEXT NOT NULL | First time scraped |
| closed_on | TEXT | When job was closed |
| status | TEXT NOT NULL | OPEN or CLOSED |
| has_matched | BOOLEAN | AI notification flag |
| ai_metadata | TEXT/JSONB | AI matched tags |
| first_seen_at | TEXT | First discovery timestamp |
| last_seen_at | TEXT | Last seen in search results |
| consecutive_misses | INTEGER | Counter for disappearances |
| details_scraped | BOOLEAN | Whether detail page fetched |

**scrape_runs_{env} Table:**
| Column | Type | Description |
|--------|------|-------------|
| run_id | TEXT PRIMARY KEY | Unique run identifier |
| company | TEXT NOT NULL | Company scraped |
| started_at | TEXT NOT NULL | Run start timestamp |
| completed_at | TEXT | Run completion timestamp |
| mode | TEXT NOT NULL | "incremental" or "full" |
| jobs_seen | INTEGER | Total jobs in scrape |
| new_jobs | INTEGER | New jobs added |
| closed_jobs | INTEGER | Jobs marked closed |
| details_fetched | INTEGER | Detail pages scraped |
| error_count | INTEGER | Errors encountered |

### Incremental Scraping Flow

```
1. Run quick list scrape (no details)
   ↓
2. Get active job IDs from database
   ↓
3. Compare: new_jobs = current - known
            still_active = current ∩ known
            missing = known - current
   ↓
4. Fetch details ONLY for new jobs
   ↓
5. Update database:
   - Insert new jobs with first_seen_at
   - Update last_seen_at for still_active
   - Increment consecutive_misses for missing
   - Mark as CLOSED if consecutive_misses >= 2
   ↓
6. Record scrape_run metadata
```

**Performance Benefits:**
- First run: ~15-30 min (full scrape with details)
- Subsequent runs: ~2-3 min (list only) + details for new jobs
- Example: 500 jobs, 10 new → 2 min + 30 sec (vs 15-30 min full scrape)

---

## Testing

### Test Structure

**tests/conftest.py** - Shared pytest fixtures:
- `sample_job_data_dict` - Raw scraped job data
- `sample_job_listing` - Valid JobListing model
- `in_memory_db` - SQLite in-memory database
- `mock_scraper` - Mocked GoogleJobsScraper
- `html_fixture` - Factory for loading HTML fixtures

**Unit Tests** (tests/unit/):
- `test_models.py` - JobListing and ScrapeRun validation
- `test_incremental_diff.py` - calculate_job_diff() logic
- `test_parser_helpers.py` - extract_salary_from_text(), check_remote_eligible()
- `test_utils.py` - should_include_job(), extract_job_id_from_url()

**Integration Tests** (tests/integration/):
- `test_database.py` - Database operations with real SQLite
- `test_incremental.py` - Full 5-phase algorithm execution
- `test_scraper_transform.py` - transform_to_job_model(), deduplicate_jobs()

### Running Tests

```bash
# All tests
pytest

# Specific test types
pytest tests/unit
pytest tests/integration

# With coverage
pytest --cov=google_jobs_scraper --cov=shared

# Verbose output
pytest -v --tb=short
```

### Test Configuration (pytest.ini)

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
asyncio_mode = auto
addopts = -v --tb=short
markers =
    unit: Unit tests without external dependencies
    integration: Tests requiring database/mocks
```

---

## Configuration Options

### Environment Setup
```bash
# Install dependencies
pip install -r scripts/requirements.txt

# Install Playwright browsers
playwright install chromium
```

### Running the Scraper

**Basic usage:**
```bash
python scripts/run_scraper.py
```

**Custom queries:**
```bash
python scripts/run_scraper.py -q "machine learning" "data scientist"
```

**Full detail scrape:**
```bash
python scripts/run_scraper.py --detail-scrape
```

**Resume interrupted scrape:**
```bash
python scripts/run_scraper.py --resume
```

**Visible browser (for debugging):**
```bash
python scripts/run_scraper.py --no-headless
```

**Limit jobs and enable verbose logging:**
```bash
python scripts/run_scraper.py --max-jobs 100 -v
```

## Output Format

The scraper generates `scripts/output/google_jobs.json`:

```json
{
  "scraped_at": "2025-12-05T03:01:09.415308Z",
  "total_jobs": 150,
  "filtered_jobs": 142,
  "metadata": {
    "search_queries": ["software engineer", "machine learning"],
    "completed_queries": ["software engineer", "machine learning"],
    "location_filter": "United States",
    "scrape_duration_seconds": 245.12,
    "detail_scrape": true
  },
  "jobs": [
    {
      "id": "114423471240291014",
      "source": "google",
      "company": "google",
      "title": "Software Engineer",
      "location": "Mountain View, CA, USA",
      "createdAt": "2025-12-05T03:01:09.414928Z",
      "url": "https://www.google.com/about/careers/applications/jobs/results/114423471240291014-software-engineer",
      "experience_level": "Mid",
      "minimum_qualifications": [
        "Bachelor's degree or equivalent practical experience",
        "8 years of experience in software development"
      ],
      "preferred_qualifications": [
        "Master's degree in Computer Science",
        "Experience with distributed systems"
      ],
      "about_the_job": "Google's software engineers develop the next-generation technologies...",
      "responsibilities": [
        "Provide technical leadership on high-impact projects",
        "Design, develop, test, deploy, maintain, and improve software"
      ],
      "apply_url": "https://www.google.com/about/careers/applications/apply?...",
      "salary_range": "$197,000-$291,000 + bonus + equity + benefits",
      "is_remote_eligible": true,
      "scraped_at": "2025-12-05T03:01:09.414928Z",
      "raw": {}
    }
  ]
}
```

## Key Features

### Robustness
- **Checkpoint System:** Automatically saves progress every 100 jobs, allowing scrapes to resume after interruptions
- **Error Handling:** Graceful fallbacks - preserves basic info if detail page scraping fails
- **Retry Logic:** Exponential backoff with tenacity for transient failures
- **Logging:** Multi-level logging (DEBUG, INFO, ERROR) with rich console output

### Performance
- **Async/Await:** Concurrent operations using asyncio
- **Pagination:** Supports up to 50 pages per query (1000 jobs)
- **Rate Limiting:** 2-5 second random delays to avoid detection
- **Selective Detail Scraping:** Optional `--detail-scrape` flag for complete data

### Data Quality
- **Deduplication:** Removes duplicate jobs by URL
- **Title Filtering:** Include/exclude keyword lists for relevant jobs
- **Location Filtering:** United States only by default
- **Type Safety:** Pydantic models validate all data
- **Alignment:** GoogleJob model matches TypeScript Job interface

## Dependencies

From `requirements.txt`:
- `playwright>=1.40.0` - Browser automation
- `pydantic>=2.0.0` - Data validation and models
- `python-dateutil>=2.8.0` - Date/time utilities
- `tenacity>=8.0.0` - Retry logic with exponential backoff
- `rich>=13.0.0` - Beautiful console output
- `psycopg2-binary>=2.9.9` - PostgreSQL database driver (NEW)

From `requirements-dev.txt` (NEW):
- `pytest>=7.4.0` - Testing framework
- `pytest-asyncio>=0.21.0` - Async test support
- `pytest-mock>=3.11.0` - Mocking utilities

## Error Handling & Recovery

### Checkpoint Recovery
If the scraper is interrupted (Ctrl+C, crash, etc.):
1. Progress is saved to `scripts/output/.checkpoint.json`
2. Resume with: `python scripts/run_scraper.py --resume`
3. Checkpoint includes completed queries and partially scraped jobs
4. Automatically deleted on successful completion

### Rate Limiting & Anti-Detection
- Random delays between requests (2-5 seconds)
- Exponential backoff on errors (4, 8, 16, 32, 60 seconds max)
- Browser configured to avoid automation detection
- Network idle wait ensures pages fully load

### Graceful Degradation
- If detail page scraping fails, basic info from list page is preserved
- Individual job failures don't stop the entire scrape
- Partial results are always saved

## Integration with Main Application

The scraper output format is designed to integrate with the Job Visualizer SPA:

1. **Data Model Alignment:** GoogleJob model matches the TypeScript `Job` interface used by the React application
2. **Source Field:** Set to `"google"` for filtering in the UI
3. **Company Field:** Set to `"google"` for company-specific views
4. **Timestamp Fields:** ISO 8601 format compatible with Redux state

The output JSON can be imported into the application's data pipeline or used to populate the Redux store directly.
