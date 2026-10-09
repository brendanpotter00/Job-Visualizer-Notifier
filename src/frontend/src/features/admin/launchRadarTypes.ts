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
 * every tab: highest Talent score (the default), highest VC score, newest
 * added. Unscored cards sort last; ties go to the newest announcement. The API
 * also accepts `announced` (newest announcement), which the page no longer offers.
 */
export type LaunchRadarSort = 'talent' | 'vc' | 'added';

/** Every sort key, in the order the page offers them. */
export const LAUNCH_RADAR_SORTS: readonly LaunchRadarSort[] = ['talent', 'vc', 'added'];

export const DEFAULT_LAUNCH_RADAR_SORT: LaunchRadarSort = 'talent';

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

/**
 * Which halves of the Talent blend `talent` stands on: both summed, or one
 * doubled because the other had no data.
 */
export type LaunchRadarTalentBasis = 'leaders' | 'team' | 'both';

/** Every Talent basis. The list response is checked against it. */
export const LAUNCH_RADAR_TALENT_BASES: readonly LaunchRadarTalentBasis[] = [
  'leaders',
  'team',
  'both',
];

/**
 * An AI Talent grade (CONTRACT §6.6.1): a Claude subagent read the card's people
 * data against a fixed rubric. The four parts add up to `score` (the backend
 * guarantees it): leaders 0-40, industry fit 0-25, team density for its size
 * 0-25, track record 0-10.
 */
export interface LaunchRadarTalentAi {
  score: number;
  parts: { leaders: number; industry: number; team: number; trackRecord: number };
  confidence: 'high' | 'medium' | 'low';
  /** The industry the grader judged the people against, in a few words. */
  industry: string;
  reasons: string[];
  rubricVersion: string;
  gradedAt: string;
}

/**
 * A card's scores. With an AI grade (`talentAi`), `talent` IS the grade and
 * the rule-based blend below adds up to `talentRules` instead. Both fields are
 * absent on an ungraded card (and from a backend that predates the grade).
 *
 * Without a grade, Talent is a 50/50 blend: up to 50 from the leaders
 * (`talentLeaders`, explained by `talentReasons`) plus up to 50 from the rest of
 * the team's tally (`talentTeam`, explained by `talentTeamReasons`). A part with
 * no data is `null` and the other is doubled (`talentBasis` says which). The
 * backend guarantees the parts add up to `talent`.
 *
 * `talentBasis: null` with a number in `talent` is a LEGACY card, scored before
 * the blend: `talent` is the leaders' raw rubric score and there are no parts.
 * Read the basis with `== null`, so a backend that predates the blend (the field
 * absent) reads as legacy too.
 */
export interface LaunchRadarScores {
  talent: number | null;
  vc: number | null;
  talentReasons: string[];
  vcReasons: string[];
  talentLeaders: number | null;
  talentTeam: number | null;
  talentBasis: LaunchRadarTalentBasis | null;
  talentTeamReasons: string[];
  talentRules?: number | null;
  talentAi?: LaunchRadarTalentAi | null;
}

/**
 * One Parallel citation behind a card's research (CONTRACT §2.4). `field` is the
 * output field it supports: a brief field (`latest_round`), a pedigree field,
 * or the FindAll match condition, sometimes indexed (`prior_rounds.0`). At most
 * 40 per card, deduplicated by URL in the loop.
 */
export interface LaunchRadarSource {
  url: string;
  title: string | null;
  field: string | null;
}

export interface LaunchRadarCard {
  id: number;
  /** Deleted rows never reach the client. */
  status: LaunchRadarStatus;
  trackedCompanyId: string | null;
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
  scores: LaunchRadarScores;
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
  sources: LaunchRadarSource[];
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

/**
 * One tab's page. The backend also sends `stats` (last run, spend, cap); the
 * page no longer shows them, so the client neither types nor checks that field.
 */
export interface LaunchRadarCardsResponse {
  cards: LaunchRadarCard[];
  total: number;
  /** Every tab's count, whatever tab was requested. */
  counts: Record<LaunchRadarStatus, number>;
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
