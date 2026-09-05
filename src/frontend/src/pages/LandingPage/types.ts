/**
 * Shared types for the landing page.
 *
 * The props contract outlived the four-design workspace it was written for
 * (2026-09-03 consolidation): the shell still hands the scene its content and
 * its fixtures rather than letting the scene reach for them, which is what
 * keeps `?data=sparse` a one-line shell concern and keeps every claim sourced
 * from one config. Copy itself traces to docs/seo/positioning-brief.md — see
 * content.ts.
 */
import type { Job } from '../../types';
import type { LandingContent } from './content';

/** Props the landing scene receives from the shell. */
export interface LandingPrototypeProps {
  content: LandingContent;
  /** Mock jobs (rich or sparse fixture, per `?data=`). */
  jobs: Job[];
  /** True when the sparse ("weekend reality") fixture is active. */
  sparse: boolean;
  /**
   * The timestamp the fixtures were built against (MOCK_NOW). Threaded as a
   * prop so no component samples Date.now() during render (react-hooks/purity)
   * and so tests are deterministic.
   */
  now: number;
}
