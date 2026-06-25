import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { RecentJobsMetrics } from '../../../../components/recent-jobs-page/RecentJobsMetrics/RecentJobsMetrics';

describe('RecentJobsMetrics', () => {
  it('renders the three metric labels with their values', () => {
    render(
      <RecentJobsMetrics totalJobs={123} jobsLast24Hours={45} jobsLast3Hours={7} />
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
});
