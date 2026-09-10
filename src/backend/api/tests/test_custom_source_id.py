"""Unit tests for the per-company source_id helpers + the custom id generator.

``custom()`` (E7 §2.1) is the private-board namespace; ``recipe()`` is the
PUBLISHED recipe-board one. They share validation and must never share a prefix
- see ``test_the_two_namespaces_can_never_be_confused_for_one_another``.
"""

from __future__ import annotations

import re

import pytest

from scripts.shared.constants import (
    CUSTOM_SOURCE_PREFIX,
    RECIPE_ATS,
    RECIPE_SOURCE_PREFIX,
    custom,
    harvest_source_id,
    new_custom_company_id,
    recipe,
)


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


# --- the PUBLISHED recipe-board namespace ------------------------------------


@pytest.mark.parametrize(
    "company_id, expected",
    [
        ("atlassian", "recipe:atlassian"),
        ("github", "recipe:github"),
        ("oracle", "recipe:oracle"),
        ("dell", "recipe:dell"),
        ("happyrobot.ai", "recipe:happyrobot.ai"),
    ],
)
def test_recipe_valid(company_id: str, expected: str) -> None:
    assert recipe(company_id) == expected


@pytest.mark.parametrize(
    "bad",
    ["", "BadUpper", "has space", ".leading", "-leading", "under_score",
     "recipe:x", "custom:x", "a/b"],
)
def test_recipe_rejects_bad_id(bad: str) -> None:
    """Same validation as ``custom()`` — the two namespaces must not disagree
    about what an id is, because both end up in ``WHERE source_id = %s``."""
    with pytest.raises(ValueError):
        recipe(bad)


def test_recipe_rejects_non_str() -> None:
    with pytest.raises(ValueError):
        recipe(None)  # type: ignore[arg-type]


def test_the_two_namespaces_can_never_be_confused_for_one_another() -> None:
    """THE point of a separate prefix, stated as the property that matters.

    The enrichment claim partitions on ``source_id LIKE 'custom:%'``. If ``recipe:``
    ever started with ``custom:`` (or vice versa) a published board would ride the
    ~10% private-board fairness brake — a real, silent bug: it reads as "enrichment
    is slow for Atlassian", not as a mis-namespaced row.
    """
    assert not RECIPE_SOURCE_PREFIX.startswith(CUSTOM_SOURCE_PREFIX)
    assert not CUSTOM_SOURCE_PREFIX.startswith(RECIPE_SOURCE_PREFIX)
    for company_id in ("atlassian", "u-abc1234567"):
        assert not recipe(company_id).startswith(CUSTOM_SOURCE_PREFIX)
        assert not custom(company_id).startswith(RECIPE_SOURCE_PREFIX)
        assert recipe(company_id) != custom(company_id)


@pytest.mark.parametrize(
    "visibility, expected_prefix",
    [
        ("public", RECIPE_SOURCE_PREFIX),
        ("user", CUSTOM_SOURCE_PREFIX),
        # Anything unexpected falls back to the PRIVATE namespace, which is the one
        # carrying the extra read-side guards — the safe direction to fail in.
        (None, CUSTOM_SOURCE_PREFIX),
        ("", CUSTOM_SOURCE_PREFIX),
        ("Public", CUSTOM_SOURCE_PREFIX),
    ],
)
def test_harvest_source_id_dispatches_on_visibility(
    visibility, expected_prefix: str
) -> None:
    assert harvest_source_id("atlassian", visibility=visibility) == (
        expected_prefix + "atlassian"
    )


def test_recipe_ats_is_not_one_of_the_vendor_ats_values() -> None:
    """``companies.ats='recipe'`` is what routes a board to the recipe fan-out and
    away from all six vendor ones. Colliding with a vendor value would put a
    published recipe board on that vendor's cron, where its script is meaningless.
    """
    assert RECIPE_ATS not in {
        "greenhouse", "ashby", "lever", "gem", "eightfold", "workday",
        # the two existing non-vendor sentinels
        "script", "discovered",
    }
