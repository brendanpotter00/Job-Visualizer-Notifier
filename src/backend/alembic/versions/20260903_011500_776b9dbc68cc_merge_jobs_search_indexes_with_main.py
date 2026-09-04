"""merge jobs search indexes with main

Empty merge revision. It has no DDL and exists only to rejoin two heads.

`4b5d40dbc774` (the OPEN-category keyset index) was authored off
`1d2d6c17acfc`. While this branch was open, `main` advanced along that same
parent — E7 Phases 1-3, the freshness trigger, the worker-heartbeat lane and two
company seed batches, then the Meta scraper's seed — ending at
`e4c8a1f9d306`. (This revision is re-pointed at main's head on every rebase;
while the branch stays open, each new migration on main re-splits the graph.) Git merges the two sets without
complaint because they touch disjoint FILES, so nothing surfaces the collision
until boot: `api/migrations.py` runs `command.upgrade(cfg, "head")` (singular)
from the FastAPI lifespan, which raises `Multiple head revisions are present`.
That is not a connectivity error, so the retry wrapper re-raises it and the
container never becomes healthy.

Merged rather than repointed, for the same reason as `a5cf3aed5f15`: repointing
`4b5d40dbc774` at `d7b3c9e15af2` would rewrite a revision that dev databases on
this branch are already stamped past. A merge revision is additive, so it is safe
wherever `536c1cddcd28` has already been applied.

Production has never seen either of this branch's revisions, so from main's head
this upgrades as `e4c8a1f9d306 -> 4b5d40dbc774 -> 536c1cddcd28 -> 776b9dbc68cc`.

Revision ID: 776b9dbc68cc
Revises: 536c1cddcd28, e4c8a1f9d306
Create Date: 2026-09-03 01:15:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '776b9dbc68cc'
down_revision: Union[str, None] = ('536c1cddcd28', 'e4c8a1f9d306')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
