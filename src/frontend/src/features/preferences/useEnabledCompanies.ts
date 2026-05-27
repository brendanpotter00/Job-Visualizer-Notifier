import { useEffect, useCallback, useRef } from 'react';
import { useAuth } from '../auth/useAuth';
import { useAppDispatch, useAppSelector } from '../../app/hooks';
import {
  loadEnabledCompanies,
  saveEnabledCompanies,
  resetEnabledCompanies,
  enabledCompaniesLoadFailed,
  selectEnabledCompanyIds,
  selectAutoEnroll,
} from './enabledCompaniesSlice';
import { extractErrorMessage } from '../../lib/errors';

type AbortableLoad = { abort: (reason?: string) => void };

export function useEnabledCompanies() {
  const { isAuthenticated, getToken } = useAuth();
  const dispatch = useAppDispatch();
  const ids = useAppSelector(selectEnabledCompanyIds);
  const autoEnroll = useAppSelector(selectAutoEnroll);
  const loading = useAppSelector((s) => s.enabledCompanies.loading);
  const error = useAppSelector((s) => s.enabledCompanies.error);
  // Tracks the in-flight load so auth-state changes and subsequent reloads
  // can cancel a stale request — otherwise a fetch started while authenticated
  // could resolve after cancellation and overwrite current state.
  const activePromise = useRef<AbortableLoad | null>(null);

  const reload = useCallback(() => {
    activePromise.current?.abort();
    activePromise.current = null;
    if (!isAuthenticated) {
      dispatch(resetEnabledCompanies());
      return;
    }
    // Install a local AbortController BEFORE awaiting getToken so cleanup
    // triggered during the token await still has something to abort.
    // Without this, a token resolving after sign-out would dispatch
    // loadEnabledCompanies against a signed-out session.
    const controller = new AbortController();
    const handle: AbortableLoad = {
      abort: (reason?: string) => controller.abort(reason),
    };
    activePromise.current = handle;

    getToken()
      .then((token) => {
        if (controller.signal.aborted || activePromise.current !== handle) return;
        activePromise.current = dispatch(loadEnabledCompanies(token));
      })
      .catch((err) => {
        if (controller.signal.aborted || activePromise.current !== handle) return;
        activePromise.current = null;
        const message = extractErrorMessage(err, 'Failed to acquire auth token');
        dispatch(enabledCompaniesLoadFailed(message));
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
    async (companyIds: string[], autoEnrollNewCompanies: boolean = true) => {
      // Abort any in-flight load before saving. The slice's save.pending
      // reducer also invalidates activeLoadRequestId as a backstop — if
      // the load's fetch already resolved, its .fulfilled handler will
      // detect the stale id and skip overwriting saved ids.
      activePromise.current?.abort();
      activePromise.current = null;
      const token = await getToken();
      await dispatch(
        saveEnabledCompanies({
          token,
          companyIds,
          autoEnroll: autoEnrollNewCompanies,
        })
      ).unwrap();
    },
    [getToken, dispatch]
  );

  return { ids, autoEnroll, loading, error, save, reload };
}
