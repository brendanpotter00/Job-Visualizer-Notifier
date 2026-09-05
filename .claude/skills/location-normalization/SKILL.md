---
name: location-normalization
description: |
  Clean up the persistent location cache in prod. Finds deviations (one raw
  string mapped to many locations, duplicate `locations` rows, junk remote
  scopes, tag explosions), decides the CORRECT location yourself, and writes it
  back as an authoritative `manual` alias so the pipeline can never re-break it.
  Also merges duplicate `locations` rows. Use when location tags look wrong or
  duplicated on the site, or on a /loop to keep the cache clean.
trigger_phrases:
  - "location normalization"
  - "clean up the location cache"
  - "fix the location tags"
  - "dedupe locations"
required_mcps:
  - postgres-prod
required_tools:
  - Bash
  - mcp__postgres-prod__query
mode: read-write   # prod: SELECT via MCP; writes ONLY via apply.py's narrow role
---

# Location normalization

## §0 What this skill is (and is not)

**Is:** a data-repair loop over the persistent location cache. You look at what
the cache currently maps a raw location string to, decide what it *should* map
to, and write that decision back permanently.

**Is not:** a root-cause investigation. Do not go looking for why the pipeline
produced a bad mapping, do not read the normalization code, do not open PRs
against `location_normalization.py`. Those bugs are fixed separately. Your job
is the data.

**You are the judge.** You already know that "San Francisco" means
San Francisco, CA, US, that "Bay Area" is a metro not a city, and that a job
whose raw location is the single word "Remote" is not located in Riyadh. Use
that knowledge directly. Only reach for the job posting URL when a string is
genuinely ambiguous to you (§4).

## §1 Hard rules

1. **`mcp__postgres-prod__query` is SELECT-only.** Never INSERT/UPDATE/DELETE/DDL
   through it. Every write goes through `apply.py`, whose role can touch only
   the four location tables plus `job_listings.normalization_status`.
2. **`apply.py` is dry-run by default.** `--apply` is the only thing that
   commits, and it runs in ONE transaction.
3. **Never write a mapping you are not confident in.** Leaving a bad alias in
   place is recoverable; writing a wrong `manual` alias is sticky, because
   `manual` is deliberately immune to LLM overwrite. When unsure, skip it and
   say so in the report.
4. **Never touch `job_listings` beyond `normalization_status`.** No title, no
   status, no closing jobs.
5. **One transaction, one rollback file.** `apply.py` writes the undo SQL before
   it commits. If the verify step in §6 shows findings did not drop, roll back.
6. **Never merge two `locations` rows that differ in real geography.** South San
   Francisco is not San Francisco. Merge only rows that name the same physical
   place.

## §2 Why writing `manual` is the whole point

`location_aliases.source` is either `'llm'` or `'manual'`. The Tier-2 writer
(`persist_llm_result`) **skips any alias whose source is `manual`** — an
operator correction wins permanently (Decision #10).

So when you write a corrected mapping as `manual`:

* every job whose raw location normalizes to that key gets the right tags on its
  next normalization, and
* the pipeline can never overwrite your judgment, no matter what Haiku returns
  later.

That is what "so it doesn't happen again" means here. `apply.py` always writes
`source='manual'`.

## §3 Phase 1 — Detect (read-only)

Run these through `mcp__postgres-prod__query`. Each returns rows worth fixing;
record the counts so §6 can compare.

**D1 — one raw string mapped to implausibly many locations.** The headline
problem. A raw string can only name so many places.

```sql
SELECT al.raw_text,
       count(*) AS n_locations,
       (length(al.raw_text) - length(replace(al.raw_text, ',', ''))) + 1 AS comma_groups,
       (SELECT count(*) FROM job_listings j
         WHERE lower(btrim(j.location)) = al.raw_text AND j.status = 'OPEN') AS open_jobs,
       string_agg(l.canonical_name, ' | ' ORDER BY al.position) AS current_mapping
FROM alias_locations al
JOIN locations l ON l.id = al.normalized_location_id
GROUP BY al.raw_text
HAVING count(*) > GREATEST((length(al.raw_text) - length(replace(al.raw_text, ',', ''))) + 1, 2)
ORDER BY open_jobs DESC, n_locations DESC
LIMIT 40;
```

**D2 — duplicate `locations` rows: same display name, different rows.** These
are the dedupe candidates.

```sql
SELECT canonical_name, count(*) AS n_rows,
       array_agg(id ORDER BY id) AS ids,
       string_agg(kind || '/' || coalesce(city,'-') || '/' || coalesce(region,'-')
                  || '/' || coalesce(country,'-') || '/' || coalesce(remote_scope,'-'),
                  ' ;; ' ORDER BY id) AS tuples
FROM locations
GROUP BY canonical_name
HAVING count(*) > 1
ORDER BY count(*) DESC
LIMIT 40;
```

**D3 — remote scopes outside the closed vocabulary.** Valid: `global`, a macro
region (`amer`/`namer`/`latam`/`emea`/`eu`/`apac`), or a lowercase ISO-3166-1
alpha-2 code.

```sql
SELECT id, canonical_name, region, country, remote_scope,
       (SELECT count(*) FROM job_locations jl WHERE jl.normalized_location_id = locations.id) AS n_jobs
FROM locations
WHERE kind = 'remote'
  AND remote_scope IS NOT NULL
  AND remote_scope NOT IN ('global','amer','namer','latam','emea','eu','apac')
  AND remote_scope !~ '^[a-z]{2}$'
ORDER BY n_jobs DESC
LIMIT 40;
```

**D4 — jobs carrying too many tags.** The user-visible symptom.

```sql
SELECT jl.job_listing_id, j.title, j.company, j.location AS raw_location,
       count(*) AS n_tags,
       string_agg(l.canonical_name, ' | ' ORDER BY l.canonical_name) AS tags
FROM job_locations jl
JOIN locations l ON l.id = jl.normalized_location_id
JOIN job_listings j ON j.id = jl.job_listing_id
WHERE j.status = 'OPEN'
GROUP BY jl.job_listing_id, j.title, j.company, j.location
HAVING count(*) > 5
ORDER BY count(*) DESC
LIMIT 30;
```

**D5 — `locations` rows nothing points at.** Safe to delete.

```sql
SELECT id, canonical_name, kind, remote_scope
FROM locations l
WHERE NOT EXISTS (SELECT 1 FROM job_locations jl WHERE jl.normalized_location_id = l.id)
  AND NOT EXISTS (SELECT 1 FROM alias_locations al WHERE al.normalized_location_id = l.id)
ORDER BY id
LIMIT 60;
```

**D6 — schema-invariant violations.** A `remote` row must have no city; a
non-remote row must have no scope; a `region` row should not carry a city.

```sql
SELECT id, canonical_name, kind, city, region, country, remote_scope
FROM locations
WHERE (kind = 'remote' AND city IS NOT NULL)
   OR (kind <> 'remote' AND remote_scope IS NOT NULL)
   OR (kind = 'region' AND city IS NOT NULL)
ORDER BY id
LIMIT 40;
```

Print a one-line summary per probe before moving on:

```
D1 alias-overcount      37 aliases   (13,838 open jobs affected)
D2 duplicate-names      48 names
D3 bad-scope            61 rows
D4 tag-explosion        1,039 jobs
D5 orphans              26 rows
D6 invariant-violations 4 rows
```

## §4 Phase 2 — Judge

For each D1 alias and each D2 duplicate group, decide the correct answer
**yourself**. Work highest-impact first (`open_jobs` descending) and stop at
whatever you can do well — a partial, correct pass beats a complete, sloppy one.

**Decide directly** when the string is unambiguous to you:

| raw_text | correct mapping |
|---|---|
| `san francisco` | one city: San Francisco, CA, US |
| `remote` | one remote, unscoped (no country is claimed) |
| `us` | one country: US |
| `hq` | nothing you can know — SKIP, note it |
| `sunnyvale, ca; kirkland, wa` | two cities |

**Consult the posting** only when you genuinely cannot tell — an internal
building code, a company-specific label, an ambiguous city name. Get a URL:

```sql
SELECT j.id, j.title, j.company, j.location, j.url
FROM job_listings j
WHERE lower(btrim(j.location)) = %s AND j.status = 'OPEN'
LIMIT 3;
```

Then fetch it with WebFetch and read what the posting itself says the location
is. If it still is not clear, **skip the alias** — rule §1.3.

**Judging rules:**

* Map to the **smallest scope that is actually true**. A job posted as "Remote -
  US" is `Remote (US)`, not `Remote (Global)`. A job posted as plain "Remote"
  claims no country, so leave the scope null rather than guessing `us`.
* A raw string that names ONE place gets ONE location. Resist keeping extra
  entries "just in case" — that is exactly how the cache got into this state.
* Preserve real distinctions. `South San Francisco, CA, US` is a different city
  from `San Francisco, CA, US`; `Remote (US)` scoped to a state keeps its state.
* If a raw string names several real sites, map all of them, in the order they
  appear in the string.

**For D2 duplicate groups**, pick the survivor as the row with the most job
links (tie-break: lowest id) and merge the rest into it — but only after
confirming every row in the group is the same physical place. A group that
mixes real places is not a merge; fix the individual rows instead.

## §5 Phase 3 — Apply

Write your decisions to a JSON file, then run `apply.py`. Its schema:

```json
{
  "aliases": [
    {
      "raw_text": "san francisco",
      "reason": "one city; cache held 10 locations",
      "locations": [
        {"kind": "city", "city": "San Francisco", "region": "CA", "country": "US"}
      ]
    },
    {
      "raw_text": "remote",
      "reason": "claims no country; cache held 29 locations incl. Riyadh",
      "locations": [{"kind": "remote"}]
    }
  ],
  "merges": [
    {"survivor_id": 39, "loser_ids": [4807, 930], "reason": "same city"}
  ],
  "delete_orphans": [17369],
  "renormalize_jobs": []
}
```

Every location spec is validated through the repo's own `canonicalize()` before
it is written, so you cannot write something the pipeline would reject.

```bash
# ALWAYS look at the plan first — this commits nothing.
python .claude/skills/location-normalization/apply.py --plan fixes.json

# Commit it.
python .claude/skills/location-normalization/apply.py --plan fixes.json --apply
```

`apply.py` needs `JVN_LOCATION_WRITER_DATABASE_URL`, which it reads from
`~/.config/jvn/location-writer.env`. It refuses to run against a DSN whose user
is not `claude_location_writer`, so it can never run as superuser by accident.

What it does, in one transaction:

1. Upserts each location spec into `locations` (canonicalized, NULLS-NOT-DISTINCT dedup).
2. Writes the alias as `source='manual', confidence=1.0`, REPLACING its mapping.
3. Rewrites `job_locations` for every OPEN job whose raw location matches that
   key, so the fix is visible immediately rather than on the next scrape.
4. Merges each duplicate group: repoints `job_locations` + `alias_locations`
   FKs onto the survivor, ORs `is_primary`, deletes the losers.
5. Deletes the listed orphans (refuses any that still have references).
6. Writes a rollback `.sql` next to the plan file BEFORE committing.

## §6 Phase 4 — Verify

Re-run every §3 probe. Compare with the counts you recorded.

* Findings dropped → good. Report the deltas.
* Findings did NOT drop, or any probe errors → **roll back** with the generated
  rollback file and report. Do not attempt a second fix in the same run.

```
LOCATION NORMALIZATION REPORT
Ran:        <ISO timestamp>
Detected:   D1 37 · D2 48 · D3 61 · D4 1039 · D5 26 · D6 4
Judged:     31 aliases, 12 merges, 26 orphans   (6 skipped — see below)
Applied:    yes (--apply)  |  no (dry-run)
After:      D1 6 · D2 4 · D3 0 · D4 88 · D5 0 · D6 0
Skipped:    'hq' (company-specific, no posting says where)
            'zone_1' (ATS internal code)
Rollback:   /path/to/fixes.rollback.sql
```

## §7 Running on a /loop

```
/loop use the location-normalization skill
```

Each tick: detect → judge → apply → verify → report. If §3 finds nothing, that
is a no-op tick; say so and wait.

Three brakes, all in `apply.py` or this file — do not remove them without being
asked:

1. **Auto-rollback on regression.** If §6 shows findings did not drop, roll back
   rather than leaving a partial write. Without this the loop can amplify its own
   mistakes tick after tick.
2. **A rollback file per run**, kept beside the plan. It is the only way to undo
   a bad unattended night.
3. **Convergence detection.** Three consecutive ticks that change nothing → stop
   looping and report, rather than burning tokens forever.

Text Brendan (`bash ~/.claude/skills/message-brendan/send.sh "<msg>"`) only when
an auto-rollback fired or a probe errored. A clean tick is not worth a text.

## §8 Edge cases

| Situation | Do this |
|---|---|
| Raw string is a building/internal code (`hq`, `zone_1`, `US-MTV-EMF680`) | Skip unless the posting states a real location. Note it in the report. |
| Alias already `source='manual'` | Someone (or a previous run) already judged it. Leave it unless it is clearly wrong. |
| Duplicate group mixes real places | NOT a merge. Fix the individual rows' tuples instead, or skip. |
| A raw string legitimately names 10+ sites | Not a finding. D1's ceiling scales with comma groups; if it still trips, override by judging it correctly with all 10. |
| `apply.py` refuses the DSN | The env file is missing or names the wrong role. Do not fall back to `railway run` or the superuser. |
| Probe query errors | Treat as UNKNOWN, not as "clean". Report it. |

## §9 First-time setup (once, by Brendan)

`apply.py` needs the narrow write role. Until it exists, Phases 1–2 work
(detection and judging are read-only through the MCP) and Phase 3 refuses.

```bash
# from the repo root
railway run -- sh -c 'psql "$DATABASE_URL" \
  -v pw="$(openssl rand -base64 32 | tr -d /=+ | cut -c1-32)" \
  -f .claude/skills/location-normalization/setup_role.sql'
```

Then store the DSN so `apply.py` can find it:

```bash
mkdir -p ~/.config/jvn
printf 'JVN_LOCATION_WRITER_DATABASE_URL=%s\n' \
  'postgresql://claude_location_writer:<pw>@<host>:<port>/<db>' \
  > ~/.config/jvn/location-writer.env
chmod 600 ~/.config/jvn/location-writer.env
```

`setup_role.sql` prints the grants it applied — it should show write access to
exactly `alias_locations`, `job_locations`, `location_aliases`, `locations`, plus
the single `job_listings.normalization_status` column grant. If it lists anything
else, stop and investigate.

**Why a separate role rather than `railway run` as superuser.** The loop in §7
runs unattended. Superuser plus unattended is the combination worth avoiding: with
this role the worst case is wrong location tags, which this skill repairs. Without
it, the worst case is any table in the database.
