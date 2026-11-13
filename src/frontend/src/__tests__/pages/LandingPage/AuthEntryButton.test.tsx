import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { AuthEntryButton } from '../../../pages/LandingPage/sections/AuthEntryButton';
import { ROUTES } from '../../../config/routes';

const auth = {
  isEnabled: true,
  isAuthenticated: false,
  login: vi.fn(async () => {}),
  signup: vi.fn(async () => {}),
};

vi.mock('../../../features/auth/useAuth', () => ({
  useAuth: () => auth,
}));

const trackSignInClick = vi.fn();
vi.mock('../../../features/analytics/events', () => ({
  trackSignInClick: (location: string) => trackSignInClick(location),
}));

const CTA = { label: 'Sign up', to: ROUTES.ACCOUNT };

function renderButton(mode: 'login' | 'signup') {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route
          path="/"
          element={<AuthEntryButton cta={CTA} mode={mode} location="landing_header" />}
        />
        <Route path={ROUTES.RECENT_JOBS} element={<div>jobs board</div>} />
        <Route path={ROUTES.ACCOUNT} element={<div>account page</div>} />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  auth.isEnabled = true;
  auth.isAuthenticated = false;
  auth.login = vi.fn(async () => {});
  auth.signup = vi.fn(async () => {});
  trackSignInClick.mockClear();
});

describe('AuthEntryButton', () => {
  it('log in opens the Auth0 login screen and records the click', async () => {
    renderButton('login');
    await userEvent.click(screen.getByRole('button', { name: 'Sign up' }));
    expect(auth.login).toHaveBeenCalledTimes(1);
    expect(auth.signup).not.toHaveBeenCalled();
    expect(trackSignInClick).toHaveBeenCalledWith('landing_header');
  });

  it('sign up opens the Auth0 sign-up screen', async () => {
    renderButton('signup');
    await userEvent.click(screen.getByRole('button', { name: 'Sign up' }));
    expect(auth.signup).toHaveBeenCalledTimes(1);
    expect(auth.login).not.toHaveBeenCalled();
  });

  it('sends a signed-in visitor to the jobs board instead', async () => {
    auth.isAuthenticated = true;
    renderButton('signup');
    await userEvent.click(screen.getByRole('button', { name: 'Sign up' }));
    expect(await screen.findByText('jobs board')).toBeInTheDocument();
    expect(auth.signup).not.toHaveBeenCalled();
  });

  it('falls back to the account page when the redirect fails', async () => {
    auth.signup = vi.fn(async () => {
      throw new Error('blocked');
    });
    renderButton('signup');
    await userEvent.click(screen.getByRole('button', { name: 'Sign up' }));
    await waitFor(() => expect(screen.getByText('account page')).toBeInTheDocument());
  });

  it('renders a plain link to the account page when auth is not configured', () => {
    auth.isEnabled = false;
    renderButton('signup');
    expect(screen.getByRole('link', { name: 'Sign up' })).toHaveAttribute('href', ROUTES.ACCOUNT);
  });
});
