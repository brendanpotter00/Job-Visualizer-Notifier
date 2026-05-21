-- One-time data fix: re-OPEN 8 jobs confirmed LIVE on their source ATS
-- after a Playwright sweep on 2026-05-21.
--
-- Context: the 2026-05-21 onesecondswe-backend-audit ran Playwright probes
-- against the audit's CLOSED-job samples and surfaced 8 jobs that still
-- render their role page (i.e., are recruiting, not closed). All 8 have
-- ``consecutive_misses=2`` (= ``MISSED_RUN_THRESHOLD``) in prod, so they
-- were closed by the close-detection path despite being live.
--
-- All 8 were re-confirmed live via Playwright at the time this script
-- was written:
--
--   Apple (5):
--     200555687-3543 — RF System Integration Engineer
--     200593548-0157 — SoC Characterization Product Engineer
--     200543111-0836 — Product Design Engineer
--     200592135-0836 — Platform and Frameworks Software Engineer, SEAR
--     200592169-0836 — DFM PCBA Engineer
--
--   Eightfold/Netflix (3):
--     790314573041 — Senior Payroll Specialist - APAC
--     790315029228 — Title Producer, Content Localization - Film & Animation
--     790314312838 — Principal Counsel, Cybersecurity Legal
--
-- The audit's Eightfold sample of 5 had 2 jobs that the Playwright probe
-- showed rendering as "Careers at Netflix" (generic) rather than the role
-- page — those (790315914390, 790313628221) are correctly CLOSED and are
-- NOT included in this reopen. Confirming-correctly-closed-jobs are not
-- re-OPENed.
--
-- ROOT CAUSE: see ``docs/incidents/2026-05-21-apple-eightfold-false-close/``
-- (when written). The close-detection algorithm in
-- ``scripts/shared/incremental.py`` treated "missing from a single scrape's
-- output" as a sufficient signal for CLOSED, with no per-job URL re-
-- verification. For sources with set-instability (Eightfold's offset
-- pagination, Apple's HTML pagination) this produced a steady trickle of
-- false-closes at exactly ``consecutive_misses=2``. Layer 1 of the fix
-- adds a URL verifier gate before the close transition; Layer 2 makes
-- Eightfold pagination more robust by dropping the unsafe "partial page =
-- end of data" heuristic. This SQL is the data-patch for the rows the
-- bug already corrupted.
--
-- RUN ORDER: ONLY run this AFTER Layer 1 + Layer 2 are deployed to prod
-- and at least one fan-out tick has shown clean Apple + Eightfold runs.
-- If you run this BEFORE the fix is live, the next fan-out tick will
-- false-close the same rows again within 2 ticks (60 minutes).
--
-- Apply with:
--   railway run -- psql -f scripts/one_off/2026-05-21_reopen_apple_eightfold_false_closed.sql
-- or via the Railway Postgres dashboard SQL console.

BEGIN;

UPDATE job_listings
SET
    status = 'OPEN',
    closed_on = NULL,
    consecutive_misses = 0,
    -- Bump last_seen_at so the next fan-out tick treats these rows as
    -- recently-observed instead of immediately re-incrementing misses.
    -- Use bare NOW() (timestamptz) — `NOW() AT TIME ZONE 'UTC'` + ::text
    -- drops the timezone tag and re-coerces under the session timezone
    -- (root CLAUDE.md gotcha #8). The job_listings.last_seen_at column
    -- is timestamptz and accepts NOW() directly.
    last_seen_at = NOW()
WHERE
    (source_id, id) IN (
        -- Apple (5)
        ('apple_scraper', '200555687-3543'),
        ('apple_scraper', '200593548-0157'),
        ('apple_scraper', '200543111-0836'),
        ('apple_scraper', '200592135-0836'),
        ('apple_scraper', '200592169-0836'),
        -- Eightfold / Netflix (3, the audit-confirmed-LIVE subset)
        ('eightfold_api', '790314573041'),
        ('eightfold_api', '790315029228'),
        ('eightfold_api', '790314312838')
    )
    AND status = 'CLOSED';

-- Sanity check: should report exactly 8 rows.
\echo Expected 8 rows updated.

COMMIT;

-- POST-RUN VERIFICATION:
--   1. Query: SELECT source_id, id, status, consecutive_misses, last_seen_at
--             FROM job_listings
--             WHERE (source_id, id) IN (the 8 pairs above);
--      All rows should show status='OPEN', consecutive_misses=0.
--   2. Watch the next 2 fan-out ticks (60 minutes) — these 8 rows should
--      either remain OPEN (verifier sees them on Apple/Eightfold) or get
--      their consecutive_misses incremented to 1 then 2 (verifier returns
--      "dead", which is the correct behavior if the jobs were genuinely
--      closed between the audit and now).
--   3. If any of the 8 re-flip to CLOSED, that's a signal Layer 1's
--      verifier is misclassifying them — investigate before re-running
--      this SQL.
