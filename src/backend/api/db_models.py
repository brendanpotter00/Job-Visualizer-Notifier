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
    BigInteger,
    Boolean,
    Column,
    DDL,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    TIMESTAMP,
    Text,
    UniqueConstraint,
    event,
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

    # External enrichment (job-enricher pull integration). All nullable /
    # catalog-only (no backfill) so the migration can't rewrite this large
    # table — see docs/incidents/2026-04-18-migration-filled-postgres-volume/.
    enrichment_status = Column(Text, nullable=True)      # NULL | 'claimed' | 'done' | 'needs_human'
    enrichment_category = Column(Text, ForeignKey("job_categories.slug"), nullable=True)
    enrichment_level = Column(Text, ForeignKey("job_levels.slug"), nullable=True)
    enrichment_claimed_at = Column(TIMESTAMP(timezone=True), nullable=True)

    __table_args__ = (
        PrimaryKeyConstraint("source_id", "id"),
        Index("idx_job_listings_status", "status"),
        Index("idx_job_listings_company", "company"),
        Index("idx_job_listings_last_seen", "last_seen_at"),
        # Drives the /pending claim scan (find NULL-status OPEN jobs fast) and
        # the analytics/dashboard GROUP BYs on category within OPEN jobs.
        Index("idx_job_listings_enrichment_status", "enrichment_status"),
        Index("idx_job_listings_status_category", "status", "enrichment_category"),
        Index("idx_job_listings_status_level", "status", "enrichment_level"),
        # Partial index on the join key used by the open_only location-search
        # path (saved_filters_service.search_locations): the EXISTS semijoin
        # probes job_listings by id restricted to OPEN rows. A partial index on
        # id WHERE status='OPEN' lets that probe use an index instead of a full
        # seq-scan of the ~57k-row table. (job_listings' PK is the composite
        # (source_id, id), so there is no standalone index on id alone.)
        Index(
            "idx_job_listings_open_id",
            "id",
            postgresql_where=text("status = 'OPEN'"),
        ),
        # Drives the /pending claim ORDER BY (freshest first_seen_at first) so the
        # enricher labels fresh jobs first even with a deep backlog. Partial index
        # that mirrors the claim's predicate exactly (enrichment_status IS NULL AND
        # status='OPEN' — the claimable set), keyed on first_seen_at so Postgres
        # scans it backward for the DESC + LIMIT instead of sorting the ~19k-row
        # backlog per tick. Partial so it stays small (only claimable rows) and
        # cheap to build (no rewrite of the large table — see the 2026-04-18
        # volume incident). Not last_seen_at/posted_on — see the /pending claim
        # comment and docs/database-schema.md "recency fields".
        Index(
            "idx_job_listings_enrichment_claim",
            "first_seen_at",
            postgresql_where=text("enrichment_status IS NULL AND status = 'OPEN'"),
        ),
    )


class JobFreshness(Base):
    """High-churn "freshness" sidecar for ``job_listings`` (see the 2026-07-13
    ``/api/jobs`` outage postmortem).

    ``last_seen_at`` is re-stamped on *every* open job on *every* hourly scrape
    cycle. Because it lives on ``job_listings`` — a ~600 MB table with a
    TOAST-heavy ``details`` JSONB — and is indexed, each of those ~millions of
    updates is a non-HOT update that bloats both the heap and
    ``idx_job_listings_last_seen`` (the index reached 100 MB for 58k rows and the
    ``ORDER BY last_seen_at DESC`` read blew past the 30 s statement timeout).

    Moving the two churny columns (``last_seen_at``, ``consecutive_misses``) onto
    this narrow ~50-byte/row sidecar means the wide parent stops being rewritten
    on every cycle, and this table's own ``last_seen_at`` index stays small enough
    that the aggressive autovacuum settings applied in the migration keep it tight
    (the mechanism that could not keep up on the 600 MB parent).

    Unlike the other side tables (``job_enrichment``/``job_tags``, keyed on
    ``job_listing_id`` alone — which cannot FK to ``job_listings``' *composite*
    ``(source_id, id)`` PK), this table is keyed on the full ``(source_id, id)``,
    so it carries a REAL composite FK with ``ON DELETE CASCADE`` (no orphaned
    freshness rows). Paired with the ``AFTER INSERT`` trigger installed in the
    migration — which creates the matching freshness row for every new
    ``job_listings`` row regardless of insert path — the read-side INNER JOIN is
    guaranteed lossless: the two tables cannot drift. The
    ``fillfactor``/autovacuum storage params and the trigger + backfill are set
    in the migration (SQLAlchemy metadata cannot express them), not here.
    """

    __tablename__ = "job_freshness"

    source_id = Column(Text, nullable=False)
    id = Column(Text, nullable=False)
    last_seen_at = Column(TIMESTAMP(timezone=True), nullable=False)
    consecutive_misses = Column(Integer, nullable=False, server_default=text("0"))

    __table_args__ = (
        PrimaryKeyConstraint("source_id", "id"),
        # Composite FK onto job_listings' composite PK. ON DELETE CASCADE means a
        # deleted listing drops its freshness row automatically — no orphans.
        ForeignKeyConstraint(
            ["source_id", "id"],
            ["job_listings.source_id", "job_listings.id"],
            ondelete="CASCADE",
            name="job_freshness_job_listings_fkey",
        ),
        # Serves the /api/jobs ORDER BY last_seen_at DESC (LIMIT n) — a backward
        # index scan on this tiny table instead of on the bloated parent index.
        Index("idx_job_freshness_last_seen", "last_seen_at"),
    )


# --- Anti-drift trigger, as model metadata --------------------------------
# The migration (01fef5c9c582) installs this same trigger via op.execute for the
# prod deploy path. It is ALSO wired here as an ``after_create`` DDL event so the
# create_all-based test/parity bootstrap (see api/tests/conftest.py and
# scripts/tests/conftest.py, which create_all + stamp rather than run migration
# bodies) installs identical behavior — otherwise a create_all schema would have
# the table but not the trigger, and the Unit 3 read-side INNER JOIN would behave
# differently in tests than in prod. The two paths never both run: prod applies
# the migration (no create_all); tests use create_all (stamp, not upgrade).
#
# References are intentionally unqualified so they resolve through the caller's
# search_path — correct in prod (public) and in the per-worker ``test_<hex>``
# schema (search_path pinned by the conftest fixtures). Seeds last_seen_at from
# NEW.first_seen_at and a literal 0 (never NEW.last_seen_at/consecutive_misses)
# so it keeps working after the Unit 4 contract migration drops those columns.
# Physical tuning (fillfactor/autovacuum) stays migration-only — it has no
# behavioral effect, so create_all test DBs don't need it.
_JOB_FRESHNESS_SYNC_FUNCTION = DDL(
    """
    CREATE OR REPLACE FUNCTION job_freshness_sync() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        INSERT INTO job_freshness (source_id, id, last_seen_at, consecutive_misses)
        VALUES (NEW.source_id, NEW.id, NEW.first_seen_at, 0)
        ON CONFLICT (source_id, id) DO NOTHING;
        RETURN NULL;  -- AFTER trigger: return value is ignored
    END;
    $$;
    """
)
_JOB_FRESHNESS_SYNC_TRIGGER = DDL(
    """
    CREATE TRIGGER job_freshness_sync_after_insert
        AFTER INSERT ON job_listings
        FOR EACH ROW
        EXECUTE FUNCTION job_freshness_sync();
    """
)

event.listen(
    JobFreshness.__table__,
    "after_create",
    _JOB_FRESHNESS_SYNC_FUNCTION.execute_if(dialect="postgresql"),
)
event.listen(
    JobFreshness.__table__,
    "after_create",
    _JOB_FRESHNESS_SYNC_TRIGGER.execute_if(dialect="postgresql"),
)
event.listen(
    JobFreshness.__table__,
    "before_drop",
    DDL(
        "DROP TRIGGER IF EXISTS job_freshness_sync_after_insert ON job_listings"
    ).execute_if(dialect="postgresql"),
)
event.listen(
    JobFreshness.__table__,
    "before_drop",
    DDL("DROP FUNCTION IF EXISTS job_freshness_sync()").execute_if(dialect="postgresql"),
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
    # Engagement counter for the admin roster's "most frequent users" view.
    # Incremented once per full page load / refresh by the authenticated user
    # via POST /api/users/visit (NOT on client-side SPA route navigation).
    # Real timestamptz for last_visit_at — like company_enroll_watermark above,
    # do NOT mimic the legacy Text-typed created_at/updated_at.
    visit_count = Column(Integer, nullable=False, server_default=text("0"))
    last_visit_at = Column(TIMESTAMP(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("email", name="users_email_key"),
        Index("idx_users_auth0_id", "auth0_id"),
        Index("idx_users_email", "email"),
    )


class UserVisit(Base):
    __tablename__ = "user_visits"

    # Append-only per-visit log: one row per POST /api/users/visit (one full
    # page load / refresh, NOT SPA route navigation — same semantics as the
    # denormalized users.visit_count / last_visit_at counters, which are KEPT).
    # Backs the admin roster's clickable "Visits" modal.
    #
    # DB-assigned BIGINT (BIGSERIAL) PK, NOT a Python-generated uuid Text like
    # users.id: an append-only log has no natural client-supplied id, so a
    # database-assigned surrogate is the right key.
    id = Column(BigInteger, primary_key=True)
    user_id = Column(
        Text,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Stamped server-side at insert. Real timestamptz — mirrors last_visit_at,
    # do NOT mimic the legacy Text-typed created_at/updated_at.
    visited_at = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # Serves the modal query (WHERE user_id = %s ORDER BY visited_at DESC
        # LIMIT N): a plain ascending composite btree supports the descending
        # scan via a backward index walk, so no DESC index is needed.
        Index(
            "idx_user_visits_user_id_visited_at",
            "user_id",
            "visited_at",
        ),
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
    location strings shared by both the Recent and Trend pages; ``category`` and
    ``level`` are JSONB arrays of enrichment facet slugs, likewise shared by
    both pages.

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
    category = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    level = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
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
    # NULL = still an upcoming/candidate feature; non-null = shipped, and the
    # timestamp doubles as the "shipped on" date used to order the completed list.
    completed_at = Column(TIMESTAMP(timezone=True), nullable=True)


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
        # Standalone index on the semijoin key used by the open_only
        # location-search path (saved_filters_service.search_locations): the
        # EXISTS subquery filters job_locations by normalized_location_id. The
        # PK leads with job_listing_id, so it can't serve this probe — without
        # this index the open_only path seq-scans the ~54k-row table.
        Index("idx_job_locations_norm_loc", "normalized_location_id"),
    )


class JobCategory(Base):
    # Tiny seeded dimension for the enrichment category facet. Gives display
    # labels + ordering + a real FK target for job_listings.enrichment_category
    # (so the taxonomy is DB-enforced, not just a code convention).
    __tablename__ = "job_categories"

    slug = Column(Text, primary_key=True)                 # 'software_engineering', ...
    label = Column(Text, nullable=False)                  # 'Software Engineering'
    sort_order = Column(Integer, nullable=False, server_default=text("0"))


class JobLevel(Base):
    # Tiny seeded dimension for the leveling facet. `parent_slug` encodes the
    # hierarchy — the whole system's load-bearing case is new_grad -> entry, so
    # the "entry" filter can expand to {entry, new_grad} from data, not code.
    __tablename__ = "job_levels"

    slug = Column(Text, primary_key=True)                 # 'new_grad','entry','mid',...
    label = Column(Text, nullable=False)
    rank = Column(Integer, nullable=False)                # ordering (new_grad=0 ... manager=5)
    parent_slug = Column(Text, ForeignKey("job_levels.slug"), nullable=True)  # new_grad -> entry


class JobTag(Base):
    # Many-to-many free-form tags. Carries source_id so the key is the COMPOSITE
    # (source_id, job_listing_id, tag): job_listings' PK is (source_id, id) and
    # `id` is NOT globally unique, so keying on job_listing_id alone could
    # clobber/collapse a different source's tags once two sources share an id.
    # Still no FK (the composite PK on job_listings blocks a single-col FK) —
    # integrity at the app layer. Indexed on `tag` for reverse lookup
    # ("all jobs tagged go").
    __tablename__ = "job_tags"

    source_id = Column(Text, nullable=False)
    job_listing_id = Column(Text, nullable=False)
    tag = Column(Text, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("source_id", "job_listing_id", "tag"),
        Index("idx_job_tags_tag", "tag"),
    )


class JobEnrichment(Base):
    # 1:1 side table holding the heavy / audit payload so the hot job_listings
    # tuple stays narrow. Keyed by the COMPOSITE (source_id, job_listing_id) —
    # job_listings' PK is (source_id, id) and `id` is NOT globally unique, so
    # keying on job_listing_id alone could clobber a different source's row once
    # two sources share an id. Still no FK (composite PK blocks a single-col FK);
    # integrity at the app layer. Written by the enrichment callback; the
    # filterable facets (category/level/status) live as columns on job_listings,
    # not here.
    __tablename__ = "job_enrichment"

    source_id = Column(Text, nullable=False)
    job_listing_id = Column(Text, nullable=False)
    clean_description = Column(Text, nullable=True)
    classify_confidence = Column(Float, nullable=True)
    classify_reasoning = Column(Text, nullable=True)
    taxonomy_version = Column(Text, nullable=True)        # provenance for manual re-enrich
    judged = Column(Boolean, nullable=False, server_default=text("false"))
    judge_passed = Column(Boolean, nullable=True)         # NULL not judged | true | false(corrected)
    judge_confidence = Column(Float, nullable=True)
    judge_notes = Column(Text, nullable=True)
    needs_human = Column(Boolean, nullable=False, server_default=text("false"))
    enriched_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    # Human correction provenance (admin needs-human queue). While
    # human_corrected_at is set, apply_result refuses to overwrite this row's
    # facets — a human label always outlives a later automated re-write; only an
    # explicit admin re-enrich (which clears these) reopens the row to the agent.
    human_corrected_at = Column(TIMESTAMP(timezone=True), nullable=True)
    human_corrected_by = Column(Text, nullable=True)      # admin email (JWT claim)
    # The human's verdict, distinct from the judge's (judged/judge_passed): what
    # the reviewer decided when they resolved a needs-human row. NULL = not yet
    # reviewed | 'corrected' (labels were wrong, human fixed them) |
    # 'confirmed_correct' (row was flagged but the human validated the AI's
    # proposal as-is). Both decisions stamp human_corrected_at (the lock); this
    # column is what lets the learning feed tell a fix from a validated raise.
    human_decision = Column(Text, nullable=True)

    __table_args__ = (
        PrimaryKeyConstraint("source_id", "job_listing_id"),
        Index("idx_job_enrichment_needs_human", "needs_human"),
    )


class EnrichmentTick(Base):
    # One row per enricher tick, pushed by the laptop via
    # POST /api/internal/enrichment/metrics (best-effort, idempotent on
    # tick_uuid). This is the ONLY channel that makes the laptop-side pipeline
    # observable from JVN — per-stage latency, throughput, heartbeat and eval
    # scorecards live in the enricher's local SQLite and never appear in
    # job_enrichment. Counters are real columns (not JSONB) so the admin charts
    # can aggregate in SQL; the free-shape payloads (knobs, stage timings,
    # scorecard) stay JSONB.
    __tablename__ = "enrichment_ticks"

    id = Column(Integer, primary_key=True)                # autoincrement surrogate
    tick_uuid = Column(Text, nullable=False)              # idempotency key from the laptop
    started_at = Column(TIMESTAMP(timezone=True), nullable=False)
    ended_at = Column(TIMESTAMP(timezone=True), nullable=True)
    status = Column(Text, nullable=False)                 # 'ok' | 'error' | 'running'
    notes = Column(Text, nullable=True)
    claimed = Column(Integer, nullable=False, server_default=text("0"))
    cleaned = Column(Integer, nullable=False, server_default=text("0"))
    classified = Column(Integer, nullable=False, server_default=text("0"))
    judged = Column(Integer, nullable=False, server_default=text("0"))
    corrected = Column(Integer, nullable=False, server_default=text("0"))
    needs_human = Column(Integer, nullable=False, server_default=text("0"))
    sent = Column(Integer, nullable=False, server_default=text("0"))
    errors = Column(Integer, nullable=False, server_default=text("0"))
    nulled_facets = Column(Integer, nullable=False, server_default=text("0"))
    duration_s = Column(Float, nullable=True)
    taxonomy_version = Column(Text, nullable=True)
    knobs = Column(JSONB, nullable=True)                  # runtime config snapshot
    stage_timings = Column(JSONB, nullable=True)          # [{stage, ms, items, retries}]
    heartbeat_age_s = Column(Float, nullable=True)
    scorecard = Column(JSONB, nullable=True)              # latest eval scorecard (only when new)
    enricher_version = Column(Text, nullable=True)
    drift_suspected = Column(Boolean, nullable=False, server_default=text("false"))
    received_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tick_uuid", name="uq_enrichment_ticks_tick_uuid"),
        Index("idx_enrichment_ticks_started_at", "started_at"),
    )
