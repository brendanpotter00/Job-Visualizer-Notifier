import { describe, it, expect, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../../test/testUtils';
import { CompaniesPageContent } from '../../../pages/CompaniesPage/CompaniesPageContent';

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

    it('does NOT render the legacy Workday caption (Workday rows are now backend-scraper)', () => {
      // After the Workday backend migration, Workday rows fetch from
      // `/api/jobs` instead of paginating from the browser — the old
      // "paginated jobs" caption no longer applies. This test pins
      // that the caption is gone for ANY loading state.
      renderWithProviders(<CompaniesPageContent isLoading />);

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
