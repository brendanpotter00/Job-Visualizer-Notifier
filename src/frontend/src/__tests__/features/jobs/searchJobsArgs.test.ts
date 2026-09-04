import { describe, it, expect } from 'vitest';
import {
  buildSearchJobsArgs,
  buildSearchJobsQuery,
  sinceForTimeWindow,
  EPOCH_ISO,
  RECENT_SEARCH_PAGE_SIZE,
  SIGNED_OUT_FETCH_LIMIT,
} from '../../../features/jobs/searchJobsArgs';
import type { SearchJobsArgs } from '../../../features/jobs/searchJobsTypes';
import type { RecentJobsFilters } from '../../../types';

/**
 * These are the RTK Query cache key. Every assertion below is really an
 * assertion about cache identity: if two filter states that mean the same thing
 * build different args, the walk restarts and every fetched page is thrown away.
 */

const FROZEN_SINCE = '2026-08-10T00:00:00.000Z';

function makeFilters(overrides: Partial<RecentJobsFilters> = {}): RecentJobsFilters {
  return { timeWindow: '24h', softwareOnly: false, ...overrides };
}

/** Signed-in build with a frozen `since`, so tests only vary what they care about. */
function build(
  filters: Partial<RecentJobsFilters>,
  enabledCompanyIds: string[] | null = null,
  isSignedOut = false,
) {
  return buildSearchJobsArgs({
    filters: makeFilters(filters),
    enabledCompanyIds,
    since: FROZEN_SINCE,
    isSignedOut,
  });
}

describe('buildSearchJobsArgs — companies', () => {
  it('sends only the companies that are both enabled and explicitly selected', () => {
    // The saved-companies preference is a hard ceiling: an explicit filter can
    // narrow it but must never widen it back to a company the user disabled.
    const args = build({ company: ['apple', 'netflix', 'stripe'] }, ['apple', 'stripe', 'figma']);

    expect(args?.companies).toEqual(['apple', 'stripe']);
  });

  it('returns null when the enabled set and the selected set are disjoint', () => {
    // The provably-empty case. An empty `company` param cannot express "no
    // companies" on the wire (omitted means ALL), so the caller has to render
    // the empty state without issuing a request.
    const args = build({ company: ['netflix'] }, ['apple', 'stripe']);

    expect(args).toBeNull();
  });

  it('treats null enabled ids as "all companies", leaving only the explicit filter', () => {
    const args = build({ company: ['netflix'] }, null);

    expect(args?.companies).toEqual(['netflix']);
  });

  it('treats an empty enabled-ids array as "all companies", same as null', () => {
    // `[]` is what the preference API returns for a user who has never picked
    // companies. Reading it as "match nothing" would show an empty page to
    // every brand-new signed-in user.
    const args = build({ company: ['netflix'] }, []);

    expect(args?.companies).toEqual(['netflix']);
  });

  it('omits companies entirely when neither the preference nor the filter constrains them', () => {
    expect(build({}, null)?.companies).toBeUndefined();
    expect(build({}, [])?.companies).toBeUndefined();
  });

  it('falls back to the enabled preference when no company filter is applied', () => {
    const args = build({ company: [] }, ['stripe', 'apple']);

    // An empty explicit filter is "no filter", not "nothing matches" — so the
    // preference alone governs, and it comes out sorted.
    expect(args?.companies).toEqual(['apple', 'stripe']);
  });

  it('never returns null when only one side is constrained, however unrelated the values', () => {
    // The null contract is narrow on purpose: it requires BOTH sides non-empty.
    expect(build({ company: ['netflix'] }, [])).not.toBeNull();
    expect(build({}, ['apple'])).not.toBeNull();
  });
});

describe('buildSearchJobsArgs — list normalization', () => {
  it('sorts and de-duplicates every multi-value list', () => {
    const args = build(
      {
        company: ['stripe', 'apple', 'stripe'],
        category: ['software_engineering', 'design', 'design'],
        subcategory: ['frontend', 'backend', 'backend'],
        level: ['senior', 'entry', 'entry'],
        location: ['Seattle, WA, US', 'Austin, TX, US', 'Austin, TX, US'],
        searchTags: [
          { text: 'rust', mode: 'include' },
          { text: 'backend', mode: 'include' },
          { text: 'rust', mode: 'include' },
          { text: 'staff', mode: 'exclude' },
          { text: 'intern', mode: 'exclude' },
          { text: 'staff', mode: 'exclude' },
        ],
      },
      null,
    );

    expect(args?.companies).toEqual(['apple', 'stripe']);
    expect(args?.category).toEqual(['design', 'software_engineering']);
    expect(args?.subcategory).toEqual(['backend', 'frontend']);
    expect(args?.level).toEqual(['entry', 'senior']);
    expect(args?.locations).toEqual(['Austin, TX, US', 'Seattle, WA, US']);
    expect(args?.include).toEqual(['backend', 'rust']);
    expect(args?.exclude).toEqual(['intern', 'staff']);
  });

  it('produces identical args for the same filter set in a different order', () => {
    // The whole point of normalization: re-ordering chips in the UI must not
    // mint a new cache entry and re-fetch the walk from page 1.
    const forward = build(
      {
        company: ['apple', 'stripe'],
        category: ['design', 'software_engineering'],
        subcategory: ['backend', 'frontend'],
        level: ['entry', 'senior'],
        location: ['Austin, TX, US', 'Seattle, WA, US'],
        searchTags: [
          { text: 'backend', mode: 'include' },
          { text: 'rust', mode: 'include' },
          { text: 'intern', mode: 'exclude' },
          { text: 'staff', mode: 'exclude' },
        ],
      },
      ['apple', 'stripe', 'figma'],
    );

    const reversed = build(
      {
        company: ['stripe', 'apple'],
        category: ['software_engineering', 'design'],
        subcategory: ['frontend', 'backend'],
        level: ['senior', 'entry'],
        location: ['Seattle, WA, US', 'Austin, TX, US'],
        searchTags: [
          { text: 'staff', mode: 'exclude' },
          { text: 'rust', mode: 'include' },
          { text: 'intern', mode: 'exclude' },
          { text: 'backend', mode: 'include' },
        ],
      },
      ['figma', 'stripe', 'apple'],
    );

    expect(forward).toEqual(reversed);
  });

  it('collapses empty lists to undefined rather than []', () => {
    // `[]` and `undefined` serialize to different cache keys but mean the same
    // thing, so only one of them is ever allowed to reach the args.
    const args = build({
      company: [],
      category: [],
      subcategory: [],
      level: [],
      location: [],
      searchTags: [],
    });

    expect(args).toEqual({
      companies: undefined,
      category: undefined,
      subcategory: undefined,
      level: undefined,
      locations: undefined,
      include: undefined,
      exclude: undefined,
      since: FROZEN_SINCE,
      limit: RECENT_SEARCH_PAGE_SIZE,
    });
  });

  it('leaves every list undefined when the filters carry none', () => {
    const args = build({});

    expect(args?.companies).toBeUndefined();
    expect(args?.category).toBeUndefined();
    expect(args?.subcategory).toBeUndefined();
    expect(args?.level).toBeUndefined();
    expect(args?.locations).toBeUndefined();
    expect(args?.include).toBeUndefined();
    expect(args?.exclude).toBeUndefined();
  });
});

describe('buildSearchJobsArgs — search tags', () => {
  it('splits search tags into include and exclude by mode', () => {
    const args = build({
      searchTags: [
        { text: 'engineer', mode: 'include' },
        { text: 'manager', mode: 'exclude' },
        { text: 'python', mode: 'include' },
      ],
    });

    expect(args?.include).toEqual(['engineer', 'python']);
    expect(args?.exclude).toEqual(['manager']);
  });

  it('leaves the opposite side undefined when every tag shares one mode', () => {
    const onlyExcludes = build({
      searchTags: [
        { text: 'manager', mode: 'exclude' },
        { text: 'director', mode: 'exclude' },
      ],
    });

    expect(onlyExcludes?.include).toBeUndefined();
    expect(onlyExcludes?.exclude).toEqual(['director', 'manager']);

    const onlyIncludes = build({ searchTags: [{ text: 'rust', mode: 'include' }] });

    expect(onlyIncludes?.include).toEqual(['rust']);
    expect(onlyIncludes?.exclude).toBeUndefined();
  });

  it('keeps a term that appears in both modes on both sides', () => {
    // Contradictory, but it is the user's stated filter — the server decides
    // what an include-and-exclude of the same term means, not this builder.
    const args = build({
      searchTags: [
        { text: 'senior', mode: 'include' },
        { text: 'senior', mode: 'exclude' },
      ],
    });

    expect(args?.include).toEqual(['senior']);
    expect(args?.exclude).toEqual(['senior']);
  });
});

describe('buildSearchJobsArgs — page size', () => {
  it('caps a signed-out reader at the sign-in overlay limit', () => {
    // 13 = the 12 visible cards plus one probe row, which is how the list
    // learns a 13th job exists and the overlay should render.
    expect(build({}, null, true)?.limit).toBe(SIGNED_OUT_FETCH_LIMIT);
    expect(SIGNED_OUT_FETCH_LIMIT).toBe(13);
  });

  it('gives a signed-in reader the full page size', () => {
    expect(build({}, null, false)?.limit).toBe(RECENT_SEARCH_PAGE_SIZE);
    expect(RECENT_SEARCH_PAGE_SIZE).toBe(50);
  });

  it('passes the frozen since through untouched', () => {
    // The builder must never read the clock: `since` participates in the
    // server's cursor fingerprint and has to survive the whole walk.
    expect(build({})?.since).toBe(FROZEN_SINCE);
  });
});

describe('sinceForTimeWindow', () => {
  const NOON = Date.parse('2026-08-10T12:34:56.789Z');

  it('floors to a whole minute so sub-minute clock drift cannot change the value', () => {
    expect(sinceForTimeWindow('24h', NOON)).toBe('2026-08-09T12:34:00.000Z');
  });

  it('returns the same string for two reads five seconds apart in the same minute', () => {
    // This is the property that keeps the cache key stable across re-renders:
    // two components computing "3 hours ago" microseconds (or seconds) apart
    // must address the same cache entry, not duplicate the request.
    const tick = Date.parse('2026-08-10T12:34:50.000Z');
    const first = sinceForTimeWindow('3h', tick);
    const second = sinceForTimeWindow('3h', tick + 5_000);

    expect(first).toBe(second);
    expect(first).toBe('2026-08-10T09:34:00.000Z');
  });

  it('moves to the next boundary once the minute actually rolls over', () => {
    // The flip side: quantization must not be so coarse that time stops.
    const before = sinceForTimeWindow('1h', Date.parse('2026-08-10T12:34:59.999Z'));
    const after = sinceForTimeWindow('1h', Date.parse('2026-08-10T12:35:00.000Z'));

    expect(before).toBe('2026-08-10T11:34:00.000Z');
    expect(after).toBe('2026-08-10T11:35:00.000Z');
  });

  it('maps the all-time window to the epoch instead of omitting the bound', () => {
    // `all` has an infinite duration, so the arithmetic would yield -Infinity.
    // An explicit floor keeps every request in one server-side mode.
    expect(sinceForTimeWindow('all', NOON)).toBe(EPOCH_ISO);
    expect(EPOCH_ISO).toBe('1970-01-01T00:00:00.000Z');
  });

  it('subtracts the right duration for each window', () => {
    expect(sinceForTimeWindow('30m', NOON)).toBe('2026-08-10T12:04:00.000Z');
    expect(sinceForTimeWindow('12h', NOON)).toBe('2026-08-10T00:34:00.000Z');
    expect(sinceForTimeWindow('7d', NOON)).toBe('2026-08-03T12:34:00.000Z');
    expect(sinceForTimeWindow('90d', NOON)).toBe('2026-05-12T12:34:00.000Z');
  });

  it('always emits a UTC instant on a zero-second boundary', () => {
    for (const window of ['30m', '6h', '24h', '3d', '180d'] as const) {
      expect(sinceForTimeWindow(window, NOON)).toMatch(/T\d{2}:\d{2}:00\.000Z$/);
    }
  });
});

describe('buildSearchJobsQuery', () => {
  function makeArgs(overrides: Partial<SearchJobsArgs> = {}): SearchJobsArgs {
    return { since: FROZEN_SINCE, limit: RECENT_SEARCH_PAGE_SIZE, ...overrides };
  }

  it('always sends since and limit', () => {
    const params = new URLSearchParams(buildSearchJobsQuery(makeArgs(), null));

    expect(params.get('since')).toBe(FROZEN_SINCE);
    expect(params.get('limit')).toBe('50');
  });

  it('sends subcategory as TWO appended params in sorted order, never comma-joined', () => {
    // `String(array)` comma-joins, and 'backend,frontend' would reach the
    // backend as ONE bogus slug that matches nothing — with a 200.
    const query = buildSearchJobsQuery(
      makeArgs({ subcategory: ['backend', 'frontend'] }),
      null,
    );

    expect(query).toContain('subcategory=backend&subcategory=frontend');
    expect(new URLSearchParams(query).getAll('subcategory')).toEqual([
      'backend',
      'frontend',
    ]);
  });

  it('sends a full_stack selection VERBATIM — the client never expands it', () => {
    // THE DOUBLE-EXPANSION GUARD. The server owns the Frontend/Backend ⊃ Full
    // Stack widening; expanding here too would put two copies of the taxonomy
    // in play and would persist the widened pair into saved filters and chips.
    const params = new URLSearchParams(
      buildSearchJobsQuery(makeArgs({ subcategory: ['full_stack'] }), null),
    );
    expect(params.getAll('subcategory')).toEqual(['full_stack']);

    const widened = new URLSearchParams(
      buildSearchJobsQuery(makeArgs({ subcategory: ['backend'] }), null),
    );
    expect(widened.getAll('subcategory')).toEqual(['backend']);
  });

  it('omits subcategory entirely when none is selected', () => {
    const params = new URLSearchParams(buildSearchJobsQuery(makeArgs(), null));
    expect(params.has('subcategory')).toBe(false);
  });

  it('repeats a multi-value filter instead of comma-joining it', () => {
    // Canonical locations and free-text keywords contain commas, so a joined
    // scalar could not be split back apart on the server.
    const query = buildSearchJobsQuery(
      makeArgs({ companies: ['apple', 'stripe'], category: ['design', 'software_engineering'] }),
      null,
    );

    expect(query).toContain('company=apple&company=stripe');

    const params = new URLSearchParams(query);
    expect(params.getAll('company')).toEqual(['apple', 'stripe']);
    expect(params.getAll('category')).toEqual(['design', 'software_engineering']);
  });

  it('uses the singular server param names for each list', () => {
    const params = new URLSearchParams(
      buildSearchJobsQuery(
        makeArgs({
          companies: ['apple'],
          category: ['design'],
          level: ['entry'],
          locations: ['Austin, TX, US'],
          include: ['rust'],
          exclude: ['manager'],
        }),
        null,
      ),
    );

    expect(params.getAll('company')).toEqual(['apple']);
    expect(params.getAll('category')).toEqual(['design']);
    expect(params.getAll('level')).toEqual(['entry']);
    expect(params.getAll('location')).toEqual(['Austin, TX, US']);
    expect(params.getAll('include')).toEqual(['rust']);
    expect(params.getAll('exclude')).toEqual(['manager']);
  });

  it('omits a list parameter entirely when it is undefined', () => {
    const query = buildSearchJobsQuery(makeArgs(), null);

    for (const name of ['company', 'category', 'level', 'location', 'include', 'exclude']) {
      expect(query).not.toContain(`${name}=`);
    }
  });

  it('encodes spaces as %20, never +', () => {
    // The request crosses a Vercel proxy that re-parses the query string, where
    // a `+` is ambiguous rather than a space.
    const query = buildSearchJobsQuery(makeArgs({ locations: ['Austin, TX, US'] }), null);

    expect(query).toContain('location=Austin%2C%20TX%2C%20US');
    expect(query).not.toContain('+');
  });

  it('preserves a literal plus sign in a keyword', () => {
    // The `+` → `%20` rewrite is safe only because URLSearchParams has already
    // escaped real plus signs to %2B. "C++" is the case that proves it.
    const query = buildSearchJobsQuery(makeArgs({ include: ['C++'] }), null);

    expect(query).toContain('include=C%2B%2B');
    expect(new URLSearchParams(query).get('include')).toBe('C++');
  });

  it('omits the cursor on the first page', () => {
    const query = buildSearchJobsQuery(makeArgs(), null);

    expect(query).not.toContain('cursor');
  });

  it('sends the cursor on a follow-up page', () => {
    const query = buildSearchJobsQuery(makeArgs(), '2026-08-09T12:00:00Z|abc123');

    expect(new URLSearchParams(query).get('cursor')).toBe('2026-08-09T12:00:00Z|abc123');
  });

  it('sends an empty-string cursor rather than dropping it', () => {
    // Only `null` means "first page"; an empty string is still a cursor value
    // and must reach the server so a malformed walk fails loudly.
    const query = buildSearchJobsQuery(makeArgs(), '');

    expect(query).toContain('cursor=');
  });

  it('serializes args from the builder without further massaging', () => {
    // End-to-end of the two pure functions: what the builder emits is exactly
    // what goes on the wire.
    const args = buildSearchJobsArgs({
      filters: makeFilters({
        company: ['stripe', 'apple'],
        location: ['Austin, TX, US'],
        searchTags: [
          { text: 'senior engineer', mode: 'include' },
          { text: 'manager', mode: 'exclude' },
        ],
      }),
      enabledCompanyIds: ['apple', 'stripe', 'figma'],
      since: FROZEN_SINCE,
      isSignedOut: true,
    });

    const params = new URLSearchParams(buildSearchJobsQuery(args as SearchJobsArgs, null));

    expect(params.getAll('company')).toEqual(['apple', 'stripe']);
    expect(params.getAll('location')).toEqual(['Austin, TX, US']);
    expect(params.getAll('include')).toEqual(['senior engineer']);
    expect(params.getAll('exclude')).toEqual(['manager']);
    expect(params.get('limit')).toBe(String(SIGNED_OUT_FETCH_LIMIT));
    expect(params.get('since')).toBe(FROZEN_SINCE);
  });
});
