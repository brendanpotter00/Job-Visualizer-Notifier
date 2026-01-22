"""
Configuration constants for Microsoft Jobs scraper

Microsoft uses Eightfold as their ATS platform and provides JSON APIs
for job search and details.
"""

# Base URLs
BASE_URL = "https://apply.careers.microsoft.com"
API_BASE = "/api/pcsx"

# API Endpoints
SEARCH_ENDPOINT = f"{API_BASE}/search"
DETAILS_ENDPOINT = f"{API_BASE}/position_details"

# Domain parameter (required for API calls)
DOMAIN = "microsoft.com"

# Location filter
LOCATION_FILTER = "United States"

# Search queries (Microsoft supports keyword search)
SEARCH_QUERIES = ["software engineer"]

# Title keywords to include (case-insensitive)
# Core keywords that cover 95%+ of software/data roles
INCLUDE_TITLE_KEYWORDS = [
    "software",
    "engineer",
    "developer",
    "data",
    "ML",
    "AI",
    "cloud",
    "security",
    "research",
    "SRE",
    "devops",
]

# Title keywords to exclude (non-tech roles)
EXCLUDE_TITLE_KEYWORDS = [
    "recruiter",
    "sales",
    "marketing",
    "HR",
    "retail",
    "account executive",
]

# Rate limiting
REQUEST_DELAY_MIN = 2.0  # seconds between requests
REQUEST_DELAY_MAX = 5.0  # random jitter
PAGE_LOAD_TIMEOUT = 30000  # milliseconds
SESSION_ESTABLISH_DELAY = 2.0  # seconds to wait after page load for session

# Pagination
JOBS_PER_PAGE = 10  # Microsoft's API returns 10 jobs per page
MAX_PAGES = 500  # Safety limit (500 * 10 = 5000 jobs max)

# Retry configuration
MAX_RETRIES = 3
RETRY_MIN_WAIT = 4  # seconds
RETRY_MAX_WAIT = 60  # seconds

# Output configuration
DEFAULT_OUTPUT_DIR = "scripts/output"
DEFAULT_OUTPUT_FILE = "microsoft_jobs.json"
