import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../../test/testUtils';
import { VoteFeaturesPage } from '../../../pages/VoteFeaturesPage/VoteFeaturesPage';

const mockAuthState = {
  isEnabled: true,
  isAuthenticated: false,
  isLoading: false,
  login: vi.fn(),
  logout: vi.fn(),
  getToken: vi.fn(),
  user: null,
};

vi.mock('../../../features/auth/useAuth', () => ({
  useAuth: () => mockAuthState,
}));

vi.mock('../../../pages/VoteFeaturesPage/ChangelogColumn', () => ({
  ChangelogColumn: () => <div data-testid="changelog-column" />,
}));

vi.mock('../../../pages/VoteFeaturesPage/VotingColumn', () => ({
  VotingColumn: () => <div data-testid="voting-column" />,
}));

describe('VoteFeaturesPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the "Vote for features" h1 heading', () => {
    renderWithProviders(<VoteFeaturesPage />);
    expect(
      screen.getByRole('heading', { name: /vote for features/i, level: 1 })
    ).toBeInTheDocument();
  });

  it('renders the ChangelogColumn', () => {
    renderWithProviders(<VoteFeaturesPage />);
    expect(screen.getByTestId('changelog-column')).toBeInTheDocument();
  });

  it('renders the VotingColumn', () => {
    renderWithProviders(<VoteFeaturesPage />);
    expect(screen.getByTestId('voting-column')).toBeInTheDocument();
  });
});
