import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../../test/testUtils';
import { AddCompanyByUrlSection } from '../../../components/saved-filters/AddCompanyByUrlSection';
import type { AddCompanyResult, SubmissionResult } from '../../../features/userCompanies/userCompaniesApi';

// Authenticated so the section renders (it self-gates on auth).
const mockAuth = { isAuthenticated: true };
vi.mock('../../../features/auth/useAuth', () => ({
  useAuth: () => mockAuth,
}));

// Test-controlled mutation / lazy-query responses.
let addResult: AddCompanyResult;
let submissionResults: SubmissionResult[];
let submissionCallIndex = 0;

const addCompanyFn = vi.fn(() => ({ unwrap: () => Promise.resolve(addResult) }));
const fetchSubmissionFn = vi.fn(() => ({
  unwrap: () =>
    Promise.resolve(submissionResults[Math.min(submissionCallIndex++, submissionResults.length - 1)]),
}));

vi.mock('../../../features/userCompanies/userCompaniesApi', async (importOriginal) => {
  const actual =
    await importOriginal<typeof import('../../../features/userCompanies/userCompaniesApi')>();
  return {
    ...actual,
    useAddCompanyMutation: () => [addCompanyFn, { isLoading: false }],
    useLazyGetSubmissionQuery: () => [fetchSubmissionFn, {}],
  };
});

const companyDto = (name: string) => ({
  id: name.toLowerCase(),
  name,
  jobsUrl: null,
  sourceAts: 'custom_json',
});

describe('AddCompanyByUrlSection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    submissionCallIndex = 0;
    mockAuth.isAuthenticated = true;
  });

  it('does not render for anonymous users', () => {
    mockAuth.isAuthenticated = false;
    const { container } = renderWithProviders(<AddCompanyByUrlSection />);
    expect(container).toBeEmptyDOMElement();
  });

  it('submits the URL and shows a success message on a synchronous add', async () => {
    addResult = { status: 'added', company: companyDto('Acme') };
    const user = userEvent.setup();
    renderWithProviders(<AddCompanyByUrlSection />);

    await user.type(screen.getByLabelText('Careers page URL'), 'https://jobs.acme.com');
    await user.click(screen.getByRole('button', { name: /add/i }));

    expect(await screen.findByText('Acme added.')).toBeInTheDocument();
    expect(addCompanyFn).toHaveBeenCalledWith({ url: 'https://jobs.acme.com' });
  });

  it('reports an already-tracked company distinctly', async () => {
    addResult = { status: 'alreadyTracked', company: companyDto('Acme') };
    const user = userEvent.setup();
    renderWithProviders(<AddCompanyByUrlSection />);

    await user.type(screen.getByLabelText('Careers page URL'), 'https://jobs.acme.com');
    await user.click(screen.getByRole('button', { name: /add/i }));

    expect(await screen.findByText('Acme is already tracked.')).toBeInTheDocument();
  });

  it('polls a pending submission and shows success when it resolves', async () => {
    addResult = { status: 'pending', submissionId: 'sub-1' };
    submissionResults = [
      { id: 'sub-1', status: 'succeeded', company: companyDto('Acme'), error: null },
    ];
    const user = userEvent.setup();
    renderWithProviders(<AddCompanyByUrlSection />);

    await user.type(screen.getByLabelText('Careers page URL'), 'https://jobs.acme.com');
    await user.click(screen.getByRole('button', { name: /add/i }));

    // Progress state while the backend analyzes the site.
    expect(await screen.findByText('Analyzing site…')).toBeInTheDocument();

    // The poll waits one interval (~2.5s) before the first status check.
    expect(await screen.findByText('Acme added.', {}, { timeout: 5000 })).toBeInTheDocument();
    expect(fetchSubmissionFn).toHaveBeenCalledWith('sub-1');
  });

  it('surfaces a failed submission error', async () => {
    addResult = { status: 'pending', submissionId: 'sub-2' };
    submissionResults = [
      { id: 'sub-2', status: 'failed', company: null, error: 'Unsupported site' },
    ];
    const user = userEvent.setup();
    renderWithProviders(<AddCompanyByUrlSection />);

    await user.type(screen.getByLabelText('Careers page URL'), 'https://bad.example.com');
    await user.click(screen.getByRole('button', { name: /add/i }));

    expect(await screen.findByText('Unsupported site', {}, { timeout: 5000 })).toBeInTheDocument();
  });
});
