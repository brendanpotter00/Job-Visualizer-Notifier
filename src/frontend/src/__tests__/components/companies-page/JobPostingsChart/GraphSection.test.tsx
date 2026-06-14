import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../../../../test/testUtils';
import { GraphSection } from '../../../../components/companies-page/JobPostingsChart/GraphSection';

// The chart and the filters are exercised by their own tests; here we mock them
// to stubs so this suite focuses purely on the collapse/expand behavior of the
// section wrapper.
vi.mock('../../../../components/companies-page/JobPostingsChart/JobPostingsChart', () => ({
  JobPostingsChart: () => <div data-testid="job-postings-chart" />,
}));

vi.mock('../../../../components/companies-page/GraphFilters', () => ({
  GraphFilters: () => <div data-testid="graph-filters" />,
}));

// Seeding a real RTK Query *error* cache entry has no public util, so we mock
// `selectCurrentCompanyError` through a mutable holder. All other selectors keep
// their real implementations (importOriginal), and `ErrorDisplay` stays UNMOCKED
// so the error text it renders is real. The happy-path tests leave the holder at
// `undefined`, exercising the real store exactly as before.
let mockCurrentCompanyError: string | undefined;
vi.mock('../../../../features/jobs/jobsSelectors', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../../features/jobs/jobsSelectors')>();
  return {
    ...actual,
    selectCurrentCompanyError: () => mockCurrentCompanyError,
  };
});

beforeEach(() => {
  mockCurrentCompanyError = undefined;
});

const getToggle = () => screen.getByRole('button', { name: /job posting timeline/i });

describe('GraphSection collapse', () => {
  it('renders the chart expanded by default, with the toggle marked expanded', () => {
    renderWithProviders(<GraphSection />);

    expect(getToggle()).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByTestId('job-postings-chart')).toBeInTheDocument();
    expect(screen.getByTestId('graph-filters')).toBeInTheDocument();
  });

  it('exposes the heading inside the toggle so the section keeps its h2 outline', () => {
    renderWithProviders(<GraphSection />);

    expect(
      screen.getByRole('heading', { level: 2, name: /job posting timeline/i })
    ).toBeInTheDocument();
  });

  it('collapses only the chart when toggled — filters stay visible', async () => {
    renderWithProviders(<GraphSection />);

    fireEvent.click(getToggle());

    // aria-expanded flips immediately; the chart unmounts after the collapse
    // transition (unmountOnExit).
    expect(getToggle()).toHaveAttribute('aria-expanded', 'false');
    await waitFor(() =>
      expect(screen.queryByTestId('job-postings-chart')).not.toBeInTheDocument()
    );

    // The filters are the single source of truth for the list, so they remain.
    expect(screen.getByTestId('graph-filters')).toBeInTheDocument();
  });

  it('re-expands the chart when toggled again', async () => {
    renderWithProviders(<GraphSection />);

    fireEvent.click(getToggle());
    await waitFor(() =>
      expect(screen.queryByTestId('job-postings-chart')).not.toBeInTheDocument()
    );

    fireEvent.click(getToggle());

    expect(getToggle()).toHaveAttribute('aria-expanded', 'true');
    expect(await screen.findByTestId('job-postings-chart')).toBeInTheDocument();
  });
});

describe('GraphSection error branch', () => {
  // The error branch now lives INSIDE the <Collapse>, so it must render while
  // expanded, disappear when collapsed (unmountOnExit), and come back when
  // re-expanded — same lifecycle as the chart it replaces.
  it('renders the ErrorDisplay (not the chart) while expanded when an error is present', () => {
    mockCurrentCompanyError = 'Boom: feed unreachable';
    renderWithProviders(<GraphSection />);

    expect(getToggle()).toHaveAttribute('aria-expanded', 'true');
    // Real ErrorDisplay (unmocked) renders the title and the message.
    expect(screen.getByText('Failed to Load Chart Data')).toBeInTheDocument();
    expect(screen.getByText('Boom: feed unreachable')).toBeInTheDocument();
    // The chart stub must NOT render — the error replaces it.
    expect(screen.queryByTestId('job-postings-chart')).not.toBeInTheDocument();
    // Filters remain regardless of the error.
    expect(screen.getByTestId('graph-filters')).toBeInTheDocument();
  });

  it('hides the error region when collapsed and brings it back on re-expand; filters stay throughout', async () => {
    mockCurrentCompanyError = 'Boom: feed unreachable';
    renderWithProviders(<GraphSection />);

    // Visible by default.
    expect(screen.getByText('Failed to Load Chart Data')).toBeInTheDocument();

    // Collapse: unmountOnExit tears down the error region.
    fireEvent.click(getToggle());
    expect(getToggle()).toHaveAttribute('aria-expanded', 'false');
    await waitFor(() =>
      expect(screen.queryByText('Failed to Load Chart Data')).not.toBeInTheDocument()
    );
    // Filters survive the collapse (single source of truth for the list).
    expect(screen.getByTestId('graph-filters')).toBeInTheDocument();

    // Re-expand: the error region comes back.
    fireEvent.click(getToggle());
    expect(getToggle()).toHaveAttribute('aria-expanded', 'true');
    expect(await screen.findByText('Failed to Load Chart Data')).toBeInTheDocument();
    expect(screen.getByText('Boom: feed unreachable')).toBeInTheDocument();
    expect(screen.queryByTestId('job-postings-chart')).not.toBeInTheDocument();
  });
});
