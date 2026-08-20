import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, render } from '@testing-library/react';
import { Provider } from 'react-redux';

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
 */

function mountWith(search: string) {
  // Navigate BEFORE the spy starts counting — this setup call is not the hook's
  // behaviour, and counting it made the "does not write before hydration" test
  // pass for the wrong reason.
  window.history.replaceState({}, '', `/${search}`);
  replaceSpy.mockClear();
  const store = createTestStore();
  function Probe() {
    useRecentJobsUrlSync();
    return null;
  }
  render(
    <Provider store={store}>
      <Probe />
    </Provider>
  );
  return store;
}

let replaceSpy: ReturnType<typeof vi.spyOn>;

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
});

describe('useRecentJobsUrlSync — writing the address bar', () => {
  it('does not write before hydration', () => {
    // Writing here would stamp the slice's DEFAULTS over the params of the very
    // link the reader followed, in the window between mount and hydration.
    mountWith('');
    expect(replaceSpy).not.toHaveBeenCalled();
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
