import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { configureStore } from '@reduxjs/toolkit';
import enabledCompaniesReducer, {
  loadEnabledCompanies,
  saveEnabledCompanies,
  resetEnabledCompanies,
  selectEnabledCompanyIds,
} from '../../../features/preferences/enabledCompaniesSlice';

function makeStore() {
  return configureStore({
    reducer: { enabledCompanies: enabledCompaniesReducer },
  });
}

describe('enabledCompaniesSlice', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('initial state', () => {
    it('has null ids, not loading, no error', () => {
      const store = makeStore();
      expect(store.getState().enabledCompanies).toEqual({
        ids: null,
        loading: false,
        error: null,
      });
    });
  });

  describe('loadEnabledCompanies', () => {
    it('pending sets loading true and clears error', () => {
      const store = makeStore();
      store.dispatch({ type: loadEnabledCompanies.pending.type });
      expect(store.getState().enabledCompanies.loading).toBe(true);
      expect(store.getState().enabledCompanies.error).toBeNull();
    });

    it('fulfilled sets ids and clears loading', () => {
      const store = makeStore();
      store.dispatch({ type: loadEnabledCompanies.pending.type });
      store.dispatch({
        type: loadEnabledCompanies.fulfilled.type,
        payload: ['a', 'b'],
      });
      expect(store.getState().enabledCompanies).toEqual({
        ids: ['a', 'b'],
        loading: false,
        error: null,
      });
    });

    it('rejected sets error, clears loading, leaves ids null', () => {
      const store = makeStore();
      store.dispatch({ type: loadEnabledCompanies.pending.type });
      store.dispatch({
        type: loadEnabledCompanies.rejected.type,
        error: { message: 'boom' },
        meta: { aborted: false },
      });
      expect(store.getState().enabledCompanies).toEqual({
        ids: null,
        loading: false,
        error: 'boom',
      });
    });

    it('rejected with aborted meta clears loading without writing an error', () => {
      const store = makeStore();
      store.dispatch({ type: loadEnabledCompanies.pending.type });
      expect(store.getState().enabledCompanies.loading).toBe(true);
      store.dispatch({
        type: loadEnabledCompanies.rejected.type,
        error: { message: 'aborted' },
        meta: { aborted: true },
      });
      const after = store.getState().enabledCompanies;
      expect(after.loading).toBe(false);
      expect(after.error).toBeNull();
      expect(after.ids).toBeNull();
    });

    it('rejected with AbortError name clears loading without writing an error', () => {
      const store = makeStore();
      store.dispatch({ type: loadEnabledCompanies.pending.type });
      expect(store.getState().enabledCompanies.loading).toBe(true);
      store.dispatch({
        type: loadEnabledCompanies.rejected.type,
        error: { name: 'AbortError', message: 'aborted' },
        meta: { aborted: false },
      });
      const after = store.getState().enabledCompanies;
      expect(after.loading).toBe(false);
      expect(after.error).toBeNull();
      expect(after.ids).toBeNull();
    });

    it('uses default message when error.message is missing', () => {
      const store = makeStore();
      store.dispatch({
        type: loadEnabledCompanies.rejected.type,
        error: {},
        meta: { aborted: false },
      });
      expect(store.getState().enabledCompanies.error).toBe(
        'Failed to load enabled companies'
      );
    });
  });

  describe('saveEnabledCompanies', () => {
    it('fulfilled updates ids and clears error', () => {
      const store = makeStore();
      store.dispatch({
        type: saveEnabledCompanies.fulfilled.type,
        payload: ['a', 'b'],
      });
      expect(store.getState().enabledCompanies.ids).toEqual(['a', 'b']);
      expect(store.getState().enabledCompanies.error).toBeNull();
    });

    it('rejected sets error, leaves ids unchanged', () => {
      const store = makeStore();
      store.dispatch({
        type: loadEnabledCompanies.fulfilled.type,
        payload: ['a'],
      });
      store.dispatch({
        type: saveEnabledCompanies.rejected.type,
        error: { message: 'save failed' },
        meta: { aborted: false },
      });
      expect(store.getState().enabledCompanies.ids).toEqual(['a']);
      expect(store.getState().enabledCompanies.error).toBe('save failed');
    });

    it('rejected with aborted meta is ignored', () => {
      const store = makeStore();
      store.dispatch({
        type: loadEnabledCompanies.fulfilled.type,
        payload: ['a'],
      });
      const before = store.getState().enabledCompanies;
      store.dispatch({
        type: saveEnabledCompanies.rejected.type,
        error: { message: 'aborted' },
        meta: { aborted: true },
      });
      expect(store.getState().enabledCompanies).toEqual(before);
    });
  });

  describe('resetEnabledCompanies', () => {
    it('returns state to initial', () => {
      const store = makeStore();
      store.dispatch({
        type: loadEnabledCompanies.fulfilled.type,
        payload: ['a', 'b'],
      });
      store.dispatch({
        type: loadEnabledCompanies.rejected.type,
        error: { message: 'fail' },
        meta: { aborted: false },
      });
      store.dispatch(resetEnabledCompanies());
      expect(store.getState().enabledCompanies).toEqual({
        ids: null,
        loading: false,
        error: null,
      });
    });
  });

  describe('selectEnabledCompanyIds', () => {
    it('returns the ids field from state', () => {
      expect(
        selectEnabledCompanyIds({
          enabledCompanies: { ids: ['a'], loading: false, error: null },
        })
      ).toEqual(['a']);
      expect(
        selectEnabledCompanyIds({
          enabledCompanies: { ids: null, loading: false, error: null },
        })
      ).toBeNull();
      expect(
        selectEnabledCompanyIds({
          enabledCompanies: { ids: [], loading: false, error: null },
        })
      ).toEqual([]);
    });
  });

  describe('integration with fetch', () => {
    it('load dispatch flows through to fulfilled', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response(JSON.stringify({ companyIds: ['x', 'y'] }), { status: 200 })
      );
      const store = makeStore();
      await store.dispatch(loadEnabledCompanies('tok'));
      expect(store.getState().enabledCompanies.ids).toEqual(['x', 'y']);
      expect(store.getState().enabledCompanies.loading).toBe(false);
    });

    it('load dispatch flows through to rejected on 500', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response('nope', { status: 500 })
      );
      const store = makeStore();
      await store.dispatch(loadEnabledCompanies('tok'));
      expect(store.getState().enabledCompanies.ids).toBeNull();
      expect(store.getState().enabledCompanies.error).toContain('500');
      expect(store.getState().enabledCompanies.loading).toBe(false);
    });

    it('save dispatch round-trips server echo into ids', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response(JSON.stringify({ companyIds: ['a', 'b'] }), { status: 200 })
      );
      const store = makeStore();
      await store.dispatch(
        saveEnabledCompanies({ token: 'tok', companyIds: ['b', 'a'] })
      );
      expect(store.getState().enabledCompanies.ids).toEqual(['a', 'b']);
    });
  });
});
