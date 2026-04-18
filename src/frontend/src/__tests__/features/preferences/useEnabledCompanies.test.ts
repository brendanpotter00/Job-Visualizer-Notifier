import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import React from 'react';
import { Provider } from 'react-redux';
import { createTestStore } from '../../../test/testUtils';
import { useEnabledCompanies } from '../../../features/preferences/useEnabledCompanies';

const mockGetToken = vi.fn();
const mockAuthState = {
  isAuthenticated: false,
};

vi.mock('../../../features/auth/useAuth', () => ({
  useAuth: () => ({
    isEnabled: true,
    isAuthenticated: mockAuthState.isAuthenticated,
    isLoading: false,
    user: undefined,
    login: vi.fn(),
    logout: vi.fn(),
    getToken: mockGetToken,
  }),
}));

function makeWrapper(store: ReturnType<typeof createTestStore>) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(
      Provider,
      { store, children } as React.ComponentProps<typeof Provider>
    );
  };
}

describe('useEnabledCompanies', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockGetToken.mockReset();
    mockAuthState.isAuthenticated = false;
  });

  it('does not fetch when signed out and ids stays null', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    const store = createTestStore();
    const { result } = renderHook(() => useEnabledCompanies(), {
      wrapper: makeWrapper(store),
    });

    await waitFor(() => {
      expect(store.getState().enabledCompanies.loading).toBe(false);
    });

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(result.current.ids).toBeNull();
  });

  it('fetches on mount when authenticated and populates ids', async () => {
    mockAuthState.isAuthenticated = true;
    mockGetToken.mockResolvedValue('tok-1');
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ companyIds: ['a', 'b'] }), { status: 200 })
    );
    const store = createTestStore();

    const { result } = renderHook(() => useEnabledCompanies(), {
      wrapper: makeWrapper(store),
    });

    await waitFor(() => {
      expect(result.current.ids).toEqual(['a', 'b']);
    });

    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/users/enabled-companies',
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: 'Bearer tok-1',
        }),
      })
    );
  });

  it('aborts in-flight load when isAuthenticated flips to false', async () => {
    mockAuthState.isAuthenticated = true;
    mockGetToken.mockResolvedValue('tok-1');
    // Build a fetch that resolves slowly and rejects with AbortError when aborted.
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(
      (_input, init) =>
        new Promise((resolve, reject) => {
          const signal = (init as RequestInit | undefined)?.signal;
          if (signal) {
            signal.addEventListener('abort', () => {
              const err = new Error('aborted');
              err.name = 'AbortError';
              reject(err);
            });
          }
          setTimeout(
            () =>
              resolve(
                new Response(JSON.stringify({ companyIds: ['a', 'b'] }), {
                  status: 200,
                })
              ),
            100
          );
        })
    );
    const store = createTestStore();

    const { rerender } = renderHook(() => useEnabledCompanies(), {
      wrapper: makeWrapper(store),
    });

    // Let the dispatch kick off the fetch.
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalled();
    });

    // Flip auth off before the fetch resolves.
    mockAuthState.isAuthenticated = false;
    rerender();

    // After the abort, state should NOT be populated.
    await waitFor(() => {
      expect(store.getState().enabledCompanies.loading).toBe(false);
    });

    // Give the aborted fetch a chance to fire its rejection.
    await new Promise((r) => setTimeout(r, 150));

    expect(store.getState().enabledCompanies.ids).toBeNull();
    expect(store.getState().enabledCompanies.error).toBeNull();
  });

  it('save resolves and commits server echo into ids', async () => {
    mockAuthState.isAuthenticated = true;
    mockGetToken.mockResolvedValue('tok-save');
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ companyIds: [] }), { status: 200 })
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ companyIds: ['a', 'b'] }), { status: 200 })
      );
    const store = createTestStore();

    const { result } = renderHook(() => useEnabledCompanies(), {
      wrapper: makeWrapper(store),
    });

    await waitFor(() => {
      expect(result.current.ids).toEqual([]);
    });

    await act(async () => {
      await result.current.save(['b', 'a']);
    });

    expect(store.getState().enabledCompanies.ids).toEqual(['a', 'b']);
  });

  it('save rejection surfaces via unwrap so callers can catch', async () => {
    mockAuthState.isAuthenticated = true;
    mockGetToken.mockResolvedValue('tok');
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ companyIds: [] }), { status: 200 })
      )
      .mockResolvedValueOnce(new Response('server error', { status: 500 }));
    const store = createTestStore();

    const { result } = renderHook(() => useEnabledCompanies(), {
      wrapper: makeWrapper(store),
    });

    await waitFor(() => {
      expect(result.current.ids).toEqual([]);
    });

    let caught: Error | null = null;
    await act(async () => {
      try {
        await result.current.save(['a']);
      } catch (err) {
        caught = err as Error;
      }
    });

    expect(caught).not.toBeNull();
    expect((caught as unknown as Error).message).toMatch(
      /Failed to save enabled companies/
    );
    await waitFor(() => {
      expect(store.getState().enabledCompanies.error).toMatch(/500/);
    });
  });

  it('reload dispatches a fresh fetch while signed in', async () => {
    mockAuthState.isAuthenticated = true;
    mockGetToken.mockResolvedValue('tok');
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ companyIds: ['a'] }), { status: 200 })
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ companyIds: ['a', 'b'] }), { status: 200 })
      );
    const store = createTestStore();

    const { result } = renderHook(() => useEnabledCompanies(), {
      wrapper: makeWrapper(store),
    });

    await waitFor(() => {
      expect(result.current.ids).toEqual(['a']);
    });

    await act(async () => {
      result.current.reload();
    });

    await waitFor(() => {
      expect(result.current.ids).toEqual(['a', 'b']);
    });

    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });
});
