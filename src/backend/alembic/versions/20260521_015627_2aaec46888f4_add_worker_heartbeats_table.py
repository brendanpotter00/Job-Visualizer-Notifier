"""add worker_heartbeats table

Revision ID: 2aaec46888f4
Revises: b9714f608e21
Create Date: 2026-05-21 01:56:27.263035+00:00

Adds the heartbeat tick table used by the */5 periodic heartbeat task and
the /health/worker liveness probe. Procrastinate's own runtime tables
(procrastinate_jobs / _events / _periodic_defers) and the existing
companies.provider_config column are intentionally NOT in the autogen diff
output — Procrastinate manages its own schema via ensure_schema_async at
startup, and provider_config was already added in revision b9714f608e21.
Both are filtered manually here, matching the pattern documented in
src/backend/CLAUDE.md § Schema migrations.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '2aaec46888f4'
down_revision: Union[str, None] = 'b9714f608e21'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'worker_heartbeats',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            'at',
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    # Drop any pre-rename leftover from an in-development run of this
    # migration where the index was originally named `_at_desc`. Prod
    # never saw the old name (migration was unmerged), so this is a
    # no-op there; on dev boxes that ran the old code it cleans up
    # the orphaned index so the names converge.
    op.execute("DROP INDEX IF EXISTS idx_worker_heartbeats_at_desc")
    op.create_index(
        'idx_worker_heartbeats_at',
        'worker_heartbeats',
        ['at'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('idx_worker_heartbeats_at', table_name='worker_heartbeats')
    op.drop_table('worker_heartbeats')
