"""
Configuration constants for Google Jobs scraper
"""

# Base URLs
BASE_URL = "https://www.google.com/about/careers/applications/jobs/results"

# Search queries for software/developer/data science roles
# Simplified for testing - uncomment others after verification
SEARCH_QUERIES = [
    "software engineer",
    # "software developer",
    # "frontend engineer",
    # "backend engineer",
    # "full stack engineer",
    # "data scientist",
    # "data engineer",
    # "machine learning engineer",
    # "DevOps engineer",
    # "SRE",
    # "platform engineer",
]

# Location filter
LOCATION_FILTER = "United States"

# Title keywords to include (case-insensitive)
INCLUDE_TITLE_KEYWORDS = [
    "software",
    "engineer",
    "developer",
    "frontend",
    "backend",
    "full stack",
    "fullstack",
    "data scientist",
    "data engineer",
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
    "operations manager",
    "support specialist",
    "program manager",
    "product manager",
    "technical program manager",
]

# Rate limiting
REQUEST_DELAY_MIN = 2.0  # seconds between requests
REQUEST_DELAY_MAX = 5.0  # random jitter
PAGE_LOAD_TIMEOUT = 30000  # milliseconds

# Pagination
JOBS_PER_PAGE = 20
MAX_PAGES = 50  # Safety limit (50 * 20 = 1000 jobs max per query)

# Retry configuration
MAX_RETRIES = 3
RETRY_MIN_WAIT = 4  # seconds
RETRY_MAX_WAIT = 60  # seconds

# Checkpoint configuration
CHECKPOINT_INTERVAL = 100  # Save checkpoint every N jobs
CHECKPOINT_FILE = "scripts/output/.checkpoint.json"

# Output configuration
DEFAULT_OUTPUT_DIR = "scripts/output"
DEFAULT_OUTPUT_FILE = "google_jobs.json"
