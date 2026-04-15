#!/usr/bin/env python
"""
Database migration CLI.

Usage:
    python scripts/migrate.py status [--env local] [--db-url ...]
    python scripts/migrate.py up [--env local] [--db-url ...]
    python scripts/migrate.py down --to <version> [--env local] [--db-url ...]

Defaults:
    --env local
    --db-url postgresql://postgres:postgres@localhost:5432/jobscraper
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Add project root to path so "scripts" is importable as a package.
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from scripts.shared.database import get_connection
from scripts.shared.migrations.runner import (
    discover_migrations,
    get_applied_versions,
    migrate_down,
    migrate_up,
)

DEFAULT_DB_URL = "postgresql://postgres:postgres@localhost:5432/jobscraper"


def _connect(args):
    db_url = args.db_url or os.environ.get("DATABASE_URL") or DEFAULT_DB_URL
    return get_connection(db_url, args.env)


def cmd_status(args) -> int:
    conn = _connect(args)
    try:
        applied = get_applied_versions(conn, args.env)
        migrations = discover_migrations()
        print(f"Environment: {args.env}")
        print(f"Applied: {len(applied)} / {len(migrations)}")
        print()
        for m in migrations:
            mark = "[x]" if m.version in applied else "[ ]"
            print(f"  {mark} {m.label}")
    finally:
        conn.close()
    return 0


def cmd_up(args) -> int:
    conn = _connect(args)
    try:
        newly = migrate_up(conn, args.env)
        if newly:
            print(f"Applied {len(newly)} migration(s): {newly}")
        else:
            print("No pending migrations.")
    finally:
        conn.close()
    return 0


def cmd_down(args) -> int:
    conn = _connect(args)
    try:
        rolled = migrate_down(conn, args.env, target_version=args.to)
        if rolled:
            print(f"Rolled back {len(rolled)} migration(s): {rolled}")
        else:
            print("Nothing to roll back.")
    finally:
        conn.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    # Shared options live on a parent parser so --env and --db-url work whether
    # they appear before or after the subcommand name.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--env",
        default="local",
        help="Environment (local, qa, prod). Default: local",
    )
    common.add_argument(
        "--db-url",
        default=None,
        help=f"PostgreSQL URL. Default: $DATABASE_URL or {DEFAULT_DB_URL}",
    )

    parser = argparse.ArgumentParser(
        description="Database migration tool",
        parents=[common],
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show applied/pending migrations", parents=[common])
    sub.add_parser("up", help="Apply all pending migrations", parents=[common])

    down_parser = sub.add_parser(
        "down", help="Roll back migrations", parents=[common]
    )
    down_parser.add_argument(
        "--to",
        type=int,
        required=True,
        help="Target version (inclusive). Use 0 to roll back everything.",
    )

    return parser


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = build_parser().parse_args()
    commands = {"status": cmd_status, "up": cmd_up, "down": cmd_down}
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
