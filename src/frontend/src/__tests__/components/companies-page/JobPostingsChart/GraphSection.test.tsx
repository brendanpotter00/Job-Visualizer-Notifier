import { describe, it, expect, vi } from 'vitest';
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
