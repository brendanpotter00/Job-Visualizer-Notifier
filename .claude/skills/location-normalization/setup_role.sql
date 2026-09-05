-- One-time setup for the `location-normalization` skill's write path.
--
-- Creates a narrow role that can repair the location cache and NOTHING else.
-- The skill's apply.py refuses to run as any other user (it asks the SERVER via
-- current_user, not the DSN string), so this role IS the safety boundary: the
-- worst a bug can do is write wrong location tags, which the skill itself
-- repairs.
--
-- RUN IT (from the repo root, as the Railway superuser):
--
--     railway run -- sh -c 'psql "$DATABASE_URL" \
--       -v pw="$(openssl rand -base64 32 | tr -d /=+ | cut -c1-32)" \
--       -f .claude/skills/location-normalization/setup_role.sql'
--
-- The LAST statement prints the full DSN. Copy it straight into
-- ~/.config/jvn/location-writer.env as:
--
--     JVN_LOCATION_WRITER_DATABASE_URL=<the printed DSN>
--
-- then `chmod 600` that file. Re-running rotates the password, which
-- INVALIDATES the stored DSN — you must copy the new one.

\set ON_ERROR_STOP on

BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'claude_location_writer') THEN
        RAISE NOTICE 'role claude_location_writer already exists; rotating password';
    ELSE
        EXECUTE 'CREATE ROLE claude_location_writer LOGIN';
        RAISE NOTICE 'created role claude_location_writer';
    END IF;
END
$$;

ALTER ROLE claude_location_writer WITH LOGIN PASSWORD :'pw';

GRANT CONNECT ON DATABASE :"DBNAME" TO claude_location_writer;
GRANT USAGE ON SCHEMA public TO claude_location_writer;

-- Undo the over-broad grant an earlier revision of this file applied, so
-- re-running actually NARROWS an existing role rather than leaving it wide.
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM claude_location_writer;

-- READ: exactly the five tables the skill touches.
--
-- NOT `GRANT SELECT ON ALL TABLES`. That is what an earlier revision did, and it
-- handed this role every row of `users` (including `email` and `auth0_id`),
-- `feedback` (user_email, message), `admins` and `user_saved_filters` -- while
-- the file's own comment claimed those were "deliberately not granted" and
-- SKILL.md told the operator the role "cannot reach users". True for writes,
-- false for reads, on a long-lived password in a plaintext file driving an
-- unattended loop.
--
-- Also deliberately NO `ALTER DEFAULT PRIVILEGES`: that would auto-grant SELECT
-- on every FUTURE table to this role, which is the opposite of the goal.
GRANT SELECT ON TABLE
    public.locations,
    public.location_aliases,
    public.alias_locations,
    public.job_locations,
    public.job_listings
    TO claude_location_writer;

-- WRITE: exactly the four location tables.
GRANT INSERT, UPDATE, DELETE ON TABLE
    public.locations,
    public.location_aliases,
    public.alias_locations,
    public.job_locations
    TO claude_location_writer;

-- locations.id is a serial, so inserts need the sequence.
GRANT USAGE, SELECT ON SEQUENCE public.locations_id_seq TO claude_location_writer;

-- ONE column on job_listings, so the skill can hand a job back to the
-- normalization safety-net. Nothing else on that table is writable.
GRANT UPDATE (normalization_status) ON TABLE public.job_listings
    TO claude_location_writer;

COMMIT;

-- ---------------------------------------------------------------- verification
-- Reads EVERY privilege type, not just the write ones. The earlier version
-- filtered to INSERT/UPDATE/DELETE, so a blanket SELECT could never appear in
-- it -- while SKILL.md told the operator "if it lists anything else, stop and
-- investigate". A check that structurally cannot fail is worse than no check.
--
-- EXPECTED, exactly:
--   alias_locations   DELETE,INSERT,SELECT,UPDATE
--   job_listings      SELECT
--   job_locations     DELETE,INSERT,SELECT,UPDATE
--   location_aliases  DELETE,INSERT,SELECT,UPDATE
--   locations         DELETE,INSERT,SELECT,UPDATE
-- Any other table name on this list is a problem. `users`, `feedback` and
-- `admins` must NOT appear.
SELECT table_name,
       string_agg(DISTINCT privilege_type, ',' ORDER BY privilege_type) AS privs
FROM information_schema.table_privileges
WHERE grantee = 'claude_location_writer'
  AND table_schema = 'public'
GROUP BY table_name
ORDER BY table_name;

-- The single column grant (column privileges live in a separate view).
SELECT table_name, column_name, privilege_type
FROM information_schema.column_privileges
WHERE grantee = 'claude_location_writer'
  AND table_schema = 'public'
  AND table_name = 'job_listings'
ORDER BY column_name;

-- Belt and braces: this must return ZERO rows.
SELECT 'LEAK: ' || table_name AS problem
FROM information_schema.table_privileges
WHERE grantee = 'claude_location_writer'
  AND table_schema = 'public'
  AND table_name NOT IN ('locations', 'location_aliases', 'alias_locations',
                         'job_locations', 'job_listings');

-- ---------------------------------------------------------------- the DSN
-- Printed here because nothing else in this script reveals the generated
-- password, and the runbook needs it. Copy the value into
-- ~/.config/jvn/location-writer.env (chmod 600).
SELECT format(
    'postgresql://claude_location_writer:%s@%s:%s/%s',
    :'pw',
    coalesce(nullif(inet_server_addr()::text, ''), 'localhost'),
    coalesce(nullif(inet_server_port()::text, ''), '5432'),
    current_database()
) AS "JVN_LOCATION_WRITER_DATABASE_URL";
