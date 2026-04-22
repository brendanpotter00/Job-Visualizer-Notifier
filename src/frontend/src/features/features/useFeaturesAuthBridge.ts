import { useEffect } from 'react';
import { useAuth } from '../auth/useAuth';
import { logger } from '../../lib/logger';
import { registerTokenGetter } from './getTokenOrNull';

export function useFeaturesAuthBridge(): void {
  const { getToken } = useAuth();

  useEffect(() => {
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
