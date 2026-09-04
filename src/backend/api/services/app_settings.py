"""Runtime-tunable application settings, key/value, JSONB-valued.

ONE table (``app_settings``), and an ALLOWLIST IN CODE rather than in the DDL —
adding a setting must not need a migration.

**THERE IS NO SEED ROW, AND THAT IS THE DESIGN.** An absent key means the code
default. A fresh database, a flag an admin deleted, and a rolled-back migration
therefore all behave identically, and no reader ever has to handle "the row is
missing" as a special case: ``get_settings`` MATERIALIZES a default row for every
allowlisted key that has none, so the UI is handed a complete list either way.

The regclass guard is load-bearing for the same reason. With no seed row there is
nothing to prove the table exists, so a pre-migration process must fall back to
the defaults rather than raise — the public flag reader in particular must NEVER
500, because failing closed there means the feature stays hidden, and failing
open means it appears before it works.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from psycopg2.extensions import connection as Connection
from psycopg2.extras import Json

from .db_rows import scalar

logger = logging.getLogger(__name__)


class SettingError(Exception):
    """Unknown / un-allowlisted setting key, or an uncoercible value.

    Copies ``enrichment_monitor.CorrectionError``'s ``not_found`` flag so the
    router can map an unknown key to 404 and a bad value to 400 without
    inspecting the message.
    """

    def __init__(self, message: str, *, not_found: bool = False) -> None:
        super().__init__(message)
        self.not_found = not_found


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    raise SettingError(f"expected a boolean, got {value!r}")


# THE ALLOWLIST. `{key: (coercer, default)}`, mirroring the enricher's
# `_KNOB_SETTERS` idiom in dashboard.py. A key absent from this dict does not
# exist as far as this module is concerned, whatever the table happens to hold.
_SETTING_SPECS: dict[str, tuple[Callable[[Any], Any], Any]] = {
    # The SWE-subcategories rollout switch. A UI REVEAL switch only: the backend
    # does NOT gate `?subcategory=` on it, so a saved filter keeps working
    # either way. Flipped BY HAND once the admin coverage tile clears 90%.
    "swe_subcategories_enabled": (_coerce_bool, False),
}

# The subset of the allowlist that the UNAUTHENTICATED public endpoint may read.
# A hard boundary, deliberately narrower than the admin allowlist: the public
# response model names its fields rather than dumping whatever the table holds,
# so a future admin-only setting cannot leak by being added to one dict.
_PUBLIC_SETTING_KEYS = frozenset({"swe_subcategories_enabled"})


def _regclass(cur: Any, name: str) -> bool:
    """Duplicated from ``enrichment_monitor._regclass`` — three lines, and
    importing a private symbol across service modules is worse than the copy.
    ``to_regclass`` is search_path-aware, so it behaves the same inside the
    per-worker test schema and in prod."""
    cur.execute("SELECT to_regclass(%s) AS oid", (name,))
    return scalar(cur.fetchone(), "oid") is not None


def get_settings(conn: Connection) -> list[dict[str, Any]]:
    """Every allowlisted setting, with defaults MATERIALIZED for missing rows.

    The caller never sees a partial list, so "no row yet" is not a state the UI
    has to render. Read-only; never commits.
    """
    stored: dict[str, dict[str, Any]] = {}
    cur = conn.cursor()
    try:
        if _regclass(cur, "app_settings"):
            cur.execute(
                "SELECT key, value, updated_at, updated_by FROM app_settings "
                "WHERE key = ANY(%s)",
                (list(_SETTING_SPECS),),
            )
            stored = {r["key"]: dict(r) for r in cur.fetchall()}
    finally:
        cur.close()
        conn.rollback()

    rows: list[dict[str, Any]] = []
    for key, (coerce, default) in sorted(_SETTING_SPECS.items()):
        row = stored.get(key)
        if row is None:
            rows.append(
                {"key": key, "value": default, "updated_at": None, "updated_by": None}
            )
            continue
        try:
            value = coerce(row["value"])
        except SettingError:
            # A hand-edited row with a garbage value must not break the page.
            logger.warning(
                "app_settings: uncoercible value for %s=%r — using the default",
                key, row["value"],
            )
            value = default
        rows.append(
            {
                "key": key,
                "value": value,
                "updated_at": row["updated_at"],
                "updated_by": row["updated_by"],
            }
        )
    return rows


def get_public_settings(conn: Connection) -> dict[str, Any]:
    """The public subset, keyed by setting name. FAILS CLOSED on ANY error.

    Unauthenticated callers hit this. A 500 here would blank the flag read for
    every visitor mid-deploy, so a read failure degrades to the code defaults —
    and for a reveal flag the code default is ``False``, i.e. the feature stays
    hidden. Hidden-when-broken is the correct failure direction: the alternative
    is revealing a filter that returns nothing.
    """
    try:
        rows = {r["key"]: r["value"] for r in get_settings(conn)}
    except Exception:  # noqa: BLE001 — deliberately total; see the docstring
        logger.exception("app_settings: public read failed — falling back to defaults")
        rows = {}
    return {
        key: rows.get(key, _SETTING_SPECS[key][1])
        for key in sorted(_PUBLIC_SETTING_KEYS)
    }


def set_setting(
    conn: Connection, *, key: str, value: Any, updated_by: str | None
) -> dict[str, Any]:
    """Upsert one allowlisted setting. Owns commit/rollback.

    An un-allowlisted key is a 404, not a silent insert — otherwise a typo'd key
    would persist happily and the setting it was meant to change would stay at
    its default forever.
    """
    spec = _SETTING_SPECS.get(key)
    if spec is None:
        raise SettingError(f"unknown setting key {key!r}", not_found=True)
    coerce, _default = spec
    coerced = coerce(value)

    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO app_settings (key, value, updated_at, updated_by) "
            "VALUES (%s, %s, now(), %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, "
            "updated_at = now(), updated_by = EXCLUDED.updated_by "
            "RETURNING key, value, updated_at, updated_by",
            (key, Json(coerced), updated_by),
        )
        row = dict(cur.fetchone())
        conn.commit()
        return {
            "key": row["key"],
            "value": coerce(row["value"]),
            "updated_at": row["updated_at"],
            "updated_by": row["updated_by"],
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


__all__ = [
    "SettingError",
    "get_public_settings",
    "get_settings",
    "set_setting",
]


# Re-exported for tests / callers that need to introspect the allowlist without
# reaching for the private name.
def allowlisted_keys() -> frozenset[str]:
    return frozenset(_SETTING_SPECS)
