/**
 * Shared types for the admin-gated landing-page prototypes.
 *
 * Every prototype tab implements the same props contract so the shell can
 * mount any of them interchangeably and copy edits flow from one content
 * config into all four designs. Copy itself traces to
 * docs/seo/positioning-brief.md — see content.ts.
 */
import type { Job } from '../../types';
import type { LandingContent } from './content';

/** Tab ids — also the `?proto=` URL values. */
export const PROTOTYPE_IDS = ['signal', 'board', 'gravity', 'drift'] as const;
export type PrototypeId = (typeof PROTOTYPE_IDS)[number];

export function isPrototypeId(value: string | null): value is PrototypeId {
  return value !== null && (PROTOTYPE_IDS as readonly string[]).includes(value);
}

/** Headline mock stats (mock-data era; wired to real data at promotion time). */
export interface LandingStats {
  /** Approximate open listings across the board ("29,500+"-style rendering). */
  totalOpenJobs: number;
  /** Derived from COMPANIES.length so it can never drift from the registry. */
  companiesTracked: number;
  /** The measured median from company post to on-site appearance. */
  medianMinutesToSurface: number;
}

/** Props every prototype tab receives from the shell. */
export interface LandingPrototypeProps {
  content: LandingContent;
  /** Mock jobs (rich or sparse fixture, per `?data=`). */
  jobs: Job[];
  stats: LandingStats;
  /** True when the sparse ("weekend reality") fixture is active. */
  sparse: boolean;
  /**
   * The timestamp the fixtures were built against (MOCK_NOW). Threaded as a
   * prop so no component samples Date.now() during render (react-hooks/purity)
   * and so tests are deterministic.
   */
  now: number;
}
