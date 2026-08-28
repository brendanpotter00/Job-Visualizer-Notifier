import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { VercelRequest, VercelResponse } from '@vercel/node';
import { TRAVERSAL_VECTORS, UNKNOWN_BUT_HARMLESS, type PathValue } from './proxyAttackVectors';

/**
 * The `?path=` allowlist guard, instantiated once per internal-key proxy.
 *
 * SECURITY BOUNDARY. Each `api/*.ts` function is a public internet endpoint and
 * attaches `X-Internal-Key` UNCONDITIONALLY, so it always clears the backend's
 * `require_internal_key` middleware. Before the allowlist, splicing the raw
 * `?path=` into the upstream URL let an ANONYMOUS caller reach
 * `/api/internal/enrichment/*` with that key — a mutating, JWT-less surface.
 *
 * The load-bearing assertion in every rejection case is
 * `expect(fetch).not.toHaveBeenCalled()`, not `expect(status).toBe(404)`.
 * "The backend refused it" is not the property under test; the proxy holds the
 * key, so forwarding at all and letting the backend decide IS the bug.
 */
export interface ProxyGuardSpec {
  /** Display name, e.g. 'users'. */
  name: string;
  /** Backend prefix the proxy owns, e.g. '/api/users'. */
  prefix: string;
  handler: (req: VercelRequest, res: VercelResponse) => Promise<void>;
  /**
   * `?path=` values this proxy must still forward, one per allowlisted backend
   * route, plus the upstream path each is expected to produce. `''` is the bare
   * prefix.
   */
  legitimate: Array<[path: PathValue, expectedUpstreamPath: string]>;
  /**
   * A legitimate path that should survive sloppy-but-harmless spelling
   * (trailing slash, duplicated slashes), and the upstream path it normalizes
   * to. The allowlist must not 404 a caller for a spelling the backend would
   * have 307'd.
   */
  normalizes: [path: PathValue, expectedUpstreamPath: string];
  /** Methods the proxy accepts, exercised against `legitimate[0]`. */
  methods: string[];
  /**
   * Headers the FORWARDING cases need — only `api/jobs-qa.ts`, which keeps a
   * cheap anonymous pre-filter after the allowlist. Rejection cases
   * deliberately ignore this: they are run both anonymous and credentialed.
   */
  headers?: Record<string, string>;
}

function mockJsonResponse(status: number, body: unknown) {
  const serialized = JSON.stringify(body);
  return {
    status,
    headers: { get: (key: string) => (key === 'content-type' ? 'application/json' : null) },
    text: async () => serialized,
    json: async () => body,
  };
}

export function runProxyAllowlistGuard(spec: ProxyGuardSpec): void {
  describe(`api/${spec.name} — ?path= allowlist (SECURITY BOUNDARY)`, () => {
    let mockRes: Partial<VercelResponse>;
    let fetchMock: ReturnType<typeof vi.fn>;

    const makeReq = (
      query: Record<string, unknown>,
      overrides: Partial<VercelRequest> = {}
    ): VercelRequest =>
      ({ method: 'GET', query, headers: {}, body: undefined, ...overrides }) as VercelRequest;

    beforeEach(() => {
      mockRes = {
        status: vi.fn().mockReturnThis(),
        json: vi.fn().mockReturnThis(),
        end: vi.fn().mockReturnThis(),
        setHeader: vi.fn().mockReturnThis(),
      };
      fetchMock = vi.fn().mockResolvedValue(mockJsonResponse(200, {}));
      global.fetch = fetchMock as unknown as typeof fetch;
      // Set on purpose: if any rejection case DID reach `fetch`, it would carry
      // a real credential. "Never called" is therefore "never credentialed".
      process.env.INTERNAL_API_KEY = 'test-internal-key';
      process.env.BACKEND_API_URL = 'https://backend.test';
    });

    afterEach(() => {
      delete process.env.INTERNAL_API_KEY;
      delete process.env.BACKEND_API_URL;
      vi.clearAllMocks();
    });

    describe('rejects every traversal spelling before the key is attached', () => {
      it.each(TRAVERSAL_VECTORS)('anonymous GET %s', async (_label, pathValue) => {
        await spec.handler(makeReq({ path: pathValue }), mockRes as VercelResponse);

        expect(fetchMock).not.toHaveBeenCalled();
        expect(mockRes.status).toHaveBeenCalledWith(404);
        expect(mockRes.json).toHaveBeenCalledWith({ detail: 'Not Found' });
      });

      it.each(TRAVERSAL_VECTORS)('credentialed GET %s', async (_label, pathValue) => {
        // Presenting a token must not help: the proxy cannot verify one, and an
        // earlier version of api/jobs-qa.ts was bypassed by exactly that
        // ("is an Authorization header present?").
        await spec.handler(
          makeReq({ path: pathValue }, { headers: { authorization: 'Bearer anything' } }),
          mockRes as VercelResponse
        );

        expect(fetchMock).not.toHaveBeenCalled();
        expect(mockRes.status).toHaveBeenCalledWith(404);
      });

      it.each(TRAVERSAL_VECTORS)('anonymous POST with a body %s', async (_label, pathValue) => {
        // The dangerous half. `POST ..%2Finternal%2Fenrichment%2Fresults`
        // writes arbitrary enrichment data onto up to 500 job rows per call.
        await spec.handler(
          makeReq(
            { path: pathValue },
            { method: 'POST', body: { results: [{ id: 'pwned' }] } }
          ),
          mockRes as VercelResponse
        );

        expect(fetchMock).not.toHaveBeenCalled();
        expect(mockRes.status).toHaveBeenCalledWith(404);
      });

      it.each(['PUT', 'PATCH', 'DELETE'])(
        'anonymous %s with a body is refused too',
        async (method) => {
          await spec.handler(
            makeReq(
              { path: '../internal/enrichment/results' },
              { method, body: { results: [] } }
            ),
            mockRes as VercelResponse
          );

          expect(fetchMock).not.toHaveBeenCalled();
          expect(mockRes.status).toHaveBeenCalledWith(404);
        }
      );

      it('extra query params cannot smuggle the path past the check', async () => {
        // `path` is destructured out and every OTHER param is forwarded to the
        // upstream query string. A second `path`-ish param must not reopen it.
        await spec.handler(
          makeReq({
            path: '../internal/enrichment/pending',
            limit: '500',
            Path: 'facets',
          }),
          mockRes as VercelResponse
        );

        expect(fetchMock).not.toHaveBeenCalled();
      });
    });

    describe('the refusal leaks nothing', () => {
      it.each(UNKNOWN_BUT_HARMLESS)(
        'an unknown-but-harmless path %s is refused identically to a traversal',
        async (pathValue) => {
          await spec.handler(makeReq({ path: pathValue }), mockRes as VercelResponse);
          const unknownCalls = {
            status: (mockRes.status as ReturnType<typeof vi.fn>).mock.calls,
            json: (mockRes.json as ReturnType<typeof vi.fn>).mock.calls,
          };

          vi.clearAllMocks();
          await spec.handler(
            makeReq({ path: '../internal/enrichment/pending' }),
            mockRes as VercelResponse
          );

          // Byte-identical: an anonymous prober cannot tell "this internal
          // route exists but the proxy refuses it" from "no such route".
          expect(unknownCalls.status).toEqual(
            (mockRes.status as ReturnType<typeof vi.fn>).mock.calls
          );
          expect(unknownCalls.json).toEqual(
            (mockRes.json as ReturnType<typeof vi.fn>).mock.calls
          );
          expect(fetchMock).not.toHaveBeenCalled();
        }
      );

      it('never responds 401/403/500 to a refused path', async () => {
        // A distinct status is itself an oracle, and a 500 (from an unhandled
        // decodeURIComponent throw) also reads as "something is there".
        for (const [, pathValue] of TRAVERSAL_VECTORS) {
          vi.clearAllMocks();
          await spec.handler(makeReq({ path: pathValue }), mockRes as VercelResponse);
          const statuses = (mockRes.status as ReturnType<typeof vi.fn>).mock.calls.flat();
          expect(statuses).toEqual([404]);
        }
      });
    });

    describe('every documented legitimate path still forwards', () => {
      it.each(spec.legitimate)('forwards %s', async (pathValue, expectedPath) => {
        const query = pathValue === '' ? {} : { path: pathValue };
        await spec.handler(
          makeReq(query, { headers: spec.headers ?? {} }),
          mockRes as VercelResponse
        );

        expect(fetchMock).toHaveBeenCalledTimes(1);
        // Compare the PARSED pathname, not the raw string: that is what
        // `fetch` actually requests, so it proves the dot segments the raw
        // string might carry cannot survive. It also tolerates the handlers
        // that append an empty `?` (api/locations.ts always does).
        expect(new URL(fetchMock.mock.calls[0][0] as string).pathname).toBe(expectedPath);
      });

      it.each(spec.methods)('forwards %s on an allowlisted path', async (method) => {
        const [pathValue, expectedPath] = spec.legitimate[0];
        const query = pathValue === '' ? {} : { path: pathValue };
        await spec.handler(
          makeReq(query, {
            method,
            body: method === 'GET' ? undefined : { a: 1 },
            headers: spec.headers ?? {},
          }),
          mockRes as VercelResponse
        );

        expect(fetchMock).toHaveBeenCalledTimes(1);
        expect(new URL(fetchMock.mock.calls[0][0] as string).pathname).toBe(expectedPath);
        // `api/jobs.ts` and `api/locations.ts` are GET-only and never set
        // `method`, which `fetch` defaults to GET. The proxies that DO forward
        // a method are still pinned, because their non-GET cases would fail.
        expect((fetchMock.mock.calls[0][1] as RequestInit).method ?? 'GET').toBe(method);
      });

      it('normalizes a sloppy spelling instead of 404ing it', async () => {
        const [pathValue, expectedPath] = spec.normalizes;
        await spec.handler(
          makeReq({ path: pathValue }, { headers: spec.headers ?? {} }),
          mockRes as VercelResponse
        );

        expect(fetchMock).toHaveBeenCalledTimes(1);
        expect(new URL(fetchMock.mock.calls[0][0] as string).pathname).toBe(expectedPath);
      });

      it('never follows a redirect on a forwarded request', async () => {
        // Node's fetch defaults to following redirects and PRESERVES headers
        // across a same-origin 3xx — including the injected X-Internal-Key.
        // With Starlette's `redirect_slashes=True` that turned a trailing slash
        // into a working bypass on api/jobs-qa.ts.
        const [pathValue] = spec.legitimate[0];
        const query = pathValue === '' ? {} : { path: pathValue };
        await spec.handler(
          makeReq(query, { headers: spec.headers ?? {} }),
          mockRes as VercelResponse
        );

        expect((fetchMock.mock.calls[0][1] as RequestInit).redirect).toBe('manual');
      });
    });
  });
}
