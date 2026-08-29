"""add lane column to worker_heartbeats

The Procrastinate worker was split into two lanes — a bulk worker draining the
six public fan-outs plus `custom_ats_fetch`/`heartbeat`/`normalize`, and a
reserved interactive worker draining `custom_discovery` and the add-time first
harvest. Two workers means two things that can die independently.

`/health/worker` reads `MAX(worker_heartbeats.at)`. Without a lane tag, a dead
interactive worker is invisible: the bulk worker keeps writing ticks and the
probe stays green. That is the same shape as the failure this split came out
of — a worker that stopped draining while nothing noticed for 14 hours — so
the observability has to be per-lane or the second lane is a second silent
failure waiting to happen.

Backfill/default is 'bulk': every row written before this migration came from
the single pre-split worker, whose queues are now the bulk lane.

Revision ID: b4d17c2a9e51
Revises: 7a4c1e93b6d8
Create Date: 2026-08-26 19:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b4d17c2a9e51"
down_revision: Union[str, None] = "7a4c1e93b6d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default fills existing rows in the same statement, so the column
    # can be NOT NULL immediately without a separate backfill pass. The table
    # is pruned to 24h (~288 rows), so the rewrite is trivially cheap.
    op.add_column(
        "worker_heartbeats",
        sa.Column(
            "lane",
            sa.Text(),
            nullable=False,
            server_default="bulk",
        ),
    )
    # Composite (lane, at) so the per-lane `MAX(at) FILTER (WHERE lane = ...)`
    # in /health/worker is an index-only scan rather than a filter over the
    # whole table. The existing idx_worker_heartbeats_at stays: the cleanup
    # task's `at < now() - interval '24 hours'` has no lane predicate.
    op.create_index(
        "idx_worker_heartbeats_lane_at",
        "worker_heartbeats",
        ["lane", "at"],
    )


def downgrade() -> None:
    op.drop_index("idx_worker_heartbeats_lane_at", table_name="worker_heartbeats")
    op.drop_column("worker_heartbeats", "lane")
