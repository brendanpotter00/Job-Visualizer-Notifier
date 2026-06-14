# Follow-up: Canonical Fragmentation (same city → multiple `locations` rows)

**Status:** Open · **Owner:** unassigned · **Raised:** 2026-06-14 (during the "surface location tags" work, PR #149)
**Severity:** Low–Medium (UX papercut + slightly wrong filter semantics; no data loss)
**Type:** Normalizer data-quality / consistency — **not** a wiring bug.

> For another agent to pick up. Evidence is reproducible with the read-only
> script **`diagnostics/canonical_fragmentation.sql`** in this directory (see
> "Reproduce" below). All numbers are from prod on 2026-06-14.

## Problem

The Tier-2 Haiku normalizer emits **inconsistent canonical forms for the same
physical city**. Because the `locations` uniqueness key is
`(kind, city, region, country, remote_scope)` (`db_models.py::Location`), each
distinct rendering becomes a **separate canonical row** — and therefore a
**separate, redundant option** in the Location filter dropdown that the
tags-wiring PR just shipped. A user looking for "Berlin" sees three Berlins.

This was surfaced live while verifying the dropdown: one Warsaw office had **four**
canonical forms, all selected by a single job:
`Warsaw, PL, PL · Warsaw, Masovian, PL · Warsaw, MZ, PL · Warsaw, PL, Poland`.

## Evidence (prod, 2026-06-14)

From `diagnostics/canonical_fragmentation.sql`:

- **319** city canonical rows across **290** distinct city names.
- **25** city names map to **>1** canonical form (**54** canonical rows involved).
- **29** city rows have a region that is **not** an ISO-2 code (`England`, `North Holland`, `Karnataka`, `Maharashtra`, `Île-de-France`, `Berlin`, `Madrid`, …).
- **4** rows have **region == country** (`Dublin, IE, IE`; `Munich, DE, DE`; `Paris, FR, FR`; `Warsaw, PL, PL`).
- **3** rows have a **non-ISO-2 country** (`Germany`, `Netherlands`, `Spain`, … rendered as full names instead of `DE`/`NL`/`ES`).
- **804 OPEN jobs** are tagged with a fragmented-city canonical (i.e. would show duplicate city options).

Worst-offender examples (one city → many forms):

| City | Distinct canonical forms | Failure mode |
|------|--------------------------|--------------|
| Berlin | `Berlin, Berlin, Germany` · `Berlin, DE, DE` · `Berlin, Germany` | country code vs full name; region = country / city name / absent |
| London | `London, England, GB` · `London, England, UK` · `London, UK` | **GB vs UK** country code; region present vs absent |
| Dublin (IE) | `Dublin, IE` · `Dublin, IE, IE` | region = country code vs absent (also collides with the real `Dublin, CA, US`) |
| Bangalore | `Bangalore, IN` · `Bangalore, KA, IN` | region present vs absent (and `Bengaluru` is a 5th alias of the same city) |
| Amsterdam | `Amsterdam, Netherlands` · `Amsterdam, North Holland, NL` | country full-name vs code; region full-name vs absent |

**Distinguish two cases** (the script's query #2 mixes them):
- **Legitimate** same-name different cities — *not* a bug: `Arlington TX/VA/WA`, `Concord CA/NC`, `Melbourne FL-US / VIC-AU`, `Richmond VA-US / VIC-AU`.
- **Likely hallucinated disambiguation** — *is* a bug: **`San Francisco, TX, US`** alongside `San Francisco, CA, US` (query #5 flags famous-city + wrong-state pairs).

## Root cause

The prompt (`services/llm_client.py::SYSTEM_PROMPT`) asks for "short region/country
codes when unambiguous" but does **not** force a single canonical rendering, so the
model varies run-to-run: region as ISO code vs full name vs the country code vs
omitted; country as ISO-2 vs full name; `GB` vs `UK`. The eval
(`api/eval/`) scores structured fields with aliasing (e.g. `USA→US`) so it does not
currently fail these inconsistencies, and the unit tests mock the LLM.

## Suggested approach (for the picking-up agent)

1. **Tighten the contract, deterministically** — prefer a post-LLM normalization
   pass over prompt-only fixes (prompts drift). After the model returns, canonicalize
   the structured fields before the `locations` upsert in
   `services/location_normalization.py::persist_llm_result`:
   - country → ISO-3166-1 alpha-2 (`Germany→DE`, `UK→GB`); reject/repair non-2-letter.
   - region → a single convention (ISO-3166-2 subdivision code, or **always omit** for
     non-US to avoid `North Holland`/`Île-de-France` noise) — and never `region == country`.
   - Recompute `canonical_name` from the cleaned parts so the label is derived, not free-text.
2. **Add eval coverage** so this can't regress: golden cases asserting `Berlin→(DE, region omitted)`,
   `London→GB` (not `UK`), `Dublin, IE` (region not `IE`), `Bangalore→(KA or omitted, consistently)`.
   Run the human-run Tier-2 gate (`api/eval/eval_locations.py`) after.
3. **Merge existing duplicates (migration / one-off)** — collapse the 54 fragmented
   rows to one canonical each and re-point `alias_locations.normalized_location_id` and
   `job_locations.normalized_location_id`, then delete the orphans. ~804 OPEN jobs affected.
   This is a data migration; gate it behind the eval and the prod monitor
   (`api/eval/monitor_prod.py`) integrity checks. Manual alias overrides
   (`PUT /api/admin/locations/aliases/{raw_text}`) can patch the worst few in the interim.
4. **Re-validate in the UI** — the dropdown should show one `Berlin, DE` / `London, GB` /
   `Bangalore, KA, IN` each (Recent Jobs + Companies pages).

## Reproduce

```bash
# read-only; safe against prod or a read replica
psql "$DATABASE_URL" -f docs/implementations/locationNormalization/diagnostics/canonical_fragmentation.sql
# or paste any single query into the postgres MCP (mcp__postgres-prod__query)
```

## Related open items (from the same PR, not blockers)

- **Tier-2 eval gate not run** — `api/eval/eval_locations.py` is human-run / spends real
  money. The PR added golden cases for the flagged dropdown variants (prod-confirmed);
  run `PYTHONPATH=. python -m src.backend.api.eval.eval_locations --set all --repeat 3` before merge.
- **Backfill sequencing** — the dropdown uses normalized tags with **no raw fallback**, so it
  should ship after the OPEN-job backlog finishes draining (`scan_unnormalized` is healthy and
  draining; ~24k OPEN+NULL at report time). Track with `monitor_prod.py`.
