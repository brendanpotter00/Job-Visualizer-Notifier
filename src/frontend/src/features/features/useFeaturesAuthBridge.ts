import { useEffect } from 'react';
import { useAuth } from '../auth/useAuth';
import { registerTokenGetter } from './getTokenOrNull';

export function useFeaturesAuthBridge(): void {
  const { getToken } = useAuth();

  useEffect(() => {
    registerTokenGetter(getToken);
    return () => {
      registerTokenGetter(null);
    };
  }, [getToken]);
}
