#!/usr/bin/env python3
"""Print the single current Alembic head of the backend migration chain.

Each new company is seeded with a hand-written data migration in
``src/backend/alembic/versions/``. Every such migration MUST chain off the
current single head (``down_revision`` = this script's output). Chaining off the
wrong revision creates a *multi-head*, which crash-loops the backend on boot
(a documented incident in this repo).

The committed migrations mix single- AND double-quoted revision identifiers
(``revision: str = 'abc'`` *and* ``revision: str = "abc"``), and a *merge*
migration's ``down_revision`` is a **tuple of parents**
(``down_revision: Union[str, None] = ('a5cf3aed5f15', '9d2f7ae5c1b4')``). The
module is parsed with ``ast`` so every one of those shapes is read correctly —
a regex that assumed a single quoted value silently dropped both parents of
every merge migration and reported their consumed parents as extra heads.

Exit codes:
  0  exactly one head -> printed to stdout (the value to use as down_revision)
  1  zero or multiple heads -> message on stderr (do NOT add a company until fixed)
  2  versions directory not found
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

# .../.claude/skills/add-company/scripts/current_head.py
#   parents[0]=scripts  [1]=add-company  [2]=skills  [3]=.claude  [4]=repo root
REPO_ROOT = Path(__file__).resolve().parents[4]
VERSIONS_DIR = REPO_ROOT / "src" / "backend" / "alembic" / "versions"

def _module_assignments(text: str) -> dict[str, ast.expr]:
    """Map each top-level assigned name in a migration module to its value node.

    Covers both the annotated form the templates emit
    (``revision: str = 'abc'``) and a bare ``revision = 'abc'``.
    """
    assignments: dict[str, ast.expr] = {}
    for node in ast.parse(text).body:
        if isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.value is not None:
                assignments[node.target.id] = node.value
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments[target.id] = node.value
    return assignments


def _revision_ids(node: ast.expr | None) -> list[str]:
    """Every revision id held by a ``revision`` / ``down_revision`` value.

    A plain string yields one id. A **merge** migration's tuple (or list) yields
    *all* of its parents — miss these and each consumed parent looks like a head.
    ``down_revision = None`` (the base migration) correctly yields none.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.Tuple, ast.List)):
        return [
            elt.value
            for elt in node.elts
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
        ]
    return []


def find_heads(versions_dir: Path = VERSIONS_DIR) -> list[str]:
    """Return revisions that no migration references as its down_revision."""
    revisions: dict[str, str] = {}
    down_revisions: set[str] = set()
    for path in sorted(versions_dir.glob("*.py")):
        assignments = _module_assignments(path.read_text(encoding="utf-8"))
        ids = _revision_ids(assignments.get("revision"))
        if not ids:
            continue
        revisions[ids[0]] = path.name
        down_revisions.update(_revision_ids(assignments.get("down_revision")))
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
