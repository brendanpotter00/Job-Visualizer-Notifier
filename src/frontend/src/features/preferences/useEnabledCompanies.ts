import { useEffect, useCallback, useRef } from 'react';
import { useAuth } from '../auth/useAuth';
import { useAppDispatch, useAppSelector } from '../../app/hooks';
import {
  loadEnabledCompanies,
  saveEnabledCompanies,
  resetEnabledCompanies,
  selectEnabledCompanyIds,
} from './enabledCompaniesSlice';

type AbortableLoad = { abort: (reason?: string) => void };

export function useEnabledCompanies() {
  const { isAuthenticated, getToken } = useAuth();
  const dispatch = useAppDispatch();
  const ids = useAppSelector(selectEnabledCompanyIds);
  const loading = useAppSelector((s) => s.enabledCompanies.loading);
  const error = useAppSelector((s) => s.enabledCompanies.error);
  // Tracks the in-flight load so auth-state changes and subsequent reloads
  // can cancel a stale request — otherwise a fetch started while authenticated
  // could resolve after sign-out and repopulate ids on a signed-out session.
  const activePromise = useRef<AbortableLoad | null>(null);

  const reload = useCallback(() => {
    activePromise.current?.abort();
    activePromise.current = null;
    if (!isAuthenticated) {
      dispatch(resetEnabledCompanies());
      return;
    }
    getToken()
      .then((token) => {
        activePromise.current = dispatch(loadEnabledCompanies(token));
      })
      .catch(() => {
        // getToken failure (e.g. expired session) surfaces through the slice
        // on the next successful reload; nothing to do here.
      });
  }, [isAuthenticated, getToken, dispatch]);

  useEffect(() => {
    if (isAuthenticated) {
      reload();
    } else {
      activePromise.current?.abort();
      activePromise.current = null;
      dispatch(resetEnabledCompanies());
    }
    return () => {
      activePromise.current?.abort();
      activePromise.current = null;
    };
  }, [isAuthenticated, reload, dispatch]);

  const save = useCallback(
    async (companyIds: string[]) => {
      const token = await getToken();
      await dispatch(saveEnabledCompanies({ token, companyIds })).unwrap();
    },
    [getToken, dispatch]
  );

  return { ids, loading, error, save, reload };
}
