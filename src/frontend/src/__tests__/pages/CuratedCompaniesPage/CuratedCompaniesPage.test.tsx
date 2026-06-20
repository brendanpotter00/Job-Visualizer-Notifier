import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import type { CuratedCompany } from '../../../features/companies/companiesApi';

type QueryResult = {
  data: CuratedCompany[] | undefined;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  refetch: () => void;
};

let mockResult: QueryResult = {
  data: undefined,
  isLoading: false,
  isError: false,
  error: undefined,
  refetch: vi.fn(),
};

vi.mock('../../../features/companies/companiesApi', () => ({
  useListCuratedCompaniesQuery: () => mockResult,
}));

// Imported after the mock so the page uses the controllable query result.
import { CuratedCompaniesPage } from '../../../pages/CuratedCompaniesPage/CuratedCompaniesPage';

function renderPage() {
  return render(
    <BrowserRouter>
      <CuratedCompaniesPage />
    </BrowserRouter>
  );
}

describe('CuratedCompaniesPage', () => {
  it('shows a loading state while the query is in flight', () => {
    mockResult = { data: undefined, isLoading: true, isError: false, error: undefined, refetch: vi.fn() };
    renderPage();
    expect(screen.getByText('Loading companies…')).toBeInTheDocument();
  });

  it('shows an error state with a retry affordance', () => {
    mockResult = {
      data: undefined,
      isLoading: false,
      isError: true,
      error: { data: 'upstream down' },
      refetch: vi.fn(),
    };
    renderPage();
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });

  it('renders the directory grid on success', () => {
    mockResult = {
      data: [
        { id: 'stripe', displayName: 'Stripe', ats: 'greenhouse', blurb: 'Payments.', accomplishment: null },
      ],
      isLoading: false,
      isError: false,
      error: undefined,
      refetch: vi.fn(),
    };
    renderPage();
    expect(screen.getByRole('heading', { level: 1, name: 'Curated Companies' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 3, name: 'Stripe' })).toBeInTheDocument();
  });
});
