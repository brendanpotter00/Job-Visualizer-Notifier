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

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import connection as Connection

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
