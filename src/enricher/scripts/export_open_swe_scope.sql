-- P0-4 — export the OPEN software_engineering scope from JVN's prod Postgres as
-- NDJSON, one object per line, for `cli subcategory-scope-import --json-file`.
--
-- ⚠ WHY THIS EXISTS AT ALL — verified, not stylistic:
--   The enricher provably has NO OPEN/CLOSED signal of its own.
--     * `inbox.status` is PIPELINE state, not job state:
--       CHECK (status IN ('claimed','cleaned','enriched','sent','failed'))  -- store.py:75-76
--     * JVN's `_JOB_PROJECTION` (internal_enrichment.py:61-72) narrows `details`
--       to exactly `department` + `experience_level`, so JVN has NEVER shipped
--       the enricher a status or company tags.
--   Backfilling CLOSED jobs is pure waste, so the scope must come from JVN.
--
-- ⚠ REFRESH POLICY: this is a POINT-IN-TIME export and jobs open and close
-- overnight. Re-run the export AND the import immediately before each night's
-- run. The importer refuses (exit 2) on a scope older than SCOPE_MAX_AGE_HOURS
-- (24) or on an empty scope, because a silently-empty scope makes `--open-only`
-- a no-op that reports success.
--
-- Usage (read-only; run from the prod checkout or any psql with prod creds):
--   psql "$DATABASE_URL" -At -f scripts/export_open_swe_scope.sql > /tmp/open_swe_scope.ndjson
--   uv run python -m job_enricher.cli subcategory-scope-import --json-file /tmp/open_swe_scope.ndjson

SELECT json_build_object(
         'source_id', jl.source_id,
         'job_listing_id', jl.id::text
       )::text
FROM job_listings jl
WHERE jl.status = 'OPEN'
  AND jl.enrichment_category = 'software_engineering'
ORDER BY jl.source_id, jl.id;
