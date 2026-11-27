"""The company-categories corpus: ONE source of truth for both tiers.

The API tier imports this as a plain top-level module (the `subcategories`
pattern; the section directory has a hyphen, so it is not a package). The UI
tier reads `ui/corpus.ts`, which shells out to `--json` below instead of
re-declaring anything.

WHY REAL COMPANY IDS
--------------------
Membership comes from `src/backend/api/data/company_categories.json`, which the
backend seeds into `company_category_members` on every boot. A fixture company
cannot be a member of anything, so the members here are REAL ids (Google,
Stripe, ...), and the one fixture company, `e2e-cc-decoy`, is the decoy: it is
in no company type at all. Every case can then assert an EXACT set.

THE ORACLE IS RESTATED, NOT READ
--------------------------------
:data:`COMPANY_TYPES` says which types each fixture company is in. It is written
out here rather than read from the JSON, so a case computes its expected set
independently of the data it is checking. CC-00 then asserts the restatement
agrees with the JSON and with the seeded tables, which is the one place the two
are allowed to meet.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CATEGORIES_JSON = REPO_ROOT / "src" / "backend" / "api" / "data" / "company_categories.json"

#: The approved set, in display order. Changing it is a product decision.
EXPECTED_SLUGS = [
    "big_tech",
    "ai_labs",
    "ai_startups",
    "yc_alumni",
    "unicorns",
    "breakout_startups",
    "hard_tech",
    "fintech",
    "dev_tools",
    "household_names",
]

SWE = "software_engineering"
PM = "product_manager"

#: Every seeded row shares one plain `source_id` (no `custom:` prefix, so the
#: rows take the public read path).
SOURCE_ID = "e2e_company_categories"

#: The one signed-in reader the UI tier uses (CC-U3 saves a default for it).
#: `seed.py` clears its saved filters on every reseed.
READER_SUB = "e2e|company-categories-reader"
READER_EMAIL = "e2e+company-categories-reader@jvn.test"

DECOY_COMPANY_ID = "e2e-cc-decoy"
DECOY_COMPANY_NAME = "E2E CC Decoy"

#: The company types each fixture company is in (restated; see module doc).
COMPANY_TYPES: dict[str, set[str]] = {
    "google": {"big_tech", "ai_labs", "household_names"},
    "apple": {"big_tech", "household_names"},
    "microsoft": {"big_tech", "household_names"},
    "netflix": {"big_tech", "household_names"},
    "anthropic": {"big_tech", "ai_labs"},
    "stripe": {"yc_alumni", "unicorns", "fintech"},
    "ramp": {"yc_alumni", "unicorns", "fintech"},
    DECOY_COMPANY_ID: set(),
}

#: Display names for the `companies` rows the seed makes sure exist.
COMPANY_NAMES: dict[str, str] = {
    "google": "Google",
    "apple": "Apple",
    "microsoft": "Microsoft",
    "netflix": "Netflix",
    "anthropic": "Anthropic",
    "stripe": "Stripe",
    "ramp": "Ramp",
    DECOY_COMPANY_ID: DECOY_COMPANY_NAME,
}


@dataclass(frozen=True)
class Job:
    key: str
    title: str
    company: str
    level: str
    category: str = SWE


#   key            company     cat  level   why it is here
#   -------------  ----------  ---  ------  ------------------------------------
#   CC-GOOGLE      google      SWE  senior  Big Tech + AI Labs member
#   CC-APPLE       apple       SWE  senior  Big Tech
#   CC-MICROSOFT   microsoft   SWE  mid     Big Tech; the LEVEL decoy for CC-03
#   CC-NETFLIX     netflix     SWE  senior  Big Tech
#   CC-ANTHROPIC   anthropic   SWE  senior  Big Tech + AI Labs
#   CC-GOOGLE-PM   google      PM   senior  Big Tech; the CATEGORY decoy for CC-03
#   CC-STRIPE      stripe      SWE  senior  Fintech, NOT Big Tech
#   CC-RAMP        ramp        SWE  mid     Fintech, NOT Big Tech
#   CC-DECOY       e2e-cc-...  SWE  senior  in NO company type: must never come
#                                           back under any type
#
# Six Big Tech rows, so a limit=2 walk is three full pages.
JOBS: list[Job] = [
    Job("CC-GOOGLE", "Software Engineer, Search", "google", "senior"),
    Job("CC-APPLE", "Software Engineer, Maps", "apple", "senior"),
    Job("CC-MICROSOFT", "Software Engineer II, Azure", "microsoft", "mid"),
    Job("CC-NETFLIX", "Senior Software Engineer, Streaming", "netflix", "senior"),
    Job("CC-ANTHROPIC", "Software Engineer, Inference", "anthropic", "senior"),
    Job("CC-GOOGLE-PM", "Product Manager, Search", "google", "senior", category=PM),
    Job("CC-STRIPE", "Software Engineer, Payments", "stripe", "senior"),
    Job("CC-RAMP", "Software Engineer, Cards", "ramp", "mid"),
    Job("CC-DECOY", "Software Engineer, Decoy Co", DECOY_COMPANY_ID, "senior"),
]
BY_KEY: dict[str, Job] = {j.key: j for j in JOBS}
ALL_KEYS: set[str] = set(BY_KEY)


def keys(*names: str) -> set[str]:
    """A set literal that fails loudly on a typo (a misspelled key would make
    the row silently "expected absent")."""
    missing = [n for n in names if n not in BY_KEY]
    if missing:
        raise KeyError(f"unknown fixture key(s): {missing}; known: {sorted(BY_KEY)}")
    return set(names)


def expected_for(
    company_types: list[str],
    *,
    category: list[str] | None = None,
    level: list[str] | None = None,
) -> set[str]:
    """The rows a search must return: ANY of the types (OR), AND category, AND
    level. Derived from the table above, never from the code under test."""
    wanted = set(company_types)
    out: set[str] = set()
    for job in JOBS:
        if wanted and not wanted & COMPANY_TYPES[job.company]:
            continue
        if category and job.category not in category:
            continue
        if level and job.level not in level:
            continue
        out.add(job.key)
    return out


def load_categories() -> list[dict]:
    """The committed JSON, the one source the backend seeds from."""
    return json.loads(CATEGORIES_JSON.read_text(encoding="utf-8"))["categories"]


def _as_json() -> str:
    cats = load_categories()
    return json.dumps(
        {
            "sourceId": SOURCE_ID,
            "decoyCompanyId": DECOY_COMPANY_ID,
            "reader": {"sub": READER_SUB, "email": READER_EMAIL},
            "categories": [{"slug": c["slug"], "label": c["label"]} for c in cats],
            "jobs": [
                {
                    "key": j.key,
                    "title": j.title,
                    "company": j.company,
                    "level": j.level,
                    "category": j.category,
                }
                for j in JOBS
            ],
            "expected": {
                "bigTech": sorted(expected_for(["big_tech"])),
                "aiLabsOrFintech": sorted(expected_for(["ai_labs", "fintech"])),
                "fintech": sorted(expected_for(["fintech"])),
                "all": sorted(ALL_KEYS),
            },
        },
        indent=2,
    )


if __name__ == "__main__":
    import sys

    if "--json" in sys.argv[1:]:
        print(_as_json())
    else:
        for _j in JOBS:
            print(f"  {_j.key:<14} {_j.company:<14} {_j.category:<22} {_j.level:<7} {sorted(COMPANY_TYPES[_j.company])}")
        print(f"big_tech -> {sorted(expected_for(['big_tech']))}")
