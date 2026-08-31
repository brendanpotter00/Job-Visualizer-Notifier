import type { UserCompany } from '../../features/userCompanies/userCompaniesApi';

/** MUI `Chip` color slots we map health states onto. */
type ChipColor = 'default' | 'info' | 'success' | 'warning' | 'error';

export interface HealthBadge {
  label: string;
  color: ChipColor;
}

/**
 * Pure mapping from a company's `healthState` to a user-facing badge.
 *
 * Kept dependency-free so the whole matrix is testable without a store or a
 * render. `healthState` is a bare `str` on the wire (backend-owned), so an
 * unknown value must still produce a non-empty, non-alarming label rather than
 * a blank chip — the `default` branch echoes the raw code so a screenshot stays
 * diagnosable.
 *
 * Phase-1 note: every company is `unverified` (no oracle exists yet), so its
 * copy deliberately reads as steady progress — "building history" — not as an
 * error. The trend page still renders; nothing about `unverified` is broken.
 */
export function describeHealthState(healthState: string): HealthBadge {
  switch (healthState) {
    case 'unverified':
      return { label: 'Tracking — building history', color: 'info' };
    case 'healthy':
      return { label: 'Healthy', color: 'success' };
    case 'quarantined':
      return { label: 'Paused — needs a look', color: 'warning' };
    case 'refused':
      return { label: 'Not trackable', color: 'error' };
    default:
      // Unknown/newer code: surface it verbatim rather than blanking the chip.
      return { label: healthState || 'Unknown', color: 'default' };
  }
}

/**
 * "Last checked" copy for a company row. Null (never harvested) is a normal
 * pre-first-run state, not an error — say so plainly.
 */
export function describeLastChecked(company: Pick<UserCompany, 'lastSuccessAt'>): string {
  if (!company.lastSuccessAt) {
    return 'Not yet checked';
  }
  const when = new Date(company.lastSuccessAt);
  if (Number.isNaN(when.getTime())) {
    return 'Not yet checked';
  }
  return `Last checked ${when.toLocaleString()}`;
}
