"""
Meta Jobs scraper package.

Scrapes metacareers.com by sniffing the single GraphQL response its listings
SPA hydrates from — the whole ~890-job catalogue arrives in one shot, so there
is no pagination and no detail-fetch phase. Selection is by payload SHAPE
(``all_jobs`` / ``featured_jobs`` arrays), never by the operation/container
name, which Meta has renamed before.
"""

from .scraper import MetaJobsScraper
from .config import (
    ALL_JOBS_KEY,
    EXCLUDE_TITLE_KEYWORDS,
    FEATURED_JOBS_KEY,
    GRAPHQL_URL_SUBSTRING,
    INCLUDE_TITLE_KEYWORDS,
    JOB_COUNT_KEY,
    JOB_COUNT_SUFFIX,
    JOB_DETAIL_URL_TEMPLATE,
    LIST_URL,
    LOCATION_FILTER,
    MIN_COMPLETENESS_RATIO,
)
from .parser import (
    MetaCaptureError,
    build_job_url,
    parse_list_job,
)

__version__ = "1.0.0"

__all__ = [
    "MetaJobsScraper",
    # config
    "ALL_JOBS_KEY",
    "EXCLUDE_TITLE_KEYWORDS",
    "FEATURED_JOBS_KEY",
    "GRAPHQL_URL_SUBSTRING",
    "INCLUDE_TITLE_KEYWORDS",
    "JOB_COUNT_KEY",
    "JOB_COUNT_SUFFIX",
    "JOB_DETAIL_URL_TEMPLATE",
    "LIST_URL",
    "LOCATION_FILTER",
    "MIN_COMPLETENESS_RATIO",
    # parser
    "MetaCaptureError",
    "build_job_url",
    "parse_list_job",
]
