import { describe, it, expect, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../../test/testUtils';
import { CompaniesPageContent } from '../../../pages/CompaniesPage/CompaniesPageContent';
import { ATSConstants } from '../../../api/types';

vi.mock('../../../components/companies-page/JobPostingsChart/GraphSection', () => ({
  GraphSection: () => <div data-testid="graph-section" />,
}));

vi.mock('../../../components/companies-page/JobList/ListSection', () => ({
  ListSection: () => <div data-testid="list-section" />,
}));

describe('CompaniesPageContent', () => {
  describe('isLoading=true', () => {
    it('renders a LoadingState spinner (role=progressbar)', () => {
      renderWithProviders(<CompaniesPageContent isLoading />);

      expect(screen.getByRole('progressbar')).toBeInTheDocument();
    });

    it('renders the Workday caption when selectedATS is Workday', () => {
      renderWithProviders(<CompaniesPageContent isLoading />, {
        preloadedState: {
          app: {
            selectedCompanyId: 'x',
            selectedATS: ATSConstants.Workday,
            isInitialized: false,
          },
        },
      });

      expect(
        screen.getByText('Workday source requires more loading time to fetch all paginated jobs...')
      ).toBeInTheDocument();
    });

    it('does NOT render the Workday caption for non-Workday ATS', () => {
      renderWithProviders(<CompaniesPageContent isLoading />, {
        preloadedState: {
          app: {
            selectedCompanyId: 'x',
            selectedATS: ATSConstants.BackendScraper,
            isInitialized: false,
          },
        },
      });

      expect(screen.queryByText(/Workday source requires/i)).not.toBeInTheDocument();
    });

    it('does NOT render GraphSection or ListSection while loading', () => {
      renderWithProviders(<CompaniesPageContent isLoading />);

      expect(screen.queryByTestId('graph-section')).not.toBeInTheDocument();
      expect(screen.queryByTestId('list-section')).not.toBeInTheDocument();
    });
  });

  describe('isLoading=false', () => {
    it('renders GraphSection and ListSection', () => {
      renderWithProviders(<CompaniesPageContent isLoading={false} />);

      expect(screen.getByTestId('graph-section')).toBeInTheDocument();
      expect(screen.getByTestId('list-section')).toBeInTheDocument();
    });

    it('does NOT render a spinner', () => {
      renderWithProviders(<CompaniesPageContent isLoading={false} />);

      expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
    });
  });
});
