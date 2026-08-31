"""Unit tests for the ``custom()`` source_id helper + id generator (E7 §2.1)."""

from __future__ import annotations

import re

import pytest

from scripts.shared.constants import custom, new_custom_company_id


@pytest.mark.parametrize(
    "company_id, expected",
    [
        ("u-abc1234567", "custom:u-abc1234567"),
        ("duolingo", "custom:duolingo"),
        ("happyrobot.ai", "custom:happyrobot.ai"),
        ("a", "custom:a"),
        ("0", "custom:0"),
    ],
)
def test_custom_valid(company_id: str, expected: str) -> None:
    assert custom(company_id) == expected


@pytest.mark.parametrize(
    "bad",
    [
        "",              # empty
        "BadUpper",      # uppercase not allowed
        "has space",     # space
        ".leading",      # leading dot
        "-leading",      # leading dash (first char must be [a-z0-9])
        "semi;colon",    # punctuation
        "under_score",   # underscore not in the custom-id shape
        "custom:x",      # a colon would double-namespace
        "a/b",           # path separator — the exact thing that must never
                         # reach a WHERE source_id = %s
    ],
)
def test_custom_rejects_bad_id(bad: str) -> None:
    with pytest.raises(ValueError):
        custom(bad)


def test_custom_rejects_non_str() -> None:
    with pytest.raises(ValueError):
        custom(None)  # type: ignore[arg-type]


def test_new_custom_company_id_shape_and_roundtrip() -> None:
    for _ in range(200):
        cid = new_custom_company_id()
        assert re.fullmatch(r"u-[0-9a-z]{10}", cid), cid
        # Every generated id must be a valid custom() input.
        assert custom(cid) == f"custom:{cid}"


def test_new_custom_company_id_is_random() -> None:
    ids = {new_custom_company_id() for _ in range(500)}
    # 36**10 space — 500 draws should not collide.
    assert len(ids) == 500
