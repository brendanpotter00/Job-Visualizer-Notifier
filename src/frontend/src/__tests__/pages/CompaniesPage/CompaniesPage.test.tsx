import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../../test/testUtils';
import { CompaniesPage } from '../../../pages/CompaniesPage/CompaniesPage';

const mockHandleRetry = vi.fn();

interface MockLoaderState {
  isLoading: boolean;
  error: string | undefined;
  handleRetry: () => void;
  jobs: unknown[];
  metadata: unknown;
}

let mockLoaderState: MockLoaderState = {
  isLoading: false,
  error: undefined,
  handleRetry: mockHandleRetry,
  jobs: [],
  metadata: undefined,
};

vi.mock('../../../hooks/useCompanyLoader', () => ({
  useCompanyLoader: () => mockLoaderState,
}));

vi.mock('../../../pages/CompaniesPage/CompaniesPageHeader', () => ({
  CompaniesPageHeader: () => <div data-testid="companies-page-header" />,
}));

vi.mock('../../../pages/CompaniesPage/CompaniesPageContent', () => ({
  CompaniesPageContent: ({ isLoading }: { isLoading: boolean }) => (
    <div data-testid="companies-page-content" data-loading={String(isLoading)} />
  ),
}));

vi.mock('../../../components/modals/BucketJobsModal/BucketJobsModal', () => ({
  BucketJobsModal: () => <div data-testid="bucket-jobs-modal" />,
}));

describe('CompaniesPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockLoaderState = {
      isLoading: false,
      error: undefined,
      handleRetry: mockHandleRetry,
      jobs: [],
      metadata: undefined,
    };
  });

  it('renders header, content, and bucket modal in happy path', () => {
    renderWithProviders(<CompaniesPage />, { initialEntries: ['/companies'] });

    expect(screen.getByTestId('companies-page-header')).toBeInTheDocument();
    expect(screen.getByTestId('companies-page-content')).toBeInTheDocument();
    expect(screen.getByTestId('bucket-jobs-modal')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  describe('loading state', () => {
    it('propagates isLoading=true to CompaniesPageContent', () => {
      mockLoaderState.isLoading = true;
      renderWithProviders(<CompaniesPage />, { initialEntries: ['/companies'] });

      expect(screen.getByTestId('companies-page-content').getAttribute('data-loading')).toBe(
        'true'
      );
    });

    it('propagates globalLoading=true from ui slice even when loader is idle', () => {
      renderWithProviders(<CompaniesPage />, {
        initialEntries: ['/companies'],
        preloadedState: {
          ui: {
            graphModal: { open: false },
            globalLoading: true,
            notifications: [],
            hideAdminFeatures: false,
          },
        },
      });

      expect(screen.getByTestId('companies-page-content').getAttribute('data-loading')).toBe(
        'true'
      );
    });
  });

  describe('error state', () => {
    it('renders ErrorState with "Failed to load job data: <error>" when loader returns error', () => {
      mockLoaderState.error = 'boom';
      renderWithProviders(<CompaniesPage />, { initialEntries: ['/companies'] });

      const alert = screen.getByRole('alert');
      expect(alert).toBeInTheDocument();
      expect(alert).toHaveTextContent('Failed to load job data: boom');
    });

    it('renders a Retry button inside the ErrorState', () => {
      mockLoaderState.error = 'boom';
      renderWithProviders(<CompaniesPage />, { initialEntries: ['/companies'] });

      expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
    });

    it('invokes handleRetry when the Retry button is clicked', async () => {
      mockLoaderState.error = 'boom';
      const user = userEvent.setup();
      renderWithProviders(<CompaniesPage />, { initialEntries: ['/companies'] });

      await user.click(screen.getByRole('button', { name: /retry/i }));

      expect(mockHandleRetry).toHaveBeenCalledTimes(1);
    });

    it('does NOT render ErrorState when error is undefined', () => {
      renderWithProviders(<CompaniesPage />, { initialEntries: ['/companies'] });

      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
      expect(screen.queryByText(/Failed to load job data/i)).not.toBeInTheDocument();
    });
  });
});
