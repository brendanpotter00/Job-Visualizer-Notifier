/**
 * Recent Jobs filters <-> browser URL query string.
 *
 * WHY THIS EXISTS: before the server-side search endpoint, the Recent page's
 * filters were client-only state with no wire representation at all, so a
 * shareable link would have meant inventing a serialization from scratch. The
 * endpoint already takes the whole filter set as query params, so a shareable
 * page URL is now a mapping rather than a design problem.
 *
 * DELIBERATELY NOT the endpoint's own param names. This is a URL a person pastes
 * into Slack: `?time=24h&tag=backend&tag=-senior` reads, `?since=1970-01-01T…`
 * does not. The page URL is a user-facing contract about FILTERS; the endpoint's
 * is a machine contract about a QUERY, and `since` in particular is derived from
 * `timeWindow` at request time (see `sinceForTimeWindow`) rather than stored.
 *
 * PRECEDENCE, decided with the repo owner: a shared URL wins for that VISIT.
 * The reader's own saved filters are never modified, and come back on their next
 * normal visit. That falls out of the slice's one-shot `hydrated` guard rather
 * than needing a new mechanism — see `useRecentJobsUrlSync`.
 */
import type { RecentJobsFilters, SearchTag, TimeWindow } from '../../types';
import { TIME_WINDOW_DURATIONS } from '../../constants/time';

/** Every param this module owns. Anything else in the URL is left alone. */
export const FILTER_PARAMS = ['time', 'category', 'level', 'location', 'tag'] as const;

/**
 * `-` prefixes an excluded keyword: `tag=backend&tag=-senior`.
 *
 * A literal leading `-` in a keyword would otherwise be ambiguous, so it is
 * escaped on the way out and unescaped on the way in. Rare, but "C-suite" style
 * text is not hypothetical and silently flipping it to an exclusion would be the
 * worst kind of bug — the reader gets fewer results and no indication why.
 */
const EXCLUDE_PREFIX = '-';
const ESCAPED_PREFIX = '\\-';

function encodeTag(tag: SearchTag): string {
  const text = tag.text.startsWith(EXCLUDE_PREFIX) ? `${ESCAPED_PREFIX}${tag.text.slice(1)}` : tag.text;
  return tag.mode === 'exclude' ? `${EXCLUDE_PREFIX}${text}` : text;
}

function decodeTag(raw: string): SearchTag | null {
  if (!raw) return null;
  if (raw.startsWith(ESCAPED_PREFIX)) {
    return { text: `${EXCLUDE_PREFIX}${raw.slice(ESCAPED_PREFIX.length)}`, mode: 'include' };
  }
  if (raw.startsWith(EXCLUDE_PREFIX)) {
    const text = raw.slice(EXCLUDE_PREFIX.length);
    return text ? { text, mode: 'exclude' } : null;
  }
  return { text: raw, mode: 'include' };
}

const isTimeWindow = (value: string): value is TimeWindow =>
  Object.prototype.hasOwnProperty.call(TIME_WINDOW_DURATIONS, value);

/**
 * Read the filter subset this module owns out of a query string.
 *
 * Returns `null` when the URL carries NONE of them, which is the signal that
 * this is an ordinary visit and saved filters should hydrate as usual. An empty
 * object would be indistinguishable from "shared link with everything cleared",
 * and those two must behave differently.
 *
 * Unknown or malformed values are DROPPED rather than rejected: a link is often
 * hand-edited or truncated by a chat client, and showing a slightly wider result
 * set beats showing an error page. A dropped value cannot silently narrow what
 * the reader sees, which is the direction that would actually mislead.
 */
export function parseFiltersFromSearch(search: string): Partial<RecentJobsFilters> | null {
  const params = new URLSearchParams(search);
  if (!FILTER_PARAMS.some((name) => params.has(name))) return null;

  const filters: Partial<RecentJobsFilters> = {};

  const time = params.get('time');
  if (time && isTimeWindow(time)) filters.timeWindow = time;

  const category = params.getAll('category').filter(Boolean);
  if (category.length) filters.category = category;

  const level = params.getAll('level').filter(Boolean);
  if (level.length) filters.level = level;

  const location = params.getAll('location').filter(Boolean);
  if (location.length) filters.location = location;

  const tags = params.getAll('tag').map(decodeTag).filter((t): t is SearchTag => t !== null);
  if (tags.length) filters.searchTags = tags;

  return filters;
}

/**
 * Render the filter subset this module owns as a query string.
 *
 * Only NON-DEFAULT values are emitted, so an untouched page keeps a clean `/`
 * rather than a URL full of noise the reader did not choose. `company` is
 * deliberately absent: it is the reader's own enabled-companies preference, not
 * a filter they set on this page, and putting someone else's roster in a shared
 * link would silently change which companies the recipient is following.
 *
 * Any param NOT in `FILTER_PARAMS` is preserved untouched, so this can be called
 * on a URL that carries unrelated query state without eating it.
 */
export function buildSearchFromFilters(
  filters: RecentJobsFilters,
  existingSearch = ''
): string {
  const params = new URLSearchParams(existingSearch);
  for (const name of FILTER_PARAMS) params.delete(name);

  if (filters.timeWindow && filters.timeWindow !== 'all') params.set('time', filters.timeWindow);
  for (const value of filters.category ?? []) params.append('category', value);
  for (const value of filters.level ?? []) params.append('level', value);
  for (const value of filters.location ?? []) params.append('location', value);
  for (const tag of filters.searchTags ?? []) params.append('tag', encodeTag(tag));

  const rendered = params.toString();
  return rendered ? `?${rendered}` : '';
}
