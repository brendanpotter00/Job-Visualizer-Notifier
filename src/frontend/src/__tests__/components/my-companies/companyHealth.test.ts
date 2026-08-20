import { describe, it, expect } from 'vitest';
import {
  DISCOVERY_STEP_LABELS,
  describeDiscoveryOutcome,
  describeDiscoveryStep,
  describeHealthState,
  describeLastChecked,
  failedDiscoveryStep,
  resolveDiscoveryOutcome,
  shouldShowDiscovery,
} from '../../../components/my-companies/companyHealth';
import type {
  DiscoveryProgress,
  DiscoveryStep,
  DiscoveryStepKey,
} from '../../../features/userCompanies/userCompaniesApi';

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

// ── discovery checklist helpers (E7 capture pivot) ─────────────────────────

function step(
  key: DiscoveryStepKey,
  status: DiscoveryStep['status'],
  result: string | null = null
): DiscoveryStep {
  return { key, status, result };
}

function progress(overrides: Partial<DiscoveryProgress> = {}): DiscoveryProgress {
  return {
    steps: [
      step('open_page', 'pending'),
      step('find_feed', 'pending'),
      step('verify_read', 'pending'),
      step('ready', 'pending'),
    ],
    outcome: 'running',
    liveViewUrl: null,
    updatedAt: null,
    jobPreview: [],
    ...overrides,
  };
}

describe('describeDiscoveryStep', () => {
  it('labels every step in the closed union', () => {
    const keys: DiscoveryStepKey[] = ['open_page', 'find_feed', 'verify_read', 'ready'];
    for (const key of keys) {
      expect(describeDiscoveryStep({ key })).toBe(DISCOVERY_STEP_LABELS[key]);
      expect(describeDiscoveryStep({ key })).not.toBe('');
    }
  });

  it('falls back to the raw key rather than an empty rung', () => {
    // The union is closed and the backend normalizes unknown keys away, but the value
    // still arrives as wire data — a blank row in a checklist someone is reading to
    // decide what to do next is the worst possible failure mode.
    expect(describeDiscoveryStep({ key: 'some_future_step' as DiscoveryStepKey })).toBe(
      'some_future_step'
    );
  });
});

describe('resolveDiscoveryOutcome', () => {
  it('reads a refused row as refused even when its blob still says "running"', () => {
    // The discovery TIMEOUT: no terminal checklist was written, so the last live
    // snapshot survives beside health_state='refused'. health_state wins.
    expect(
      resolveDiscoveryOutcome({ healthState: 'refused', discovery: progress() })
    ).toBe('refused');
  });

  it('reads a discovering row as running whatever the blob says', () => {
    expect(
      resolveDiscoveryOutcome({
        healthState: 'discovering',
        discovery: progress({ outcome: 'tracking' }),
      })
    ).toBe('running');
  });

  it('otherwise trusts the blob, defaulting to running when there is none', () => {
    expect(
      resolveDiscoveryOutcome({
        healthState: 'unverified',
        discovery: progress({ outcome: 'tracking' }),
      })
    ).toBe('tracking');
    expect(resolveDiscoveryOutcome({ healthState: 'healthy', discovery: null })).toBe(
      'running'
    );
  });
});

describe('shouldShowDiscovery', () => {
  const tracking = progress({ outcome: 'tracking' });

  it('shows the checklist while a board is being set up, and after a refusal', () => {
    expect(
      shouldShowDiscovery({
        healthState: 'discovering',
        discovery: progress(),
        lastSuccessAt: null,
      })
    ).toBe(true);
    expect(
      shouldShowDiscovery({ healthState: 'refused', discovery: progress(), lastSuccessAt: null })
    ).toBe(true);
  });

  it('keeps the success summary only until the first harvest lands', () => {
    // After that the row is an ordinary tracked company and a permanent setup receipt
    // is clutter — which also means nothing has to sweep the blob away server-side.
    expect(
      shouldShowDiscovery({
        healthState: 'unverified',
        discovery: tracking,
        lastSuccessAt: null,
      })
    ).toBe(true);
    expect(
      shouldShowDiscovery({
        healthState: 'unverified',
        discovery: tracking,
        lastSuccessAt: '2026-08-09T10:00:00Z',
      })
    ).toBe(false);
  });

  it('does not resurrect the receipt when a harvested board drops to zero open jobs', () => {
    // The bug an open-job count stands in for "no harvest yet": a board that genuinely
    // has no roles today would render a green "We can read X's board" over a "0 open
    // jobs" chip, linking to postings the harvest just proved gone. `lastSuccessAt` is
    // the real signal, and it does not go back to null.
    expect(
      shouldShowDiscovery({
        healthState: 'unverified',
        discovery: tracking,
        lastSuccessAt: '2026-06-01T00:00:00Z',
      })
    ).toBe(false);
  });

  it('never shows a success receipt on a row the backend has marked broken', () => {
    // "We can read Acme's board" directly under "Paused — needs a look" is the UI
    // contradicting the badge beside it. Same for a graduated (healthy) row.
    expect(
      shouldShowDiscovery({
        healthState: 'quarantined',
        discovery: tracking,
        lastSuccessAt: null,
      })
    ).toBe(false);
    expect(
      shouldShowDiscovery({ healthState: 'healthy', discovery: tracking, lastSuccessAt: null })
    ).toBe(false);
  });

  it('never shows anything for a company with no checklist (every ATS board)', () => {
    expect(
      shouldShowDiscovery({ healthState: 'discovering', discovery: null, lastSuccessAt: null })
    ).toBe(false);
  });
});

describe('describeDiscoveryOutcome', () => {
  const refused = progress({
    outcome: 'refused',
    steps: [
      step('open_page', 'done', 'opened acme.example — recorded 4 JSON request(s)'),
      step('find_feed', 'done', 'found 3 candidate feed(s)'),
      step('verify_read', 'failed', 'the replay returned a different list'),
      step('ready', 'pending'),
    ],
  });

  it('frames a refusal around the company, and chains the ✓/✕ across the steps', () => {
    const headline = describeDiscoveryOutcome({
      displayName: 'Acme',
      healthState: 'refused',
      discovery: refused,
      openJobCount: 0,
    });
    expect(headline.title).toBe("We couldn't read Acme's board");
    expect(headline.severity).toBe('error');
    expect(headline.summary).toBe(
      'Opening the careers page ✓ · Finding the jobs feed ✓ · Verifying we can read it ✕'
    );
  });

  it('leaves pending steps out of the summary', () => {
    const headline = describeDiscoveryOutcome({
      displayName: 'Acme',
      healthState: 'refused',
      discovery: refused,
      openJobCount: 0,
    });
    expect(headline.summary).not.toMatch(/ready to track/i);
  });

  it('frames success and in-progress distinctly', () => {
    expect(
      describeDiscoveryOutcome({
        displayName: 'Acme',
        healthState: 'unverified',
        discovery: progress({ outcome: 'tracking' }),
        openJobCount: 0,
      })
    ).toMatchObject({ title: "We can read Acme's board", severity: 'success' });
    expect(
      describeDiscoveryOutcome({
        displayName: 'Acme',
        healthState: 'discovering',
        discovery: progress(),
        openJobCount: 0,
      })
    ).toMatchObject({ title: 'Setting up Acme', severity: 'info' });
  });
});

describe('failedDiscoveryStep', () => {
  it('finds the one step a refusal stopped on', () => {
    const found = failedDiscoveryStep(
      progress({ steps: [step('open_page', 'done'), step('find_feed', 'failed', 'nope')] })
    );
    expect(found?.key).toBe('find_feed');
  });

  it('returns null when nothing failed — a timeout fails no step', () => {
    expect(failedDiscoveryStep(progress())).toBeNull();
    expect(failedDiscoveryStep(null)).toBeNull();
  });
});
