-- Local dev seed: `companies` table, aligned with production.
--
-- WHY THIS EXISTS
--   The one-time local schema bootstrap (docs/LOCAL-SETUP.md step 8) materializes
--   the schema with `Base.metadata.create_all` + `alembic stamp head`, which
--   intentionally SKIPS every Alembic migration's data body -- including the
--   `seed_*` company migrations. A freshly bootstrapped local DB therefore has an
--   empty `companies` table, so the Procrastinate fan-out has no companies to
--   scrape and `job_listings` never fills. Apply this file after the bootstrap to
--   re-seed the same company set production runs.
--
-- IDEMPOTENT
--   Every row uses `ON CONFLICT (id) DO NOTHING`, wrapped in one transaction.
--   Safe to run repeatedly: re-running never duplicates rows. (It also never
--   UPDATES an existing row -- an out-of-band edit wins, matching the behavior
--   of the seed_* migrations.)
--
-- PROD IS THE SOURCE OF TRUTH
--   This is a point-in-time snapshot, so it can drift when companies are added via
--   new seed_* migrations. Refresh it by re-dumping prod (read-only) with:
--
--     SELECT string_agg(
--       'INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('
--       || quote_literal(id) || ', ' || quote_literal(display_name) || ', '
--       || quote_literal(ats) || ', ' || quote_nullable(board_token) || ', '
--       || enabled::text || ', ' || quote_literal(provider_config::text) || '::jsonb'
--       || ') ON CONFLICT (id) DO NOTHING;', E'\n' ORDER BY id)
--     FROM companies;
--
--   Snapshot: 2026-06-14  |  rows: 127
--   id md5:   c497b1cb0e03a44541b530e32b9e7701
--   full md5: a377cb33ac7b4ce28018951a569f99f5
--
-- APPLY (from repo root, with the Postgres container running)
--   docker exec -i jobscraper-postgres psql -U postgres -d jobscraper \
--     -v ON_ERROR_STOP=1 -f - < src/backend/seed/companies_seed.sql
--
BEGIN;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('adobe', 'Adobe', 'workday', 'adobe', true, '{"base_url": "https://adobe.wd5.myworkdayjobs.com", "tenant_slug": "adobe", "default_facets": {"jobFamilyGroup": ["591af8b812fa10737af39db3d96eed9f", "591af8b812fa10737b43a1662896f01c"], "locationCountry": ["bc33aa3152ec42d4995f4791a106ed09"]}, "career_site_slug": "external_experienced"}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('affirm', 'Affirm', 'greenhouse', 'affirm', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('airbnb', 'Airbnb', 'greenhouse', 'airbnb', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('airtable', 'Airtable', 'greenhouse', 'airtable', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('akunacapital', 'Akuna Capital', 'greenhouse', 'akunacapital', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('andurilindustries', 'Anduril', 'greenhouse', 'andurilindustries', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('anthropic', 'Anthropic', 'greenhouse', 'anthropic', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('apex-technology-inc', 'Apex Technology Inc', 'ashby', 'apex-technology-inc', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('appliedintuition', 'Applied Intuition', 'greenhouse', 'appliedintuition', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('astranis', 'Astranis', 'greenhouse', 'astranis', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('base-power', 'Base Power Company', 'ashby', 'base-power', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('baseten', 'Baseten', 'ashby', 'baseten', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('belvederetrading', 'Belvedere Trading', 'lever', 'belvederetrading', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('block', 'Block', 'greenhouse', 'block', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('blueorigin', 'Blue Origin', 'workday', 'blueorigin', true, '{"base_url": "https://blueorigin.wd5.myworkdayjobs.com", "tenant_slug": "blueorigin", "career_site_slug": "BlueOrigin"}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('braintrust', 'Braintrust', 'ashby', 'Braintrust', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('brex', 'Brex', 'greenhouse', 'brex', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('browserbase', 'Browserbase', 'ashby', 'browserbase', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('capitalone', 'Capital One', 'workday', 'capitalone', true, '{"base_url": "https://capitalone.wd12.myworkdayjobs.com", "tenant_slug": "capitalone", "career_site_slug": "Capital_One"}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('chalk', 'Chalk', 'ashby', 'chalk', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('clear', 'Clear', 'greenhouse', 'clear', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('clickup', 'ClickUp', 'ashby', 'clickup', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('cloudflare', 'Cloudflare', 'greenhouse', 'cloudflare', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('cognition', 'Cognition', 'ashby', 'cognition', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('cohere', 'Cohere', 'ashby', 'cohere', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('crunchyroll', 'Crunchyroll', 'greenhouse', 'crunchyroll', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('ctc', 'Chicago Trading (CTC)', 'greenhouse', 'chicagotrading', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('cursor', 'Cursor', 'ashby', 'cursor', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('databricks', 'Databricks', 'greenhouse', 'databricks', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('datadog', 'Datadog', 'greenhouse', 'datadog', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('decagon', 'Decagon', 'ashby', 'decagon', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('discord', 'Discord', 'greenhouse', 'discord', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('disney', 'Disney', 'workday', 'disney', true, '{"base_url": "https://disney.wd5.myworkdayjobs.com", "tenant_slug": "disney", "career_site_slug": "disneycareer"}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('distyl', 'Distyl', 'ashby', 'Distyl', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('doordashusa', 'Doordash', 'greenhouse', 'doordashusa', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('dropbox', 'Dropbox', 'greenhouse', 'dropbox', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('drw', 'DRW', 'greenhouse', 'drweng', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('elevenlabs', 'ElevenLabs', 'ashby', 'elevenlabs', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('eliseai', 'EliseAI', 'ashby', 'eliseai', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('exa', 'Exa', 'ashby', 'exa', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('expedia', 'Expedia', 'workday', 'expedia', true, '{"base_url": "https://expedia.wd108.myworkdayjobs.com", "tenant_slug": "expedia", "career_site_slug": "search"}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('fal', 'fal', 'greenhouse', 'fal', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('figma', 'Figma', 'greenhouse', 'figma', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('figureai', 'Figure AI', 'greenhouse', 'figureai', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('fireworksai', 'Fireworks AI', 'greenhouse', 'fireworksai', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('flint', 'Flint', 'ashby', 'flint', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('flowengineering', 'Flow Engineering', 'ashby', 'flowengineering', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('gem', 'Gem', 'gem', 'gem', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('generalintelligencecompany', 'General Intelligence Company', 'ashby', 'generalintelligencecompany', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('gigaml', 'GigaML', 'ashby', 'GigaML', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('gitlab', 'GitLab', 'greenhouse', 'gitlab', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('gleanwork', 'Glean', 'greenhouse', 'gleanwork', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('gm', 'General Motors', 'workday', 'gm', true, '{"base_url": "https://generalmotors.wd5.myworkdayjobs.com", "tenant_slug": "generalmotors", "career_site_slug": "Careers_GM"}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('granola', 'Granola', 'ashby', 'granola', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('happyrobot.ai', 'Happyrobot', 'ashby', 'happyrobot.ai', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('harvey', 'Harvey', 'ashby', 'harvey', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('hightouch', 'Hightouch', 'greenhouse', 'hightouch', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('hrt', 'Hudson River Trading', 'greenhouse', 'wehrtyou', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('imc', 'IMC Trading', 'greenhouse', 'imc', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('instacart', 'Instacart', 'greenhouse', 'instacart', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('judgmentlabs', 'Judgment Labs', 'ashby', 'judgmentlabs', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('jumptrading', 'Jump Trading', 'greenhouse', 'jumptrading', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('krea', 'Krea', 'ashby', 'krea', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('langchain', 'LangChain', 'ashby', 'langchain', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('light', 'Light', 'ashby', 'light', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('linear', 'Linear', 'ashby', 'Linear', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('lyft', 'Lyft', 'greenhouse', 'lyft', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('merge', 'Merge', 'greenhouse', 'merge', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('mintlify', 'Mintlify', 'ashby', 'Mintlify', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('modal', 'Modal Labs', 'ashby', 'modal', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('mongodb', 'MongoDB', 'greenhouse', 'mongodb', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('netflix', 'Netflix', 'eightfold', 'netflix', true, '{"domain": "netflix.com", "tenant_host": "explore.jobs.netflix.net"}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('neuralink', 'Neuralink', 'greenhouse', 'neuralink', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('nominal', 'Nominal', 'gem', 'nominal', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('notion', 'Notion', 'ashby', 'notion', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('nuro', 'Nuro', 'greenhouse', 'nuro', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('nvidia', 'NVIDIA', 'workday', 'nvidia', true, '{"base_url": "https://nvidia.wd5.myworkdayjobs.com", "tenant_slug": "nvidia", "default_facets": {"timeType": ["5509c0b5959810ac0029943377d47364"], "jobFamilyGroup": ["0c40f6bd1d8f10ae43ffaefd46dc7e78"], "locationHierarchy1": ["2fcb99c455831013ea52fb338f2932d8"]}, "career_site_slug": "NVIDIAExternalCareerSite"}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('openai', 'OpenAI', 'ashby', 'openai', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('optiver', 'Optiver', 'greenhouse', 'optiverprivate', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('palantir', 'Palantir', 'lever', 'palantir', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('pallet', 'Pallet', 'greenhouse', 'pallet', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('paraform', 'Paraform', 'ashby', 'paraform', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('paypal', 'PayPal', 'workday', 'paypal', true, '{"base_url": "https://paypal.wd1.myworkdayjobs.com", "tenant_slug": "paypal", "career_site_slug": "jobs"}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('perplexity', 'Perplexity', 'ashby', 'perplexity', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('pinterest', 'Pinterest', 'greenhouse', 'pinterest', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('plaid', 'Plaid', 'ashby', 'plaid', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('poke', 'Poke', 'ashby', 'interaction', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('posthog', 'PostHog', 'ashby', 'posthog', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('pylon-labs', 'Pylon', 'ashby', 'pylon-labs', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('ramp', 'Ramp', 'ashby', 'ramp', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('reddit', 'Reddit', 'greenhouse', 'reddit', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('resolve-ai', 'Resolve AI', 'ashby', 'Resolve AI', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('retool', 'Retool', 'gem', 'retool', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('roadrunner', 'Roadrunner', 'ashby', 'Roadrunner', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('robinhood', 'Robinhood', 'greenhouse', 'robinhood', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('roblox', 'Roblox', 'greenhouse', 'roblox', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('saronic', 'Saronic', 'ashby', 'saronic', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('scaleai', 'ScaleAI', 'greenhouse', 'scaleai', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('sentry', 'Sentry', 'ashby', 'sentry', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('sesame', 'Sesame', 'ashby', 'sesame', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('sierra', 'Sierra', 'ashby', 'Sierra', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('siftstack', 'Sift Stack', 'ashby', 'siftstack', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('slack', 'Slack', 'workday', 'slack', true, '{"base_url": "https://salesforce.wd12.myworkdayjobs.com", "tenant_slug": "salesforce", "career_site_slug": "Slack"}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('snap', 'Snap', 'workday', 'snap', true, '{"base_url": "https://snapchat.wd1.myworkdayjobs.com", "tenant_slug": "snapchat", "career_site_slug": "snap"}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('snowflake', 'Snowflake', 'ashby', 'snowflake', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('spacex', 'SpaceX', 'greenhouse', 'spacex', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('spotify', 'Spotify', 'lever', 'spotify', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('squarespace', 'Squarespace', 'greenhouse', 'squarespace', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('stainlessapi', 'Stainless API', 'ashby', 'stainlessapi', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('stripe', 'Stripe', 'greenhouse', 'stripe', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('sunday', 'Sunday', 'ashby', 'sunday', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('supabase', 'Supabase', 'ashby', 'supabase', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('thinkingmachines', 'Thinking Machines', 'greenhouse', 'thinkingmachines', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('togetherai', 'Together AI', 'greenhouse', 'togetherai', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('trajectory', 'Trajectory', 'ashby', 'trajectory', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('traversal', 'Traversal', 'ashby', 'traversal', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('turo', 'Turo', 'workday', 'turo', true, '{"base_url": "https://turo.wd12.myworkdayjobs.com", "tenant_slug": "turo", "career_site_slug": "Turo_careers"}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('twilio', 'Twilio', 'greenhouse', 'twilio', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('twitch', 'Twitch', 'greenhouse', 'twitch', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('unity3d', 'Unity', 'greenhouse', 'unity3d', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('vercel', 'Vercel', 'greenhouse', 'vercel', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('vizcom', 'Vizcom', 'ashby', 'vizcom', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('waymo', 'Waymo', 'greenhouse', 'waymo', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('wispr-flow', 'Wispr Flow', 'ashby', 'wispr-flow', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('workweave', 'Workweave', 'ashby', 'workweave', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('xai', 'XAI', 'greenhouse', 'xai', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
INSERT INTO companies (id, display_name, ats, board_token, enabled, provider_config) VALUES ('zoox', 'Zoox', 'lever', 'zoox', true, '{}'::jsonb) ON CONFLICT (id) DO NOTHING;
COMMIT;
