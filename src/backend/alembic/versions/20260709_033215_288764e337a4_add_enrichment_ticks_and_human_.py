"""add enrichment_ticks and human-correction columns

Revision ID: 288764e337a4
Revises: 0fa33aca5bda
Create Date: 2026-07-09 03:32:15.164151+00:00

Additive follow-up to the enrichment pull integration (0fa33aca5bda):

- ``enrichment_ticks``: one row per enricher tick, pushed by the laptop via the
  new ``POST /api/internal/enrichment/metrics`` (idempotent on ``tick_uuid``).
  Brand-new table — no rewrite of any existing relation.
- ``job_enrichment.human_corrected_at`` / ``human_corrected_by``: provenance for
  admin needs-human corrections. Nullable, no default — catalog-only ALTER, no
  table rewrite (same rule as 0fa33aca5bda; see the 2026-04-18 volume-fill
  incident).

Phantom ``procrastinate_*`` autogenerate ops stripped (those tables are owned
by Procrastinate's own schema setup, not our models — same trim as
0fa33aca5bda).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '288764e337a4'
down_revision: Union[str, None] = '0fa33aca5bda'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('enrichment_ticks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tick_uuid', sa.Text(), nullable=False),
    sa.Column('started_at', sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('ended_at', sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('claimed', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('cleaned', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('classified', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('judged', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('corrected', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('needs_human', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('sent', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('errors', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('nulled_facets', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('duration_s', sa.Float(), nullable=True),
    sa.Column('taxonomy_version', sa.Text(), nullable=True),
    sa.Column('knobs', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('stage_timings', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('heartbeat_age_s', sa.Float(), nullable=True),
    sa.Column('scorecard', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('enricher_version', sa.Text(), nullable=True),
    sa.Column('drift_suspected', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('received_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tick_uuid', name='uq_enrichment_ticks_tick_uuid')
    )
    op.create_index('idx_enrichment_ticks_started_at', 'enrichment_ticks', ['started_at'], unique=False)
    # Single combined ALTER: both columns nullable/no-default => catalog-only.
    op.add_column('job_enrichment', sa.Column('human_corrected_at', sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column('job_enrichment', sa.Column('human_corrected_by', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('job_enrichment', 'human_corrected_by')
    op.drop_column('job_enrichment', 'human_corrected_at')
    op.drop_index('idx_enrichment_ticks_started_at', table_name='enrichment_ticks')
    op.drop_table('enrichment_ticks')
