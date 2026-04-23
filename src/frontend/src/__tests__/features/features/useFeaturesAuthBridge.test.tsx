import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { getTokenOrNull } from '../../../features/features/getTokenOrNull';
import { useFeaturesAuthBridge } from '../../../features/features/useFeaturesAuthBridge';
import { NotAuthenticatedError } from '../../../features/auth/useAuth';
import { logger } from '../../../lib/logger';

const mockGetToken = vi.fn<() => Promise<string>>();

vi.mock('../../../features/auth/useAuth', async () => {
  // Preserve the real `NotAuthenticatedError` class so consumers of this test
  // module + the source under test share the same `instanceof`-compatible
  // marker. Only `useAuth` itself is replaced with a stub.
  const actual =
    await vi.importActual<typeof import('../../../features/auth/useAuth')>(
      '../../../features/auth/useAuth'
    );
  return {
    ...actual,
    useAuth: () => ({
      isEnabled: true,
      isAuthenticated: true,
      isLoading: false,
      user: undefined,
      login: vi.fn(),
      logout: vi.fn(),
      getToken: mockGetToken,
    }),
  };
});

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
    mockGetToken.mockRejectedValue(new NotAuthenticatedError());
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

  it('emits logger.debug on register (mount) and unregister (unmount)', async () => {
    mockGetToken.mockResolvedValue('tok-bridge');
    const debugSpy = vi.spyOn(logger, 'debug').mockImplementation(() => {});
    try {
      const { unmount } = renderHook(() => useFeaturesAuthBridge());

      await waitFor(() => {
        expect(debugSpy).toHaveBeenCalledWith(
          '[useFeaturesAuthBridge] registered getToken'
        );
      });

      unmount();

      expect(debugSpy).toHaveBeenCalledWith(
        '[useFeaturesAuthBridge] unregistered getToken'
      );
    } finally {
      debugSpy.mockRestore();
    }
  });
});
