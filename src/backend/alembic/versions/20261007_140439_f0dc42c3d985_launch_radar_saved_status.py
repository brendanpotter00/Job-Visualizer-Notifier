"""launch radar saved status

Revision ID: f0dc42c3d985
Revises: a67d3d0286a2
Create Date: 2026-10-07 14:04:39.099161+00:00

Adds ``'saved'`` to ``ck_launch_radar_cards_status``: the admin dashboard's
third tab (New / Saved / Archived). Lifecycle: new -> saved (Save), saved ->
new (Unsave), new or saved -> archived (Archive), archived -> new (Restore),
archived -> deleted (the tombstone).

Written by hand (in a revision made with ``alembic revision -m``) because
autogenerate does not compare CHECK constraints: a changed CHECK is invisible
to ``alembic revision --autogenerate`` and to ``alembic check``. The constraint
keeps its name, so the model in ``db_models.py`` and this file must list the
same statuses (``api/tests/test_db_models.py`` pins both).

Postgres cannot alter a CHECK in place, so it is dropped and re-created inside
the migration's transaction. ``launch_radar_cards`` is small (one row per
company the loop ever posted), so the re-validation scan is cheap and nothing
is rewritten.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f0dc42c3d985'
down_revision: Union[str, None] = 'a67d3d0286a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "launch_radar_cards"
_CONSTRAINT = "ck_launch_radar_cards_status"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(
        _CONSTRAINT, _TABLE, "status IN ('new','saved','archived','deleted')"
    )


def downgrade() -> None:
    # The old constraint has no 'saved', so a saved card goes back to the New
    # tab first (Unsave), or re-creating the CHECK would fail on that row.
    op.execute(
        "UPDATE launch_radar_cards SET status = 'new', updated_at = now() "
        "WHERE status = 'saved'"
    )
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(
        _CONSTRAINT, _TABLE, "status IN ('new','archived','deleted')"
    )
