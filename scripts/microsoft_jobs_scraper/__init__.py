"""
Microsoft Jobs Scraper

Scrapes job listings from Microsoft Careers (apply.careers.microsoft.com)
using the Eightfold ATS platform APIs.
"""

from .scraper import MicrosoftJobsScraper
from .config import (
    BASE_URL,
    API_BASE,
    DOMAIN,
    LOCATION_FILTER,
    SEARCH_QUERIES,
    INCLUDE_TITLE_KEYWORDS,
    EXCLUDE_TITLE_KEYWORDS,
    JOBS_PER_PAGE,
    MAX_PAGES,
)
from .api_client import (
    fetch_search_results,
    fetch_job_details,
    get_apply_url,
    JobSearchError,
    JobDetailsFetchError,
)
from .parser import (
    extract_job_cards_from_list,
    extract_position_id_from_url,
    check_has_next_page,
    JobCardExtractionError,
)

__all__ = [
    # Main scraper class
    "MicrosoftJobsScraper",
    # Config
    "BASE_URL",
    "API_BASE",
    "DOMAIN",
    "LOCATION_FILTER",
    "SEARCH_QUERIES",
    "INCLUDE_TITLE_KEYWORDS",
    "EXCLUDE_TITLE_KEYWORDS",
    "JOBS_PER_PAGE",
    "MAX_PAGES",
    # API client
    "fetch_search_results",
    "fetch_job_details",
    "get_apply_url",
    "JobSearchError",
    "JobDetailsFetchError",
    # Parser
    "extract_job_cards_from_list",
    "extract_position_id_from_url",
    "check_has_next_page",
    "JobCardExtractionError",
]
