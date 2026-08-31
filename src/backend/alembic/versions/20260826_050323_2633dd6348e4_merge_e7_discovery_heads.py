"""merge e7 discovery heads

Empty merge revision. It has no DDL and exists only to rejoin two heads.

Originally this merged `1d2d6c17acfc` (main) with `9d2f7ae5c1b4` (the Phase 3
recipe-budget line, which descends from Phase 1's `fb8467065dfc`). Phase 1 has
since grown its own merge revision, `a5cf3aed5f15`, because the same
`fb8467065dfc`/`1d2d6c17acfc` fork broke CI on PRs #243 and #247 — this branch
was simply the only one in the stack that had already worked around it.

So the `1d2d6c17acfc` parent is now `a5cf3aed5f15` instead. That revision already
merges `1d2d6c17acfc` in, so main is still an ancestor by exactly one more hop,
and this stays a genuine two-branch merge: neither `a5cf3aed5f15` nor
`9d2f7ae5c1b4` is an ancestor of the other. Repointing rather than adding a third
merge revision is what keeps this branch at ONE head — pointing at
`1d2d6c17acfc` directly would have left `a5cf3aed5f15` dangling as a second head
once Phase 1 merged up.

Only a parent pointer changed; the revision id is untouched, so a database
already stamped at or past `2633dd6348e4` needs nothing.

Revision ID: 2633dd6348e4
Revises: a5cf3aed5f15, 9d2f7ae5c1b4
Create Date: 2026-08-26 05:03:23.522674+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2633dd6348e4'
down_revision: Union[str, None] = ('a5cf3aed5f15', '9d2f7ae5c1b4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
