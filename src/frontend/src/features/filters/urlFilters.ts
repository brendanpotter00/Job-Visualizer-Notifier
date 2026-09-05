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
import { canAddSearchTag } from '../../constants/tags';

/** Every param this module owns. Anything else in the URL is left alone. */
export const FILTER_PARAMS = ['time', 'category', 'level', 'location', 'tag'] as const;

/**
 * The endpoint's own per-dimension caps, mirrored — see
 * `routers/jobs_search._MAX_FACET_VALUES` (20, for `category` and `level` alike)
 * and `_MAX_LOCATIONS` (100).
 *
 * A hand-edited link is the ONE add-site with no UI control in front of it: every
 * other way a filter grows goes through a chip input that already asks the shared
 * guard first. Over the cap the endpoint answers a hard 400 to every subsequent
 * search, and the reader's only route back is deleting chips one at a time — so a
 * link is truncated here, on the way in, for the same reason `MAX_SEARCH_TAGS` is
 * enforced where tags are added rather than where the request is built.
 */
export const MAX_URL_FACET_VALUES = 20;
export const MAX_URL_LOCATIONS = 100;
/** Mirrors `routers/jobs_search._MAX_LOCATION_LENGTH`. */
export const MAX_URL_LOCATION_LENGTH = 200;

/**
 * Mirrors the endpoint's `_CATEGORY_RE` / `_LEVEL_RE` (`\A[a-z_]{1,40}\Z`).
 * A slug that cannot match is dropped on the way in rather than 422-ing every
 * search for the visit.
 */
const FACET_SLUG_RE = /^[a-z_]{1,40}$/;
const isFacetSlug = (value: string): boolean => FACET_SLUG_RE.test(value);

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

/**
 * Inverse of `encodeTag`, and the ORDER of the two steps is the whole point.
 *
 * `encodeTag` escapes first and prefixes second, so `{text: '-suite', mode:
 * 'exclude'}` goes out as `-\-suite`. Unescaping only in the "no exclude prefix"
 * branch — which is what this did — handled the include half and corrupted the
 * exclude half: `-\-suite` came back as the literal text `\-suite`, excluded.
 * That is a keyword that matches nothing, so every job the sender excluded
 * silently reappears for the recipient, and the chip on screen reads `\-suite`.
 * Stripping the prefix FIRST and unescaping the remainder makes the decode the
 * exact mirror of the encode in both modes.
 */
function decodeTag(raw: string): SearchTag | null {
  if (!raw) return null;
  // An escaped literal dash (`\-`) is not the exclude prefix — check the prefix
  // against the raw string, whose first character can only be one or the other.
  const excluded = raw.startsWith(EXCLUDE_PREFIX);
  const body = excluded ? raw.slice(EXCLUDE_PREFIX.length) : raw;
  if (!body) return null;
  const text = body.startsWith(ESCAPED_PREFIX)
    ? `${EXCLUDE_PREFIX}${body.slice(ESCAPED_PREFIX.length)}`
    : body;
  return { text, mode: excluded ? 'exclude' : 'include' };
}

const isTimeWindow = (value: string): value is TimeWindow =>
  Object.prototype.hasOwnProperty.call(TIME_WINDOW_DURATIONS, value);

/**
 * Read the filter subset this module owns out of a query string.
 *
 * Returns `null` in TWO cases, and both mean "ordinary visit — let saved filters
 * hydrate": the URL carries none of our params, OR it carries some but not one
 * survived validation. See the note on the second case below; it is the more
 * surprising of the two and it was a real bug before it was a rule.
 *
 * Unknown or malformed values are DROPPED rather than rejected: a link is often
 * hand-edited or truncated by a chat client, and showing a result set that is
 * merely imprecise beats showing an error page.
 *
 * A DROP IS NOT ALWAYS SAFE IN THE SAME DIRECTION, and an earlier version of
 * this comment claimed it was. Dropping an unparseable `time` widens the result
 * set, which is the harmless direction. But `category`, `level`, `location` and
 * include-`tag` are OR-ed WITHIN their dimension, so losing one of them — to a
 * truncated link, or to the caps below — makes the recipient's set strictly
 * SMALLER than the sender's, silently. That is accepted deliberately (see the
 * caps' own note: a hard 400 the reader can only escape by deleting chips one at
 * a time is worse), but it is a tradeoff, not an invariant. Do not read this
 * paragraph as licence to add further silent drops.
 *
 * ...and a link whose owned params ALL fail validation is an ordinary visit, not
 * an empty shared link, and returning `{}` for it was actively destructive.
 * `hydrate{Name}Filters` marks the slice hydrated UNCONDITIONALLY
 * (`createFilterSlice.ts`), so `?time=garbage` made the real saved-filters
 * hydration a permanent no-op and a signed-in reader silently got site defaults
 * instead of their own configuration — no error, no log, and a chat client
 * truncating a link is enough to cause it. Dropping to `null` widens nothing that
 * "drop the bad value" did not already widen; it only stops the drop from taking
 * the reader's whole saved set with it.
 *
 * Nothing representable is lost by that. A DELIBERATELY-cleared link is spelled
 * `?time=all`, which survives validation, comes back non-empty, and still wins
 * over saved filters. A link that clears EVERYTHING including the window is
 * already indistinguishable from an ordinary visit at the other end of the pipe:
 * `buildSearchFromFilters` emits nothing at all for a default filter set, so `/`
 * is what "cleared" looks like on the way out.
 */
export function parseFiltersFromSearch(search: string): Partial<RecentJobsFilters> | null {
  const params = new URLSearchParams(search);
  if (!FILTER_PARAMS.some((name) => params.has(name))) return null;

  const filters: Partial<RecentJobsFilters> = {};

  const time = params.get('time');
  if (time && isTimeWindow(time)) filters.timeWindow = time;

  // Shape, not just count. The endpoint's slug pattern is `\A[a-z_]{1,40}\Z`
  // (`routers/jobs_search._CATEGORY_RE`), so `?category=Software%20Engineering`
  // is a 422 on EVERY search for the whole visit — the same
  // malformed-link-degrades-the-page failure the caps exist to prevent, left
  // half-implemented when only the count was bounded. Dropping the bad value is
  // what this module already does everywhere else.
  const category = params.getAll('category').filter(isFacetSlug).slice(0, MAX_URL_FACET_VALUES);
  if (category.length) filters.category = category;

  const level = params.getAll('level').filter(isFacetSlug).slice(0, MAX_URL_FACET_VALUES);
  if (level.length) filters.level = level;

  // Locations are free text (canonical names like "Austin, TX, US"), so there is
  // no pattern to check — only the endpoint's length bound.
  const location = params
    .getAll('location')
    .filter((value) => value.length > 0 && value.length <= MAX_URL_LOCATION_LENGTH)
    .slice(0, MAX_URL_LOCATIONS);
  if (location.length) filters.location = location;

  // Asks the SHARED guard rather than counting: this is the fifth site that has
  // to agree with `MAX_SEARCH_TAGS`, and a hand-rolled copy is exactly what
  // shipped the last cap bug. A malformed `tag` costs no room — it is dropped,
  // not counted — so a truncated link still fills its 20 slots with real chips.
  const tags: SearchTag[] = [];
  const seenTagText = new Set<string>();
  for (const raw of params.getAll('tag')) {
    if (!canAddSearchTag(tags)) break;
    const tag = decodeTag(raw);
    // Dedupe by text, matching `addSearchTagToFilters`. Without it
    // `?tag=foo&tag=foo` renders two identical chips AND spends two of the
    // twenty slots, so "fills its slots with real chips" would be optimistic.
    if (!tag || seenTagText.has(tag.text)) continue;
    seenTagText.add(tag.text);
    tags.push(tag);
  }
  if (tags.length) filters.searchTags = tags;

  return Object.keys(filters).length > 0 ? filters : null;
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
