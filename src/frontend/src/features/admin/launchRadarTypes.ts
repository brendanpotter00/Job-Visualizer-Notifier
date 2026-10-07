// Launch Radar admin dashboard — wire types for `GET/PATCH/DELETE
// /api/admin/launch-radar/cards`. The backend serializes these camelCase from
// the snake_case payload the loop posts (docs/implementations/launch-radar/
// CONTRACT.md §2.4 / §5.2). Deleted (tombstoned) cards never reach the client,
// so `LaunchRadarStatus` has no 'deleted' member.

/**
 * The dashboard's three tabs; a card is in exactly one. Moves: new → saved
 * (Save), saved → new (Unsave), new or saved → archived (Archive), archived →
 * new (Restore). Any other move is a 409.
 */
export type LaunchRadarStatus = 'new' | 'saved' | 'archived';

/** Every live status, in tab order. The list response is checked against it. */
export const LAUNCH_RADAR_STATUSES: readonly LaunchRadarStatus[] = ['new', 'saved', 'archived'];

/**
 * The list's sort keys (`?sort=` on the API and in the page URL), the same for
 * every tab: newest announcement (the default), highest Talent score, highest
 * VC score, newest added. Unscored cards sort last; ties go to the newest
 * announcement.
 */
export type LaunchRadarSort = 'announced' | 'talent' | 'vc' | 'added';

/** Every sort key, in the order the page offers them. */
export const LAUNCH_RADAR_SORTS: readonly LaunchRadarSort[] = [
  'announced',
  'talent',
  'vc',
  'added',
];

export const DEFAULT_LAUNCH_RADAR_SORT: LaunchRadarSort = 'announced';

export type LaunchRadarAtsProvider =
  | 'greenhouse'
  | 'ashby'
  | 'lever'
  | 'gem'
  | 'workday'
  | 'eightfold'
  | 'other'
  | 'none';

export interface LaunchRadarRound {
  stage: string | null;
  amountUsd: string | null;
  announcedAt: string | null;
  leadInvestors: string[];
  otherInvestors: string[];
}

export interface LaunchRadarLeader {
  name: string;
  title: string | null;
  linkedinUrl: string | null;
  profileUrl: string | null;
  summary: string | null;
  schools: string[];
  priorCompanies: string[];
  foundedBefore: string[];
  yearsExperience: number | null;
  industryExperience: string | null;
  signals: string[];
}

export interface LaunchRadarTally {
  name: string;
  count: number;
}

export interface LaunchRadarEvent {
  type: 'funding' | 'launch' | 'other';
  headline: string;
  sourceUrl: string | null;
  /** `YYYY-MM-DD`, or `YYYY-MM` when only the month is known (the backend admits nothing else). */
  announcedAt: string | null;
  round: string | null;
  amountUsd: string | null;
  investors: string | null;
  origin: 'monitor' | 'findall_backfill' | 'task brief';
}

export interface LaunchRadarTeamStats {
  /** null = the team tally did not return a usable count (unknown, not zero). */
  profilesFound: number | null;
  teamSizeEstimate: string;
  schools: LaunchRadarTally[];
  priorEmployers: LaunchRadarTally[];
  /** null = unknown; only 0 means "no prior exits found". */
  exFoundersWithExit: number | null;
  sampleNames: string[];
}

export interface LaunchRadarAts {
  provider: LaunchRadarAtsProvider;
  boardToken: string | null;
  boardUrl: string | null;
  verified: boolean;
  jobCount: number | null;
  checkedUrl: string | null;
}

export interface LaunchRadarCard {
  id: number;
  /** Deleted rows never reach the client. */
  status: LaunchRadarStatus;
  trackedCompanyId: string | null;
  prUrl: string | null;
  postedAt: string;
  archivedAt: string | null;
  updatedBy: string | null;
  company: string;
  domain: string;
  website: string;
  oneLiner: string | null;
  whatTheyDo: string | null;
  blurb: string | null;
  event: LaunchRadarEvent | null;
  /** `null` score = no data (rendered as a dash), never 0. */
  scores: {
    talent: number | null;
    vc: number | null;
    talentReasons: string[];
    vcReasons: string[];
  };
  leaders: LaunchRadarLeader[];
  leadersDropped: number;
  teamStats: LaunchRadarTeamStats | null;
  funding: {
    latestRound: LaunchRadarRound | null;
    priorRounds: LaunchRadarRound[];
    totalRaisedUsd: string | null;
  };
  notableFacts: string[];
  careersUrl: string | null;
  ats: LaunchRadarAts;
  prReady: boolean;
  sources: { url: string; title: string | null; field: string | null }[];
  parallelRunIds: {
    findallId: string | null;
    briefRunId: string | null;
    teamRunId: string | null;
    pedigreeGroupId: string | null;
  };
  costUsd: number;
  timingsS: Record<string, number>;
  issues: string[];
  generatedAt: string;
}

export interface LaunchRadarLastRun {
  startedAt: string;
  endedAt: string | null;
  status: 'running' | 'ok' | 'stopped' | 'error';
  host: string | null;
}

export interface LaunchRadarStats {
  lastRun: LaunchRadarLastRun | null;
  spendUsd: number;
  capUsd: number;
}

export interface LaunchRadarCardsResponse {
  cards: LaunchRadarCard[];
  total: number;
  /** Every tab's count, whatever tab was requested. */
  counts: Record<LaunchRadarStatus, number>;
  stats: LaunchRadarStats;
}

/**
 * One Save / Unsave / Archive / Restore: the card, the tab it moves to, and the
 * tab it was in when clicked (`from`), which the backend checks before moving it.
 */
export interface LaunchRadarStatusMove {
  id: number;
  status: LaunchRadarStatus;
  from: LaunchRadarStatus;
}

export interface LaunchRadarCardsArgs {
  status: LaunchRadarStatus;
  page: number;
  rowsPerPage: number;
  /** Part of the cache key: each sort of each page is its own entry. */
  sort: LaunchRadarSort;
}
