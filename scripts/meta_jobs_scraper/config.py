"""
Configuration constants for the Meta (metacareers.com) Jobs scraper.

Meta's careers site (https://www.metacareers.com/jobsearch) is a client-side
SPA that hydrates from a **single GraphQL POST returning the entire ~890-job
catalogue in one shot** — there is no pagination and no keyword search. We
scrape it with Playwright by sniffing the GraphQL response, so this package
has no ``api_client.py`` (there is no JSON endpoint to call directly).

The values here are ported from the sibling ``job-watcher`` repo's proven
``adapters/meta.py`` module constants.
"""

# --- URLs ---------------------------------------------------------------------
# The human-facing listings page. build_search_url returns this; the real
# capture in scraper.py navigates here and sniffs the GraphQL response.
LIST_URL = "https://www.metacareers.com/jobsearch"
# Per-job detail page (list-only first cut never fetches it, but the job_url is
# built from it so the frontend links out correctly).
JOB_DETAIL_URL_TEMPLATE = "https://www.metacareers.com/profile/job_details/{}"
# Every GraphQL request Meta issues hits a URL containing this substring; the
# response handler filters on it.
GRAPHQL_URL_SUBSTRING = "/graphql"

# --- Payload-shape anchors ----------------------------------------------------
# These are the leaf array/scalar names INSIDE the GraphQL response —
# deliberately NOT the operation name or the container/wrapper key, both of
# which Meta has already renamed once (silently zeroing the sibling adapter for
# 41 days). Selection walks the ``data`` subtree for ANY dict carrying one of
# these arrays, so it survives the inevitable ``..._v3`` wrapper rename. Anchor
# on the leaf, never on the wrapper.
ALL_JOBS_KEY = "all_jobs"
FEATURED_JOBS_KEY = "featured_jobs"
JOB_COUNT_KEY = "job_count"
# ``job_count`` is itself a hardcoded name, which is the very thing that broke
# the sibling adapter — so accept a versioned/prefixed variant too
# (``total_job_count``, ``open_job_count``, ...) and, when nothing matches, say
# so out loud instead of quietly disarming the completeness check.
JOB_COUNT_SUFFIX = "_job_count"

# --- Completeness guard -------------------------------------------------------
# A capture that parses fewer than this fraction of the advertised job_count is
# treated as truncated rather than as a shrinking board. Loose enough to absorb
# the small race between the count query and the results query (a posting added
# between the two), tight enough to catch a genuinely partial payload — Meta
# returns the entire catalogue in one response, so there is no legitimate reason
# for a large shortfall.
MIN_COMPLETENESS_RATIO = 0.9

# An unparseable GraphQL body this big is almost certainly the results payload:
# live, the results response is ~160KB and every other GraphQL response on the
# page is 0.2-20KB. Promotes an undecodable large body to a WARNING (it is the
# shape a switch to multipart/@defer streaming would take).
LARGE_BODY_BYTES = 50_000

# --- Timeouts / poll budgets --------------------------------------------------
PAGE_TIMEOUT_MS = 45_000          # page.goto timeout
RESPONSE_WAIT_S = 15.0            # settle-poll WAIT phase budget (job array must land)
NEW_PAGE_TIMEOUT_S = 30.0         # context.new_page() bound
BODY_READ_TIMEOUT_S = 30.0        # per-response body read bound (inside the handler)

# Settle-poll cadence. After a job array lands we keep polling for a short
# drain, because leaving the browser context cancels any response body still
# being read. See parser._SettlePoll for what this does and does not buy.
POLL_INTERVAL_S = 0.1
DRAIN_MAX_S = 3.0
DRAIN_STABLE_S = 0.5

# --- Client-side US + title filters (mirror TikTok) ---------------------------
# metacareers.com/jobsearch returns a broad set, so we narrow to US software /
# data roles client-side, identical to the TikTok scraper. The completeness
# guard runs against Meta's own ``job_count`` on the FULL parsed set BEFORE this
# filter, so a legitimately narrow kept count never false-trips it.
LOCATION_FILTER = "United States"

# Title keywords to include (case-insensitive substring match).
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
# ``MetaJobsScraper.filter_job``. Bare "HR" is deliberately absent: as a
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

# --- Output configuration -----------------------------------------------------
DEFAULT_OUTPUT_DIR = "scripts/output"
DEFAULT_OUTPUT_FILE = "meta_jobs.json"
