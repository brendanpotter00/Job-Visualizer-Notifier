"""add features and upvotes

Revision ID: 050b9adc98e1
Revises: 91337142414f
Create Date: 2026-04-20 01:44:38.408735+00:00

Originally shipped with env-suffixed table names (``features_{env}`` /
``feature_upvotes_{env}``) driven by ``SCRAPER_ENVIRONMENT``. After the
envAgnosticTables cutover (revisions ``e1974f8f8eee`` and
``f4008c4fb790``) the suffix scheme is retired, so this revision now
creates the bare names directly for any fresh DB. Prod already applied
this revision under the old scheme; the env-suffixed names it produced
there are converted to the bare names below by ``e1974f8f8eee``.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '050b9adc98e1'
down_revision: Union[str, None] = '91337142414f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'features',
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'feature_upvotes',
        sa.Column('feature_id', sa.Text(), nullable=False),
        sa.Column('user_id', sa.Text(), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['feature_id'], ['features.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('feature_id', 'user_id'),
    )
    op.create_index('idx_feature_upvotes_feature_id', 'feature_upvotes', ['feature_id'], unique=False)
    op.create_index('idx_feature_upvotes_user_id', 'feature_upvotes', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_feature_upvotes_user_id', table_name='feature_upvotes')
    op.drop_index('idx_feature_upvotes_feature_id', table_name='feature_upvotes')
    op.drop_table('feature_upvotes')
    op.drop_table('features')
