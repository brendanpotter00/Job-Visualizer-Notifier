import { describe, it, expect } from 'vitest';
import {
  computeVerdict,
  severityToMuiColor,
  integritySeverityToMuiColor,
} from '../../../pages/AdminLocationNormalizationPage/verdict';
import type { LocationHealth, IntegrityCheck } from '../../../features/admin/adminApi';

// A "perfectly healthy" baseline. Individual tests override single fields to
// isolate a threshold or verdict branch.
function makeHealth(overrides: Partial<LocationHealth> = {}): LocationHealth {
  return {
    schemaPresent: true,
    windowHours: 24,
    nullBacklog: 0,
    nullAged: 0,
    done: 100,
    failed: 0,
    total: 1000,
    failedBlank: 0,
    failedNonblank: 0,
    failedNonblankRatio: 0,
    heartbeatAgeMinutes: 1,
    normalizeQueue: { todo: 0, doing: 0, succeeded: 100, failed: 0 },
    throughputInWindow: 100,
    keyConfigured: true,
    dormant: false,
    ...overrides,
  };
}

function check(severity: IntegrityCheck['severity'], count: number): IntegrityCheck {
  return { id: `chk-${severity}-${count}`, label: `${severity} check`, count, severity };
}

describe('computeVerdict', () => {
  it('returns HEALTHY (success) for a clean health snapshot with no integrity issues', () => {
    const result = computeVerdict(makeHealth(), []);
    expect(result.verdict).toBe('HEALTHY');
    expect(result.color).toBe('success');
    expect(result.metrics).toEqual({ heartbeat: 'ok', nullAged: 'ok', failedRatio: 'ok' });
    expect(result.integrity).toEqual({ critCount: 0, warnCount: 0 });
  });

  it('returns SETUP (info) when key is not configured and total is 0', () => {
    const result = computeVerdict(makeHealth({ keyConfigured: false, total: 0 }), []);
    expect(result.verdict).toBe('SETUP');
    expect(result.color).toBe('info');
  });

  it('does NOT return SETUP when key is missing but total > 0', () => {
    // total > 0 means there ARE rows — not a fresh "unconfigured" setup.
    const result = computeVerdict(
      makeHealth({ keyConfigured: false, total: 50, nullBacklog: 5, done: 10 }),
      []
    );
    expect(result.verdict).not.toBe('SETUP');
  });

  it('returns DORMANT (info) when key missing, backlog > 100, and done === 0', () => {
    const result = computeVerdict(
      makeHealth({ keyConfigured: false, total: 500, nullBacklog: 101, done: 0 }),
      []
    );
    expect(result.verdict).toBe('DORMANT');
    expect(result.color).toBe('info');
  });

  it('does NOT return DORMANT when backlog is exactly 100 (boundary)', () => {
    // Threshold is strictly greater-than 100.
    const result = computeVerdict(
      makeHealth({ keyConfigured: false, total: 500, nullBacklog: 100, done: 0 }),
      []
    );
    expect(result.verdict).not.toBe('DORMANT');
  });

  it('does NOT return DORMANT when done > 0 even if backlog is large', () => {
    const result = computeVerdict(
      makeHealth({ keyConfigured: false, total: 500, nullBacklog: 200, done: 5 }),
      []
    );
    expect(result.verdict).not.toBe('DORMANT');
  });

  it('returns DEGRADED (error) when an integrity check is crit', () => {
    const result = computeVerdict(makeHealth(), [check('crit', 3)]);
    expect(result.verdict).toBe('DEGRADED');
    expect(result.color).toBe('error');
    expect(result.integrity.critCount).toBe(1);
  });

  it('returns DEGRADED (warning) when an integrity check is warn but none crit', () => {
    const result = computeVerdict(makeHealth(), [check('warn', 2)]);
    expect(result.verdict).toBe('DEGRADED');
    expect(result.color).toBe('warning');
    expect(result.integrity.warnCount).toBe(1);
  });

  it('crit metric outranks warn integrity → error color', () => {
    const result = computeVerdict(makeHealth({ nullAged: 3000 }), [check('warn', 1)]);
    expect(result.verdict).toBe('DEGRADED');
    expect(result.color).toBe('error');
  });

  // ─── nullAged boundaries (warn > 500, crit > 2000) ─────────────────────────

  it('nullAged 500 is ok', () => {
    expect(computeVerdict(makeHealth({ nullAged: 500 }), []).metrics.nullAged).toBe('ok');
  });
  it('nullAged 501 is warn', () => {
    const r = computeVerdict(makeHealth({ nullAged: 501 }), []);
    expect(r.metrics.nullAged).toBe('warn');
    expect(r.verdict).toBe('DEGRADED');
    expect(r.color).toBe('warning');
  });
  it('nullAged 2000 is warn', () => {
    expect(computeVerdict(makeHealth({ nullAged: 2000 }), []).metrics.nullAged).toBe('warn');
  });
  it('nullAged 2001 is crit', () => {
    const r = computeVerdict(makeHealth({ nullAged: 2001 }), []);
    expect(r.metrics.nullAged).toBe('crit');
    expect(r.color).toBe('error');
  });

  // ─── failedNonblankRatio boundaries (warn > 2, crit > 5) ───────────────────

  it('failedNonblankRatio 2 is ok', () => {
    expect(computeVerdict(makeHealth({ failedNonblankRatio: 2 }), []).metrics.failedRatio).toBe(
      'ok'
    );
  });
  it('failedNonblankRatio 2.01 is warn', () => {
    expect(
      computeVerdict(makeHealth({ failedNonblankRatio: 2.01 }), []).metrics.failedRatio
    ).toBe('warn');
  });
  it('failedNonblankRatio 5 is warn', () => {
    expect(computeVerdict(makeHealth({ failedNonblankRatio: 5 }), []).metrics.failedRatio).toBe(
      'warn'
    );
  });
  it('failedNonblankRatio 5.01 is crit', () => {
    expect(
      computeVerdict(makeHealth({ failedNonblankRatio: 5.01 }), []).metrics.failedRatio
    ).toBe('crit');
  });

  // ─── heartbeat boundaries (warn > 10, crit > 30 or null) ───────────────────

  it('heartbeat 10 is ok', () => {
    expect(computeVerdict(makeHealth({ heartbeatAgeMinutes: 10 }), []).metrics.heartbeat).toBe(
      'ok'
    );
  });
  it('heartbeat 11 is warn', () => {
    expect(computeVerdict(makeHealth({ heartbeatAgeMinutes: 11 }), []).metrics.heartbeat).toBe(
      'warn'
    );
  });
  it('heartbeat 30 is warn', () => {
    expect(computeVerdict(makeHealth({ heartbeatAgeMinutes: 30 }), []).metrics.heartbeat).toBe(
      'warn'
    );
  });
  it('heartbeat 31 is crit', () => {
    const r = computeVerdict(makeHealth({ heartbeatAgeMinutes: 31 }), []);
    expect(r.metrics.heartbeat).toBe('crit');
    expect(r.color).toBe('error');
  });
  it('heartbeat null is crit', () => {
    const r = computeVerdict(makeHealth({ heartbeatAgeMinutes: null }), []);
    expect(r.metrics.heartbeat).toBe('crit');
    expect(r.verdict).toBe('DEGRADED');
    expect(r.color).toBe('error');
  });
});

describe('severityToMuiColor', () => {
  it('maps ok→success, warn→warning, crit→error', () => {
    expect(severityToMuiColor('ok')).toBe('success');
    expect(severityToMuiColor('warn')).toBe('warning');
    expect(severityToMuiColor('crit')).toBe('error');
  });
});

describe('integritySeverityToMuiColor', () => {
  it('maps ok→success, warn→warning, crit→error', () => {
    expect(integritySeverityToMuiColor('ok')).toBe('success');
    expect(integritySeverityToMuiColor('warn')).toBe('warning');
    expect(integritySeverityToMuiColor('crit')).toBe('error');
  });
});
