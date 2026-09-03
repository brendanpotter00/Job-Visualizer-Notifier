"""
TikTok Jobs scraper package.

Scrapes lifeattiktok.com via its public JSON search endpoint. The list payload
carries plain-text descriptions inline, so there is no detail-fetch phase.
"""

from .scraper import TikTokJobsScraper
from .config import (
    API_BASE_URL,
    EXCLUDE_TITLE_KEYWORDS,
    INCLUDE_TITLE_KEYWORDS,
    JOBS_PER_PAGE,
    JOB_URL_PREFIX,
    LOCATION_FILTER,
    MAX_PAGES,
    SEARCH_PATH,
    SEARCH_QUERIES,
    SITE_URL,
    WEBSITE_PATH,
)
from .api_client import (
    JobDetailsFetchError,
    JobSearchError,
    build_search_body,
    combine_description,
    fetch_search_results,
    flatten_location,
    get_job_url,
    get_search_url,
)
from .parser import (
    JobCardExtractionError,
    build_job_url,
    extract_job_id_from_url,
)

__version__ = "1.0.0"

__all__ = [
    "TikTokJobsScraper",
    # config
    "API_BASE_URL",
    "EXCLUDE_TITLE_KEYWORDS",
    "INCLUDE_TITLE_KEYWORDS",
    "JOBS_PER_PAGE",
    "JOB_URL_PREFIX",
    "LOCATION_FILTER",
    "MAX_PAGES",
    "SEARCH_PATH",
    "SEARCH_QUERIES",
    "SITE_URL",
    "WEBSITE_PATH",
    # api_client
    "JobDetailsFetchError",
    "JobSearchError",
    "build_search_body",
    "combine_description",
    "fetch_search_results",
    "flatten_location",
    "get_job_url",
    "get_search_url",
    # parser
    "JobCardExtractionError",
    "build_job_url",
    "extract_job_id_from_url",
]
