"""
Configuration constants for the TikTok Jobs scraper.

TikTok's careers site (lifeattiktok.com) is backed by a public JSON search
endpoint that returns plain-text descriptions inline, so this scraper never
needs a per-job detail fetch. See ``api_client.py`` for the request shape.
"""

# Base URLs
API_BASE_URL = "https://api.lifeattiktok.com"
SEARCH_PATH = "/api/v1/public/supplier/search/job/posts"

# Public site origin. Job URLs hang off it, and — because the API sends no
# Access-Control-Allow-Origin header — the browser must be sitting on this
# origin before the in-page fetch() runs. Verified live 2026-08-09.
SITE_URL = "https://lifeattiktok.com"
SESSION_PATH = "/search"
JOB_URL_PREFIX = f"{SITE_URL}/search"

# The `website-path` header selects which brand's job pool to search and is
# REQUIRED — without it the edge answers HTTP 400 (verified live).
WEBSITE_PATH = "tiktok"

# Search queries. TikTok supports free-text keyword search; the unfiltered
# catalogue is ~3,900 roles globally across every function, which is far wider
# than this project tracks. "software engineer" narrows it to ~716.
SEARCH_QUERIES = ["software engineer"]

# Location filter, applied CLIENT-SIDE against the flattened city_info string.
#
# Deliberately not server-side: `location_code_list` accepts *city* codes
# (e.g. CT_163) and silently returns count=0 for country codes (CN_6 = USA),
# so filtering there would need a brittle hardcoded list of every US city code.
# Matching the country name on the flattened location is the same
# fetch-then-filter shape the Apple scraper uses.
LOCATION_FILTER = "United States"

# Title keywords to include (case-insensitive substring match)
INCLUDE_TITLE_KEYWORDS = [
    "software",
    "engineer",
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
    "architect",
    "analyst",
    "infrastructure",
    "backend",
    "frontend",
    "full stack",
]

# Title keywords to exclude (non-tech roles).
#
# Multi-word / unambiguous terms only, matched on WORD BOUNDARIES by
# ``TikTokJobsScraper.filter_job``. Bare "HR" is deliberately absent: as a
# substring it matches "T-h-r-eat" and silently drops real listings.
EXCLUDE_TITLE_KEYWORDS = [
    "recruiter",
    "recruiting",
    "account executive",
    "sales representative",
    "human resources",
    "executive assistant",
    "content moderator",
]

# Rate limiting
REQUEST_DELAY_MIN = 2.0  # seconds between requests
REQUEST_DELAY_MAX = 5.0  # random jitter
PAGE_LOAD_TIMEOUT = 30000  # milliseconds
SESSION_ESTABLISH_DELAY = 2.0  # seconds to wait after page load for session

# Pagination
# The API honours limit=500 without clamping, but 100 keeps each response
# small and matches the sibling job-watcher adapter.
JOBS_PER_PAGE = 100
MAX_PAGES = 50  # safety bound (~5000 jobs; keyword-filtered count was 716)

# Give up on a query after this many consecutive page failures
MAX_CONSECUTIVE_ERRORS = 3

# Output configuration
DEFAULT_OUTPUT_DIR = "scripts/output"
DEFAULT_OUTPUT_FILE = "tiktok_jobs.json"
