import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../features/auth/useAuth';
import { setLoginRef, setNavigateRef } from './refs';

/**
 * Render-null bridge that captures the router's `navigate` and Auth0's `login`
 * into module refs (`refs.ts`) so the store-only `registerWebMcpTools(store)`
 * entry can still reach these hook-bound APIs at tool-call time (§2.5).
 *
 * Mounted only behind `WEBMCP_CONFIG.isEnabled`, inside `<BrowserRouter>` (so
 * `useNavigate` has router context). Touches no other state; clears the refs on
 * unmount so a torn-down tree never leaves a dangling navigate.
 */
export function WebMcpBridge(): null {
  const navigate = useNavigate();
  const { login } = useAuth();

  useEffect(() => {
    setNavigateRef(navigate);
    setLoginRef(login);
    return () => {
      setNavigateRef(null);
      setLoginRef(null);
    };
  }, [navigate, login]);

  return null;
}
