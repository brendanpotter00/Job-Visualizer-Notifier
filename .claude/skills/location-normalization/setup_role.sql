-- One-time setup for the `location-normalization` skill's write path.
--
-- Creates a narrow role that can repair the location cache and NOTHING else.
-- The skill's apply.py refuses to run as any other user, so this role IS the
-- safety boundary: the worst a bug can do is write wrong location tags, which
-- the skill itself repairs. It cannot reach users, companies, or job content.
--
-- RUN IT (from the repo root, as the Railway superuser):
--
--     railway run -- sh -c 'psql "$DATABASE_URL" \
--       -v pw="$(openssl rand -base64 32 | tr -d /=+ | cut -c1-32)" \
--       -f .claude/skills/location-normalization/setup_role.sql'
--
-- Then store the DSN it prints (see the last SELECT) at
-- ~/.config/jvn/location-writer.env, mode 0600, as:
--
--     JVN_LOCATION_WRITER_DATABASE_URL=postgresql://claude_location_writer:<pw>@<host>:<port>/<db>
--
-- Re-running is safe: it rotates the password and re-applies the grants.

\set ON_ERROR_STOP on

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

-- Read everything: judging a location needs to see job_listings and companies.
GRANT SELECT ON ALL TABLES IN SCHEMA public TO claude_location_writer;

-- Write: exactly the four location tables.
GRANT INSERT, UPDATE, DELETE ON
    locations, location_aliases, alias_locations, job_locations
    TO claude_location_writer;

-- locations.id is a serial, so inserts need the sequence.
GRANT USAGE, SELECT ON SEQUENCE locations_id_seq TO claude_location_writer;

-- ONE column on job_listings, so the skill can hand a job back to the
-- normalization safety-net. Nothing else on that table is writable.
GRANT UPDATE (normalization_status) ON TABLE job_listings TO claude_location_writer;

-- Deliberately NOT granted: users, companies, admins, feedback,
-- user_saved_filters, every other job_listings column, any DDL, any other schema.

-- Confirm what the role can actually write (should list exactly the 4 tables).
SELECT table_name, string_agg(privilege_type, ',' ORDER BY privilege_type) AS privs
FROM information_schema.table_privileges
WHERE grantee = 'claude_location_writer'
  AND privilege_type IN ('INSERT', 'UPDATE', 'DELETE')
GROUP BY table_name
ORDER BY table_name;

-- And the single column grant.
SELECT table_name, column_name, privilege_type
FROM information_schema.column_privileges
WHERE grantee = 'claude_location_writer'
  AND privilege_type = 'UPDATE'
  AND table_name = 'job_listings';
