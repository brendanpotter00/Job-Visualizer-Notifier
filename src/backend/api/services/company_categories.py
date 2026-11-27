"""Company categories: load, seed, and read (facets + search filter).

The committed ``data/company_categories.json`` is the ONE source of truth. The
backend seeds ``company_categories`` + ``company_category_members`` from it on
every boot, and the frontend imports the same file (bundled dropdown options,
landing cards, demo-mode filter). File shape::

    {"categories": [
        {"slug": "big_tech", "label": "Big Tech", "definition": "...",
         "companyIds": ["google", "apple", ...]}
    ]}

Array order is display order (``sort_order`` = index). ``companyIds`` order is
the landing logo order (``position`` = index, 0 = most recognizable).

The seed mirrors ``companies_seed``: loaded lazily, one transaction, rolled
back and re-raised on a DB error, and the lifespan call is wrapped in a broad
``except`` so a bad file degrades to last-good DB content instead of
crash-looping boot.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, TypedDict

import psycopg2
from psycopg2.extensions import connection as Connection

from ..models import ENABLED_COMPANY_ID_PATTERN
from .db_rows import scalar

logger = logging.getLogger(__name__)

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "company_categories.json"

# Same shape as the search router's ``_COMPANY_CATEGORY_RE``. ``\Z``, never
# ``$`` (``$`` also matches before a trailing newline).
_SLUG_RE = re.compile(r"\A[a-z_]{1,40}\Z")
_COMPANY_ID_RE = re.compile(ENABLED_COMPANY_ID_PATTERN.rstrip("$") + r"\Z")
_MAX_COMPANY_ID_LEN = 64  # models.CompanyId


class CompanyCategoryDef(TypedDict):
    """One category from the data file, in snake_case."""

    slug: str
    label: str
    definition: str
    company_ids: list[str]


def _require_str(entry: dict[str, Any], key: str, where: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{where}: '{key}' must be a string")
    return value


def parse_company_categories(raw: Any) -> list[CompanyCategoryDef]:
    """Turn the file's JSON into validated ``CompanyCategoryDef`` rows.

    Raises ``ValueError`` on any wrong shape, then runs
    :func:`validate_company_categories`.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("categories"), list):
        raise ValueError("company categories: expected {'categories': [...]}")
    parsed: list[CompanyCategoryDef] = []
    for index, entry in enumerate(raw["categories"]):
        where = f"company categories[{index}]"
        if not isinstance(entry, dict):
            raise ValueError(f"{where}: expected an object")
        company_ids = entry.get("companyIds")
        if not isinstance(company_ids, list) or not all(
            isinstance(company_id, str) for company_id in company_ids
        ):
            raise ValueError(f"{where}: 'companyIds' must be a list of strings")
        parsed.append(
            {
                "slug": _require_str(entry, "slug", where),
                "label": _require_str(entry, "label", where),
                "definition": _require_str(entry, "definition", where),
                "company_ids": list(company_ids),
            }
        )
    return validate_company_categories(parsed)


def validate_company_categories(
    categories: list[CompanyCategoryDef],
) -> list[CompanyCategoryDef]:
    """Check the rules the seed relies on. Raises ``ValueError`` on the first break.

    - at least one category (an empty file would wipe the tables);
    - slug matches ``\\A[a-z_]{1,40}\\Z``, and no slug or label repeats;
    - label and definition are not blank;
    - every member id is a valid company id, at most once per category.
    """
    if not categories:
        raise ValueError("company categories: the file lists no categories")
    seen_slugs: set[str] = set()
    seen_labels: set[str] = set()
    for category in categories:
        slug = category["slug"]
        if not _SLUG_RE.match(slug):
            raise ValueError(f"company categories: bad slug {slug!r}")
        if slug in seen_slugs:
            raise ValueError(f"company categories: duplicate slug {slug!r}")
        seen_slugs.add(slug)
        label = category["label"]
        if not label.strip():
            raise ValueError(f"company categories: {slug!r} has an empty label")
        if label in seen_labels:
            raise ValueError(f"company categories: duplicate label {label!r}")
        seen_labels.add(label)
        if not category["definition"].strip():
            raise ValueError(f"company categories: {slug!r} has an empty definition")
        seen_members: set[str] = set()
        for company_id in category["company_ids"]:
            if len(company_id) > _MAX_COMPANY_ID_LEN or not _COMPANY_ID_RE.match(
                company_id
            ):
                raise ValueError(
                    f"company categories: {slug!r} has a bad company id {company_id!r}"
                )
            if company_id in seen_members:
                raise ValueError(
                    f"company categories: {slug!r} lists {company_id!r} twice"
                )
            seen_members.add(company_id)
    return categories


def load_company_categories(path: Path = DATA_PATH) -> list[CompanyCategoryDef]:
    """Read and validate the committed data file."""
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    return parse_company_categories(raw)


class SeedSummary(TypedDict):
    categories_inserted: int
    categories_updated: int
    categories_deleted: int
    members_inserted: int
    members_updated: int
    members_deleted: int
    unmatched: list[str]


def _count_inserted(rows: list[Any]) -> tuple[int, int]:
    """Split ``RETURNING (xmax = 0) AS inserted`` rows into (inserted, updated)."""
    inserted = sum(1 for row in rows if scalar(row, "inserted"))
    return inserted, len(rows) - inserted


def seed_company_categories(
    conn: Connection, categories: list[CompanyCategoryDef] | None = None
) -> SeedSummary:
    """Make the two tables match the data file. Idempotent.

    One transaction:

    1. Upsert every category (``sort_order`` = its index).
    2. Delete member rows the file no longer lists.
    3. Upsert every member (``position`` = its index in ``companyIds``).
    4. Delete categories the file no longer lists (their members cascade).
    5. Commit.

    An upsert only writes a row whose values changed, so a second run with the
    same file reports all zeros. A member id with no ``companies`` row is still
    seeded (the link is soft) and WARN-logged. Validation runs BEFORE any write,
    so bad data raises ``ValueError`` and touches nothing. A ``psycopg2.Error``
    rolls back and re-raises.

    ``categories`` may be passed in by tests; otherwise the file is loaded
    lazily, so a bad file fails here (inside the lifespan's guard) rather than
    at import.
    """
    if categories is None:
        categories = load_company_categories()
    else:
        categories = validate_company_categories(categories)

    slugs = [category["slug"] for category in categories]
    member_slugs: list[str] = []
    member_ids: list[str] = []
    member_positions: list[int] = []
    for category in categories:
        for position, company_id in enumerate(category["company_ids"]):
            member_slugs.append(category["slug"])
            member_ids.append(company_id)
            member_positions.append(position)

    cursor = conn.cursor()
    try:
        category_rows: list[Any] = []
        for sort_order, category in enumerate(categories):
            cursor.execute(
                "INSERT INTO company_categories (slug, label, definition, sort_order)"
                " VALUES (%s, %s, %s, %s)"
                " ON CONFLICT (slug) DO UPDATE SET"
                " label = EXCLUDED.label,"
                " definition = EXCLUDED.definition,"
                " sort_order = EXCLUDED.sort_order"
                " WHERE (company_categories.label, company_categories.definition,"
                " company_categories.sort_order)"
                " IS DISTINCT FROM"
                " (EXCLUDED.label, EXCLUDED.definition, EXCLUDED.sort_order)"
                " RETURNING (xmax = 0) AS inserted",
                (category["slug"], category["label"], category["definition"], sort_order),
            )
            category_rows.extend(cursor.fetchall())
        categories_inserted, categories_updated = _count_inserted(category_rows)

        cursor.execute(
            "DELETE FROM company_category_members m"
            " WHERE NOT EXISTS ("
            " SELECT 1 FROM unnest(%s::text[], %s::text[]) AS f(slug, company_id)"
            " WHERE f.slug = m.category_slug AND f.company_id = m.company_id)",
            (member_slugs, member_ids),
        )
        members_deleted = cursor.rowcount

        cursor.execute(
            "INSERT INTO company_category_members (category_slug, company_id, position)"
            " SELECT * FROM unnest(%s::text[], %s::text[], %s::int[])"
            " ON CONFLICT (category_slug, company_id) DO UPDATE SET"
            " position = EXCLUDED.position"
            " WHERE company_category_members.position IS DISTINCT FROM EXCLUDED.position"
            " RETURNING (xmax = 0) AS inserted",
            (member_slugs, member_ids, member_positions),
        )
        members_inserted, members_updated = _count_inserted(cursor.fetchall())

        cursor.execute(
            "DELETE FROM company_categories WHERE NOT (slug = ANY(%s::text[]))",
            (slugs,),
        )
        categories_deleted = cursor.rowcount

        cursor.execute(
            "SELECT f.id FROM unnest(%s::text[]) AS f(id)"
            " WHERE NOT EXISTS (SELECT 1 FROM companies c WHERE c.id = f.id)"
            " ORDER BY f.id",
            (sorted(set(member_ids)),),
        )
        unmatched = [scalar(row, "id") for row in cursor.fetchall()]

        conn.commit()
    except psycopg2.Error as exc:
        conn.rollback()
        logger.error(
            "Database error during seed_company_categories: %s", exc, exc_info=True
        )
        raise

    if unmatched:
        logger.warning(
            "seed_company_categories: %d member id(s) matched no companies row"
            " (seeded anyway): %s",
            len(unmatched),
            ", ".join(unmatched),
        )
    # Unconditional, like the other seeds: a conditional line is
    # indistinguishable from a silent crash in Railway logs.
    logger.info(
        "seed_company_categories completed (categories: inserted=%d updated=%d"
        " deleted=%d; members: inserted=%d updated=%d deleted=%d; total=%d;"
        " unmatched=%d)",
        categories_inserted,
        categories_updated,
        categories_deleted,
        members_inserted,
        members_updated,
        members_deleted,
        len(member_ids),
        len(unmatched),
    )
    return {
        "categories_inserted": categories_inserted,
        "categories_updated": categories_updated,
        "categories_deleted": categories_deleted,
        "members_inserted": members_inserted,
        "members_updated": members_updated,
        "members_deleted": members_deleted,
        "unmatched": unmatched,
    }


def _regclass(cur: Any, name: str) -> bool:
    """Duplicated from ``enrichment_monitor._regclass`` (same reason as
    ``app_settings``: three lines beat importing a private symbol)."""
    cur.execute("SELECT to_regclass(%s) AS oid", (name,))
    return scalar(cur.fetchone(), "oid") is not None


def list_company_category_facets(conn: Connection) -> list[dict[str, Any]]:
    """Dropdown rows for ``GET /api/jobs/facets`` (``companyCategories``).

    Same row shape as the other facet arms (``parent_slug`` is always NULL).
    Returns ``[]`` when the table is missing or the read fails: the frontend
    then shows its bundled list, and the rest of the facets still load.
    """
    cur = conn.cursor()
    try:
        if not _regclass(cur, "company_categories"):
            return []
        cur.execute(
            "SELECT slug, label, sort_order, NULL AS parent_slug"
            " FROM company_categories ORDER BY sort_order, slug"
        )
        return [dict(row) for row in cur.fetchall()]
    except psycopg2.Error:
        logger.exception("Failed to read company category facets")
        return []
    finally:
        cur.close()
        conn.rollback()


def resolve_company_category_members(conn: Connection, slugs: list[str]) -> list[str]:
    """Every company id in ANY of ``slugs``, sorted and distinct.

    An unknown slug contributes nothing, so a filter of only unknown slugs
    resolves to ``[]`` (which the search treats as "match nothing").
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT company_id FROM company_category_members"
            " WHERE category_slug = ANY(%s::text[]) ORDER BY company_id",
            (list(slugs),),
        )
        return [scalar(row, "company_id") for row in cur.fetchall()]
