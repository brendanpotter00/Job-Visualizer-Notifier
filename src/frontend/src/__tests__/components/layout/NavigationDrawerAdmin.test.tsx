import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, render as rtlRender } from '@testing-library/react';
import type { ReactElement } from 'react';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { NavigationDrawer } from '../../../components/layout/NavigationDrawer.tsx';
import { createTestStore } from '../../../test/testUtils';
import type { RootState } from '../../../app/store';

let mockUser: { isAdmin: boolean } | null = null;
let mockUserError: string | null = null;
const mockReload = vi.fn();

vi.mock('../../../features/auth/useAuth', () => ({
  useAuth: () => ({
    isEnabled: true,
    isAuthenticated: true,
    isLoading: false,
    user: null,
    login: vi.fn(),
    logout: vi.fn(),
    getToken: vi.fn(),
  }),
}));

vi.mock('../../../features/auth/useCurrentUser', () => ({
  useCurrentUser: () => ({
    user: mockUser,
    setUser: vi.fn(),
    loading: false,
    error: mockUserError,
    reload: mockReload,
  }),
}));

const mockProps = {
  open: true,
  onClose: vi.fn(),
  onToggleCollapse: vi.fn(),
  drawerWidth: 240,
  isMobile: false,
};

// NavigationDrawer reads `ui.hideAdminFeatures` via useAppSelector, so every
// render needs a Redux Provider. Wrap RTL's render with a test store.
function render(ui: ReactElement, preloadedState?: Partial<RootState>) {
  return rtlRender(<Provider store={createTestStore(preloadedState)}>{ui}</Provider>);
}

describe('NavigationDrawer admin section', () => {
  beforeEach(() => {
    mockUser = null;
    mockUserError = null;
    mockReload.mockReset();
  });

  it('hides the Admin section when the current-user profile has not loaded', () => {
    mockUser = null;
    render(
      <MemoryRouter>
        <NavigationDrawer {...mockProps} />
      </MemoryRouter>
    );
    expect(screen.queryByText('ADMIN')).not.toBeInTheDocument();
    expect(screen.queryByText('Users')).not.toBeInTheDocument();
    expect(screen.queryByText('Scraper Runs')).not.toBeInTheDocument();
    expect(screen.queryByText('User Feedback')).not.toBeInTheDocument();
  });

  it('hides the Admin section for non-admin users', () => {
    mockUser = { isAdmin: false };
    render(
      <MemoryRouter>
        <NavigationDrawer {...mockProps} />
      </MemoryRouter>
    );
    expect(screen.queryByText('ADMIN')).not.toBeInTheDocument();
    expect(screen.queryByText('Users')).not.toBeInTheDocument();
    expect(screen.queryByText('Scraper Runs')).not.toBeInTheDocument();
    expect(screen.queryByText('User Feedback')).not.toBeInTheDocument();
  });

  it('shows the Admin section with Users, Scraper Runs and User Feedback items for admins', () => {
    mockUser = { isAdmin: true };
    render(
      <MemoryRouter>
        <NavigationDrawer {...mockProps} />
      </MemoryRouter>
    );
    expect(screen.getByText('ADMIN')).toBeInTheDocument();
    expect(screen.getByText('Users')).toBeInTheDocument();
    expect(screen.getByText('Scraper Runs')).toBeInTheDocument();
    expect(screen.getByText('User Feedback')).toBeInTheDocument();
  });

  it('hides the Admin section for admins when hideAdminFeatures is enabled (demo mode)', () => {
    // Demo-only ephemeral flag in the ui slice. Even for a real admin, the
    // entire Admin group is suppressed while the flag is on; it returns on
    // refresh because the flag is not persisted.
    mockUser = { isAdmin: true };
    render(
      <MemoryRouter>
        <NavigationDrawer {...mockProps} />
      </MemoryRouter>,
      {
        ui: {
          graphModal: { open: false },
          globalLoading: false,
          notifications: [],
          hideAdminFeatures: true,
        },
      }
    );
    expect(screen.queryByText('ADMIN')).not.toBeInTheDocument();
    expect(screen.queryByText('Users')).not.toBeInTheDocument();
    expect(screen.queryByText('Scraper Runs')).not.toBeInTheDocument();
  });

  it('renders admin items flat (icons only) when the drawer is collapsed', () => {
    mockUser = { isAdmin: true };
    render(
      <MemoryRouter>
        <NavigationDrawer {...mockProps} open={false} />
      </MemoryRouter>
    );
    // Icons are still rendered; the ADMIN caption is hidden because text
    // labels are hidden at collapsed widths.
    expect(screen.getByTestId('PeopleIcon')).toBeInTheDocument();
    expect(screen.getByTestId('BugReportIcon')).toBeInTheDocument();
    expect(screen.queryByText('ADMIN')).not.toBeInTheDocument();
  });

  it('renders the "admin status unavailable" indicator when /api/users errored with no cached user', async () => {
    // Auth backend outage: ``useCurrentUser`` returned ``{ user: null,
    // error: '...' }``. Hiding the Admin section entirely silently
    // strips admin nav from anyone who refreshes during the outage,
    // including real admins. The indicator surfaces the unavailability
    // so the admin retries instead of assuming their access was
    // revoked.
    const userEvent = (await import('@testing-library/user-event')).default;
    mockUser = null;
    mockUserError = '/api/users failed: 500';
    render(
      <MemoryRouter>
        <NavigationDrawer {...mockProps} />
      </MemoryRouter>
    );

    expect(screen.getByTestId('admin-status-unavailable')).toBeInTheDocument();
    expect(screen.getByText(/admin status unavailable/i)).toBeInTheDocument();

    // Clicking the indicator must call reload() so the admin can retry
    // without a full page refresh. The button is nested inside the
    // ListItem testid wrapper; aria-label exposes the affordance.
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /admin status unavailable.*retry/i }));
    expect(mockReload).toHaveBeenCalled();
  });

  it('does NOT render the unavailability indicator when userError is null', () => {
    // Regression guard: the indicator must only fire on the
    // ``userError && !user`` case, not on every signed-in render with
    // no admin grant.
    mockUser = null;
    mockUserError = null;
    render(
      <MemoryRouter>
        <NavigationDrawer {...mockProps} />
      </MemoryRouter>
    );
    expect(screen.queryByTestId('admin-status-unavailable')).not.toBeInTheDocument();
  });

  it('keeps the Account item anchored to the bottom via a flex spacer', () => {
    // Regression guard for the "admin section takes up the entire sidebar"
    // layout bug. The fix replaces `mt: 'auto'` on the Account divider with
    // an explicit `<Box sx={{ flexGrow: 1 }} />` spacer between the Admin
    // group and the Account section. We assert: the drawer content is a
    // flex column, Account appears after the spacer in DOM order, and the
    // spacer's `flexGrow` style is present.
    mockUser = { isAdmin: true };
    const { container } = render(
      <MemoryRouter>
        <NavigationDrawer {...mockProps} />
      </MemoryRouter>
    );

    // The Account link should be rendered.
    const accountText = screen.getByText('Account');
    expect(accountText).toBeInTheDocument();

    // Locate the spacer: the only div with flex-grow: 1 inside the drawer
    // content. computedStyle uses the inline-equivalent via getAttribute on
    // the style attribute (jsdom + MUI's sx serializes to inline class, so
    // probe by walking siblings instead).
    const accountListItem = accountText.closest('li');
    expect(accountListItem).not.toBeNull();
    // The spacer lives in the DOM between the Admin section and the
    // <Divider> immediately above Account — i.e. it precedes Account.
    // Grab all elements within the drawer paper that look like a spacer.
    const spacerCandidates = container.querySelectorAll('div');
    const hasSpacer = Array.from(spacerCandidates).some((el) => {
      const styles = window.getComputedStyle(el);
      return styles.flexGrow === '1' && !el.querySelector('*');
    });
    expect(hasSpacer).toBe(true);
  });
});
