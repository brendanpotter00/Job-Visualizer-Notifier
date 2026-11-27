"""Tests for the idempotent company-categories seed (``services.company_categories``).

The seed runs on every boot and makes ``company_categories`` +
``company_category_members`` match the committed JSON. What must hold:

- an empty DB gets every row, and a second run changes nothing;
- edits to the file (removed member, removed category, new label/definition,
  reordering) all apply;
- bad data raises BEFORE any write;
- an id with no ``companies`` row is still seeded, with a WARN.
"""

from __future__ import annotations

import copy
import json
import logging

import pytest

from api.services import company_categories as cc
from api.services.company_categories import (
    CompanyCategoryDef,
    list_company_category_facets,
    load_company_categories,
    parse_company_categories,
    resolve_company_category_members,
    seed_company_categories,
)

from .conftest import _insert_company

FIXTURE: list[CompanyCategoryDef] = [
    {
        "slug": "big_tech",
        "label": "Big Tech",
        "definition": "The giants.",
        "company_ids": ["google", "apple", "stripe"],
    },
    {
        "slug": "fintech",
        "label": "Fintech & Trading",
        "definition": "Money software.",
        "company_ids": ["stripe", "ramp"],
    },
    {
        "slug": "dev_tools",
        "label": "Dev Tools & Infra",
        "definition": "What engineers use.",
        "company_ids": ["github"],
    },
]


def _fixture() -> list[CompanyCategoryDef]:
    return copy.deepcopy(FIXTURE)


def _seed_companies(conn, ids=("google", "apple", "stripe", "ramp", "github")) -> None:
    for company_id in ids:
        _insert_company(conn, company_id)


def _categories(conn) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT slug, label, definition, sort_order FROM company_categories"
        " ORDER BY sort_order"
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.commit()
    return rows


def _members(conn) -> list[tuple[str, str, int]]:
    cur = conn.cursor()
    cur.execute(
        "SELECT category_slug, company_id, position FROM company_category_members"
        " ORDER BY category_slug, position"
    )
    rows = [(r["category_slug"], r["company_id"], r["position"]) for r in cur.fetchall()]
    conn.commit()
    return rows


def test_seeds_empty_tables(db_conn):
    _seed_companies(db_conn)

    summary = seed_company_categories(db_conn, _fixture())

    assert summary["categories_inserted"] == 3
    assert summary["members_inserted"] == 6
    assert summary["unmatched"] == []
    assert _categories(db_conn) == [
        {"slug": "big_tech", "label": "Big Tech", "definition": "The giants.", "sort_order": 0},
        {"slug": "fintech", "label": "Fintech & Trading", "definition": "Money software.", "sort_order": 1},
        {"slug": "dev_tools", "label": "Dev Tools & Infra", "definition": "What engineers use.", "sort_order": 2},
    ]
    assert _members(db_conn) == [
        ("big_tech", "google", 0),
        ("big_tech", "apple", 1),
        ("big_tech", "stripe", 2),
        ("dev_tools", "github", 0),
        ("fintech", "stripe", 0),
        ("fintech", "ramp", 1),
    ]


def test_a_second_run_changes_nothing(db_conn):
    _seed_companies(db_conn)
    seed_company_categories(db_conn, _fixture())
    before = (_categories(db_conn), _members(db_conn))

    summary = seed_company_categories(db_conn, _fixture())

    assert summary == {
        "categories_inserted": 0,
        "categories_updated": 0,
        "categories_deleted": 0,
        "members_inserted": 0,
        "members_updated": 0,
        "members_deleted": 0,
        "unmatched": [],
    }
    assert (_categories(db_conn), _members(db_conn)) == before


def test_a_removed_member_is_deleted(db_conn):
    _seed_companies(db_conn)
    seed_company_categories(db_conn, _fixture())

    edited = _fixture()
    edited[0]["company_ids"] = ["google", "stripe"]  # apple leaves Big Tech
    summary = seed_company_categories(db_conn, edited)

    assert summary["members_deleted"] == 1
    # stripe moved from index 2 to index 1.
    assert summary["members_updated"] == 1
    assert [m for m in _members(db_conn) if m[0] == "big_tech"] == [
        ("big_tech", "google", 0),
        ("big_tech", "stripe", 1),
    ]


def test_a_removed_category_is_deleted_with_its_members(db_conn):
    _seed_companies(db_conn)
    seed_company_categories(db_conn, _fixture())

    summary = seed_company_categories(db_conn, _fixture()[:2])  # drop dev_tools

    assert summary["categories_deleted"] == 1
    assert [c["slug"] for c in _categories(db_conn)] == ["big_tech", "fintech"]
    assert not [m for m in _members(db_conn) if m[0] == "dev_tools"]


def test_label_and_definition_edits_apply(db_conn):
    _seed_companies(db_conn)
    seed_company_categories(db_conn, _fixture())

    edited = _fixture()
    edited[1]["label"] = "Fintech"
    edited[1]["definition"] = "Payments and trading."
    summary = seed_company_categories(db_conn, edited)

    assert summary["categories_updated"] == 1
    fintech = next(c for c in _categories(db_conn) if c["slug"] == "fintech")
    assert fintech["label"] == "Fintech"
    assert fintech["definition"] == "Payments and trading."


def test_sort_order_and_position_follow_the_file(db_conn):
    _seed_companies(db_conn)
    seed_company_categories(db_conn, _fixture())

    reordered = list(reversed(_fixture()))
    reordered[2]["company_ids"] = ["stripe", "apple", "google"]  # big_tech, reversed
    seed_company_categories(db_conn, reordered)

    assert [(c["slug"], c["sort_order"]) for c in _categories(db_conn)] == [
        ("dev_tools", 0),
        ("fintech", 1),
        ("big_tech", 2),
    ]
    assert [m for m in _members(db_conn) if m[0] == "big_tech"] == [
        ("big_tech", "stripe", 0),
        ("big_tech", "apple", 1),
        ("big_tech", "google", 2),
    ]


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda c: c[0].update(slug="Big-Tech"), "bad slug"),
        (lambda c: c[1].update(slug="big_tech"), "duplicate slug"),
        (lambda c: c[1].update(label="Big Tech"), "duplicate label"),
        (lambda c: c[0].update(label="  "), "empty label"),
        (lambda c: c[0].update(definition=""), "empty definition"),
        (lambda c: c[0]["company_ids"].append("../etc"), "bad company id"),
        (lambda c: c[0]["company_ids"].append("google"), "twice"),
        (lambda c: c.clear(), "no categories"),
    ],
)
def test_malformed_data_raises_before_any_write(db_conn, mutate, message):
    _seed_companies(db_conn)
    seed_company_categories(db_conn, _fixture())
    before = (_categories(db_conn), _members(db_conn))

    bad = _fixture()
    mutate(bad)
    with pytest.raises(ValueError, match=message):
        seed_company_categories(db_conn, bad)

    assert (_categories(db_conn), _members(db_conn)) == before


def test_parse_rejects_a_wrong_shape():
    with pytest.raises(ValueError):
        parse_company_categories([])
    with pytest.raises(ValueError):
        parse_company_categories({"categories": [{"slug": "a", "label": "A"}]})
    with pytest.raises(ValueError):
        parse_company_categories(
            {"categories": [{"slug": "a", "label": "A", "definition": "d", "companyIds": [1]}]}
        )


def test_a_malformed_file_raises_on_load(tmp_path):
    path = tmp_path / "company_categories.json"
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_company_categories(path)


def test_an_id_with_no_companies_row_is_seeded_and_warned(db_conn, caplog):
    _seed_companies(db_conn, ids=("google", "apple", "stripe", "ramp"))  # no github

    with caplog.at_level(logging.WARNING, logger=cc.__name__):
        summary = seed_company_categories(db_conn, _fixture())

    assert summary["unmatched"] == ["github"]
    assert ("dev_tools", "github", 0) in _members(db_conn)
    assert any("github" in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)


def test_always_logs_one_info_line(db_conn, caplog):
    _seed_companies(db_conn)
    seed_company_categories(db_conn, _fixture())
    caplog.clear()

    # A second run changes nothing and still logs its line.
    with caplog.at_level(logging.INFO, logger=cc.__name__):
        seed_company_categories(db_conn, _fixture())

    lines = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(lines) == 1
    assert "seed_company_categories completed" in lines[0].getMessage()


def test_the_committed_file_seeds_every_membership(db_conn):
    """The real file: 10 categories, one row per (category, company)."""
    expected = load_company_categories()

    seed_company_categories(db_conn)

    assert [c["slug"] for c in _categories(db_conn)] == [c["slug"] for c in expected]
    assert len(_members(db_conn)) == sum(len(c["company_ids"]) for c in expected)


def test_facets_and_member_resolution_read_the_seeded_rows(db_conn):
    _seed_companies(db_conn)
    seed_company_categories(db_conn, _fixture())

    assert list_company_category_facets(db_conn) == [
        {"slug": "big_tech", "label": "Big Tech", "sort_order": 0, "parent_slug": None},
        {"slug": "fintech", "label": "Fintech & Trading", "sort_order": 1, "parent_slug": None},
        {"slug": "dev_tools", "label": "Dev Tools & Infra", "sort_order": 2, "parent_slug": None},
    ]
    # Union, distinct, sorted. An unknown slug adds nothing.
    assert resolve_company_category_members(db_conn, ["big_tech", "fintech", "nope"]) == [
        "apple", "google", "ramp", "stripe",
    ]
    assert resolve_company_category_members(db_conn, ["nope"]) == []
