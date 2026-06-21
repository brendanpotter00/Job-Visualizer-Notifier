"""SQLAlchemy declarative models mirroring the post-envAgnosticTables schema.

This module exists so Alembic's autogenerate can diff the live Postgres schema
against the model metadata. It is not used for application queries — the app
continues to use raw psycopg2 via scripts/shared/database.py.

Tables are bare-named (no `_{env}` suffix). Test isolation is handled by the
PYTEST_SCHEMA Postgres-schema mechanism in scripts/shared/database.get_connection
and src/backend/api/dependencies.get_db.

Any schema contract to update here is derived from reading migrations under
src/backend/alembic/versions/. Discrepancies between this file and the real
schema are caught by the Unit 3 parity test and resolved by editing this file,
never by editing frozen migrations.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    TIMESTAMP,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all ORM models.

    Defined as a ``DeclarativeBase`` subclass (rather than the legacy
    ``declarative_base()`` factory) so static type checkers recognize it as a
    valid base class / type. Metadata behaviour is identical, so Alembic
    autogenerate is unaffected.
    """


class JobListing(Base):
    __tablename__ = "job_listings"

    id = Column(Text, nullable=False)
    title = Column(Text, nullable=False)
    company = Column(Text, nullable=False)
    location = Column(Text, nullable=True)
    url = Column(Text, nullable=False)
    source_id = Column(Text, nullable=False)
    details = Column(JSONB, server_default=text("'{}'::jsonb"))
    posted_on = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False)
    closed_on = Column(TIMESTAMP(timezone=True), nullable=True)
    status = Column(Text, nullable=False, server_default=text("'OPEN'"))
    has_matched = Column(Boolean, server_default=text("false"))
    ai_metadata = Column(JSONB, server_default=text("'{}'::jsonb"))
    first_seen_at = Column(TIMESTAMP(timezone=True), nullable=False)
    last_seen_at = Column(TIMESTAMP(timezone=True), nullable=False)
    consecutive_misses = Column(Integer, server_default=text("0"))
    details_scraped = Column(Boolean, server_default=text("false"))
    normalization_status = Column(Text, nullable=True)  # NULL (never attempted) | 'done' | 'failed'

    __table_args__ = (
        PrimaryKeyConstraint("source_id", "id"),
        Index("idx_job_listings_status", "status"),
        Index("idx_job_listings_company", "company"),
        Index("idx_job_listings_last_seen", "last_seen_at"),
    )


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    run_id = Column(Text, primary_key=True)
    company = Column(Text, nullable=False)
    started_at = Column(Text, nullable=False)
    completed_at = Column(Text, nullable=True)
    mode = Column(Text, nullable=False)
    jobs_seen = Column(Integer, server_default=text("0"))
    new_jobs = Column(Integer, server_default=text("0"))
    closed_jobs = Column(Integer, server_default=text("0"))
    details_fetched = Column(Integer, server_default=text("0"))
    error_count = Column(Integer, server_default=text("0"))


class User(Base):
    __tablename__ = "users"

    id = Column(Text, primary_key=True)
    auth0_id = Column(Text, nullable=False, unique=True)
    email = Column(Text, nullable=False)
    display_name = Column(Text, nullable=True)
    given_name = Column(Text, nullable=True)
    family_name = Column(Text, nullable=True)
    picture_url = Column(Text, nullable=True)
    created_at = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=False)
    # "I've already decided about every company that existed as of this time."
    # Companies created after this watermark auto-enroll into the user's set on
    # read (gated by auto_enroll_new_companies); bumped to now() on every save
    # so opt-outs stick. Real timestamptz — do NOT mimic the legacy Text-typed
    # created_at/updated_at above.
    company_enroll_watermark = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    auto_enroll_new_companies = Column(
        Boolean, nullable=False, server_default=text("true")
    )

    __table_args__ = (
        UniqueConstraint("email", name="users_email_key"),
        Index("idx_users_auth0_id", "auth0_id"),
        Index("idx_users_email", "email"),
    )


class Admin(Base):
    __tablename__ = "admins"

    user_id = Column(
        Text,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    granted_by = Column(
        Text,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


class UserEnabledCompany(Base):
    __tablename__ = "user_enabled_companies"

    user_id = Column(
        Text,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    company_id = Column(Text, nullable=False)
    created_at = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        PrimaryKeyConstraint("user_id", "company_id"),
        Index("idx_user_enabled_companies_user_id", "user_id"),
    )


class UserSavedFilters(Base):
    """Scalar per-user saved filters (one row per user).

    Time windows are plain TEXT validated to the ``TimeWindow`` Literal at the
    Pydantic boundary (matches how ``job_listings.status`` stays TEXT and is
    validated in ``models``). ``locations`` is a JSONB array of canonical
    location strings shared by both the Recent and Trend pages.

    ``recent_active_keyword_list_id`` / ``trend_active_keyword_list_id`` are
    plain TEXT (NOT a FK) because they may hold the synthetic built-in id
    ``'builtin-swe'``, which has no row in ``user_keyword_lists``. Referential
    integrity to user lists is enforced in the service layer, and a list
    DELETE NULLs any pointer referencing it in the same transaction.
    """

    __tablename__ = "user_saved_filters"

    user_id = Column(
        Text,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    recent_time_window = Column(Text, nullable=False, server_default=text("'3h'"))
    trend_time_window = Column(Text, nullable=False, server_default=text("'7d'"))
    locations = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    recent_active_keyword_list_id = Column(Text, nullable=True)
    trend_active_keyword_list_id = Column(Text, nullable=True)
    created_at = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class UserKeywordList(Base):
    """One saved keyword list per row (one user owns many lists).

    ``id`` is an app-generated uuid4 hex (matching the TEXT-PK convention used
    elsewhere). ``tags`` is a JSONB array of ``{"text", "mode"}`` objects whose
    shape + caps are validated by Pydantic on write. The built-in "Software
    Engineering" list is NOT stored here — it is synthesized server-side and its
    name is reserved case-insensitively against this table's unique index.
    """

    __tablename__ = "user_keyword_lists"

    id = Column(Text, primary_key=True)
    user_id = Column(
        Text,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = Column(Text, nullable=False)
    tags = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    position = Column(Integer, nullable=False, server_default=text("0"))
    created_at = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_user_keyword_lists_user_id", "user_id"),
        # Case-insensitive uniqueness of list name per user. Functional
        # expression index on lower(name); the service pre-checks for a clean
        # 409 and catches the UniqueViolation as a backstop.
        Index(
            "uq_user_keyword_lists_user_name",
            "user_id",
            text("lower(name)"),
            unique=True,
        ),
    )


class Feature(Base):
    __tablename__ = "features"

    id = Column(Text, primary_key=True)
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=False)
    created_at = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class FeatureUpvote(Base):
    __tablename__ = "feature_upvotes"

    feature_id = Column(
        Text,
        ForeignKey("features.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(
        Text,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        PrimaryKeyConstraint("feature_id", "user_id"),
        Index("idx_feature_upvotes_feature_id", "feature_id"),
        Index("idx_feature_upvotes_user_id", "user_id"),
    )


class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(Text, primary_key=True)
    message = Column(Text, nullable=False)
    # Nullable FK so anonymous submissions are allowed; SET NULL keeps the
    # feedback row (and its email/display_name snapshot) after a user is deleted.
    user_id = Column(
        Text,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Point-in-time snapshots of who submitted this, as they were AT submit time.
    # Kept independent of the live users row so the admin view stays stable after
    # an email change or account deletion (FK goes NULL, snapshot stays).
    user_email = Column(Text, nullable=True)
    display_name = Column(Text, nullable=True)
    created_at = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_feedback_user_id", "user_id"),
        Index("idx_feedback_created_at", "created_at"),
    )


class Company(Base):
    __tablename__ = "companies"

    id = Column(Text, primary_key=True)
    display_name = Column(Text, nullable=False)
    ats = Column(Text, nullable=False)
    board_token = Column(Text, nullable=False)
    enabled = Column(Boolean, nullable=False, server_default=text("true"))
    # Per-ATS configuration that doesn't fit in scalar columns. Eightfold rows
    # carry ``{tenant_host, domain}``; Workday rows carry
    # ``{base_url, tenant_slug, career_site_slug, default_facets?}``. The column
    # name is a frozen contract — Eightfold seeded it in migration
    # ``08e719b2aa03`` and Workday's seed migration reuses it. Empty
    # ``{}``::jsonb default keeps Greenhouse + Ashby + Lever + Gem rows
    # unaffected.
    provider_config = Column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # Curated directory content for the public "Curated Companies" page. Both
    # nullable — a company added without a profile still lists (the page omits
    # the missing line). Populated idempotently on startup from the committed
    # ``data/company_profiles.json`` by ``services.companies_seed`` (that JSON
    # is the source of truth, re-applied each boot).
    blurb = Column(Text, nullable=True)
    accomplishment = Column(Text, nullable=True)
    created_at = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_companies_ats_enabled", "ats", "enabled"),
    )


class WorkerHeartbeat(Base):
    """Tick row written by the heartbeat periodic task every 5 minutes.

    Independent of `procrastinate_events` so a sick connector that breaks
    event-writes (but leaves the worker's periodic scheduler alive) still
    surfaces a freshness signal via /health/worker. The table is kept tiny
    by a separate cleanup periodic task that prunes rows older than 24h.
    """

    __tablename__ = "worker_heartbeats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    at = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # Plain ASC btree — Postgres' planner uses it for both
        # `MAX(at)` (the /health/worker probe) and
        # `at < now() - interval '24h'` (the cleanup task) with a
        # forward or backward scan. No DESC needed.
        Index("idx_worker_heartbeats_at", "at"),
    )


class Location(Base):
    __tablename__ = "locations"

    id = Column(Integer, primary_key=True)
    canonical_name = Column(Text, nullable=False)        # "San Francisco, CA, US"
    kind = Column(Text, nullable=False)                  # 'city'|'region'|'country'|'remote'
    city = Column(Text, nullable=True)                   # always NULL for kind='remote'
    region = Column(Text, nullable=True)                 # may scope a remote (e.g. 'AZ')
    country = Column(Text, nullable=True)                # may scope a remote (e.g. 'US')
    remote_scope = Column(Text, nullable=True)           # NULL|'global'|'us'|'eu'|country code
    lat = Column(Float, nullable=True)                   # NULL in v1 (Decision #7)
    lng = Column(Float, nullable=True)                   # NULL in v1
    created_at = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # remote_scope intentionally part of the uniqueness key (Decision #6).
        UniqueConstraint(
            "kind", "city", "region", "country", "remote_scope",
            name="uq_locations_canonical",
            postgresql_nulls_not_distinct=True,
        ),
    )


class LocationAlias(Base):
    __tablename__ = "location_aliases"

    raw_text = Column(Text, primary_key=True)            # pre-normalized cache key
    source = Column(Text, nullable=False)                # 'llm'|'manual' (manual wins; Decision #10)
    confidence = Column(Float, nullable=True)
    created_at = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class AliasLocation(Base):
    # join: one alias -> 1..N canonical locations, ordered by `position`.
    __tablename__ = "alias_locations"

    raw_text = Column(
        Text,
        ForeignKey("location_aliases.raw_text", ondelete="CASCADE"),
        primary_key=True,
    )
    normalized_location_id = Column(
        Integer, ForeignKey("locations.id"), primary_key=True
    )
    position = Column(Integer, nullable=False)           # order within the raw string


class JobLocation(Base):
    # job <-> canonical location join (Decision #5: keyed by job alone).
    #
    # NOTE: job_listing_id has NO database FK. job_listings' PK is the COMPOSITE
    # (source_id, id) and there is no UNIQUE/PK constraint on `id` alone, so a
    # single-column FK to job_listings(id) is invalid Postgres. We key
    # job_locations by job_listing_id alone (matches the plan's worked examples
    # and lets Units 5/8 operate with just job_id) and enforce integrity at the
    # application layer. job_listings.id is globally unique in practice
    # (verified: 0 collisions across 44,666 prod rows). normalized_location_id
    # keeps a real FK because locations.id is a single-column PK.
    __tablename__ = "job_locations"

    job_listing_id = Column(Text, nullable=False)
    normalized_location_id = Column(
        Integer, ForeignKey("locations.id"), nullable=False
    )
    is_primary = Column(Boolean, nullable=False, server_default=text("false"))

    __table_args__ = (
        PrimaryKeyConstraint("job_listing_id", "normalized_location_id"),
        Index("idx_job_locations_job_listing_id", "job_listing_id"),
    )
