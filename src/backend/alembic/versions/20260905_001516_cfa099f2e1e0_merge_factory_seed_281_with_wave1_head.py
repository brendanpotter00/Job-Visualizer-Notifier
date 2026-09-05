"""merge factory seed (#281) with wave1 head

Revision ID: cfa099f2e1e0
Revises: 48806539e400, 6f654e803393
Create Date: 2026-09-05 00:15:16.677206+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cfa099f2e1e0'
down_revision: Union[str, None] = ('48806539e400', '6f654e803393')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
