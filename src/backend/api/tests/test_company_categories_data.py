"""Pure checks on the committed ``data/company_categories.json``.

The file is the one source of truth for the company categories: the backend
seeds its tables from it and the frontend imports it. These tests pin the
approved category set and the rules every edit (for example the add-company
skill's Step 4.5) must keep. No database.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from api.models import ENABLED_COMPANY_ID_PATTERN
from api.services.company_categories import DATA_PATH, load_company_categories

_PROFILES_PATH = Path(__file__).resolve().parents[1] / "data" / "company_profiles.json"
_COMPANY_ID_RE = re.compile(ENABLED_COMPANY_ID_PATTERN.rstrip("$") + r"\Z")

# The approved set, in display order. Changing it needs the owner's yes.
APPROVED_SLUGS = [
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

# Big Tech is the giants only, never a subsidiary of one.
BIG_TECH_SUBSIDIARIES = {"github", "slack", "twitch", "waymo", "zoox", "xai"}
BIG_TECH_MAX = 25
MIN_MEMBERS = 5


@pytest.fixture(scope="module")
def raw() -> dict:
    with open(DATA_PATH, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def categories():
    return load_company_categories()


@pytest.fixture(scope="module")
def profile_ids() -> set[str]:
    with open(_PROFILES_PATH, encoding="utf-8") as fh:
        return set(json.load(fh))


def test_the_file_loads_through_the_seed_validator(categories):
    assert len(categories) == len(APPROVED_SLUGS)


def test_exactly_the_approved_slugs_in_display_order(categories):
    assert [c["slug"] for c in categories] == APPROVED_SLUGS


def test_each_entry_has_exactly_the_four_keys(raw):
    for entry in raw["categories"]:
        assert set(entry) == {"slug", "label", "definition", "companyIds"}, entry["slug"]


def test_labels_are_unique_and_not_blank(categories):
    labels = [c["label"] for c in categories]
    assert all(label.strip() for label in labels)
    assert len(set(labels)) == len(labels)


def test_definitions_are_not_blank(categories):
    for category in categories:
        assert category["definition"].strip(), category["slug"]


def test_member_ids_are_valid_company_ids(categories):
    for category in categories:
        for company_id in category["company_ids"]:
            assert _COMPANY_ID_RE.match(company_id), (category["slug"], company_id)


def test_no_member_repeats_inside_a_category(categories):
    for category in categories:
        ids = category["company_ids"]
        assert len(set(ids)) == len(ids), category["slug"]


def test_every_category_has_at_least_five_members(categories):
    for category in categories:
        assert len(category["company_ids"]) >= MIN_MEMBERS, category["slug"]


def test_every_roster_company_is_in_at_least_one_category(categories, profile_ids):
    """Backend-side roster parity: company_profiles.json lists every curated id."""
    members = {cid for c in categories for cid in c["company_ids"]}
    missing = sorted(profile_ids - members)
    assert not missing, f"companies with no category: {missing}"


def test_every_member_is_a_roster_company(categories, profile_ids):
    members = {cid for c in categories for cid in c["company_ids"]}
    unknown = sorted(members - profile_ids)
    assert not unknown, f"category members not in company_profiles.json: {unknown}"


def test_a_company_can_be_in_several_categories(categories):
    """Overlap is allowed and expected (Google is Big Tech and AI Labs)."""
    in_big_tech = set(next(c for c in categories if c["slug"] == "big_tech")["company_ids"])
    in_ai_labs = set(next(c for c in categories if c["slug"] == "ai_labs")["company_ids"])
    assert "google" in in_big_tech & in_ai_labs


def test_big_tech_is_the_giants_only(categories):
    big_tech = next(c for c in categories if c["slug"] == "big_tech")["company_ids"]
    assert len(big_tech) <= BIG_TECH_MAX
    assert not BIG_TECH_SUBSIDIARIES & set(big_tech)
