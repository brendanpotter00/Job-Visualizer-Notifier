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

describe('EditCompanyPreferencesRow', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
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

  it('renders both the signed-out caption and the callout while auth is still loading', () => {
    // End-to-end regression for Unit 1: on `main` the caption would be
    // replaced by a height-reservation Box while isLoading=true, leaving
    // the NewFeatureCallout pill next to an invisible placeholder on first
    // paint. After the fix, both render together.
    mockAuthState.isLoading = true;
    mockAuthState.isAuthenticated = false;
    mockEnabledIds = null;
    renderRow();

    expect(screen.getByTestId('edit-company-preferences-row')).toBeInTheDocument();
    expect(screen.getByTestId('sign-in-to-edit-preferences-link')).toBeInTheDocument();
    expect(screen.getByRole('status')).toBeInTheDocument();
    expect(screen.getByText('New! Pick your companies')).toBeInTheDocument();
    expect(screen.queryByTestId('edit-company-preferences-link')).not.toBeInTheDocument();
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
