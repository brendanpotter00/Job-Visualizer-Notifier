import { describe, it, expect } from 'vitest';
import { rewriteCursorJobUrls } from '../../api/clients/cursorJobUrl';
import type { AshbyJobResponse } from '../../api/types';

function mkJob(
  overrides: Partial<AshbyJobResponse> & Pick<AshbyJobResponse, 'id' | 'title' | 'jobUrl' | 'location'>
): AshbyJobResponse {
  return {
    publishedAt: '2026-04-01T00:00:00Z',
    applyUrl: overrides.jobUrl + '/application',
    employmentType: 'FullTime',
    ...overrides,
  } as AshbyJobResponse;
}

describe('rewriteCursorJobUrls', () => {
  it('leaves non-Cursor boards untouched', () => {
    const jobs = [
      mkJob({
        id: 'a',
        title: 'Foo',
        location: 'Remote',
        jobUrl: 'https://jobs.ashbyhq.com/notion/abc',
      }),
    ];
    expect(rewriteCursorJobUrls(jobs)).toEqual(jobs);
  });

  it('rewrites unique titles to cursor.com/careers/<slugified-title>', () => {
    const jobs = [
      mkJob({
        id: 'a',
        title: 'Software Engineer, Core Services',
        location: 'San Francisco',
        jobUrl: 'https://jobs.ashbyhq.com/cursor/abc',
      }),
    ];
    const [out] = rewriteCursorJobUrls(jobs);
    expect(out.jobUrl).toBe(
      'https://cursor.com/careers/software-engineer-core-services'
    );
  });

  it('appends location when two postings share a title', () => {
    const jobs = [
      mkJob({
        id: 'a',
        title: 'Account Associate',
        location: 'San Francisco',
        jobUrl: 'https://jobs.ashbyhq.com/cursor/a',
      }),
      mkJob({
        id: 'b',
        title: 'Account Associate',
        location: 'New York',
        jobUrl: 'https://jobs.ashbyhq.com/cursor/b',
      }),
    ];
    const out = rewriteCursorJobUrls(jobs);
    expect(out.map((j) => j.jobUrl)).toEqual([
      'https://cursor.com/careers/account-associate-san-francisco',
      'https://cursor.com/careers/account-associate-new-york',
    ]);
  });

  it('returns empty array unchanged', () => {
    expect(rewriteCursorJobUrls([])).toEqual([]);
  });

  it('does not mutate the input array', () => {
    const original = [
      mkJob({
        id: 'a',
        title: 'Foo',
        location: 'SF',
        jobUrl: 'https://jobs.ashbyhq.com/cursor/abc',
      }),
    ];
    const originalUrl = original[0].jobUrl;
    rewriteCursorJobUrls(original);
    expect(original[0].jobUrl).toBe(originalUrl);
  });
});
