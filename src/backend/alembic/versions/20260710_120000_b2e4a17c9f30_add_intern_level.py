"""add standalone `intern` leveling tier

Revision ID: b2e4a17c9f30
Revises: 288764e337a4
Create Date: 2026-07-10 12:00:00.000000+00:00

Adds the `intern` job_levels row and renumbers the pre-existing six tiers +1 so
intern sorts first in the level dropdown.

`intern` is a STANDALONE tier (``parent_slug = NULL``) — an internship is its own
filter and does NOT surface under `entry` or `new_grad`. Because it has no
parent it adds no edge to the `entry -> {entry, new_grad}` filter expansion, so
``api.services.database._LEVEL_FILTER_EXPANSION`` (and its frontend mirror) need
no change.

Idempotent: the INSERT is ``ON CONFLICT (slug) DO NOTHING`` and every rank change
is a plain value-assignment, so re-running is a no-op. Ships together with
``enrichment_writer.LEVEL_SLUGS`` gaining ``"intern"`` — the FK
(``job_listings.enrichment_level -> job_levels.slug``) means the seed row and the
write-back allow-list MUST land in the same deploy or an incoming ``intern``
result is either soft-nulled (missing from LEVEL_SLUGS) or FK-rejected (missing
row).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b2e4a17c9f30'
down_revision: Union[str, None] = '288764e337a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Levels this migration adds on top of the 0fa33aca5bda seed
# (slug, label, rank, parent_slug). Read by the taxonomy-parity test, which
# unions this with the original LEVEL_SEED to stay in lock-step with the code
# constants. `intern` is standalone: parent_slug is None.
ADDED_LEVELS = [
    ("intern", "Intern", 0, None),
]

# New ranks for the pre-existing tiers (each shifted +1 so `intern` sorts first).
_RERANK = {
    "new_grad": 1,
    "entry": 2,
    "mid": 3,
    "senior": 4,
    "senior_plus": 5,
    "manager": 6,
}

# The original ranks (0fa33aca5bda seed), restored on downgrade.
_ORIGINAL_RANK = {
    "new_grad": 0,
    "entry": 1,
    "mid": 2,
    "senior": 3,
    "senior_plus": 4,
    "manager": 5,
}


def upgrade() -> None:
    bind = op.get_bind()
    insert = sa.text(
        "INSERT INTO job_levels (slug, label, rank, parent_slug) "
        "VALUES (:slug, :label, :rank, :parent) ON CONFLICT (slug) DO NOTHING"
    )
    for slug, label, rank, parent in ADDED_LEVELS:
        bind.execute(insert, {"slug": slug, "label": label, "rank": rank, "parent": parent})
    rerank = sa.text("UPDATE job_levels SET rank = :rank WHERE slug = :slug")
    for slug, rank in _RERANK.items():
        bind.execute(rerank, {"rank": rank, "slug": slug})


def downgrade() -> None:
    bind = op.get_bind()
    # Null any listings pinned to `intern` first so the FK doesn't block the
    # delete (rolling back the tier means those rows lose their intern label).
    bind.execute(sa.text(
        "UPDATE job_listings SET enrichment_level = NULL WHERE enrichment_level = 'intern'"
    ))
    restore = sa.text("UPDATE job_levels SET rank = :rank WHERE slug = :slug")
    for slug, rank in _ORIGINAL_RANK.items():
        bind.execute(restore, {"rank": rank, "slug": slug})
    bind.execute(sa.text("DELETE FROM job_levels WHERE slug = 'intern'"))
