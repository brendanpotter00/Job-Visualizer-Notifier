import { describe, it, expect } from 'vitest';
import { computeActivityStats } from '../../../pages/AdminLandingPrototypesPage/sections/activityStats';
import { buildMockJobs, buildSparseMockJobs, MOCK_STATS } from '../../../pages/AdminLandingPrototypesPage/mockData';

const NOW = new Date('2026-08-09T18:00:00Z').getTime();

describe('computeActivityStats', () => {
  it('rich data → event-shaped 24h stats plus the median claim', () => {
    const stats = computeActivityStats(buildMockJobs(NOW), MOCK_STATS, NOW);
    expect(stats).toHaveLength(3);
    expect(stats[0].label).toMatch(/posted by .+ in the past 24 hours/);
    expect(stats[1].label).toMatch(/tracked in the past 24 hours/);
    expect(stats[2].value).toBe(`~${MOCK_STATS.medianMinutesToSurface} min`);
    expect(stats[2].label).toMatch(/median/);
  });

  it('quiet day (sparse fixture) → honestly widens the window to the past week', () => {
    const stats = computeActivityStats(buildSparseMockJobs(NOW), MOCK_STATS, NOW);
    expect(stats.some((s) => s.label.includes('in the past week'))).toBe(true);
    expect(stats.every((s) => !s.label.includes('past 24 hours'))).toBe(true);
  });

  it('no jobs at all → still renders the median claim without a top-company stat', () => {
    const stats = computeActivityStats([], MOCK_STATS, NOW);
    expect(stats).toHaveLength(2);
    expect(stats[0].value).toBe('0');
    expect(stats[1].value).toBe(`~${MOCK_STATS.medianMinutesToSurface} min`);
  });
});
