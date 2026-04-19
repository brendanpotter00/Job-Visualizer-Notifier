"""SQLAlchemy declarative models mirroring the post-migration-0005 schema.

This module exists so Alembic's autogenerate can diff the live Postgres schema
against the model metadata. It is not used for application queries — the app
continues to use raw psycopg2 via scripts/shared/database.py.

Tables are environment-suffixed (job_listings_{env}, users_{env}, etc.)
matching the repo's existing naming convention. The env is read at import
time from SCRAPER_ENVIRONMENT; validation mirrors
scripts/shared/database._is_valid_env so the same allow-list applies here.

Any schema contract to update here is derived from reading migrations 0001-0005
under scripts/shared/migrations/. Discrepancies between this file and the real
schema are caught by the Unit 3 parity test and resolved by editing this file,
never by editing the frozen migrations.
"""

from __future__ import annotations

import os
import re

from sqlalchemy import (
    Boolean,
    Column,
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
from sqlalchemy.orm import declarative_base

_ALLOWED_ENVS = frozenset({"local", "qa", "prod"})
_TEST_ENV_PATTERN = re.compile(r"^test_[a-f0-9]{8}$")


def _resolve_env() -> str:
    env = os.environ.get("SCRAPER_ENVIRONMENT", "local")
    if env in _ALLOWED_ENVS or _TEST_ENV_PATTERN.match(env):
        return env
    raise ValueError(
        f"Invalid SCRAPER_ENVIRONMENT for db_models: {env!r}. "
        f"Must be one of {sorted(_ALLOWED_ENVS)} or match ^test_[a-f0-9]{{8}}$."
    )


_ENV = _resolve_env()

Base = declarative_base()


class JobListing(Base):
    __tablename__ = f"job_listings_{_ENV}"

    id = Column(Text, primary_key=True)
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

    __table_args__ = (
        Index(f"idx_job_listings_{_ENV}_status", "status"),
        Index(f"idx_job_listings_{_ENV}_company", "company"),
        Index(f"idx_job_listings_{_ENV}_last_seen", "last_seen_at"),
    )


class ScrapeRun(Base):
    __tablename__ = f"scrape_runs_{_ENV}"

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
    __tablename__ = f"users_{_ENV}"

    id = Column(Text, primary_key=True)
    auth0_id = Column(Text, nullable=False, unique=True)
    email = Column(Text, nullable=False)
    display_name = Column(Text, nullable=True)
    given_name = Column(Text, nullable=True)
    family_name = Column(Text, nullable=True)
    picture_url = Column(Text, nullable=True)
    created_at = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("email", name=f"users_{_ENV}_email_key"),
        Index(f"idx_users_{_ENV}_auth0_id", "auth0_id"),
        Index(f"idx_users_{_ENV}_email", "email"),
    )


class UserEnabledCompany(Base):
    __tablename__ = f"user_enabled_companies_{_ENV}"

    user_id = Column(
        Text,
        ForeignKey(f"users_{_ENV}.id", ondelete="CASCADE"),
        nullable=False,
    )
    company_id = Column(Text, nullable=False)
    created_at = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        PrimaryKeyConstraint("user_id", "company_id"),
        Index(f"idx_user_enabled_companies_{_ENV}_user_id", "user_id"),
    )
