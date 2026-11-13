"""
Configuration constants for Apple Jobs scraper
"""

# Base URLs
BASE_URL = "https://jobs.apple.com"
SEARCH_PATH = "/en-us/search"
API_BASE = "/api/v1"

# Location filter
LOCATION_FILTER = "united-states-USA"

# Title keywords to include (case-insensitive)
INCLUDE_TITLE_KEYWORDS = [
    "software",
    "engineer",
    "developer",
    "scientist",
    "analyst",
    "architect",
    "swe",
    "sde",
    "intern",
    "frontend",
    "backend",
    "full stack",
    "fullstack",
    "data",
    "machine learning",
    "ML",
    "AI",
    "devops",
    "SRE",
    "platform",
    "infrastructure",
    "cloud",
    "systems",
    "iOS",
    "macOS",
    "swift",
]

# Title keywords to exclude (non-software roles that might appear)
EXCLUDE_TITLE_KEYWORDS = [
    "recruiter",
    "sales",
    "marketing",
    "legal",
    "finance",
    "HR",
    "human resources",
    "manager",
    "director",
    "coordinator",
    "assistant",
    "specialist",  # Apple Retail Specialist
    "genius",  # Apple Genius Bar
    "creative",  # Apple Creative
]

# Rate limiting
REQUEST_DELAY_MIN = 2.0  # seconds between requests
REQUEST_DELAY_MAX = 5.0  # random jitter
PAGE_LOAD_TIMEOUT = 30000  # milliseconds

# Pagination
JOBS_PER_PAGE = 20
# Safety cap only — real termination is check_has_next_page's Next-button probe,
# cross-checked against Apple's advertised total-pages count (get_total_pages).
# The US board is ~226 pages (~3,350 kept) today. Bumped 250 -> 300 for headroom:
# at 250 a board that grew past 5,000 listings would have silently truncated at
# the cap. That is no longer silent — scrape_query logs a loud SCRAPER TRUNCATION
# error whenever the walk ends short of the advertised page count, including at
# this cap — but the extra headroom keeps the cap from biting a growing board in
# the first place.
MAX_PAGES = 300  # 300 * 20 = 6000 jobs max

# Per-page retry for the list walk. Apple's search backend intermittently
# answers an unchanged query with its zero-results template (HTTP 200,
# ``totalRecords: 0``, ``#search-no-search-results``); an immediate re-request
# gets the real page. From 2026-09-22 ~16:00Z this hit roughly 1 page in 10,
# and because one bad page used to abandon the whole ~228-page walk, no run
# completed for Apple from then on. A page is now retried up to
# PAGE_MAX_ATTEMPTS times total, sleeping PAGE_RETRY_BACKOFF_S[i] (plus jitter)
# before retry i+1; only when every attempt fails does the walk give up, and
# then it raises rather than returning a short list. At a 10% per-attempt flake
# rate, 5 attempts leave ~0.2% odds of losing a 228-page run.
# See docs/incidents/2026-09-22-apple-zero-results-flake.md.
PAGE_MAX_ATTEMPTS = 5
PAGE_RETRY_BACKOFF_S = (3.0, 8.0, 20.0, 45.0)

# Retry configuration
MAX_RETRIES = 3
RETRY_MIN_WAIT = 4  # seconds
RETRY_MAX_WAIT = 60  # seconds

# Output configuration
DEFAULT_OUTPUT_DIR = "scripts/output"
DEFAULT_OUTPUT_FILE = "apple_jobs.json"
