/**
 * Pure per-tier particle configuration for the Drift scene.
 *
 * Two layers create parallax depth: the JOBS layer encodes data (one dot per
 * job posted in the last 24h — the hero caption's claim) and the AMBIENT layer
 * sits further back, smaller and slower. Everything stays monochrome gray and
 * low-opacity: the field must read as ≤10% visual weight behind the copy.
 */

export interface SparklesLayerConfig {
  count: number;
  /** drei Sparkles point size scalar. */
  size: number;
  /** World-units box the layer fills, [x, y, z]. */
  scale: [number, number, number];
  speed: number;
  opacity: number;
}

export interface DriftParticlesConfig {
  /** Data layer: one dot per job posted in the last 24h. */
  jobs: SparklesLayerConfig;
  /** Ambience layer: farther, smaller, slower — the parallax backdrop. */
  ambient: SparklesLayerConfig;
}

/** Floor for the data layer so quiet weekends never look broken/empty. */
export const MIN_JOB_DOTS = 12;

const DAY_MS = 24 * 3_600_000;

/** Jobs first seen within the last 24h of `now` (pure; `now` injected). */
export function countJobsPostedToday(
  jobs: readonly { firstSeenAt: string }[],
  now: number
): number {
  const cutoff = now - DAY_MS;
  return jobs.filter((job) => new Date(job.firstSeenAt).getTime() >= cutoff).length;
}

export function buildParticlesConfig(input: {
  jobsPostedToday: number;
  /** Constrained (mobile/low-end) full tier: fewer, smaller ambient dots. */
  constrained: boolean;
}): DriftParticlesConfig {
  return {
    jobs: {
      count: Math.max(MIN_JOB_DOTS, input.jobsPostedToday),
      size: input.constrained ? 3.5 : 4.5,
      scale: [16, 9, 1],
      speed: 0.18,
      opacity: 0.32,
    },
    ambient: {
      count: input.constrained ? 40 : 80,
      size: 1.8,
      scale: [22, 12, 6],
      speed: 0.08,
      opacity: 0.18,
    },
  };
}
