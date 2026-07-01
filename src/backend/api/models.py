"""Pydantic response models with camelCase serialization for frontend compatibility."""

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
_MAX_TAGS_PER_LIST = 100
_MAX_TAG_TEXT_LEN = 100
_MAX_LIST_NAME_LEN = 100
_MAX_LOCATION_LEN = 200  # matches LocationSpec.canonical_name


def _dedup_locations(locations: list[str]) -> list[str]:
    """Collapse exact-duplicate location strings, preserving first-seen order."""
    seen: set[str] = set()
    result: list[str] = []
    for loc in locations:
        if loc not in seen:
            seen.add(loc)
            result.append(loc)
    return result


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
    recent_active_keyword_list_id: str | None = None
    trend_active_keyword_list_id: str | None = None


class SavedFiltersUpdateRequest(BaseModel):
    """Full-replace body for PUT /api/users/saved-filters.

    Locations are deduped (order-preserving) at the boundary. The active-list
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
    recent_active_keyword_list_id: str | None = Field(default=None, max_length=64)
    trend_active_keyword_list_id: str | None = Field(default=None, max_length=64)

    @field_validator("locations")
    @classmethod
    def _dedup_locations_field(cls, value: list[str]) -> list[str]:
        return _dedup_locations(value)


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
    """One canonical location returned by the saved-filters location-search
    autocomplete. Leaner than ``AdminLocationResponse`` (no ``position``)."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: int
    canonical_name: str
    kind: str


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
    that field is typed ``list[dict[str, Any]]`` so even a value-type-malformed
    location (e.g. ``confidence: "high"``) is carried through unchanged and
    degraded by ``CanonicalLocation(**loc)`` inside the writer's ``enr_loc``
    savepoint ("labels persisted, location skipped + warned"), rather than
    routing the whole item to ``failed[]``. ``CanonicalLocation`` is the sole
    strict arbiter; enforcing primitive types here would instead fail the item
    on a bad location (reversing F2's "location degrades independently" intent).
    Kept as a typed reference of the fields the enricher sends.
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

    ``locations`` is typed ``list[dict[str, Any]]`` (NOT ``EnrichmentLocationItem``)
    so a value-type-malformed location is carried through and degraded by
    ``CanonicalLocation`` in the writer's ``enr_loc`` savepoint, keeping the row
    ``written``/``done`` (F2/F10) instead of failing the whole item.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    job_listing_id: Annotated[str, StringConstraints(min_length=1)]
    source_id: Annotated[str, StringConstraints(min_length=1)]
    category: str | None = None
    level: str | None = None
    tags: list[str] = Field(default_factory=list)
    clean_description: str | None = None
    classify_confidence: float | None = None
    classify_reasoning: str | None = None
    taxonomy_version: str | None = None
    raw_location: str | None = None
    locations: list[dict[str, Any]] = Field(default_factory=list)
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
