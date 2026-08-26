"""
Configuration constants for Amazon Jobs scraper

Amazon exposes a public JSON search endpoint (``/en/search.json``) that returns
the full job description inline, so this scraper never needs a per-job detail
fetch. See ``api_client.py`` for the request shape.
"""

# Base URLs
BASE_URL = "https://www.amazon.jobs"
SEARCH_PATH = "/en/search.json"

# Navigable HTML page used to establish a same-origin browsing context before
# the in-page fetch() runs. Load-bearing: the JSON endpoint sends no
# Access-Control-Allow-Origin header, so a fetch() from about:blank is blocked
# by CORS. Verified live 2026-08-09.
SESSION_PATH = "/en/search?base_query=software+engineer&country=USA"

# Server-side search filters (mirrors the sibling job-watcher adapter's scope)
COUNTRY = "USA"
SORT = "recent"

# Search queries (Amazon supports free-text relevance search via base_query)
SEARCH_QUERIES = ["software engineer"]

# Title keywords to include (case-insensitive substring match).
# Tuned for Amazon's vocabulary: "SDE" and "Engr" are Amazon-specific
# abbreviations that a generic list would drop.
INCLUDE_TITLE_KEYWORDS = [
    "software",
    "engineer",
    "engr",
    "developer",
    "data",
    "machine learning",
    "ml",
    "ai",
    "cloud",
    "security",
    "research",
    "scientist",
    "sre",
    "devops",
    "sde",
    "architect",
    "analyst",
]

# Title keywords to exclude (non-tech roles).
#
# Multi-word and unambiguous terms ONLY, matched on word boundaries by
# ``AmazonJobsScraper.filter_job``. Bare "HR" is deliberately absent: as a
# substring it matches "T-h-r-eat", silently dropping real listings such as
# "Software Development Engineer II - Threat Intelligence Systems" (observed
# live). An INCLUDE false-positive is harmless because Amazon already narrowed
# by relevance server-side; an EXCLUDE false-positive loses a real job.
EXCLUDE_TITLE_KEYWORDS = [
    "recruiter",
    "recruiting",
    "account executive",
    "sales representative",
    "human resources",
    "retail associate",
    "marketing manager",
    "executive assistant",
]

# Rate limiting
REQUEST_DELAY_MIN = 2.0  # seconds between requests
REQUEST_DELAY_MAX = 5.0  # random jitter
PAGE_LOAD_TIMEOUT = 30000  # milliseconds
SESSION_ESTABLISH_DELAY = 2.0  # seconds to wait after page load for session

# Pagination
# result_limit is a HARD cap at 100 — the API answers 200 with
# {"error": "Result limit cannot be greater than 100", "jobs": null}.
JOBS_PER_PAGE = 100
MAX_PAGES = 50  # safety bound (~5000 jobs; live `hits` was 1303 on 2026-08-09)

# Give up on a query after this many consecutive page failures
MAX_CONSECUTIVE_ERRORS = 3

# Output configuration
DEFAULT_OUTPUT_DIR = "scripts/output"
DEFAULT_OUTPUT_FILE = "amazon_jobs.json"
