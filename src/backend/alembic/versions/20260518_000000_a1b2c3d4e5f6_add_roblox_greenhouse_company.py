"""add roblox greenhouse company

Revision ID: a1b2c3d4e5f6
Revises: e6cbbb3c2f17
Create Date: 2026-05-18 00:00:00.000000+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule in feedback_use_alembic_migrations.md). Adds the Roblox Greenhouse board
(board_token == 'roblox') to the companies table so the backend Procrastinate
worker picks it up alongside the rest of the Greenhouse boards.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'e6cbbb3c2f17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO companies (id, display_name, ats, board_token) "
            "VALUES (:id, :display_name, :ats, :board_token) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {
            'id': 'roblox',
            'display_name': 'Roblox',
            'ats': 'greenhouse',
            'board_token': 'roblox',
        },
    )


def downgrade() -> None:
    op.execute("DELETE FROM companies WHERE id = 'roblox'")
