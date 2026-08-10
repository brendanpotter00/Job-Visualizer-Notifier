import { describe, it, expect } from 'vitest';
import {
  buildParticlesConfig,
  countJobsPostedToday,
  MIN_JOB_DOTS,
} from '../../../pages/AdminLandingPrototypesPage/prototypes/DriftPrototype/particlesConfig';

const NOW = new Date('2026-08-09T18:00:00Z').getTime();
const HOUR = 3_600_000;

function jobAt(agoMs: number): { firstSeenAt: string } {
  return { firstSeenAt: new Date(NOW - agoMs).toISOString() };
}

describe('countJobsPostedToday', () => {
  it('counts only jobs first seen within the last 24h of `now`', () => {
    const jobs = [jobAt(1 * HOUR), jobAt(23 * HOUR), jobAt(25 * HOUR), jobAt(72 * HOUR)];
    expect(countJobsPostedToday(jobs, NOW)).toBe(2);
  });

  it('includes the exact 24h boundary and returns 0 for empty input', () => {
    expect(countJobsPostedToday([jobAt(24 * HOUR)], NOW)).toBe(1);
    expect(countJobsPostedToday([], NOW)).toBe(0);
  });
});

describe('buildParticlesConfig', () => {
  it('one dot per job posted today drives the data layer', () => {
    expect(
      buildParticlesConfig({ jobsPostedToday: 30, constrained: false }).jobs.count
    ).toBe(30);
  });

  it('floors the data layer at MIN_JOB_DOTS so quiet weekends never look empty', () => {
    expect(
      buildParticlesConfig({ jobsPostedToday: 3, constrained: false }).jobs.count
    ).toBe(MIN_JOB_DOTS);
    expect(
      buildParticlesConfig({ jobsPostedToday: 0, constrained: true }).jobs.count
    ).toBe(MIN_JOB_DOTS);
  });

  it('constrained tier thins the ambient layer and shrinks the job dots', () => {
    const full = buildParticlesConfig({ jobsPostedToday: 20, constrained: false });
    const constrained = buildParticlesConfig({ jobsPostedToday: 20, constrained: true });
    expect(constrained.ambient.count).toBeLessThan(full.ambient.count);
    expect(constrained.jobs.size).toBeLessThan(full.jobs.size);
    expect(constrained.jobs.count).toBe(full.jobs.count);
  });

  it('stays restrained: every layer at low opacity (≤10% visual weight)', () => {
    const config = buildParticlesConfig({ jobsPostedToday: 20, constrained: false });
    expect(config.jobs.opacity).toBeLessThanOrEqual(0.35);
    expect(config.ambient.opacity).toBeLessThanOrEqual(0.35);
  });

  it('encodes parallax: the near data layer is bigger, faster, and shallower', () => {
    const config = buildParticlesConfig({ jobsPostedToday: 20, constrained: false });
    expect(config.jobs.size).toBeGreaterThan(config.ambient.size);
    expect(config.jobs.speed).toBeGreaterThan(config.ambient.speed);
    expect(config.jobs.scale[2]).toBeLessThan(config.ambient.scale[2]);
  });
});
