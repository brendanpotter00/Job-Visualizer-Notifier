import type {
  AdminCustomCompaniesResponse,
  AdminCustomCompanyAttemptRow,
  AdminCustomCompanyAttemptsResponse,
  AdminCustomCompanyRow,
  AdminCustomCompanyUserRow,
} from '../../../features/admin/adminApi';

/**
 * Shared wire fixtures for the Custom Companies admin page tests.
 *
 * Modelled on the real local dataset the page was designed against: three
 * boards (two live, one orphaned) and an attempts log dominated by boards the
 * user has since deleted — which is the common case, not the edge one.
 */

export function makeCompanyRow(
  overrides: Partial<AdminCustomCompanyRow> = {}
): AdminCustomCompanyRow {
  return {
    id: 'u-pxfm7e08i4',
    displayName: 'Atlassian',
    ats: 'discovered',
    boardToken: 'https://atlassian.com/company/careers/all-jobs',
    enabled: true,
    healthState: 'unverified',
    cadenceHours: 24,
    createdAt: '2026-08-25T03:00:00Z',
    lastSuccessAt: '2026-08-28T01:10:00Z',
    consecutiveFailures: 0,
    ownerUserId: 'user-1',
    ownerEmail: 'brendanpotter00@gmail.com',
    ownerDisplayName: 'Brendan',
    ownerCount: 1,
    transport: 'http_json',
    oracleKind: 'declared_total',
    scriptVersion: 1,
    lastHarvestAt: '2026-08-28T01:10:00Z',
    lastHarvestAgeS: 3060,
    verdict: 'UNVERIFIED',
    verdictReason: 'no_oracle',
    recordsHarvested: 232,
    declaredTotal: 232,
    oracleTotal: null,
    capHit: false,
    liveStatus: 'live',
    liveReason: null,
    ...overrides,
  };
}

export const ORPHAN_COMPANY = makeCompanyRow({
  id: 'u-6hkpc6fh0z',
  displayName: 'Amazon (live check)',
  ownerUserId: null,
  ownerEmail: null,
  ownerDisplayName: null,
  ownerCount: 0,
  recordsHarvested: 11040,
  declaredTotal: null,
  capHit: true,
  lastHarvestAt: '2026-08-27T08:15:00Z',
  lastHarvestAgeS: 61200,
  liveStatus: 'orphan',
  liveReason: 'no owner row',
});

export function makeCompaniesResponse(
  overrides: Partial<AdminCustomCompaniesResponse> = {}
): AdminCustomCompaniesResponse {
  const companies = overrides.companies ?? [makeCompanyRow(), ORPHAN_COMPANY];
  return {
    companies,
    total: companies.length,
    summary: {
      trackedCount: 3,
      liveCount: 2,
      byLiveStatus: { live: 2, orphan: 1 },
      byHealthState: { unverified: 3 },
      attemptCount: 26,
      userCount: 1,
      failedCount: 8,
      refusedCount: 4,
      stuckCount: 4,
      ...overrides.summary,
    },
    schemaPresent: true,
    ...overrides,
  };
}

export function makeAttemptRow(
  overrides: Partial<AdminCustomCompanyAttemptRow> = {}
): AdminCustomCompanyAttemptRow {
  return {
    id: 57,
    attemptKey: 'u-pxfm7e08i4',
    createdAt: '2026-08-28T01:10:00Z',
    firstSeenAt: '2026-08-28T01:09:47Z',
    auditRowCount: 2,
    decidedInS: 13,
    userId: 'user-1',
    userEmail: 'brendanpotter00@gmail.com',
    userDisplayName: null,
    submittedUrl: 'https://atlassian.com/company/careers/all-jobs',
    normalizedUrl: 'https://atlassian.com/company/careers/all-jobs',
    resolvedAts: 'discovered',
    boardToken: 'https://atlassian.com/company/careers/all-jobs',
    outcome: 'added',
    rawOutcome: 'added',
    errorDetail: null,
    failedStep: null,
    failureReason: null,
    companyId: 'u-pxfm7e08i4',
    companyExists: true,
    companyDisplayName: 'Atlassian',
    companyVisibility: 'user',
    companyHealthState: 'unverified',
    companyLiveStatus: 'live',
    discoverySteps: [
      { key: 'open_page', status: 'done', result: 'recorded 9 JSON request(s)' },
      { key: 'find_feed', status: 'done', result: 'found 1 candidate feed' },
      { key: 'verify_read', status: 'done', result: 'read 232 jobs' },
      { key: 'ready', status: 'done', result: null },
      { key: 'first_scan', status: 'done', result: null },
    ],
    ...overrides,
  };
}

/** The common case: the board was added, then deleted, so nothing survives but the URL. */
export const DELETED_BOARD_ATTEMPT = makeAttemptRow({
  id: 41,
  attemptKey: 'attempt#41',
  createdAt: '2026-08-25T03:13:53Z',
  firstSeenAt: '2026-08-25T03:13:09Z',
  decidedInS: 44,
  submittedUrl: 'https://jobs.sequoiacap.com/jobs/vanta',
  normalizedUrl: 'https://jobs.sequoiacap.com/jobs/vanta',
  outcome: 'refused',
  rawOutcome: 'refused',
  errorDetail: 'Building web scraper: HTTP 412 from the in-browser fetch on page 0',
  failedStep: 'Building web scraper',
  failureReason: 'HTTP 412 from the in-browser fetch on page 0',
  companyId: 'u-fsdpg7vebq',
  companyExists: false,
  companyDisplayName: null,
  companyVisibility: null,
  companyHealthState: null,
  companyLiveStatus: null,
  discoverySteps: null,
});

export function makeUserRow(
  overrides: Partial<AdminCustomCompanyUserRow> = {}
): AdminCustomCompanyUserRow {
  return {
    userId: 'user-1',
    email: 'brendanpotter00@gmail.com',
    displayName: 'Brendan',
    attempts: 26,
    added: 17,
    refused: 4,
    stuck: 4,
    pending: 0,
    alreadyPublic: 1,
    otherFailed: 0,
    ownsNow: 2,
    firstAttemptAt: '2026-08-20T10:00:00Z',
    lastAttemptAt: '2026-08-28T01:10:00Z',
    ...overrides,
  };
}

export function makeAttemptsResponse(
  overrides: Partial<AdminCustomCompanyAttemptsResponse> = {}
): AdminCustomCompanyAttemptsResponse {
  const attempts = overrides.attempts ?? [makeAttemptRow(), DELETED_BOARD_ATTEMPT];
  return {
    attempts,
    total: attempts.length,
    byOutcome: { added: 17, already_public: 1, refused: 4, stuck: 4 },
    users: [makeUserRow()],
    usersTruncated: false,
    schemaPresent: true,
    ...overrides,
  };
}
