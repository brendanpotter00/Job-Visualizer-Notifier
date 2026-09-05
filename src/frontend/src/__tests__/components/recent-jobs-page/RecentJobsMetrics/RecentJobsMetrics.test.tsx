import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { RecentJobsMetrics } from '../../../../components/recent-jobs-page/RecentJobsMetrics/RecentJobsMetrics';

describe('RecentJobsMetrics', () => {
  it('renders the three metric labels with their values', () => {
    render(
      <RecentJobsMetrics
        totalJobs={{ kind: 'exact', value: 123 }}
        jobsLast24Hours={45}
        jobsLast3Hours={7}
      />
    );

    // Renamed label is the key thing under test.
    expect(screen.getByText('Displayed Jobs')).toBeInTheDocument();
    expect(screen.getByText('Past 24 Hours')).toBeInTheDocument();
    expect(screen.getByText('Past 3 Hours')).toBeInTheDocument();

    // Values render (distinct numbers avoid ambiguous matches).
    expect(screen.getByText('123')).toBeInTheDocument();
    expect(screen.getByText('45')).toBeInTheDocument();
    expect(screen.getByText('7')).toBeInTheDocument();
  });

  // The bug this tile shipped with: the server defers the exact total (#277) and
  // sends `null`, so the ONLY state a real signed-in search ever reached was the
  // em-dash — a permanently blank number over a list full of jobs.
  it('shows a lower bound rather than a blank when the exact total is deferred', () => {
    render(
      <RecentJobsMetrics
        totalJobs={{ kind: 'atLeast', value: 50 }}
        jobsLast24Hours={309}
        jobsLast3Hours={9}
      />
    );

    expect(screen.getByText('50+')).toBeInTheDocument();
    expect(screen.queryByText('—')).not.toBeInTheDocument();
  });

  it('renders an em-dash only when nothing has measured the set', () => {
    render(
      <RecentJobsMetrics
        totalJobs={{ kind: 'unknown' }}
        jobsLast24Hours={null}
        jobsLast3Hours={null}
      />
    );

    // All three, and never a zero: "0 Displayed Jobs" over an error banner reads
    // as "your filters matched nothing".
    expect(screen.getAllByText('—')).toHaveLength(3);
    expect(screen.queryByText('0')).not.toBeInTheDocument();
  });
});
