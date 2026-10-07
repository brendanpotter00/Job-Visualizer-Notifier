import { describe, it, expect, vi, beforeEach } from 'vitest';
import { StrictMode } from 'react';
import { renderHook, waitFor } from '@testing-library/react';

// Mock the two collaborators. The hook only reads `isAuthenticated` / `getToken`
// from useAuth and calls recordVisit — mock both so the test is isolated.
const recordVisitMock = vi.fn();
let authState: { isAuthenticated: boolean; getToken: () => Promise<string> };
const authConfig = vi.hoisted(() => ({ devAdminBypassEnabled: false }));

vi.mock('../../../config/auth', () => ({ AUTH_CONFIG: authConfig }));

vi.mock('../../../features/auth/useAuth', () => ({
  useAuth: () => authState,
}));
vi.mock('../../../features/auth/authService', () => ({
  recordVisit: (token: string | null) => recordVisitMock(token),
}));

import { useRecordVisit } from '../../../features/auth/useRecordVisit';

describe('useRecordVisit', () => {
  beforeEach(() => {
    authConfig.devAdminBypassEnabled = false;
    recordVisitMock.mockReset().mockResolvedValue(undefined);
    authState = {
      isAuthenticated: true,
      getToken: vi.fn().mockResolvedValue('tok'),
    };
  });

  it('records exactly one visit when authenticated', async () => {
    renderHook(() => useRecordVisit());
    await waitFor(() => expect(recordVisitMock).toHaveBeenCalledTimes(1));
    expect(recordVisitMock).toHaveBeenCalledWith('tok');
  });

  it('records the visit with no token under the local dev admin bypass', async () => {
    // The bypass getToken rejects by design; asking it would log an error on every load.
    authConfig.devAdminBypassEnabled = true;
    authState = {
      isAuthenticated: true,
      getToken: vi.fn().mockRejectedValue(new Error('no token')),
    };
    renderHook(() => useRecordVisit());
    await waitFor(() => expect(recordVisitMock).toHaveBeenCalledTimes(1));
    expect(recordVisitMock).toHaveBeenCalledWith(null);
    expect(authState.getToken).not.toHaveBeenCalled();
  });

  it('records nothing when unauthenticated (anonymous load)', async () => {
    authState = { isAuthenticated: false, getToken: vi.fn() };
    renderHook(() => useRecordVisit());
    await Promise.resolve();
    expect(recordVisitMock).not.toHaveBeenCalled();
    expect(authState.getToken).not.toHaveBeenCalled();
  });

  it('records only once across re-renders (one visit per page load, not per nav)', async () => {
    const { rerender } = renderHook(() => useRecordVisit());
    await waitFor(() => expect(recordVisitMock).toHaveBeenCalledTimes(1));
    rerender();
    rerender();
    await Promise.resolve();
    expect(recordVisitMock).toHaveBeenCalledTimes(1);
  });

  it('records only once under StrictMode double-invocation', async () => {
    renderHook(() => useRecordVisit(), { wrapper: StrictMode });
    await waitFor(() => expect(recordVisitMock).toHaveBeenCalledTimes(1));
    // Give any second StrictMode effect invocation a tick to (not) fire.
    await Promise.resolve();
    expect(recordVisitMock).toHaveBeenCalledTimes(1);
  });

  it('swallows a failed visit without throwing', async () => {
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    recordVisitMock.mockRejectedValue(new Error('network'));

    expect(() => renderHook(() => useRecordVisit())).not.toThrow();
    await waitFor(() => expect(errSpy).toHaveBeenCalled());

    errSpy.mockRestore();
  });
});
