import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, render } from '@testing-library/react';
import { Provider } from 'react-redux';
import { BrowserRouter } from 'react-router-dom';

import { createTestStore } from '../../../test/testUtils';
import { useRecentJobsUrlSync } from '../../../features/filters/useRecentJobsUrlSync';
import {
  hydrateRecentJobsFilters,
  setRecentJobsTimeWindow,
} from '../../../features/filters/slices/recentJobsFiltersSlice';

/**
 * The Recent page's filters <-> browser URL binding.
 *
 * The behaviour that matters here is PRECEDENCE, agreed with the repo owner: a
 * shared link wins for that visit, and the reader's own saved filters are
 * neither read into the page nor written to. That is implemented by hydrating
 * from the URL before the saved-filters round trip resolves and letting the
 * slice's existing one-shot `hydrated` guard do the rest — so the test that
 * earns its place is the one proving a later saved-filters hydration is a no-op.
 * The version of that proof with BOTH hooks actually mounted lives in
 * `recentJobsUrlPrecedence.test.tsx`; this file drives the hook alone.
 *
 * `BrowserRouter`, not `MemoryRouter`, on purpose: the hook route-scopes itself
 * off `useLocation().pathname` but reads the query string off `window.location`,
 * and only a BrowserRouter keeps those two the same object. Under a MemoryRouter
 * the two would disagree and every assertion here would be about a URL the hook
 * never saw.
 */

function mountWith(search: string, pathname = '/') {
  // Navigate BEFORE the spy starts counting — this setup call is not the hook's
  // behaviour, and counting it made the "does not write before hydration" test
  // pass for the wrong reason.
  window.history.replaceState({}, '', `${pathname}${search}`);
  replaceSpy.mockClear();
  const store = createTestStore();
  function Probe() {
    useRecentJobsUrlSync();
    return null;
  }
  render(
    <Provider store={store}>
      <BrowserRouter>
        <Probe />
      </BrowserRouter>
    </Provider>
  );
  return store;
}

let replaceSpy: ReturnType<typeof vi.spyOn>;

/**
 * The `replaceState` calls that actually rewrote the URL.
 *
 * `BrowserRouter` calls `replaceState(state, '')` once on mount to attach its own
 * history key — two arguments, no URL. Counting that as a write made "did not
 * touch the address bar" assertions fail for a reason that has nothing to do with
 * this hook, so the third argument is the discriminator.
 */
const urlWrites = () =>
  (replaceSpy.mock.calls as unknown[][]).filter((call) => call[2] !== undefined);

beforeEach(() => {
  replaceSpy = vi.spyOn(window.history, 'replaceState');
});

afterEach(() => {
  replaceSpy.mockRestore();
  window.history.replaceState({}, '', '/');
});

describe('useRecentJobsUrlSync — reading a shared link', () => {
  it('hydrates the slice from the URL and marks it hydrated', () => {
    const store = mountWith('?time=24h&level=entry');
    const state = store.getState().recentJobsFilters;
    expect(state.filters.timeWindow).toBe('24h');
    expect(state.filters.level).toEqual(['entry']);
    expect(state.hydrated).toBe(true);
  });

  it('leaves the slice alone on an ordinary visit', () => {
    const store = mountWith('');
    // `hydrated` must stay false so useHydrateSavedFilters still gets its turn —
    // this is what keeps a normal visit showing the reader's saved filters.
    expect(store.getState().recentJobsFilters.hydrated).toBe(false);
  });

  it('makes a later saved-filters hydration a no-op', () => {
    // THE precedence test. The saved-filters request resolves after mount, and
    // its dispatch must not overwrite what the shared link asked for.
    const store = mountWith('?time=24h');
    expect(store.getState().recentJobsFilters.filters.timeWindow).toBe('24h');

    act(() => {
      store.dispatch(
        hydrateRecentJobsFilters({ timeWindow: '90d', level: ['senior'] })
      );
    });

    const filters = store.getState().recentJobsFilters.filters;
    expect(filters.timeWindow).toBe('24h');
    expect(filters.level).toBeUndefined();
  });

  it('does not read filter params off another page URL', () => {
    // `?time=…` on /companies is not a Recent-page shared link. Hydrating from
    // it would flip the one-shot `hydrated` guard and lock the reader out of
    // their own saved filters for the whole visit.
    const store = mountWith('?time=24h', '/companies');
    expect(store.getState().recentJobsFilters.hydrated).toBe(false);
    expect(store.getState().recentJobsFilters.filters.timeWindow).toBe('all');
  });
});

describe('useRecentJobsUrlSync — writing the address bar', () => {
  it('never stamps the slice defaults over a shared link', () => {
    // The window this guards is one COMMIT wide, not one request: the read
    // effect dispatches, but the write effect in that same commit still closes
    // over the PRE-hydration filters. Writing there would rebuild the query
    // string from the defaults and delete the params of the very link the reader
    // followed.
    mountWith('?time=24h&level=entry');
    expect(urlWrites()).toHaveLength(0);
    expect(window.location.search).toBe('?time=24h&level=entry');
  });

  it('mirrors a filter change into the URL', () => {
    const store = mountWith('?time=24h');

    act(() => {
      store.dispatch(setRecentJobsTimeWindow('7d'));
    });

    expect(replaceSpy).toHaveBeenCalled();
    const url = String(replaceSpy.mock.calls.at(-1)?.[2]);
    expect(url).toContain('time=7d');
    expect(url).not.toContain('time=24h');
  });

  it('writes for a reader who arrived with NO params and never hydrates', () => {
    // The signed-out case, and the audience the whole feature exists for: you
    // share a link WITH people who do not have an account. Gating the write on
    // the slice's `hydrated` flag made this silently inert — that flag's only
    // producers are a URL that carried params and a saved-filters pair that both
    // returned 200 for a signed-in reader. A signed-in reader whose saved-filters
    // query FAILS is the same dead state.
    const store = mountWith('');
    expect(store.getState().recentJobsFilters.hydrated).toBe(false);

    act(() => {
      store.dispatch(setRecentJobsTimeWindow('7d'));
    });

    expect(store.getState().recentJobsFilters.hydrated).toBe(false);
    expect(window.location.search).toBe('?time=7d');
  });

  it('leaves every other route alone', () => {
    // Mounted at the app root so it can beat the saved-filters hydration, which
    // means without the route scope its write lands on /companies, /account,
    // /saved-filters and the admin pages — so any link a signed-in reader copies
    // from any page carries their private filter set, and the recipient's Recent
    // page ADOPTS it. The same rule `useURLSync` applies to `?company=`.
    const store = mountWith('', '/saved-filters');

    act(() => {
      store.dispatch(setRecentJobsTimeWindow('7d'));
    });

    expect(urlWrites()).toHaveLength(0);
    expect(window.location.search).toBe('');
  });

  it('clears its params when the filters go back to the defaults', () => {
    // The mechanism behind the logout cleanup: `resetRecentJobsFilters` changes
    // `filters`, the write effect rebuilds from a default set, and
    // `buildSearchFromFilters` emits nothing for one. See
    // `recentJobsUrlPrecedence.test.tsx` for the real sign-out path.
    const store = mountWith('?time=24h');
    act(() => {
      store.dispatch(setRecentJobsTimeWindow('all'));
    });
    expect(window.location.search).toBe('');
  });

  it('uses replaceState, never pushState', () => {
    // A filter tweak is not a navigation. With pushState, Back would step
    // through every intermediate filter state — and the 300ms debounce means
    // there are more of those than the reader actually made — instead of
    // leaving the page.
    const pushSpy = vi.spyOn(window.history, 'pushState');
    const store = mountWith('?time=24h');
    act(() => {
      store.dispatch(setRecentJobsTimeWindow('7d'));
    });
    expect(pushSpy).not.toHaveBeenCalled();
    pushSpy.mockRestore();
  });
});
