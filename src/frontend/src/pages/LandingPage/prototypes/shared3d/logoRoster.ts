/**
 * Deterministic company-logo roster for the 3D scenes and their DOM fallbacks.
 *
 * Pure: for a given (companies, count, seed) the roster is always identical, so
 * physics spawns, fallback grids, and tests all agree on which logos appear and
 * in what order. Household names (TOP_COMPANY_IDS) lead — they are the
 * recognizable proof the hero pile exists to deliver — then the rest of the
 * registry fills the remaining slots. Both partitions are seeded-shuffled so
 * the pile doesn't mirror registry ordering.
 */
import { getCompanyLogoUrl } from '../../../../config/companies';
import { TOP_COMPANY_IDS } from '../../content';
import { mulberry32 } from './mulberry32';

export interface LogoRosterEntry {
  companyId: string;
  logoUrl: string;
}

function seededShuffle<T>(items: readonly T[], random: () => number): T[] {
  const out = [...items];
  for (let i = out.length - 1; i > 0; i -= 1) {
    const j = Math.floor(random() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

export function selectLogoRoster(
  companies: readonly { id: string }[],
  count: number,
  seed: number
): LogoRosterEntry[] {
  const random = mulberry32(seed);
  // Set dedupes while preserving first-seen order, keeping the shuffle stable
  // even if the input ever carries a duplicated id.
  const available = new Set(companies.map((company) => company.id));
  const top = TOP_COMPANY_IDS.filter((id) => available.has(id));
  const topSet = new Set(top);
  const rest = [...available].filter((id) => !topSet.has(id));
  const ordered = [...seededShuffle(top, random), ...seededShuffle(rest, random)];
  return ordered.slice(0, Math.max(0, count)).map((companyId) => ({
    companyId,
    logoUrl: getCompanyLogoUrl(companyId),
  }));
}
