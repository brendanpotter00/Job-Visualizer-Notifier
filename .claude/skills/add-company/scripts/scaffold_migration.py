#!/usr/bin/env python3
"""Scaffold a hand-written Alembic data migration that seeds ONE company row.

Mirrors the committed single-company seed migrations (e.g. the ``reducto`` seed).
By default it chains off the current single head (see ``current_head.py``) so the
chain keeps exactly one head — a multi-head crash-loops the backend on boot.

Greenhouse / Ashby / Lever / Gem need only id/display_name/ats/board_token.
Eightfold / Workday additionally require a ``--provider-config`` JSON blob, written
as a ``CAST(... AS JSONB)`` insert:
  - eightfold: {"tenant_host": "<host on the SSRF allowlist>", "domain": "<domain>"}
  - workday:   {"base_url": "...", "tenant_slug": "...", "career_site_slug": "...",
                "default_facets": {...}}   (default_facets optional)

Examples:
  python scaffold_migration.py --id reducto --display-name Reducto \\
      --ats ashby --board-token reducto
  python scaffold_migration.py --id netflix --display-name Netflix \\
      --ats eightfold --board-token netflix \\
      --provider-config '{"tenant_host":"explore.jobs.netflix.net","domain":"netflix.com"}'
  python scaffold_migration.py --id demo --display-name Demo --ats greenhouse \\
      --board-token demo --dry-run        # preview only, writes nothing
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from current_head import VERSIONS_DIR, find_heads  # noqa: E402

VALID_ATS = ("greenhouse", "ashby", "lever", "gem", "eightfold", "workday")
PROVIDER_CONFIG_ATS = ("eightfold", "workday")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9.\-]*$")

_SIMPLE_TEMPLATE = '''"""seed {id} company

Revision ID: {rev}
Revises: {down}
Create Date: {created}

Hand-written data migration (the documented exception to the autogenerate-only
rule). Adds one company to the ``companies`` table:

- ``{id}`` ({ats}) — board_token ``{board_token}``

Chains off the current head ``{down}`` so the alembic chain keeps a single head.
Single-company seeds land after the frozen per-ATS seed migrations, so the
per-ATS counts asserted in ``test_migration_companies.py`` are unaffected.

Source of truth for the frontend entry:
  src/frontend/src/config/companies.ts (``{id}`` row)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '{rev}'
down_revision: Union[str, None] = '{down}'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    {{'id': '{id}', 'display_name': '{display_name}', 'ats': '{ats}', 'board_token': '{board_token}'}},
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
    op.execute("DELETE FROM companies WHERE id = '{id}'")
'''

_PROVIDER_TEMPLATE = '''"""seed {id} company

Revision ID: {rev}
Revises: {down}
Create Date: {created}

Hand-written data migration (the documented exception to the autogenerate-only
rule). Adds one {ats} company to the ``companies`` table with its
``provider_config`` JSONB blob:

- ``{id}`` ({ats}) — board_token ``{board_token}``

Chains off the current head ``{down}`` so the alembic chain keeps a single head.
Single-company seeds land after the frozen per-ATS seed migrations, so the
per-ATS counts asserted in ``test_migration_companies.py`` are unaffected.

Source of truth for the frontend entry:
  src/frontend/src/config/companies.ts (``{id}`` row)
"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '{rev}'
down_revision: Union[str, None] = '{down}'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    {{
        'id': '{id}',
        'display_name': '{display_name}',
        'ats': '{ats}',
        'board_token': '{board_token}',
        'provider_config': {provider_config!r},
    }},
]


def upgrade() -> None:
    bind = op.get_bind()
    insert_sql = sa.text(
        "INSERT INTO companies (id, display_name, ats, board_token, provider_config) "
        "VALUES (:id, :display_name, :ats, :board_token, CAST(:provider_config AS JSONB)) "
        "ON CONFLICT (id) DO NOTHING"
    )
    for row in SEED_ROWS:
        bind.execute(
            insert_sql,
            {{
                'id': row['id'],
                'display_name': row['display_name'],
                'ats': row['ats'],
                'board_token': row['board_token'],
                'provider_config': json.dumps(row['provider_config']),
            }},
        )


def downgrade() -> None:
    op.execute("DELETE FROM companies WHERE id = '{id}'")
'''


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--id", required=True, help="company slug / primary key (e.g. reducto)")
    p.add_argument("--display-name", required=True, help="display name (e.g. Reducto)")
    p.add_argument("--ats", required=True, choices=VALID_ATS, help="originating ATS")
    p.add_argument("--board-token", required=True, help="ATS board slug (verify live first)")
    p.add_argument("--provider-config", help="JSON blob (required for eightfold/workday)")
    p.add_argument("--down-revision", help="override parent revision (default: current single head)")
    p.add_argument("--dry-run", action="store_true", help="print the migration instead of writing it")
    return p.parse_args(argv)


def resolve_down_revision(override: str | None) -> str:
    if override:
        return override
    heads = find_heads()
    if len(heads) != 1:
        raise SystemExit(
            "error: cannot auto-resolve down_revision — expected exactly one "
            f"Alembic head, found {len(heads)}: {heads or '[]'}. Fix the chain "
            "(or pass --down-revision) before scaffolding."
        )
    return heads[0]


def build_migration(args: argparse.Namespace) -> tuple[str, str]:
    """Return (filename, file_contents)."""
    if not ID_RE.match(args.id):
        raise SystemExit(
            f"error: --id {args.id!r} must be a lowercase slug "
            "([a-z0-9] then [a-z0-9.-])."
        )

    provider_config = None
    if args.provider_config:
        try:
            provider_config = json.loads(args.provider_config)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"error: --provider-config is not valid JSON: {exc}")
        if not isinstance(provider_config, dict):
            raise SystemExit("error: --provider-config must be a JSON object.")
    if args.ats in PROVIDER_CONFIG_ATS and not provider_config:
        raise SystemExit(
            f"error: --ats {args.ats} requires --provider-config. "
            "eightfold: {\"tenant_host\":...,\"domain\":...}; "
            "workday: {\"base_url\":...,\"tenant_slug\":...,\"career_site_slug\":...}."
        )

    existing = list(VERSIONS_DIR.glob(f"*_seed_{args.id}_company.py"))
    if existing and not args.dry_run:
        raise SystemExit(
            f"error: a seed migration for {args.id!r} already exists: "
            f"{existing[0].name}. Refusing to create a duplicate."
        )

    down = resolve_down_revision(args.down_revision)
    rev = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc)
    created = now.isoformat(sep=" ", timespec="microseconds")
    filename = f"{now.strftime('%Y%m%d_%H%M%S')}_{rev}_seed_{args.id}_company.py"

    fields = dict(
        id=args.id,
        display_name=args.display_name,
        ats=args.ats,
        board_token=args.board_token,
        rev=rev,
        down=down,
        created=created,
    )
    if provider_config is not None:
        contents = _PROVIDER_TEMPLATE.format(provider_config=provider_config, **fields)
    else:
        contents = _SIMPLE_TEMPLATE.format(**fields)
    return filename, contents


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    filename, contents = build_migration(args)
    if args.dry_run:
        print(f"# --- DRY RUN: would write src/backend/alembic/versions/{filename} ---\n")
        print(contents)
        return 0
    out_path = VERSIONS_DIR / filename
    out_path.write_text(contents, encoding="utf-8")
    print(f"wrote {out_path.relative_to(VERSIONS_DIR.parents[3])}")
    print("next: re-run current_head.py to confirm a single head, then add the "
          "companies.ts entry, changelog.ts entry, and logos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
