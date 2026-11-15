import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { useEffect, useReducer, type ReactNode } from 'react';
import { BrowserRouter, Route, Routes, useLocation } from 'react-router-dom';
import { HomeRoute } from '../../app/HomeRoute';
import * as authModule from '../../features/auth/useAuth';

/**
 * Regression: "Sign in to upgrade" must land on /pricing?intent=pro, not /jobs.
 *
 * Auth0's redirect_uri is the origin, so the callback renders HomeRoute at
 * `/?code=…`. auth0-react calls onRedirectCallback (our replaceState + synthetic
 * popstate, which React Router 7 applies as a TRANSITION) and then, in the same
 * tick, flips auth to signed-in (an URGENT update). Before the fix HomeRoute saw
 * "signed in" while the router still said "/", and <Navigate to="/jobs"> won.
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

function FakeAuth0Provider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(
    (_: unknown, action: 'INITIALISED') =>
      action === 'INITIALISED' ? { isAuthenticated: true, isLoading: false } : _,
    { isAuthenticated: false, isLoading: true }
  );
  useEffect(() => {
    void (async () => {
      await new Promise((r) => setTimeout(r, 10)); // client.handleRedirectCallback()
      // AuthProviders.handleRedirectCallback({ returnTo: '/pricing?intent=pro' })
      window.history.replaceState({}, document.title, '/pricing?intent=pro');
      window.dispatchEvent(new PopStateEvent('popstate', { state: {} }));
      dispatch('INITIALISED'); // auth0-react, same tick
    })();
  }, []);
  return <AuthCtx.Provider value={state}>{children}</AuthCtx.Provider>;
}

function Where({ name }: { name: string }) {
  const { pathname, search } = useLocation();
  return <div data-testid="where">{`${name} ${pathname}${search}`}</div>;
}

describe('HomeRoute after an Auth0 redirect with a returnTo', () => {
  afterEach(() => window.history.replaceState({}, '', '/'));

  it('lands on /pricing?intent=pro, not /jobs', async () => {
    window.history.replaceState({}, '', '/?code=abc&state=xyz');
    render(
      <FakeAuth0Provider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<HomeRoute />} />
            <Route path="/pricing" element={<Where name="pricing" />} />
            <Route path="/jobs" element={<Where name="jobs" />} />
          </Routes>
        </BrowserRouter>
      </FakeAuth0Provider>
    );
    await waitFor(() =>
      expect(screen.getByTestId('where')).toHaveTextContent('pricing /pricing?intent=pro')
    );
    // And it stays there: nothing navigates to /jobs afterwards.
    await new Promise((r) => setTimeout(r, 50));
    expect(window.location.pathname).toBe('/pricing');
  });
});
