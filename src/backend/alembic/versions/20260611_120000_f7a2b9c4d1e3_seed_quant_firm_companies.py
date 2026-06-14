"""seed quant firm companies

Revision ID: f7a2b9c4d1e3
Revises: c4f0a2d8b9e1
Create Date: 2026-06-11 12:00:00.000000+00:00

Hand-written data migration (the documented exception to the
autogenerate-only rule). Adds eight quantitative / proprietary trading
firms to the ``companies`` table — seven on Greenhouse, one on Lever:

- ``jumptrading``      (Greenhouse) — https://boards.greenhouse.io/jumptrading
- ``drw``              (Greenhouse) — https://job-boards.greenhouse.io/drweng
- ``akunacapital``     (Greenhouse) — https://job-boards.greenhouse.io/akunacapital
- ``optiver``          (Greenhouse) — https://job-boards.greenhouse.io/optiverprivate
- ``imc``              (Greenhouse) — https://job-boards.greenhouse.io/imc
- ``ctc``              (Greenhouse) — https://job-boards.greenhouse.io/chicagotrading
- ``hrt``              (Greenhouse) — https://boards.greenhouse.io/wehrtyou
- ``belvederetrading`` (Lever)      — https://jobs.lever.co/belvederetrading

``board_token`` carries the real ATS slug, which differs from ``id`` for
several firms (DRW=drweng, Optiver=optiverprivate, CTC=chicagotrading,
HRT=wehrtyou) — the same id/board_token split the ``sierra`` seed relies on.

Sits on top of the frozen per-ATS seeds (Greenhouse ``939331c99a23``, Lever
``b29cd1eef0aab1``); the per-ATS counts asserted in
``test_migration_companies.py`` are unaffected because that test stops at
``WORKDAY_SEED_REV``, before this revision (mirrors the exa/roblox seed).

Chains off ``c4f0a2d8b9e1`` (the sierra seed) — the current single head — so
the alembic chain keeps a single head when this PR merges into main.

Source of truth for the frontend entries:
  src/frontend/src/config/companies.ts (quant trading firm rows)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f7a2b9c4d1e3'
down_revision: Union[str, None] = 'c4f0a2d8b9e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    {'id': 'jumptrading',      'display_name': 'Jump Trading',          'ats': 'greenhouse', 'board_token': 'jumptrading'},
    {'id': 'drw',              'display_name': 'DRW',                   'ats': 'greenhouse', 'board_token': 'drweng'},
    {'id': 'akunacapital',     'display_name': 'Akuna Capital',        'ats': 'greenhouse', 'board_token': 'akunacapital'},
    {'id': 'optiver',          'display_name': 'Optiver',              'ats': 'greenhouse', 'board_token': 'optiverprivate'},
    {'id': 'imc',              'display_name': 'IMC Trading',          'ats': 'greenhouse', 'board_token': 'imc'},
    {'id': 'ctc',              'display_name': 'Chicago Trading (CTC)', 'ats': 'greenhouse', 'board_token': 'chicagotrading'},
    {'id': 'hrt',              'display_name': 'Hudson River Trading', 'ats': 'greenhouse', 'board_token': 'wehrtyou'},
    {'id': 'belvederetrading', 'display_name': 'Belvedere Trading',    'ats': 'lever',      'board_token': 'belvederetrading'},
]


def upgrade() -> None:
    bind = op.get_bind()
    insert_sql = sa.text(
        "INSERT INTO companies (id, display_name, ats, board_token) "
        "VALUES (:id, :display_name, :ats, :board_token) "
        "ON CONFLICT (id) DO NOTHING"
    )
    for row in SEED_ROWS:
        bind.execute(insert_sql, row)


def downgrade() -> None:
    op.execute(
        "DELETE FROM companies WHERE id IN ("
        "'jumptrading', 'drw', 'akunacapital', 'optiver', "
        "'imc', 'ctc', 'hrt', 'belvederetrading')"
    )
