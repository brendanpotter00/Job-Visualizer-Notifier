"""add human_decision to job_enrichment

Revision ID: 74ef55837f12
Revises: 288764e337a4
Create Date: 2026-07-10 23:58:17.702891+00:00

Adds ``job_enrichment.human_decision`` — the human reviewer's verdict on a
needs-human row, distinct from the judge's (``judged`` / ``judge_passed``):

- ``NULL``              not yet reviewed by a human
- ``'corrected'``       labels were wrong; the admin fixed them (Correct dialog)
- ``'confirmed_correct'`` row was flagged but the admin validated the AI's
  proposal as-is (one-click Confirm)

Both decisions already stamp ``human_corrected_at`` (the row lock); this column
is what lets the golden-merge feed tell a fix from a validated raise — the
"raised but correct" signal for a future learning layer. Kept as free-form TEXT
(app-validated) to match the sibling ``enrichment_status`` / judge columns,
which are not DB enums.

Backfill: every existing human-resolved row (``human_corrected_at IS NOT NULL``)
predates this column and was, by definition, a correction — set it to
``'corrected'`` so history reads correctly.

Phantom ``procrastinate_*`` autogenerate ops stripped (those tables are owned by
Procrastinate's own schema, not ``db_models.py``, so autogenerate always wants
to drop them).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '74ef55837f12'
down_revision: Union[str, None] = '288764e337a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('job_enrichment', sa.Column('human_decision', sa.Text(), nullable=True))
    # Backfill: pre-existing human-resolved rows were all corrections.
    op.execute(
        "UPDATE job_enrichment SET human_decision = 'corrected' "
        "WHERE human_corrected_at IS NOT NULL AND human_decision IS NULL"
    )


def downgrade() -> None:
    op.drop_column('job_enrichment', 'human_decision')
