import { describe, it, expect } from 'vitest';
import {
  describeHealthState,
  describeLastChecked,
} from '../../../components/my-companies/companyHealth';

describe('describeHealthState', () => {
  it('frames the provisional discovering state as "Setting up…", not an error', () => {
    const badge = describeHealthState('discovering');
    expect(badge.label).toMatch(/setting up/i);
    expect(badge.color).toBe('info');
  });

  it('frames the Phase-1 unverified state as steady progress, not an error', () => {
    const badge = describeHealthState('unverified');
    expect(badge.label).toMatch(/building history/i);
    expect(badge.color).toBe('info');
  });

  it('frames the Phase-2 healthy state as "Tracking — healthy" progress', () => {
    const badge = describeHealthState('healthy');
    expect(badge.label).toMatch(/tracking — healthy/i);
    expect(badge.color).toBe('success');
  });

  it('maps the other known states to distinct colors', () => {
    expect(describeHealthState('healthy').color).toBe('success');
    expect(describeHealthState('quarantined').color).toBe('warning');
    expect(describeHealthState('refused').color).toBe('error');
  });

  it('echoes an unknown/newer code verbatim rather than blanking the chip', () => {
    const badge = describeHealthState('some_future_state');
    expect(badge.label).toBe('some_future_state');
    expect(badge.color).toBe('default');
  });

  it('never returns an empty label, even for an empty string', () => {
    expect(describeHealthState('').label).not.toBe('');
  });
});

describe('describeLastChecked', () => {
  it('says "Not yet checked" before the first harvest (null)', () => {
    expect(describeLastChecked({ lastSuccessAt: null })).toBe('Not yet checked');
  });

  it('treats an unparseable timestamp as never-checked rather than "Invalid Date"', () => {
    expect(describeLastChecked({ lastSuccessAt: 'not-a-date' })).toBe('Not yet checked');
  });

  it('renders a "Last checked …" line for a real timestamp', () => {
    expect(describeLastChecked({ lastSuccessAt: '2026-08-09T10:00:00Z' })).toMatch(
      /^Last checked /
    );
  });
});
