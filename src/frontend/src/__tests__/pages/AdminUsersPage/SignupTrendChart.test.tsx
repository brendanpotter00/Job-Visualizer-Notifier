import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { bucketCumulative, bucketPerDay } from '../../../pages/AdminUsersPage/lib/bucketSignups';
import { SignupTrendChart } from '../../../pages/AdminUsersPage/components/SignupTrendChart';
import { SignupsPerDayChart } from '../../../pages/AdminUsersPage/components/SignupsPerDayChart';

// Recharts pulls in DOM measurement APIs that jsdom doesn't implement.
// Match the established App.test.tsx pattern by stubbing the parts we use.
vi.mock('recharts', () => ({
  AreaChart: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="recharts-AreaChart">{children}</div>
  ),
  Area: () => null,
  BarChart: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="recharts-BarChart">{children}</div>
  ),
  Bar: () => null,
  XAxis: () => null,
  YAxis: () => null,
  CartesianGrid: () => null,
  Tooltip: () => null,
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="recharts-ResponsiveContainer">{children}</div>
  ),
}));

describe('bucketCumulative', () => {
  const realNow = Date.now;

  beforeEach(() => {
    // Pin Date.now() so the forward-fill-through-today logic is deterministic.
    Date.now = () => Date.UTC(2025, 0, 10, 12, 0, 0);
  });

  afterEach(() => {
    Date.now = realNow;
  });

  it('returns an empty series when no signups', () => {
    expect(bucketCumulative([])).toEqual([]);
  });

  it('drops invalid date strings without crashing', () => {
    const result = bucketCumulative(['not-a-date', 'still-bad']);
    expect(result).toEqual([]);
  });

  it('groups two signups on the same day into a single cumulative point of 2', () => {
    const result = bucketCumulative(['2025-01-10T03:00:00Z', '2025-01-10T22:00:00Z']);
    // First signup is on 2025-01-10; "today" (pinned) is also 2025-01-10.
    // One day in the series, cumulative count 2.
    expect(result).toHaveLength(1);
    expect(result[0].count).toBe(2);
  });

  it('emits a strictly non-decreasing cumulative series across days', () => {
    const result = bucketCumulative([
      '2025-01-05T12:00:00Z',
      '2025-01-07T08:00:00Z',
      '2025-01-07T20:00:00Z',
      '2025-01-09T00:00:00Z',
    ]);
    const counts = result.map((p) => p.count);
    for (let i = 1; i < counts.length; i += 1) {
      expect(counts[i]).toBeGreaterThanOrEqual(counts[i - 1]);
    }
    // 4 signups total → final cumulative value is 4.
    expect(counts[counts.length - 1]).toBe(4);
  });

  it('forward-fills empty days through today with a flat cumulative segment', () => {
    // First (and only) signup on 2025-01-05. "Today" pinned to 2025-01-10.
    // Expect 6 daily points (Jan 5..Jan 10 inclusive), each with count=1.
    const result = bucketCumulative(['2025-01-05T12:00:00Z']);
    expect(result).toHaveLength(6);
    for (const point of result) {
      expect(point.count).toBe(1);
    }
  });
});

describe('SignupTrendChart', () => {
  it('renders the empty-state placeholder when no signups are present', () => {
    render(<SignupTrendChart createdAts={[]} />);
    expect(screen.getByText(/no signups yet/i)).toBeInTheDocument();
    expect(screen.queryByTestId('recharts-ResponsiveContainer')).not.toBeInTheDocument();
  });

  it('renders the chart container when signups are present', () => {
    render(<SignupTrendChart createdAts={['2025-01-10T12:00:00Z']} />);
    expect(screen.getByTestId('recharts-ResponsiveContainer')).toBeInTheDocument();
    expect(screen.queryByText(/no signups yet/i)).not.toBeInTheDocument();
  });
});

describe('bucketPerDay', () => {
  const realNow = Date.now;

  beforeEach(() => {
    // Pin Date.now() so the forward-fill-through-today logic is deterministic.
    Date.now = () => Date.UTC(2025, 0, 10, 12, 0, 0);
  });

  afterEach(() => {
    Date.now = realNow;
  });

  it('returns an empty series when no signups', () => {
    expect(bucketPerDay([])).toEqual([]);
  });

  it('drops invalid date strings without crashing', () => {
    expect(bucketPerDay(['not-a-date', 'still-bad'])).toEqual([]);
  });

  it('groups two signups on the same day into a single point with count=2', () => {
    const result = bucketPerDay(['2025-01-10T03:00:00Z', '2025-01-10T22:00:00Z']);
    expect(result).toHaveLength(1);
    expect(result[0].count).toBe(2);
  });

  it('emits zero-count points for gap days between signups (no skipping)', () => {
    // Signups on Jan 5 and Jan 9. "Today" pinned to Jan 10.
    // Series should be [Jan 5=1, Jan 6=0, Jan 7=0, Jan 8=0, Jan 9=1, Jan 10=0].
    const result = bucketPerDay(['2025-01-05T12:00:00Z', '2025-01-09T18:00:00Z']);
    expect(result.map((p) => p.count)).toEqual([1, 0, 0, 0, 1, 0]);
  });

  it('forward-fills empty days through today even when latest signup was earlier', () => {
    // Only signup on Jan 5; "today" is Jan 10. Tail should be zeros, not truncated.
    const result = bucketPerDay(['2025-01-05T12:00:00Z']);
    expect(result).toHaveLength(6);
    expect(result[0].count).toBe(1);
    expect(result.slice(1).every((p) => p.count === 0)).toBe(true);
  });

  it('handles signups that span a month boundary', () => {
    Date.now = () => Date.UTC(2025, 1, 2, 12, 0, 0); // Feb 2, 2025
    const result = bucketPerDay([
      '2025-01-30T08:00:00Z',
      '2025-02-01T08:00:00Z',
      '2025-02-01T09:00:00Z',
    ]);
    // Jan 30, Jan 31, Feb 1, Feb 2 — counts: 1, 0, 2, 0.
    // Labels are intentionally not asserted: bucketCumulative/bucketPerDay
    // produce UTC-aligned `time` values but `format(new Date(time), 'MMM d')`
    // renders in the *local* timezone, so the displayed day rolls backwards
    // west of UTC. This mirrors the existing bucketCumulative tests, which
    // also assert counts only.
    expect(result).toHaveLength(4);
    expect(result.map((p) => p.count)).toEqual([1, 0, 2, 0]);
  });
});

describe('SignupsPerDayChart', () => {
  it('renders the empty-state placeholder when no signups are present', () => {
    render(<SignupsPerDayChart createdAts={[]} />);
    expect(screen.getByText(/no signups yet/i)).toBeInTheDocument();
    expect(screen.queryByTestId('recharts-BarChart')).not.toBeInTheDocument();
  });

  it('renders the BarChart container when signups are present', () => {
    render(<SignupsPerDayChart createdAts={['2025-01-10T12:00:00Z']} />);
    expect(screen.getByTestId('recharts-BarChart')).toBeInTheDocument();
    expect(screen.queryByText(/no signups yet/i)).not.toBeInTheDocument();
  });
});
