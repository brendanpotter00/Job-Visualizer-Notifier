import { describe, it, expect } from 'vitest';
import {
  atsLabel,
  boardLine,
  cardToggleId,
  formatEventDate,
  formatMonthYear,
  formatRunLine,
  formatShortDate,
  formatUsd,
  hostnameOf,
  jobBoardHref,
  joinWithAnd,
  leadersFromBrief,
  listWithMore,
  parseSort,
  researchGaps,
  roundLine,
  safeHttpUrl,
  scoreEmphasis,
  summarizeTally,
} from '../../../pages/AdminLaunchRadarPage/format';
import type { LaunchRadarAts } from '../../../features/admin/launchRadarTypes';

const ATS: LaunchRadarAts = {
  provider: 'ashby',
  boardToken: 'Raindrop',
  boardUrl: null,
  verified: true,
  jobCount: 9,
  checkedUrl: null,
};

describe('Launch Radar format helpers', () => {
  describe('formatShortDate / formatMonthYear', () => {
    it('formats in UTC so a date-only event never shifts a day', () => {
      expect(formatShortDate('2026-09-17')).toBe('Sep 17');
      expect(formatShortDate('2026-10-07T23:59:00Z')).toBe('Oct 7');
      expect(formatMonthYear('2026-09-17')).toBe('Sep 2026');
    });

    it('returns an empty string for null or junk', () => {
      expect(formatShortDate(null)).toBe('');
      expect(formatShortDate('not a date')).toBe('');
      expect(formatMonthYear(undefined)).toBe('');
    });
  });

  describe('formatEventDate', () => {
    it('shows a day as "Sep 17" and a month-only date as "Sep 2026", never as the 1st', () => {
      expect(formatEventDate('2026-09-17')).toBe('Sep 17');
      expect(formatEventDate('2026-09')).toBe('Sep 2026');
      expect(formatEventDate(null)).toBe('');
      expect(formatEventDate('soon')).toBe('');
    });
  });

  describe('provenance notes in issues', () => {
    const NOTE = 'leaders from the brief (FindAll found none); 2 company page(s) dropped';

    it('leaves the leaders-from-the-brief note out of the research gaps', () => {
      expect(researchGaps([NOTE])).toEqual([]);
      expect(researchGaps([NOTE, 'team tally failed: timeout'])).toEqual([
        'team tally failed: timeout',
      ]);
      expect(researchGaps(['no leaders confirmed'])).toEqual(['no leaders confirmed']);
    });

    it('tells when the leaders came from the company brief', () => {
      expect(leadersFromBrief([NOTE])).toBe(true);
      expect(leadersFromBrief(['leaders from the brief (FindAll found none)'])).toBe(true);
      expect(leadersFromBrief(['no leaders confirmed', 'brief failed: x'])).toBe(false);
      expect(leadersFromBrief([])).toBe(false);
    });
  });

  it('formatUsd shows two decimals', () => {
    expect(formatUsd(0.46)).toBe('$0.46');
    expect(formatUsd(5)).toBe('$5.00');
    expect(formatUsd(0.1349)).toBe('$0.13');
  });

  describe('formatRunLine', () => {
    const stats = {
      lastRun: {
        startedAt: '2026-10-07T01:31:00Z',
        endedAt: null,
        status: 'ok' as const,
        host: 'server-laptop',
      },
      spendUsd: 0.46,
      capUsd: 5,
    };

    it('names the run time in UTC, the host and the spend of the cap', () => {
      expect(formatRunLine(stats)).toBe(
        'Last run Oct 7 at 01:31 UTC on server-laptop. $0.46 of the $5.00 budget used.'
      );
    });

    it('flags a run that did not end ok and omits a missing host', () => {
      expect(
        formatRunLine({ ...stats, lastRun: { ...stats.lastRun, status: 'stopped', host: null } })
      ).toBe('Last run Oct 7 at 01:31 UTC (stopped). $0.46 of the $5.00 budget used.');
    });

    it('says "No runs yet." when there is no run', () => {
      expect(formatRunLine({ lastRun: null, spendUsd: 0, capUsd: 5 })).toBe(
        'No runs yet. $0.00 of the $5.00 budget used.'
      );
    });
  });

  it('atsLabel capitalizes every provider', () => {
    expect(atsLabel('greenhouse')).toBe('Greenhouse');
    expect(atsLabel('eightfold')).toBe('Eightfold');
    expect(atsLabel('none')).toBe('None');
  });

  describe('boardLine', () => {
    it('counts open jobs on a verified board (singular and plural)', () => {
      expect(boardLine(ATS)).toBe('Ashby board, 9 open jobs');
      expect(boardLine({ ...ATS, jobCount: 1 })).toBe('Ashby board, 1 open job');
      expect(boardLine({ ...ATS, jobCount: null })).toBe('Ashby board');
    });

    it('says "not verified" for an unverified provider and "No job board found" for none', () => {
      expect(boardLine({ ...ATS, provider: 'workday', verified: false })).toBe(
        'Workday board, not verified'
      );
      expect(boardLine({ ...ATS, provider: 'none', verified: false })).toBe('No job board found');
    });

    it('never mentions a PR', () => {
      for (const verified of [true, false]) {
        for (const provider of ['ashby', 'workday', 'other', 'none'] as const) {
          expect(boardLine({ ...ATS, provider, verified })).not.toMatch(/PR/);
        }
      }
    });
  });

  it('hostnameOf strips www. and rejects junk', () => {
    expect(hostnameOf('https://www.techcrunch.com/2026/x')).toBe('techcrunch.com');
    expect(hostnameOf('https://blog.raindrop.ai/a')).toBe('blog.raindrop.ai');
    expect(hostnameOf('nope')).toBeNull();
    expect(hostnameOf(null)).toBeNull();
  });

  it('jobBoardHref picks the first safe http(s) URL: the board, then the careers page', () => {
    const board = 'https://jobs.ashbyhq.com/Raindrop';
    const careers = 'https://raindrop.ai/careers';
    expect(jobBoardHref({ ...ATS, boardUrl: board }, careers)).toBe(board);
    expect(jobBoardHref({ ...ATS, boardUrl: null }, careers)).toBe(careers);
    expect(jobBoardHref({ ...ATS, boardUrl: 'javascript:alert(1)' }, careers)).toBe(careers);
    expect(
      jobBoardHref({ ...ATS, boardUrl: 'data:text/html,x' }, 'javascript:alert(1)')
    ).toBeNull();
    expect(jobBoardHref({ ...ATS, boardUrl: null }, null)).toBeNull();
  });

  it('safeHttpUrl lets only absolute http(s) URLs through', () => {
    expect(safeHttpUrl('https://www.globenewswire.com/news-release/2026/10/06/x.html')).toBe(
      'https://www.globenewswire.com/news-release/2026/10/06/x.html'
    );
    expect(safeHttpUrl('http://businesswire.com/a')).toBe('http://businesswire.com/a');
    expect(safeHttpUrl('HTTPS://Example.com/A')).toBe('https://example.com/A');
    expect(safeHttpUrl('javascript:alert(1)')).toBeNull();
    expect(safeHttpUrl(' javascript:alert(1)')).toBeNull();
    expect(safeHttpUrl('data:text/html,<b>x</b>')).toBeNull();
    expect(safeHttpUrl('ftp://example.com/a')).toBeNull();
    expect(safeHttpUrl('/relative/path')).toBeNull();
    expect(safeHttpUrl('nope')).toBeNull();
    expect(safeHttpUrl('')).toBeNull();
    expect(safeHttpUrl(null)).toBeNull();
    expect(safeHttpUrl(undefined)).toBeNull();
  });

  it('joinWithAnd and listWithMore build the card list style', () => {
    expect(joinWithAnd([])).toBe('');
    expect(joinWithAnd(['A'])).toBe('A');
    expect(joinWithAnd(['A', 'B'])).toBe('A and B');
    expect(joinWithAnd(['A', 'B', 'C'])).toBe('A, B and C');
    expect(listWithMore(['A', 'B', 'C', 'D', 'E'], 3)).toBe('A, B, C and 2 more');
    expect(listWithMore(['A', 'B'], 3)).toBe('A and B');
  });

  it('summarizeTally sorts by count and shows a count only above 1', () => {
    expect(
      summarizeTally(
        [
          { name: 'Twitter', count: 1 },
          { name: 'Amazon', count: 2 },
          { name: 'Ledgerline', count: 1 },
          { name: 'Zoho', count: 1 },
        ],
        2
      )
    ).toBe('Amazon (2), Twitter and 2 more');
  });

  describe('roundLine', () => {
    it('leads, then others capped at 3', () => {
      expect(
        roundLine({
          stage: 'Series A',
          amountUsd: '$35M',
          announcedAt: '2026-09-17',
          leadInvestors: ['CRV'],
          otherInvestors: ['Lightspeed', 'Y Combinator'],
        })
      ).toEqual({
        head: 'Series A $35M',
        tail: ', Sep 2026. Led by CRV, with Lightspeed and Y Combinator',
      });
    });

    it('lists investors alone when there is no lead and no date', () => {
      expect(
        roundLine({
          stage: 'Seed',
          amountUsd: '$15M',
          announcedAt: null,
          leadInvestors: [],
          otherInvestors: ['Lightspeed', 'Figma Ventures', 'Vercel Ventures', 'SV Angel'],
        })
      ).toEqual({
        head: 'Seed $15M',
        tail: '. Lightspeed, Figma Ventures, Vercel Ventures and 1 more',
      });
    });

    it('falls back to "Round" with no stage or amount', () => {
      expect(
        roundLine({
          stage: null,
          amountUsd: null,
          announcedAt: null,
          leadInvestors: [],
          otherInvestors: [],
        })
      ).toEqual({ head: 'Round', tail: '.' });
    });
  });

  describe('parseSort', () => {
    it.each(['announced', 'talent', 'vc', 'added'] as const)('reads %s', (key) => {
      expect(parseSort(key)).toBe(key);
    });

    it.each([null, '', 'bogus', 'TALENT', ' talent', 'posted_at DESC'])(
      'reads %j as the default (announced)',
      (raw) => {
        expect(parseSort(raw)).toBe('announced');
      }
    );
  });

  describe('scoreEmphasis', () => {
    it('strengthens the sorted score and mutes the other; other sorts leave both alone', () => {
      expect(scoreEmphasis('talent')).toEqual({ talent: 'strong', vc: 'muted' });
      expect(scoreEmphasis('vc')).toEqual({ talent: 'muted', vc: 'strong' });
      expect(scoreEmphasis('announced')).toEqual({ talent: 'normal', vc: 'normal' });
      expect(scoreEmphasis('added')).toEqual({ talent: 'normal', vc: 'normal' });
    });
  });

  it('cardToggleId is unique per card', () => {
    expect(cardToggleId(7)).toBe('radar-card-7-toggle');
    expect(cardToggleId(7)).not.toBe(cardToggleId(17));
  });
});
