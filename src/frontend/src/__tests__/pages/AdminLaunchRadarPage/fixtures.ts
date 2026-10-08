import type {
  LaunchRadarCard,
  LaunchRadarCardsResponse,
  LaunchRadarScores,
} from '../../../features/admin/launchRadarTypes';

/**
 * Scores with no Talent breakdown: a legacy card (scored before the 50/50
 * blend) when `talent` is a number, an unscored one when it is null.
 */
export function unblendedScores(
  scores: Pick<LaunchRadarScores, 'talent' | 'vc' | 'talentReasons' | 'vcReasons'>
): LaunchRadarScores {
  return {
    ...scores,
    talentLeaders: null,
    talentTeam: null,
    talentBasis: null,
    talentTeamReasons: [],
  };
}

/**
 * Cards shaped exactly like the backend's camelCase admin response
 * (CONTRACT.md §2.4 / §5.2), modelled on the plan's mock: Raindrop AI (full
 * data, already tracked), Ghost AI (no people data), Athennian
 * (archived, leaders without background, unverified board) and Kestrel (saved).
 */
export function makeRaindropCard(overrides: Partial<LaunchRadarCard> = {}): LaunchRadarCard {
  return {
    id: 1,
    status: 'new',
    trackedCompanyId: 'raindrop',
    postedAt: '2026-10-07T01:36:00Z',
    archivedAt: null,
    updatedBy: null,
    company: 'Raindrop AI',
    domain: 'raindrop.ai',
    website: 'https://www.raindrop.ai',
    oneLiner: 'Monitoring for AI agents',
    whatTheyDo: 'Observability for production AI agents.',
    blurb: 'Raindrop watches agents in production.',
    event: {
      type: 'funding',
      headline: 'Raindrop raises $35M Series A',
      sourceUrl: 'https://www.techcrunch.com/2026/09/17/raindrop-series-a/',
      announcedAt: '2026-09-17',
      round: 'Series A',
      amountUsd: '$35M',
      investors: 'CRV, Lightspeed',
      origin: 'monitor',
    },
    // Talent 49 = leaders 24 + team 25 (the team: 3 of the 6 profiles came from
    // Amazon or Twitter, half the profiles, so the full 25 employer points; no
    // top school, so 0 of the 25 school points).
    scores: {
      talent: 49,
      vc: 55,
      talentReasons: [
        'Priya Raman: top school (Berkeley)',
        'Priya Raman: prior exit (Ledgerline, acquired by Northwind)',
      ],
      vcReasons: ['CRV led (tier 2)', 'Lightspeed joined (tier 1)', 'round over $20M'],
      talentLeaders: 24,
      talentTeam: 25,
      talentBasis: 'both',
      talentTeamReasons: [
        'the 1 school listed across 6 profiles is not a top school',
        '3 of the 3 employers listed across 6 profiles are top employers (+25)',
      ],
    },
    leaders: [
      {
        name: 'Priya Raman',
        title: 'CEO',
        linkedinUrl: 'https://linkedin.com/in/example-priya-raman',
        profileUrl: null,
        summary: 'Berkeley CS. Co-founded Ledgerline, acquired by Northwind',
        schools: ['UC Berkeley BS CS'],
        priorCompanies: ['Ledgerline (Co-founder)'],
        foundedBefore: ['Ledgerline (acquired, acq. by Northwind, 2025)'],
        yearsExperience: 11,
        industryExperience: 'Crypto, AI infra',
        signals: [],
      },
      {
        name: 'Sam Rivera',
        title: 'CTO',
        linkedinUrl: null,
        profileUrl: 'https://example-sam-rivera.com',
        summary: 'WPI. Apple visionOS designer; interned at Google and SpaceX',
        schools: ['Worcester Polytechnic Institute BS Robotics'],
        priorCompanies: ['Apple (Designer)', 'Google (Intern)'],
        foundedBefore: [],
        yearsExperience: 8,
        industryExperience: null,
        signals: [],
      },
    ],
    leadersDropped: 0,
    teamStats: {
      profilesFound: 6,
      teamSizeEstimate: 'approximately 10-20',
      schools: [
        { name: 'UC Davis', count: 1 },
        { name: 'UCSB', count: 1 },
      ],
      priorEmployers: [
        { name: 'Twitter', count: 1 },
        { name: 'Amazon', count: 2 },
      ],
      sampleNames: ['Alex Moreno'],
    },
    funding: {
      latestRound: {
        stage: 'Series A',
        amountUsd: '$35M',
        announcedAt: '2026-09-17',
        leadInvestors: ['CRV'],
        otherInvestors: ['Lightspeed', 'Y Combinator'],
      },
      priorRounds: [
        {
          stage: 'Seed',
          amountUsd: '$15M',
          announcedAt: null,
          leadInvestors: [],
          otherInvestors: ['Lightspeed', 'Figma Ventures', 'Vercel Ventures', 'SV Angel'],
        },
      ],
      totalRaisedUsd: '$50M',
    },
    notableFacts: [
      'Team built fraud models at Robinhood',
      'Simulations replay production traffic',
      'Moved from startups to enterprises',
      'A fourth fact the card never shows',
    ],
    careersUrl: 'https://www.raindrop.ai/careers',
    ats: {
      provider: 'ashby',
      boardToken: 'Raindrop',
      boardUrl: 'https://jobs.ashbyhq.com/Raindrop',
      verified: true,
      jobCount: 9,
      checkedUrl: 'https://api.ashbyhq.com/posting-api/job-board/Raindrop',
    },
    sources: [{ url: 'https://www.raindrop.ai', title: 'Raindrop', field: 'one_liner' }],
    parallelRunIds: {
      findallId: 'findall_1',
      briefRunId: 'trun_1',
      teamRunId: 'trun_2',
      pedigreeGroupId: 'tgrp_1',
    },
    costUsd: 0.3,
    timingsS: { findall_s: 154 },
    issues: [],
    generatedAt: '2026-10-07T01:36:00Z',
    ...overrides,
  };
}

export function makeGhostCard(overrides: Partial<LaunchRadarCard> = {}): LaunchRadarCard {
  return makeRaindropCard({
    id: 2,
    trackedCompanyId: null,
    company: 'Ghost AI',
    domain: 'ghost.ai',
    website: 'https://ghost.ai',
    oneLiner: 'On-device personal AI computer',
    event: {
      type: 'funding',
      headline: 'Ghost AI raises $11M seed',
      sourceUrl: null,
      announcedAt: '2026-10-05',
      round: 'Seed',
      amountUsd: '$11M',
      investors: 'Andreessen Horowitz',
      origin: 'task brief',
    },
    scores: {
      talent: null,
      vc: 65,
      talentReasons: [],
      vcReasons: ['Andreessen Horowitz led (tier 1)'],
      talentLeaders: null,
      talentTeam: null,
      talentBasis: null,
      talentTeamReasons: ['no team tally on this card'],
    },
    leaders: [],
    leadersDropped: 3,
    teamStats: null,
    ats: {
      provider: 'ashby',
      boardToken: 'ghost',
      boardUrl: 'https://jobs.ashbyhq.com/ghost',
      verified: true,
      jobCount: 1,
      checkedUrl: null,
    },
    costUsd: 0.13,
    ...overrides,
  });
}

export function makeAthennianCard(overrides: Partial<LaunchRadarCard> = {}): LaunchRadarCard {
  return makeRaindropCard({
    id: 3,
    status: 'archived',
    trackedCompanyId: null,
    archivedAt: '2026-10-07T12:00:00Z',
    updatedBy: 'admin@example.com',
    company: 'Athennian',
    domain: 'athennian.com',
    website: 'https://athennian.com',
    oneLiner: 'Entity management for legal teams',
    event: {
      type: 'launch',
      headline: 'Athennian launches Athennian Intelligence',
      sourceUrl: 'https://athennian.com/news',
      announcedAt: '2026-10-06',
      round: null,
      amountUsd: null,
      investors: null,
      origin: 'monitor',
    },
    scores: unblendedScores({
      talent: null,
      vc: 20,
      talentReasons: [],
      vcReasons: ['round over $10M'],
    }),
    leaders: [
      {
        name: 'Robin Hart',
        title: 'COO',
        linkedinUrl: null,
        profileUrl: null,
        summary: null,
        schools: [],
        priorCompanies: [],
        foundedBefore: [],
        yearsExperience: null,
        industryExperience: null,
        signals: [],
      },
    ],
    teamStats: null,
    ats: {
      provider: 'other',
      boardToken: null,
      boardUrl: null,
      verified: false,
      jobCount: null,
      checkedUrl: null,
    },
    careersUrl: 'https://athennian.com/careers',
    ...overrides,
  });
}

export function makeKestrelCard(overrides: Partial<LaunchRadarCard> = {}): LaunchRadarCard {
  return makeRaindropCard({
    id: 4,
    status: 'saved',
    trackedCompanyId: null,
    updatedBy: 'admin@example.com',
    company: 'Kestrel Labs',
    domain: 'kestrel.dev',
    website: 'https://kestrel.dev',
    oneLiner: 'Evals for voice agents',
    ats: {
      provider: 'greenhouse',
      boardToken: 'kestrel',
      boardUrl: 'https://job-boards.greenhouse.io/kestrel',
      verified: true,
      jobCount: 4,
      checkedUrl: null,
    },
    careersUrl: 'https://kestrel.dev/careers',
    ...overrides,
  });
}

export function makeCardsResponse(
  overrides: Partial<LaunchRadarCardsResponse> = {}
): LaunchRadarCardsResponse {
  return {
    cards: [makeGhostCard(), makeRaindropCard()],
    total: 2,
    counts: { new: 2, saved: 1, archived: 1 },
    ...overrides,
  };
}
