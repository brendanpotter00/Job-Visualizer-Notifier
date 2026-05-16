"""add companies table

Revision ID: 438ad0658e53
Revises: f4008c4fb790
Create Date: 2026-05-16 00:14:26.469955+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '438ad0658e53'
down_revision: Union[str, None] = 'f4008c4fb790'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'companies',
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('display_name', sa.Text(), nullable=False),
        sa.Column('ats', sa.Text(), nullable=False),
        sa.Column('board_token', sa.Text(), nullable=False),
        sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_companies_ats_enabled', 'companies', ['ats', 'enabled'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_companies_ats_enabled', table_name='companies')
    op.drop_table('companies')
