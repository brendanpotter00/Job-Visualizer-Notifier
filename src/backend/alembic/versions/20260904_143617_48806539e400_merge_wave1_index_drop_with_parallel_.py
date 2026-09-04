"""merge wave1 index drop with parallel seed

Revision ID: 48806539e400
Revises: a1f7c9d2e8b4, 9496d11cbd60
Create Date: 2026-09-04 14:36:17.562167+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '48806539e400'
down_revision: Union[str, None] = ('a1f7c9d2e8b4', '9496d11cbd60')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
