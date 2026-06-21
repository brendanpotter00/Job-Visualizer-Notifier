"""add user_saved_filters and user_keyword_lists

Revision ID: 6df9297dcc67
Revises: e015cd4d01a8
Create Date: 2026-06-21 05:23:49.560539+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '6df9297dcc67'
down_revision: Union[str, None] = 'e015cd4d01a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NOTE: autogenerate also reported drift for the library-owned
    # `procrastinate_*` tables (not in Base.metadata) and the already-migrated
    # `feedback` table (the local dev DB was in a partial state). Those false
    # positives were removed; this revision only adds the two new tables.
    op.create_table(
        'user_keyword_lists',
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('user_id', sa.Text(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('tags', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('position', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_user_keyword_lists_user_id', 'user_keyword_lists', ['user_id'], unique=False)
    op.create_index(
        'uq_user_keyword_lists_user_name',
        'user_keyword_lists',
        ['user_id', sa.literal_column('lower(name)')],
        unique=True,
    )
    op.create_table(
        'user_saved_filters',
        sa.Column('user_id', sa.Text(), nullable=False),
        sa.Column('recent_time_window', sa.Text(), server_default=sa.text("'3h'"), nullable=False),
        sa.Column('trend_time_window', sa.Text(), server_default=sa.text("'7d'"), nullable=False),
        sa.Column('locations', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('recent_active_keyword_list_id', sa.Text(), nullable=True),
        sa.Column('trend_active_keyword_list_id', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id'),
    )


def downgrade() -> None:
    op.drop_table('user_saved_filters')
    op.drop_index('uq_user_keyword_lists_user_name', table_name='user_keyword_lists')
    op.drop_index('idx_user_keyword_lists_user_id', table_name='user_keyword_lists')
    op.drop_table('user_keyword_lists')
