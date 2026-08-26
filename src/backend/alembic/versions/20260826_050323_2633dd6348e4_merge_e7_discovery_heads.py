"""merge e7 discovery heads

Revision ID: 2633dd6348e4
Revises: 1d2d6c17acfc, 9d2f7ae5c1b4
Create Date: 2026-08-26 05:03:23.522674+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2633dd6348e4'
down_revision: Union[str, None] = ('1d2d6c17acfc', '9d2f7ae5c1b4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
