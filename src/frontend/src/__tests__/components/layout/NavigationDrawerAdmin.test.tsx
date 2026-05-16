import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { NavigationDrawer } from '../../../components/layout/NavigationDrawer.tsx';

let mockUser: { isAdmin: boolean } | null = null;

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
    error: null,
    reload: vi.fn(),
  }),
}));

const mockProps = {
  open: true,
  onClose: vi.fn(),
  onToggleCollapse: vi.fn(),
  drawerWidth: 240,
  isMobile: false,
};

describe('NavigationDrawer admin section', () => {
  beforeEach(() => {
    mockUser = null;
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
    expect(screen.queryByText('Scraper')).not.toBeInTheDocument();
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
    expect(screen.queryByText('Scraper')).not.toBeInTheDocument();
  });

  it('shows the Admin section with Users and Scraper items for admins', () => {
    mockUser = { isAdmin: true };
    render(
      <MemoryRouter>
        <NavigationDrawer {...mockProps} />
      </MemoryRouter>
    );
    expect(screen.getByText('ADMIN')).toBeInTheDocument();
    expect(screen.getByText('Users')).toBeInTheDocument();
    expect(screen.getByText('Scraper')).toBeInTheDocument();
  });

  it('renders admin items flat (icons only) when the drawer is collapsed', () => {
    mockUser = { isAdmin: true };
    render(
      <MemoryRouter>
        <NavigationDrawer {...mockProps} open={false} />
      </MemoryRouter>
    );
    // Icons are still rendered; ADMIN caption is hidden because the
    // accordion header is omitted at collapsed widths.
    expect(screen.getByTestId('PeopleIcon')).toBeInTheDocument();
    expect(screen.getByTestId('BugReportIcon')).toBeInTheDocument();
    expect(screen.queryByText('ADMIN')).not.toBeInTheDocument();
  });
});
