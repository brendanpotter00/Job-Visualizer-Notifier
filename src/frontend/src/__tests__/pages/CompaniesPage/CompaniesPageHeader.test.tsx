import { describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../../test/testUtils';
import { CompaniesPageHeader } from '../../../pages/CompaniesPage/CompaniesPageHeader';
import type { AppState } from '../../../features/app/appSlice';

function appState(selectedCompanyId: string): { app: AppState } {
  return {
    app: { selectedCompanyId, selectedATS: 'backend-scraper', isInitialized: true },
  };
}

describe('CompaniesPageHeader source label', () => {
  it('shows the true ATS provider as the source (not "Backend-scraper")', () => {
    // Default store selects SpaceX, which originates from Greenhouse.
    renderWithProviders(<CompaniesPageHeader />, { initialEntries: ['/companies'] });
    expect(screen.getByText('Source: Greenhouse')).toBeInTheDocument();
    expect(screen.queryByText(/Backend-scraper/i)).not.toBeInTheDocument();
  });

  it('labels a custom-scraped company "Custom Web Scraper"', () => {
    renderWithProviders(<CompaniesPageHeader />, {
      initialEntries: ['/companies'],
      preloadedState: appState('google'),
    });
    expect(screen.getByText('Source: Custom Web Scraper')).toBeInTheDocument();
  });

  it('resolves the Eightfold and Workday source labels', () => {
    const { unmount } = renderWithProviders(<CompaniesPageHeader />, {
      initialEntries: ['/companies'],
      preloadedState: appState('netflix'),
    });
    expect(screen.getByText('Source: Eightfold')).toBeInTheDocument();
    unmount();

    renderWithProviders(<CompaniesPageHeader />, {
      initialEntries: ['/companies'],
      preloadedState: appState('nvidia'),
    });
    expect(screen.getByText('Source: Workday')).toBeInTheDocument();
  });
});
