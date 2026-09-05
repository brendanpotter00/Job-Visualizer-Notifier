/**
 * Turns the Recent page's filter state into the arguments for one search.
 *
 * Pure, and deliberately so: these arguments ARE the RTK Query cache key, so any
 * instability here (an unsorted array, an empty list where `undefined` was meant,
 * a clock read) mints a new cache entry and throws away every page already
 * fetched. Everything below exists to make the mapping from "what the user is
 * looking at" to "which cache entry" exactly one-to-one.
 */

import { TIME_WINDOW_DURATIONS } from '../../constants/time.ts';
import { SIGN_IN_OVERLAY_CONFIG, INFINITE_SCROLL_CONFIG } from '../../constants/ui.ts';
import type { RecentJobsFilters, TimeWindow } from '../../types';
import type { SearchJobsArgs } from './searchJobsTypes.ts';

/**
 * The `since` value for the all-time window.
 *
 * An explicit floor rather than an omitted parameter: it keeps every request in
 * exactly one server-side mode, and it keeps `SearchJobsArgs.since` a plain
 * `string` so nothing downstream has to special-case an optional bound.
 */
export const EPOCH_ISO = '1970-01-01T00:00:00.000Z';

/**
 * Quantization applied to a computed `since`.
 *
 * Two components computing "24 hours ago" microseconds apart must produce the
 * same string or they address different cache entries and duplicate every
 * request. A minute of granularity is far finer than any window on offer (the
 * shortest is 30 minutes) and makes the value trivially assertable in tests.
 */
const SINCE_QUANTUM_MS = 60_000;

/**
 * Resolve a time window to an inclusive ISO lower bound.
 *
 * `now` is injected rather than read here so this stays pure. Callers freeze a
 * single value for the lifetime of a walk: `useRecentJobsSearch` stamps the
 * instant onto its debounced filter snapshot (`snapshot.at`) and derives `since`
 * from that, so the bound only moves when the filters do. A live clock here would
 * mint a new cache key on every render and 422 the next cursor.
 */
export function sinceForTimeWindow(timeWindow: TimeWindow, now: number): string {
  const durationMs = TIME_WINDOW_DURATIONS[timeWindow];
  if (!Number.isFinite(durationMs)) return EPOCH_ISO;
  const floor = Math.floor((now - durationMs) / SINCE_QUANTUM_MS) * SINCE_QUANTUM_MS;
  return new Date(floor).toISOString();
}

/** Sorted copy, or `undefined` when there is nothing to send. */
function normalizeList(values: readonly string[] | undefined): string[] | undefined {
  if (!values || values.length === 0) return undefined;
  return [...new Set(values)].sort();
}

/**
 * Page size for a signed-in reader. Matches the old client-side reveal batch, so
 * the first screenful lands in one request and the virtualizer has enough rows to
 * measure against.
 */
export const RECENT_SEARCH_PAGE_SIZE = INFINITE_SCROLL_CONFIG.INITIAL_BATCH_SIZE;

/**
 * Signed-out readers see a fixed number of cards behind the sign-in overlay, and
 * cannot page. Fetching one MORE than the cap is what lets the list know whether
 * a 13th job exists — that is the condition the overlay renders on.
 */
export const SIGNED_OUT_FETCH_LIMIT = SIGN_IN_OVERLAY_CONFIG.SIGNED_OUT_JOB_LIMIT + 1;

export interface BuildSearchJobsArgsInput {
  filters: RecentJobsFilters;
  /** The user's enabled-companies preference. `null` or `[]` both mean "all". */
  enabledCompanyIds: string[] | null;
  /**
   * The reader's OWN custom companies (`u-<id>`), which are never in
   * `enabledCompanyIds`.
   *
   * `user_enabled_companies` holds only public companies: nothing writes a custom
   * company into it, and `list_enabled_companies`' auto-enroll UNION filters on
   * `c.visibility = 'public'` so it cannot supply one either (correctly — that
   * branch must never pull someone ELSE's private board into a feed). The result
   * is that a signed-in reader's enabled set is an explicit allowlist that omits
   * the very companies they added themselves, and since that set becomes the
   * `company=` param, it filtered their own boards back out of a request the
   * backend was by then willing to serve.
   *
   * Kept separate from `enabledCompanyIds` rather than merged upstream so the
   * "did the user opt out of this company" preference stays one concept and this
   * stays another. Empty for signed-out readers.
   */
  ownedCompanyIds: readonly string[];
  /** Frozen recency bound for this walk. */
  since: string;
  isSignedOut: boolean;
}

/**
 * Build the search arguments, or `null` when the filter set provably matches
 * nothing.
 *
 * The `null` case is not an optimization. If the user's enabled companies and
 * their explicit company filter are disjoint, the correct answer is "no jobs" —
 * but an EMPTY company list cannot express that on the wire, because an omitted
 * `companies` param means "all companies". Sending nothing would return the whole
 * corpus; sending an empty param is a 422. So the caller renders the empty state
 * without a request, and `null` is how it is told to.
 */
export function buildSearchJobsArgs({
  filters,
  enabledCompanyIds,
  ownedCompanyIds,
  since,
  isSignedOut,
}: BuildSearchJobsArgsInput): SearchJobsArgs | null {
  const storedEnabled = normalizeList(enabledCompanyIds ?? undefined);
  // ONLY widen an allowlist that already exists. `undefined` here means "all
  // companies" (the param is omitted), and that already includes the reader's own
  // boards — turning it into an explicit list containing just those would INVERT
  // the meaning and hide the entire public corpus.
  const enabled =
    storedEnabled && ownedCompanyIds.length > 0
      ? normalizeList([...storedEnabled, ...ownedCompanyIds])
      : storedEnabled;
  const selected = normalizeList(filters.company);

  let companies: string[] | undefined;
  if (enabled && selected) {
    companies = enabled.filter((id) => selected.includes(id));
    if (companies.length === 0) return null;
  } else {
    companies = enabled ?? selected;
  }

  const includeTerms = filters.searchTags
    ?.filter((tag) => tag.mode === 'include')
    .map((tag) => tag.text);
  const excludeTerms = filters.searchTags
    ?.filter((tag) => tag.mode === 'exclude')
    .map((tag) => tag.text);

  return {
    companies,
    category: normalizeList(filters.category),
    level: normalizeList(filters.level),
    locations: normalizeList(filters.location),
    include: normalizeList(includeTerms),
    exclude: normalizeList(excludeTerms),
    since,
    limit: isSignedOut ? SIGNED_OUT_FETCH_LIMIT : RECENT_SEARCH_PAGE_SIZE,
  };
}

/**
 * Serialize search arguments into a query string.
 *
 * Multi-value filters are REPEATED params, not comma-joined: canonical location
 * names ("Austin, TX, US") and free-text keywords contain commas, so a joined
 * scalar could not be split back apart unambiguously. One convention for all six
 * beats two conventions split by which values happen to be comma-free.
 *
 * Spaces are `%20`, not `+`. `URLSearchParams` emits `+`, which is correct for
 * `application/x-www-form-urlencoded` bodies but ambiguous in a query string —
 * and this request crosses a Vercel proxy that re-parses it. Same reasoning and
 * same fix as `savedFiltersApi`'s serializer.
 */
export function buildSearchJobsQuery(args: SearchJobsArgs, cursor: string | null): string {
  const params = new URLSearchParams();
  params.set('since', args.since);
  params.set('limit', String(args.limit));
  for (const value of args.companies ?? []) params.append('company', value);
  for (const value of args.category ?? []) params.append('category', value);
  for (const value of args.level ?? []) params.append('level', value);
  for (const value of args.locations ?? []) params.append('location', value);
  for (const value of args.include ?? []) params.append('include', value);
  for (const value of args.exclude ?? []) params.append('exclude', value);
  if (cursor !== null) params.set('cursor', cursor);
  return params.toString().replace(/\+/g, '%20');
}
