-- One-time data fix: re-OPEN 2 Eightfold/Netflix jobs confirmed LIVE on
-- their source ATS after a Playwright sweep on 2026-05-21. See PR #129.
--
-- Both jobs are in CLOSED state with consecutive_misses=2 in prod, but
-- Playwright shows the listings are still actively recruiting and posted
-- within the last 60 days. Consistent with the Eightfold dedup-collision
-- class of bug fixed in PR #126.
--
-- The Playwright sweep also identified 3 Lever jobs that are technically
-- still live on the source ATS, but they have been REMOVED from the
-- public Lever job board (i.e., live job URL works if you have the link,
-- but they don't appear in any board search). The product decision is to
-- treat "not publicly listed" as effectively CLOSED — those 3 are NOT
-- being re-OPENed. See feedback memory `unlisted_jobs_treated_as_closed`.
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
        ('eightfold_api', '790314312838')   -- Principal Counsel, Cybersecurity Legal
    )
    AND status = 'CLOSED';

-- Sanity check: should report exactly 2 rows.
\echo Expected 2 rows updated.

COMMIT;
