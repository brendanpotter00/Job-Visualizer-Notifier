#!/usr/bin/env bash
# Create jobscraper_e2e from a clone of jobscraper_pr243 if it doesn't exist
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

set -euo pipefail

SOURCE_DB="jobscraper_pr243"
TARGET_DB="jobscraper_e2e"
CONTAINER="${E2E_PG_CONTAINER:-jobscraper-postgres}"
PGUSER="postgres"
REFRESH=0

for arg in "$@"; do
  case "$arg" in
    --refresh) REFRESH=1 ;;
  esac
done

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

echo "ensure_db.sh: done — public companies=$COMPANIES_COUNT user companies=$USER_COUNT"

if [ "$USER_COUNT" != "0" ]; then
  echo "ensure_db.sh: WARNING — expected 0 visibility='user' rows after scrub, found $USER_COUNT" >&2
fi
