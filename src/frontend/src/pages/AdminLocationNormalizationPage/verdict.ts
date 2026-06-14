import type { LocationHealth, IntegrityCheck } from '../../features/admin/adminApi';

/**
 * Pure verdict-derivation for the Location Normalization Monitor.
 *
 * The thresholds below mirror the runbook §6 table
 * (src/backend/docs/location-normalization-monitoring.md) and the CLI
 * (src/backend/api/eval/monitor_prod.py) — the same numbers expressed in three
 * places (TS can't share a constant with Python). Keep all three in sync when a
 * threshold changes. The module is intentionally free of React/MUI imports so
 * it is fully unit-testable in isolation and the page can derive its focal
 * "verdict banner" from a single trusted function rather than scattering
 * threshold checks across the UI.
 */

// ─── Thresholds (runbook §6) ─────────────────────────────────────────────────

/** Heartbeat age (minutes): above this is critical (or null heartbeat). */
export const HEARTBEAT_CRIT_MINUTES = 30;
/** Heartbeat age (minutes): above this is a warning. */
export const HEARTBEAT_WARN_MINUTES = 10;

/** NULL-aged backlog: above this is critical. */
export const NULL_AGED_CRIT = 2000;
/** NULL-aged backlog: above this is a warning. */
export const NULL_AGED_WARN = 500;

/** failedNonblankRatio (percentage 0..100): above this is critical. */
export const FAILED_RATIO_CRIT = 5;
/** failedNonblankRatio (percentage 0..100): above this is a warning. */
export const FAILED_RATIO_WARN = 2;

export type MetricSeverity = 'ok' | 'warn' | 'crit';

export type Verdict = 'HEALTHY' | 'DEGRADED' | 'DORMANT' | 'SETUP';
export type VerdictColor = 'success' | 'warning' | 'error' | 'info';

export interface VerdictResult {
  verdict: Verdict;
  color: VerdictColor;
  summary: string;
  metrics: {
    heartbeat: MetricSeverity;
    nullAged: MetricSeverity;
    failedRatio: MetricSeverity;
  };
  integrity: {
    critCount: number;
    warnCount: number;
  };
}

/** Maps a derived metric severity to a MUI palette color name. */
export function severityToMuiColor(s: MetricSeverity): VerdictColor {
  switch (s) {
    case 'crit':
      return 'error';
    case 'warn':
      return 'warning';
    case 'ok':
    default:
      return 'success';
  }
}

/** Maps an integrity-check severity to a MUI palette color name. */
export function integritySeverityToMuiColor(s: IntegrityCheck['severity']): VerdictColor {
  switch (s) {
    case 'crit':
      return 'error';
    case 'warn':
      return 'warning';
    case 'ok':
    default:
      return 'success';
  }
}

function heartbeatSeverity(heartbeatAgeMinutes: number | null): MetricSeverity {
  // Null heartbeat = worker never beat / heartbeat row missing → critical.
  if (heartbeatAgeMinutes === null) return 'crit';
  if (heartbeatAgeMinutes > HEARTBEAT_CRIT_MINUTES) return 'crit';
  if (heartbeatAgeMinutes > HEARTBEAT_WARN_MINUTES) return 'warn';
  return 'ok';
}

function nullAgedSeverity(nullAged: number): MetricSeverity {
  if (nullAged > NULL_AGED_CRIT) return 'crit';
  if (nullAged > NULL_AGED_WARN) return 'warn';
  return 'ok';
}

function failedRatioSeverity(failedNonblankRatio: number): MetricSeverity {
  if (failedNonblankRatio > FAILED_RATIO_CRIT) return 'crit';
  if (failedNonblankRatio > FAILED_RATIO_WARN) return 'warn';
  return 'ok';
}

/**
 * Derives the single headline verdict from a trusted health snapshot plus the
 * integrity invariants. Pure — no side effects, no clock reads.
 */
export function computeVerdict(health: LocationHealth, checks: IntegrityCheck[]): VerdictResult {
  const metrics = {
    heartbeat: heartbeatSeverity(health.heartbeatAgeMinutes),
    nullAged: nullAgedSeverity(health.nullAged),
    failedRatio: failedRatioSeverity(health.failedNonblankRatio),
  };

  const critCount = checks.filter((c) => c.severity === 'crit').length;
  const warnCount = checks.filter((c) => c.severity === 'warn').length;
  const integrity = { critCount, warnCount };

  const anyMetricCrit =
    metrics.heartbeat === 'crit' || metrics.nullAged === 'crit' || metrics.failedRatio === 'crit';
  const anyMetricWarn =
    metrics.heartbeat === 'warn' || metrics.nullAged === 'warn' || metrics.failedRatio === 'warn';

  // SETUP: key not configured and there's nothing to process yet. The feature
  // simply isn't wired up — not "broken".
  if (!health.keyConfigured && health.total === 0) {
    return {
      verdict: 'SETUP',
      color: 'info',
      summary: 'Normalization is not configured — no LLM key and no rows to process.',
      metrics,
      integrity,
    };
  }

  // DORMANT: trust the backend's authoritative dormancy inference (no LLM key +
  // a NULL backlog with nothing processed yet) rather than recomputing the
  // heuristic here — single source of truth, so the API and the UI can't
  // disagree. SETUP above already handled the empty-corpus case.
  if (health.dormant) {
    return {
      verdict: 'DORMANT',
      color: 'info',
      summary: `Normalization is dormant — ${health.nullBacklog.toLocaleString()} rows queued but no LLM key configured.`,
      metrics,
      integrity,
    };
  }

  // DEGRADED (critical): any integrity crit OR any metric crit.
  if (critCount > 0 || anyMetricCrit) {
    return {
      verdict: 'DEGRADED',
      color: 'error',
      summary: buildDegradedSummary(metrics, integrity),
      metrics,
      integrity,
    };
  }

  // DEGRADED (warning): any integrity warn OR any metric warn.
  if (warnCount > 0 || anyMetricWarn) {
    return {
      verdict: 'DEGRADED',
      color: 'warning',
      summary: buildDegradedSummary(metrics, integrity),
      metrics,
      integrity,
    };
  }

  return {
    verdict: 'HEALTHY',
    color: 'success',
    summary: 'Normalization is healthy — heartbeat fresh, backlog low, failures within tolerance.',
    metrics,
    integrity,
  };
}

function buildDegradedSummary(
  metrics: VerdictResult['metrics'],
  integrity: VerdictResult['integrity']
): string {
  const reasons: string[] = [];
  if (metrics.heartbeat !== 'ok') reasons.push('stale heartbeat');
  if (metrics.nullAged !== 'ok') reasons.push('aged NULL backlog');
  if (metrics.failedRatio !== 'ok') reasons.push('elevated failure ratio');
  if (integrity.critCount > 0)
    reasons.push(`${integrity.critCount} critical integrity issue${integrity.critCount === 1 ? '' : 's'}`);
  else if (integrity.warnCount > 0)
    reasons.push(`${integrity.warnCount} integrity warning${integrity.warnCount === 1 ? '' : 's'}`);

  if (reasons.length === 0) {
    return 'Normalization is degraded.';
  }
  return `Normalization is degraded — ${reasons.join(', ')}.`;
}
