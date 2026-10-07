import { describe, it, expect } from 'vitest';
import {
  buildUpstreamUrl,
  buildUpstreamUrlWithEncoder,
  canonicalizeProxyPath,
  resolveProxyPath,
} from '../../../../../../api/utils/proxyPath';
import {
  DOT_SEGMENT_SPELLINGS,
  NFKC_HAZARD_SEGMENTS,
  UNENCODABLE_SEGMENTS,
  WILDCARD_TAIL_ESCAPES,
} from './proxyAttackVectors';

/**
 * Unit tests for the shared canonicalizer + route matcher.
 *
 * These exist because the per-proxy guards cannot see the whole mechanism.
 * Mutation testing proved it: removing the `..` check, removing the
 * structural-hazard gate, and allowing a mid-pattern `*` all SURVIVED the
 * handler-level suites — the real allowlists are narrow enough that a mangled
 * path missed them anyway and still 404'd.
 *
 * That is a coincidence of today's route tables, not a property of the code.
 * The one allowlist entry that spans segments — admin's
 * `locations/aliases/*`, matching the backend's `{raw_text:path}` converter —
 * turns every one of those mutants into a live traversal, because the wildcard
 * will happily eat `../../../internal/enrichment/pending`. The handler-level
 * suites now cover that case too (see `admin.serverless.test.ts`); these tests
 * pin the mechanism directly so the next wildcard entry inherits the guarantee
 * instead of re-discovering it.
 */
describe('canonicalizeProxyPath', () => {
  it('joins the array form and drops empty segments', () => {
    expect(canonicalizeProxyPath(['a', '', 'b'])).toEqual(['a', 'b']);
    expect(canonicalizeProxyPath('/a//b/')).toEqual(['a', 'b']);
    expect(canonicalizeProxyPath(undefined)).toEqual([]);
    expect(canonicalizeProxyPath('')).toEqual([]);
  });

  it('percent-decodes once, so the comparison sees what the backend will', () => {
    // Uvicorn decodes scope["path"] before Starlette routes, and WHATWG URL
    // decodes %2e before collapsing dot segments.
    expect(canonicalizeProxyPath('a%2Fb')).toEqual(['a', 'b']);
    expect(canonicalizeProxyPath('%2e%2e/x')).toBeNull();
    expect(canonicalizeProxyPath('%2E%2E/x')).toBeNull();
  });

  it('rejects dot segments anywhere in the path, not only at the front', () => {
    // The "not only at the front" half is what the admin wildcard depends on.
    expect(canonicalizeProxyPath('..')).toBeNull();
    expect(canonicalizeProxyPath('../x')).toBeNull();
    expect(canonicalizeProxyPath('./x')).toBeNull();
    expect(canonicalizeProxyPath('locations/aliases/../../../internal/x')).toBeNull();
    expect(canonicalizeProxyPath('a/./b')).toBeNull();
    // ...but a dot INSIDE a segment is ordinary text and must survive.
    expect(canonicalizeProxyPath('a.b/..c/d..')).toEqual(['a.b', '..c', 'd..']);
  });

  it('rejects every character that can restructure the upstream URL', () => {
    // Each verified against Node's WHATWG URL; see api/utils/proxyPath.ts.
    expect(canonicalizeProxyPath('a\\b')).toBeNull(); // backslash IS a separator
    expect(canonicalizeProxyPath('a?b')).toBeNull(); // query injection
    expect(canonicalizeProxyPath('a#b')).toBeNull(); // fragment truncation
    expect(canonicalizeProxyPath('a\tb')).toBeNull(); // stripped by the parser
    expect(canonicalizeProxyPath('a\nb')).toBeNull();
    expect(canonicalizeProxyPath('a\rb')).toBeNull();
    expect(canonicalizeProxyPath('a%00b')).toBeNull(); // NUL truncation
    expect(canonicalizeProxyPath('a%7Fb')).toBeNull(); // DEL
  });

  it('rejects malformed percent-encoding instead of falling back to the raw string', () => {
    // The fallback is tempting and wrong: it hands the un-decoded string to
    // `fetch`, which does its own decoding of %2e — so the escape survives.
    expect(canonicalizeProxyPath('%')).toBeNull();
    expect(canonicalizeProxyPath('%zz')).toBeNull();
    expect(canonicalizeProxyPath('a/%e0%a4%a')).toBeNull();
  });

  it('rejects any `%` that survives its one decode — the production bypass', () => {
    // Vercel decodes the request path once before the handler, so these are
    // what `req.query.path` held for a client that encoded three or more
    // times. One more decode leaves `%2e%2e` — not literally `..`, which is
    // why it used to pass — and WHATWG URL then collapsed it inside `fetch`.
    expect(canonicalizeProxyPath('%252e%252e/internal/x')).toBeNull();
    expect(canonicalizeProxyPath('%252E%252E/internal/x')).toBeNull();
    expect(canonicalizeProxyPath('.%252e/internal/x')).toBeNull();
    expect(canonicalizeProxyPath('%252E./internal/x')).toBeNull();
    expect(canonicalizeProxyPath('%25252e%25252e/internal/x')).toBeNull();
    expect(
      canonicalizeProxyPath(
        'locations/aliases/%252e%252e/%252e%252e/%252e%252e/internal/launch-radar/monitors'
      )
    ).toBeNull();
    // Not only dots: no encoding layer at all may survive, so an encoded
    // slash, backslash or NUL one layer down is refused as well.
    expect(canonicalizeProxyPath('a%252Fb')).toBeNull();
    expect(canonicalizeProxyPath('a%255Cb')).toBeNull();
    expect(canonicalizeProxyPath('a%2500b')).toBeNull();
    expect(canonicalizeProxyPath('a%2520b')).toBeNull();
  });

  it.each(DOT_SEGMENT_SPELLINGS)('rejects the dot spelling %s in any position', (dot) => {
    expect(canonicalizeProxyPath(dot)).toBeNull();
    expect(canonicalizeProxyPath(`a/${dot}`)).toBeNull();
    expect(canonicalizeProxyPath(`a/${dot}/b`)).toBeNull();
    expect(canonicalizeProxyPath(['a', dot, 'b'])).toBeNull();
  });

  it('rejects runs of three or more dots too — no legitimate id is all dots', () => {
    expect(canonicalizeProxyPath('...')).toBeNull();
    expect(canonicalizeProxyPath('a/..../b')).toBeNull();
    expect(canonicalizeProxyPath('a/.%2e./b')).toBeNull();
  });

  it('rejects mixed and encoded slash/backslash separators', () => {
    expect(canonicalizeProxyPath('a/..\\/b')).toBeNull();
    expect(canonicalizeProxyPath('..\\../internal/x')).toBeNull();
    expect(canonicalizeProxyPath('a%5Cb')).toBeNull(); // decodes to a backslash
    expect(canonicalizeProxyPath('a%5cb')).toBeNull();
  });

  it('still accepts legitimate keys with spaces, commas, colons and unicode', () => {
    expect(canonicalizeProxyPath('aliases/São Paulo, SP')).toEqual(['aliases', 'São Paulo, SP']);
    expect(canonicalizeProxyPath('aliases/S%C3%A3o%20Paulo')).toEqual(['aliases', 'São Paulo']);
    expect(canonicalizeProxyPath('jobs/greenhouse:openai/q-1')).toEqual([
      'jobs',
      'greenhouse:openai',
      'q-1',
    ]);
  });

  it('rejects Unicode NFKC look-alikes of dots and separators', () => {
    // Each folds to an ASCII hazard under NFKC: ． ․ ﹒ -> `.`, ‥ -> `..`,
    // ／ -> `/`, ＼ -> `\`. Refused in a dynamic position, alone or climbing.
    for (const lookalike of ['\uFF0E', '\u2025', '\u2024', '\uFE52', '\uFF0F', '\uFF3C']) {
      expect(canonicalizeProxyPath(`aliases/${lookalike}`)).toBeNull();
      expect(canonicalizeProxyPath(`aliases/${lookalike}/internal/x`)).toBeNull();
    }
    expect(canonicalizeProxyPath('aliases/\u2025\uFF0F\u2025\uFF0Finternal')).toBeNull();
    expect(canonicalizeProxyPath('aliases/\uFF0E\uFF0E/\uFF0E\uFF0E/internal/x')).toBeNull();
  });

  it.each(NFKC_HAZARD_SEGMENTS)('rejects the NFKC hazard %s in any position', (segment) => {
    expect(canonicalizeProxyPath(segment)).toBeNull();
    expect(canonicalizeProxyPath(`a/${segment}/b`)).toBeNull();
  });

  it('rejects `;` path-parameter and whitespace-padded dot segments', () => {
    // `..;x` is `..` to a server that strips path parameters; `. ` / ` ..` are
    // dot segments to anything that trims.
    for (const segment of ['..;', '.;', '..;jsessionid=x', '. ', ' ..', '.. ', ' . ', '..\uFF1B']) {
      expect(canonicalizeProxyPath(`a/${segment}/b`)).toBeNull();
    }
    // ...but a `;` or a space inside ordinary data is just data.
    expect(canonicalizeProxyPath('a/v1.2;beta/Austin; TX')).toEqual([
      'a',
      'v1.2;beta',
      'Austin; TX',
    ]);
    expect(canonicalizeProxyPath('a/.. x')).toEqual(['a', '.. x']);
  });

  it('accepts real non-ASCII keys and returns them exactly as sent, never NFKC-folded', () => {
    // NFKC is a CHECK only. A decomposed "Zürich" (u + U+0308) must reach the
    // backend decomposed, byte-for-byte — folding it would change the key.
    expect(canonicalizeProxyPath('aliases/Zürich')).toEqual(['aliases', 'Zürich']);
    expect(canonicalizeProxyPath('aliases/München')).toEqual(['aliases', 'München']);
    expect(canonicalizeProxyPath('aliases/São Paulo')).toEqual(['aliases', 'São Paulo']);
    const decomposed = 'Zu\u0308rich';
    expect(canonicalizeProxyPath(`aliases/${decomposed}`)).toEqual(['aliases', decomposed]);
    expect(
      buildUpstreamUrl('https://backend.test', '/api/admin', `locations/aliases/${decomposed}`)
    ).toBe('https://backend.test/api/admin/locations/aliases/Zu%CC%88rich');
  });

  it("lets a lone surrogate through — rejecting it is buildUpstreamUrl's job", () => {
    // Pinned so the builder's try/catch below stays load-bearing: nothing here
    // would stop `encodeURIComponent` from throwing on these.
    for (const segment of UNENCODABLE_SEGMENTS) {
      expect(canonicalizeProxyPath(`a/${segment}`)).toEqual(['a', segment]);
    }
  });
});

describe('the WHATWG URL behaviour these layers defend against', () => {
  // Pinned so the threat model is executable, not folklore: if Node ever stops
  // doing this, these fail and the comments in api/utils/proxyPath.ts are stale.
  it('collapses a percent-encoded dot segment inside fetch', () => {
    const naive = 'http://h/api/admin/locations/aliases/%2e%2e/%2e%2e/%2e%2e/internal/x';
    expect(new URL(naive).pathname).toBe('/api/internal/x');
  });

  it('does NOT collapse a segment whose `%` has itself been encoded', () => {
    const encoded = 'http://h/api/admin/locations/aliases/%252e%252e/internal/x';
    expect(new URL(encoded).pathname).toBe('/api/admin/locations/aliases/%252e%252e/internal/x');
  });
});

describe('buildUpstreamUrl', () => {
  const BACKEND = 'https://backend.test';

  it('builds the bare prefix and a literal path unchanged', () => {
    expect(buildUpstreamUrl(BACKEND, '/api/users', '')).toBe('https://backend.test/api/users');
    expect(buildUpstreamUrl(BACKEND, '/api/jobs', 'facets', '?limit=5')).toBe(
      'https://backend.test/api/jobs/facets?limit=5'
    );
    expect(buildUpstreamUrl(BACKEND, '/api/locations', 'search', '?')).toBe(
      'https://backend.test/api/locations/search?'
    );
  });

  it('percent-encodes every segment itself, keeping `/` as the only separator', () => {
    expect(buildUpstreamUrl(BACKEND, '/api/admin', 'locations/aliases/emea / remote')).toBe(
      'https://backend.test/api/admin/locations/aliases/emea%20/%20remote'
    );
    expect(buildUpstreamUrl(BACKEND, '/api/admin', 'locations/aliases/São Paulo')).toBe(
      'https://backend.test/api/admin/locations/aliases/S%C3%A3o%20Paulo'
    );
    // Characters that would restructure a URL if handed raw to `fetch` are
    // inert once encoded. (The canonicalizer refuses them first; this proves
    // the encoder would hold on its own.)
    expect(buildUpstreamUrl(BACKEND, '/api/admin', 'locations/aliases/a?b#c\\d')).toBe(
      'https://backend.test/api/admin/locations/aliases/a%3Fb%23c%5Cd'
    );
    expect(buildUpstreamUrl(BACKEND, '/api/admin', 'locations/aliases/100%')).toBe(
      'https://backend.test/api/admin/locations/aliases/100%25'
    );
  });

  it('a `%2e%2e` segment that reaches it is refused; `%2e` inside data is encoded, never collapsed', () => {
    // An all-dots segment in any encoding is refused outright, even here.
    expect(buildUpstreamUrl(BACKEND, '/api/admin', 'locations/aliases/%2e%2e/%2e%2e/x')).toBeNull();
    expect(buildUpstreamUrl(BACKEND, '/api/admin', 'locations/aliases/.%2E/x')).toBeNull();
    // A `%2e` that is part of ordinary data gets its `%` encoded, so WHATWG URL
    // sees `%252e` and has nothing to reinterpret as a dot.
    const url = buildUpstreamUrl(BACKEND, '/api/admin', 'locations/aliases/a%2e%2e/x');
    expect(url).toBe('https://backend.test/api/admin/locations/aliases/a%252e%252e/x');
    expect(new URL(url as string).pathname).toBe('/api/admin/locations/aliases/a%252e%252e/x');
  });

  it('keeps the RFC 3986 pchar delimiters literal, as the proxies always sent them', () => {
    expect(buildUpstreamUrl(BACKEND, '/api/jobs', 'workday:tenant/REQ-9')).toBe(
      'https://backend.test/api/jobs/workday:tenant/REQ-9'
    );
    expect(buildUpstreamUrl(BACKEND, '/api/admin', 'locations/aliases/Austin, TX')).toBe(
      'https://backend.test/api/admin/locations/aliases/Austin,%20TX'
    );
    expect(buildUpstreamUrl(BACKEND, '/api/admin', "x/a@b$c&d+e;f=g!h'i(j)k*l")).toBe(
      "https://backend.test/api/admin/x/a@b$c&d+e;f=g!h'i(j)k*l"
    );
  });

  it('refuses a dot or empty segment rather than repairing it', () => {
    expect(buildUpstreamUrl(BACKEND, '/api/admin', '..')).toBeNull();
    expect(
      buildUpstreamUrl(BACKEND, '/api/admin', 'locations/aliases/../../internal/x')
    ).toBeNull();
    expect(buildUpstreamUrl(BACKEND, '/api/admin', 'a/./b')).toBeNull();
    expect(buildUpstreamUrl(BACKEND, '/api/admin', 'a//b')).toBeNull();
    expect(buildUpstreamUrl(BACKEND, '/api/admin', '/a')).toBeNull();
  });

  it('refuses a target whose router segment right after `/api` is `internal`', () => {
    // The only position that selects the JWT-less `/api/internal/*` router.
    // Any case, any encoding, and NFKC look-alikes (fullwidth ｉｎｔｅｒｎａｌ).
    for (const router of [
      'internal',
      'Internal',
      'INTERNAL',
      '%69nternal',
      '\uFF49\uFF4E\uFF54\uFF45\uFF52\uFF4E\uFF41\uFF4C',
    ]) {
      expect(buildUpstreamUrl(BACKEND, `/api/${router}`, 'enrichment/pending')).toBeNull();
      expect(buildUpstreamUrl(BACKEND, `/api/${router}`, '')).toBeNull();
    }
    // Behind a base path too: the `/api` root is parsed from BACKEND_API_URL.
    expect(buildUpstreamUrl('https://backend.test/base', '/api/internal', 'x')).toBeNull();
    // And nothing outside `/api` at all — every proxied router lives under it.
    expect(buildUpstreamUrl(BACKEND, '/internal', 'x')).toBeNull();
    expect(buildUpstreamUrl(BACKEND, '/apix/users', 'x')).toBeNull();
  });

  it('forwards `internal` as DATA anywhere below the router segment', () => {
    // A location alias whose raw text is "Internal", or a job whose id is
    // `internal`, is a legitimate request. The prefix assertion is what keeps
    // a request from climbing to the router position.
    expect(buildUpstreamUrl(BACKEND, '/api/admin', 'locations/aliases/Internal')).toBe(
      'https://backend.test/api/admin/locations/aliases/Internal'
    );
    expect(buildUpstreamUrl(BACKEND, '/api/admin', 'locations/aliases/x/internal/y')).toBe(
      'https://backend.test/api/admin/locations/aliases/x/internal/y'
    );
    expect(buildUpstreamUrl(BACKEND, '/api/jobs', 'greenhouse:acme/internal')).toBe(
      'https://backend.test/api/jobs/greenhouse:acme/internal'
    );
    expect(buildUpstreamUrl(BACKEND, '/api/jobs', 'internal/enrichment')).toBe(
      'https://backend.test/api/jobs/internal/enrichment'
    );
    expect(buildUpstreamUrl(BACKEND, '/api/admin', 'locations/aliases/internal-tools')).toBe(
      'https://backend.test/api/admin/locations/aliases/internal-tools'
    );
  });

  it('refuses a query string that is not a query string', () => {
    // A queryString not starting with `?` would be appended to the path.
    expect(buildUpstreamUrl(BACKEND, '/api/users', 'visit', '/../internal/x')).toBeNull();
    expect(buildUpstreamUrl(BACKEND, '/api/users', 'visit', '#x')).toBeNull();
    // A raw `#` anywhere cuts the URL into a fragment. URLSearchParams encodes
    // one as %23, so only a hand-assembled query string can carry it.
    expect(buildUpstreamUrl(BACKEND, '/api/users', 'visit', '?a=1#x')).toBeNull();
    expect(buildUpstreamUrl(BACKEND, '/api/users', 'visit', '?#')).toBeNull();
    expect(
      buildUpstreamUrl(BACKEND, '/api/users', 'visit', `?${new URLSearchParams({ a: '1#x' })}`)
    ).toBe('https://backend.test/api/users/visit?a=1%23x');
  });

  it('refuses `;` path-parameter and whitespace-padded dot segments', () => {
    for (const segment of ['..;', '.;x', '. ', ' ..', '\u2025', '\uFF0E']) {
      expect(buildUpstreamUrl(BACKEND, '/api/admin', `locations/aliases/${segment}/x`)).toBeNull();
    }
  });

  it.each(UNENCODABLE_SEGMENTS)(
    'returns null instead of throwing on the unencodable segment %j',
    (segment) => {
      // `encodeURIComponent` throws URIError on a lone surrogate; escaping the
      // handler that would be a 500, not the shared 404.
      expect(() =>
        buildUpstreamUrl(BACKEND, '/api/admin', `locations/aliases/${segment}`)
      ).not.toThrow();
      expect(buildUpstreamUrl(BACKEND, '/api/admin', `locations/aliases/${segment}`)).toBeNull();
      expect(buildUpstreamUrl(BACKEND, '/api/jobs', `greenhouse:acme/${segment}`)).toBeNull();
    }
  );

  it('compares against the prefix as parsed from the backend URL, base path and all', () => {
    expect(buildUpstreamUrl('https://backend.test/base', '/api/users', 'visit')).toBe(
      'https://backend.test/base/api/users/visit'
    );
    expect(buildUpstreamUrl('not a url', '/api/users', 'visit')).toBeNull();
  });

  it.each(WILDCARD_TAIL_ESCAPES)(
    'holds on its own with the canonicalizer bypassed: %s',
    (_label, tail) => {
      // Simulate layer 1 regressing to the OLD canonicalizer — decode once,
      // compare dot segments literally — and hand whatever it would have
      // accepted straight to the builder. Layers 2 and 3 must still refuse it
      // or keep it inside the subtree; that is what "defence in depth" means.
      let decoded: string;
      try {
        decoded = decodeURIComponent(`locations/aliases/${tail}`);
      } catch {
        return; // the old canonicalizer refused it too
      }
      const segments = decoded.split('/').filter((s) => s.length > 0);
      if (segments.some((s) => s === '.' || s === '..' || /[\\?#]/.test(s))) return;

      const url = buildUpstreamUrl(BACKEND, '/api/admin', segments.join('/'));
      if (url === null) return;
      const { pathname } = new URL(url);
      expect(pathname.startsWith('/api/admin/locations/aliases/')).toBe(true);
      // `internal` deeper down is DATA inside the alias subtree (the
      // triple-encoded tail forwards as an alias key literally containing
      // `%252e%252e/…/internal/…`); only the router segment after `/api` may
      // never be `internal`, and the prefix check above already pins it.
      // What must hold is that the backend's view — after Uvicorn's one decode —
      // has no dot segment left to climb with.
      expect(decodeURIComponent(pathname).split('/')).not.toContain('..');
      expect(decodeURIComponent(pathname).split('/')).not.toContain('.');
    }
  );
});

/**
 * The ASSERT layer, isolated from the ENCODE layer.
 *
 * With the real encoder, no canonical segment can produce a URL that escapes
 * its prefix, so deleting the prefix assertion would leave every other test
 * green. `buildUpstreamUrlWithEncoder` lets these tests swap in an identity
 * encoder — the encoder regressing to "hand the raw string to fetch" — and
 * prove the assertion still refuses on its own.
 */
describe('buildUpstreamUrl — the prefix assertion holds with the encoder disabled', () => {
  const BACKEND = 'https://backend.test';
  const identity = (segment: string) => segment;

  it('the seam is wired: an identity encoder still builds a harmless URL', () => {
    expect(buildUpstreamUrlWithEncoder(identity, BACKEND, '/api/users', 'visit')).toBe(
      'https://backend.test/api/users/visit'
    );
  });

  it.each([
    // [label, canonical path] — each passes the dot-segment check (TAB is
    // stripped only by the URL parser; `\` is a separator only to it) and,
    // handed raw to `fetch`, lands in a SIBLING router under /api — not under
    // /api/internal — so only the prefix assertion can catch it.
    ['TAB-stuffed dot segments', 'x/.\t./.\t./users/visit'],
    ['backslash-separated climb', 'x\\..\\..\\users'],
    ['newline-stuffed dot segments', 'x/.\n./.\n./features'],
  ])('refuses an escape to a sibling router: %s', (_label, path) => {
    const naive = new URL(`${BACKEND}/api/admin/${path}`).pathname;
    expect(naive.startsWith('/api/admin')).toBe(false); // it really does escape...
    expect(naive.split('/')[2]).not.toBe('internal'); // ...but not to /api/internal
    expect(buildUpstreamUrlWithEncoder(identity, BACKEND, '/api/admin', path)).toBeNull();
  });

  it('refuses an escape to /api/internal', () => {
    expect(
      buildUpstreamUrlWithEncoder(
        identity,
        BACKEND,
        '/api/admin',
        'x/.\t./.\t./internal/enrichment/pending'
      )
    ).toBeNull();
  });

  it('turns an encoder that throws into a refusal', () => {
    const throwing = () => {
      throw new URIError('URI malformed');
    };
    expect(buildUpstreamUrlWithEncoder(throwing, BACKEND, '/api/users', 'visit')).toBeNull();
  });
});

describe('resolveProxyPath', () => {
  const ROUTES = ['', 'visit', 'companies/:id/jobs', 'aliases/*'];

  it('returns the canonical path for an allowlisted route', () => {
    expect(resolveProxyPath(undefined, ROUTES)).toBe('');
    expect(resolveProxyPath('visit', ROUTES)).toBe('visit');
    expect(resolveProxyPath('/visit/', ROUTES)).toBe('visit');
    expect(resolveProxyPath(['companies', 'u-1', 'jobs'], ROUTES)).toBe('companies/u-1/jobs');
  });

  it('requires an exact segment count — a pattern is not a prefix', () => {
    // Without this, `companies/:id/jobs` would also match
    // `companies/x/jobs/../../../internal/enrichment/pending`.
    expect(resolveProxyPath('visit/extra', ROUTES)).toBeNull();
    expect(resolveProxyPath('companies/u-1/jobs/extra', ROUTES)).toBeNull();
    expect(resolveProxyPath('companies/u-1', ROUTES)).toBeNull();
  });

  it('matches literal segments literally', () => {
    expect(resolveProxyPath('visitor', ROUTES)).toBeNull();
    expect(resolveProxyPath('Visit', ROUTES)).toBeNull(); // case-sensitive, like FastAPI
    expect(resolveProxyPath('companies/u-1/JOBS', ROUTES)).toBeNull();
  });

  it('lets `*` span segments, but only as the final element', () => {
    expect(resolveProxyPath('aliases/emea / remote', ROUTES)).toBe('aliases/emea / remote');
    expect(resolveProxyPath('aliases/a/b/c', ROUTES)).toBe('aliases/a/b/c');
    // ONE or more, never zero: the bare collection route is a separate entry.
    expect(resolveProxyPath('aliases', ROUTES)).toBeNull();
    // A mid-pattern `*` is a typo. Treating it as a literal would silently
    // accept `a/*/b` as a real path; treating it as a wildcard would let it
    // swallow arbitrary segments in the middle of an otherwise-fixed route.
    expect(resolveProxyPath('a/x/y/b', ['a/*/b'])).toBeNull();
    expect(resolveProxyPath('a/x/b', ['a/*/b'])).toBeNull();
  });

  it('a wildcard cannot be used to climb out of its own subtree', () => {
    // The exact hazard the wildcard introduces: `*` eats anything, so the
    // dot-segment rejection in the canonicalizer is the ONLY thing standing
    // between `aliases/*` and `/api/internal/*`.
    expect(resolveProxyPath('aliases/../../../internal/enrichment/pending', ROUTES)).toBeNull();
    expect(resolveProxyPath('aliases/%2e%2e/%2e%2e/internal/x', ROUTES)).toBeNull();
    expect(resolveProxyPath('aliases/..\\..\\internal\\x', ROUTES)).toBeNull();
    expect(resolveProxyPath('aliases/x?limit=99999', ROUTES)).toBeNull();
    // Double-encoded dots: the production bypass through admin's wildcard.
    expect(resolveProxyPath('aliases/%252e%252e/%252e%252e/internal/x', ROUTES)).toBeNull();
    expect(resolveProxyPath('aliases/.%252e/%252E./internal/x', ROUTES)).toBeNull();
    expect(resolveProxyPath('aliases/%25252e%25252e/internal/x', ROUTES)).toBeNull();
    expect(resolveProxyPath('aliases/..\\/..%5Cinternal/x', ROUTES)).toBeNull();
  });

  it.each(WILDCARD_TAIL_ESCAPES)('refuses the wildcard-tail escape: %s', (_label, tail) => {
    expect(resolveProxyPath(`aliases/${tail}`, ROUTES)).toBeNull();
  });

  it('a `:id` position refuses every dot spelling, not only the wildcard', () => {
    for (const dot of DOT_SEGMENT_SPELLINGS) {
      expect(resolveProxyPath(`companies/${dot}/jobs`, ROUTES)).toBeNull();
    }
  });

  it('an empty route list refuses everything', () => {
    expect(resolveProxyPath('', [])).toBeNull();
    expect(resolveProxyPath('anything', [])).toBeNull();
  });
});
