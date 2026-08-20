/**
 * Wire and cache types for `GET /api/jobs/search`.
 *
 * Kept out of `jobsApi.ts` so the endpoint definition there stays readable, and
 * out of `types/index.ts` because nothing outside the Recent Jobs data layer has
 * any business referring to them.
 */

import type { BackendJobListing } from '../../api/types.ts';
import type { Job } from '../../types';

/**
 * Header metrics, returned with page 1 only.
 *
 * `total` counts the ACTIVE filter set. The two recency figures are scoped to the
 * companies the reader follows (the `companies` argument) and to NOTHING else —
 * not category, level, keywords, locations or the time window. That is what the
 * Recent page's "Past 24 Hours" / "Past 3 Hours" tiles have always shown: before
 * this endpoint they came off `selectAllJobsFromQuery`, i.e. the enabled-companies
 * prefilter, applied ahead of every other filter. Preserved rather than
 * "simplified" so the migration does not silently change what those numbers mean.
 */
export interface SearchJobsCounts {
  total: number;
  last24h: number;
  last3h: number;
}

/**
 * The response envelope AFTER `validateSearchJobsResponse` has normalized it —
 * job rows still untransformed, but the header metrics renamed.
 *
 * NOT byte-for-byte the wire shape: the endpoint sends the metrics as `meta`
 * (`{filteredTotal, countLast24h, countLast3h}` — see `JobSearchResponse` in
 * `api/models.py`), and the validator both renames the key to `counts` and maps
 * the three fields onto `SearchJobsCounts`. The rename happens in exactly one
 * place; nothing downstream of the validator ever sees `meta`.
 */
export interface SearchJobsResponseBody {
  jobs: BackendJobListing[];
  /**
   * `null` means END OF WALK — the only termination signal. Present iff the page
   * came back full, so a trailing exactly-full page costs one extra request that
   * returns an empty array.
   *
   * In the BODY rather than a header (`/api/jobs` uses `X-Next-Cursor`) because a
   * header has to survive three separate hops — the Vercel proxy's explicit
   * re-emit, FastAPI `expose_headers`, and `vercel.json`'s
   * `Access-Control-Expose-Headers` — and missing any one of them fails silently:
   * the page renders and the walk just stops.
   */
  nextCursor: string | null;
  /** Absent on cursor pages; the counts describe the filter set, not the page. */
  counts?: SearchJobsCounts;
}

/**
 * The arguments that identify one search — and therefore one RTK Query cache
 * entry. Every list is sorted and every empty list is `undefined` rather than
 * `[]`, so two filter states that mean the same thing serialize to the same key
 * (see `buildSearchJobsArgs`).
 */
export interface SearchJobsArgs {
  /** Company ids to include. Omitted = every company the user can see. */
  companies?: string[];
  /** Enrichment category slugs. Omitted = no category filter. */
  category?: string[];
  /**
   * Enrichment level slugs, sent UNEXPANDED. The server owns the
   * new_grad ⊂ entry hierarchy; expanding here too would mean two copies of the
   * taxonomy that can disagree.
   */
  level?: string[];
  /**
   * SWE subcategory slugs, sent UNEXPANDED — the same rule as `level` above and
   * for the same reason. The server owns the Frontend/Backend ⊃ Full Stack
   * widening (`services/job_search.py::expand_subcategories`); expanding here
   * too would mean two copies of the taxonomy that can disagree, and it would
   * persist the widened pair `['backend','full_stack']` into the user's saved
   * filters and into the chips they see.
   *
   * NOTE for readers of `meta`: the recency tiles will NOT narrow with this
   * filter. `filteredTotal` tracks the whole filter set and does reflect it, but
   * `countLast24h` / `countLast3h` are company-scoped and scoped to nothing else
   * by design (see the interface below). That asymmetry predates this field; a
   * 15-way subdivision just makes the gap between "Past 24 Hours" and the
   * visible rows much more noticeable. Nobody has decided whether to change it.
   */
  subcategory?: string[];
  /** Canonical location names; the server resolves them hierarchically. */
  locations?: string[];
  /** Keyword terms a job must match at least one of. */
  include?: string[];
  /** Keyword terms a job must match none of. */
  exclude?: string[];
  /**
   * Recency lower bound, inclusive, as an ISO instant with an offset.
   *
   * FROZEN for the lifetime of a walk. It participates in the server's cursor
   * fingerprint, so recomputing `now - 3h` on page 2 is a 422 — and even without
   * that, a changing value would mint a new cache entry and throw away every page
   * already fetched.
   */
  since: string;
  limit: number;
}

/** One fetched page, with rows already mapped to the app's `Job` model. */
export interface SearchJobsPage {
  jobs: Job[];
  nextCursor: string | null;
  counts?: SearchJobsCounts;
}
