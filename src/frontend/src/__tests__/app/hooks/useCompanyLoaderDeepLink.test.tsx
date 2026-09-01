import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { BrowserRouter } from 'react-router-dom';
import React from 'react';

/**
 * The `/companies` cold-load selection gate.
 *
 * `/companies` picks its company synchronously on mount, but a `?company=u-…`
 * cannot be validated until an AUTHENTICATED query resolves. Waiting for that
 * query on every load would slow the page down for everyone — including every
 * signed-out visitor — so the wait is scoped to the only case that needs it: a
 * raw `?company=` value shaped like a custom board id.
 *
 * T5 (a public deep link still resolves on the very first dispatch, with the
 * authed query deliberately left hanging) is the guard against that regression.
 * T9 is the other half: a custom deep link must NOT be answered with the default
 * company and must not have its URL rewritten while it waits.
 */

const { flagState } = vi.hoisted(() => ({ flagState: { isEnabled: true } }));
vi.mock('../../../config/customCompanies', () => ({
  CUSTOM_COMPANIES_CONFIG: {
    get isEnabled() {
      return flagState.isEnabled;
    },
    isDiscoveryProgressEnabled: false,
  },
}));

const { authState } = vi.hoisted(() => ({
  authState: { isAuthenticated: true, isLoading: false },
}));
vi.mock('../../../features/auth/useAuth', () => ({
  // `getTokenOrNull` imports this marker class from the same module, so the mock
  // has to export it too.
  NotAuthenticatedError: class NotAuthenticatedError extends Error {},
  useAuth: () => ({
    isEnabled: true,
    isAuthenticated: authState.isAuthenticated,
    isLoading: authState.isLoading,
    user: null,
    login: vi.fn(),
    logout: vi.fn(),
    getToken: vi.fn(),
  }),
}));

import { createTestStore } from '../../../test/testUtils';
import { useCompanyLoader } from '../../../hooks/useCompanyLoader';
import { useURLSync } from '../../../app/hooks';

// Node's `Request` (undici) requires absolute URLs; `fetchBaseQuery` builds
// relative ones from `baseUrl: '/api'`. Same shim the other API-slice tests use.
const OriginalRequest = globalThis.Request;
class TestRequest extends OriginalRequest {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    super(
      typeof input === 'string' && input.startsWith('/') ? `http://localhost${input}` : input,
      init
    );
  }
}
globalThis.Request = TestRequest as unknown as typeof Request;

const USER_COMPANIES_PATH = '/api/users/companies';

interface UserCompaniesGate {
  /** Resolve the pending `GET /api/users/companies` with these boards. */
  resolve: (ids: string[]) => void;
  /** Every path the app asked for, in order. */
  paths: string[];
}

function installFetch(): UserCompaniesGate {
  const paths: string[] = [];
  let release: ((ids: string[]) => void) | null = null;
  const pending = new Promise<string[]>((res) => {
    release = res;
  });

  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const href = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const path = href.replace('http://localhost', '').split('?')[0];
    paths.push(path);
    if (path === USER_COMPANIES_PATH) {
      const ids = await pending;
      return new Response(
        JSON.stringify({
          companies: ids.map((id) => ({
            id,
            displayName: id.toUpperCase(),
            ats: 'greenhouse',
            boardToken: id,
            sourceId: `custom:${id}`,
            healthState: 'healthy',
            openJobCount: 1,
            lastSuccessAt: null,
            trackingStartedAt: null,
          })),
        }),
        { status: 200, headers: { 'content-type': 'application/json' } }
      );
    }
    return new Response('[]', { status: 200, headers: { 'content-type': 'application/json' } });
  }) as unknown as typeof fetch;

  return { resolve: (ids) => release?.(ids), paths };
}

/** Mounts the same two hooks the real page mounts: selection + URL sync. */
function mountCompaniesPage(store: ReturnType<typeof createTestStore>) {
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <Provider store={store}>
      <BrowserRouter>{children}</BrowserRouter>
    </Provider>
  );
  return renderHook(
    () => {
      useURLSync();
      return useCompanyLoader();
    },
    { wrapper }
  );
}

const selected = (store: ReturnType<typeof createTestStore>) =>
  store.getState().app.selectedCompanyId;

beforeEach(() => {
  authState.isAuthenticated = true;
  authState.isLoading = false;
  flagState.isEnabled = true;
});

afterEach(() => {
  vi.restoreAllMocks();
  window.history.pushState({}, '', '/');
});

describe('T5 — a public deep link never waits on the authed query', () => {
  it('selects the company on the FIRST dispatch, with `getUserCompanies` still in flight', () => {
    const gate = installFetch(); // deliberately never resolved
    window.history.pushState({}, '', '/companies?company=figma');
    const store = createTestStore();

    mountCompaniesPage(store);

    // No `await`, no `waitFor`: if this needed another tick the assertion fails.
    expect(selected(store)).toBe('figma');
    expect(gate.paths).not.toContain(USER_COMPANIES_PATH);
  });

  it('does the same for a signed-out visitor', () => {
    authState.isAuthenticated = false;
    installFetch();
    window.history.pushState({}, '', '/companies?company=anthropic');
    const store = createTestStore();

    mountCompaniesPage(store);

    expect(selected(store)).toBe('anthropic');
  });

  it('still falls back to the default for an unknown public id', () => {
    installFetch();
    window.history.pushState({}, '', '/companies?company=does-not-exist');
    const store = createTestStore();

    mountCompaniesPage(store);

    expect(selected(store)).toBe('spacex');
  });
});

describe('T9 — a custom deep link waits, and its URL survives the wait', () => {
  it('holds the selection while the owned-company list is in flight', async () => {
    const gate = installFetch();
    window.history.pushState({}, '', '/companies?company=u-abc123');
    const store = createTestStore();

    mountCompaniesPage(store);

    // Held: still the store's default, and — the part that actually breaks the
    // deep link — the URL has NOT been rewritten to `?company=spacex`.
    expect(window.location.search).toBe('?company=u-abc123');

    gate.resolve(['u-abc123']);
    await waitFor(() => expect(selected(store)).toBe('u-abc123'));
    expect(window.location.search).toBe('?company=u-abc123');
  });

  it('falls back to the default once the list proves the id is not theirs', async () => {
    const gate = installFetch();
    window.history.pushState({}, '', '/companies?company=u-notmine');
    const store = createTestStore();

    mountCompaniesPage(store);
    gate.resolve(['u-abc123']);

    await waitFor(() => expect(selected(store)).toBe('spacex'));
  });

  it('does not wait — and issues no authed request — when signed out', () => {
    authState.isAuthenticated = false;
    const gate = installFetch();
    window.history.pushState({}, '', '/companies?company=u-abc123');
    const store = createTestStore();

    mountCompaniesPage(store);

    expect(selected(store)).toBe('spacex');
    expect(gate.paths).not.toContain(USER_COMPANIES_PATH);
  });

  it('does not wait — and issues no authed request — with the flag off', () => {
    flagState.isEnabled = false;
    const gate = installFetch();
    window.history.pushState({}, '', '/companies?company=u-abc123');
    const store = createTestStore();

    mountCompaniesPage(store);

    expect(selected(store)).toBe('spacex');
    expect(gate.paths).not.toContain(USER_COMPANIES_PATH);
  });

  it('reports the gate window as loading rather than an empty board', () => {
    installFetch();
    window.history.pushState({}, '', '/companies?company=u-abc123');
    const store = createTestStore();

    const { result } = mountCompaniesPage(store);

    expect(result.current.isLoading).toBe(true);
    expect(result.current.jobs).toEqual([]);
  });
});
