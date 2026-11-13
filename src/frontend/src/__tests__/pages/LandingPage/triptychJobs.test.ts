import { describe, it, expect } from 'vitest';
import {
  BIG_TECH_WINDOWS,
  EARLY_CAREER_WINDOWS,
  JOBS_PER_SLOT,
  LATEST_WINDOWS,
  selectTriptychSlots,
  TRIPTYCH_REQUESTS,
  TRIPTYCH_SLOT_IDS,
  type TriptychSlots,
} from '../../../pages/LandingPage/sections/triptychJobs';
import { COMPANY_CATEGORIES } from '../../../pages/LandingPage/companyCategories';
import { mulberry32 } from '../../../pages/LandingPage/prototypes/shared3d/mulberry32';
import type { Job } from '../../../types';
import {
  buildHolidayLandingJobs,
  buildRichLandingJobs,
  LANDING_NOW,
  simulateBatchRequest,
  SOFTWARE_ENGINEERING,
} from './landingJobFixtures';

const NOW = LANDING_NOW;
const HOUR = 3_600_000;

const BIG_TECH_IDS = COMPANY_CATEGORIES.find((c) => c.id === 'big_tech')!.companyIds;
const NOT_BIG_TECH = ['anthropic', 'openai', 'stripe', 'spacex', 'databricks', 'ramp'];

interface StubOverrides {
  level?: string | null;
  category?: string | null;
  id?: string;
}

function stubJobAt(company: string, ageMs: number, overrides: StubOverrides = {}): Job {
  const firstSeenAt = new Date(NOW - ageMs).toISOString();
  return {
    id: overrides.id ?? `${company}-${ageMs}`,
    source: 'backend-scraper',
    company,
    title: `Engineer at ${company}`,
    createdAt: firstSeenAt,
    firstSeenAt,
    url: 'https://example.test',
    level: overrides.level === undefined ? 'mid' : overrides.level,
    category: overrides.category === undefined ? SOFTWARE_ENGINEERING : overrides.category,
    raw: null,
  };
}

function stubJob(company: string, hoursAgo: number, overrides: StubOverrides = {}): Job {
  return stubJobAt(company, hoursAgo * HOUR, overrides);
}

function slotById(jobs: Job[], id: (typeof TRIPTYCH_SLOT_IDS)[number], perSlot?: number) {
  return selectTriptychSlots(jobs, NOW, perSlot).find((slot) => slot.id === id)!;
}

function ids(jobs: Job[]): string[] {
  return jobs.map((job) => job.id);
}

function latestFillers(count: number, newestHoursAgo = 0.1): Job[] {
  return Array.from({ length: count }, (_, i) =>
    stubJob(NOT_BIG_TECH[i % NOT_BIG_TECH.length], newestHoursAgo + i * 0.01, {
      id: `filler-${i}`,
    })
  );
}

describe('selectTriptychSlots', () => {
  it('always returns the three slots in render order', () => {
    const slots = selectTriptychSlots(buildRichLandingJobs(NOW), NOW);
    expect(slots.map((s) => s.id)).toEqual([...TRIPTYCH_SLOT_IDS]);
    expect(slots).toHaveLength(3);
  });

  it('shows five jobs per slot by default', () => {
    expect(JOBS_PER_SLOT).toBe(5);
  });

  it('rich fixture: every slot fills to exactly five at its base window, disjoint', () => {
    const slots = selectTriptychSlots(buildRichLandingJobs(NOW), NOW);
    for (const slot of slots) {
      expect(slot.jobs, `${slot.id} should fill on the rich fixture`).toHaveLength(JOBS_PER_SLOT);
    }
    expect(slots.map((slot) => slot.windowHours)).toEqual([
      EARLY_CAREER_WINDOWS[0].hours,
      LATEST_WINDOWS[0].hours,
      BIG_TECH_WINDOWS[0].hours,
    ]);
    expect(slots.map((slot) => slot.label)).toEqual([
      'Internships & new grad',
      'Last 24 hours',
      'Big tech',
    ]);
    const all = slots.flatMap((slot) => ids(slot.jobs));
    expect(new Set(all).size).toBe(all.length);
  });

  it('claims in priority order: early-career > latest > big tech', () => {
    const jobs = [
      stubJob('google', 1, { level: 'intern', id: 'contested' }),
      stubJob('anthropic', 2, { id: 'latest' }),
      stubJob('apple', 30, { id: 'big' }),
    ];
    const slots = selectTriptychSlots(jobs, NOW, 1);
    expect(ids(slots[0].jobs)).toEqual(['contested']);
    expect(ids(slots[1].jobs)).toEqual(['latest']);
    expect(ids(slots[2].jobs)).toEqual(['big']);
  });

  it('a job the earlier slot could not fit stays available to the later one', () => {
    const jobs = [1, 2, 3, 4, 5, 6].map((h) =>
      stubJob('google', h, { level: 'intern', id: `intern-${h}` })
    );
    const slots = selectTriptychSlots(jobs, NOW);
    expect(ids(slots[0].jobs)).toEqual([
      'intern-1',
      'intern-2',
      'intern-3',
      'intern-4',
      'intern-5',
    ]);
    expect(ids(slots[1].jobs)).toEqual(['intern-6']);
    expect(slots[2].jobs).toHaveLength(0);
  });

  it('every pool is newest-first and capped at the per-slot count', () => {
    const slots = selectTriptychSlots(buildRichLandingJobs(NOW), NOW);
    for (const slot of slots) {
      expect(slot.jobs.length).toBeLessThanOrEqual(JOBS_PER_SLOT);
      for (let i = 1; i < slot.jobs.length; i += 1) {
        expect(Date.parse(slot.jobs[i - 1].firstSeenAt)).toBeGreaterThanOrEqual(
          Date.parse(slot.jobs[i].firstSeenAt)
        );
      }
    }
  });

  it('honors an explicit per-slot count', () => {
    const slots = selectTriptychSlots(buildRichLandingJobs(NOW), NOW, 2);
    for (const slot of slots) {
      expect(slot.jobs).toHaveLength(2);
    }
  });

  describe('software engineering only', () => {
    it('never shows a job outside the software-engineering category', () => {
      const slots = selectTriptychSlots(buildRichLandingJobs(NOW), NOW);
      for (const job of slots.flatMap((slot) => slot.jobs)) {
        expect(job.category).toBe(SOFTWARE_ENGINEERING);
      }
    });

    it('a corpus with no software-engineering jobs leaves every slot empty', () => {
      const jobs = [
        stubJob('google', 1, { level: 'intern', category: 'data_scientist' }),
        stubJob('stripe', 2, { category: 'product_manager' }),
        stubJob('apple', 3, { category: null, level: null }),
      ];
      for (const slot of selectTriptychSlots(jobs, NOW)) {
        expect(slot.jobs).toHaveLength(0);
      }
    });
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
      expect(slot.label).toBe('Internships');
    });

    it('falls back to new-grad roles, and says so, when no internship exists', () => {
      const slot = slotById(
        [
          stubJob('stripe', 1, { level: 'new_grad', id: 'new-grad' }),
          stubJob('google', 3, { level: 'senior' }),
        ],
        'early_career'
      );
      expect(slot.label).toBe('New grad');
      expect(ids(slot.jobs)).toEqual(['new-grad']);
    });

    it('ignores every other level, and jobs with no level at all', () => {
      const slot = slotById(
        [
          stubJob('google', 1, { level: null }),
          stubJob('apple', 2, { level: 'entry' }),
          stubJob('spacex', 3, { level: 'senior' }),
        ],
        'early_career'
      );
      expect(slot.jobs).toHaveLength(0);
      expect(slot.label).toBe('Internships & new grad');
      expect(slot.emptyText).toBe('None in the last 60 days.');
    });
  });

  describe('big-tech slot', () => {
    it('only shows companies from the big_tech category of COMPANY_CATEGORIES', () => {
      const slot = slotById(buildRichLandingJobs(NOW), 'big_tech');
      expect(slot.jobs.length).toBeGreaterThan(0);
      for (const job of slot.jobs) {
        expect(BIG_TECH_IDS).toContain(job.company);
      }
    });

    it('excludes companies outside that roster', () => {
      const jobs = [
        ...latestFillers(5),
        stubJob('spacex', 30),
        stubJob('anthropic', 40),
        stubJob('netflix', 50),
      ];
      expect(slotById(jobs, 'big_tech').jobs.map((j) => j.company)).toEqual(['netflix']);
    });
  });

  describe('latest slot widening', () => {
    it.each([
      [23, 'Last 24 hours', 24],
      [48, 'Last 3 days', 72],
      [100, 'Last week', 168],
      [200, 'Last 2 weeks', 336],
      [500, 'Last 30 days', 720],
    ])('fifth job at %sh: caption "%s", window %sh', (fifthHoursAgo, label, hours) => {
      const jobs = [
        ...latestFillers(4),
        stubJob('ramp', fifthHoursAgo, { id: 'fifth' }),
        stubJob('stripe', 900, { id: 'too-old' }),
      ];
      const slot = slotById(jobs, 'last_24h');
      expect(slot.label).toBe(label);
      expect(slot.windowHours).toBe(hours);
      expect(slot.jobs).toHaveLength(JOBS_PER_SLOT);
      expect(ids(slot.jobs)).toContain('fifth');
    });

    it.each(LATEST_WINDOWS.map((w, i) => [w.label, i] as const))(
      'boundary of "%s" is inclusive and one millisecond past it widens',
      (_label, i) => {
        const step = LATEST_WINDOWS[i];
        const onBoundary = slotById(
          [...latestFillers(4), stubJobAt('ramp', step.hours * HOUR, { id: 'edge' })],
          'last_24h'
        );
        expect(onBoundary.label).toBe(step.label);
        expect(ids(onBoundary.jobs)).toContain('edge');

        const justPast = slotById(
          [...latestFillers(4), stubJobAt('ramp', step.hours * HOUR + 1, { id: 'edge' })],
          'last_24h'
        );
        const next = LATEST_WINDOWS[i + 1];
        if (next) {
          expect(justPast.label).toBe(next.label);
          expect(ids(justPast.jobs)).toContain('edge');
        } else {
          expect(justPast.label).toBe(step.label);
          expect(ids(justPast.jobs)).not.toContain('edge');
          expect(justPast.jobs).toHaveLength(4);
        }
      }
    );

    it('never reaches past 30 days, and shows what exists under the cap label', () => {
      const slot = slotById(
        [
          stubJob('ramp', 100, { id: 'a' }),
          stubJob('ramp', 600, { id: 'b' }),
          stubJob('ramp', 721),
        ],
        'last_24h'
      );
      expect(ids(slot.jobs)).toEqual(['a', 'b']);
      expect(slot.label).toBe('Last 30 days');
      expect(slot.windowHours).toBe(720);
    });

    it('empty at the cap says so for the cap window', () => {
      const slot = slotById([], 'last_24h');
      expect(slot.jobs).toHaveLength(0);
      expect(slot.label).toBe('Last 30 days');
      expect(slot.emptyText).toBe('None in the last 30 days.');
    });
  });

  describe('early-career and big-tech widening', () => {
    it.each([
      [100, 168],
      [200, 336],
      [500, 720],
      [1000, 1440],
    ])('early career: fifth job at %sh widens to %sh', (fifthHoursAgo, hours) => {
      const jobs = [
        ...[1, 2, 3, 4].map((h) => stubJob('stripe', h, { level: 'new_grad', id: `ng-${h}` })),
        stubJob('anthropic', fifthHoursAgo, { level: 'intern', id: 'fifth' }),
      ];
      const slot = slotById(jobs, 'early_career');
      expect(slot.windowHours).toBe(hours);
      expect(ids(slot.jobs)).toContain('fifth');
      expect(slot.label).toBe('Internships & new grad');
    });

    it.each([
      [100, 168],
      [200, 336],
      [500, 720],
      [1000, 1440],
    ])('big tech: fifth job at %sh widens to %sh', (fifthHoursAgo, hours) => {
      const jobs = [
        ...latestFillers(5),
        ...[1, 2, 3, 4].map((h) => stubJob('google', h, { id: `bt-${h}` })),
        stubJob('apple', fifthHoursAgo, { id: 'fifth' }),
      ];
      const slot = slotById(jobs, 'big_tech');
      expect(slot.windowHours).toBe(hours);
      expect(ids(slot.jobs)).toContain('fifth');
      expect(slot.label).toBe('Big tech');
    });

    it('both stop at 60 days, inclusive', () => {
      const edge = 1440 * HOUR;
      const jobs = [
        ...latestFillers(5),
        stubJobAt('stripe', edge, { level: 'new_grad', id: 'ng-edge' }),
        stubJobAt('stripe', edge + 1, { level: 'new_grad', id: 'ng-past' }),
        stubJobAt('google', edge, { id: 'bt-edge' }),
        stubJobAt('google', edge + 1, { id: 'bt-past' }),
      ];
      const [early, , big] = selectTriptychSlots(jobs, NOW);
      expect(ids(early.jobs)).toEqual(['ng-edge']);
      expect(ids(big.jobs)).toEqual(['bt-edge']);
      expect(early.windowHours).toBe(1440);
      expect(big.windowHours).toBe(1440);
    });

    it('empty at the cap says so for 60 days and keeps window text out of the labels', () => {
      const [early, , big] = selectTriptychSlots([], NOW);
      expect(early.emptyText).toBe('None in the last 60 days.');
      expect(big.emptyText).toBe('None in the last 60 days.');
      expect(early.label).toBe('Internships & new grad');
      expect(big.label).toBe('Big tech');
    });
  });

  describe('disjoint after widening', () => {
    it('holiday fixture: every slot widens and no job appears twice', () => {
      const [early, latest, big] = selectTriptychSlots(buildHolidayLandingJobs(NOW), NOW);
      expect(early.jobs).toHaveLength(2);
      expect(early.windowHours).toBe(1440);
      expect(latest.label).toBe('Last 3 days');
      expect(latest.jobs).toHaveLength(JOBS_PER_SLOT);
      expect(big.windowHours).toBe(720);
      expect(big.jobs).toHaveLength(JOBS_PER_SLOT);
      const all = [early, latest, big].flatMap((slot) => ids(slot.jobs));
      expect(new Set(all).size).toBe(all.length);
    });

    it('a widened later slot never takes an earlier claim', () => {
      const jobs = [
        stubJob('figma', 50, { level: 'intern', id: 'big-tech-intern' }),
        stubJob('ramp', 3, { level: 'new_grad', id: 'fresh-new-grad' }),
        stubJob('google', 400, { id: 'old-big-tech' }),
      ];
      const [early, latest, big] = selectTriptychSlots(jobs, NOW);
      expect(ids(early.jobs)).toEqual(['fresh-new-grad', 'big-tech-intern']);
      expect(ids(latest.jobs)).toEqual(['old-big-tech']);
      expect(big.jobs).toHaveLength(0);
    });
  });
});

describe('TRIPTYCH_REQUESTS', () => {
  it('asks for exactly what each slot needs at its cap', () => {
    const [early, latest, big] = TRIPTYCH_REQUESTS;
    expect(TRIPTYCH_REQUESTS).toHaveLength(3);
    expect(TRIPTYCH_REQUESTS.map((r) => r.limit)).toEqual([5, 10, 15]);
    expect(early.maxAgeHours).toBe(EARLY_CAREER_WINDOWS[EARLY_CAREER_WINDOWS.length - 1].hours);
    expect(latest.maxAgeHours).toBe(LATEST_WINDOWS[LATEST_WINDOWS.length - 1].hours);
    expect(big.maxAgeHours).toBe(BIG_TECH_WINDOWS[BIG_TECH_WINDOWS.length - 1].hours);
    expect(early.level).toEqual(['intern', 'new_grad']);
    expect(latest.level).toBeUndefined();
    expect(big.companies).toEqual([...BIG_TECH_IDS].sort());
    for (const request of TRIPTYCH_REQUESTS) {
      expect(request.category).toEqual([SOFTWARE_ENGINEERING]);
    }
  });

  it('selecting over the merged server answers equals selecting over the whole corpus', () => {
    const companies = [...BIG_TECH_IDS, ...NOT_BIG_TECH, 'cohere', 'xai', 'notion'];
    const levels = ['intern', 'new_grad', 'entry', 'mid', 'senior', null];
    const categories = [
      SOFTWARE_ENGINEERING,
      SOFTWARE_ENGINEERING,
      SOFTWARE_ENGINEERING,
      'product_manager',
      'data_scientist',
      null,
    ];
    const sizes = [0, 3, 8, 15, 40, 120];
    const spans = [30, 100, 400, 1500, 3000];
    let widened = 0;
    let filled = 0;

    for (let seed = 1; seed <= 200; seed += 1) {
      const rng = mulberry32(seed);
      const pick = <T>(values: readonly T[]): T => values[Math.floor(rng() * values.length)];
      const size = pick(sizes) + Math.floor(rng() * 5);
      const spanHours = pick(spans);
      const used = new Set<number>();
      const corpus: Job[] = [];
      for (let i = 0; i < size; i += 1) {
        let ageMs = Math.floor(rng() * spanHours * HOUR);
        while (used.has(ageMs)) ageMs += 1;
        used.add(ageMs);
        corpus.push(
          stubJobAt(pick(companies), ageMs, {
            id: `s${seed}-j${i}`,
            level: pick(levels),
            category: pick(categories),
          })
        );
      }

      const merged = [
        ...new Map(
          TRIPTYCH_REQUESTS.flatMap((request) => simulateBatchRequest(corpus, request, NOW)).map(
            (job) => [job.id, job]
          )
        ).values(),
      ];
      const expected: TriptychSlots = selectTriptychSlots(corpus, NOW);
      expect(selectTriptychSlots(merged, NOW), `seed ${seed}`).toEqual(expected);

      widened += expected.filter(
        (slot, i) =>
          slot.windowHours > [EARLY_CAREER_WINDOWS, LATEST_WINDOWS, BIG_TECH_WINDOWS][i][0].hours
      ).length;
      filled += expected.filter((slot) => slot.jobs.length === JOBS_PER_SLOT).length;
    }

    expect(widened).toBeGreaterThan(0);
    expect(filled).toBeGreaterThan(0);
  });
});
