-- One-time data fix: re-OPEN 5 jobs confirmed LIVE on their source ATS
-- after a Playwright sweep on 2026-05-21. See docs note in PR.
--
-- All 5 jobs are in CLOSED state with consecutive_misses=2 in prod, but
-- Playwright shows the listings are still actively recruiting. Two are
-- Eightfold/Netflix (consistent with the Eightfold dedup-collision class
-- of bug fixed in PR #126); three are Lever, which is a previously
-- unidentified failure pattern worth investigating separately.
--
-- Run this BEFORE the next */30 cron tick or `consecutive_misses` will
-- need to be incremented twice again before the jobs flip back to CLOSED
-- if the underlying scraper bug is still present.
--
-- Apply with:
--   railway run -- psql -f scripts/one_off/2026-05-21_reopen_false_closed.sql
-- or via the Railway Postgres dashboard SQL console.

BEGIN;

UPDATE job_listings
SET
    status = 'OPEN',
    closed_on = NULL,
    consecutive_misses = 0
WHERE
    (source_id, id) IN (
        -- Eightfold / Netflix (still live; both posted within last 60 days)
        ('eightfold_api', '790315029228'),  -- Title Producer, Content Localization
        ('eightfold_api', '790314312838'),  -- Principal Counsel, Cybersecurity Legal
        -- Lever / zoox (jobs.lever.co page renders with APPLY button)
        ('lever_api', '2ef5b0c9-04af-4ece-9f3e-16a07be96151'),  -- Salesforce CRM Architect
        ('lever_api', '0686875b-6d06-49aa-b9f2-772f756d5235'),  -- Full Stack SWE, Ops Apps
        -- Lever / spotify
        ('lever_api', 'aa4220b2-b5fd-4db6-9ef6-2b34fde9f6ef')   -- Manager, Ads Partner Strategy
    )
    AND status = 'CLOSED';

-- Sanity check: should report exactly 5 rows.
\echo Expected 5 rows updated.

COMMIT;
