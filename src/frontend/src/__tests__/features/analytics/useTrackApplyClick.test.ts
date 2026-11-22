import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import type { Job } from '../../../types';

const recordApplyClickMock = vi.fn();
const getSessionIdMock = vi.fn<() => string | undefined>();
let authState: { isAuthenticated: boolean; getToken: () => Promise<string> };

vi.mock('../../../features/auth/useAuth', () => ({
  useAuth: () => authState,
}));
vi.mock('../../../features/auth/authService', () => ({
  recordApplyClick: (token: string, payload: unknown) => recordApplyClickMock(token, payload),
}));
vi.mock('../../../features/analytics/events', () => ({
  getPostHogSessionId: () => getSessionIdMock(),
}));

import { useTrackApplyClick } from '../../../features/analytics/useTrackApplyClick';

const job: Job = {
  id: '42',
  source: 'backend-scraper',
  sourceId: 'greenhouse_api',
  company: 'spacex',
  title: 'Engineer',
  createdAt: '2026-11-01T00:00:00Z',
  firstSeenAt: '2026-11-01T00:00:00Z',
  url: 'https://example.com/42',
  raw: {},
};

describe('useTrackApplyClick', () => {
  beforeEach(() => {
    recordApplyClickMock.mockReset().mockResolvedValue(undefined);
    getSessionIdMock.mockReset().mockReturnValue('sess-1');
    authState = { isAuthenticated: true, getToken: vi.fn().mockResolvedValue('tok') };
  });

  it('logs the click with the job key, surface and session when signed in', async () => {
    const { result } = renderHook(() => useTrackApplyClick(job, 'recent'));
    result.current();
    await waitFor(() => expect(recordApplyClickMock).toHaveBeenCalledTimes(1));
    expect(recordApplyClickMock).toHaveBeenCalledWith('tok', {
      sourceId: 'greenhouse_api',
      jobId: '42',
      surface: 'recent',
      sessionId: 'sess-1',
    });
  });

  it('logs nothing when signed out', async () => {
    authState = { isAuthenticated: false, getToken: vi.fn() };
    const { result } = renderHook(() => useTrackApplyClick(job, 'recent'));
    result.current();
    await Promise.resolve();
    expect(authState.getToken).not.toHaveBeenCalled();
    expect(recordApplyClickMock).not.toHaveBeenCalled();
  });

  it('logs nothing without a surface (a hidden sizer copy)', async () => {
    const { result } = renderHook(() => useTrackApplyClick(job, undefined));
    result.current();
    await Promise.resolve();
    expect(recordApplyClickMock).not.toHaveBeenCalled();
  });

  it('logs nothing for a job without a backend sourceId', async () => {
    const { result } = renderHook(() =>
      useTrackApplyClick({ ...job, sourceId: undefined }, 'company')
    );
    result.current();
    await Promise.resolve();
    expect(recordApplyClickMock).not.toHaveBeenCalled();
  });

  it('returns synchronously and swallows a failed request', async () => {
    recordApplyClickMock.mockRejectedValue(new Error('network'));
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const { result } = renderHook(() => useTrackApplyClick(job, 'landing'));
    expect(result.current()).toBeUndefined();
    await waitFor(() => expect(recordApplyClickMock).toHaveBeenCalled());
    warn.mockRestore();
  });

  it('swallows a token failure', async () => {
    authState = {
      isAuthenticated: true,
      getToken: vi.fn().mockRejectedValue(new Error('expired')),
    };
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const { result } = renderHook(() => useTrackApplyClick(job, 'recent'));
    expect(() => result.current()).not.toThrow();
    await waitFor(() => expect(authState.getToken).toHaveBeenCalled());
    expect(recordApplyClickMock).not.toHaveBeenCalled();
    warn.mockRestore();
  });
});
