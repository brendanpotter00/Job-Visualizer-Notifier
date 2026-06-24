import { useEffect, useRef } from 'react';
import { useAuth } from './useAuth';
import { recordVisit } from './authService';

/**
 * Record exactly one "visit" per full page load / refresh for the signed-in
 * user — this backs the admin roster's "most frequent users" view.
 *
 * Mounted once at the app root (`AppContent`). Because `AppContent` is NOT
 * remounted by client-side `<Link>` navigation, this fires once per real page
 * load and never on in-SPA route changes. The `firedRef` guard is set
 * synchronously before the await so it survives:
 *   - React.StrictMode's dev double-invocation of effects, and
 *   - effect re-runs caused by `getToken` / `isAuthenticated` identity changes
 *     mid-session (e.g. a silent token refresh).
 * It only resets when the component unmounts — i.e. on a genuine full reload.
 *
 * Gated on `isAuthenticated`: anonymous loads record nothing (there's no user
 * row to attribute them to; Google Analytics covers anonymous traffic). The
 * POST is fire-and-forget — a failure is logged and swallowed so visit
 * telemetry can never break the app (mirrors `useCurrentUser`).
 */
export function useRecordVisit(): void {
  const { isAuthenticated, getToken } = useAuth();
  const firedRef = useRef(false);

  useEffect(() => {
    if (!isAuthenticated || firedRef.current) return;
    // Set the guard BEFORE awaiting so a second StrictMode invocation (or an
    // effect re-run from a changed getToken/isAuthenticated identity) bails.
    firedRef.current = true;

    const send = async () => {
      try {
        const token = await getToken();
        await recordVisit(token);
      } catch (err) {
        console.error('[useRecordVisit] failed to record visit', err);
      }
    };
    void send();
  }, [isAuthenticated, getToken]);
}
