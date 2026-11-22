"""north star tracking: job_apply_clicks, user_visits.session_id, users.is_internal, metrics views

Revision ID: bcbc67dbd87e
Revises: 61434ebb0689
Create Date: 2026-11-22 20:10:36.861630+00:00

Schema for the North Star metrics in USER-METRICS.md:

* ``job_apply_clicks`` (new): one row per Apply press by a signed-in user.
* ``user_visits.session_id`` (new, nullable): the page load's PostHog session.
* ``users.is_internal`` (new, default false): accounts the views skip. Only
  the owner's account is flagged below; ``nonadmin@nonadmin.com`` is used to
  test in prod and deliberately stays counted.
* ``metrics`` schema with three read-only views (hand-added; Alembic does not
  autogenerate views). They hold the metric definitions so a read-only SQL
  client gets each number with one SELECT.

Every ALTER touches a different table, one column each, and both new columns
are nullable or carry a constant default, so neither rewrites its table.

The view SQL is idempotent (``IF NOT EXISTS`` / ``OR REPLACE``) because the
``metrics`` schema is database-wide: a test that upgrades inside a per-worker
schema must not trip over a ``metrics`` schema another run left behind.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bcbc67dbd87e'
down_revision: Union[str, None] = '61434ebb0689'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Owner's account only. nonadmin@nonadmin.com is NOT internal: it is used to
# test in prod, and the owner wants it counted.
INTERNAL_EMAILS = ("brendanpotter00@gmail.com",)

# user_visits starts on 2026-06-24, so cohorts start with signups on the 25th.
# users.created_at is legacy TEXT (ISO 8601), hence the casts. Weeks are
# Monday-start in UTC regardless of the session's TimeZone.
SIGNUP_RETENTION_SQL = """
CREATE OR REPLACE VIEW metrics.signup_retention AS
WITH cohort AS (
    SELECT u.id AS user_id, u.created_at::timestamptz AS signed_up_at
    FROM users u
    WHERE NOT u.is_internal
      AND u.created_at::timestamptz >= TIMESTAMPTZ '2026-06-25 00:00:00+00'
),
visits AS (
    SELECT c.user_id,
           v.visited_at,
           v.visited_at - c.signed_up_at AS since_signup,
           -- Gap since the previous visit; the signup itself anchors the first.
           v.visited_at - COALESCE(
               lag(v.visited_at) OVER (PARTITION BY v.user_id ORDER BY v.visited_at),
               c.signed_up_at
           ) AS gap_before
    FROM cohort c
    JOIN user_visits v ON v.user_id = c.user_id
),
per_user AS (
    SELECT user_id,
           bool_or(since_signup >= interval '3 days'
                   AND since_signup < interval '31 days') AS back_day3plus,
           bool_or(since_signup >= interval '7 days'
                   AND since_signup < interval '31 days') AS back_day7plus,
           -- Week n after signup = days [7n, 7n+7); weeks 1-8 = days [7, 63).
           count(DISTINCT floor(extract(epoch FROM since_signup) / 604800))
               FILTER (WHERE since_signup >= interval '7 days'
                         AND since_signup < interval '63 days') AS weeks_returned,
           bool_or(gap_before >= interval '14 days') AS came_back_after_14d,
           max(visited_at) AS last_visit_at
    FROM visits
    GROUP BY user_id
)
SELECT c.user_id,
       c.signed_up_at,
       date_trunc('week', c.signed_up_at AT TIME ZONE 'UTC')::date AS cohort_week,
       COALESCE(p.back_day3plus, false) AS back_day3plus,
       COALESCE(p.back_day7plus, false) AS back_day7plus,
       COALESCE(p.weeks_returned, 0)::integer AS weeks_returned,
       COALESCE(p.came_back_after_14d, false) AS came_back_after_14d,
       -- Denominator for came_back_after_14d: went 14+ days without a visit at
       -- some point, either between visits or since the last one (or signup).
       (COALESCE(p.came_back_after_14d, false)
        OR now() - COALESCE(p.last_visit_at, c.signed_up_at) >= interval '14 days'
       ) AS had_14d_gap
FROM cohort c
LEFT JOIN per_user p ON p.user_id = c.user_id
"""

# A cohort week is mature once its LAST signup is 31+ days old (week start +
# 7 + 31 days), and mature for weeks returned once week 8 of its last signup
# has ended (week start + 7 + 63 days). Immature rows are kept, flagged.
NORTH_STAR_WEEKLY_SQL = """
CREATE OR REPLACE VIEW metrics.north_star_weekly AS
SELECT cohort_week,
       count(*) AS signups,
       ((cohort_week::timestamp AT TIME ZONE 'UTC') + interval '38 days' <= now()) AS mature,
       ((cohort_week::timestamp AT TIME ZONE 'UTC') + interval '70 days' <= now())
           AS weeks_returned_mature,
       round(avg(back_day3plus::int), 4) AS back_day3plus,
       round(avg(back_day7plus::int), 4) AS back_day7plus,
       round(avg(weeks_returned), 4) AS avg_weeks_returned,
       round(count(*) FILTER (WHERE came_back_after_14d)::numeric
             / NULLIF(count(*) FILTER (WHERE had_14d_gap), 0), 4) AS came_back_after_14d
FROM metrics.signup_retention
GROUP BY cohort_week
"""

APPLY_CLICKS_WEEKLY_SQL = """
CREATE OR REPLACE VIEW metrics.apply_clicks_weekly AS
WITH clicks AS (
    SELECT date_trunc('week', c.clicked_at AT TIME ZONE 'UTC')::date AS week,
           count(*) AS clicks
    FROM job_apply_clicks c
    JOIN users u ON u.id = c.user_id
    WHERE NOT u.is_internal
    GROUP BY 1
),
sessions AS (
    SELECT date_trunc('week', v.visited_at AT TIME ZONE 'UTC')::date AS week,
           count(DISTINCT v.session_id) AS sessions
    FROM user_visits v
    JOIN users u ON u.id = v.user_id
    WHERE NOT u.is_internal
      AND v.session_id IS NOT NULL
    GROUP BY 1
)
SELECT week,
       COALESCE(c.clicks, 0) AS clicks,
       COALESCE(s.sessions, 0) AS sessions,
       round(COALESCE(c.clicks, 0)::numeric / NULLIF(s.sessions, 0), 4) AS clicks_per_session
FROM clicks c
FULL OUTER JOIN sessions s USING (week)
"""


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('job_apply_clicks',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('clicked_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('user_id', sa.Text(), nullable=False),
    sa.Column('session_id', sa.Text(), nullable=True),
    sa.Column('source_id', sa.Text(), nullable=False),
    sa.Column('job_id', sa.Text(), nullable=False),
    sa.Column('job_age_seconds', sa.Integer(), nullable=True),
    sa.Column('surface', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_job_apply_clicks_clicked_at', 'job_apply_clicks', ['clicked_at'], unique=False)
    op.create_index('idx_job_apply_clicks_user_id_clicked_at', 'job_apply_clicks', ['user_id', 'clicked_at'], unique=False)
    op.add_column('user_visits', sa.Column('session_id', sa.Text(), nullable=True))
    op.add_column('users', sa.Column('is_internal', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    # ### end Alembic commands ###
    op.execute(
        sa.text("UPDATE users SET is_internal = true WHERE email IN :emails").bindparams(
            sa.bindparam("emails", value=list(INTERNAL_EMAILS), expanding=True)
        )
    )
    op.execute("CREATE SCHEMA IF NOT EXISTS metrics")
    op.execute(SIGNUP_RETENTION_SQL)
    op.execute(NORTH_STAR_WEEKLY_SQL)
    op.execute(APPLY_CLICKS_WEEKLY_SQL)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS metrics.apply_clicks_weekly")
    op.execute("DROP VIEW IF EXISTS metrics.north_star_weekly")
    op.execute("DROP VIEW IF EXISTS metrics.signup_retention")
    # Not CASCADE: anything else someone put in `metrics` stops the downgrade
    # instead of being dropped with it.
    op.execute("DROP SCHEMA IF EXISTS metrics")
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('users', 'is_internal')
    op.drop_column('user_visits', 'session_id')
    op.drop_index('idx_job_apply_clicks_user_id_clicked_at', table_name='job_apply_clicks')
    op.drop_index('idx_job_apply_clicks_clicked_at', table_name='job_apply_clicks')
    op.drop_table('job_apply_clicks')
    # ### end Alembic commands ###
