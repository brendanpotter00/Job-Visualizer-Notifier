import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { RecentJobsMetrics } from '../../../../components/recent-jobs-page/RecentJobsMetrics/RecentJobsMetrics';

describe('RecentJobsMetrics', () => {
  it('renders the recency label with its value', () => {
    render(<RecentJobsMetrics jobsLast24Hours={45} />);

    expect(screen.getByText('Past 24 Hours')).toBeInTheDocument();
    expect(screen.getByText('45')).toBeInTheDocument();
  });

  // Both removed at the owner's request (2026-09-05): "Displayed Jobs" could only
  // ever show a lower bound over the rows walked, and a second, shorter recency
  // window was one more than the question needed. Pinned so re-adding either is a
  // deliberate act — `RecentJobsMetrics`' header comment carries the reasoning.
  it('renders exactly one tile — no job count, no second recency window', () => {
    render(<RecentJobsMetrics jobsLast24Hours={45} />);

    expect(screen.queryByText('Displayed Jobs')).not.toBeInTheDocument();
    expect(screen.queryByText('Total Jobs')).not.toBeInTheDocument();
    expect(screen.queryByText('Past 3 Hours')).not.toBeInTheDocument();
  });

  it('renders an em-dash, never a zero, when the count is not known', () => {
    // A 0 over the ErrorState reads as "your filters matched nothing" next to a
    // banner that actually says the request was rejected.
    render(<RecentJobsMetrics jobsLast24Hours={null} />);

    expect(screen.getByText('—')).toBeInTheDocument();
    expect(screen.queryByText('0')).not.toBeInTheDocument();
  });

  it('marks the tile busy while a new page 1 is in flight', () => {
    render(<RecentJobsMetrics jobsLast24Hours={45} pending />);

    expect(screen.getByText('Past 24 Hours').closest('[aria-busy="true"]')).not.toBeNull();
  });

  it('does not mark the tile busy when nothing is in flight', () => {
    render(<RecentJobsMetrics jobsLast24Hours={45} />);

    expect(screen.getByText('Past 24 Hours').closest('[aria-busy="true"]')).toBeNull();
  });
});
