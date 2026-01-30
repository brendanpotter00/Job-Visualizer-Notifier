"""
Configuration constants for TikTok Jobs scraper
"""

# Base URLs
BASE_URL = "https://lifeattiktok.com"
SEARCH_PATH = "/search"

# Search configuration
SEARCH_QUERIES = ["software engineer"]
DEFAULT_LIMIT = 12  # Jobs per page (TikTok's default)

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
    "specialist",
    "content",
    "creative",
    "policy",
    "trust",
    "safety",
]

# Rate limiting
REQUEST_DELAY_MIN = 2.0  # seconds between requests
REQUEST_DELAY_MAX = 5.0  # random jitter
PAGE_LOAD_TIMEOUT = 30000  # milliseconds

# Pagination
JOBS_PER_PAGE = 12
MAX_PAGES = 75  # Safety limit (75 * 12 = 900 jobs max)

# Retry configuration
MAX_RETRIES = 3
RETRY_MIN_WAIT = 4  # seconds
RETRY_MAX_WAIT = 60  # seconds

# Output configuration
DEFAULT_OUTPUT_DIR = "scripts/output"
DEFAULT_OUTPUT_FILE = "tiktok_jobs.json"
