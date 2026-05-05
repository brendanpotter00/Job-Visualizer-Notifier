import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { EditCompanyPreferencesRow } from '../../../components/recent-jobs-page/EditCompanyPreferencesRow';

const mockLogin = vi.fn();
const mockLogout = vi.fn();
const mockGetToken = vi.fn();

let mockAuthState = {
  isEnabled: true,
  isAuthenticated: true,
  isLoading: false,
  login: mockLogin,
  logout: mockLogout,
  getToken: mockGetToken,
  user: null,
};

vi.mock('../../../features/auth/useAuth', () => ({
  useAuth: () => mockAuthState,
}));

let mockEnabledIds: string[] | null = ['a', 'b'];
vi.mock('../../../app/hooks', () => ({
  useAppSelector: () => mockEnabledIds,
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => vi.fn(),
  };
});

function renderRow() {
  return render(
    <MemoryRouter>
      <EditCompanyPreferencesRow />
    </MemoryRouter>
  );
}

// Pin Date.now() to a moment before the NewFeatureCallout's expiresAt
// (2026-05-02T00:00:00Z) so these tests are deterministic regardless of
// when CI runs. The real-time clock is irrelevant — the row's row of
// callout/dismiss UI is what's under test.
const FIXED_NOW_MS = new Date('2026-04-15T00:00:00Z').getTime();

describe('EditCompanyPreferencesRow', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
    vi.spyOn(Date, 'now').mockReturnValue(FIXED_NOW_MS);
    mockAuthState = {
      isEnabled: true,
      isAuthenticated: true,
      isLoading: false,
      login: mockLogin,
      logout: mockLogout,
      getToken: mockGetToken,
      user: null,
    };
    mockEnabledIds = ['a', 'b'];
  });

  afterEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it('renders the wrapper, the edit preferences link, and the callout', () => {
    renderRow();

    expect(screen.getByTestId('edit-company-preferences-row')).toBeInTheDocument();
    expect(screen.getByTestId('edit-company-preferences-link')).toBeInTheDocument();
    expect(screen.getByText('New! Pick your companies')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Dismiss' })).toBeInTheDocument();
  });

  it('places the callout as a sibling of the link inside the wrapper', () => {
    renderRow();

    const wrapper = screen.getByTestId('edit-company-preferences-row');
    const link = screen.getByTestId('edit-company-preferences-link');
    const callout = screen.getByRole('status');

    expect(wrapper).toContainElement(link);
    expect(wrapper).toContainElement(callout);
  });

  it('still renders the callout when the user is signed out', () => {
    mockAuthState.isAuthenticated = false;
    renderRow();

    expect(screen.getByTestId('sign-in-to-edit-preferences-link')).toBeInTheDocument();
    expect(screen.getByText('New! Pick your companies')).toBeInTheDocument();
  });

  it('hides the callout after the Dismiss button is clicked', () => {
    renderRow();

    expect(screen.getByRole('status')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(screen.queryByText('New! Pick your companies')).not.toBeInTheDocument();
  });

  it('stays dismissed across unmount + remount (localStorage-backed)', () => {
    const { unmount } = renderRow();

    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
    expect(screen.queryByRole('status')).not.toBeInTheDocument();

    unmount();

    render(
      <MemoryRouter>
        <EditCompanyPreferencesRow />
      </MemoryRouter>
    );

    expect(screen.queryByRole('status')).toBeNull();
    expect(screen.queryByText('New! Pick your companies')).toBeNull();
  });
});
