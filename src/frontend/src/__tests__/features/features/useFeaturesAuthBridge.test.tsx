import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { getTokenOrNull } from '../../../features/features/getTokenOrNull';
import { useFeaturesAuthBridge } from '../../../features/features/useFeaturesAuthBridge';

const mockGetToken = vi.fn<() => Promise<string>>();

vi.mock('../../../features/auth/useAuth', () => ({
  useAuth: () => ({
    isEnabled: true,
    isAuthenticated: true,
    isLoading: false,
    user: undefined,
    login: vi.fn(),
    logout: vi.fn(),
    getToken: mockGetToken,
  }),
}));

describe('useFeaturesAuthBridge', () => {
  beforeEach(() => {
    mockGetToken.mockReset();
  });

  it('after mount, getTokenOrNull() returns what useAuth().getToken() resolves to', async () => {
    mockGetToken.mockResolvedValue('tok-bridge');
    renderHook(() => useFeaturesAuthBridge());

    await waitFor(async () => {
      await expect(getTokenOrNull()).resolves.toBe('tok-bridge');
    });
  });

  it('resolves to null (no uncaught error) when useAuth().getToken() rejects', async () => {
    mockGetToken.mockRejectedValue(new Error('Not authenticated'));
    renderHook(() => useFeaturesAuthBridge());

    await waitFor(async () => {
      await expect(getTokenOrNull()).resolves.toBeNull();
    });
  });

  it('unregisters on unmount so the holder is null after teardown', async () => {
    mockGetToken.mockResolvedValue('tok-bridge');
    const { unmount } = renderHook(() => useFeaturesAuthBridge());

    await waitFor(async () => {
      await expect(getTokenOrNull()).resolves.toBe('tok-bridge');
    });

    unmount();

    await expect(getTokenOrNull()).resolves.toBeNull();
  });
});
