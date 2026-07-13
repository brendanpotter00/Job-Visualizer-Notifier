import type { EnrichmentHealth } from '../../features/admin/adminApi';

/**
 * Pure verdict logic for the admin enrichment page (React-free, mirrors
 * AdminLocationNormalizationPage/verdict.ts). The pull model's whole point is
 * that JVN must NOTICE when the unmanaged laptop goes dark — the verdict
 * banner is that noticing, condensed to one word.
 *
 * Verdicts:
 *  - SETUP    schema not deployed yet (migration pending)
 *  - IDLE     kill switch off — the cloud-Haiku floor is the only pipeline
 *  - DARK     flag on, work available, but the laptop has stopped showing up
 *  - DEGRADED alive but unhealthy (error ticks, drift, stale claims, deep queue)
 *  - HEALTHY  alive and clean
 */

/** Laptop tick cadence (launchd StartInterval, seconds). */
export const EXPECTED_TICK_INTERVAL_S = 600;

/**
 * "Dark" threshold: no tick heard for 90 minutes.
 *
 * The `claude-code` fan-out engine ticks fast (well under the old 6×-cadence
 * 1h threshold), but the local `ollama`/`opencode` engines can spend
 * 1.5-2.5h in a single tick (classify-run/judge-run against a local GPU, no
 * fan-out). The job-enricher wrapper pushes a metrics snapshot after
 * classify-run and after judge-run (not just once at tick end) specifically
 * so a live mid-tick laptop keeps refreshing this — 90 minutes is a buffer
 * above the longest single stage-to-stage gap that produces, not the whole
 * tick length. A laptop that's actually gone quiet for 90+ minutes with no
 * stage completing is a real DARK, not a false alarm from a slow tick.
 */
export const DARK_TICK_AGE_S = 90 * 60;

/**
 * Fallback dark threshold when the enricher has never pushed metrics: no
 * enrichment WRITE for 2h while claimable work exists.
 */
export const DARK_WRITE_AGE_S = 2 * 3600;

/** Needs-human queue depth that flips the verdict to DEGRADED. */
export const NEEDS_HUMAN_WARN = 50;

export type EnrichmentVerdictKind = 'HEALTHY' | 'DEGRADED' | 'DARK' | 'IDLE' | 'SETUP';
export type VerdictColor = 'success' | 'warning' | 'error' | 'info';

export interface EnrichmentVerdict {
  verdict: EnrichmentVerdictKind;
  color: VerdictColor;
  summary: string;
  /** Individual observations feeding the verdict, worst first. */
  notes: string[];
}

export function computeEnrichmentVerdict(health: EnrichmentHealth): EnrichmentVerdict {
  if (!health.schemaPresent) {
    return {
      verdict: 'SETUP',
      color: 'info',
      summary: 'Enrichment schema not deployed — run the migration to begin.',
      notes: [],
    };
  }

  if (!health.enabled) {
    return {
      verdict: 'IDLE',
      color: 'info',
      summary:
        'External enrichment is off (kill switch). The cloud location pipeline remains the floor.',
      notes:
        health.staleClaims > 0
          ? [`${health.staleClaims} in-flight claims will auto-release after the TTL.`]
          : [],
    };
  }

  const workAvailable = health.eligibleUnenriched > 0;
  const tickIsFresh = health.lastTickAgeS !== null && health.lastTickAgeS <= DARK_TICK_AGE_S;
  const neverTicked = health.lastTickAgeS === null;
  const writesAreStale =
    health.lastEnrichedAgeS === null || health.lastEnrichedAgeS > DARK_WRITE_AGE_S;

  // DARK: work exists, and either the tick channel has gone quiet or (if the
  // enricher predates metrics-push) no writes are landing either.
  if (workAvailable && !tickIsFresh && (!neverTicked || writesAreStale)) {
    const lastHeard =
      health.lastTickAgeS !== null
        ? `last tick ${formatAge(health.lastTickAgeS)} ago`
        : health.lastEnrichedAgeS !== null
          ? `last write ${formatAge(health.lastEnrichedAgeS)} ago`
          : 'never heard from';
    return {
      verdict: 'DARK',
      color: 'error',
      summary: `Laptop enricher has gone dark (${lastHeard}) with ${health.eligibleUnenriched.toLocaleString()} claimable jobs waiting.`,
      notes: darkNotes(health),
    };
  }

  const notes: string[] = [];
  if (health.lastTickStatus === 'error') {
    notes.push('The most recent tick ended in error.');
  }
  if (health.errorTicksInWindow > 0) {
    notes.push(`${health.errorTicksInWindow} error tick(s) in the last ${health.windowHours}h.`);
  }
  if (health.lastTickDriftSuspected) {
    notes.push('Taxonomy drift suspected — the last tick had most facets nulled.');
  }
  if (health.staleClaims > 0) {
    notes.push(
      `${health.staleClaims} stale claim(s) past the ${health.claimTtlMinutes}m TTL (auto-reclaim on next poll).`
    );
  }
  if (health.needsHumanOpen > NEEDS_HUMAN_WARN) {
    notes.push(`Needs-human queue is deep (${health.needsHumanOpen} open rows).`);
  }
  if (notes.length > 0) {
    return {
      verdict: 'DEGRADED',
      color: 'warning',
      summary: notes[0],
      notes,
    };
  }

  const throughput = `${health.enrichedInWindow.toLocaleString()} enriched / ${health.windowHours}h`;
  const backlog = workAvailable
    ? `${health.eligibleUnenriched.toLocaleString()} claimable in backlog`
    : 'backlog drained';
  return {
    verdict: 'HEALTHY',
    color: 'success',
    summary: `Pipeline healthy — ${throughput}, ${backlog}.`,
    notes: [],
  };
}

function darkNotes(health: EnrichmentHealth): string[] {
  const notes: string[] = [];
  if (health.staleClaims > 0) {
    notes.push(`${health.staleClaims} claims stranded mid-flight (auto-reclaim after TTL).`);
  }
  if (health.needsHumanOpen > 0) {
    notes.push(`${health.needsHumanOpen} needs-human rows can still be triaged meanwhile.`);
  }
  return notes;
}

/** Compact humanized age: 90 -> "2m", 5400 -> "1.5h", 200000 -> "2.3d". */
export function formatAge(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1).replace(/\.0$/, '')}h`;
  return `${(seconds / 86400).toFixed(1).replace(/\.0$/, '')}d`;
}
