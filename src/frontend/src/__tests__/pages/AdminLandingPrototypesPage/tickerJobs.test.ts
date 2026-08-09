import { describe, it, expect } from 'vitest';
import { selectTickerJobs } from '../../../pages/AdminLandingPrototypesPage/sections/tickerJobs';
import { buildMockJobs, buildSparseMockJobs } from '../../../pages/AdminLandingPrototypesPage/mockData';
import { TOP_COMPANY_IDS } from '../../../pages/AdminLandingPrototypesPage/content';
import type { Job } from '../../../types';

const NOW = new Date('2026-08-09T18:00:00Z').getTime();
const HOUR = 3_600_000;

function stubJob(company: string, hoursAgo: number, id = `${company}-${hoursAgo}`): Job {
  const firstSeenAt = new Date(NOW - hoursAgo * HOUR).toISOString();
  return {
    id,
    source: 'backend-scraper',
    company,
    title: `Engineer at ${company}`,
    createdAt: firstSeenAt,
    firstSeenAt,
    url: 'https://example.test',
    raw: null,
  };
}

describe('selectTickerJobs', () => {
  it('rich data → fresh mode: <48h top-company jobs, newest first, deduped by company', () => {
    const { items, mode } = selectTickerJobs(buildMockJobs(NOW), TOP_COMPANY_IDS, NOW, 10);
    expect(mode).toBe('fresh');
    expect(items.length).toBeGreaterThanOrEqual(6);
    const companies = items.map((j) => j.company);
    expect(new Set(companies).size).toBe(companies.length);
    for (let i = 1; i < items.length; i += 1) {
      expect(new Date(items[i - 1].firstSeenAt).getTime()).toBeGreaterThanOrEqual(
        new Date(items[i].firstSeenAt).getTime()
      );
    }
    for (const job of items) {
      expect(TOP_COMPANY_IDS).toContain(job.company);
      expect(NOW - new Date(job.firstSeenAt).getTime()).toBeLessThan(48 * HOUR);
    }
  });

  it('sparse data → widens to the 7-day pool across all companies (week mode)', () => {
    const { items, mode } = selectTickerJobs(buildSparseMockJobs(NOW), TOP_COMPANY_IDS, NOW, 10);
    expect(mode).toBe('week');
    expect(items.length).toBeGreaterThan(0);
  });

  it('caps at maxItems and dedupes multiple postings from one company', () => {
    const jobs = [
      stubJob('apple', 1, 'a1'),
      stubJob('apple', 2, 'a2'),
      stubJob('google', 3),
      stubJob('spacex', 4),
      stubJob('stripe', 5),
      stubJob('openai', 6),
      stubJob('anthropic', 7),
      stubJob('netflix', 8),
    ];
    const { items, mode } = selectTickerJobs(jobs, TOP_COMPANY_IDS, NOW, 4);
    expect(mode).toBe('fresh');
    expect(items).toHaveLength(4);
    expect(items[0].id).toBe('a1');
    expect(items.filter((j) => j.company === 'apple')).toHaveLength(1);
  });

  it('non-top companies never appear in fresh mode', () => {
    const jobs = [
      ...['apple', 'google', 'spacex', 'stripe', 'openai', 'anthropic'].map((c, i) =>
        stubJob(c, i + 1)
      ),
      stubJob('gigaml', 1),
    ];
    const { items, mode } = selectTickerJobs(jobs, TOP_COMPANY_IDS, NOW, 10);
    expect(mode).toBe('fresh');
    expect(items.map((j) => j.company)).not.toContain('gigaml');
  });
});
