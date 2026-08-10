"""
Amazon Jobs scraper package.

Scrapes amazon.jobs via its public JSON search endpoint. The list payload
carries the full description inline, so there is no detail-fetch phase.
"""

from .scraper import AmazonJobsScraper
from .config import (
    BASE_URL,
    COUNTRY,
    EXCLUDE_TITLE_KEYWORDS,
    INCLUDE_TITLE_KEYWORDS,
    JOBS_PER_PAGE,
    MAX_PAGES,
    SEARCH_PATH,
    SEARCH_QUERIES,
    SORT,
)
from .api_client import (
    JobDetailsFetchError,
    JobSearchError,
    build_search_api_url,
    combine_description,
    extract_location,
    fetch_search_results,
    get_job_url,
    parse_posted_date,
    strip_html,
)
from .parser import (
    JobCardExtractionError,
    build_job_url,
    extract_job_id_from_url,
)

__version__ = "1.0.0"

__all__ = [
    "AmazonJobsScraper",
    # config
    "BASE_URL",
    "COUNTRY",
    "EXCLUDE_TITLE_KEYWORDS",
    "INCLUDE_TITLE_KEYWORDS",
    "JOBS_PER_PAGE",
    "MAX_PAGES",
    "SEARCH_PATH",
    "SEARCH_QUERIES",
    "SORT",
    # api_client
    "JobDetailsFetchError",
    "JobSearchError",
    "build_search_api_url",
    "combine_description",
    "extract_location",
    "fetch_search_results",
    "get_job_url",
    "parse_posted_date",
    "strip_html",
    # parser
    "JobCardExtractionError",
    "build_job_url",
    "extract_job_id_from_url",
]
