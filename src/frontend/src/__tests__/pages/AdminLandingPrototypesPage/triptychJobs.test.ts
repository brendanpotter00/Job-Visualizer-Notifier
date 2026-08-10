import { describe, it, expect } from 'vitest';
import {
  DEFAULT_MAX_PER_SLOT,
  selectTriptychSlots,
  TRIPTYCH_SLOT_IDS,
} from '../../../pages/AdminLandingPrototypesPage/sections/triptychJobs';
import {
  buildMockJobs,
  buildSparseMockJobs,
} from '../../../pages/AdminLandingPrototypesPage/mockData';
import { COMPANY_CATEGORIES } from '../../../pages/AdminLandingPrototypesPage/companyCategories';
import type { Job } from '../../../types';

const NOW = new Date('2026-08-09T18:00:00Z').getTime();
const HOUR = 3_600_000;
const DAY = 24 * HOUR;

const BIG_TECH_IDS = COMPANY_CATEGORIES.find((c) => c.id === 'big_tech')!.companyIds;

interface StubOverrides {
  level?: string;
  id?: string;
}

function stubJob(company: string, hoursAgo: number, overrides: StubOverrides = {}): Job {
  const firstSeenAt = new Date(NOW - hoursAgo * HOUR).toISOString();
  return {
    id: overrides.id ?? `${company}-${hoursAgo}`,
    source: 'backend-scraper',
    company,
    title: `Engineer at ${company}`,
    createdAt: firstSeenAt,
    firstSeenAt,
    url: 'https://example.test',
    level: overrides.level,
    raw: null,
  };
}

function slotById(jobs: Job[], id: (typeof TRIPTYCH_SLOT_IDS)[number], now = NOW) {
  return selectTriptychSlots(jobs, now).find((slot) => slot.id === id)!;
}

describe('selectTriptychSlots', () => {
  it('always returns the three slots in render order', () => {
    const slots = selectTriptychSlots(buildMockJobs(NOW), NOW);
    expect(slots.map((s) => s.id)).toEqual([...TRIPTYCH_SLOT_IDS]);
    expect(slots).toHaveLength(3);
  });

  it('rich fixture: every slot has jobs and no job appears in two pools', () => {
    const slots = selectTriptychSlots(buildMockJobs(NOW), NOW);
    for (const slot of slots) {
      expect(slot.jobs.length, `${slot.id} should not be empty on the rich fixture`).toBeGreaterThan(
        0
      );
    }
    const ids = slots.flatMap((slot) => slot.jobs.map((job) => job.id));
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('claims in priority order: early-career > last 24h > big tech', () => {
    // One job that qualifies for ALL THREE slots: a fresh big-tech internship.
    const jobs = [
      stubJob('google', 1, { level: 'intern', id: 'contested' }),
      stubJob('anthropic', 2),
      stubJob('apple', 30),
    ];
    const slots = selectTriptychSlots(jobs, NOW);
    expect(slots[0].jobs.map((j) => j.id)).toEqual(['contested']);
    expect(slots[1].jobs.map((j) => j.id)).toEqual(['anthropic-2']);
    expect(slots[2].jobs.map((j) => j.id)).toEqual(['apple-30']);
  });

  it('a job the earlier slot could not fit stays available to the later one', () => {
    // Five fresh big-tech internships: the first slot caps at four, and the
    // fifth is NOT burned — the big-tech slot picks it up.
    const jobs = [1, 2, 3, 4, 5].map((h) =>
      stubJob('google', h, { level: 'intern', id: `intern-${h}` })
    );
    const slots = selectTriptychSlots(jobs, NOW);
    expect(slots[0].jobs).toHaveLength(DEFAULT_MAX_PER_SLOT);
    // The overflow lands in the next slot that claims it (last 24h).
    expect(slots[1].jobs.map((j) => j.id)).toEqual(['intern-5']);
    expect(slots[2].jobs).toHaveLength(0);
  });

  it('every pool is newest-first and capped at maxPerSlot', () => {
    const slots = selectTriptychSlots(buildMockJobs(NOW), NOW);
    for (const slot of slots) {
      expect(slot.jobs.length).toBeLessThanOrEqual(DEFAULT_MAX_PER_SLOT);
      for (let i = 1; i < slot.jobs.length; i += 1) {
        expect(new Date(slot.jobs[i - 1].firstSeenAt).getTime()).toBeGreaterThanOrEqual(
          new Date(slot.jobs[i].firstSeenAt).getTime()
        );
      }
    }
  });

  it('honors an explicit maxPerSlot', () => {
    const slots = selectTriptychSlots(buildMockJobs(NOW), NOW, 2);
    for (const slot of slots) {
      expect(slot.jobs.length).toBeLessThanOrEqual(2);
    }
  });

  describe('early-career slot', () => {
    it('pools interns AND new grads, labeling itself for what it actually holds', () => {
      const mixed = slotById(
        [stubJob('stripe', 1, { level: 'new_grad' }), stubJob('figma', 2, { level: 'intern' })],
        'early_career'
      );
      expect(mixed.label).toBe('Internships & new grad');
      expect(mixed.jobs.map((j) => j.level)).toEqual(['new_grad', 'intern']);
    });

    it('says "internships" only when the pool is all interns', () => {
      const slot = slotById(
        [stubJob('figma', 2, { level: 'intern' }), stubJob('google', 3, { level: 'mid' })],
        'early_career'
      );
      expect(slot.label).toBe('Newest internships');
    });

    it('falls back to new-grad roles — and says so — when no internship exists', () => {
      const slot = slotById(
        [stubJob('stripe', 1, { level: 'new_grad' }), stubJob('google', 3, { level: 'senior' })],
        'early_career'
      );
      expect(slot.label).toBe('Newest new-grad roles');
      expect(slot.jobs.map((j) => j.id)).toEqual(['stripe-1']);
    });

    it('ignores every other level, and jobs with no level at all', () => {
      const slot = slotById(
        [stubJob('google', 1), stubJob('apple', 2, { level: 'entry' }), stubJob('spacex', 3, { level: 'senior' })],
        'early_career'
      );
      expect(slot.jobs).toHaveLength(0);
      expect(slot.label).toBe('Internships & new grad');
      expect(slot.emptyText).toBe('No internships or new-grad roles this week.');
    });
  });

  describe('last-24h slot', () => {
    it('includes the job sitting exactly on the 24h boundary and excludes the one past it', () => {
      const onBoundary: Job = {
        ...stubJob('anthropic', 0, { id: 'on-boundary' }),
        firstSeenAt: new Date(NOW - DAY).toISOString(),
      };
      const justPast: Job = {
        ...stubJob('anthropic', 0, { id: 'just-past' }),
        firstSeenAt: new Date(NOW - DAY - 1).toISOString(),
      };
      const slot = slotById([onBoundary, justPast], 'last_24h');
      expect(slot.jobs.map((j) => j.id)).toEqual(['on-boundary']);
      expect(slot.label).toBe('Posted in the last 24 hours');
    });

    it('every job it shows really is under 24 hours old', () => {
      const slot = slotById(buildMockJobs(NOW), 'last_24h');
      for (const job of slot.jobs) {
        expect(NOW - new Date(job.firstSeenAt).getTime()).toBeLessThanOrEqual(DAY);
      }
    });
  });

  describe('big-tech slot', () => {
    it('only shows companies from the big_tech category of COMPANY_CATEGORIES', () => {
      const slot = slotById(buildMockJobs(NOW), 'big_tech');
      expect(slot.jobs.length).toBeGreaterThan(0);
      for (const job of slot.jobs) {
        expect(BIG_TECH_IDS).toContain(job.company);
      }
    });

    it('excludes companies outside that roster', () => {
      const slot = slotById(
        [stubJob('spacex', 30), stubJob('anthropic', 40), stubJob('netflix', 50)],
        'big_tech'
      );
      expect(slot.jobs.map((j) => j.company)).toEqual(['netflix']);
    });
  });

  describe('freshness bound', () => {
    it('drops everything older than 7 days from every slot', () => {
      const stale = [
        stubJob('google', 8 * 24, { level: 'intern' }),
        stubJob('anthropic', 10 * 24),
        stubJob('apple', 30 * 24),
      ];
      const slots = selectTriptychSlots(stale, NOW);
      expect(slots.flatMap((s) => s.jobs)).toHaveLength(0);
    });
  });

  describe('empty pools', () => {
    it('sparse fixture: the early-career slot goes quiet, the others still fill', () => {
      const slots = selectTriptychSlots(buildSparseMockJobs(NOW), NOW);
      const [earlyCareer, lastDay, bigTech] = slots;
      expect(earlyCareer.jobs).toHaveLength(0);
      expect(earlyCareer.emptyText).toBeTruthy();
      expect(lastDay.jobs.length).toBeGreaterThan(0);
      expect(bigTech.jobs.length).toBeGreaterThan(0);
    });

    it('no jobs at all: three empty slots, each with honest copy', () => {
      const slots = selectTriptychSlots([], NOW);
      for (const slot of slots) {
        expect(slot.jobs).toHaveLength(0);
        expect(slot.emptyText.length).toBeGreaterThan(0);
        expect(slot.label.length).toBeGreaterThan(0);
      }
    });
  });
});
