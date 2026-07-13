"""Per-user saved filters + keyword-list CRUD + canonical-location search.

Backed by the bare-named ``user_saved_filters`` and ``user_keyword_lists`` tables
and the read-only ``locations`` table. Mirrors the psycopg2 conventions of
``user_preferences_service`` (enabled-companies): raw SQL via a pooled
``Connection`` with ``RealDictCursor``, atomic transactions with explicit
``conn.commit()`` and ``conn.rollback()`` on ``psycopg2.Error``.

Two scalars-vs-collection shapes:

* ``user_saved_filters`` is a single fixed-shape row per user, written with an
  ``INSERT ... ON CONFLICT (user_id) DO UPDATE`` upsert (PUT = full replace).
  A missing row reads back as the server defaults (``GET`` never 404s).
* ``user_keyword_lists`` is an unbounded per-user collection mutated one list at
  a time (create / rename / replace-tags / reorder / delete).

The built-in "Software Engineering" list is **synthesized** here (module
constant ``BUILTIN_SWE_LIST``) and never stored. It is returned last by
``list_keyword_lists`` and its name is reserved case-insensitively. The
active-list pointers on ``user_saved_filters`` are plain TEXT (not FKs) so they
can hold the built-in id; ownership is enforced in this layer and a list DELETE
NULLs any pointer referencing it in the same transaction.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, TypedDict

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import connection as Connection
from psycopg2.extras import Json

logger = logging.getLogger(__name__)

_SAVED_FILTERS = sql.Identifier("user_saved_filters")
_KEYWORD_LISTS = sql.Identifier("user_keyword_lists")
_LOCATIONS = sql.Identifier("locations")

# Caps. The list-text/name/tag caps are also enforced by Pydantic at the
# boundary; the per-user list count is checked here because Pydantic cannot see
# the existing row count.
MAX_KEYWORD_LISTS_PER_USER = 50

# --- Built-in "Software Engineering" list (synthesized, never stored) ---------

BUILTIN_SWE_LIST_ID = "builtin-swe"
BUILTIN_SWE_LIST_NAME = "Software Engineering"
# Exact tags (all "include" mode) per the feature spec.
BUILTIN_SWE_LIST: dict[str, Any] = {
    "id": BUILTIN_SWE_LIST_ID,
    "name": BUILTIN_SWE_LIST_NAME,
    "is_builtin": True,
    "position": 0,
    "tags": [
        {"text": "software engineer", "mode": "include"},
        {"text": "developer", "mode": "include"},
        {"text": "engineer", "mode": "include"},
        {"text": "data engineer", "mode": "include"},
        {"text": "backend", "mode": "include"},
        {"text": "frontend", "mode": "include"},
    ],
}

# Server defaults returned when a user has no ``user_saved_filters`` row.
_DEFAULT_RECENT_TIME_WINDOW = "3h"
_DEFAULT_TREND_TIME_WINDOW = "7d"


class SavedFiltersRow(TypedDict):
    """Shape of the saved-filters dict returned by this service to the router."""

    recent_time_window: str
    trend_time_window: str
    locations: list[str]
    category: list[str]
    level: list[str]
    recent_active_keyword_list_id: str | None
    trend_active_keyword_list_id: str | None


class KeywordListRow(TypedDict):
    """Shape of a keyword-list dict returned by this service to the router."""

    id: str
    name: str
    tags: list[dict[str, str]]
    is_builtin: bool
    position: int


# --- Custom exceptions --------------------------------------------------------


class DuplicateListName(Exception):
    """Raised when a create/rename collides with an existing name (case-
    insensitive) or with the reserved built-in name. Router -> 409."""


class KeywordListNotFound(Exception):
    """Raised when a PATCH/DELETE targets a list id the caller does not own.
    Router -> 404."""


class BuiltinListReadOnly(Exception):
    """Raised when a mutation targets the synthesized built-in list id.
    Router -> 422."""


class KeywordListLimitReached(Exception):
    """Raised when a user is already at ``MAX_KEYWORD_LISTS_PER_USER``.
    Router -> 422."""


class UnknownActiveList(Exception):
    """Raised when an active-list pointer references a list the caller does not
    own (and is not the built-in id). Router -> 409."""


# --- Scalar saved filters -----------------------------------------------------


def default_saved_filters() -> SavedFiltersRow:
    """Server defaults returned when a user has no ``user_saved_filters`` row.

    Public so the router can serve them for a caller with no ``users`` row yet
    (avoiding a pointless query against a non-existent user id) without the
    GET endpoint ever 404ing.
    """
    return {
        "recent_time_window": _DEFAULT_RECENT_TIME_WINDOW,
        "trend_time_window": _DEFAULT_TREND_TIME_WINDOW,
        "locations": [],
        "category": [],
        "level": [],
        "recent_active_keyword_list_id": None,
        "trend_active_keyword_list_id": None,
    }


def _coerce_str_list(raw: Any) -> list[str]:
    """Guard a JSONB array column against an unexpected NULL/non-list."""
    return list(raw) if isinstance(raw, list) else []


def _row_to_saved_filters(row: dict[str, Any]) -> SavedFiltersRow:
    # ``locations`` / ``category`` / ``level`` round-trip as Python lists via the
    # JSONB columns; guard against an unexpected NULL/non-list by coercing to [].
    return {
        "recent_time_window": row["recent_time_window"],
        "trend_time_window": row["trend_time_window"],
        "locations": _coerce_str_list(row["locations"]),
        "category": _coerce_str_list(row["category"]),
        "level": _coerce_str_list(row["level"]),
        "recent_active_keyword_list_id": row["recent_active_keyword_list_id"],
        "trend_active_keyword_list_id": row["trend_active_keyword_list_id"],
    }


def get_saved_filters(conn: Connection, user_id: str) -> SavedFiltersRow:
    """Return the user's scalar saved filters, or server defaults if no row.

    READ-ONLY (SELECT only; no commit). Never raises for a missing row — a
    user who has never saved any filters resolves to the defaults so the GET
    endpoint never 404s.
    """
    cursor = conn.cursor()
    cursor.execute(
        sql.SQL(
            "SELECT recent_time_window, trend_time_window, locations,"
            " category, level,"
            " recent_active_keyword_list_id, trend_active_keyword_list_id"
            " FROM {} WHERE user_id = %s"
        ).format(_SAVED_FILTERS),
        (user_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return default_saved_filters()
    return _row_to_saved_filters(dict(row))


def _user_owns_list(cursor: Any, user_id: str, list_id: str) -> bool:
    cursor.execute(
        sql.SQL("SELECT 1 FROM {} WHERE id = %s AND user_id = %s").format(
            _KEYWORD_LISTS
        ),
        (list_id, user_id),
    )
    return cursor.fetchone() is not None


def _validate_active_pointer(
    cursor: Any, user_id: str, pointer: str | None
) -> None:
    """Raise ``UnknownActiveList`` if a non-null pointer is neither the built-in
    id nor a list the caller owns."""
    if pointer is None or pointer == BUILTIN_SWE_LIST_ID:
        return
    if not _user_owns_list(cursor, user_id, pointer):
        raise UnknownActiveList(pointer)


def upsert_saved_filters(
    conn: Connection,
    user_id: str,
    *,
    recent_time_window: str,
    trend_time_window: str,
    locations: list[str],
    category: list[str],
    level: list[str],
    recent_active_keyword_list_id: str | None,
    trend_active_keyword_list_id: str | None,
) -> SavedFiltersRow:
    """Full-replace upsert of the user's scalar saved filters (PUT semantics).

    Validates each non-null active-list pointer against the built-in id or a
    list the caller owns BEFORE writing (raises ``UnknownActiveList`` -> 409),
    then ``INSERT ... ON CONFLICT (user_id) DO UPDATE`` in a single transaction.
    Rolls back and re-raises on ``psycopg2.Error``.
    """
    cursor = conn.cursor()
    try:
        _validate_active_pointer(cursor, user_id, recent_active_keyword_list_id)
        _validate_active_pointer(cursor, user_id, trend_active_keyword_list_id)
        cursor.execute(
            sql.SQL(
                "INSERT INTO {} ("
                " user_id, recent_time_window, trend_time_window, locations,"
                " category, level,"
                " recent_active_keyword_list_id, trend_active_keyword_list_id"
                ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (user_id) DO UPDATE SET"
                " recent_time_window = EXCLUDED.recent_time_window,"
                " trend_time_window = EXCLUDED.trend_time_window,"
                " locations = EXCLUDED.locations,"
                " category = EXCLUDED.category,"
                " level = EXCLUDED.level,"
                " recent_active_keyword_list_id ="
                " EXCLUDED.recent_active_keyword_list_id,"
                " trend_active_keyword_list_id ="
                " EXCLUDED.trend_active_keyword_list_id,"
                " updated_at = now()"
                " RETURNING recent_time_window, trend_time_window, locations,"
                " category, level,"
                " recent_active_keyword_list_id, trend_active_keyword_list_id"
            ).format(_SAVED_FILTERS),
            (
                user_id,
                recent_time_window,
                trend_time_window,
                Json(locations),
                Json(category),
                Json(level),
                recent_active_keyword_list_id,
                trend_active_keyword_list_id,
            ),
        )
        row = cursor.fetchone()
        conn.commit()
    except UnknownActiveList:
        conn.rollback()
        raise
    except psycopg2.Error as exc:
        conn.rollback()
        logger.error(
            "Database error in upsert_saved_filters for user_id=%s: %s",
            user_id,
            exc,
            exc_info=True,
        )
        raise
    if row is None:
        raise RuntimeError(
            f"upsert_saved_filters returned no row for user_id={user_id}"
        )
    return _row_to_saved_filters(dict(row))


# --- Keyword lists ------------------------------------------------------------


def _coerce_tags(raw: Any) -> list[dict[str, str]]:
    """Coerce a stored JSONB tags value into a list of {text, mode} dicts.

    Defensive against a NULL or malformed column; only keeps dict entries that
    carry both keys, so a partial row can't crash the response serializer.
    """
    if not isinstance(raw, list):
        return []
    tags: list[dict[str, str]] = []
    for item in raw:
        if isinstance(item, dict) and "text" in item and "mode" in item:
            tags.append({"text": item["text"], "mode": item["mode"]})
    return tags


def _row_to_keyword_list(row: dict[str, Any]) -> KeywordListRow:
    return {
        "id": row["id"],
        "name": row["name"],
        "tags": _coerce_tags(row["tags"]),
        "is_builtin": False,
        "position": int(row["position"]),
    }


def builtin_swe_list() -> KeywordListRow:
    """Return a fresh copy of the synthesized built-in list (never mutated).

    Public so the router can serve it for a caller with no ``users`` row yet
    (the keyword-lists GET always includes the built-in, even for a brand-new
    user).
    """
    return {
        "id": BUILTIN_SWE_LIST_ID,
        "name": BUILTIN_SWE_LIST_NAME,
        "tags": [dict(t) for t in BUILTIN_SWE_LIST["tags"]],
        "is_builtin": True,
        "position": 0,
    }


def list_keyword_lists(conn: Connection, user_id: str) -> list[KeywordListRow]:
    """Return the user's keyword lists ordered by (position, created_at), then
    the synthesized built-in "Software Engineering" list LAST.

    READ-ONLY (SELECT only; no commit).
    """
    cursor = conn.cursor()
    cursor.execute(
        sql.SQL(
            "SELECT id, name, tags, position FROM {}"
            " WHERE user_id = %s"
            " ORDER BY position ASC, created_at ASC, id ASC"
        ).format(_KEYWORD_LISTS),
        (user_id,),
    )
    rows = cursor.fetchall()
    result = [_row_to_keyword_list(dict(r)) for r in rows]
    result.append(builtin_swe_list())
    return result


def _name_is_reserved(name: str) -> bool:
    return name.strip().lower() == BUILTIN_SWE_LIST_NAME.lower()


def _name_taken(
    cursor: Any, user_id: str, name: str, *, exclude_id: str | None = None
) -> bool:
    """Case-insensitive name-collision check among the user's own lists."""
    if exclude_id is None:
        cursor.execute(
            sql.SQL(
                "SELECT 1 FROM {} WHERE user_id = %s AND lower(name) = lower(%s)"
            ).format(_KEYWORD_LISTS),
            (user_id, name),
        )
    else:
        cursor.execute(
            sql.SQL(
                "SELECT 1 FROM {} WHERE user_id = %s AND lower(name) = lower(%s)"
                " AND id <> %s"
            ).format(_KEYWORD_LISTS),
            (user_id, name, exclude_id),
        )
    return cursor.fetchone() is not None


def create_keyword_list(
    conn: Connection,
    user_id: str,
    *,
    name: str,
    tags: list[dict[str, str]],
) -> KeywordListRow:
    """Create a new keyword list for the user.

    Raises ``DuplicateListName`` (-> 409) if the name collides case-insensitively
    with an existing list or with the reserved built-in name, and
    ``KeywordListLimitReached`` (-> 422) if the user is already at the per-user
    cap. New rows append at the end (``position`` = current count). The
    ``uq_user_keyword_lists_user_name`` index is the backstop for a concurrent
    duplicate (caught and re-mapped to ``DuplicateListName``).
    """
    new_id = uuid.uuid4().hex
    cursor = conn.cursor()
    try:
        if _name_is_reserved(name):
            raise DuplicateListName(name)
        cursor.execute(
            sql.SQL("SELECT count(*) AS n FROM {} WHERE user_id = %s").format(
                _KEYWORD_LISTS
            ),
            (user_id,),
        )
        count = int(cursor.fetchone()["n"])
        if count >= MAX_KEYWORD_LISTS_PER_USER:
            raise KeywordListLimitReached(user_id)
        if _name_taken(cursor, user_id, name):
            raise DuplicateListName(name)
        cursor.execute(
            sql.SQL(
                "INSERT INTO {} (id, user_id, name, tags, position)"
                " VALUES (%s, %s, %s, %s, %s)"
                " RETURNING id, name, tags, position"
            ).format(_KEYWORD_LISTS),
            (new_id, user_id, name, Json(tags), count),
        )
        row = cursor.fetchone()
        conn.commit()
    except (DuplicateListName, KeywordListLimitReached):
        conn.rollback()
        raise
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        raise DuplicateListName(name)
    except psycopg2.Error as exc:
        conn.rollback()
        logger.error(
            "Database error in create_keyword_list for user_id=%s: %s",
            user_id,
            exc,
            exc_info=True,
        )
        raise
    if row is None:
        raise RuntimeError(
            f"create_keyword_list returned no row for user_id={user_id}"
        )
    return _row_to_keyword_list(dict(row))


def update_keyword_list(
    conn: Connection,
    user_id: str,
    list_id: str,
    *,
    name: str | None = None,
    tags: list[dict[str, str]] | None = None,
    position: int | None = None,
) -> KeywordListRow:
    """Partially update a keyword list (PATCH semantics).

    ``name`` renames, ``tags`` replaces the whole array, ``position`` reorders;
    any subset may be present. Raises ``BuiltinListReadOnly`` (-> 422) if
    ``list_id`` is the built-in id, ``KeywordListNotFound`` (-> 404) if the list
    isn't owned by the caller, and ``DuplicateListName`` (-> 409) on a rename
    collision (case-insensitive, or the reserved built-in name). An all-None
    body is a no-op that returns the current row.
    """
    if list_id == BUILTIN_SWE_LIST_ID:
        raise BuiltinListReadOnly(list_id)
    cursor = conn.cursor()
    try:
        if not _user_owns_list(cursor, user_id, list_id):
            raise KeywordListNotFound(list_id)
        if name is not None:
            if _name_is_reserved(name):
                raise DuplicateListName(name)
            if _name_taken(cursor, user_id, name, exclude_id=list_id):
                raise DuplicateListName(name)

        set_clauses: list[sql.Composable] = []
        params: list[Any] = []
        if name is not None:
            set_clauses.append(sql.SQL("name = %s"))
            params.append(name)
        if tags is not None:
            set_clauses.append(sql.SQL("tags = %s"))
            params.append(Json(tags))
        if position is not None:
            set_clauses.append(sql.SQL("position = %s"))
            params.append(position)

        if not set_clauses:
            # No-op PATCH: re-read and return the current row without a write.
            cursor.execute(
                sql.SQL(
                    "SELECT id, name, tags, position FROM {}"
                    " WHERE id = %s AND user_id = %s"
                ).format(_KEYWORD_LISTS),
                (list_id, user_id),
            )
            row = cursor.fetchone()
            conn.commit()
        else:
            set_clauses.append(sql.SQL("updated_at = now()"))
            params.extend([list_id, user_id])
            cursor.execute(
                sql.SQL(
                    "UPDATE {} SET {} WHERE id = %s AND user_id = %s"
                    " RETURNING id, name, tags, position"
                ).format(_KEYWORD_LISTS, sql.SQL(", ").join(set_clauses)),
                params,
            )
            row = cursor.fetchone()
            conn.commit()
    except (BuiltinListReadOnly, KeywordListNotFound, DuplicateListName):
        conn.rollback()
        raise
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        # name is not None here (the only unique key), but guard for mypy.
        raise DuplicateListName(name or list_id)
    except psycopg2.Error as exc:
        conn.rollback()
        logger.error(
            "Database error in update_keyword_list for user_id=%s list_id=%s: %s",
            user_id,
            list_id,
            exc,
            exc_info=True,
        )
        raise
    if row is None:
        # The owner check passed inside the txn, so a missing row here is an
        # unexpected concurrent delete; surface as not-found rather than 500.
        raise KeywordListNotFound(list_id)
    return _row_to_keyword_list(dict(row))


def delete_keyword_list(conn: Connection, user_id: str, list_id: str) -> None:
    """Delete a keyword list owned by the caller.

    Raises ``BuiltinListReadOnly`` (-> 422) for the built-in id and
    ``KeywordListNotFound`` (-> 404) if the list isn't owned. In the same
    transaction, NULLs any ``user_saved_filters`` active-list pointer (recent
    and/or trend) that referenced this list — the pointer is a plain TEXT
    column (not a FK), so ``ON DELETE CASCADE`` does not cover it.
    """
    if list_id == BUILTIN_SWE_LIST_ID:
        raise BuiltinListReadOnly(list_id)
    cursor = conn.cursor()
    try:
        cursor.execute(
            sql.SQL(
                "DELETE FROM {} WHERE id = %s AND user_id = %s"
            ).format(_KEYWORD_LISTS),
            (list_id, user_id),
        )
        if cursor.rowcount == 0:
            raise KeywordListNotFound(list_id)
        cursor.execute(
            sql.SQL(
                "UPDATE {} SET"
                " recent_active_keyword_list_id = CASE"
                " WHEN recent_active_keyword_list_id = %(lid)s THEN NULL"
                " ELSE recent_active_keyword_list_id END,"
                " trend_active_keyword_list_id = CASE"
                " WHEN trend_active_keyword_list_id = %(lid)s THEN NULL"
                " ELSE trend_active_keyword_list_id END,"
                " updated_at = now()"
                " WHERE user_id = %(uid)s"
                " AND (recent_active_keyword_list_id = %(lid)s"
                " OR trend_active_keyword_list_id = %(lid)s)"
            ).format(_SAVED_FILTERS),
            {"lid": list_id, "uid": user_id},
        )
        conn.commit()
    except KeywordListNotFound:
        conn.rollback()
        raise
    except psycopg2.Error as exc:
        conn.rollback()
        logger.error(
            "Database error in delete_keyword_list for user_id=%s list_id=%s: %s",
            user_id,
            list_id,
            exc,
            exc_info=True,
        )
        raise


# --- Location search ----------------------------------------------------------


def search_locations(
    conn: Connection, q: str, limit: int, open_only: bool
) -> list[dict[str, Any]]:
    """Substring autocomplete over canonical ``locations`` names.

    Prefix matches rank first, then shorter names, then alphabetical. When
    ``open_only`` is true, restrict to canonical locations that have at least
    one OPEN job (via the ``job_locations`` join). READ-ONLY (SELECT only; no
    commit). On ``psycopg2.Error`` rolls back so the pooled connection isn't
    left mid-transaction, then re-raises for the router to map to a 500.

    Returns a list of ``{"id", "canonical_name", "kind", "city", "region",
    "country", "remote_scope"}`` dicts. The structured columns let the frontend
    filter cache a full descriptor so it can resolve any selected location, not
    just the US states/cities it re-derives from the display string.
    """
    pat = f"%{q}%"
    prefix = f"{q}%"
    try:
        with conn.cursor() as cur:
            if open_only:
                cur.execute(
                    sql.SQL(
                        "SELECT l.id, l.canonical_name, l.kind, l.city,"
                        " l.region, l.country, l.remote_scope"
                        " FROM {locations} AS l"
                        " WHERE l.canonical_name ILIKE %(pat)s"
                        " AND EXISTS ("
                        " SELECT 1 FROM job_locations jl"
                        " JOIN job_listings j ON j.id = jl.job_listing_id"
                        " WHERE jl.normalized_location_id = l.id"
                        " AND j.status = 'OPEN')"
                        " ORDER BY (l.canonical_name ILIKE %(prefix)s) DESC,"
                        " length(l.canonical_name) ASC, l.canonical_name ASC"
                        " LIMIT %(limit)s"
                    ).format(locations=_LOCATIONS),
                    {"pat": pat, "prefix": prefix, "limit": limit},
                )
            else:
                cur.execute(
                    sql.SQL(
                        "SELECT id, canonical_name, kind, city, region,"
                        " country, remote_scope"
                        " FROM {locations}"
                        " WHERE canonical_name ILIKE %(pat)s"
                        " ORDER BY (canonical_name ILIKE %(prefix)s) DESC,"
                        " length(canonical_name) ASC, canonical_name ASC"
                        " LIMIT %(limit)s"
                    ).format(locations=_LOCATIONS),
                    {"pat": pat, "prefix": prefix, "limit": limit},
                )
            rows = cur.fetchall()
    except psycopg2.Error:
        conn.rollback()
        logger.exception("search_locations failed for q=%r open_only=%s", q, open_only)
        raise
    return [
        {
            "id": int(r["id"]),
            "canonical_name": r["canonical_name"],
            "kind": r["kind"],
            "city": r["city"],
            "region": r["region"],
            "country": r["country"],
            "remote_scope": r["remote_scope"],
        }
        for r in rows
    ]
