"""job_freshness trigger seeds last_seen_at from now(), not NEW.first_seen_at

Revision ID: 7a4c1e93b6d8
Revises: 2633dd6348e4
Create Date: 2026-08-26 07:00:00.000000+00:00

POSTED-DATE-PLAN.md §5/U2 — one line, and the only real obstacle to D10.

``first_seen_at`` is being repurposed as the **effective posted date** (§2): the
board's own posting date when it publishes a real one, our first sight otherwise.
That makes it a value that can legitimately be months old on the day the row is
inserted — and the ``AFTER INSERT`` trigger has always seeded the freshness
sidecar's ``last_seen_at`` from it. Left alone, onboarding a board that publishes
old dates would materialize freshness rows that claim we last saw those jobs a
year ago, which is simply false: we saw them a second ago.

``last_seen_at`` means "when did this scrape last observe the listing". An INSERT
*is* an observation, so ``now()`` is the honest seed and ``NEW.first_seen_at``
never was — it was only ever right because the two values used to be the same
number.

This makes the trigger AGREE with what the code already does two statements
later: every upsert path calls ``_upsert_freshness`` in the same transaction
(``scripts/shared/database.py:493``, ``:572``) and overwrites the seed with the
scrape timestamp. The only caller that actually relies on the trigger's seed is
the plain-INSERT full-scrape mode (``scripts/run_scraper.py:242``).

⚠️ **never-wrong-close.** This cannot change close behaviour. The close sweep is
purely ``consecutive_misses >= threshold``
(``get_jobs_exceeding_miss_threshold``, ``scripts/shared/database.py:783-790``);
there is no time-based close anywhere in it. The one optional time clause,
``min_seen_age_hours``, is a *floor* that only ever makes closing HARDER, and all
six public crons pass ``None``. The trigger's seed also moves strictly FORWARD
here (``now()`` >= any backdated ``first_seen_at``), so even a hypothetical
age-based rule would close less, never more.

The matching ``create_all`` DDL in ``api/db_models.py`` is changed in lockstep —
the test databases build their schema from that, not from this migration body, so
the two must not drift.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '7a4c1e93b6d8'
down_revision: Union[str, None] = '2633dd6348e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Unqualified table reference on purpose: it resolves through the caller's
# search_path, which is ``public`` in prod and the per-worker ``test_<hex>``
# schema under pytest. Matches the original definition in 01fef5c9c582.
_SEED_NOW = """
CREATE OR REPLACE FUNCTION job_freshness_sync() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO job_freshness (source_id, id, last_seen_at, consecutive_misses)
    VALUES (NEW.source_id, NEW.id, now(), 0)
    ON CONFLICT (source_id, id) DO NOTHING;
    RETURN NULL;  -- AFTER trigger: return value is ignored
END;
$$;
"""

_SEED_FIRST_SEEN_AT = """
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


def upgrade() -> None:
    # CREATE OR REPLACE only swaps the function body. The trigger
    # (``job_freshness_sync_after_insert``) binds to the function by name and is
    # untouched, so there is no window in which listings insert without a
    # freshness row.
    op.execute(_SEED_NOW)


def downgrade() -> None:
    op.execute(_SEED_FIRST_SEEN_AT)
