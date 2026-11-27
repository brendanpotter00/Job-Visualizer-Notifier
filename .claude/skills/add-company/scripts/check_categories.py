#!/usr/bin/env python3
"""Check company categories in ``src/backend/api/data/company_categories.json``.

Usage:
  check_categories.py <id> [<id> ...]   print each id's categories; fail if one has none
  check_categories.py                   check the whole roster against company_profiles.json

Stdlib only, so plain ``python3`` works (no venv). The tests are the real gate
(``companyCategories.test.ts`` and ``test_company_categories_data.py``); this
is the quick check while you edit.

Exit codes:
  0  every id checked is in at least one category (and, with no args, the
     roster and the categories match both ways)
  1  an id has no category, or the roster and the categories disagree
  2  a data file is missing or unreadable
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# .../.claude/skills/add-company/scripts/check_categories.py
#   parents[0]=scripts  [1]=add-company  [2]=skills  [3]=.claude  [4]=repo root
REPO_ROOT = Path(__file__).resolve().parents[4]
DATA_DIR = REPO_ROOT / "src" / "backend" / "api" / "data"
CATEGORIES_PATH = DATA_DIR / "company_categories.json"
PROFILES_PATH = DATA_DIR / "company_profiles.json"


def _load(path: Path) -> object:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
        sys.exit(2)


def _memberships() -> dict:
    """Map company id -> list of category labels, in file order."""
    data = _load(CATEGORIES_PATH)
    result: dict = {}
    for category in data["categories"]:
        for company_id in category["companyIds"]:
            result.setdefault(company_id, []).append(category["label"])
    return result


def _check_ids(ids: list) -> int:
    memberships = _memberships()
    failed = False
    for company_id in ids:
        labels = memberships.get(company_id, [])
        if labels:
            print(f"{company_id}: {', '.join(labels)}")
        else:
            print(f"{company_id}: NO CATEGORY (add it to 1+ companyIds lists)")
            failed = True
    return 1 if failed else 0


def _check_roster() -> int:
    memberships = _memberships()
    profiles = set(_load(PROFILES_PATH))
    members = set(memberships)
    missing = sorted(profiles - members)
    unknown = sorted(members - profiles)
    for company_id in missing:
        print(f"{company_id}: in company_profiles.json but in no category")
    for company_id in unknown:
        print(f"{company_id}: in a category but not in company_profiles.json")
    if missing or unknown:
        return 1
    print(f"ok: all {len(profiles)} companies have 1+ category")
    return 0


def main(argv: list) -> int:
    if argv:
        return _check_ids(argv)
    return _check_roster()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
