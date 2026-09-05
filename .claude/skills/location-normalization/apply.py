#!/usr/bin/env python3
"""Apply a location-cache repair plan to prod. DRY-RUN BY DEFAULT.

    python apply.py --plan fixes.json            # print the plan, commit nothing
    python apply.py --plan fixes.json --apply    # commit, in ONE transaction

The plan is JSON produced by the `location-normalization` skill after Claude has
judged what each raw location string SHOULD map to. See SKILL.md §5 for the
schema.

Two things make this safe to run unattended:

* It connects as `claude_location_writer`, whose grants cover only the four
  location tables plus `job_listings.normalization_status`. It REFUSES any other
  role, so a mistake here cannot reach users, companies or job content.
* It writes a rollback .sql file BEFORE it commits, capturing the prior state of
  everything it is about to touch.

Corrections are written as `source='manual'`, which the Tier-2 writer skips
(Decision #10) -- so a judgment written here is permanent and the pipeline
cannot overwrite it.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import urllib.parse
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

# The skill lives at <repo>/.claude/skills/location-normalization/, so the repo
# root is four levels up. Importing the repo's own canonicalize() means a plan
# can never write a tuple the live pipeline would reject or re-render.
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))

from src.backend.api.services.location_canonicalize import (  # noqa: E402
    canonicalize_parts,
)

ENV_PATH = pathlib.Path.home() / ".config" / "jvn" / "location-writer.env"
ENV_KEY = "JVN_LOCATION_WRITER_DATABASE_URL"
REQUIRED_ROLE = "claude_location_writer"
VALID_KINDS = {"city", "region", "country", "remote"}


# ---------------------------------------------------------------- connection


def load_dsn() -> str:
    dsn = os.environ.get(ENV_KEY)
    if not dsn and ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line.startswith(ENV_KEY + "="):
                dsn = line.split("=", 1)[1].strip()
                break
    if not dsn:
        sys.exit(
            f"{ENV_KEY} is not set and {ENV_PATH} does not provide it.\n"
            f"This script will not fall back to a superuser DSN or to `railway run`."
        )

    user = urllib.parse.urlparse(dsn).username
    if user != REQUIRED_ROLE:
        sys.exit(
            f"refusing to run: DSN user is {user!r}, expected {REQUIRED_ROLE!r}.\n"
            f"The narrow role is the safety boundary -- do not point this at postgres."
        )
    return dsn


# ---------------------------------------------------------------- plan model


def canonical_spec(spec: dict) -> dict:
    """Validate + canonicalize one location spec from the plan."""
    kind = spec.get("kind")
    if kind not in VALID_KINDS:
        sys.exit(f"invalid kind {kind!r} in plan; expected one of {sorted(VALID_KINDS)}")
    parts = canonicalize_parts(
        kind=kind,
        canonical_name=spec.get("canonical_name") or "",
        city=spec.get("city"),
        region=spec.get("region"),
        country=spec.get("country"),
        remote_scope=spec.get("remote_scope"),
    )
    if not parts.canonical_name:
        sys.exit(
            f"spec {spec!r} canonicalizes to an empty label; supply enough structure "
            f"(a city, a country, or a remote scope)"
        )
    return {
        "canonical_name": parts.canonical_name,
        "kind": parts.kind,
        "city": parts.city,
        "region": parts.region,
        "country": parts.country,
        "remote_scope": parts.remote_scope,
    }


def load_plan(path: pathlib.Path) -> dict:
    plan = json.loads(path.read_text())
    for alias in plan.get("aliases", []):
        if not alias.get("raw_text"):
            sys.exit("every alias entry needs a raw_text")
        if not alias.get("locations"):
            sys.exit(
                f"alias {alias['raw_text']!r} has no locations. To remove a mapping "
                f"entirely, delete the alias by hand -- this script only rewrites."
            )
        alias["locations"] = [canonical_spec(s) for s in alias["locations"]]
    for merge in plan.get("merges", []):
        if merge.get("survivor_id") in merge.get("loser_ids", []):
            sys.exit(f"merge {merge!r} lists the survivor as its own loser")
    return plan


# ---------------------------------------------------------------- reads


def upsert_location(cur, spec: dict) -> int:
    cur.execute(
        "INSERT INTO locations (canonical_name, kind, city, region, country, remote_scope) "
        "VALUES (%(canonical_name)s, %(kind)s, %(city)s, %(region)s, %(country)s, %(remote_scope)s) "
        "ON CONFLICT ON CONSTRAINT uq_locations_canonical DO NOTHING RETURNING id",
        spec,
    )
    row = cur.fetchone()
    if row:
        return int(row["id"])
    cur.execute(
        "SELECT id FROM locations WHERE kind = %(kind)s "
        "AND city IS NOT DISTINCT FROM %(city)s AND region IS NOT DISTINCT FROM %(region)s "
        "AND country IS NOT DISTINCT FROM %(country)s "
        "AND remote_scope IS NOT DISTINCT FROM %(remote_scope)s",
        spec,
    )
    row = cur.fetchone()
    if not row:
        sys.exit(f"locations upsert conflicted but no matching row found for {spec!r}")
    return int(row["id"])


def sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


# ---------------------------------------------------------------- rollback


class Rollback:
    """Captures prior state and renders an undo script in DEPENDENCY order.

    Chronological order does NOT work here. `job_locations` and `alias_locations`
    both carry a FK to `locations`, so an undo that restores a job's tags before
    re-creating the merged-away `locations` row it pointed at fails with
    `violates foreign key constraint` and the whole rollback aborts -- exactly
    when you need it most. Statements are therefore bucketed and emitted as:

        locations -> location_aliases -> alias_locations -> job_locations

    Every snapshot is idempotent: the FIRST capture wins, so a row touched twice
    in one run (once by an alias rewrite, once by a merge) is restored to the
    state it had before the run started, not to some intermediate state.
    """

    def __init__(self) -> None:
        self._locations: dict[int, str] = {}
        self._aliases: dict[str, str] = {}
        self._alias_children: dict[str, list[dict]] = {}
        self._jobs: dict[str, list[dict]] = {}
        self._notes: list[str] = []

    def note(self, text: str) -> None:
        self._notes.append(f"-- {text}")

    def snapshot_location(self, cur, loc_id: int) -> None:
        if loc_id in self._locations:
            return
        cur.execute(
            "SELECT id, canonical_name, kind, city, region, country, remote_scope "
            "FROM locations WHERE id = %s",
            (loc_id,),
        )
        row = cur.fetchone()
        if not row:
            return
        self._locations[loc_id] = (
            "INSERT INTO locations (id, canonical_name, kind, city, region, country, "
            f"remote_scope) VALUES ({row['id']}, {sql_literal(row['canonical_name'])}, "
            f"{sql_literal(row['kind'])}, {sql_literal(row['city'])}, "
            f"{sql_literal(row['region'])}, {sql_literal(row['country'])}, "
            f"{sql_literal(row['remote_scope'])}) ON CONFLICT (id) DO NOTHING;"
        )

    def snapshot_alias(self, cur, raw_text: str) -> None:
        if raw_text in self._alias_children:
            return
        cur.execute(
            "SELECT source, confidence FROM location_aliases WHERE raw_text = %s",
            (raw_text,),
        )
        alias = cur.fetchone()
        if alias is None:
            # The alias did not exist before this run -- undo means removing it.
            self._aliases[raw_text] = (
                f"DELETE FROM location_aliases WHERE raw_text = {sql_literal(raw_text)};"
            )
        else:
            self._aliases[raw_text] = (
                "INSERT INTO location_aliases (raw_text, source, confidence) VALUES "
                f"({sql_literal(raw_text)}, {sql_literal(alias['source'])}, "
                f"{sql_literal(alias['confidence'])}) ON CONFLICT (raw_text) DO UPDATE "
                "SET source = EXCLUDED.source, confidence = EXCLUDED.confidence;"
            )
        cur.execute(
            "SELECT normalized_location_id, position FROM alias_locations "
            "WHERE raw_text = %s ORDER BY position",
            (raw_text,),
        )
        children = [dict(r) for r in cur.fetchall()]
        self._alias_children[raw_text] = children
        # Every location the alias pointed at must exist again before its rows do.
        for child in children:
            self.snapshot_location(cur, int(child["normalized_location_id"]))

    def prior_alias_locations(self, raw_text: str) -> list[dict]:
        """The alias's mapping as it was BEFORE this run (snapshot it first)."""
        return self._alias_children.get(raw_text, [])

    def snapshot_job(self, cur, job_id: str) -> None:
        if job_id in self._jobs:
            return
        cur.execute(
            "SELECT normalized_location_id, is_primary FROM job_locations "
            "WHERE job_listing_id = %s",
            (job_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        self._jobs[job_id] = rows
        for row in rows:
            self.snapshot_location(cur, int(row["normalized_location_id"]))

    def render(self, plan_path) -> str:
        out: list[str] = [
            "-- Rollback for a location-normalization apply run.",
            f"-- plan: {plan_path}",
            "-- Statements are ordered locations -> location_aliases -> alias_locations",
            "-- -> job_locations so the FKs on the child tables always resolve.",
            "BEGIN;",
        ]
        out.extend(self._notes)
        out.extend(self._locations.values())
        out.extend(self._aliases.values())
        for raw_text, children in self._alias_children.items():
            out.append(
                f"DELETE FROM alias_locations WHERE raw_text = {sql_literal(raw_text)};"
            )
            for child in children:
                out.append(
                    "INSERT INTO alias_locations (raw_text, normalized_location_id, position) "
                    f"VALUES ({sql_literal(raw_text)}, {child['normalized_location_id']}, "
                    f"{child['position']});"
                )
        for job_id, rows in self._jobs.items():
            out.append(
                f"DELETE FROM job_locations WHERE job_listing_id = {sql_literal(job_id)};"
            )
            for row in rows:
                out.append(
                    "INSERT INTO job_locations (job_listing_id, normalized_location_id, "
                    f"is_primary) VALUES ({sql_literal(job_id)}, "
                    f"{row['normalized_location_id']}, {sql_literal(row['is_primary'])});"
                )
        out.append("COMMIT;")
        return "\n".join(out) + "\n"


# ---------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", required=True, type=pathlib.Path,
                    help="JSON repair plan (see SKILL.md \u00a75)")
    ap.add_argument("--apply", action="store_true",
                    help="COMMIT. Without this the transaction is rolled back.")
    args = ap.parse_args()

    plan = load_plan(args.plan)
    dsn = load_dsn()

    aliases = plan.get("aliases", [])
    merges = plan.get("merges", [])
    orphans = plan.get("delete_orphans", [])
    renormalize = plan.get("renormalize_jobs", [])

    mode = "APPLY (will COMMIT)" if args.apply else "DRY-RUN (will ROLLBACK)"
    print(f"=== location-normalization apply \u2014 {mode} ===")
    print(f"plan: {args.plan}")
    print(f"  {len(aliases)} alias rewrite(s), {len(merges)} merge(s), "
          f"{len(orphans)} orphan delete(s), {len(renormalize)} job re-normalization(s)")
    print()

    rb = Rollback()
    conn = psycopg2.connect(dsn, cursor_factory=RealDictCursor)
    try:
        cur = conn.cursor()
        touched_jobs: set[str] = set()

        # ---- 1. alias rewrites -------------------------------------------
        for alias in aliases:
            raw = alias["raw_text"]
            rb.snapshot_alias(cur, raw)
            before_ids = [
                c["normalized_location_id"] for c in rb.prior_alias_locations(raw)
            ]

            wanted_ids = [upsert_location(cur, s) for s in alias["locations"]]
            seen: set[int] = set()
            wanted_ids = [i for i in wanted_ids if not (i in seen or seen.add(i))]

            labels = " | ".join(s["canonical_name"] for s in alias["locations"])
            print(f"alias {raw!r}")
            print(f"    before: {len(before_ids)} location(s) {before_ids}")
            print(f"    after : {len(wanted_ids)} location(s) {wanted_ids}  -> {labels}")
            if alias.get("reason"):
                print(f"    reason: {alias['reason']}")

            cur.execute(
                "INSERT INTO location_aliases (raw_text, source, confidence) "
                "VALUES (%s, 'manual', 1.0) "
                "ON CONFLICT (raw_text) DO UPDATE SET source = 'manual', confidence = 1.0",
                (raw,),
            )
            cur.execute("DELETE FROM alias_locations WHERE raw_text = %s", (raw,))
            for position, loc_id in enumerate(wanted_ids):
                cur.execute(
                    "INSERT INTO alias_locations (raw_text, normalized_location_id, position) "
                    "VALUES (%s, %s, %s)",
                    (raw, loc_id, position),
                )

            # Retag OPEN jobs carrying this raw string so the fix is visible now
            # rather than on the next scrape. lower(btrim(...)) approximates
            # normalize_string (which also folds NFKC, unicode dashes/quotes and
            # whitespace runs); the stragglers it misses are fixed anyway on their
            # next normalization, via a Tier-1 hit on the manual alias just written.
            cur.execute(
                "SELECT id FROM job_listings "
                "WHERE status = 'OPEN' AND lower(btrim(location)) = %s",
                (raw,),
            )
            job_ids = [r["id"] for r in cur.fetchall()]
            print(f"    retagging {len(job_ids)} OPEN job(s)")
            for job_id in job_ids:
                rb.snapshot_job(cur, job_id)
                touched_jobs.add(job_id)
                cur.execute("DELETE FROM job_locations WHERE job_listing_id = %s", (job_id,))
                for position, loc_id in enumerate(wanted_ids):
                    cur.execute(
                        "INSERT INTO job_locations (job_listing_id, normalized_location_id, "
                        "is_primary) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                        (job_id, loc_id, position == 0),
                    )
            print()

        # ---- 2. merges ---------------------------------------------------
        for merge in merges:
            survivor = int(merge["survivor_id"])
            cur.execute("SELECT canonical_name FROM locations WHERE id = %s", (survivor,))
            srow = cur.fetchone()
            if not srow:
                sys.exit(f"merge survivor id {survivor} does not exist")
            print(f"merge -> {survivor} ({srow['canonical_name']!r})")
            rb.snapshot_location(cur, survivor)

            for loser in [int(x) for x in merge.get("loser_ids", [])]:
                cur.execute("SELECT canonical_name FROM locations WHERE id = %s", (loser,))
                lrow = cur.fetchone()
                if not lrow:
                    print(f"    loser {loser} already gone; skipping")
                    continue
                rb.snapshot_location(cur, loser)

                # Snapshot EVERY row that references the loser before touching it.
                # A job or alias reached only by a merge is not covered by the
                # alias-rewrite snapshots above, and would otherwise be unrecoverable.
                cur.execute(
                    "SELECT DISTINCT job_listing_id FROM job_locations "
                    "WHERE normalized_location_id IN (%s, %s)",
                    (loser, survivor),
                )
                for r in cur.fetchall():
                    rb.snapshot_job(cur, r["job_listing_id"])
                cur.execute(
                    "SELECT DISTINCT raw_text FROM alias_locations "
                    "WHERE normalized_location_id IN (%s, %s)",
                    (loser, survivor),
                )
                for r in cur.fetchall():
                    rb.snapshot_alias(cur, r["raw_text"])

                # OR is_primary onto the survivor BEFORE dropping colliders.
                cur.execute(
                    "UPDATE job_locations s SET is_primary = TRUE FROM job_locations l "
                    "WHERE s.job_listing_id = l.job_listing_id "
                    "AND s.normalized_location_id = %s AND l.normalized_location_id = %s "
                    "AND l.is_primary",
                    (survivor, loser),
                )
                cur.execute(
                    "DELETE FROM job_locations jl WHERE jl.normalized_location_id = %s "
                    "AND EXISTS (SELECT 1 FROM job_locations s "
                    "WHERE s.job_listing_id = jl.job_listing_id "
                    "AND s.normalized_location_id = %s)",
                    (loser, survivor),
                )
                cur.execute(
                    "UPDATE job_locations SET normalized_location_id = %s "
                    "WHERE normalized_location_id = %s",
                    (survivor, loser),
                )
                cur.execute(
                    "DELETE FROM alias_locations al WHERE al.normalized_location_id = %s "
                    "AND EXISTS (SELECT 1 FROM alias_locations s WHERE s.raw_text = al.raw_text "
                    "AND s.normalized_location_id = %s)",
                    (loser, survivor),
                )
                cur.execute(
                    "UPDATE alias_locations SET normalized_location_id = %s "
                    "WHERE normalized_location_id = %s",
                    (survivor, loser),
                )
                cur.execute("DELETE FROM locations WHERE id = %s", (loser,))
                print(f"    merged {loser} ({lrow['canonical_name']!r})")
            print()

        # ---- 3. orphan deletes -------------------------------------------
        for loc_id in [int(x) for x in orphans]:
            cur.execute(
                "SELECT (SELECT count(*) FROM job_locations WHERE normalized_location_id = %s) AS j,"
                "       (SELECT count(*) FROM alias_locations WHERE normalized_location_id = %s) AS a",
                (loc_id, loc_id),
            )
            refs = cur.fetchone()
            if refs["j"] or refs["a"]:
                sys.exit(
                    f"refusing to delete location {loc_id}: still referenced "
                    f"({refs['j']} job link(s), {refs['a']} alias link(s))"
                )
            cur.execute("SELECT canonical_name FROM locations WHERE id = %s", (loc_id,))
            row = cur.fetchone()
            if not row:
                continue
            rb.snapshot_location(cur, loc_id)
            cur.execute("DELETE FROM locations WHERE id = %s", (loc_id,))
            print(f"deleted orphan {loc_id} ({row['canonical_name']!r})")

        # ---- 4. explicit re-normalizations -------------------------------
        for job_id in renormalize:
            cur.execute(
                "UPDATE job_listings SET normalization_status = NULL WHERE id = %s", (job_id,)
            )
        if renormalize:
            print(f"cleared normalization_status on {len(renormalize)} job(s)")
            rb.note(
                f"normalization_status was cleared on {len(renormalize)} job(s); the "
                "pipeline re-derives it on the next scan, so there is nothing to undo"
            )

        if touched_jobs:
            print(f"\nretagged {len(touched_jobs)} distinct OPEN job(s) in total")

        rollback_path = args.plan.with_suffix(".rollback.sql")
        rollback_path.write_text(rb.render(args.plan))
        print(f"rollback written to {rollback_path}")

        if args.apply:
            conn.commit()
            print("COMMITTED.")
        else:
            conn.rollback()
            print("DRY-RUN \u2014 rolled back. Re-run with --apply to commit.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
