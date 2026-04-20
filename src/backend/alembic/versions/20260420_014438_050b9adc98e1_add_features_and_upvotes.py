"""add features and upvotes

Revision ID: 050b9adc98e1
Revises: 91337142414f
Create Date: 2026-04-20 01:44:38.408735+00:00

Table names follow the repo-wide ``{name}_{env}`` convention: the
``SCRAPER_ENVIRONMENT`` setting drives the suffix so one revision covers
``features_local`` / ``features_prod`` / ``features_test_<hex>`` (see
``db_models.py`` ``_ENV`` and the baseline revision for the same pattern).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from api.config import settings


# revision identifiers, used by Alembic.
revision: str = '050b9adc98e1'
down_revision: Union[str, None] = '91337142414f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ENV = settings.scraper_environment
_FEATURES = f"features_{_ENV}"
_UPVOTES = f"feature_upvotes_{_ENV}"
_USERS = f"users_{_ENV}"


def upgrade() -> None:
    op.create_table(
        _FEATURES,
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        _UPVOTES,
        sa.Column('feature_id', sa.Text(), nullable=False),
        sa.Column('user_id', sa.Text(), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['feature_id'], [f'{_FEATURES}.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], [f'{_USERS}.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('feature_id', 'user_id'),
    )
    op.create_index(f'idx_feature_upvotes_{_ENV}_feature_id', _UPVOTES, ['feature_id'], unique=False)
    op.create_index(f'idx_feature_upvotes_{_ENV}_user_id', _UPVOTES, ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(f'idx_feature_upvotes_{_ENV}_user_id', table_name=_UPVOTES)
    op.drop_index(f'idx_feature_upvotes_{_ENV}_feature_id', table_name=_UPVOTES)
    op.drop_table(_UPVOTES)
    op.drop_table(_FEATURES)
