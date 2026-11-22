import { useCallback } from 'react';
import { useAuth } from '../auth/useAuth';
import { recordApplyClick, type ApplyClickSurface } from '../auth/authService';
import { getPostHogSessionId } from './events';
import type { Job } from '../../types';

/**
 * Returns a click handler that logs an apply click for `job` on `surface`.
 *
 * Fire-and-forget: it never prevents or delays the link opening (the request is
 * sent with `keepalive` after the click has already gone through), and any
 * failure is swallowed. It does nothing when the user is signed out, when no
 * `surface` is given (a hidden, non-interactive copy of a card), or when the job
 * has no backend `sourceId` to key the row on.
 */
export function useTrackApplyClick(job: Job, surface: ApplyClickSurface | undefined): () => void {
  const { isAuthenticated, getToken } = useAuth();
  const { sourceId, id: jobId } = job;

  return useCallback(() => {
    if (!isAuthenticated || !surface || !sourceId) return;
    const sessionId = getPostHogSessionId();
    const send = async () => {
      try {
        const token = await getToken();
        await recordApplyClick(token, { sourceId, jobId, surface, sessionId });
      } catch (err) {
        if (import.meta.env.DEV) {
          console.warn('[useTrackApplyClick] failed to record apply click (non-fatal):', err);
        }
      }
    };
    void send();
  }, [isAuthenticated, getToken, surface, sourceId, jobId]);
}
