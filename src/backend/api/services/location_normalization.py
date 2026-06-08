"""Tier 1 of the location-normalization cascade: the Postgres alias cache.

This module is intentionally small and side-effect-light:

* ``normalize_string`` is a PURE function that produces the canonical cache key
  stored in ``location_aliases.raw_text``. It lowercases, NFKC-normalizes,
  folds unicode dashes/quotes to ASCII, collapses internal whitespace, and
  trims. It NEVER strips accents from real letters ("Zürich" -> "zürich",
  "São Paulo" -> "são paulo"); only case, whitespace, dashes, quotes, and
  Unicode compatibility forms are altered. It is idempotent:
  ``normalize_string(normalize_string(x)) == normalize_string(x)``.

* ``lookup_alias`` is a READ-ONLY Tier-1 cache probe. Given a raw location
  string it pre-normalizes the string, then looks the key up in
  ``location_aliases`` joined to ``alias_locations``. It returns an ordered
  ``list[int]`` of ``locations.id`` on a cache hit, or ``None`` on a cache miss
  (no ``location_aliases`` row at all). Writing the cache is NOT this module's
  job -- that belongs to the Tier-2 task (Unit 5).

Connection contract for ``lookup_alias``: the caller owns the connection. The
function issues only ``SELECT`` statements and does not commit. On a database
error it rolls back (so it never leaves the caller's connection in an aborted
transaction) and re-raises.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import TYPE_CHECKING, Sequence

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import connection as Connection

if TYPE_CHECKING:  # avoid circular import — Tier-1 must not hard-import Tier-2.
    from .llm_client import CanonicalLocation

logger = logging.getLogger(__name__)


# --- normalize_string ------------------------------------------------------

_DASH_CHARS = {
    "‐": "-",  # HYPHEN
    "‑": "-",  # NON-BREAKING HYPHEN
    "‒": "-",  # FIGURE DASH
    "–": "-",  # EN DASH
    "—": "-",  # EM DASH
    "―": "-",  # HORIZONTAL BAR
    "−": "-",  # MINUS SIGN
}

_QUOTE_CHARS = {
    "‘": "'",  # LEFT SINGLE QUOTATION MARK
    "’": "'",  # RIGHT SINGLE QUOTATION MARK (also apostrophe)
    "′": "'",  # PRIME
    "“": '"',  # LEFT DOUBLE QUOTATION MARK
    "”": '"',  # RIGHT DOUBLE QUOTATION MARK
    "″": '"',  # DOUBLE PRIME
}

_TRANSLATION = {ord(k): v for k, v in {**_DASH_CHARS, **_QUOTE_CHARS}.items()}

_WHITESPACE_RUN = re.compile(r"\s+")


def normalize_string(raw: str | None) -> str:
    """Return the canonical cache key for a raw location string.

    Transformation, applied in this exact order:

    1. ``None`` -> ``""``.
    2. Unicode NFKC normalization (folds compatibility forms; preserves
       accented letters -- does NOT strip diacritics).
    3. Unicode dashes (en/em/figure/horizontal-bar/minus/hyphen variants) ->
       ASCII ``-``.
    4. Unicode quotes (curly single/double, primes) -> ASCII ``'`` / ``"``.
    5. Lowercase.
    6. Collapse every internal whitespace run to a single ASCII space.
    7. Strip leading/trailing whitespace.

    The result is idempotent: ``normalize_string(normalize_string(x))`` equals
    ``normalize_string(x)`` for all ``x``.
    """
    if raw is None:
        return ""
    s = unicodedata.normalize("NFKC", raw)
    s = s.translate(_TRANSLATION)
    s = s.lower()
    s = _WHITESPACE_RUN.sub(" ", s)
    return s.strip()


# --- lookup_alias ----------------------------------------------------------

_LOCATION_ALIASES = sql.Identifier("location_aliases")
_ALIAS_LOCATIONS = sql.Identifier("alias_locations")
_LOCATIONS = sql.Identifier("locations")
_JOB_LOCATIONS = sql.Identifier("job_locations")
_JOB_LISTINGS = sql.Identifier("job_listings")


def _location_id_from_row(row) -> int:
    """Extract normalized_location_id from a RealDict row or a plain tuple."""
    if isinstance(row, dict):
        return int(row["normalized_location_id"])
    return int(row[0])


def lookup_alias(conn: Connection, raw: str | None) -> list[int] | None:
    """Tier-1 cache probe for a raw location string.

    Pre-normalizes ``raw`` via :func:`normalize_string`, then resolves the key
    against the alias cache.

    Returns:
        * ``None`` -- cache MISS: no ``location_aliases`` row exists for the
          normalized key.
        * ``list[int]`` -- cache HIT: ordered ``locations.id`` values for this
          alias, ascending by ``alias_locations.position``. By invariant
          (enforced by the Unit-5 writer, which always inserts >=1
          ``alias_locations`` row alongside each ``location_aliases`` row) this
          list is non-empty on a real hit. A present alias row with zero
          children yields ``[]`` (distinct from ``None``), which should not
          occur in practice but is returned faithfully if it does.

    Read-only: issues only SELECTs and never commits. On a database error it
    rolls back the caller's connection (to avoid leaving it in an aborted
    transaction) and re-raises. The caller owns the connection lifecycle.
    """
    key = normalize_string(raw)
    cursor = conn.cursor()
    try:
        cursor.execute(
            sql.SQL("SELECT 1 FROM {} WHERE raw_text = %s LIMIT 1").format(
                _LOCATION_ALIASES
            ),
            (key,),
        )
        if cursor.fetchone() is None:
            return None

        cursor.execute(
            sql.SQL(
                "SELECT al.normalized_location_id"
                " FROM {alias_locations} AS al"
                " JOIN {location_aliases} AS la ON al.raw_text = la.raw_text"
                " WHERE la.raw_text = %s"
                " ORDER BY al.position"
            ).format(
                alias_locations=_ALIAS_LOCATIONS,
                location_aliases=_LOCATION_ALIASES,
            ),
            (key,),
        )
        return [_location_id_from_row(row) for row in cursor.fetchall()]
    except psycopg2.Error as exc:
        conn.rollback()
        logger.error(
            "Database error in lookup_alias for normalized key %r: %s",
            key, exc, exc_info=True,
        )
        raise
    finally:
        cursor.close()


# --- Unit-5 writers (caller owns the transaction; none of these commit) -----


def set_normalization_status(conn: Connection, job_id: str, status: str) -> None:
    """Set job_listings.normalization_status. Keys on id alone (globally unique). No commit."""
    cursor = conn.cursor()
    try:
        cursor.execute(
            sql.SQL("UPDATE {} SET normalization_status = %s WHERE id = %s").format(_JOB_LISTINGS),
            (status, job_id),
        )
        if cursor.rowcount == 0:
            logger.warning("set_normalization_status: no job_listings row for id=%r (status=%r)", job_id, status)
    finally:
        cursor.close()


def write_job_locations_from_ids(conn: Connection, job_id: str, location_ids: Sequence[int]) -> None:
    """Tier-1-HIT writer: job_locations rows (position 0 primary) + mark done. Idempotent. No commit."""
    cursor = conn.cursor()
    try:
        for position, loc_id in enumerate(location_ids):
            cursor.execute(
                sql.SQL(
                    "INSERT INTO {} (job_listing_id, normalized_location_id, is_primary) "
                    "VALUES (%s, %s, %s) ON CONFLICT (job_listing_id, normalized_location_id) DO NOTHING"
                ).format(_JOB_LOCATIONS),
                (job_id, int(loc_id), position == 0),
            )
        cursor.execute(
            sql.SQL("UPDATE {} SET normalization_status = 'done' WHERE id = %s").format(_JOB_LISTINGS),
            (job_id,),
        )
    finally:
        cursor.close()


def persist_llm_result(conn: Connection, job_id: str, raw_text: str, locations: "Sequence[CanonicalLocation]") -> None:
    """Tier-2 writer (tx2 body). raw_text MUST be the normalize_string()'d key. All ON CONFLICT DO NOTHING. No commit."""
    cursor = conn.cursor()
    try:
        location_ids: list[int] = []
        for loc in locations:
            cursor.execute(
                sql.SQL(
                    "INSERT INTO {} (canonical_name, kind, city, region, country, remote_scope) "
                    "VALUES (%s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT ON CONSTRAINT uq_locations_canonical DO NOTHING RETURNING id"
                ).format(_LOCATIONS),
                (loc.canonical_name, loc.kind, loc.city, loc.region, loc.country, loc.remote_scope),
            )
            row = cursor.fetchone()
            if row is None:
                cursor.execute(
                    sql.SQL(
                        "SELECT id FROM {} WHERE kind = %s "
                        "AND city IS NOT DISTINCT FROM %s AND region IS NOT DISTINCT FROM %s "
                        "AND country IS NOT DISTINCT FROM %s AND remote_scope IS NOT DISTINCT FROM %s"
                    ).format(_LOCATIONS),
                    (loc.kind, loc.city, loc.region, loc.country, loc.remote_scope),
                )
                existing = cursor.fetchone()
                if existing is None:
                    raise RuntimeError(
                        f"locations upsert conflicted but no matching row found for "
                        f"kind={loc.kind!r} city={loc.city!r} region={loc.region!r} "
                        f"country={loc.country!r} remote_scope={loc.remote_scope!r}"
                    )
                loc_id = existing["id"] if isinstance(existing, dict) else existing[0]
            else:
                loc_id = row["id"] if isinstance(row, dict) else row[0]
            location_ids.append(int(loc_id))

        avg_conf = sum(l.confidence for l in locations) / len(locations)
        cursor.execute(
            sql.SQL("INSERT INTO {} (raw_text, source, confidence) VALUES (%s, 'llm', %s) "
                    "ON CONFLICT (raw_text) DO NOTHING").format(_LOCATION_ALIASES),
            (raw_text, avg_conf),
        )
        for position, loc_id in enumerate(location_ids):
            cursor.execute(
                sql.SQL("INSERT INTO {} (raw_text, normalized_location_id, position) VALUES (%s, %s, %s) "
                        "ON CONFLICT (raw_text, normalized_location_id) DO NOTHING").format(_ALIAS_LOCATIONS),
                (raw_text, loc_id, position),
            )
        for position, loc_id in enumerate(location_ids):
            cursor.execute(
                sql.SQL("INSERT INTO {} (job_listing_id, normalized_location_id, is_primary) VALUES (%s, %s, %s) "
                        "ON CONFLICT (job_listing_id, normalized_location_id) DO NOTHING").format(_JOB_LOCATIONS),
                (job_id, loc_id, position == 0),
            )
        cursor.execute(
            sql.SQL("UPDATE {} SET normalization_status = 'done' WHERE id = %s").format(_JOB_LISTINGS),
            (job_id,),
        )
    finally:
        cursor.close()
