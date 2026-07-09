import { describe, it, expect } from 'vitest';
import {
  computeEnrichmentVerdict,
  formatAge,
  DARK_TICK_AGE_S,
  NEEDS_HUMAN_WARN,
} from '../../../pages/AdminEnrichmentPage/verdict';
import type { EnrichmentHealth } from '../../../features/admin/adminApi';

function makeHealth(overrides: Partial<EnrichmentHealth> = {}): EnrichmentHealth {
  return {
    schemaPresent: true,
    enabled: true,
    openByStatus: { unenriched: 100, done: 50 },
    eligibleUnenriched: 80,
    staleClaims: 0,
    claimTtlMinutes: 240,
    needsHumanOpen: 3,
    humanCorrectedTotal: 1,
    lastEnrichedAt: new Date().toISOString(),
    lastEnrichedAgeS: 120,
    lastTickUuid: 't-1',
    lastTickStatus: 'ok',
    lastTickStartedAt: new Date().toISOString(),
    lastTickAgeS: 300,
    lastTickDriftSuspected: false,
    windowHours: 24,
    enrichedInWindow: 200,
    errorTicksInWindow: 0,
    ...overrides,
  };
}

describe('computeEnrichmentVerdict', () => {
  it('SETUP when the schema is absent', () => {
    const v = computeEnrichmentVerdict(makeHealth({ schemaPresent: false }));
    expect(v.verdict).toBe('SETUP');
    expect(v.color).toBe('info');
  });

  it('IDLE when the kill switch is off, regardless of backlog', () => {
    const v = computeEnrichmentVerdict(makeHealth({ enabled: false, eligibleUnenriched: 5000 }));
    expect(v.verdict).toBe('IDLE');
  });

  it('IDLE mentions in-flight claims draining after TTL', () => {
    const v = computeEnrichmentVerdict(makeHealth({ enabled: false, staleClaims: 7 }));
    expect(v.notes.join(' ')).toContain('7');
  });

  it('HEALTHY when ticks are fresh and nothing is wrong', () => {
    const v = computeEnrichmentVerdict(makeHealth());
    expect(v.verdict).toBe('HEALTHY');
    expect(v.color).toBe('success');
  });

  it('DARK when work exists but ticks have gone quiet', () => {
    const v = computeEnrichmentVerdict(
      makeHealth({ lastTickAgeS: DARK_TICK_AGE_S + 60, lastEnrichedAgeS: DARK_TICK_AGE_S + 60 })
    );
    expect(v.verdict).toBe('DARK');
    expect(v.color).toBe('error');
  });

  it('DARK when metrics were never pushed AND writes are stale', () => {
    const v = computeEnrichmentVerdict(
      makeHealth({ lastTickAgeS: null, lastTickUuid: null, lastEnrichedAgeS: 3 * 3600 })
    );
    expect(v.verdict).toBe('DARK');
  });

  it('NOT dark when metrics were never pushed but writes are landing (pre-metrics enricher)', () => {
    const v = computeEnrichmentVerdict(
      makeHealth({ lastTickAgeS: null, lastTickUuid: null, lastEnrichedAgeS: 300 })
    );
    expect(v.verdict).toBe('HEALTHY');
  });

  it('NOT dark when the backlog is drained, even with old ticks', () => {
    const v = computeEnrichmentVerdict(
      makeHealth({ eligibleUnenriched: 0, lastTickAgeS: DARK_TICK_AGE_S * 4 })
    );
    expect(v.verdict).toBe('HEALTHY');
  });

  it.each([
    ['error tick', { lastTickStatus: 'error' as const }],
    ['error ticks in window', { errorTicksInWindow: 2 }],
    ['drift suspected', { lastTickDriftSuspected: true }],
    ['stale claims', { staleClaims: 4 }],
    ['deep needs-human queue', { needsHumanOpen: NEEDS_HUMAN_WARN + 1 }],
  ])('DEGRADED on %s', (_label, overrides) => {
    const v = computeEnrichmentVerdict(makeHealth(overrides));
    expect(v.verdict).toBe('DEGRADED');
    expect(v.color).toBe('warning');
    expect(v.notes.length).toBeGreaterThan(0);
  });
});

describe('formatAge', () => {
  it('formats seconds, minutes, hours, days', () => {
    expect(formatAge(45)).toBe('45s');
    expect(formatAge(180)).toBe('3m');
    expect(formatAge(5400)).toBe('1.5h');
    expect(formatAge(2 * 86400)).toBe('2d');
  });
});
