#!/usr/bin/env python3
"""Print the single current Alembic head of the backend migration chain.

Each new company is seeded with a hand-written data migration in
``src/backend/alembic/versions/``. Every such migration MUST chain off the
current single head (``down_revision`` = this script's output). Chaining off the
wrong revision creates a *multi-head*, which crash-loops the backend on boot
(a documented incident in this repo).

The committed migrations mix single- AND double-quoted revision identifiers
(``revision: str = 'abc'`` *and* ``revision: str = "abc"``), so both are parsed.

Exit codes:
  0  exactly one head -> printed to stdout (the value to use as down_revision)
  1  zero or multiple heads -> message on stderr (do NOT add a company until fixed)
  2  versions directory not found
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# .../.claude/skills/add-company/scripts/current_head.py
#   parents[0]=scripts  [1]=add-company  [2]=skills  [3]=.claude  [4]=repo root
REPO_ROOT = Path(__file__).resolve().parents[4]
VERSIONS_DIR = REPO_ROOT / "src" / "backend" / "alembic" / "versions"

# Match a top-of-file ``revision`` / ``down_revision`` assignment with either
# quote style. ``[^=]*`` skips the type annotation (e.g. ``: Union[str, None]``).
# A ``= None`` down_revision (the base migration) has no quotes -> no match,
# which is correct: it must not count as a parent.
_REVISION = re.compile(r"""^revision\s*[^=]*=\s*['"]([^'"]+)['"]""", re.M)
_DOWN_REVISION = re.compile(r"""^down_revision\s*[^=]*=\s*['"]([^'"]+)['"]""", re.M)


def find_heads(versions_dir: Path = VERSIONS_DIR) -> list[str]:
    """Return revisions that no migration references as its down_revision."""
    revisions: dict[str, str] = {}
    down_revisions: set[str] = set()
    for path in sorted(versions_dir.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        match = _REVISION.search(text)
        if not match:
            continue
        revisions[match.group(1)] = path.name
        down = _DOWN_REVISION.search(text)
        if down:
            down_revisions.add(down.group(1))
    return sorted(rev for rev in revisions if rev not in down_revisions)


def main() -> int:
    if not VERSIONS_DIR.is_dir():
        print(f"error: versions dir not found: {VERSIONS_DIR}", file=sys.stderr)
        return 2
    heads = find_heads()
    if len(heads) == 1:
        print(heads[0])
        return 0
    if not heads:
        print(
            f"error: no Alembic head found in {VERSIONS_DIR} "
            "(empty or unparseable).",
            file=sys.stderr,
        )
        return 1
    print(
        "error: multiple Alembic heads — the chain is branched and the backend "
        "will crash-loop on boot. Resolve the multi-head before adding a "
        "company. Heads:\n  " + "\n  ".join(heads),
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
