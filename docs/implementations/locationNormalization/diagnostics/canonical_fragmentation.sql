-- Canonical-fragmentation diagnostic for location normalization.
--
-- READ-ONLY (every statement is a SELECT). Quantifies how often the LLM
-- normalizer emits MORE THAN ONE canonical `locations` row for the SAME
-- physical city (inconsistent region/country codes, full names vs ISO codes,
-- region == country, city aliases). Each extra canonical row is an extra,
-- redundant option in the Location filter dropdown.
--
-- How to run (read-only; safe against prod or a read replica):
--   psql "$DATABASE_URL" -f docs/implementations/locationNormalization/diagnostics/canonical_fragmentation.sql
-- or, against the read-only monitor URL used by the prod monitor:
--   psql "$MONITOR_DATABASE_URL" -f docs/implementations/locationNormalization/diagnostics/canonical_fragmentation.sql
-- or paste any single query below into the postgres MCP (mcp__postgres-prod__query).
--
-- Captured baseline (prod, 2026-06-14): 319 city canonical rows / 290 distinct
-- city names; 25 city names map to >1 canonical (54 rows involved); 29 city
-- rows have a non-ISO-2 region; 4 rows have region == country; 3 rows have a
-- non-ISO-2 country.

\echo '== 1. Fragmentation summary (city canonicals) =='
WITH city_rows AS (
  SELECT id, canonical_name, lower(city) AS city_l, region, country
  FROM locations
  WHERE kind = 'city' AND city IS NOT NULL
)
SELECT
  (SELECT COUNT(*) FROM city_rows)                              AS total_city_canonical_rows,
  (SELECT COUNT(DISTINCT city_l) FROM city_rows)               AS distinct_city_names,
  COUNT(*) FILTER (WHERE n > 1)                                AS city_names_with_multiple_canonicals,
  SUM(n) FILTER (WHERE n > 1)                                  AS canonical_rows_involved
FROM (SELECT city_l, COUNT(*) AS n FROM city_rows GROUP BY city_l) g;

\echo '== 2. Worst offenders: one city name -> many canonical forms =='
-- NOTE: some rows here are LEGITIMATE distinct cities sharing a name
-- (Arlington TX/VA/WA, Concord CA/NC, Melbourne FL-US / VIC-AU). The BUG cases
-- are same-city-different-rendering: "Berlin, DE, DE" vs "Berlin, Germany";
-- "London, ..., GB" vs "..., UK"; "Bangalore, IN" vs "Bangalore, KA, IN".
SELECT lower(city) AS city,
       COUNT(*)    AS canonical_variants,
       array_agg(DISTINCT canonical_name ORDER BY canonical_name) AS forms
FROM locations
WHERE kind = 'city' AND city IS NOT NULL
GROUP BY lower(city)
HAVING COUNT(*) > 1
ORDER BY canonical_variants DESC, city;

\echo '== 3. Structured-field anti-patterns (all location rows) =='
SELECT
  COUNT(*)                                                                         AS total_locations,
  COUNT(*) FILTER (WHERE country IS NOT NULL AND country !~ '^[A-Z]{2}$')          AS country_not_iso2,
  COUNT(*) FILTER (WHERE region IS NOT NULL AND country IS NOT NULL AND region = country) AS region_equals_country,
  COUNT(*) FILTER (WHERE kind='city' AND region IS NOT NULL AND region !~ '^[A-Z]{2}$')   AS city_region_not_2letter
FROM locations;

\echo '== 4. Offending rows: non-ISO-2 region or country, or region == country =='
SELECT id, kind, canonical_name, city, region, country, remote_scope
FROM locations
WHERE (country IS NOT NULL AND country !~ '^[A-Z]{2}$')
   OR (kind = 'city' AND region IS NOT NULL AND region !~ '^[A-Z]{2}$')
   OR (region IS NOT NULL AND country IS NOT NULL AND region = country)
ORDER BY lower(city) NULLS LAST, canonical_name;

\echo '== 5. Suspicious disambiguations (likely hallucinated region), e.g. "San Francisco, TX, US" =='
-- Same city name with multiple US states is usually real (Arlington), but a
-- famous-city + wrong-state pair (San Francisco, TX) is almost always an error.
-- Eyeball this list; cross-check counts before merging.
SELECT lower(city) AS city,
       array_agg(canonical_name ORDER BY canonical_name) AS forms
FROM locations
WHERE kind = 'city' AND country = 'US' AND city IS NOT NULL
GROUP BY lower(city)
HAVING COUNT(DISTINCT region) > 1
ORDER BY city;

\echo '== 6. Impact: OPEN jobs tagged with a fragmented-city canonical =='
-- How many live jobs would show duplicate city options in the dropdown.
WITH fragmented AS (
  SELECT l.id
  FROM locations l
  JOIN (
    SELECT lower(city) AS city_l
    FROM locations
    WHERE kind='city' AND city IS NOT NULL
    GROUP BY lower(city)
    HAVING COUNT(*) > 1
  ) f ON lower(l.city) = f.city_l
  WHERE l.kind='city'
)
SELECT COUNT(DISTINCT jl.id) AS open_jobs_touching_a_fragmented_city
FROM job_listings jl
JOIN job_locations j ON j.job_listing_id = jl.id
JOIN fragmented fr   ON fr.id = j.normalized_location_id
WHERE jl.status = 'OPEN';
