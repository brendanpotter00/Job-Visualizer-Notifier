"""add feedback table

Revision ID: b38c364cd0c4
Revises: c876c313e55c
Create Date: 2026-06-14 06:02:05.419714+00:00

Note: autogenerate also proposed dropping the ``procrastinate_*`` tables and
recreating them in downgrade. Those tables are owned by the Procrastinate
library's own schema (not our ``Base.metadata``), so they are intentionally
excluded here — this migration only creates the ``feedback`` table and its
indexes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b38c364cd0c4'
down_revision: Union[str, None] = 'c876c313e55c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'feedback',
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('user_id', sa.Text(), nullable=True),
        sa.Column('user_email', sa.Text(), nullable=True),
        sa.Column('display_name', sa.Text(), nullable=True),
        sa.Column(
            'created_at',
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_feedback_user_id', 'feedback', ['user_id'], unique=False)
    op.create_index(
        'idx_feedback_created_at', 'feedback', ['created_at'], unique=False
    )


def downgrade() -> None:
    op.drop_index('idx_feedback_created_at', table_name='feedback')
    op.drop_index('idx_feedback_user_id', table_name='feedback')
    op.drop_table('feedback')
