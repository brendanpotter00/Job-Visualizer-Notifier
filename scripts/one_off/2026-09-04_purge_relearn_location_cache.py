#!/usr/bin/env python3
"""One-time: purge the poisoned alias cache and re-learn it from scratch.

Background
----------
The alias cache was append-only until 2026-09 (``persist_llm_result`` inserted
into ``alias_locations`` with ON CONFLICT DO NOTHING and never deleted), so every
re-normalization UNIONed its answer with every previous one. One raw string
accumulated every mapping Haiku had ever produced for it: the key ``'remote'``
reached 29 locations (including Riyadh, on jobs whose raw location is the single
word "Remote"), ``'san francisco'`` reached 10, and 332 aliases held 3 or more.
13,838 OPEN jobs -- 36% of the corpus -- carried tags from a poisoned alias.

The writer is fixed. This clears the damage it already did.

ORDER OF OPERATIONS -- this is load-bearing
-------------------------------------------
Run these in sequence. Running this script before the fixes are DEPLOYED just
re-poisons the cache with the same bug.

  1. Merge #283 (replace semantics + per-alias advisory lock) and let Railway
     finish deploying it. Without this, the relearn in step 4 re-accumulates.
  2. Merge #284 (closed remote_scope vocabulary + derived canonical_name) and let
     it deploy. Without this, the relearn recreates the duplicate-name rows.
  3. Re-run the existing canonicalize backfill, which now does far more than it
     did in June because canonicalize() got stronger in #284 -- it will coerce the
     junk remote scopes and re-derive every label, merging what collapses:

         railway run -- python scripts/one_off/2026-06-14_canonicalize_locations.py
         railway run -- python scripts/one_off/2026-06-14_canonicalize_locations.py --apply

  4. THEN run this script. It empties the alias cache and hands every OPEN job
     back to the normalization safety-net, which re-learns each distinct location
     string exactly once (the per-alias lock from #283 is what makes it once
     rather than once-per-job).

Cost and duration
-----------------
~2,500 distinct alias keys, one Haiku call each, roughly $2. ``scan_unnormalized``
drains 100 jobs/tick every 5 minutes, so the full corpus takes ~32h at the default
cadence. Raise SCAN_LIMIT temporarily to compress it.

While it drains, OPEN jobs progressively regain tags. Jobs not yet re-normalized
have NO location tags, so location filters under-return during the window. That
is accepted (see the plan); run it overnight if you would rather not.

Safety
------
* DEFAULT IS DRY-RUN: prints the plan and ROLLS BACK. Pass ``--apply`` to commit.
* Everything runs in ONE transaction.
* ``source='manual'`` aliases are PRESERVED by default. Those are operator (or
  location-normalization skill) judgments -- deliberately immune to LLM overwrite
  -- and purging them would throw away exactly the corrections worth keeping.
  ``--purge-manual`` overrides, and says so loudly.
* Take a logical backup first:
      pg_dump "$DATABASE_URL" -t locations -t location_aliases \\
              -t alias_locations -t job_locations > loc-backup-$(date +%F).sql

Usage
-----
    railway run -- python scripts/one_off/2026-09-04_purge_relearn_location_cache.py
    railway run -- python scripts/one_off/2026-09-04_purge_relearn_location_cache.py --apply
"""

from __future__ import annotations

import argparse
import os
import sys

import psycopg2
from psycopg2.extras import RealDictCursor


def scalar(row, key):
    return row[key] if isinstance(row, dict) else row[0]


def report(cur, label: str) -> dict:
    """Print the numbers that decide whether this worked."""
    cur.execute(
        """
        SELECT
          (SELECT count(*) FROM locations)                                        AS locations,
          (SELECT count(DISTINCT canonical_name) FROM locations)                  AS distinct_names,
          (SELECT count(*) FROM location_aliases)                                 AS aliases,
          (SELECT count(*) FROM location_aliases WHERE source = 'manual')         AS manual_aliases,
          (SELECT count(*) FROM alias_locations)                                  AS alias_links,
          (SELECT count(*) FROM job_locations)                                    AS job_links,
          (SELECT count(*) FROM job_listings WHERE status = 'OPEN')               AS open_jobs,
          (SELECT count(*) FROM job_listings
             WHERE status = 'OPEN' AND normalization_status IS NULL)              AS open_null,
          (SELECT count(*) FROM job_listings
             WHERE status = 'OPEN' AND normalization_status = 'failed')           AS open_failed,
          (SELECT count(*) FROM (
              SELECT raw_text FROM alias_locations GROUP BY raw_text HAVING count(*) >= 3
           ) t)                                                                   AS aliases_3plus
        """
    )
    row = dict(cur.fetchone())
    print(f"--- {label} ---")
    for key, value in row.items():
        print(f"    {key:<16} {value}")
    return row


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--apply", action="store_true",
                    help="COMMIT. Without this the transaction is rolled back.")
    ap.add_argument("--db-url", default=os.environ.get("DATABASE_URL"),
                    help="defaults to $DATABASE_URL")
    ap.add_argument("--purge-manual", action="store_true",
                    help="ALSO delete source='manual' aliases. Off by default: those "
                         "are operator/skill judgments and are the corrections most "
                         "worth keeping.")
    ap.add_argument("--include-closed", action="store_true",
                    help="also reset CLOSED jobs. Off by default -- re-normalizing "
                         "closed jobs spends Haiku calls on rows nobody can apply to.")
    args = ap.parse_args()

    if not args.db_url:
        sys.exit("no database URL: pass --db-url or set DATABASE_URL "
                 "(normally via `railway run --`)")

    mode = "APPLY (will COMMIT)" if args.apply else "DRY-RUN (will ROLLBACK)"
    print(f"=== purge + relearn location cache — {mode} ===\n")

    conn = psycopg2.connect(args.db_url, cursor_factory=RealDictCursor)
    try:
        cur = conn.cursor()
        before = report(cur, "BEFORE")
        print()

        if before["manual_aliases"] and not args.purge_manual:
            print(f"preserving {before['manual_aliases']} manual alias(es) "
                  f"(pass --purge-manual to delete them too)")
        elif args.purge_manual and before["manual_aliases"]:
            print(f"!! --purge-manual: DELETING {before['manual_aliases']} operator "
                  f"judgment(s). These are not recoverable from the LLM.")

        # 1. Empty the alias cache. alias_locations cascades from location_aliases,
        #    so deleting the parent is enough -- but be explicit about the children
        #    for the manual-preserving case, where a plain TRUNCATE is not an option.
        if args.purge_manual:
            cur.execute("DELETE FROM alias_locations")
            cur.execute("DELETE FROM location_aliases")
        else:
            cur.execute(
                "DELETE FROM alias_locations WHERE raw_text IN "
                "(SELECT raw_text FROM location_aliases WHERE source <> 'manual')"
            )
            cur.execute("DELETE FROM location_aliases WHERE source <> 'manual'")
        print(f"\ncleared {cur.rowcount} alias row(s)")

        # 2. Hand every job back to the safety-net. 'failed' rows are included on
        #    purpose: 4,073 OPEN jobs sit there with no tags at all, and they
        #    deserve a fresh attempt under the fixed code.
        status_filter = "" if args.include_closed else " AND status = 'OPEN'"
        cur.execute(
            "UPDATE job_listings SET normalization_status = NULL "
            f"WHERE normalization_status IS NOT NULL{status_filter}"
        )
        print(f"reset normalization_status on {cur.rowcount} job(s)")

        # 3. Drop locations nothing points at any more. Safe: no FK targets them,
        #    and the relearn re-creates whatever it actually needs.
        cur.execute(
            "DELETE FROM locations l WHERE NOT EXISTS "
            "(SELECT 1 FROM job_locations jl WHERE jl.normalized_location_id = l.id) "
            "AND NOT EXISTS "
            "(SELECT 1 FROM alias_locations al WHERE al.normalized_location_id = l.id)"
        )
        print(f"deleted {cur.rowcount} orphan location row(s)")

        print()
        after = report(cur, "AFTER (in-transaction)")

        # --- post-checks, before committing --------------------------------
        problems: list[str] = []
        if not args.purge_manual and after["manual_aliases"] != before["manual_aliases"]:
            problems.append(
                f"manual aliases changed {before['manual_aliases']} -> "
                f"{after['manual_aliases']} but --purge-manual was not passed"
            )
        expected_non_manual = 0 if args.purge_manual else after["manual_aliases"]
        if after["aliases"] != expected_non_manual:
            problems.append(
                f"expected {expected_non_manual} alias(es) to remain, found {after['aliases']}"
            )
        if after["open_null"] != after["open_jobs"]:
            problems.append(
                f"{after['open_jobs'] - after['open_null']} OPEN job(s) still carry a "
                f"normalization_status; they will not be re-learned"
            )
        cur.execute(
            "SELECT count(*) AS n FROM alias_locations al "
            "WHERE NOT EXISTS (SELECT 1 FROM location_aliases la WHERE la.raw_text = al.raw_text)"
        )
        widowed = int(scalar(cur.fetchone(), "n"))
        if widowed:
            problems.append(f"{widowed} alias_locations row(s) have no parent alias")

        print()
        if problems:
            for p in problems:
                print(f"POST-CHECK FAILED: {p}")
            conn.rollback()
            print("\nROLLED BACK — post-checks failed. Nothing was changed.")
            return 1

        print("post-checks OK")
        if args.apply:
            conn.commit()
            print("\nCOMMITTED.")
            print("The safety-net now re-learns each distinct location string once.")
            print("Watch it drain:")
            print("    SELECT count(*) FROM job_listings")
            print("     WHERE status='OPEN' AND normalization_status IS NULL;")
        else:
            conn.rollback()
            print("\nDRY-RUN — rolled back. Re-run with --apply to commit.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
