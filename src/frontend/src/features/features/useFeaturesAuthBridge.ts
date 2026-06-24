import { useLayoutEffect } from 'react';
import { useAuth } from '../auth/useAuth';
import { logger } from '../../lib/logger';
import { registerTokenGetter } from './getTokenOrNull';

export function useFeaturesAuthBridge(): void {
  const { getToken } = useAuth();

  // MUST be useLayoutEffect, not useEffect. React flushes ALL layout effects
  // (whole tree) before ANY passive effect, whereas passive effects run
  // child-first. The auth-gated RTK Query queries (saved filters / keyword
  // lists) dispatch their first request from a *passive* effect — and several
  // live in route components mounted *below* this app-root hook. With a passive
  // effect here, those deeper queries fire before this registers the token
  // getter, so they read a null getter, go out anonymous, 401, and — having no
  // retry/refetch — strand the page on "Loading…". Registering in a layout
  // effect guarantees the getter is live before any passive query dispatch.
  useLayoutEffect(() => {
    registerTokenGetter(getToken);
    // Debug observability: if the bridge silently fails to register (removed
    // call site, upstream render error, import failure), every authenticated
    // mutation goes out anonymous and gets 401. A visible lifecycle trace
    // makes the "mutations going out anonymous" symptom debuggable.
    logger.debug('[useFeaturesAuthBridge] registered getToken');
    return () => {
      logger.debug('[useFeaturesAuthBridge] unregistered getToken');
      registerTokenGetter(null);
    };
  }, [getToken]);
}
