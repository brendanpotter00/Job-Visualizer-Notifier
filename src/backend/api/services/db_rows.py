"""Small psycopg2 row-access helpers shared across services.

The cursors in this codebase may yield either ``RealDictRow`` (dict-like) or
plain tuples depending on the cursor factory, so reads go through a tiny shim
rather than indexing directly.
"""

from typing import Any


def scalar(row: Any, key: str) -> Any:
    """Read a column from a RealDict row or a plain tuple (first col)."""
    if row is None:
        return None
    if isinstance(row, dict):
        return row[key]
    return row[0]
