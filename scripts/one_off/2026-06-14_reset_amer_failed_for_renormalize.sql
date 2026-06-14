-- One-time data fix: re-queue the `AMER` job listings that were marked
-- normalization_status='failed' so they re-normalize to the United States.
--
-- Background: a bare "AMER" location used to come back from the Tier-2 LLM
-- BELOW the 0.5 confidence floor, so those jobs were marked 'failed' — a
-- terminal state the scan_unnormalized safety-net never retries. This PR adds a
-- SYSTEM_PROMPT rule mapping the macro-region code 'AMER' -> United States
-- (kind='country', country='US') with high confidence, so the pipeline now
-- normalizes it correctly (verified live: AMER -> US @ 0.92).
--
-- Why this script is needed: the code fix only helps rows that get RE-processed.
-- scan_unnormalized only re-defers rows where normalization_status IS NULL, so
-- the already-'failed' rows are skipped forever. Flipping them back to NULL lets
-- the periodic safety-net (every 5 min, throttled to SCAN_LIMIT/tick) pick them
-- up and run them through the now-fixed pipeline. The first one caches the
-- 'amer' -> US alias; the rest are Tier-1 cache hits (no extra LLM spend).
--
-- Scope is intentionally AMER-only (NOT every 'failed' row): other failures
-- (e.g. 'Weave HQ', blank locations) are genuinely un-normalizable and would
-- just re-fail, burning LLM calls. AMER rows already at status NULL are NOT
-- touched here — they auto-recover on the next scan tick with no action.
--
-- ORDER OF OPERATIONS: run this ONLY AFTER the PR is deployed. If you run it
-- before the prompt fix is live in prod, the rows will just re-fail.
--
-- Prod count on 2026-06-14: 2 failed AMER rows (cloudflare x1, supabase x1).
-- Idempotent: re-running matches nothing once the rows are NULL/done.
--
-- Apply with:
--   railway run -- psql -f scripts/one_off/2026-06-14_reset_amer_failed_for_renormalize.sql
-- or paste into the Railway Postgres dashboard SQL console.
--
-- Dry-run first (optional) — counts what WOULD be reset:
--   SELECT company, location, count(*)
--   FROM job_listings
--   WHERE normalization_status = 'failed' AND upper(btrim(location)) = 'AMER'
--   GROUP BY company, location;

BEGIN;

UPDATE job_listings
SET normalization_status = NULL
WHERE normalization_status = 'failed'
  AND upper(btrim(location)) = 'AMER';

-- Sanity check: expected ~2 rows on prod as of 2026-06-14 (cloudflare, supabase).
\echo Reset AMER failed rows to NULL (expected ~2 on prod 2026-06-14).

COMMIT;
