#!/usr/bin/env python3
"""One-time backfill: canonicalize the existing `locations` rows and merge dupes.

Background
----------
Hierarchical location FILTERING (a state matches its cities; a country matches
everything in-country) compares ``region`` + ``country`` codes across a job's
tags. Prod has those codes fragmented — full-name countries (``Brazil``,
``Sweden``), a ``UK`` vs ``GB`` split, non-ISO regions (``Bavaria``, ``QLD``),
``region == country`` rows, and many cities rendered several ways. This script
applies the SAME deterministic ``canonicalize()`` pass the live pipeline now runs
(``api/services/location_canonicalize.py``) to every existing row, MERGING rows
that collapse onto the same canonical identity (repointing the ``job_locations``
and ``alias_locations`` foreign keys, then deleting the now-duplicate rows).

Why Python (not raw SQL): the merge must repoint FKs in two child tables with
composite-PK collision handling and OR-ing ``is_primary``, and it must reuse the
exact country/region maps from the live code so the backfill and future writes
never drift. A ``.py`` one-off (vs the usual ``.sql``) is justified by that.

Why in-place merge (not LLM re-normalization): deterministic, auditable
(``--dry-run`` prints every planned merge), zero LLM spend, single transaction
over ~400 rows. The live canonicalize() pass protects all FUTURE writes.

Safety
------
* DEFAULT IS DRY-RUN: prints the plan and ROLLS BACK. Pass ``--apply`` to commit.
* Everything runs in ONE transaction. Take a logical backup of ``locations`` +
  ``job_locations`` + ``alias_locations`` (or a PITR snapshot) before ``--apply``.
* Run the eval gate + ``api/eval/monitor_prod.py`` integrity checks afterwards.

Usage
-----
    # dry-run (no writes), prints planned merges/updates:
    railway run -- python scripts/one_off/2026-06-14_canonicalize_locations.py
    # commit:
    railway run -- python scripts/one_off/2026-06-14_canonicalize_locations.py --apply
    # local:
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/jobscraper \
        python scripts/one_off/2026-06-14_canonicalize_locations.py
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

# Make `src.backend.api...` importable when run from anywhere.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.backend.api.services.location_canonicalize import canonicalize  # noqa: E402


class _Row:
    """Attribute view of a locations row for canonicalize()."""

    __slots__ = ("id", "canonical_name", "kind", "city", "region", "country", "remote_scope")

    def __init__(self, d: dict):
        self.id = d["id"]
        self.canonical_name = d["canonical_name"]
        self.kind = d["kind"]
        self.city = d["city"]
        self.region = d["region"]
        self.country = d["country"]
        self.remote_scope = d["remote_scope"]


def _key(kind, city, region, country, remote_scope):
    """The uq_locations_canonical key (NULLs compare equal as Python None)."""
    return (kind, city, region, country, remote_scope)


def _merge_loser_into_survivor(cur, loser: int, survivor: int) -> tuple[int, int]:
    """Repoint child FKs from loser -> survivor, then delete the loser row.

    Returns (job_locations_repointed, alias_locations_repointed) counts.
    """
    # --- job_locations: composite PK (job_listing_id, normalized_location_id) ---
    # Preserve is_primary: if a job is linked to a PRIMARY loser AND the survivor,
    # promote the survivor row to primary before deleting the colliding loser.
    cur.execute(
        "UPDATE job_locations s SET is_primary = TRUE "
        "WHERE s.normalized_location_id = %(survivor)s AND EXISTS ("
        "  SELECT 1 FROM job_locations l WHERE l.job_listing_id = s.job_listing_id "
        "  AND l.normalized_location_id = %(loser)s AND l.is_primary)",
        {"survivor": survivor, "loser": loser},
    )
    # Drop loser rows that would collide (job already linked to survivor).
    cur.execute(
        "DELETE FROM job_locations l WHERE l.normalized_location_id = %(loser)s AND EXISTS ("
        "  SELECT 1 FROM job_locations s WHERE s.job_listing_id = l.job_listing_id "
        "  AND s.normalized_location_id = %(survivor)s)",
        {"survivor": survivor, "loser": loser},
    )
    # Repoint the rest.
    cur.execute(
        "UPDATE job_locations SET normalized_location_id = %(survivor)s "
        "WHERE normalized_location_id = %(loser)s",
        {"survivor": survivor, "loser": loser},
    )
    jl = cur.rowcount

    # --- alias_locations: composite PK (raw_text, normalized_location_id) -------
    cur.execute(
        "DELETE FROM alias_locations l WHERE l.normalized_location_id = %(loser)s AND EXISTS ("
        "  SELECT 1 FROM alias_locations s WHERE s.raw_text = l.raw_text "
        "  AND s.normalized_location_id = %(survivor)s)",
        {"survivor": survivor, "loser": loser},
    )
    cur.execute(
        "UPDATE alias_locations SET normalized_location_id = %(survivor)s "
        "WHERE normalized_location_id = %(loser)s",
        {"survivor": survivor, "loser": loser},
    )
    al = cur.rowcount

    cur.execute("DELETE FROM locations WHERE id = %(loser)s", {"loser": loser})
    return jl, al


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="commit (default: dry-run + rollback)")
    parser.add_argument("--db-url", default=os.environ.get("DATABASE_URL"))
    args = parser.parse_args()

    if not args.db_url:
        print("ERROR: set DATABASE_URL or pass --db-url", file=sys.stderr)
        return 2

    mode = "APPLY (will COMMIT)" if args.apply else "DRY-RUN (will ROLLBACK)"
    print(f"== canonicalize_locations :: {mode} ==\n")

    conn = psycopg2.connect(args.db_url, cursor_factory=RealDictCursor)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, canonical_name, kind, city, region, country, remote_scope "
            "FROM locations ORDER BY id"
        )
        rows = [_Row(r) for r in cur.fetchall()]
        print(f"Read {len(rows)} locations rows.")

        # Group every row by its CANONICAL target key.
        groups: dict[tuple, list[tuple[_Row, object]]] = defaultdict(list)
        for r in rows:
            c = canonicalize(r)
            groups[_key(c.kind, c.city, c.region, c.country, c.remote_scope)].append((r, c))

        merges = updates = jl_repoints = al_repoints = 0

        for key, members in groups.items():
            members.sort(key=lambda m: m[0].id)  # survivor = min(id)
            survivor_row, target = members[0]
            losers = members[1:]

            for loser_row, _ in losers:
                print(
                    f"  MERGE  id={loser_row.id} "
                    f"({loser_row.canonical_name!r} {loser_row.region}/{loser_row.country}) "
                    f"-> id={survivor_row.id} ({target.canonical_name!r} "
                    f"{target.region}/{target.country})"
                )
                jl, al = _merge_loser_into_survivor(cur, loser_row.id, survivor_row.id)
                jl_repoints += jl
                al_repoints += al
                merges += 1

            # Bring the survivor's columns to the canonical target (it may itself
            # have been non-canonical, e.g. the min-id row said 'USA'/'Brazil').
            needs_update = (
                survivor_row.canonical_name != target.canonical_name
                or survivor_row.region != target.region
                or survivor_row.country != target.country
            )
            if needs_update:
                if not losers:
                    print(
                        f"  UPDATE id={survivor_row.id} "
                        f"{survivor_row.region}/{survivor_row.country} {survivor_row.canonical_name!r} "
                        f"-> {target.region}/{target.country} {target.canonical_name!r}"
                    )
                cur.execute(
                    "UPDATE locations SET canonical_name = %(name)s, region = %(region)s, "
                    "country = %(country)s WHERE id = %(id)s",
                    {
                        "name": target.canonical_name,
                        "region": target.region,
                        "country": target.country,
                        "id": survivor_row.id,
                    },
                )
                updates += 1

        # Post-checks (within the txn, before commit/rollback).
        cur.execute("SELECT count(*) AS n FROM locations WHERE country IS NOT NULL AND country !~ '^[A-Z]{2}$'")
        bad_country = cur.fetchone()["n"]
        cur.execute(
            "SELECT count(*) AS n FROM locations WHERE country='US' AND kind IN ('city','region') "
            "AND region IS NOT NULL AND region !~ '^[A-Z]{2}$'"
        )
        bad_us_region = cur.fetchone()["n"]
        cur.execute(
            "SELECT count(*) AS n FROM (SELECT 1 FROM locations "
            "GROUP BY kind, city, region, country, remote_scope HAVING count(*) > 1) t"
        )
        dup_keys = cur.fetchone()["n"]

        print(
            f"\nPlan: {merges} merge(s), {updates} update(s); "
            f"repointed {jl_repoints} job_locations, {al_repoints} alias_locations."
        )
        print(
            f"Post-check (in txn): non-ISO2 country={bad_country}, "
            f"non-2-letter US region={bad_us_region}, duplicate canonical keys={dup_keys}"
        )

        if args.apply:
            conn.commit()
            print("\nCOMMITTED.")
        else:
            conn.rollback()
            print("\nDRY-RUN complete — rolled back, no changes written. Re-run with --apply to commit.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
