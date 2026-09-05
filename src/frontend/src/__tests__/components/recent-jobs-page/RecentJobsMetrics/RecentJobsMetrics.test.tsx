import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { RecentJobsMetrics } from '../../../../components/recent-jobs-page/RecentJobsMetrics/RecentJobsMetrics';

describe('RecentJobsMetrics', () => {
  it('renders the two recency labels with their values', () => {
    render(<RecentJobsMetrics jobsLast24Hours={45} jobsLast3Hours={7} />);

    expect(screen.getByText('Past 24 Hours')).toBeInTheDocument();
    expect(screen.getByText('Past 3 Hours')).toBeInTheDocument();

    // Distinct numbers avoid ambiguous matches.
    expect(screen.getByText('45')).toBeInTheDocument();
    expect(screen.getByText('7')).toBeInTheDocument();
  });

  // Removed at the owner's request: the server defers the exact total (#277), so
  // the only honest thing this tile could show was a lower bound over the rows
  // walked ("50+" above fifty cards) — a number that restates the list under it.
  // Pinned so re-adding one is a deliberate act rather than an accident.
  it('shows no job-count tile at all', () => {
    render(<RecentJobsMetrics jobsLast24Hours={45} jobsLast3Hours={7} />);

    expect(screen.queryByText('Displayed Jobs')).not.toBeInTheDocument();
    expect(screen.queryByText('Total Jobs')).not.toBeInTheDocument();
  });

  it('renders an em-dash, never a zero, when a count is not known', () => {
    // A 0 over the ErrorState reads as "your filters matched nothing" next to a
    // banner that actually says the request was rejected.
    render(<RecentJobsMetrics jobsLast24Hours={null} jobsLast3Hours={null} />);

    expect(screen.getAllByText('—')).toHaveLength(2);
    expect(screen.queryByText('0')).not.toBeInTheDocument();
  });

  it('marks the tiles busy while a new page 1 is in flight', () => {
    render(<RecentJobsMetrics jobsLast24Hours={45} jobsLast3Hours={7} pending />);

    expect(screen.getByText('Past 24 Hours').closest('[aria-busy="true"]')).not.toBeNull();
  });
});
