import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { EditCompanyPreferencesLink } from '../../../components/recent-jobs-page/EditCompanyPreferencesLink';

const mockLogin = vi.fn();
const mockLogout = vi.fn();
const mockGetToken = vi.fn();

let mockAuthState = {
  isEnabled: true,
  isAuthenticated: false,
  isLoading: false,
  login: mockLogin,
  logout: mockLogout,
  getToken: mockGetToken,
  user: null,
};

vi.mock('../../../features/auth/useAuth', () => ({
  useAuth: () => mockAuthState,
}));

let mockEnabledIds: string[] | null = null;
vi.mock('../../../app/hooks', () => ({
  useAppSelector: () => mockEnabledIds,
}));

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

function renderWithRouter() {
  return render(
    <MemoryRouter>
      <EditCompanyPreferencesLink />
    </MemoryRouter>
  );
}

function getCaption(testId: string): HTMLElement {
  const link = screen.getByTestId(testId);
  const caption = link.closest('p');
  if (!caption) {
    throw new Error(`Expected link ${testId} to be inside a <p> caption`);
  }
  return caption;
}

describe('EditCompanyPreferencesLink', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAuthState = {
      isEnabled: true,
      isAuthenticated: false,
      isLoading: false,
      login: mockLogin,
      logout: mockLogout,
      getToken: mockGetToken,
      user: null,
    };
    mockEnabledIds = null;
  });

  describe('when signed in', () => {
    beforeEach(() => {
      mockAuthState.isAuthenticated = true;
    });

    it('renders the enabled-count caption and a Customize link', () => {
      mockEnabledIds = ['a', 'b', 'c'];
      renderWithRouter();

      expect(getCaption('edit-company-preferences-link')).toHaveTextContent(
        'Showing jobs from your 3 enabled companies · Customize'
      );
      expect(screen.getByTestId('edit-company-preferences-link')).toHaveTextContent('Customize');
    });

    it('singularizes "company" when only one is enabled', () => {
      mockEnabledIds = ['a'];
      renderWithRouter();

      expect(getCaption('edit-company-preferences-link')).toHaveTextContent(
        'Showing jobs from your 1 enabled company · Customize'
      );
    });

    it('falls back to "all companies · Choose your companies" when no preferences are saved', () => {
      mockEnabledIds = [];
      renderWithRouter();

      expect(getCaption('edit-company-preferences-link')).toHaveTextContent(
        'Showing jobs from all companies · Choose your companies'
      );
      expect(screen.getByTestId('edit-company-preferences-link')).toHaveTextContent(
        'Choose your companies'
      );
    });

    it('renders a spacer while preferences are still loading', () => {
      mockEnabledIds = null;
      renderWithRouter();

      expect(screen.queryByTestId('edit-company-preferences-link')).not.toBeInTheDocument();
      expect(screen.queryByRole('button')).not.toBeInTheDocument();
    });

    it('navigates to /account on click', async () => {
      mockEnabledIds = ['a', 'b'];
      const user = userEvent.setup();
      renderWithRouter();

      await user.click(screen.getByTestId('edit-company-preferences-link'));

      expect(mockNavigate).toHaveBeenCalledWith('/account');
      expect(mockLogin).not.toHaveBeenCalled();
    });
  });

  describe('when signed out', () => {
    it('renders the "Sign in" prompt', () => {
      renderWithRouter();

      expect(getCaption('sign-in-to-edit-preferences-link')).toHaveTextContent(
        'Sign in to customize this feed to the companies you care about'
      );
      expect(screen.getByTestId('sign-in-to-edit-preferences-link')).toHaveTextContent('Sign in');
    });

    it('calls login on click, not navigate', async () => {
      const user = userEvent.setup();
      renderWithRouter();

      await user.click(screen.getByTestId('sign-in-to-edit-preferences-link'));

      expect(mockLogin).toHaveBeenCalledTimes(1);
      expect(mockNavigate).not.toHaveBeenCalled();
    });

    it('stays mounted when login rejects', async () => {
      mockLogin.mockRejectedValueOnce(new Error('Popup blocked'));
      const user = userEvent.setup();
      renderWithRouter();

      await user.click(screen.getByTestId('sign-in-to-edit-preferences-link'));

      expect(screen.getByTestId('sign-in-to-edit-preferences-link')).toBeInTheDocument();
    });
  });

  describe('when auth is loading', () => {
    it('renders the Sign-in prompt when loading and not yet authenticated', () => {
      // useAuth reports isAuthenticated=false while isLoading=true. The
      // signed-out branch must run during that window — otherwise the
      // NewFeatureCallout pill renders with no adjacent caption on first
      // paint.
      mockAuthState.isLoading = true;
      mockAuthState.isAuthenticated = false;
      renderWithRouter();

      expect(getCaption('sign-in-to-edit-preferences-link').textContent).toBe(
        'Sign in to customize this feed to the companies you care about'
      );
      expect(screen.getByTestId('sign-in-to-edit-preferences-link')).toHaveTextContent('Sign in');
      expect(screen.queryByTestId('edit-company-preferences-link')).not.toBeInTheDocument();
    });

    it('still renders a spacer when loading AND authenticated but enabledIds have not arrived', () => {
      // A user who *is* signed in must not see a "Sign in" flash. While
      // auth is loading and the session turns out to be authenticated, the
      // signed-in branch is waiting on enabledIds, so the placeholder must
      // still render.
      mockAuthState.isLoading = true;
      mockAuthState.isAuthenticated = true;
      mockEnabledIds = null;
      renderWithRouter();

      expect(screen.queryByTestId('edit-company-preferences-link')).not.toBeInTheDocument();
      expect(screen.queryByTestId('sign-in-to-edit-preferences-link')).not.toBeInTheDocument();
      expect(screen.queryByRole('button')).not.toBeInTheDocument();
    });

    it('swaps from Sign-in prompt to spacer, then to the signed-in caption as auth resolves', () => {
      mockAuthState.isLoading = true;
      mockAuthState.isAuthenticated = false;
      mockEnabledIds = null;
      const { rerender } = renderWithRouter();

      // 1) Loading + unauthenticated: Sign-in prompt present.
      expect(screen.getByTestId('sign-in-to-edit-preferences-link')).toBeInTheDocument();

      // 2) Auth resolved to signed-in but enabledIds still loading: spacer.
      mockAuthState.isLoading = false;
      mockAuthState.isAuthenticated = true;
      mockEnabledIds = null;
      rerender(
        <MemoryRouter>
          <EditCompanyPreferencesLink />
        </MemoryRouter>
      );

      expect(screen.queryByTestId('sign-in-to-edit-preferences-link')).not.toBeInTheDocument();
      expect(screen.queryByTestId('edit-company-preferences-link')).not.toBeInTheDocument();
      expect(screen.queryByRole('button')).not.toBeInTheDocument();

      // 3) enabledIds arrive: signed-in "Customize" caption renders.
      mockEnabledIds = ['apple'];
      rerender(
        <MemoryRouter>
          <EditCompanyPreferencesLink />
        </MemoryRouter>
      );

      expect(screen.getByTestId('edit-company-preferences-link')).toBeInTheDocument();
      expect(screen.getByTestId('edit-company-preferences-link')).toHaveTextContent('Customize');
      expect(screen.queryByTestId('sign-in-to-edit-preferences-link')).not.toBeInTheDocument();
    });
  });
});
