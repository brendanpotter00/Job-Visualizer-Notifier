"""merge e7 phase 1 schema with main

Empty merge revision. It has no DDL and exists only to rejoin two heads.

`fb8467065dfc` (E7 Phase 1 schema) was authored off `b4e1c9d77a02`. While this
branch was open, `main` advanced along the same parent —
`b4e1c9d77a02 -> c7a41b93e5d2 -> d8b52c04f6e3 -> 1d2d6c17acfc` — so merging
`main` in gave the script directory two heads and every `stamp("head")` call
raised `MultipleHeads`, which is what broke CI on this PR.

Merged rather than repointed on purpose. Repointing `fb8467065dfc` at
`1d2d6c17acfc` would rewrite a revision that dev databases are already stamped
past; a merge revision is additive, so it is safe wherever `fb8467065dfc` has
already been applied. Production is stamped `1d2d6c17acfc` and has never seen
`fb8467065dfc`, so from prod this upgrades as
`1d2d6c17acfc -> fb8467065dfc -> a5cf3aed5f15`.

Revision ID: a5cf3aed5f15
Revises: fb8467065dfc, 1d2d6c17acfc
Create Date: 2026-08-31 03:47:16.113212+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a5cf3aed5f15'
down_revision: Union[str, None] = ('fb8467065dfc', '1d2d6c17acfc')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
