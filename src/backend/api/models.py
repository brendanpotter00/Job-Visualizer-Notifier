"""Pydantic response models with camelCase serialization for frontend compatibility."""

import json
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic.alias_generators import to_camel

# Closed set of signup provider tokens derived from
# ``_signup_provider_from_auth0_id`` in ``services.admin_service``. Keeping
# this as a module-level alias means a new provider added to that mapping
# is a TS *and* Python compile error at every consumer — no silent fallback
# to a raw string key in the admin dashboard.
SignupProvider = Literal["google", "email", "other"]

# Shared validation pattern for company name query parameters.
# Backend-scraped companies only (google, apple, microsoft) — no dots needed.
COMPANY_PATTERN = r"^[a-zA-Z0-9_-]+$"

# Pattern for frontend company IDs stored in user preferences. Allows interior
# dots so IDs like ``happyrobot.ai`` round-trip, but still rejects leading/
# trailing dots and ``..`` — no path-traversal shapes reach the DB layer.
ENABLED_COMPANY_ID_PATTERN = r"^[a-zA-Z0-9_-]+(\.[a-zA-Z0-9_-]+)*$"

CompanyId = Annotated[
    str,
    StringConstraints(pattern=ENABLED_COMPANY_ID_PATTERN, min_length=1, max_length=64),
]


class JobLocationResponse(BaseModel):
    """One normalized canonical location tag attached to a job.

    Mirrors a ``locations`` row reached through the ``job_locations`` join.
    The DB layer builds these as camelCase JSON via ``json_build_object`` (see
    ``services.database._LOCATIONS_SUBQUERY``), so the camelCase keys land on the
    aliases here; ``populate_by_name`` also accepts the snake_case field names.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    canonical_name: str
    kind: str
    city: str | None = None
    region: str | None = None
    country: str | None = None
    remote_scope: str | None = None
    is_primary: bool


class JobListingResponse(BaseModel):
    """Matches the frontend BackendJobListing TypeScript interface."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str
    title: str
    company: str
    # Raw scraped location string, kept for display fallback on jobs that have
    # not been normalized yet. Filtering uses ``locations`` (the canonical tags).
    location: str | None = None
    # Normalized canonical location tags (multi-location aware). Empty list for
    # jobs whose ``normalization_status`` is NULL/failed.
    locations: list[JobLocationResponse] = Field(default_factory=list)
    url: str
    source_id: str
    details: str  # JSON string, not parsed object
    created_at: datetime
    posted_on: datetime | None = None
    closed_on: datetime | None = None
    status: Literal["OPEN", "CLOSED"]
    has_matched: bool
    ai_metadata: str  # JSON string, not parsed object
    first_seen_at: datetime
    last_seen_at: datetime
    consecutive_misses: int = Field(ge=0)
    details_scraped: bool
    # External enrichment facets (job-enricher). All optional — NULL/absent for
    # jobs not yet enriched. The enrichment flag gates claiming in /pending, NOT
    # this response, so a row enriched while the flag was on keeps serializing
    # its facets even after the flag is turned back off.
    category: str | None = None            # job_categories.slug
    level: str | None = None               # job_levels.slug (see the new_grad⊂entry hierarchy)
    tags: list[str] = Field(default_factory=list)
    enrichment_status: str | None = None   # NULL | 'claimed' | 'done' | 'needs_human'


class ScrapeRunResponse(BaseModel):
    """Matches the frontend ScrapeRunResponse TypeScript interface."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    run_id: str
    company: str
    started_at: str
    completed_at: str | None = None
    mode: Literal["incremental", "full"]
    jobs_seen: int = Field(ge=0)
    new_jobs: int = Field(ge=0)
    closed_jobs: int = Field(ge=0)
    details_fetched: int = Field(ge=0)
    error_count: int = Field(ge=0)
    # Tri-state on purpose. ``True``/``False`` come from the writer; ``None``
    # means the row predates the column (nullable, no backfill) — NOT "the
    # guard didn't trip". The QA table renders the three states distinctly.
    skipped_update: bool | None = None


class CompanyCountResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    company: str
    count: int


class JobsStatsResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    total_jobs: int
    open_jobs: int
    closed_jobs: int
    company_counts: list[CompanyCountResponse]


class UserResponse(BaseModel):
    """User profile at the API boundary.

    The ``provider_subject`` field tracks the *most recent* identity provider's
    subject (Auth0 ``sub`` or Google-prefixed One Tap ``sub``). It maps to the
    DB column ``auth0_id`` for historical reasons — the column predates Google
    One Tap support — but the model name reflects that the value is no longer
    Auth0-specific. See ``docs/implementations/auth0/REVIEW_AUDIT.md``.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str
    provider_subject: str
    email: str
    display_name: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    picture_url: str | None = None
    created_at: str
    updated_at: str
    # Required (no default) — a future endpoint that forgets to compute the
    # admin flag will fail Pydantic validation rather than silently demoting
    # the user to non-admin in the response.
    is_admin: bool


class UserUpdateRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    display_name: str | None = Field(default=None, max_length=100)


class EnabledCompaniesResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    company_ids: list[str]
    # When true, companies added after the user's last save auto-enroll into
    # their feed on read. See user_preferences_service.list_enabled_companies.
    auto_enroll_new_companies: bool = True


class EnabledCompaniesUpdateRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    # Cap is well above the company catalogue size: auto-enroll materializes
    # full-catalogue lists for "Select All" / see-all users, so a save payload
    # can legitimately contain every company id. 200 was too tight once the
    # catalogue passed ~119 and keeps growing.
    company_ids: list[CompanyId] = Field(max_length=1000)
    auto_enroll_new_companies: bool = True


class FeatureResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str
    title: str
    description: str
    created_at: datetime
    # NULL while the feature is an open candidate; set to the ship date once
    # it's been delivered. Drives the "Shipped" section + badge on the frontend.
    completed_at: datetime | None = None
    upvote_count: int = Field(ge=0)
    has_upvoted: bool


class FeatureListResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    features: list[FeatureResponse]


class FeatureUpvoteStateResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    feature_id: str
    upvote_count: int = Field(ge=0)
    has_upvoted: bool


class CompanyProfileResponse(BaseModel):
    """One curated company in the public directory. ``blurb`` /
    ``accomplishment`` are nullable — a company without a profile still lists."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str
    display_name: str
    ats: str
    blurb: str | None = None
    accomplishment: str | None = None


class CompanyListResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    companies: list[CompanyProfileResponse]


class FeedbackSubmitRequest(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid"
    )

    # min_length=1 rejects an empty body at the 422 boundary; 5000 caps a single
    # note so an oversized message is rejected before it ever reaches the INSERT.
    # Whitespace-only bodies pass min_length but are stripped + re-rejected in the
    # router (Pydantic min_length does not strip).
    message: str = Field(min_length=1, max_length=5000)


class FeedbackResponse(BaseModel):
    """One feedback row. Used by the public submit ACK and the admin list.

    ``user_id``/``user_email``/``display_name`` are all null for anonymous
    submissions; when set they are a point-in-time snapshot of the submitter.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str
    message: str
    user_id: str | None = None
    user_email: str | None = None
    display_name: str | None = None
    created_at: datetime


class AdminFeedbackListResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    feedback: list[FeedbackResponse]
    # Total rows across the whole table (not just this page) so the admin UI can
    # paginate server-side and report an accurate count.
    total: int


class AdminUserRow(BaseModel):
    """One row in the admin Users page roster."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str
    email: str
    display_name: str | None = None
    signup_provider: SignupProvider
    created_at: str
    # Engagement fields for the "most frequent users" view. ``visit_count``
    # is incremented once per full page load via POST /api/users/visit;
    # ``last_visit_at`` is the most recent load (NULL until the user's first
    # visit after this feature shipped). Serialized as visitCount / lastVisitAt.
    visit_count: int = Field(ge=0)
    last_visit_at: datetime | None = None
    is_admin: bool


class AdminUsersListResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    users: list[AdminUserRow]


class AdminUserVisitsResponse(BaseModel):
    """One user's individual visit history for the roster's Visits modal."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    # Visit timestamps, most-recent first, capped server-side (LIMIT 500).
    visits: list[datetime]
    # The denormalized total visit_count for this user, so the modal can flag
    # the count-vs-history gap: per-visit history only began when the
    # user_visits table shipped, so for pre-launch visits ``totalVisitCount``
    # exceeds ``len(visits)``. Serialized as ``totalVisitCount``.
    total_visit_count: int = Field(ge=0)
    # True when the list was truncated by the server-side cap, so the modal can
    # say "showing the most recent 500".
    truncated: bool


class AdminUsersStatsResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    total_users: int = Field(ge=0)
    first_signup_at: str | None = None
    latest_signup_at: str | None = None
    # Aggregate may omit zero-count providers, so this dict is partial.
    # Typed as ``SignupProvider`` (not ``str``) so adding a new provider
    # to ``_signup_provider_from_auth0_id`` is a compile-time error here
    # rather than rendering raw keys to admins.
    by_provider: dict[SignupProvider, int]


# --- Location-normalization admin models (Unit 8) ----------------------------

# Allowed values for a manual-override location spec's `kind`. Mirrors
# `_VALID_KINDS` in services.llm_client.CanonicalLocation so a manual override
# can produce exactly the same `locations` rows the LLM path produces.
LocationKind = Literal["city", "region", "country", "remote"]


class LocationSpec(BaseModel):
    """One canonical location in a manual alias-override request body.

    Mirrors services.llm_client.CanonicalLocation's structured fields (minus
    `confidence`, which is forced to 1.0 for manual overrides). The upsert into
    `locations` keys on (kind, city, region, country, remote_scope) against the
    NULLS-NOT-DISTINCT `uq_locations_canonical` constraint, exactly like the LLM
    write path.
    """

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid"
    )

    canonical_name: str = Field(min_length=1, max_length=200)
    kind: LocationKind
    city: str | None = Field(default=None, max_length=120)
    region: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=120)
    remote_scope: str | None = Field(default=None, max_length=60)

    @model_validator(mode="after")
    def _kind_remote_scope_invariant(self) -> "LocationSpec":
        """Enforce the kind <-> remote_scope cross-field rule.

        Mirrors services.llm_client.CanonicalLocation: a remote role has no
        worksite city, but MAY carry a country/region scope (so a manual override
        can map 'US - AZ - Remote' -> Remote(AZ, US)). A contradictory override
        (kind='remote' carrying a city, or a non-remote kind carrying
        remote_scope) yields a 422 instead of silently writing a nonsensical row.
        """
        if self.kind == "remote":
            if self.city is not None:
                raise ValueError(
                    "kind='remote' must have city=None (a remote role has no "
                    "worksite city); region/country may carry the remote's scope. "
                    f"got city={self.city!r}"
                )
        elif self.remote_scope is not None:
            raise ValueError(
                f"remote_scope is only valid for kind='remote'; got kind={self.kind!r} "
                f"remote_scope={self.remote_scope!r}"
            )
        return self


class AdminAliasOverrideRequest(BaseModel):
    """Body for PUT /api/admin/locations/aliases/{raw_text}.

    `locations` is the ordered list of canonical locations this raw string maps
    to (position = list index). Manual overwrite semantics: this REPLACES any
    existing mapping for the normalized key and promotes the alias to
    source='manual' so it wins over a cached 'llm' guess (Decision #10).
    """

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid"
    )

    # Bounded: a single raw string never maps to more than a handful of
    # locations (the multi-location prod max is 2). Cap defends against an
    # accidental huge body fanning out unbounded INSERTs.
    locations: list[LocationSpec] = Field(min_length=1, max_length=20)


class AdminLocationResponse(BaseModel):
    """A canonical location row as returned by the admin endpoints."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: int
    canonical_name: str
    kind: str
    city: str | None = None
    region: str | None = None
    country: str | None = None
    remote_scope: str | None = None
    position: int  # order within the alias mapping (alias_locations.position)


class AdminAliasResponse(BaseModel):
    """Result of a manual override OR one inspect row.

    `locations` is ordered by position. `confidence` is nullable (manual
    overrides set 1.0; llm aliases carry the averaged model confidence).
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    raw_text: str
    source: str
    confidence: float | None = None
    locations: list[AdminLocationResponse]


class AdminAliasListResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    aliases: list[AdminAliasResponse]
    # Bounded count of all aliases matching the same filter — independent of the
    # page `limit`, so the UI can paginate. Added for the monitor page.
    total: int = Field(ge=0)


class AdminNormalizeJobResponse(BaseModel):
    """Result of POST /api/admin/jobs/{job_id}/normalize."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    job_id: str
    status: str  # "queued" | "reset_defer_failed" (reset committed; safety-net will pick it up)
    # False when ANTHROPIC_API_KEY is unset: the reset/defer still happened, but
    # a Tier-1 cache miss will dead-end until the key is configured (the job
    # stays NULL and auto-recovers once it is set). Surfaced so an explicit
    # admin action never silently no-ops.
    key_configured: bool


class AdminReNormalizeAllResponse(BaseModel):
    """Result of POST /api/admin/locations/re-normalize-all (break-glass)."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    reset_count: int
    scan_deferred: bool
    # False when ANTHROPIC_API_KEY is unset: the reset is committed, but the
    # deferred scan skips while the key is absent — draining is PAUSED until the
    # key is set (then it auto-resumes on the next periodic tick). Surfaced so
    # the break-glass action never claims progress it can't make.
    key_configured: bool
    # Explicit, surfaced to the operator in the JSON body: this does NOT force
    # fresh LLM re-normalization — it re-applies the pipeline against the
    # current alias cache (incl. manual overrides). To force fresh LLM calls an
    # operator must clear aliases manually (deliberately not one-click).
    note: str


# --- Location-normalization MONITOR models (admin read-only oversight) --------

# Invariant set of integrity-check severities. Literal (not str) so the values
# stay a closed set at the type boundary — a typo'd severity is a compile error.
CheckSeverity = Literal["ok", "warn", "crit"]


class AdminLocationHealthResponse(BaseModel):
    """Health snapshot for the monitor page (GET /api/admin/locations/health)."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    schema_present: bool
    window_hours: int
    null_backlog: int = Field(ge=0)
    null_aged: int = Field(ge=0)
    done: int = Field(ge=0)
    failed: int = Field(ge=0)
    total: int = Field(ge=0)
    failed_blank: int = Field(ge=0)
    failed_nonblank: int = Field(ge=0)
    # Percentage 0..100 = 100 * failed_nonblank / (done + failed_nonblank); 0.0
    # when the denominator is 0.
    failed_nonblank_ratio: float = Field(ge=0)
    # Minutes since the last worker_heartbeats row; None when the table is absent
    # or empty.
    heartbeat_age_minutes: float | None = None
    # Procrastinate 'normalize' queue counts by status; {} when the procrastinate
    # tables are absent (NOT ORM tables — guarded by to_regclass).
    normalize_queue: dict[str, int]
    # Succeeded normalize events in the window; None when procrastinate tables
    # are absent.
    throughput_in_window: int | None = None
    key_configured: bool
    dormant: bool


class AdminLocationIntegrityCheck(BaseModel):
    """One C1..C9 integrity probe result."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str
    label: str
    count: int = Field(ge=0)
    severity: CheckSeverity


class AdminLocationIntegrityResponse(BaseModel):
    """GET /api/admin/locations/integrity."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    schema_present: bool
    checks: list[AdminLocationIntegrityCheck]


class AdminReverseLocation(BaseModel):
    """The canonical location half of a reverse-lookup row.

    A subset of AdminLocationResponse (no `position` — reverse lookup is not
    scoped to a single alias mapping).
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: int
    canonical_name: str
    kind: str
    city: str | None = None
    region: str | None = None
    country: str | None = None
    remote_scope: str | None = None


class AdminLocationReverseRow(BaseModel):
    """One canonical location + every raw_text that maps to it."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    location: AdminReverseLocation
    raw_texts: list[str]


class AdminLocationReverseListResponse(BaseModel):
    """GET /api/admin/locations/reverse."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    results: list[AdminLocationReverseRow]


class AdminAliasOriginal(BaseModel):
    """One verbatim job-location string + the job ids carrying it."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    original: str
    job_ids: list[str]


class AdminAliasOriginalsResponse(BaseModel):
    """GET /api/admin/locations/alias-originals."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    raw_text: str
    # Count of distinct originals RETURNED (== len(originals)), bounded by the
    # page `limit` and the service-side prefilter cap. NOT a filter-independent
    # grand total like the other *total fields — this is a display feature with
    # no full count to report. See services.location_admin.alias_originals.
    total: int = Field(ge=0)
    originals: list[AdminAliasOriginal]


class AdminProblemJob(BaseModel):
    """One actionable failed job (failed status with a non-blank location)."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str
    title: str | None = None
    company: str | None = None
    location: str | None = None
    normalization_status: str | None = None
    last_seen_at: str | None = None


class AdminProblemJobsResponse(BaseModel):
    """GET /api/admin/locations/problem-jobs."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    jobs: list[AdminProblemJob]
    total: int = Field(ge=0)


# --- User Saved Filters -------------------------------------------------------

# The 13 allowed time-window tokens shared by the Recent and Trend pages.
# Stored as TEXT in ``user_saved_filters`` but validated to this Literal at the
# boundary, so any value outside the set yields a 422 (same mechanism as
# ``ScrapeRunResponse.mode``).
TimeWindow = Literal[
    "30m", "1h", "3h", "6h", "12h", "24h",
    "3d", "7d", "14d", "30d", "90d", "180d", "all",
]
KeywordMode = Literal["include", "exclude"]

# Caps that defend the DB layer. The per-user list-count cap lives only in
# saved_filters_service.MAX_KEYWORD_LISTS_PER_USER, where the existing row count
# is visible — Pydantic can't enforce it at the request boundary.
_MAX_LOCATIONS = 100
# Tied to ``routers.jobs_search._MAX_KEYWORDS``, which is the per-query budget for
# include+exclude terms COMBINED. A saved list auto-hydrates into the Recent page's
# filter chips on page load and those chips become the query's keyword parameters,
# so a list the user may STORE but not QUERY is a hard 400 on Recent Jobs the next
# time they open it. Lowered from 100 to match; the widest list in prod is 11 tags
# (2026-08-19), so no stored list is affected, and ``KeywordListResponse`` carries
# no length bound, so any legacy oversized row still reads back fine.
_MAX_TAGS_PER_LIST = 20
_MAX_TAG_TEXT_LEN = 100
_MAX_LIST_NAME_LEN = 100
_MAX_LOCATION_LEN = 200  # matches LocationSpec.canonical_name
# Enrichment facet slugs (category/level). The slug is a short snake_case token
# (e.g. "software_engineering", "senior"); 64 chars is generous headroom, and 50
# values comfortably exceeds the seeded catalog while bounding the payload.
_MAX_FACET_VALUES = 50
_MAX_FACET_SLUG_LEN = 64


def _dedup_strings(values: list[str]) -> list[str]:
    """Collapse exact-duplicate strings, preserving first-seen order."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _dedup_locations(locations: list[str]) -> list[str]:
    """Collapse exact-duplicate location strings, preserving first-seen order."""
    return _dedup_strings(locations)


class SearchTag(BaseModel):
    """One keyword tag: free text plus an include/exclude mode."""

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid"
    )

    text: str = Field(min_length=1, max_length=_MAX_TAG_TEXT_LEN)
    mode: KeywordMode


def _dedup_tags(tags: list[SearchTag]) -> list[SearchTag]:
    """Collapse exact (text, mode) duplicates, preserving order.

    The dedup key includes ``mode`` so the same text may legitimately appear
    once as include and once as exclude — only an exact (text, mode) repeat is
    dropped. Frontend resolves any include/exclude precedence.
    """
    seen: set[tuple[str, str]] = set()
    result: list[SearchTag] = []
    for tag in tags:
        key = (tag.text, tag.mode)
        if key not in seen:
            seen.add(key)
            result.append(tag)
    return result


class SavedFiltersResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    recent_time_window: TimeWindow
    trend_time_window: TimeWindow
    locations: list[str]
    category: list[str]
    level: list[str]
    recent_active_keyword_list_id: str | None = None
    trend_active_keyword_list_id: str | None = None


class SavedFiltersUpdateRequest(BaseModel):
    """Full-replace body for PUT /api/users/saved-filters.

    Locations, category, and level are deduped (order-preserving) at the
    boundary. ``category`` / ``level`` hold enrichment facet slugs shared by both
    the Recent and Trend pages (an empty list means "no filter"). The active-list
    pointers are bounded at 64 chars to match the uuid4-hex id shape and the
    ``'builtin-swe'`` sentinel; service-layer ownership validation decides
    whether a non-null pointer is accepted (409 otherwise).
    """

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid"
    )

    recent_time_window: TimeWindow
    trend_time_window: TimeWindow
    locations: list[
        Annotated[
            str, StringConstraints(min_length=1, max_length=_MAX_LOCATION_LEN)
        ]
    ] = Field(default_factory=list, max_length=_MAX_LOCATIONS)
    category: list[
        Annotated[
            str, StringConstraints(min_length=1, max_length=_MAX_FACET_SLUG_LEN)
        ]
    ] = Field(default_factory=list, max_length=_MAX_FACET_VALUES)
    level: list[
        Annotated[
            str, StringConstraints(min_length=1, max_length=_MAX_FACET_SLUG_LEN)
        ]
    ] = Field(default_factory=list, max_length=_MAX_FACET_VALUES)
    recent_active_keyword_list_id: str | None = Field(default=None, max_length=64)
    trend_active_keyword_list_id: str | None = Field(default=None, max_length=64)

    @field_validator("locations")
    @classmethod
    def _dedup_locations_field(cls, value: list[str]) -> list[str]:
        return _dedup_locations(value)

    @field_validator("category", "level")
    @classmethod
    def _dedup_facet_field(cls, value: list[str]) -> list[str]:
        return _dedup_strings(value)


class KeywordListResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str
    name: str
    tags: list[SearchTag]
    is_builtin: bool = False
    position: int = 0


class KeywordListsResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    lists: list[KeywordListResponse]


class KeywordListCreateRequest(BaseModel):
    """Body for POST /api/users/saved-filters/keyword-lists.

    Tags are deduped (order-preserving) on (text, mode) at the boundary.
    """

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid"
    )

    name: str = Field(min_length=1, max_length=_MAX_LIST_NAME_LEN)
    tags: list[SearchTag] = Field(
        default_factory=list, max_length=_MAX_TAGS_PER_LIST
    )

    @field_validator("tags")
    @classmethod
    def _dedup_tags_field(cls, value: list[SearchTag]) -> list[SearchTag]:
        return _dedup_tags(value)


class KeywordListUpdateRequest(BaseModel):
    """Body for PATCH /api/users/saved-filters/keyword-lists/{id}.

    All fields optional (partial update): ``name`` renames, ``tags`` replaces
    the whole array, ``position`` reorders. An empty body is a no-op. Tags are
    deduped (order-preserving) on (text, mode) when present.
    """

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid"
    )

    name: str | None = Field(
        default=None, min_length=1, max_length=_MAX_LIST_NAME_LEN
    )
    tags: list[SearchTag] | None = Field(
        default=None, max_length=_MAX_TAGS_PER_LIST
    )
    position: int | None = Field(default=None, ge=0)

    @field_validator("tags")
    @classmethod
    def _dedup_tags_field(
        cls, value: list[SearchTag] | None
    ) -> list[SearchTag] | None:
        return _dedup_tags(value) if value is not None else None


class LocationSearchResult(BaseModel):
    """One canonical location returned by the public location-search autocomplete.

    Leaner than ``AdminLocationResponse`` (no ``position``), but carries the
    structured ``city``/``region``/``country``/``remote_scope`` columns in
    addition to the display ``canonical_name``. The frontend caches these as a
    descriptor so its hierarchical location filter can resolve ANY selected
    canonical location (non-US countries, irregular regions) — not just the US
    states / cities it can re-derive from the string alone.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: int
    canonical_name: str
    kind: str
    city: str | None = None
    region: str | None = None
    country: str | None = None
    remote_scope: str | None = None


# --- External enrichment (POST /results) request models ----------------------
#
# The job-enricher laptop POSTs enrichment results to
# /api/internal/enrichment/results. These models validate that external,
# untrusted body at the trust boundary. All accept snake_case field names (the
# enricher's wire format) via ``populate_by_name`` alongside the camelCase alias.
#
# CRITICAL isolation rule: only the ENVELOPE is validated at the FastAPI
# boundary (``EnrichmentResultsBody`` — a ``BaseModel`` whose ``results`` field is
# a ``list[Any]``), and each ITEM is validated INSIDE the per-row SAVEPOINT in the
# router. That keeps a single bad item confined to ``failed[]`` instead of 422-ing
# the whole batch, while a mis-keyed or non-object envelope still 422s up front.


class JudgeVerdict(BaseModel):
    """The laptop judge's verdict for one result item. All fields optional so an
    absent/partial ``judge`` object never fails item validation — the writer
    reads ``needs_human`` to decide the publish gate."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    needs_human: bool = False
    judged: bool = False
    passed: bool | None = None
    confidence: float | None = None
    notes: str | None = None


class EnrichmentLocationItem(BaseModel):
    """DOCUMENTATION ONLY — the Contract-of-Record shape of one ``locations[]``
    element. It is deliberately NOT used to validate ``EnrichmentResultItem``:
    that field is typed ``list[Any]`` so BOTH a value-type-malformed location
    (e.g. ``confidence: "high"``) AND a NON-DICT element (``["Berlin"]``,
    ``[None]``, ``[123]``) are carried through unchanged and degraded by
    ``CanonicalLocation(**loc)`` inside the writer's ``enr_loc`` savepoint
    ("labels persisted, location skipped + warned"), rather than routing the
    whole item to ``failed[]``. ``CanonicalLocation`` is the sole strict arbiter;
    enforcing primitive types — or even ``dict``-ness (``list[dict[str, Any]]``,
    which raises Pydantic ``dict_type`` on a non-dict) — here would instead fail
    the whole item on a bad location (reversing F2's "location degrades
    independently" intent). Kept as a typed reference of the fields the enricher
    sends.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    canonical_name: str | None = None
    kind: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None
    remote_scope: str | None = None
    confidence: float | None = None


class EnrichmentResultItem(BaseModel):
    """One enrichment result for a single job.

    ``job_listing_id`` AND ``source_id`` are REQUIRED and NON-EMPTY
    (``min_length=1``): the writer keys the ``job_listings`` UPDATE on the
    composite PK ``(source_id, id)`` (``id`` is not globally unique), so a missing
    ``source_id`` must fail this item rather than risk flipping the wrong source's
    row. An empty ``job_listing_id`` would update ZERO ``job_listings`` yet insert
    orphan side-table rows and still count as ``written`` — so an empty id must
    fail validation → per-row ``failed[]`` inside the SAVEPOINT.

    ``category`` / ``level`` stay ``str | None`` (NOT a strict ``Literal``): the
    writer's ``_valid()`` soft-nulls an out-of-taxonomy slug so a laptop-side
    taxonomy drift degrades to "unlabelled", never a 422/dropped batch (CR-3).

    ``locations`` is typed ``list[Any]`` (NOT ``list[dict[str, Any]]`` and NOT
    ``EnrichmentLocationItem``) so BOTH a value-malformed location AND a NON-DICT
    location element (``["Berlin"]``, ``[None]``, ``[123]``) are carried through
    item validation and degraded by ``CanonicalLocation(**loc)`` in the writer's
    ``enr_loc`` savepoint — a non-dict splat raises ``TypeError`` there, so the
    location is skipped + warned while the row stays ``written``/``done``
    (F2/F10/F12). ``CanonicalLocation`` is the sole strict arbiter; a stricter
    type here (even ``dict``) would instead route the WHOLE item to ``failed[]``
    at ``model_validate`` (Pydantic ``dict_type``), discarding the good
    ``category``/``level``/``tags`` and re-opening the F2 reclaim churn.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    job_listing_id: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
    source_id: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
    category: str | None = None
    level: str | None = None
    tags: list[str] = Field(default_factory=list)
    clean_description: str | None = None
    classify_confidence: float | None = None
    classify_reasoning: str | None = None
    taxonomy_version: str | None = None
    raw_location: str | None = None
    locations: list[Any] = Field(default_factory=list)
    judge: JudgeVerdict | None = None


class EnrichmentResultsBody(BaseModel):
    """Envelope for POST /results: ``{"results": [...]}``.

    ``results`` is REQUIRED (no default): a mis-keyed body (``{}``,
    ``{"items": [...]}``) must 422 up front rather than silently return
    ``200 {"written": 0}`` — with the enricher ignoring ``failed[]`` (CR-1) an
    envelope-key drift would otherwise look like success. An explicit
    ``{"results": []}`` is still accepted (a no-op poll).

    The element type stays ``list[Any]`` — the top-level shape is validated here,
    but each element is validated into an ``EnrichmentResultItem`` INSIDE the
    per-row SAVEPOINT (router) so a null / non-dict / schema-invalid element lands
    in ``failed[]`` and never 422s or 500s the whole batch.
    """

    results: list[Any]


class EnrichmentTickCounters(BaseModel):
    """Per-tick pipeline counters pushed by the enricher. All default 0 so a
    partial counters object degrades to zeros instead of failing the push —
    metrics are best-effort observability, never a write path worth 422-ing."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    claimed: int = Field(default=0, ge=0)
    cleaned: int = Field(default=0, ge=0)
    classified: int = Field(default=0, ge=0)
    judged: int = Field(default=0, ge=0)
    corrected: int = Field(default=0, ge=0)
    needs_human: int = Field(default=0, ge=0)
    sent: int = Field(default=0, ge=0)
    errors: int = Field(default=0, ge=0)
    nulled_facets: int = Field(default=0, ge=0)


class EnrichmentMetricsBody(BaseModel):
    """Body for POST /api/internal/enrichment/metrics — one enricher tick
    snapshot (see docs/enrichment/HANDOFF.md §3 and the enricher's
    ``cli metrics-push``). Idempotent on ``tick_uuid`` (re-push upserts).

    Size caps (``knobs`` ≤ 2 KB, ``stage_timings`` ≤ 20 rows, ``scorecard``
    ≤ 16 KB when JSON-encoded) bound what an internal-key holder can persist
    per row; the payloads land in JSONB and are echoed to the admin UI.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    tick_uuid: Annotated[str, StringConstraints(min_length=1, max_length=64, strip_whitespace=True)]
    started_at: datetime
    ended_at: datetime | None = None
    status: Literal["ok", "error", "running"]
    notes: str | None = Field(default=None, max_length=2000)
    counters: EnrichmentTickCounters = Field(default_factory=EnrichmentTickCounters)
    duration_s: float | None = Field(default=None, ge=0)
    taxonomy_version: str | None = Field(default=None, max_length=100)
    knobs: dict[str, Any] | None = None
    stage_timings: list[dict[str, Any]] | None = Field(default=None, max_length=20)
    heartbeat_age_s: float | None = Field(default=None, ge=0)
    scorecard: dict[str, Any] | None = None
    enricher_version: str | None = Field(default=None, max_length=100)
    drift_suspected: bool = False

    @field_validator("knobs")
    @classmethod
    def _cap_knobs(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is not None and len(json.dumps(value)) > 2048:
            raise ValueError("knobs payload exceeds 2KB")
        return value

    @field_validator("scorecard")
    @classmethod
    def _cap_scorecard(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is not None and len(json.dumps(value)) > 16384:
            raise ValueError("scorecard payload exceeds 16KB")
        return value


class FacetOption(BaseModel):
    """One dropdown option from the seeded dimension tables (GET /api/jobs/facets)."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    slug: str
    label: str
    sort_order: int
    # job_levels only: parent in the level hierarchy (new_grad -> entry). The
    # frontend derives its client-side filter expansion from this, so the
    # entry⊇new_grad contract stays data-driven end to end.
    parent_slug: str | None = None


class JobFacetsResponse(BaseModel):
    """GET /api/jobs/facets — data-driven dropdown catalog for the enrichment
    facets. Sourced from job_categories / job_levels so taxonomy changes ship as
    a migration, never a frontend redeploy."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    categories: list[FacetOption]
    levels: list[FacetOption]


class JobSearchMeta(BaseModel):
    """Header metrics for GET /api/jobs/search, returned with page 1 only.

    ``filtered_total`` counts the ACTIVE filter set. The two recency tiles are
    scoped to ``company`` and to nothing else — not category, level, keywords,
    locations, ``since`` or ``status`` — which is what the Recent page's "Past 24
    Hours" / "Past 3 Hours" cards have always shown: client-side they were derived
    from the enabled-companies prefilter before any other filter ran.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    filtered_total: int
    # Explicit aliases: ``to_camel`` splits on the digit and emits
    # ``countLast24H`` / ``countLast3H`` — a stray capital that reads like a typo
    # in the JSON and would have to be mirrored verbatim in the TypeScript type.
    # A field-level alias takes priority over the generator.
    count_last_24h: int = Field(serialization_alias="countLast24h")
    count_last_3h: int = Field(serialization_alias="countLast3h")


class JobSearchResponse(BaseModel):
    """GET /api/jobs/search — an ENVELOPE, unlike GET /api/jobs' bare array.

    ``/api/jobs`` carries its page token in the ``X-Next-Cursor`` header because it
    could not change a body shape every existing consumer depended on. That header
    needs three separate hops wired correctly (the Vercel proxy's explicit
    re-emit, FastAPI ``expose_headers``, and ``vercel.json``'s
    ``Access-Control-Expose-Headers``), and missing any one of them fails
    silently — the client simply never sees another page.

    This endpoint is new, so it has no such constraint and puts the cursor in the
    body, where it cannot be dropped in transit.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    jobs: list[JobListingResponse]
    # Absent/null means END OF WALK — it is the only termination signal, exactly
    # as with the header on /api/jobs. Present iff the page came back full.
    next_cursor: str | None = None
    # None on cursor pages: the counts describe the whole filter set, so
    # recomputing them per page would be pure waste.
    meta: JobSearchMeta | None = None


# --- Enrichment MONITOR models (admin oversight of the pull pipeline) ---------


class AdminEnrichmentHealthResponse(BaseModel):
    """Health snapshot for the admin enrichment page
    (GET /api/admin/enrichment/health)."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    schema_present: bool
    enabled: bool
    # OPEN jobs by COALESCE(enrichment_status,'unenriched'). Keys:
    # unenriched | claimed | done | needs_human (absent => 0).
    open_by_status: dict[str, int]
    # Of the unenriched OPEN rows, how many the /pending claim query could
    # actually hand out (description present, allowlist respected). The gap
    # (unenriched - eligible) is permanently invisible to the enricher — the
    # dark-vs-idle distinction the bare 'unenriched' count can't make.
    eligible_unenriched: int = Field(ge=0)
    stale_claims: int = Field(ge=0)
    claim_ttl_minutes: int = Field(ge=0)
    # Open, un-corrected needs-human queue depth (the actionable number, unlike
    # the internal /health's raw job_enrichment.needs_human count which includes
    # CLOSED jobs and already-corrected rows).
    needs_human_open: int = Field(ge=0)
    human_corrected_total: int = Field(ge=0)
    last_enriched_at: datetime | None = None
    last_enriched_age_s: float | None = None
    # Latest pushed tick (enrichment_ticks); all None when nothing pushed yet.
    last_tick_uuid: str | None = None
    last_tick_status: str | None = None
    last_tick_started_at: datetime | None = None
    last_tick_age_s: float | None = None
    last_tick_drift_suspected: bool = False
    # Aggregates over the trailing window (default 24h): enriched throughput
    # from job_enrichment, tick error count from enrichment_ticks.
    window_hours: int = Field(ge=1)
    enriched_in_window: int = Field(ge=0)
    error_ticks_in_window: int = Field(ge=0)


class AdminEnrichmentNeedsHumanRow(BaseModel):
    """One needs-human queue row (job_enrichment ⋈ job_listings)."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    source_id: str
    job_listing_id: str
    title: str | None = None
    company: str | None = None
    url: str | None = None
    job_status: str | None = None            # job_listings.status (OPEN/CLOSED)
    enrichment_status: str | None = None
    category: str | None = None              # published facet (job_listings)
    level: str | None = None
    tags: list[str] = Field(default_factory=list)
    clean_description: str | None = None
    classify_confidence: float | None = None
    classify_reasoning: str | None = None
    taxonomy_version: str | None = None
    judged: bool = False
    judge_passed: bool | None = None
    judge_confidence: float | None = None
    judge_notes: str | None = None
    enriched_at: datetime | None = None
    human_corrected_at: datetime | None = None
    human_corrected_by: str | None = None
    human_decision: str | None = None        # NULL | 'corrected' | 'confirmed_correct'


class AdminEnrichmentNeedsHumanResponse(BaseModel):
    """GET /api/admin/enrichment/needs-human — paginated queue."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    rows: list[AdminEnrichmentNeedsHumanRow]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class AdminEnrichmentTickRow(BaseModel):
    """One pushed tick (GET /api/admin/enrichment/ticks)."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    tick_uuid: str
    started_at: datetime
    ended_at: datetime | None = None
    status: str
    notes: str | None = None
    claimed: int = 0
    cleaned: int = 0
    classified: int = 0
    judged: int = 0
    corrected: int = 0
    needs_human: int = 0
    sent: int = 0
    errors: int = 0
    nulled_facets: int = 0
    duration_s: float | None = None
    taxonomy_version: str | None = None
    stage_timings: list[dict[str, Any]] | None = None
    heartbeat_age_s: float | None = None
    drift_suspected: bool = False
    received_at: datetime | None = None


class AdminEnrichmentTicksResponse(BaseModel):
    """GET /api/admin/enrichment/ticks — trailing-window tick series plus the
    latest pushed scorecard/knobs (returned once, not per row, to keep the
    series light)."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    ticks: list[AdminEnrichmentTickRow]
    window_hours: int = Field(ge=1)
    latest_scorecard: dict[str, Any] | None = None
    latest_scorecard_tick_uuid: str | None = None
    latest_knobs: dict[str, Any] | None = None


class AdminEnrichmentRecentRow(BaseModel):
    """One recently-enriched job (GET /api/admin/enrichment/recent)."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    source_id: str
    job_listing_id: str
    title: str | None = None
    company: str | None = None
    url: str | None = None
    enrichment_status: str | None = None
    category: str | None = None
    level: str | None = None
    tags: list[str] = Field(default_factory=list)
    classify_confidence: float | None = None
    classify_reasoning: str | None = None
    judged: bool = False
    judge_passed: bool | None = None
    judge_confidence: float | None = None
    judge_notes: str | None = None
    taxonomy_version: str | None = None
    needs_human: bool = False
    human_corrected_at: datetime | None = None
    human_decision: str | None = None        # NULL | 'corrected' | 'confirmed_correct'
    enriched_at: datetime | None = None


class AdminEnrichmentRecentResponse(BaseModel):
    """GET /api/admin/enrichment/recent — latest enrichment writes."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    rows: list[AdminEnrichmentRecentRow]


class AdminEnrichmentCorrectionRequest(BaseModel):
    """Body for POST /api/admin/enrichment/jobs/{source_id}/{job_id}/correct.

    ``category``/``level`` accept a slug or null (null = explicitly unlabelled);
    ``tags`` replaces the tag set (empty list clears). Slugs are validated
    against the live dimension tables in the service — a stale admin UI gets a
    409, never a silent null (the agent gets soft-nulling because a drifted
    laptop must degrade, not fail; a human in the admin UI deserves the error).
    """

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid"
    )

    category: str | None = None
    level: str | None = None
    tags: list[str] = Field(default_factory=list, max_length=16)
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for tag in value:
            t = tag.strip().lower()
            if not t:
                continue
            if len(t) > 60:
                raise ValueError("tag exceeds 60 characters")
            if t not in seen:
                seen.add(t)
                cleaned.append(t)
        return cleaned


class AdminEnrichmentCorrectionResponse(BaseModel):
    """Result of a correct / confirm / re-enrich action."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    source_id: str
    job_listing_id: str
    enrichment_status: str | None = None
    category: str | None = None
    level: str | None = None
    tags: list[str] = Field(default_factory=list)
    human_corrected_at: datetime | None = None
    human_corrected_by: str | None = None
    human_decision: str | None = None        # NULL | 'corrected' | 'confirmed_correct'


class ResolveUrlRequest(BaseModel):
    """Body for POST /api/companies/resolve.

    ``extra="forbid"`` so a client that misspells the field gets a 422 instead
    of silently resolving nothing. 2048 is the practical URL ceiling; anything
    longer is rejected before it reaches the SSRF guard.
    """

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid"
    )

    url: str = Field(min_length=1, max_length=2048)


class AtsCandidateResponse(BaseModel):
    """An ATS board we recognized, in the shape the backend clients consume."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    ats: str
    board_token: str
    provider_config: dict[str, str] = Field(default_factory=dict)
    source_url: str


class ProbeResultResponse(BaseModel):
    """What the real ATS client returned when we called the candidate board.

    ``error`` carries the underlying message rather than a bare flag — "board
    not found" and "timed out" need different answers from the user.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    ok: bool
    job_count: int = Field(ge=0)
    error: str | None = None


class ResolveUrlResponse(BaseModel):
    """200 body for POST /api/companies/resolve. Persists nothing."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    candidate: AtsCandidateResponse
    probe: ProbeResultResponse
    via: str                       # 'direct' | 'redirect' | 'embedded'
    hops: list[str] = Field(default_factory=list)
    final_url: str


class AddUserCompanyRequest(BaseModel):
    """Body for POST /api/users/companies — the careers URL to add.

    Same shape + caps as ``ResolveUrlRequest`` (``extra='forbid'`` so a
    misspelled field is a 422, 2048-char URL ceiling before the SSRF guard).
    """

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid"
    )

    url: str = Field(min_length=1, max_length=2048)
    # The one-line override for the P2 dedupe. Default False, so the FIRST add of a
    # board we already publish always stops and links to the public page; a caller
    # who wants a private copy anyway re-sends the same URL with this set. It is
    # deliberately not sticky and not stored — the check is cheap enough to re-run,
    # and a persisted "ignore" would be a piece of state nothing ever clears.
    track_anyway: bool = False


class RenameUserCompanyRequest(BaseModel):
    """Body for PATCH /api/users/companies/{id} — the owner's name for their board.

    The REAL limits (trim, control-character stripping, the 100-character cap) live in
    ``routers/user_companies._clean_display_name`` and are enforced there, NOT here.
    That is deliberate: a Pydantic ``Field`` violation returns Pydantic's own 422 shape
    (``detail`` as a list of error objects, no ``reason``), and the frontend's
    ``asAddFailure`` requires a 422 carrying a string ``reason`` before it will render
    specific copy — so a name rejected by a ``Field`` constraint would surface as
    generic "something went wrong" text instead of "that name is too long".

    ``max_length`` here is only a payload ceiling, an order of magnitude above the real
    cap, so a megabyte of text is refused before it is ever normalized. A client that
    trips it is broken or hostile, and the generic 422 is the right answer for both.
    """

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid"
    )

    display_name: str = Field(min_length=1, max_length=1000)


class AlreadyPublicResponse(BaseModel):
    """200 body when a pasted URL is a board we already publish (the P2 dedupe).

    Nothing was created — no ``companies`` row, no ``user_companies`` row, no
    scraper, no capture — so there is no ``UserCompany`` to return and this is not
    a failure either. ``status`` is the discriminant the frontend narrows on, the
    same way it narrows the 202 ``discovery_pending`` body.

    ``company_id`` / ``display_name`` are the PUBLIC company's, and both are
    already served unauthenticated by ``GET /api/companies``. ``final_url`` is the
    URL the resolver settled on, echoed back so a caller that decides to track a
    private copy anyway can re-send exactly what we resolved.

    ``match_kind`` is HOW SURE WE ARE, and it exists because the same body is now
    produced by evidence of two very different strengths:

    * ``'board'`` — we matched a BOARD. Either the ``(ats, board_token)`` pair the
      resolver named, or a careers host in our own declared table. There is no
      plausible reading where the user meant a different company, so the frontend
      renders this terminally: "We already track X", and no escape hatch.
    * ``'name'`` — we matched a STRING IN A DOMAIN against the names of companies we
      publish (``lifeatspotify.com`` → Spotify). No board was resolved and no job set
      was compared. It is a good guess and it is still a guess, so the frontend must
      hedge the wording AND keep a way out; a wrong guess with no way out would
      hard-block somebody from adding a legitimately different company.

    Defaulted to ``'board'`` so the two exact rungs need say nothing, and so a client
    built before this field existed keeps reading the stricter, older meaning.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    status: Literal["already_public"] = "already_public"
    detail: str
    company_id: str
    display_name: str
    final_url: str
    match_kind: Literal["board", "name"] = "board"


class DiscoveryStepResponse(BaseModel):
    """One rung of the 4-step discovery checklist (E7 capture pivot).

    ``key`` is one of ``open_page | find_feed | verify_read | ready`` and ``status`` one
    of ``pending | active | done | failed``; both are bare ``str`` on the wire because
    the server owns the vocabulary, and the frontend maps them through a closed union so
    an unknown value is caught there rather than blanking a row.

    ``result`` is the SPECIFIC thing this step found ("found 3 candidate feeds", "read
    90 jobs") or — on the failed step — why it stopped. A generic tick is a spinner with
    extra steps, which is what this replaced.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    key: str
    status: str
    result: str | None = None


class DiscoveryJobPreviewResponse(BaseModel):
    """One job from the acceptance replay, shown so a user can recognise their board.

    The rows the REPLAY returned, not the capture's — the same bytes the nightly
    harvest will read. ``url`` is present only when it is an http(s) link (the blob is
    rendered, and a scraped ``javascript:`` href would be a stored-XSS vector).
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    title: str
    location: str | None = None
    url: str | None = None


class DiscoveryRequestResponse(BaseModel):
    """One response the capture browser recorded — a row of the network log.

    THE EVIDENCE BEHIND THE VERDICT. Discovery's commonest refusal is "none of the 14
    JSON requests this page made returned a list of job postings", which is a conclusion
    with nothing attached; these rows are the fourteen requests, so a user can see for
    themselves whether we opened the wrong page.

    WHAT IS DELIBERATELY ABSENT is the point: no request headers, no cookies, no POST
    body, and no query VALUES. ``url`` has already been through
    ``discovery.progress.display_url`` — userinfo and port stripped, every query value
    replaced by an ellipsis — because a board that signs its URLs puts the signature in
    the query and this blob is rendered in a browser.

    ``records`` is ``null`` until the pre-filter has looked at the response, then the
    number of job-shaped records found in it (``0`` for the analytics and config traffic
    every careers page fires). ``state`` is ``recorded | oversize | blocked | chosen``.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    method: str
    url: str
    status: int
    bytes: int
    records: int | None = None
    state: str = "recorded"
    note: str | None = None


class DiscoveryPayloadSampleResponse(BaseModel):
    """One record from the request we picked, pretty-printed — "show me the JSON".

    ``text`` is a SAMPLE and not the body: a captured body can be 4 MB, and the question
    it answers ("is this actually my board?") is settled by one record. Credential-shaped
    keys are redacted and long strings clipped before it is stored.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    path: str = ""
    records: int = 0
    text: str


class DiscoveryNetworkResponse(BaseModel):
    """What the capture browser saw, and which of it we chose.

    ``recorded`` is how many responses the capture recorded, which can exceed
    ``len(requests)`` when the stored blob was clipped to its size budget — the heading
    stays truthful about what we saw even when the list under it is shorter.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    requests: list[DiscoveryRequestResponse] = Field(default_factory=list)
    recorded: int = 0
    sample: DiscoveryPayloadSampleResponse | None = None


class DiscoveryProgressResponse(BaseModel):
    """The discovery checklist attached to a user company, if it has one.

    Stored in ``companies.provider_config['discovery']`` (no migration — see
    ``api.services.discovery.progress``) and read back by the SAME poll the list already
    runs, so no second polling channel exists (DECISION D2).

    ``liveViewUrl`` is the hosted, iframe-embeddable view of the capture session. It
    exists ONLY for a Browserbase run and our default is our own Chromium, so it is
    absent on nearly every discovery and the UI must never block on it (DECISION D4).
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    steps: list[DiscoveryStepResponse] = Field(default_factory=list)
    # 'running' | 'tracking' | 'refused'
    outcome: str = "running"
    live_view_url: str | None = None
    updated_at: str | None = None
    job_preview: list[DiscoveryJobPreviewResponse] = Field(default_factory=list)
    # The network log behind the checklist. Always present (``read_progress`` fills an
    # empty one), so the frontend never has to distinguish "no evidence" from "a blob
    # written before this existed" — both are an empty list, and both render nothing.
    network: DiscoveryNetworkResponse = Field(default_factory=DiscoveryNetworkResponse)


class PublicMatchResponse(BaseModel):
    """"This looks like Spotify, which we already track" — a SUGGESTION (E7 unit 10).

    Stored in ``companies.provider_config['public_match']`` (no migration — same sidecar
    the discovery checklist uses) and read back by the SAME poll the list already runs.

    It means the board's OPEN job titles overlap a published company's by at least 70%,
    on sets of at least 20 titles each. It does NOT mean anything was merged, moved or
    changed: nothing on this path writes a ``job_listings`` row or touches a company's
    identity. The user decides — the banner offers the public page and a dismiss, and
    dismissing is a normal outcome, not a failure.

    ``companyId`` is a PUBLIC company id (``spotify``), never a ``u-…`` runtime id.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    company_id: str
    display_name: str
    #: How many normalized titles the two boards share, out of ``candidateTitles`` on
    #: this board. The banner renders them as "70 of 81 roles match", so both are
    #: required — a count with no denominator is not a sentence.
    shared: int = Field(ge=0)
    candidate_titles: int = Field(ge=0)
    detected_at: str | None = None


class UserCompanyResponse(BaseModel):
    """One private custom company the caller owns.

    ``sourceId`` is the ``custom:<id>`` namespace; ``healthState`` starts at
    'unverified' (no harvest has yet been proven complete) and graduates to
    'healthy' on the first VERIFIED harvest, once an oracle can prove the whole
    board was seen. ``openJobCount`` and ``lastSuccessAt`` render the list.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str
    display_name: str
    ats: str
    board_token: str
    source_id: str
    health_state: str | None = None
    open_job_count: int = Field(ge=0)
    last_success_at: datetime | None = None
    # Set on the first VERIFIED harvest (E7 Phase 2). NULL until a company
    # graduates. Served ahead of any consumer: the trend page's "already live
    # when tracking began" line is still derived from first_seen_at, not this.
    tracking_started_at: datetime | None = None
    # The 4-step discovery checklist, present only for an ``ats='discovered'`` row that
    # has one. NULL for every ATS company and for anything discovered before this
    # shipped — the UI renders the badge-only row it always did.
    discovery: DiscoveryProgressResponse | None = None
    # The published-board suggestion, present only once a first VERIFIED harvest found
    # one. NULL is the overwhelmingly common case and renders nothing.
    public_match: PublicMatchResponse | None = None


class AddQuotaResponse(BaseModel):
    """How many company adds the caller has left this calendar month.

    Rides the ``GET /api/users/companies`` envelope rather than getting its own
    endpoint: the Add Companies page already fetches (and polls) that list, so the
    counter arrives with data the page was loading anyway, is invalidated by the same
    ``MyCompanies`` tag every add and delete already invalidates, and can never be
    stale relative to the list it sits above.

    ``limit`` is the CONFIGURED cap and means exactly what it says: the number of adds
    allowed this month. ``0`` allows none (the kill switch), and the UI renders
    "0 of 0 adds left this month" — it is NOT an "unlimited" sentinel. The UI renders
    no counter only when this whole object is absent, which is a different thing: a
    server that predates the counter. ``remaining`` is deliberately NOT on the wire:
    ``max(limit - used, 0)`` is display arithmetic, it has exactly one definition
    (``addsRemaining`` in ``userCompaniesApi.ts``), and a second copy travelling over
    the wire would be a second thing that can disagree with the number on screen.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    used: int = Field(ge=0)
    limit: int = Field(ge=0)
    # Start of the next UTC calendar month — when ``used`` goes back to 0.
    resets_at: datetime


class UserCompanyListResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    companies: list[UserCompanyResponse]
    # Optional so a client built before the counter existed keeps parsing this
    # payload unchanged. The server always sends it.
    quota: AddQuotaResponse | None = None


# ---------------------------------------------------------------------------
# Admin · Custom Companies (E7 oversight page) — read-only
# ---------------------------------------------------------------------------


class AdminCustomCompanyRow(BaseModel):
    """One user-added board on the admin Custom Companies page.

    ``live_status`` is derived server-side from ONE SQL ``CASE`` (never re-derived
    on the client) so the table chips and the headline tile can never disagree.
    Precedence is top-down: ``orphan`` beats everything, because a board with no
    ``user_companies`` row is a data-integrity problem whether or not it harvests.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str
    display_name: str
    ats: str
    board_token: str
    enabled: bool
    health_state: str | None = None
    cadence_hours: int | None = None
    created_at: datetime
    last_success_at: datetime | None = None
    consecutive_failures: int = Field(ge=0)

    # Owner — LEFT JOIN. ``owner_count == 0`` is a real, present state: deleting a
    # user's last link leaves the board behind (an "orphan").
    owner_user_id: str | None = None
    owner_email: str | None = None
    owner_display_name: str | None = None
    owner_count: int = Field(ge=0)

    # company_scripts — LEFT JOIN; all null before the first script is written.
    transport: str | None = None
    oracle_kind: str | None = None
    script_version: int | None = None

    # Newest company_harvests row — LEFT JOIN; all null when never harvested.
    last_harvest_at: datetime | None = None
    last_harvest_age_s: int | None = None
    verdict: str | None = None
    verdict_reason: str | None = None
    records_harvested: int | None = None
    declared_total: int | None = None
    oracle_total: int | None = None
    cap_hit: bool | None = None

    # 'orphan' | 'never_harvested' | 'failing' | 'stale' | 'live'
    live_status: str
    # Short human reason the row is not live. null IFF live_status == 'live'.
    live_reason: str | None = None


class AdminCustomCompaniesSummary(BaseModel):
    """Headline counts for the four StatTiles. Always over the WHOLE table —
    never narrowed by the page's filters, so the tiles stay a stable reference
    point while the admin drills into the table below them."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    tracked_count: int = Field(ge=0)
    live_count: int = Field(ge=0)
    by_live_status: dict[str, int] = Field(default_factory=dict)
    # health_state -> count. Key '' means NULL health_state.
    by_health_state: dict[str, int] = Field(default_factory=dict)
    attempt_count: int = Field(ge=0)
    user_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    refused_count: int = Field(ge=0)
    stuck_count: int = Field(ge=0)


class AdminCustomCompaniesResponse(BaseModel):
    """GET /api/admin/custom-companies."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    companies: list[AdminCustomCompanyRow] = Field(default_factory=list)
    # Rows matching the filters, BEFORE limit/offset. Drives the pager.
    total: int = Field(ge=0)
    summary: AdminCustomCompaniesSummary
    # false when this database has no E7 tables (production today). Everything
    # else is zeroed/empty and the page renders its EmptyState instead of erroring.
    schema_present: bool = True


class AdminCustomCompanyAttemptRow(BaseModel):
    """One ADD ATTEMPT (not one audit row) on the admin Custom Companies page.

    A single user submission of a non-ATS URL writes TWO ``company_add_attempts``
    rows — an interim ``discovery_pending`` from the request path, then a terminal
    one from the worker. This model is the collapsed view: the newest row per
    attempt, plus the span metadata (``first_seen_at`` / ``audit_row_count`` /
    ``decided_in_s``) recovered from the rows it swallowed.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: int
    # Stable key: ``company_id`` when set, else ``attempt#<id>``. NOT just
    # company_id — the column is nullable (unsupported/empty/probe_failed write
    # none), and collapsing on it alone would fold every NULL into one phantom row.
    attempt_key: str
    created_at: datetime
    first_seen_at: datetime
    audit_row_count: int = Field(ge=1)
    # Seconds from the immediately-preceding discovery_pending row to the terminal
    # row. null when the previous row was not a pending (an idempotent re-add, or
    # a single-row ATS attempt).
    decided_in_s: int | None = None

    user_id: str
    user_email: str | None = None
    user_display_name: str | None = None

    submitted_url: str
    normalized_url: str | None = None
    resolved_ats: str | None = None
    board_token: str | None = None

    # The DERIVED outcome — 'pending'/'stuck' in place of the raw
    # 'discovery_pending', split on the stall grace period.
    outcome: str
    raw_outcome: str
    error_detail: str | None = None
    # error_detail split on the FIRST ": " — the engine's step name, then the reason.
    failed_step: str | None = None
    failure_reason: str | None = None

    company_id: str | None = None
    # false = the companies row was HARD-DELETED. The UI degrades to the URL.
    company_exists: bool = False
    company_display_name: str | None = None
    company_visibility: str | None = None
    company_health_state: str | None = None
    # null when company_exists is false or visibility <> 'user'. Same SQL CASE
    # as AdminCustomCompanyRow.live_status, so the two can never drift.
    company_live_status: str | None = None
    # provider_config->'discovery'->'steps' only. NEVER ->'network' (the full
    # request log plus a payload sample — kilobytes per row, unbounded in general).
    discovery_steps: list[DiscoveryStepResponse] | None = None


class AdminCustomCompanyUserRow(BaseModel):
    """One submitter's lifetime rollup. ``owns_now`` differs from ``added``
    because deleting a custom company hard-deletes the ``companies`` row."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    user_id: str
    email: str | None = None
    display_name: str | None = None
    attempts: int = Field(ge=0)
    added: int = Field(ge=0)
    refused: int = Field(ge=0)
    stuck: int = Field(ge=0)
    pending: int = Field(ge=0)
    already_public: int = Field(ge=0)
    other_failed: int = Field(ge=0)
    owns_now: int = Field(ge=0)
    first_attempt_at: datetime
    last_attempt_at: datetime


class AdminCustomCompanyAttemptsResponse(BaseModel):
    """GET /api/admin/custom-companies/attempts — attempts page + full rollup."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    attempts: list[AdminCustomCompanyAttemptRow] = Field(default_factory=list)
    # Attempts matching the filters, BEFORE limit/offset. Drives the pager.
    total: int = Field(ge=0)
    # ALWAYS over ALL attempts, ignoring filters — drives the table subtitle.
    by_outcome: dict[str, int] = Field(default_factory=dict)
    # ALWAYS over ALL attempts, ignoring filters. Also feeds the User dropdown.
    users: list[AdminCustomCompanyUserRow] = Field(default_factory=list)
    # true when the rollup hit its 200-row cap (mirrors AdminUserVisitsResponse).
    users_truncated: bool = False
    schema_present: bool = True
