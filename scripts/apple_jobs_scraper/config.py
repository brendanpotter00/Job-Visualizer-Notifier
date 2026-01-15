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
MAX_PAGES = 250  # Safety limit (250 * 20 = 5000 jobs max)

# Retry configuration
MAX_RETRIES = 3
RETRY_MIN_WAIT = 4  # seconds
RETRY_MAX_WAIT = 60  # seconds

# Output configuration
DEFAULT_OUTPUT_DIR = "scripts/output"
DEFAULT_OUTPUT_FILE = "apple_jobs.json"
