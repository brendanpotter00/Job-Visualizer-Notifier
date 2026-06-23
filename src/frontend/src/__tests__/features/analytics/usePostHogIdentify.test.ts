import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import type { User } from '../../../features/auth/authService';

const mockIdentify = vi.fn();
const mockReset = vi.fn();

vi.mock('@posthog/react', () => ({
  usePostHog: () => ({ identify: mockIdentify, reset: mockReset }),
}));

vi.mock('../../../config/posthog', () => ({
  POSTHOG_CONFIG: { isEnabled: true },
}));

const mockUser: User = {
  id: 'user-123',
  providerSubject: 'auth0|abc',
  email: 'test@example.com',
  displayName: 'Test User',
  givenName: 'Test',
  familyName: 'User',
  pictureUrl: null,
  createdAt: '2024-01-01',
  updatedAt: '2024-01-01',
  isAdmin: false,
};

let mockCurrentUser: { user: User | null; loading: boolean; error: null } = {
  user: null,
  loading: false,
  error: null,
};

vi.mock('../../../features/auth/useCurrentUser', () => ({
  useCurrentUser: () => mockCurrentUser,
}));

import { usePostHogIdentify } from '../../../features/analytics/usePostHogIdentify';

describe('usePostHogIdentify', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCurrentUser = { user: null, loading: false, error: null };
  });

  it('identifies user with id, email, and isAdmin when user is present', () => {
    mockCurrentUser = { user: mockUser, loading: false, error: null };
    renderHook(() => usePostHogIdentify());
    expect(mockIdentify).toHaveBeenCalledWith('user-123', {
      email: 'test@example.com',
      name: 'Test User',
      isAdmin: false,
    });
  });

  it('calls reset when there is no user', () => {
    renderHook(() => usePostHogIdentify());
    expect(mockReset).toHaveBeenCalled();
    expect(mockIdentify).not.toHaveBeenCalled();
  });

  it('re-identifies when user changes', () => {
    const { rerender } = renderHook(() => usePostHogIdentify());
    expect(mockReset).toHaveBeenCalledTimes(1);

    mockCurrentUser = { user: mockUser, loading: false, error: null };
    rerender();
    expect(mockIdentify).toHaveBeenCalledWith('user-123', expect.any(Object));
  });

  it('resets when user signs out', () => {
    mockCurrentUser = { user: mockUser, loading: false, error: null };
    const { rerender } = renderHook(() => usePostHogIdentify());
    expect(mockIdentify).toHaveBeenCalledTimes(1);

    mockCurrentUser = { user: null, loading: false, error: null };
    rerender();
    expect(mockReset).toHaveBeenCalled();
  });
});
