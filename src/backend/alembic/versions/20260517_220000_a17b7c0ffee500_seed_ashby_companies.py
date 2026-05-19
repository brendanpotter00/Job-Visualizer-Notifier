"""seed ashby companies

Revision ID: a17b7c0ffee500
Revises: ebb479b7eed5
Create Date: 2026-05-17 22:00:00.000000+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). Alembic's --autogenerate diffs schema, not data — so the 46 Ashby
companies that previously lived in src/frontend/src/config/companies.ts
must be transcribed by hand into the per-row INSERT loop below.

Source of truth at the time of writing:
  src/frontend/src/config/companies.ts (Ashby block, lines ~280-410)

Most entries use the default Ashby boardToken == id. Overrides:
  distyl -> Distyl
  linear -> Linear
  gigaml -> GigaML
  braintrust -> Braintrust
  resolve-ai -> Resolve AI
  mintlify -> Mintlify
  roadrunner -> Roadrunner

Note: happyrobot.ai, pylon-labs, wispr-flow have explicit jobBoardName
overrides in companies.ts but their override values match their ids
(cosmetic overrides), so board_token == id for those.

Future Ashby adds should be made via a new migration, NOT by editing this
one — frozen migrations stay frozen.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a17b7c0ffee500'
down_revision: Union[str, None] = 'ebb479b7eed5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ASHBY_SEED_ROWS = [
    {'id': 'chalk',                      'display_name': 'Chalk',                        'ats': 'ashby', 'board_token': 'chalk'},
    {'id': 'notion',                     'display_name': 'Notion',                       'ats': 'ashby', 'board_token': 'notion'},
    {'id': 'ramp',                       'display_name': 'Ramp',                         'ats': 'ashby', 'board_token': 'ramp'},
    {'id': 'snowflake',                  'display_name': 'Snowflake',                    'ats': 'ashby', 'board_token': 'snowflake'},
    {'id': 'decagon',                    'display_name': 'Decagon',                      'ats': 'ashby', 'board_token': 'decagon'},
    {'id': 'distyl',                     'display_name': 'Distyl',                       'ats': 'ashby', 'board_token': 'Distyl'},
    {'id': 'elevenlabs',                 'display_name': 'ElevenLabs',                   'ats': 'ashby', 'board_token': 'elevenlabs'},
    {'id': 'flowengineering',            'display_name': 'Flow Engineering',             'ats': 'ashby', 'board_token': 'flowengineering'},
    {'id': 'baseten',                    'display_name': 'Baseten',                      'ats': 'ashby', 'board_token': 'baseten'},
    {'id': 'browserbase',                'display_name': 'Browserbase',                  'ats': 'ashby', 'board_token': 'browserbase'},
    {'id': 'base-power',                 'display_name': 'Base Power Company',           'ats': 'ashby', 'board_token': 'base-power'},
    {'id': 'clickup',                    'display_name': 'ClickUp',                      'ats': 'ashby', 'board_token': 'clickup'},
    {'id': 'apex-technology-inc',        'display_name': 'Apex Technology Inc',          'ats': 'ashby', 'board_token': 'apex-technology-inc'},
    {'id': 'light',                      'display_name': 'Light',                        'ats': 'ashby', 'board_token': 'light'},
    {'id': 'linear',                     'display_name': 'Linear',                       'ats': 'ashby', 'board_token': 'Linear'},
    {'id': 'siftstack',                  'display_name': 'Sift Stack',                   'ats': 'ashby', 'board_token': 'siftstack'},
    {'id': 'stainlessapi',               'display_name': 'Stainless API',                'ats': 'ashby', 'board_token': 'stainlessapi'},
    {'id': 'gigaml',                     'display_name': 'GigaML',                       'ats': 'ashby', 'board_token': 'GigaML'},
    {'id': 'sesame',                     'display_name': 'Sesame',                       'ats': 'ashby', 'board_token': 'sesame'},
    {'id': 'happyrobot.ai',              'display_name': 'Happyrobot',                   'ats': 'ashby', 'board_token': 'happyrobot.ai'},
    {'id': 'granola',                    'display_name': 'Granola',                      'ats': 'ashby', 'board_token': 'granola'},
    {'id': 'sunday',                     'display_name': 'Sunday',                       'ats': 'ashby', 'board_token': 'sunday'},
    {'id': 'openai',                     'display_name': 'OpenAI',                       'ats': 'ashby', 'board_token': 'openai'},
    {'id': 'perplexity',                 'display_name': 'Perplexity',                   'ats': 'ashby', 'board_token': 'perplexity'},
    {'id': 'pylon-labs',                 'display_name': 'Pylon',                        'ats': 'ashby', 'board_token': 'pylon-labs'},
    {'id': 'cohere',                     'display_name': 'Cohere',                       'ats': 'ashby', 'board_token': 'cohere'},
    {'id': 'traversal',                  'display_name': 'Traversal',                    'ats': 'ashby', 'board_token': 'traversal'},
    {'id': 'harvey',                     'display_name': 'Harvey',                       'ats': 'ashby', 'board_token': 'harvey'},
    {'id': 'sentry',                     'display_name': 'Sentry',                       'ats': 'ashby', 'board_token': 'sentry'},
    {'id': 'braintrust',                 'display_name': 'Braintrust',                   'ats': 'ashby', 'board_token': 'Braintrust'},
    {'id': 'eliseai',                    'display_name': 'EliseAI',                      'ats': 'ashby', 'board_token': 'eliseai'},
    {'id': 'resolve-ai',                 'display_name': 'Resolve AI',                   'ats': 'ashby', 'board_token': 'Resolve AI'},
    {'id': 'mintlify',                   'display_name': 'Mintlify',                     'ats': 'ashby', 'board_token': 'Mintlify'},
    {'id': 'roadrunner',                 'display_name': 'Roadrunner',                   'ats': 'ashby', 'board_token': 'Roadrunner'},
    {'id': 'supabase',                   'display_name': 'Supabase',                     'ats': 'ashby', 'board_token': 'supabase'},
    {'id': 'wispr-flow',                 'display_name': 'Wispr Flow',                   'ats': 'ashby', 'board_token': 'wispr-flow'},
    {'id': 'flint',                      'display_name': 'Flint',                        'ats': 'ashby', 'board_token': 'flint'},
    {'id': 'cursor',                     'display_name': 'Cursor',                       'ats': 'ashby', 'board_token': 'cursor'},
    {'id': 'modal',                      'display_name': 'Modal Labs',                   'ats': 'ashby', 'board_token': 'modal'},
    {'id': 'langchain',                  'display_name': 'LangChain',                    'ats': 'ashby', 'board_token': 'langchain'},
    {'id': 'cognition',                  'display_name': 'Cognition',                    'ats': 'ashby', 'board_token': 'cognition'},
    {'id': 'paraform',                   'display_name': 'Paraform',                     'ats': 'ashby', 'board_token': 'paraform'},
    {'id': 'judgmentlabs',               'display_name': 'Judgment Labs',                'ats': 'ashby', 'board_token': 'judgmentlabs'},
    {'id': 'generalintelligencecompany', 'display_name': 'General Intelligence Company', 'ats': 'ashby', 'board_token': 'generalintelligencecompany'},
    {'id': 'saronic',                    'display_name': 'Saronic',                      'ats': 'ashby', 'board_token': 'saronic'},
    {'id': 'plaid',                      'display_name': 'Plaid',                        'ats': 'ashby', 'board_token': 'plaid'},
]


def upgrade() -> None:
    # ON CONFLICT (id) DO NOTHING for idempotency: if any of these rows were
    # backfilled out-of-band (manual repair, partial prior run, prod hotfix),
    # the seed migration must NOT trip a PK-conflict and brick startup.
    # `enabled` is omitted from the INSERT; the column has server_default=true.
    bind = op.get_bind()
    insert_sql = sa.text(
        "INSERT INTO companies (id, display_name, ats, board_token) "
        "VALUES (:id, :display_name, :ats, :board_token) "
        "ON CONFLICT (id) DO NOTHING"
    )
    for row in ASHBY_SEED_ROWS:
        bind.execute(insert_sql, row)


def downgrade() -> None:
    # Scoped DELETE — must not touch Greenhouse rows or any out-of-band
    # rows with other ats values. Mirrors the Greenhouse seed's downgrade.
    op.execute("DELETE FROM companies WHERE ats = 'ashby'")
