import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { configureStore } from '@reduxjs/toolkit';
import enabledCompaniesReducer, {
  loadEnabledCompanies,
  saveEnabledCompanies,
  resetEnabledCompanies,
  enabledCompaniesLoadFailed,
  selectEnabledCompanyIds,
  selectAutoEnroll,
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
    it('has null ids/autoEnroll, not loading, no error, no active request id', () => {
      const store = makeStore();
      expect(store.getState().enabledCompanies).toEqual({
        ids: null,
        autoEnroll: null,
        loading: false,
        error: null,
        activeLoadRequestId: null,
      });
    });
  });

  describe('loadEnabledCompanies', () => {
    it('pending sets loading true, clears error, and tracks requestId', () => {
      const store = makeStore();
      store.dispatch({
        type: loadEnabledCompanies.pending.type,
        meta: { requestId: 'req-1' },
      });
      expect(store.getState().enabledCompanies.loading).toBe(true);
      expect(store.getState().enabledCompanies.error).toBeNull();
      expect(store.getState().enabledCompanies.activeLoadRequestId).toBe('req-1');
    });

    it('fulfilled sets ids + autoEnroll and clears loading', () => {
      const store = makeStore();
      store.dispatch({
        type: loadEnabledCompanies.pending.type,
        meta: { requestId: 'req-1' },
      });
      store.dispatch({
        type: loadEnabledCompanies.fulfilled.type,
        payload: { companyIds: ['a', 'b'], autoEnroll: false },
        meta: { requestId: 'req-1' },
      });
      expect(store.getState().enabledCompanies).toEqual({
        ids: ['a', 'b'],
        autoEnroll: false,
        loading: false,
        error: null,
        activeLoadRequestId: null,
      });
    });

    it('rejected sets error, clears loading, leaves ids null', () => {
      const store = makeStore();
      store.dispatch({
        type: loadEnabledCompanies.pending.type,
        meta: { requestId: 'req-1' },
      });
      store.dispatch({
        type: loadEnabledCompanies.rejected.type,
        error: { message: 'boom' },
        meta: { requestId: 'req-1', aborted: false },
      });
      expect(store.getState().enabledCompanies).toEqual({
        ids: null,
        autoEnroll: null,
        loading: false,
        error: 'boom',
        activeLoadRequestId: null,
      });
    });

    it('rejected with aborted meta clears loading without writing an error', () => {
      const store = makeStore();
      store.dispatch({
        type: loadEnabledCompanies.pending.type,
        meta: { requestId: 'req-1' },
      });
      expect(store.getState().enabledCompanies.loading).toBe(true);
      store.dispatch({
        type: loadEnabledCompanies.rejected.type,
        error: { message: 'aborted' },
        meta: { requestId: 'req-1', aborted: true },
      });
      const after = store.getState().enabledCompanies;
      expect(after.loading).toBe(false);
      expect(after.error).toBeNull();
      expect(after.ids).toBeNull();
    });

    it('rejected with AbortError name clears loading without writing an error', () => {
      const store = makeStore();
      store.dispatch({
        type: loadEnabledCompanies.pending.type,
        meta: { requestId: 'req-1' },
      });
      expect(store.getState().enabledCompanies.loading).toBe(true);
      store.dispatch({
        type: loadEnabledCompanies.rejected.type,
        error: { name: 'AbortError', message: 'aborted' },
        meta: { requestId: 'req-1', aborted: false },
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
        meta: { requestId: 'req-1', aborted: false },
      });
      expect(store.getState().enabledCompanies.error).toBe(
        'Failed to load enabled companies'
      );
    });

    it('fulfilled with stale requestId does NOT overwrite saved ids', () => {
      // Simulates a load started before a save — the save invalidates
      // activeLoadRequestId, so the racing load.fulfilled must skip writing.
      const store = makeStore();
      store.dispatch({
        type: loadEnabledCompanies.pending.type,
        meta: { requestId: 'req-stale' },
      });
      // A save happens while the load is pending.
      store.dispatch({
        type: saveEnabledCompanies.pending.type,
        meta: { requestId: 'save-1' },
      });
      store.dispatch({
        type: saveEnabledCompanies.fulfilled.type,
        payload: { companyIds: ['saved-a', 'saved-b'], autoEnroll: true },
        meta: { requestId: 'save-1' },
      });
      // Now the stale load finally resolves.
      store.dispatch({
        type: loadEnabledCompanies.fulfilled.type,
        payload: { companyIds: ['stale-x', 'stale-y'], autoEnroll: false },
        meta: { requestId: 'req-stale' },
      });
      // Saved ids must win.
      expect(store.getState().enabledCompanies.ids).toEqual([
        'saved-a',
        'saved-b',
      ]);
      expect(store.getState().enabledCompanies.autoEnroll).toBe(true);
    });
  });

  describe('saveEnabledCompanies', () => {
    it('pending clears activeLoadRequestId so in-flight loads become stale', () => {
      const store = makeStore();
      store.dispatch({
        type: loadEnabledCompanies.pending.type,
        meta: { requestId: 'req-load' },
      });
      expect(store.getState().enabledCompanies.activeLoadRequestId).toBe(
        'req-load'
      );
      store.dispatch({
        type: saveEnabledCompanies.pending.type,
        meta: { requestId: 'req-save' },
      });
      expect(store.getState().enabledCompanies.activeLoadRequestId).toBeNull();
    });

    it('fulfilled updates ids + autoEnroll and clears error', () => {
      const store = makeStore();
      store.dispatch({
        type: saveEnabledCompanies.fulfilled.type,
        payload: { companyIds: ['a', 'b'], autoEnroll: false },
      });
      expect(store.getState().enabledCompanies.ids).toEqual(['a', 'b']);
      expect(store.getState().enabledCompanies.autoEnroll).toBe(false);
      expect(store.getState().enabledCompanies.error).toBeNull();
    });

    it('rejected sets error, leaves ids unchanged', () => {
      const store = makeStore();
      store.dispatch({
        type: loadEnabledCompanies.pending.type,
        meta: { requestId: 'req-1' },
      });
      store.dispatch({
        type: loadEnabledCompanies.fulfilled.type,
        payload: { companyIds: ['a'], autoEnroll: true },
        meta: { requestId: 'req-1' },
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
        type: loadEnabledCompanies.pending.type,
        meta: { requestId: 'req-1' },
      });
      store.dispatch({
        type: loadEnabledCompanies.fulfilled.type,
        payload: { companyIds: ['a'], autoEnroll: true },
        meta: { requestId: 'req-1' },
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

  describe('enabledCompaniesLoadFailed (synthetic)', () => {
    it('sets error and clears loading/activeLoadRequestId', () => {
      const store = makeStore();
      store.dispatch({
        type: loadEnabledCompanies.pending.type,
        meta: { requestId: 'req-1' },
      });
      store.dispatch(enabledCompaniesLoadFailed('token expired'));
      expect(store.getState().enabledCompanies).toEqual({
        ids: null,
        autoEnroll: null,
        loading: false,
        error: 'token expired',
        activeLoadRequestId: null,
      });
    });
  });

  describe('resetEnabledCompanies', () => {
    it('returns state to initial', () => {
      const store = makeStore();
      store.dispatch({
        type: loadEnabledCompanies.pending.type,
        meta: { requestId: 'req-1' },
      });
      store.dispatch({
        type: loadEnabledCompanies.fulfilled.type,
        payload: { companyIds: ['a', 'b'], autoEnroll: false },
        meta: { requestId: 'req-1' },
      });
      store.dispatch({
        type: loadEnabledCompanies.rejected.type,
        error: { message: 'fail' },
        meta: { requestId: 'req-1', aborted: false },
      });
      store.dispatch(resetEnabledCompanies());
      expect(store.getState().enabledCompanies).toEqual({
        ids: null,
        autoEnroll: null,
        loading: false,
        error: null,
        activeLoadRequestId: null,
      });
    });
  });

  describe('selectEnabledCompanyIds', () => {
    it('returns the ids field from state', () => {
      expect(
        selectEnabledCompanyIds({
          enabledCompanies: {
            ids: ['a'],
            autoEnroll: true,
            loading: false,
            error: null,
            activeLoadRequestId: null,
          },
        })
      ).toEqual(['a']);
      expect(
        selectEnabledCompanyIds({
          enabledCompanies: {
            ids: null,
            autoEnroll: null,
            loading: false,
            error: null,
            activeLoadRequestId: null,
          },
        })
      ).toBeNull();
      expect(
        selectEnabledCompanyIds({
          enabledCompanies: {
            ids: [],
            autoEnroll: true,
            loading: false,
            error: null,
            activeLoadRequestId: null,
          },
        })
      ).toEqual([]);
    });
  });

  describe('selectAutoEnroll', () => {
    it('returns the autoEnroll field from state', () => {
      expect(
        selectAutoEnroll({
          enabledCompanies: {
            ids: ['a'],
            autoEnroll: false,
            loading: false,
            error: null,
            activeLoadRequestId: null,
          },
        })
      ).toBe(false);
      expect(
        selectAutoEnroll({
          enabledCompanies: {
            ids: null,
            autoEnroll: null,
            loading: false,
            error: null,
            activeLoadRequestId: null,
          },
        })
      ).toBeNull();
    });
  });

  describe('integration with fetch', () => {
    it('load dispatch flows through to fulfilled', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response(
          JSON.stringify({ companyIds: ['x', 'y'], autoEnrollNewCompanies: false }),
          { status: 200 }
        )
      );
      const store = makeStore();
      await store.dispatch(loadEnabledCompanies('tok'));
      expect(store.getState().enabledCompanies.ids).toEqual(['x', 'y']);
      expect(store.getState().enabledCompanies.autoEnroll).toBe(false);
      expect(store.getState().enabledCompanies.loading).toBe(false);
    });

    it('load defaults autoEnroll to true when the field is omitted', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response(JSON.stringify({ companyIds: ['x'] }), { status: 200 })
      );
      const store = makeStore();
      await store.dispatch(loadEnabledCompanies('tok'));
      expect(store.getState().enabledCompanies.autoEnroll).toBe(true);
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

    it('save dispatch round-trips server echo into ids + autoEnroll', async () => {
      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response(
          JSON.stringify({ companyIds: ['a', 'b'], autoEnrollNewCompanies: false }),
          { status: 200 }
        )
      );
      const store = makeStore();
      await store.dispatch(
        saveEnabledCompanies({ token: 'tok', companyIds: ['b', 'a'], autoEnroll: false })
      );
      expect(store.getState().enabledCompanies.ids).toEqual(['a', 'b']);
      expect(store.getState().enabledCompanies.autoEnroll).toBe(false);
      // The toggle is sent to the backend under its camelCase alias.
      const body = JSON.parse(
        (fetchSpy.mock.calls[0][1] as RequestInit).body as string
      );
      expect(body.autoEnrollNewCompanies).toBe(false);
    });
  });
});
