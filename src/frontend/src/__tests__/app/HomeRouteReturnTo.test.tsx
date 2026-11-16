import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { useEffect, useReducer, type ReactNode } from 'react';
import { BrowserRouter, Route, Routes, useLocation } from 'react-router-dom';
import type { AppState } from '@auth0/auth0-react';
import { HomeRoute } from '../../app/HomeRoute';
import { handleAuthRedirect } from '../../features/auth/returnTo';
import * as authModule from '../../features/auth/useAuth';

/**
 * "Sign in to upgrade" must land on /pricing?intent=pro. Auth0's callback renders
 * HomeRoute at `/?code=…`; auth0-react calls onRedirectCallback and then, in the
 * same tick, flips auth to signed-in.
 */
vi.mock('../../features/auth/useAuth', async () => {
  const React = await import('react');
  const AuthCtx = React.createContext({ isAuthenticated: false, isLoading: true });
  return {
    __AuthCtx: AuthCtx,
    useAuth: () => React.useContext(AuthCtx),
  };
});

const AuthCtx = (authModule as unknown as { __AuthCtx: React.Context<unknown> }).__AuthCtx;

function FakeAuth0Provider({ appState, children }: { appState: AppState; children: ReactNode }) {
  const [state, dispatch] = useReducer(
    (_: unknown, action: 'INITIALISED') =>
      action === 'INITIALISED' ? { isAuthenticated: true, isLoading: false } : _,
    { isAuthenticated: false, isLoading: true }
  );
  useEffect(() => {
    void (async () => {
      await new Promise((r) => setTimeout(r, 10)); // client.handleRedirectCallback()
      handleAuthRedirect(appState);
      dispatch('INITIALISED');
    })();
  }, [appState]);
  return <AuthCtx.Provider value={state}>{children}</AuthCtx.Provider>;
}

function Where({ name }: { name: string }) {
  const { pathname, search } = useLocation();
  return <div data-testid="where">{`${name} ${pathname}${search}`}</div>;
}

function renderCallback(appState: AppState) {
  window.history.replaceState({}, '', '/?code=abc&state=xyz');
  render(
    <FakeAuth0Provider appState={appState}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<HomeRoute />} />
          <Route path="/pricing" element={<Where name="pricing" />} />
          <Route path="/jobs" element={<Where name="jobs" />} />
        </Routes>
      </BrowserRouter>
    </FakeAuth0Provider>
  );
}

describe('HomeRoute after an Auth0 redirect', () => {
  afterEach(() => window.history.replaceState({}, '', '/'));

  it('lands on the returnTo, not /jobs', async () => {
    renderCallback({ returnTo: '/pricing?intent=pro' });
    await waitFor(() =>
      expect(screen.getByTestId('where')).toHaveTextContent('pricing /pricing?intent=pro')
    );
    // And it stays there: nothing navigates to /jobs afterwards.
    await new Promise((r) => setTimeout(r, 50));
    expect(window.location.pathname + window.location.search).toBe('/pricing?intent=pro');
  });

  it('without a returnTo, lands on /jobs', async () => {
    renderCallback({});
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('jobs /jobs'));
  });

  it('ignores an off-site returnTo', async () => {
    renderCallback({ returnTo: '//evil.example/x' });
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('jobs /jobs'));
  });
});
