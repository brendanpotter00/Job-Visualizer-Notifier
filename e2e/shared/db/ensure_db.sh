#!/usr/bin/env bash
# Provision a section's e2e database from jobscraper_pr243 if it doesn't exist
# (PLAN.md §2, §12 step 1). Idempotent: does nothing on a second run unless
# --refresh is passed.
#
# SOURCE_DB is READ-ONLY here — only ever SELECTed from (via pg_dump). Never
# written to, never dropped, never truncated.
#
# Uses `pg_dump`/`pg_restore`/`createdb`/`dropdb` INSIDE the jobscraper-postgres
# docker container (docker-compose.yml's container_name) rather than requiring
# those client binaries on the host, since this laptop doesn't have the
# Postgres client tools installed locally — only the Python driver.
#
# Usage: ensure_db.sh [--refresh] [--target-db NAME] [--schema-only]
#
#   --target-db NAME  which database to provision. Defaults to jobscraper_e2e,
#                     which is what `add-companies` and `live-view` share.
#                     A section that SEEDS ROWS must pass its own name: two
#                     sections writing fixtures into one database is the same
#                     class of bug as two runs sharing one stack.
#   --schema-only     clone the SCHEMA plus the small seeded dimension tables,
#                     and none of the 46k job rows / 725 MB of job_listings.
#                     17s and ~110 MB instead of minutes and 760 MB. For a
#                     section whose every assertion is about rows IT seeds, the
#                     corpus is not evidence — it is noise that has to be
#                     scoped out of every query. `add-companies` needs the real
#                     corpus (AC-06 matches titles against the published
#                     fleet); `subcategories` needs the opposite.
#
# The two modes agree on everything after the restore: both run `alembic
# upgrade head` against the result and both run `_scrub.py`, so a schema-only
# database is at the same migration head with the same seeded taxonomy.

set -euo pipefail

SOURCE_DB="jobscraper_pr243"
TARGET_DB="jobscraper_e2e"
CONTAINER="${E2E_PG_CONTAINER:-jobscraper-postgres}"
PGUSER="postgres"
REFRESH=0
SCHEMA_ONLY=0

# Tables whose ROWS a --schema-only clone still needs. All small, all
# dimension/reference data, and every one of them is read by the app on a path
# a section is likely to exercise:
#   alembic_version              - or `alembic upgrade head` replays from zero
#   job_categories / job_levels  - GET /api/jobs/facets, and the FK targets
#                                  enrichment_category / enrichment_level point at
#   locations / *_aliases        - the location filter's catalog
# `job_subcategories` is deliberately NOT here: the seed migration
# (5a7d3e9c1b46) inserts all 17 rows itself, so copying them would only create
# a second, staler source for the same data.
SCHEMA_ONLY_DATA_TABLES=(
  alembic_version
  job_categories
  job_levels
  locations
  location_aliases
  alias_locations
)

while [ $# -gt 0 ]; do
  case "$1" in
    --refresh) REFRESH=1; shift ;;
    --target-db) TARGET_DB="$2"; shift 2 ;;
    --schema-only) SCHEMA_ONLY=1; shift ;;
    *) echo "ensure_db.sh: unknown arg $1" >&2; exit 1 ;;
  esac
done

# A gate that *can* point at the owner's database once will point at it at 2am
# (PLAN.md §2). The clone TARGET is the one name this script drops and
# recreates, so it is the one that has to be fenced.
case "$TARGET_DB" in
  jobscraper_e2e|jobscraper_e2e_*) : ;;
  *)
    echo "ensure_db.sh: refusing --target-db '$TARGET_DB' — an e2e target must be" \
      "'jobscraper_e2e' or 'jobscraper_e2e_<section>'. This script DROPS the target" \
      "on --refresh; it may not be aimed at anything else." >&2
    exit 1 ;;
esac
if [ "$TARGET_DB" = "$SOURCE_DB" ]; then
  echo "ensure_db.sh: refusing to clone $SOURCE_DB onto itself" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

_psql() {
  docker exec -i "$CONTAINER" psql -U "$PGUSER" -v ON_ERROR_STOP=1 "$@"
}

_db_exists() {
  local name="$1"
  docker exec "$CONTAINER" psql -U "$PGUSER" -tAc \
    "SELECT 1 FROM pg_database WHERE datname = '${name}'" | grep -q 1
}

if ! docker exec "$CONTAINER" pg_isready -U "$PGUSER" >/dev/null 2>&1; then
  echo "ensure_db.sh: postgres container '$CONTAINER' is not reachable" >&2
  exit 1
fi

if ! _db_exists "$SOURCE_DB"; then
  echo "ensure_db.sh: source database '$SOURCE_DB' does not exist — cannot clone" >&2
  exit 1
fi

if [ "$REFRESH" = "1" ] && _db_exists "$TARGET_DB"; then
  echo "ensure_db.sh: --refresh — dropping existing $TARGET_DB"
  # Terminate any lingering connections (a prior crashed run) before DROP.
  docker exec "$CONTAINER" psql -U "$PGUSER" -tAc \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${TARGET_DB}' AND pid <> pg_backend_pid()" >/dev/null || true
  docker exec "$CONTAINER" dropdb -U "$PGUSER" "$TARGET_DB"
fi

if _db_exists "$TARGET_DB"; then
  echo "ensure_db.sh: $TARGET_DB already exists — skipping clone (use --refresh to force)"
elif [ "$SCHEMA_ONLY" = "1" ]; then
  echo "ensure_db.sh: SCHEMA-ONLY clone $SOURCE_DB -> $TARGET_DB (no job_listings rows)"
  docker exec "$CONTAINER" createdb -U "$PGUSER" "$TARGET_DB"
  START=$(date +%s)
  docker exec "$CONTAINER" bash -c \
    "pg_dump -U $PGUSER --schema-only --no-owner --no-acl '$SOURCE_DB' | psql -U $PGUSER -q -d '$TARGET_DB'" \
    || echo "ensure_db.sh: schema restore reported warnings (often benign — extensions/roles); continuing"
  # Plain text + psql rather than -Fc + pg_restore for the data half: the
  # dimension tables carry circular FKs (job_levels.parent_slug is self-
  # referential), which pg_dump warns about on a --data-only dump and which a
  # per-table restore order cannot satisfy. A single psql session applies the
  # whole INSERT stream inside one transaction-per-statement run where the
  # deferred constraints settle.
  DATA_TABLE_ARGS=""
  for t in "${SCHEMA_ONLY_DATA_TABLES[@]}"; do
    DATA_TABLE_ARGS="$DATA_TABLE_ARGS -t $t"
  done
  docker exec "$CONTAINER" bash -c \
    "pg_dump -U $PGUSER --data-only --no-owner --no-acl $DATA_TABLE_ARGS '$SOURCE_DB' | psql -U $PGUSER -q -d '$TARGET_DB'" \
    || echo "ensure_db.sh: dimension-data restore reported warnings; continuing"
  END=$(date +%s)
  echo "ensure_db.sh: schema-only clone took $((END - START))s"
else
  echo "ensure_db.sh: cloning $SOURCE_DB -> $TARGET_DB via pg_dump -Fc | pg_restore"
  docker exec "$CONTAINER" createdb -U "$PGUSER" "$TARGET_DB"
  START=$(date +%s)
  docker exec "$CONTAINER" bash -c \
    "pg_dump -U $PGUSER -Fc --no-owner --no-acl '$SOURCE_DB' | pg_restore -U $PGUSER --no-owner --no-acl -d '$TARGET_DB'" \
    || echo "ensure_db.sh: pg_restore reported warnings (often benign — extensions/roles); continuing"
  END=$(date +%s)
  echo "ensure_db.sh: clone took $((END - START))s"
fi

echo "ensure_db.sh: alembic upgrade head against $TARGET_DB"
(
  cd "$REPO_ROOT"
  DATABASE_URL="postgresql://postgres:postgres@localhost:5432/${TARGET_DB}" \
    "$REPO_ROOT/.venv/bin/python" -m alembic upgrade head
)

echo "ensure_db.sh: scrubbing inherited visibility='user' rows and stale procrastinate_jobs"
"$REPO_ROOT/.venv/bin/python" "$SCRIPT_DIR/_scrub.py" "$TARGET_DB"

COMPANIES_COUNT=$(docker exec "$CONTAINER" psql -U "$PGUSER" -d "$TARGET_DB" -tAc \
  "SELECT count(*) FROM companies WHERE visibility='public'")
USER_COUNT=$(docker exec "$CONTAINER" psql -U "$PGUSER" -d "$TARGET_DB" -tAc \
  "SELECT count(*) FROM companies WHERE visibility='user'")
SUBCAT_COUNT=$(docker exec "$CONTAINER" psql -U "$PGUSER" -d "$TARGET_DB" -tAc \
  "SELECT count(*) FROM job_subcategories")

echo "ensure_db.sh: done ($TARGET_DB) — public companies=$COMPANIES_COUNT" \
  "user companies=$USER_COUNT subcategory dimension rows=$SUBCAT_COUNT"

# The seeded taxonomy is the one piece of reference data BOTH modes depend on
# and neither copies: it arrives via migration 5a7d3e9c1b46. Seventeen is the
# count the subcategories section's whole case table is written against, so a
# silent 0 here would make every one of its filters vacuously empty.
if [ "$SUBCAT_COUNT" != "17" ]; then
  echo "ensure_db.sh: WARNING — expected 17 job_subcategories rows after" \
    "'alembic upgrade head', found $SUBCAT_COUNT" >&2
fi

if [ "$USER_COUNT" != "0" ]; then
  echo "ensure_db.sh: WARNING — expected 0 visibility='user' rows after scrub, found $USER_COUNT" >&2
fi
