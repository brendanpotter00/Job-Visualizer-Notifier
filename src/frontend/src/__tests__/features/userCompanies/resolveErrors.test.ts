import { describe, it, expect } from 'vitest';
import {
  describeResolveError,
  RESOLVE_FAILURE_REASONS,
  type ResolveFailureReason,
} from '../../../features/userCompanies/resolveErrors';

/** Builds the flat resolver 422 the backend returns (NOT nested under `detail`). */
function resolverFailure(reason: string) {
  return {
    status: 422,
    data: { reason, finalUrl: 'https://example.com/careers', hops: [] },
  };
}

/** Every branch must produce real, renderable copy — never '', undefined, or '[object Object]'. */
function expectRenderableCopy(display: { title: string; detail: string }) {
  expect(typeof display.title).toBe('string');
  expect(display.title.trim().length).toBeGreaterThan(0);
  expect(typeof display.detail).toBe('string');
  expect(display.detail.trim().length).toBeGreaterThan(0);
  expect(display.title).not.toContain('[object Object]');
  expect(display.detail).not.toContain('[object Object]');
  expect(display.title).not.toContain('undefined');
  expect(display.detail).not.toContain('undefined');
}

describe('describeResolveError', () => {
  describe('resolver 422 reason codes (flat body)', () => {
    it('covers every reason code the backend can emit', () => {
      // Guards against the list drifting from the backend's url_guard /
      // ats_discovery constants without anyone updating the copy.
      expect(RESOLVE_FAILURE_REASONS).toHaveLength(13);
    });

    it.each(RESOLVE_FAILURE_REASONS)('maps %s to renderable copy', (reason) => {
      const display = describeResolveError(resolverFailure(reason));
      expectRenderableCopy(display);
      expect(display.reasonCode).toBe(reason);
    });

    it('gives every reason code a DISTINCT title and detail', () => {
      const titles = new Set<string>();
      const details = new Set<string>();
      for (const reason of RESOLVE_FAILURE_REASONS) {
        const display = describeResolveError(resolverFailure(reason));
        titles.add(display.title);
        details.add(display.detail);
      }
      // Copy-pasted placeholder copy would collapse these sets.
      expect(details.size).toBe(RESOLVE_FAILURE_REASONS.length);
      expect(titles.size).toBe(RESOLVE_FAILURE_REASONS.length);
    });

    it('names the supported boards for no_ats_detected', () => {
      const { detail } = describeResolveError(resolverFailure('no_ats_detected'));
      for (const board of ['Greenhouse', 'Ashby', 'Lever', 'Gem', 'Workday', 'Eightfold']) {
        expect(detail).toContain(board);
      }
    });

    it('explains the private-network case in plain words', () => {
      const { detail } = describeResolveError(resolverFailure('resolves_to_private_address'));
      expect(detail).toMatch(/private/i);
      expect(detail).toMatch(/internal|localhost|192\.168/i);
    });

    it('explains deadline_exceeded as a slow page', () => {
      const { detail } = describeResolveError(resolverFailure('deadline_exceeded'));
      expect(detail).toMatch(/too long|waiting/i);
    });
  });

  describe('unknown / future reason codes', () => {
    it('falls back to generic copy but still surfaces the raw code', () => {
      const display = describeResolveError(resolverFailure('quantum_flux_detected'));
      expectRenderableCopy(display);
      // Diagnosability is the whole point: the code must survive to the screen.
      expect(display.reasonCode).toBe('quantum_flux_detected');
      expect(display.detail).toContain('quantum_flux_detected');
    });

    it('does not claim the unknown code is one of the known ones', () => {
      const display = describeResolveError(resolverFailure('brand_new_code'));
      const knownDetails = RESOLVE_FAILURE_REASONS.map(
        (r: ResolveFailureReason) => describeResolveError(resolverFailure(r)).detail
      );
      expect(knownDetails).not.toContain(display.detail);
    });
  });

  describe('FastAPI request-validation 422 (different shape — no `reason` key)', () => {
    it('is handled distinctly from the resolver 422 and does not crash', () => {
      const display = describeResolveError({
        status: 422,
        data: {
          detail: [
            {
              type: 'string_too_short',
              loc: ['body', 'url'],
              msg: 'String should have at least 1 character',
            },
          ],
        },
      });
      expectRenderableCopy(display);
      expect(display.reasonCode).toBeUndefined();
      expect(display.detail).toContain('String should have at least 1 character');
    });

    it('still renders when the validation array carries no usable msg', () => {
      const display = describeResolveError({
        status: 422,
        data: { detail: [{ loc: ['body', 'url'] }] },
      });
      expectRenderableCopy(display);
      expect(display.detail).toMatch(/2048/);
    });

    it('handles an extra-field rejection (extra="forbid")', () => {
      const display = describeResolveError({
        status: 422,
        data: {
          detail: [
            { type: 'extra_forbidden', loc: ['body', 'ur1'], msg: 'Extra inputs are not permitted' },
          ],
        },
      });
      expectRenderableCopy(display);
      expect(display.detail).toContain('Extra inputs are not permitted');
    });

    it('handles a 422 whose body matches neither known shape', () => {
      const display = describeResolveError({ status: 422, data: { something: 'else' } });
      expectRenderableCopy(display);
    });
  });

  describe('other HTTP statuses', () => {
    it('401 tells the user to sign in again', () => {
      const display = describeResolveError({ status: 401, data: { detail: 'Not authenticated' } });
      expectRenderableCopy(display);
      expect(display.title).toMatch(/sign in/i);
    });

    it('429 quotes the documented rate limit', () => {
      const display = describeResolveError({ status: 429, data: { detail: 'Too many requests' } });
      expectRenderableCopy(display);
      expect(display.detail).toContain('10');
      expect(display.detail).toMatch(/minute/i);
    });

    it('503 explains that the SERVER flag is off and is separate from the client one', () => {
      const display = describeResolveError({
        status: 503,
        data: { detail: 'Custom company sources are not enabled' },
      });
      expectRenderableCopy(display);
      expect(display.detail).toMatch(/separate/i);
    });

    it('502 from the Vercel proxy surfaces the proxy `details` field', () => {
      const display = describeResolveError({
        status: 502,
        data: { error: 'Upstream backend unavailable', details: 'ECONNREFUSED 127.0.0.1:8000' },
      });
      expectRenderableCopy(display);
      expect(display.detail).toContain('ECONNREFUSED 127.0.0.1:8000');
    });

    it('502 still renders when the proxy sends no `details`', () => {
      const display = describeResolveError({ status: 502, data: { error: 'boom' } });
      expectRenderableCopy(display);
    });

    it('an unmapped status still reports the status number', () => {
      const display = describeResolveError({ status: 500, data: { detail: 'Internal error' } });
      expectRenderableCopy(display);
      expect(display.detail).toContain('500');
      expect(display.detail).toContain('Internal error');
    });

    it('an unmapped status with no body still renders', () => {
      const display = describeResolveError({ status: 418, data: undefined });
      expectRenderableCopy(display);
      expect(display.detail).toContain('418');
    });
  });

  describe('non-HTTP RTK Query errors', () => {
    it('FETCH_ERROR reads as a connectivity problem', () => {
      const display = describeResolveError({ status: 'FETCH_ERROR', error: 'Failed to fetch' });
      expectRenderableCopy(display);
      expect(display.detail).toMatch(/offline|connection|unreachable/i);
    });

    it('TIMEOUT_ERROR renders', () => {
      const display = describeResolveError({ status: 'TIMEOUT_ERROR', error: 'timed out' });
      expectRenderableCopy(display);
    });

    it('PARSING_ERROR renders', () => {
      const display = describeResolveError({
        status: 'PARSING_ERROR',
        originalStatus: 200,
        data: '<html>',
        error: 'Unexpected token',
      });
      expectRenderableCopy(display);
    });

    it('CUSTOM_ERROR surfaces its message', () => {
      const display = describeResolveError({ status: 'CUSTOM_ERROR', error: 'guard tripped' });
      expectRenderableCopy(display);
      expect(display.detail).toContain('guard tripped');
    });
  });

  describe('degenerate inputs', () => {
    it.each([
      ['null', null],
      ['undefined', undefined],
      ['a bare string', 'boom'],
      ['a number', 42],
      ['an empty object', {}],
      ['a SerializedError', { name: 'Error', message: 'kaboom' }],
    ])('renders copy for %s without crashing', (_label, input) => {
      expectRenderableCopy(describeResolveError(input));
    });

    it('includes a SerializedError message when present', () => {
      const display = describeResolveError({ name: 'Error', message: 'kaboom' });
      expect(display.detail).toContain('kaboom');
    });
  });
});
